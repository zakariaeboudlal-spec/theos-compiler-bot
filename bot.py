#!/usr/bin/env python3
import os
import shutil
import subprocess
import patoolib
import asyncio
import logging
import re
import threading
import time
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8683956903:AAHfM4eybz3oLKi-SWXr6TzsHzMRaoUwI-M")
# Use a path that is more likely to persist or at least be accessible
THEOS_PATH = os.getenv("THEOS", "/home/ubuntu/theos" if os.path.exists("/home/ubuntu") else "/opt/render/project/src/theos")
WORK_DIR = "/tmp/theos_builds"
MAX_CONCURRENT_BUILDS = int(os.getenv("MAX_CONCURRENT_BUILDS", "3"))
BUILD_TIMEOUT = int(os.getenv("BUILD_TIMEOUT", "900"))
RATE_LIMIT_MINUTES = int(os.getenv("RATE_LIMIT_MINUTES", "1"))
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "100"))
LOG_GROUP_ID = int(os.getenv("LOG_GROUP_ID", "0"))

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

os.makedirs(WORK_DIR, exist_ok=True)

# Global state
active_builds = 0
build_lock = asyncio.Lock()
user_last_build = defaultdict(lambda: datetime.min)
active_processes = {}

# --- Self-Healing Theos Setup ---
def ensure_theos_installed():
    """Checks if Theos is present, if not, installs a minimal version quickly."""
    if os.path.exists(os.path.join(THEOS_PATH, "makefiles", "tweak.mk")):
        return True
    
    logger.info("Theos not found or incomplete. Starting emergency installation...")
    try:
        os.makedirs(os.path.dirname(THEOS_PATH), exist_ok=True)
        # Clone minimal Theos
        subprocess.run(["git", "clone", "--depth", "1", "--recurse-submodules", "https://github.com/theos/theos.git", THEOS_PATH], check=True)
        
        # Download Toolchain (Sbingner)
        toolchain_path = os.path.join(THEOS_PATH, "toolchain")
        os.makedirs(toolchain_path, exist_ok=True)
        subprocess.run(["curl", "-L", "https://github.com/sbingner/llvm-project/releases/download/v10.0.0-1/linux-ios-arm64e-clang-toolchain.tar.lzma", "-o", "/tmp/toolchain.tar.lzma"], check=True)
        subprocess.run(["tar", "--lzma", "-xf", "/tmp/toolchain.tar.lzma", "-C", toolchain_path, "--strip-components=1"], check=True)
        
        # Download SDK 12.4
        sdks_path = os.path.join(THEOS_PATH, "sdks")
        os.makedirs(sdks_path, exist_ok=True)
        subprocess.run(["curl", "-L", "https://github.com/theos/sdks/raw/master/iPhoneOS12.4.sdk.tar.xz", "-o", "/tmp/sdk.tar.xz"], check=True)
        subprocess.run(["tar", "-xf", "/tmp/sdk.tar.xz", "-C", sdks_path], check=True)
        
        # Cleanup
        if os.path.exists("/tmp/toolchain.tar.lzma"): os.remove("/tmp/toolchain.tar.lzma")
        if os.path.exists("/tmp/sdk.tar.xz"): os.remove("/tmp/sdk.tar.xz")
        
        logger.info("Emergency Theos installation complete.")
        return True
    except Exception as e:
        logger.error(f"Failed to install Theos: {e}")
        return False

# --- Health Check Server ---
health_app = Flask(__name__)

@health_app.route('/health')
def health_check():
    status = "READY" if os.path.exists(os.path.join(THEOS_PATH, "makefiles", "tweak.mk")) else "SETUP_REQUIRED"
    return f"Status: {status}", 200

@health_app.route('/')
def index():
    return f"Theos Compiler Bot active. Path: {THEOS_PATH}", 200

def run_http_server():
    port = int(os.getenv("PORT", "10000"))
    health_app.run(host='0.0.0.0', port=port)

