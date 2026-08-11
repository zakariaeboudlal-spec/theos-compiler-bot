#!/usr/bin/env python3
import os
import shutil
import subprocess
import patoolib
import asyncio
import logging
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8683956903:AAHfM4eybz3oLKi-SWXr6TzsHzMRaoUwI-M")
THEOS_PATH = os.getenv("THEOS", os.path.abspath(os.path.join(os.path.dirname(__file__), "theos")) if os.path.exists(os.path.abspath(os.path.join(os.path.dirname(__file__), "theos"))) else "/opt/render/project/src/theos" if os.path.exists("/opt/render/project") else "/opt/render/project/.render/theos")}
WORK_DIR = "/tmp/theos_builds"
MAX_CONCURRENT_BUILDS = 3
BUILD_TIMEOUT = 900  # 15 minutes
RATE_LIMIT_MINUTES = 1
MAX_FILE_SIZE_MB = 100
LOG_GROUP_ID = int(os.getenv("LOG_GROUP_ID", "0"))  # Optional private group for build logs

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler()  # Only console output, no file
    ]
)
logger = logging.getLogger(__name__)

os.makedirs(WORK_DIR, exist_ok=True)

# Global state
active_builds = 0
build_lock = asyncio.Lock()
user_last_build = defaultdict(lambda: datetime.min)
active_processes = {}  # user_id -> process


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message with bot information"""
    # Only work in private chats
    if update.effective_chat.type != 'private':
        return
    
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) started the bot")
    
    keyboard = [[InlineKeyboardButton("📊 Server Status", callback_data="status")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🔧 *Theos Compiler Bot*\n\n"
        "Professional iOS tweak compilation service\n\n"
        "📦 *Supported Formats:*\n"
        "zip, rar, 7z, tar.gz, tar.bz2, and more\n\n"
        "📋 *Requirements:*\n"
        "• Valid Theos project structure\n"
        "• Makefile in project root\n"
        f"• File size under {MAX_FILE_SIZE_MB}MB\n\n"
        "⚡ *Features:*\n"
        "• Real-time build progress\n"
        "• Multiple output formats (dylib, deb, framework)\n"
        "• Build cancellation support\n\n"
        "Send your project archive to begin compilation.\n\n"
        "👨‍💻 *Developer:* @staline777",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show server status"""
    query = update.callback_query
    await query.answer()
    
    async with build_lock:
        builds = active_builds
    
    status_text = (
        f"📊 *Server Status*\n\n"
        f"Active Builds: {builds}/{MAX_CONCURRENT_BUILDS}\n"
        f"Available Slots: {MAX_CONCURRENT_BUILDS - builds}\n"
        f"Build Timeout: {BUILD_TIMEOUT}s\n"
        f"Rate Limit: {RATE_LIMIT_MINUTES} min\n"
    )
    
    await query.edit_message_text(status_text, parse_mode='Markdown')


