#!/usr/bin/env python3
import os
import shutil
import subprocess
import patoolib
import asyncio
import logging
import re
import threading
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8683956903:AAHfM4eybz3oLKi-SWXr6TzsHzMRaoUwI-M")
THEOS_PATH = os.getenv("THEOS", "/opt/render/project/src/theos")
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

# --- Health Check Server ---
health_app = Flask(__name__)

@health_app.route('/health')
def health_check():
    return "OK", 200

@health_app.route('/')
def index():
    return "Theos Compiler Bot is active", 200

def run_http_server():
    port = int(os.getenv("PORT", "10000"))
    logger.info(f"Starting health check server on port {port}")
    health_app.run(host='0.0.0.0', port=port)

# --- Bot Logic ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    
    keyboard = [[InlineKeyboardButton("📊 Server Status", callback_data="status")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🚀 *Theos Compiler Bot (L3CHBA Edition)*\n\n"
        "أهلاً بك! أنا جاهز لتجميع مشاريع iOS الخاصة بك.\n\n"
        "📦 *الصيغ المدعومة:* zip, rar, 7z, tar.gz\n"
        "🛠️ *البيئة:* Theos + iOS 14.5 SDK + Clang 10\n\n"
        "أرسل ملف المشروع (zip) وسأقوم بالباقي.\n\n"
        "👨‍💻 *المطور:* @staline777",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    async with build_lock: builds = active_builds
    
    status_text = (
        f"📊 *Server Status*\n\n"
        f"Builds: {builds}/{MAX_CONCURRENT_BUILDS}\n"
        f"SDK: iPhoneOS 14.5\n"
        f"Status: Running 24/7"
    )
    await query.edit_message_text(status_text, parse_mode='Markdown')

async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    if user_id in active_processes:
        active_processes[user_id].kill()
        await query.answer("Build cancelled!")
        await query.edit_message_text("❌ Build terminated.")
    else:
        await query.answer("No active build")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global active_builds
    if update.effective_chat.type != 'private': return
    
    doc = update.message.document
    user_id = update.effective_user.id
    
    if doc.file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
        await update.message.reply_text("❌ File too large.")
        return

    # Rate limit check
    if datetime.now() - user_last_build[user_id] < timedelta(minutes=RATE_LIMIT_MINUTES):
        await update.message.reply_text("⏳ Please wait 1 minute.")
        return

    async with build_lock:
        if active_builds >= MAX_CONCURRENT_BUILDS:
            await update.message.reply_text("⏳ Server busy, try again.")
            return
        active_builds += 1
    
    user_last_build[user_id] = datetime.now()
    status_msg = await update.message.reply_text("📥 Received. Starting build...", parse_mode='Markdown')
    
    build_dir = os.path.join(WORK_DIR, f"build_{user_id}_{int(datetime.now().timestamp())}")
    os.makedirs(build_dir, exist_ok=True)
    
    try:
        # Download
        file = await context.bot.get_file(doc.file_id)
        archive_path = os.path.join(build_dir, doc.file_name)
        await file.download_to_drive(archive_path)
        
        # Log to group if configured
        if LOG_GROUP_ID != 0:
            try:
                await context.bot.send_message(LOG_GROUP_ID, f"Build started for {update.effective_user.first_name} ({user_id})")
            except: pass

        # Extract
        extract_dir = os.path.join(build_dir, "project")
        os.makedirs(extract_dir)
        patoolib.extract_archive(archive_path, outdir=extract_dir)
        
        # Find Makefile
        project_root = extract_dir
        for root, dirs, files in os.walk(extract_dir):
            if 'Makefile' in files:
                project_root = root
                break
        
        # Build environment
        env = os.environ.copy()
        env["THEOS"] = THEOS_PATH
        env["THEOS_MAKE_PATH"] = os.path.join(THEOS_PATH, "makefiles")
        env["PATH"] = f"{THEOS_PATH}/bin:{THEOS_PATH}/toolchain/bin:{env.get('PATH', '')}"
        
        # Compile
        await status_msg.edit_text("🔨 Compiling...")
        
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
            await status_msg.edit_text("✅ Build Success! Sending files...")
            
            # Send .deb
            pkg_dir = os.path.join(project_root, "packages")
            if os.path.exists(pkg_dir):
                for f in os.listdir(pkg_dir):
                    if f.endswith(".deb"):
                        with open(os.path.join(pkg_dir, f), 'rb') as deb:
                            await update.message.reply_document(deb, caption=f"📦 {f}")
            
            # Send .dylib
            obj_dir = os.path.join(project_root, ".theos/obj/debug") if os.path.exists(os.path.join(project_root, ".theos/obj/debug")) else os.path.join(project_root, ".theos/obj")
            if os.path.exists(obj_dir):
                for root, _, files in os.walk(obj_dir):
                    for f in files:
                        if f.endswith(".dylib"):
                            with open(os.path.join(root, f), 'rb') as dylib:
                                await update.message.reply_document(dylib, caption=f"📚 {f}")
        else:
            log_path = os.path.join(build_dir, "error.log")
            with open(log_path, 'w') as f: f.write(stdout)
            with open(log_path, 'rb') as f:
                await update.message.reply_document(f, caption="❌ Build Failed. Check logs.")
            await status_msg.edit_text("❌ Compilation Failed.")

    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)[:100]}")
    finally:
        if user_id in active_processes: del active_processes[user_id]
        async with build_lock: active_builds -= 1
        shutil.rmtree(build_dir, ignore_errors=True)

def main():
    threading.Thread(target=run_http_server, daemon=True).start()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(status_callback, pattern="^status$"))
    app.add_handler(CallbackQueryHandler(cancel_callback, pattern="^cancel$"))
    logger.info("Bot started")
    app.run_polling()

if __name__ == '__main__':
    main()