# --- Bot Logic ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    await update.message.reply_text(
        "🚀 *Theos Compiler Bot (Stable Edition)*\n\n"
        "أهلاً بك! سأقوم بتجميع مشاريعك باستخدام SDK 12.4.\n"
        "سأقوم بتصحيح أي أخطاء في مسارات Makefile تلقائياً.\n\n"
        "أرسل ملف المشروع الآن.",
        parse_mode='Markdown'
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global active_builds
    if update.effective_chat.type != 'private': return
    
    doc = update.message.document
    user_id = update.effective_user.id
    
    status_msg = await update.message.reply_text("🔍 Checking environment...", parse_mode='Markdown')
    
    # Ensure Theos is ready
    if not ensure_theos_installed():
        await status_msg.edit_text("❌ Critical Error: Theos environment could not be initialized. Please contact admin.")
        return

    async with build_lock:
        if active_builds >= MAX_CONCURRENT_BUILDS:
            await status_msg.edit_text("⏳ Server busy, try again in a moment.")
            return
        active_builds += 1
    
    user_last_build[user_id] = datetime.now()
    await status_msg.edit_text("📥 Downloading project...", parse_mode='Markdown')
    
    build_dir = os.path.join(WORK_DIR, f"build_{user_id}_{int(time.time())}")
    os.makedirs(build_dir, exist_ok=True)
    
    try:
        file = await context.bot.get_file(doc.file_id)
        archive_path = os.path.join(build_dir, doc.file_name)
        await file.download_to_drive(archive_path)
        
        extract_dir = os.path.join(build_dir, "project")
        os.makedirs(extract_dir)
        patoolib.extract_archive(archive_path, outdir=extract_dir)
        
        project_root = extract_dir
        for root, _, files in os.walk(extract_dir):
            if 'Makefile' in files:
                project_root = root
                break
        
        # Patch Makefile
        makefile_path = os.path.join(project_root, "Makefile")
        if os.path.exists(makefile_path):
            with open(makefile_path, 'r') as f: content = f.read()
            # Force THEOS path at the very beginning
            content = f"THEOS = {THEOS_PATH}\ninclude $(THEOS)/makefiles/common.mk\n" + content
            # Remove any conflicting definitions
            content = re.sub(r'THEOS\s*[:?]?=.*', '', content)
            content = re.sub(r'include\s+.*\/(common|tweak)\.mk', '', content)
            # Add back the correct tweak.mk include at the end if it's a tweak
            content += f"\ninclude $(THEOS)/makefiles/tweak.mk\n"
            with open(makefile_path, 'w') as f: f.write(content)

        env = os.environ.copy()
        env["THEOS"] = THEOS_PATH
        env["THEOS_MAKE_PATH"] = os.path.join(THEOS_PATH, "makefiles")
        env["PATH"] = f"{THEOS_PATH}/bin:{THEOS_PATH}/toolchain/bin:{env.get('PATH', '')}"
        
        await status_msg.edit_text("🔨 Compiling with SDK 12.4...")
        
        make_cmd = [
            "make", "package",
            f"THEOS={THEOS_PATH}",
            "TARGET=iphone:clang:12.4:12.0",
            "ADDITIONAL_CFLAGS=-fno-modules",
            "ADDITIONAL_OBJCFLAGS=-fno-modules",
            "FINALPACKAGE=1", "DEBUG=0"
        ]
        
        process = subprocess.Popen(
            make_cmd, cwd=project_root, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        active_processes[user_id] = process
        stdout, _ = process.communicate(timeout=BUILD_TIMEOUT)

        if process.returncode == 0:
            await status_msg.edit_text("✅ Success! Sending files...")
            found = False
            # Send .deb
            pkg_dir = os.path.join(project_root, "packages")
            if os.path.exists(pkg_dir):
                for f in os.listdir(pkg_dir):
                    if f.endswith(".deb"):
                        with open(os.path.join(pkg_dir, f), 'rb') as deb:
                            await update.message.reply_document(deb, caption=f"📦 {f}")
                            found = True
            # Send .dylib
            for root, _, files in os.walk(os.path.join(project_root, ".theos/obj")):
                for f in files:
                    if f.endswith(".dylib"):
                        with open(os.path.join(root, f), 'rb') as dylib:
                            await update.message.reply_document(dylib, caption=f"📚 {f}")
                            found = True
            if not found: await update.message.reply_text("⚠️ Build finished but no output found.")
        else:
            log_path = os.path.join(build_dir, "error.log")
            with open(log_path, 'w') as f: f.write(stdout)
            with open(log_path, 'rb') as f:
                await update.message.reply_document(f, caption="❌ Build Failed.")
            await status_msg.edit_text("❌ Compilation Failed.")

    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)[:200]}")
    finally:
        if user_id in active_processes: del active_processes[user_id]
        async with build_lock: active_builds -= 1
        shutil.rmtree(build_dir, ignore_errors=True)

def main():
    threading.Thread(target=run_http_server, daemon=True).start()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    logger.info("Bot started")
    app.run_polling()

if __name__ == '__main__':
    main()