async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel active build"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    if user_id in active_processes:
        process = active_processes[user_id]
        try:
            process.kill()
            del active_processes[user_id]
            await query.answer("Build cancelled!")
            await query.edit_message_text("❌ *Build Cancelled*\n\nYour compilation has been terminated.", parse_mode='Markdown')
            logger.info(f"User {user_id} cancelled their build")
        except Exception as e:
            await query.answer("Failed to cancel")
            logger.error(f"Cancel failed for user {user_id}: {e}")
    else:
        await query.answer("No active build found")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded project files"""
    global active_builds
    
    # Only work in private chats (not groups, except log group)
    if update.effective_chat.type != 'private':
        return
    
    document = update.message.document
    user = update.effective_user
    user_id = user.id
    
    logger.info(f"User {user_id} ({user.username}) uploaded: {document.file_name} ({document.file_size} bytes)")
    
    # File size check
    if document.file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
        await update.message.reply_text(f"❌ File too large. Maximum size: {MAX_FILE_SIZE_MB}MB")
        return
    
    # Rate limiting
    time_since_last = datetime.now() - user_last_build[user_id]
    if time_since_last < timedelta(minutes=RATE_LIMIT_MINUTES):
        wait_time = RATE_LIMIT_MINUTES - (time_since_last.seconds // 60)
        await update.message.reply_text(
            f"⏳ *Rate Limit*\n\nPlease wait {wait_time} minute(s) before submitting another build.",
            parse_mode='Markdown'
        )
        return
    
    # Concurrent builds check
    async with build_lock:
        if active_builds >= MAX_CONCURRENT_BUILDS:
            await update.message.reply_text(
                f"⏳ *Server Busy*\n\n"
                f"All build slots occupied ({active_builds}/{MAX_CONCURRENT_BUILDS})\n"
                f"Please try again in a few moments.",
                parse_mode='Markdown'
            )
            return
        active_builds += 1
    
    user_last_build[user_id] = datetime.now()
    
    # Create cancel button
    keyboard = [[InlineKeyboardButton("❌ Cancel Build", callback_data="cancel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    status_msg = await update.message.reply_text(
        f"📥 *Received*\n\nExtracting archive... ({active_builds}/{MAX_CONCURRENT_BUILDS} builds active)",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    
    build_dir = os.path.join(WORK_DIR, f"build_{user_id}_{datetime.now().timestamp()}")
    
    try:
        # Clean up and create build directory
        if os.path.exists(build_dir):
            shutil.rmtree(build_dir)
        os.makedirs(build_dir)
        
        # Download archive with longer timeout
        file = await context.bot.get_file(document.file_id)
        archive_path = os.path.join(build_dir, document.file_name)
        
        try:
            await asyncio.wait_for(
                file.download_to_drive(archive_path),
                timeout=300  # 5 minutes for download
            )
        except asyncio.TimeoutError:
            await status_msg.edit_text(
                "❌ *خطأ في التحميل*\n\n"
                "استغرق تحميل الملف وقتاً طويلاً. يرجى المحاولة مرة أخرى.",
                parse_mode='Markdown'
            )
            return
        except Exception as e:
            error_msg = str(e)
            if "File is too big" in error_msg:
                await status_msg.edit_text(
                    "❌ *الملف كبير جداً!*\n\n"
                    "حجم الملف الذي أرسلته (~45 ميجابايت) يتجاوز الحد الأقصى المسموح به لملفات البوت عبر خوادم تلغرام الرسمية (20 ميجابايت).\n\n"
                    "💡 *الحل:* قم بضغط المشروع بدون مجلدات البناء الضخمة (مثل `.theos/_obj`, `obj`, `layout`) ليكون حجم الملف أقل من 20 ميجابايت.",
                    parse_mode='Markdown'
                )
            else:
                await status_msg.edit_text(
                    f"❌ *فشل تحميل الملف*\n\n"
                    f"حدث خطأ: {error_msg[:100]}",
                    parse_mode='Markdown'
                )
            return
        
        # Forward original project to log group BEFORE building (always send, even duplicates)
        # Retry logic for large files or network issues
        max_retries = 3
        forwarded = False
        
        for attempt in range(max_retries):
            try:
                client_name = user.first_name + (f" {user.last_name}" if user.last_name else "")
                client_username = f"@{user.username}" if user.username else "No username"
                
                # Check if file is too large for bot forwarding (Telegram bot limit: 50MB)
                if document.file_size > 50 * 1024 * 1024:
                    # Send text info only for large files
                    project_info = (
                        f"👤 *Client Info*\n\n"
                        f"Name: {client_name}\n"
                        f"Username: {client_username}\n"
                        f"User ID: `{user_id}`\n"
                        f"Project: {document.file_name}\n"
                        f"Size: {document.file_size / 1024 / 1024:.1f} MB\n"
                        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"Status: Building...\n\n"
                        f"⚠️ File too large to forward (>50MB limit)"
                    )
                    await context.bot.send_message(
                        chat_id=LOG_GROUP_ID,
                        text=project_info,
                        parse_mode='Markdown'
                    )
                    logger.info(f"Sent text info for large file from user {user_id}")
                    forwarded = True
                    break
                else:
                    # Forward file for normal-sized projects
                    project_info = (
                        f"👤 *Client Info*\n\n"
                        f"Name: {client_name}\n"
                        f"Username: {client_username}\n"
                        f"User ID: `{user_id}`\n"
                        f"Project: {document.file_name}\n"
                        f"Size: {document.file_size / 1024:.1f} KB\n"
                        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"Status: Building..."
                    )
                    
                    with open(archive_path, 'rb') as f:
                        await asyncio.wait_for(
                            context.bot.send_document(
                                chat_id=LOG_GROUP_ID,
                                document=f,
                                caption=project_info,
                                filename=document.file_name,
                                parse_mode='Markdown',
                                disable_content_type_detection=False,
                                protect_content=False,
                                read_timeout=180,
                                write_timeout=180
                            ),
                            timeout=300  # 5 minutes for forwarding
                        )
                    logger.info(f"Forwarded project to log group from user {user_id} (attempt {attempt + 1})")
                    forwarded = True
                    break
                    
            except asyncio.TimeoutError:
                logger.warning(f"Timeout forwarding to log group for user {user_id} (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)  # Wait 2 seconds before retry
                    continue
            except Exception as e:
                logger.error(f"Failed to forward project to log group (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)  # Wait 2 seconds before retry
                    continue
        
        # If all retries failed, send notification to log group
        if not forwarded:
            try:
                fail_info = (
                    f"⚠️ *Forward Failed*\n\n"
                    f"User: {client_name} ({client_username})\n"
                    f"User ID: `{user_id}`\n"
                    f"Project: {document.file_name}\n"
                    f"Size: {document.file_size / 1024:.1f} KB\n"
                    f"Failed after {max_retries} attempts"
                )
                await context.bot.send_message(
                    chat_id=LOG_GROUP_ID,
                    text=fail_info,
                    parse_mode='Markdown'
                )
            except:
                pass
        
        await status_msg.edit_text(
            "📦 *Extracting*\n\nDecompressing project files...",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
        # Extract archive with timeout
        extract_dir = os.path.join(build_dir, "project")
        os.makedirs(extract_dir)
        
        try:
            await asyncio.wait_for(
                asyncio.to_thread(patoolib.extract_archive, archive_path, outdir=extract_dir),
                timeout=180  # 3 minutes for extraction
            )
        except asyncio.TimeoutError:
            log_file = os.path.join(build_dir, "extraction_timeout.log")
            with open(log_file, 'w') as f:
                f.write("=== EXTRACTION TIMEOUT LOG ===\n\n")
                f.write(f"Project: {document.file_name}\n")
                f.write(f"Size: {document.file_size / 1024:.1f} KB\n\n")
                f.write("Extraction took too long (>3 minutes)\n")
                f.write("Possible causes:\n")
                f.write("- Very large archive\n")
                f.write("- Too many files\n")
                f.write("- Corrupted archive\n")
            
            with open(log_file, 'rb') as f:
                await update.message.reply_document(
                    document=f,
                    caption=f"❌ *Extraction Timeout*\n\nCheck the log file.",
                    filename="extraction_timeout.log",
                    parse_mode='Markdown'
                )
            
            await status_msg.edit_text(
                f"❌ *Extraction Timeout*\n\nLog file sent above.",
                parse_mode='Markdown'
            )
            return
        except Exception as e:
            logger.error(f"Extraction failed for user {user_id}: {e}")
            
            # Create extraction error log
            log_file = os.path.join(build_dir, "extraction_error.log")
            with open(log_file, 'w') as f:
                f.write("=== EXTRACTION ERROR LOG ===\n\n")
                f.write(f"Project: {document.file_name}\n")
                f.write(f"Error: {str(e)}\n\n")
                f.write("Possible causes:\n")
                f.write("- Corrupted archive file\n")
                f.write("- Unsupported compression format\n")
                f.write("- Password-protected archive\n")
            
            with open(log_file, 'rb') as f:
                await update.message.reply_document(
                    document=f,
                    caption=f"❌ *Extraction Failed*\n\nCheck the log file for details.",
                    filename="extraction_error.log",
                    parse_mode='Markdown'
                )
            
            await status_msg.edit_text(
                f"❌ *Extraction Failed*\n\n"
                f"Unable to decompress archive. Log file sent above.",
                parse_mode='Markdown'
            )
            return
        
        # Find Makefile
        project_root = extract_dir
        for root, dirs, files in os.walk(extract_dir):
            if 'Makefile' in files:
                project_root = root
                break
        
        if not os.path.exists(os.path.join(project_root, 'Makefile')):
            # Create error log
            log_file = os.path.join(build_dir, "project_error.log")
            with open(log_file, 'w') as f:
                f.write("=== PROJECT STRUCTURE ERROR ===\n\n")
                f.write(f"Project: {document.file_name}\n\n")
                f.write("Error: No Makefile found\n\n")
                f.write("Your project must contain:\n")
                f.write("- Makefile (required)\n")
                f.write("- control file\n")
                f.write("- Source files (.m, .mm, .c, .cpp)\n\n")
                f.write("Project structure found:\n")
                for root, dirs, files in os.walk(extract_dir):
                    level = root.replace(extract_dir, '').count(os.sep)
                    indent = ' ' * 2 * level
                    f.write(f"{indent}{os.path.basename(root)}/\n")
                    subindent = ' ' * 2 * (level + 1)
                    for file in files[:20]:  # Limit to 20 files
                        f.write(f"{subindent}{file}\n")
            
            with open(log_file, 'rb') as f:
                await update.message.reply_document(
                    document=f,
                    caption=f"❌ *Invalid Project*\n\nNo Makefile found. Check the log for project structure.",
                    filename="project_error.log",
                    parse_mode='Markdown'
                )
            
            await status_msg.edit_text(
                "❌ *Invalid Project*\n\n"
                "No Makefile found. Log file sent above.",
                parse_mode='Markdown'
            )
            return
        
        # Fix THEOS path in Makefile
        makefile_path = os.path.join(project_root, 'Makefile')
        try:
            with open(makefile_path, 'r', encoding='utf-8', errors='ignore') as f:
                makefile_content = f.read()
            
            original_content = makefile_content
            
            # Robust Makefile patching for Theos paths
            makefile_content = re.sub(r'include\s+/opt/theos/makefiles/', f'include {THEOS_PATH}/makefiles/', makefile_content)
            makefile_content = re.sub(r'include\s+/opt/render/project/src/theos/makefiles/', f'include {THEOS_PATH}/makefiles/', makefile_content)
            
            lines = makefile_content.splitlines()
            cleaned_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("export THEOS") or stripped.startswith("THEOS="):
                    continue
                if stripped in ["include /tweak.mk", "include /common.mk", "include /aggregate.mk"]:
                    continue
                cleaned_lines.append(line)
            
            new_lines = [
                f"THEOS = {THEOS_PATH}",
                f"export THEOS = {THEOS_PATH}",
                f"THEOS_MAKE_PATH = $(THEOS)/makefiles",
                f"export THEOS_MAKE_PATH = $(THEOS)/makefiles"
            ] + cleaned_lines
            
            makefile_content = "\n".join(new_lines)
            
            # Write back if changed
            if makefile_content != original_content:
                with open(makefile_path, 'w', encoding='utf-8') as f:
                    f.write(makefile_content)
                logger.info(f"Fixed THEOS path in Makefile for user {user_id}")
        except Exception as e:
            logger.warning(f"Could not fix Makefile for user {user_id}: {e}")
        
        # Fix permissions for dpkg-deb (prevent "bad permissions" errors)
        try:
            # Fix common permission issues
            for root, dirs, files in os.walk(project_root):
                # Fix directory permissions
                for dir_name in dirs:
                    dir_path = os.path.join(root, dir_name)
                    try:
                        os.chmod(dir_path, 0o755)
                    except:
                        pass
                
                # Fix file permissions
                for file_name in files:
                    file_path = os.path.join(root, file_name)
                    try:
                        os.chmod(file_path, 0o644)
                    except:
                        pass
            
            # Specifically fix layout/DEBIAN if it exists
            debian_dir = os.path.join(project_root, 'layout', 'DEBIAN')
            if os.path.exists(debian_dir):
                os.chmod(debian_dir, 0o755)
                control_file = os.path.join(debian_dir, 'control')
                if os.path.exists(control_file):
                    os.chmod(control_file, 0o644)
            
            logger.info(f"Fixed permissions for user {user_id}")
        except Exception as e:
            logger.warning(f"Could not fix permissions for user {user_id}: {e}")
        
        # Auto-create Filter.plist if missing (for tweaks)
        try:
            # Check if this is a tweak project by reading Makefile
            is_tweak = False
            tweak_name = None
            
            makefile_path = os.path.join(project_root, 'Makefile')
            if os.path.exists(makefile_path):
                with open(makefile_path, 'r', encoding='utf-8', errors='ignore') as f:
                    makefile_content = f.read()
                    # Check if it's a tweak
                    if 'TWEAK_NAME' in makefile_content or 'include $(THEOS)/makefiles/tweak.mk' in makefile_content:
                        is_tweak = True
                        # Try to extract tweak name
                        for line in makefile_content.split('\n'):
                            if 'TWEAK_NAME' in line and '=' in line:
                                tweak_name = line.split('=')[1].strip()
                                break
            
            # If it's a tweak and no plist exists, create one
            if is_tweak:
                plist_exists = False
                for file in os.listdir(project_root):
                    if file.endswith('.plist'):
                        plist_exists = True
                        break
                
                if not plist_exists:
                    # Create Filter.plist or TweakName.plist
                    if tweak_name:
                        plist_filename = f"{tweak_name}.plist"
                    else:
                        plist_filename = "Filter.plist"
                    
                    filter_plist_path = os.path.join(project_root, plist_filename)
                    with open(filter_plist_path, 'w') as f:
                        f.write('{ Filter = { Bundles = ( "com.apple.UIKit" ); }; }\n')
                    logger.info(f"Auto-created {plist_filename} for user {user_id}")
        except Exception as e:
            logger.warning(f"Could not create Filter.plist for user {user_id}: {e}")
        
        # Strict environment check before build
        theos_common = os.path.join(THEOS_PATH, "makefiles", "common.mk")
        theos_tweak = os.path.join(THEOS_PATH, "makefiles", "tweak.mk")
        theos_sdks = os.path.join(THEOS_PATH, "sdks")

        if not os.path.isfile(theos_common):
            error_msg = f"Theos common.mk not found: {theos_common}"
            logger.error(error_msg)
            await status_msg.edit_text(f"❌ *Build Error*\n\n{error_msg}", parse_mode='Markdown')
            return

        if not os.path.isfile(theos_tweak):
            error_msg = f"Theos tweak.mk not found: {theos_tweak}"
            logger.error(error_msg)
            await status_msg.edit_text(f"❌ *Build Error*\n\n{error_msg}", parse_mode='Markdown')
            return

        sdk_list = [d for d in os.listdir(theos_sdks) if d.endswith(".sdk")] if os.path.isdir(theos_sdks) else []
        if not sdk_list:
            error_msg = f"No iOS SDK found in: {theos_sdks}"
            logger.error(error_msg)
            await status_msg.edit_text(f"❌ *Build Error*\n\n{error_msg}", parse_mode='Markdown')
            return
        
        os.environ['THEOS'] = THEOS_PATH
        os.environ['THEOS_MAKE_PATH'] = os.path.join(THEOS_PATH, "makefiles")
        
        # Clean previous builds with timeout
        try:
            await asyncio.wait_for(
                asyncio.to_thread(subprocess.run, ["make", "clean"], cwd=project_root, capture_output=True),
                timeout=30
            )
        except asyncio.TimeoutError:
            logger.warning(f"Make clean timeout for user {user_id}")
        except Exception as e:
            logger.warning(f"Make clean failed for user {user_id}: {e}")
        
        await status_msg.edit_text(
            "🔨 *Compiling*\n\n"
            "Building your project...\n\n"
            "⏱️ *Estimated Time:* 30 seconds to 5 minutes\n"
            "Please wait while we compile your tweak.",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
        # Pass custom environment with explicit THEOS and THEOS_MAKE_PATH
        build_env = os.environ.copy()
        build_env['THEOS'] = THEOS_PATH
        build_env['THEOS_MAKE_PATH'] = os.path.join(THEOS_PATH, "makefiles")
        build_env['PATH'] = f"{THEOS_PATH}/bin:{build_env.get('PATH', '')}"

        # Start compilation with correct environment
        process = subprocess.Popen(
            ["make", "package", f"THEOS={THEOS_PATH}", f"THEOS_MAKE_PATH={build_env['THEOS_MAKE_PATH']}"],
            cwd=project_root,
            env=build_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        active_processes[user_id] = process
        
        output_lines = []
        build_start = datetime.now()
        
        try:
            # Read output without live updates
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                
                if line:
                    line = line.strip()
                    output_lines.append(line)
                
                # Timeout check
                if (datetime.now() - build_start).seconds > BUILD_TIMEOUT:
                    process.kill()
                    
                    # Create timeout log
                    log_file = os.path.join(build_dir, "timeout_error.log")
                    with open(log_file, 'w') as f:
                        f.write("=== BUILD TIMEOUT LOG ===\n\n")
                        f.write(f"Project: {document.file_name}\n")
                        f.write(f"Timeout: {BUILD_TIMEOUT}s\n\n")
                        f.write("=== BUILD OUTPUT (before timeout) ===\n\n")
                        f.write("\n".join(output_lines))
                    
                    with open(log_file, 'rb') as f:
                        await update.message.reply_document(
                            document=f,
                            caption=f"❌ *Build Timeout*\n\nExceeded {BUILD_TIMEOUT}s limit.",
                            filename="timeout_error.log",
                            parse_mode='Markdown'
                        )
                    
                    await status_msg.edit_text(
                        f"❌ *Build Timeout*\n\n"
                        f"Compilation exceeded {BUILD_TIMEOUT}s limit. Log sent above.",
                        parse_mode='Markdown'
                    )
                    logger.warning(f"Build timeout for user {user_id}")
                    return
            
            # Check result - Don't fail on packaging errors, dylib might still exist
            if process.returncode != 0:
                # Check if it's just a packaging error (dylib might still be built)
                packaging_error = any(
                    keyword in "\n".join(output_lines).lower() 
                    for keyword in ['filter property list', 'making stage', 'dpkg-deb']
                )
                
                if packaging_error:
                    logger.warning(f"Packaging error for user {user_id}, but checking for dylib/framework")
                    await status_msg.edit_text(
                        "⚠️ *Packaging Warning*\n\n"
                        "Build completed but packaging failed. Checking for compiled files...",
                        parse_mode='Markdown'
                    )
                    # Continue to file sending - don't return here
                else:
                    # Real compilation error - save full build log
                    log_file = os.path.join(build_dir, "build_error.log")
                    with open(log_file, 'w') as f:
                        f.write("=== THEOS BUILD ERROR LOG ===\n\n")
                        f.write(f"Project: {document.file_name}\n")
                        f.write(f"Build Time: {(datetime.now() - build_start).seconds}s\n")
                        f.write(f"Exit Code: {process.returncode}\n\n")
                        f.write("=== BUILD OUTPUT ===\n\n")
                        f.write("\n".join(output_lines))
                    
                    # Extract error summary
                    error_lines = [l for l in output_lines if "error" in l.lower() or "fatal" in l.lower()][:5]
                    error_summary = "\n".join(error_lines) if error_lines else "Build failed with unknown error"
                    
                    # Send error log file to client
                    with open(log_file, 'rb') as f:
                        await update.message.reply_document(
                            document=f,
                            caption=f"❌ *Compilation Failed*\n\nCheck the log file for details.",
                            filename="build_error.log",
                            parse_mode='Markdown'
                        )
                    
                    await status_msg.edit_text(
                        f"❌ *Compilation Failed*\n\n```\n{error_summary[:200]}\n```\n\nFull log sent above.",
                        parse_mode='Markdown'
                    )
                    logger.error(f"Build failed for user {user_id}")
                    return
        
        finally:
            if user_id in active_processes:
                del active_processes[user_id]
        
        await status_msg.edit_text(
            "✅ *Build Complete*\n\nPackaging output files...",
            parse_mode='Markdown'
        )
        
        # Find and send output files
        files_sent = 0
        
        # Find and send output files (only first of each type)
        files_sent = 0
        deb_sent = False
        dylib_sent = False
        framework_sent = False
        
        # Send first .deb package only
        packages_dir = os.path.join(project_root, "packages")
        if os.path.exists(packages_dir) and not deb_sent:
            for file in sorted(os.listdir(packages_dir)):
                if file.endswith('.deb'):
                    deb_path = os.path.join(packages_dir, file)
                    with open(deb_path, 'rb') as f:
                        await update.message.reply_document(
                            document=f,
                            caption=f"📦 {file}",
                            filename=file
                        )
                    files_sent += 1
                    deb_sent = True
                    logger.info(f"Sent .deb to user {user_id}: {file}")
                    break  # Only send first .deb
        
        # Search for frameworks ONLY in build output directories (not project source)
        framework_search_paths = [
            os.path.join(project_root, ".theos/obj/debug"),
            os.path.join(project_root, ".theos/obj/release"),
            os.path.join(project_root, ".theos/obj"),
            os.path.join(project_root, "obj/debug"),
            os.path.join(project_root, "obj/release"),
            os.path.join(project_root, "obj"),
        ]
        
        if not dylib_sent and not framework_sent:
            for search_path in framework_search_paths:
                if os.path.exists(search_path):
                    for root, dirs, files in os.walk(search_path):
                        for dir_name in sorted(dirs):
                            if dir_name.endswith('.framework'):
                                framework_path = os.path.join(root, dir_name)
                                # Zip framework
                                zip_path = os.path.join(build_dir, f"{dir_name}.zip")
                                shutil.make_archive(zip_path.replace('.zip', ''), 'zip', framework_path)
                                with open(zip_path, 'rb') as f:
                                    await update.message.reply_document(
                                        document=f,
                                        caption=f"🎯 {dir_name}",
                                        filename=f"{dir_name}.zip"
                                    )
                                files_sent += 1
                                framework_sent = True
                                logger.info(f"Sent framework to user {user_id}: {dir_name}")
                                break
                        if framework_sent:
                            break
                if framework_sent:
                    break
        
        # Search for .app bundles (applications)
        app_sent = False
        app_search_paths = [
            os.path.join(project_root, ".theos/obj/debug"),
            os.path.join(project_root, ".theos/obj/release"),
            os.path.join(project_root, "obj/debug"),
            os.path.join(project_root, "obj/release"),
            project_root,
        ]
        
        if not framework_sent and not dylib_sent and not app_sent:
            for search_path in app_search_paths:
                if os.path.exists(search_path):
                    for root, dirs, files in os.walk(search_path):
                        for dir_name in sorted(dirs):
                            if dir_name.endswith('.app'):
                                app_path = os.path.join(root, dir_name)
                                # Zip .app bundle
                                zip_path = os.path.join(build_dir, f"{dir_name}.zip")
                                shutil.make_archive(zip_path.replace('.zip', ''), 'zip', app_path)
                                with open(zip_path, 'rb') as f:
                                    await update.message.reply_document(
                                        document=f,
                                        caption=f"📱 {dir_name}",
                                        filename=f"{dir_name}.zip"
                                    )
                                files_sent += 1
                                app_sent = True
                                logger.info(f"Sent .app to user {user_id}: {dir_name}")
                                break
                        if app_sent:
                            break
                if app_sent:
                    break
        
        # Search for .dylib in multiple locations (if no framework sent)
        dylib_search_paths = [
            os.path.join(project_root, ".theos/obj"),
            os.path.join(project_root, ".theos/obj/debug"),
            os.path.join(project_root, ".theos/obj/release"),
            os.path.join(project_root, "obj"),
            os.path.join(project_root, "obj/debug"),
            os.path.join(project_root, "obj/release"),
            project_root,
        ]
        
        if not framework_sent and not dylib_sent:
            for search_path in dylib_search_paths:
                if os.path.exists(search_path):
                    for root, dirs, files in os.walk(search_path):
                        for file in sorted(files):
                            if file.endswith('.dylib'):
                                dylib_path = os.path.join(root, file)
                                with open(dylib_path, 'rb') as f:
                                    await update.message.reply_document(
                                        document=f,
                                        caption=f"📚 {file}",
                                        filename=file
                                    )
                                files_sent += 1
                                dylib_sent = True
                                logger.info(f"Sent .dylib to user {user_id}: {file}")
                                break
                        if dylib_sent:
                            break
                if dylib_sent:
                    break
        
        if files_sent > 0:
            build_time = (datetime.now() - build_start).seconds
            await status_msg.edit_text(
                f"✅ *Compilation Successful*\n\n"
                f"Files: {files_sent}\n"
                f"Time: {build_time}s",
                parse_mode='Markdown'
            )
            logger.info(f"Build successful for user {user_id}: {files_sent} files in {build_time}s")
        else:
            await status_msg.edit_text(
                "⚠️ *Build Complete*\n\n"
                "No output files found. Check your project configuration.",
                parse_mode='Markdown'
            )
    
    except Exception as e:
        logger.error(f"Error for user {user_id}: {e}", exc_info=True)
        
        # Create general error log
        log_file = os.path.join(build_dir, "system_error.log")
        try:
            with open(log_file, 'w') as f:
                f.write("=== SYSTEM ERROR LOG ===\n\n")
                f.write(f"Project: {document.file_name}\n")
                f.write(f"Error Type: {type(e).__name__}\n")
                f.write(f"Error Message: {str(e)}\n\n")
                f.write("Please contact support if this issue persists.\n")
            
            with open(log_file, 'rb') as f:
                await update.message.reply_document(
                    document=f,
                    caption=f"❌ *System Error*\n\nAn unexpected error occurred.",
                    filename="system_error.log",
                    parse_mode='Markdown'
                )
        except:
            await update.message.reply_text(
                f"❌ *Error*\n\n```\n{str(e)[:200]}\n```",
                parse_mode='Markdown'
            )
    
    finally:
        # Cleanup
        try:
            if os.path.exists(build_dir):
                shutil.rmtree(build_dir)
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
        
        # Release build slot
        async with build_lock:
            active_builds -= 1
        
        logger.info(f"Build slot released. Active builds: {active_builds}")


from flask import Flask
import threading

health_app = Flask(__name__)

@health_app.route('/health')
def health_check():
    return "Theos Compiler Bot is running 24/7!", 200

@health_app.route('/')
def index():
    return "Bot is alive", 200

def run_http_server():
    port = int(os.getenv("PORT", "10000"))
    logger.info(f"Starting Flask health check server on port {port}")
    health_app.run(host='0.0.0.0', port=port)

def main():
    """Start the bot"""
    logger.info("Starting Theos Compiler Bot...")
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    # Start HTTP server thread for Render web service health check
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(status_callback, pattern="^status$"))
    app.add_handler(CallbackQueryHandler(cancel_callback, pattern="^cancel$"))
    
    logger.info("Bot is running and ready to accept builds")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
