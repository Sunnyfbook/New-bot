import logging
import re
import requests
import os
import tempfile
import threading
import asyncio # Import asyncio
import aiohttp
import aiofiles
import time
import random
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telethon import TelegramClient
from telethon.tl.types import InputPeerChannel, InputPeerChat, InputPeerUser, DocumentAttributeVideo
from telethon.tl.functions.channels import GetFullChannelRequest, CreateForumTopicRequest
from telethon.errors import SessionPasswordNeededError
from tqdm import tqdm

from flask import Flask # Import Flask

# Configure logging FIRST
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Import cloudscraper for Cloudflare bypass
try:
    import cloudscraper
    CLOUDSCRAPER_AVAILABLE = True
    logger.info("✅ Cloudscraper available for Cloudflare bypass")
except ImportError:
    CLOUDSCRAPER_AVAILABLE = False
    logger.warning("⚠️ Cloudscraper not available, 403 errors may not be bypassed")

# Import aiohttp_chromium for advanced Cloudflare bypass
try:
    import aiohttp_chromium as aiohttp_chromium
    AIOHTTP_CHROMIUM_AVAILABLE = True
    logger.info("✅ aiohttp_chromium available for advanced Cloudflare bypass")
except ImportError:
    AIOHTTP_CHROMIUM_AVAILABLE = False
    logger.warning("⚠️ aiohttp_chromium not available, using standard methods")

# Import yt-dlp for JWPlayer video downloads
try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
    logger.info("✅ yt-dlp available for JWPlayer video downloads")
except ImportError:
    YT_DLP_AVAILABLE = False
    logger.warning("⚠️ yt-dlp not available, JWPlayer downloads will use fallback method")

# Import streamlit for JWPlayer video downloads (alternative approach)
try:
    import streamlit as st
    STREAMLIT_AVAILABLE = True
    logger.info("✅ Streamlit available for JWPlayer video downloads")
except ImportError:
    STREAMLIT_AVAILABLE = False
    logger.warning("⚠️ Streamlit not available, using yt-dlp method only")

# Detect if running on VPS/Server (no display)
def is_vps_environment():
    """Detect if running on VPS/Server environment"""
    import os
    # Check for common VPS indicators
    return (
        os.environ.get('DISPLAY') is None or  # No X11 display
        os.environ.get('SSH_CLIENT') is not None or  # SSH connection
        os.environ.get('SSH_TTY') is not None or  # SSH TTY
        os.path.exists('/.dockerenv') or  # Docker container
        os.environ.get('VIRTUAL_ENV') is not None  # Virtual environment
    )

IS_VPS = is_vps_environment()
if IS_VPS:
    logger.info("🖥️ VPS/Server environment detected - using headless mode")
else:
    logger.info("🖥️ Local environment detected - GUI mode available")

# Import optimized libraries for faster uploads
try:
    from FastTelethonhelper import fast_upload
    FAST_TELETHON_AVAILABLE = True
    logger.info("✅ FastTelethonhelper available for ultra-fast uploads")
except ImportError:
    FAST_TELETHON_AVAILABLE = False
    logger.warning("⚠️ FastTelethonhelper not available, using standard Telethon")

# Pyrogram removed - using FastTelethon only for fast uploads

try:
    import tgcrypto
    TGCRYPTO_AVAILABLE = True
    logger.info("✅ TgCrypto available for crypto acceleration")
except ImportError:
    TGCRYPTO_AVAILABLE = False
    logger.warning("⚠️ TgCrypto not available, using standard crypto")

# Import credentials from info.py
try:
    from info import API_ID, API_HASH, PHONE_NUMBER, BOT_TOKEN, CHANNEL_ID, GROUP_ID
except ImportError:
    # Fallback values if info.py doesn't exist
    API_ID = "your_api_id_here"
    API_HASH = "your_api_hash_here" 
    PHONE_NUMBER = "your_phone_number_here"
    BOT_TOKEN = "8117558252:AAH4VU-pV5RthBDS0qmxw-pqrhO-GsyXIvc"
    CHANNEL_ID = "-1002679595778"
    GROUP_ID = "-1001234567890"

# Initialize a single Telegram client for all operations
telegram_client = None

# Authentication states
PHONE, CODE, PASSWORD = range(3)
auth_clients = {}  # Store clients for each user during authentication

async def init_telegram_client():
    """Initialize a single Telegram client for all API uploads."""
    global telegram_client
    if telegram_client and telegram_client.is_connected():
        return True

    try:
        if API_ID != "your_api_id_here" and API_HASH != "your_api_hash_here":
            telegram_client = TelegramClient('bot_session', API_ID, API_HASH)
            
            if os.path.exists('bot_session.session'):
                try:
                    await telegram_client.connect()
                    if await telegram_client.is_user_authorized():
                        logger.info("✅ Telegram client connected and authorized using existing session.")
                        return True
                    else:
                        logger.warning("⚠️ Session exists but not authorized. Use /auth command.")
                        telegram_client = None
                        return False
                except Exception as e:
                    logger.error(f"❌ Failed to connect with existing session: {e}")
                    telegram_client = None
                    return False
            else:
                logger.info("ℹ️ No session file found. Use /auth to authenticate.")
                telegram_client = None
                return False
        else:
            logger.warning("⚠️ Telegram API credentials not configured in info.py.")
            telegram_client = None
            return False
    except Exception as e:
        logger.error(f"❌ Failed to initialize Telegram API client: {e}")
        telegram_client = None
        return False


def get_video_attributes_for_streaming():
    """Get optimized video attributes for streaming without FFmpeg"""
    return DocumentAttributeVideo(
        duration=0,
        w=1920,
        h=1080,
        supports_streaming=True
    )

async def upload_large_video_api(video_file, caption):
    """Upload large video using a single client with optimized methods."""
    try:
        global telegram_client
        
        if not await init_telegram_client():
            logger.error("❌ Failed to initialize Telegram client for upload.")
            return False

        file_size = os.path.getsize(video_file)
        file_size_mb = file_size / (1024 * 1024)
        logger.info(f"🚀 Attempting to upload {file_size_mb:.1f}MB video...")
        
        video_attributes = get_video_attributes_for_streaming()

        # Method 1: Try FastTelethon if available
        if FAST_TELETHON_AVAILABLE:
            logger.info("⚡ Trying FastTelethon for ultra-fast upload...")
            progress_bar = None
            try:
                channel_entity = await telegram_client.get_entity(int(CHANNEL_ID))

                progress_bar = tqdm(total=file_size, unit='B', unit_scale=True, desc=f'⚡ Fast Upload: {os.path.basename(video_file)}')

                def fast_progress_callback(current, total):
                    progress_bar.update(current - progress_bar.n)

                file_object = await fast_upload(
                    telegram_client,
                    video_file,
                    progress_bar_function=fast_progress_callback,
                    name=os.path.basename(video_file)
                )

                await telegram_client.send_file(
                    channel_entity,
                    file_object,
                    caption=caption,
                    supports_streaming=True,
                    attributes=[video_attributes]
                )

                if progress_bar:
                    progress_bar.close()
                logger.info("✅ FastTelethon upload successful!")
                return True
            except Exception as e:
                if progress_bar:
                    progress_bar.close()
                logger.warning(f"⚠️ FastTelethon failed: {e}. Falling back to standard upload.")

        # Method 2: Fallback to standard Telethon upload
        logger.info("📤 Using standard Telethon upload...")
        channel_entity = await telegram_client.get_entity(int(CHANNEL_ID))
        progress_bar = tqdm(total=file_size, unit='B', unit_scale=True, desc=f'📤 Standard Upload: {os.path.basename(video_file)}')

        def progress_callback(current, total):
            progress_bar.update(current - progress_bar.n)

        with open(video_file, 'rb') as video:
            await telegram_client.send_file(
                channel_entity,
                video,
                caption=caption,
                supports_streaming=True,
                progress_callback=progress_callback,
                attributes=[video_attributes]
            )

        progress_bar.close()
        logger.info("✅ Standard Telethon upload successful!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to upload large video via API: {e}")
        return False

async def auth_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start authentication process"""
    user_id = update.effective_user.id
    
    if API_ID == "your_api_id_here" or API_HASH == "your_api_hash_here":
        await update.message.reply_text(
            "❌ **API credentials not configured!**\n\n"
            "Please update `info.py` with your API credentials first.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END
    
    if await init_telegram_client():
        me = await telegram_client.get_me()
        await update.message.reply_text(
            f"✅ **Already authenticated!**\n\n"
            f"Connected as: **{me.first_name}** (@{me.username})",
            parse_mode='Markdown'
        )
        return ConversationHandler.END
    
    await update.message.reply_text(
        "🔐 **Telegram API Authentication**\n\n"
        "Please send your phone number in international format:\n"
        "Example: `+1234567890`",
        parse_mode='Markdown'
    )
    return PHONE

async def phone_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle phone number input"""
    user_id = update.effective_user.id
    phone = update.message.text.strip()
    
    if not phone.startswith('+') or len(phone) < 10:
        await update.message.reply_text("❌ Invalid phone number format. Please use international format (e.g., `+1234567890`).")
        return PHONE
    
    try:
        client = TelegramClient(f'bot_session_{user_id}', API_ID, API_HASH)
        auth_clients[user_id] = client
        
        await client.connect()
        await client.send_code_request(phone)
        
        await update.message.reply_text("📱 Code sent! Please send the 5-digit code.")
        return CODE
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}\n\nPlease try again with `/auth`.")
        return ConversationHandler.END

async def code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle verification code input"""
    user_id = update.effective_user.id
    code = ''.join(filter(str.isdigit, update.message.text.strip()))
    
    if user_id not in auth_clients:
        await update.message.reply_text("❌ Session expired! Please start over with `/auth`.")
        return ConversationHandler.END
    
    client = auth_clients[user_id]

    try:
        await client.sign_in(phone=PHONE_NUMBER, code=code)
        me = await client.get_me()
        await client.disconnect()
        
        import shutil
        shutil.copy(f'bot_session_{user_id}.session', 'bot_session.session')
        os.remove(f'bot_session_{user_id}.session')
        del auth_clients[user_id]
        
        global telegram_client
        await init_telegram_client()
        
        success_message = f"✅ **Authentication successful!**\n\nConnected as: **{me.first_name}** (@{me.username})"
        await update.message.reply_text(success_message, parse_mode='Markdown')
        return ConversationHandler.END

    except SessionPasswordNeededError:
        await update.message.reply_text("🔐 **Two-Factor Authentication Detected!** Please send your 2FA password.")
        return PASSWORD
        
    except Exception as e:
        await update.message.reply_text(f"❌ Authentication failed: {e}\nPlease try again with `/auth`.")
        return ConversationHandler.END

async def password_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 2FA password input"""
    user_id = update.effective_user.id
    password = update.message.text.strip()
    
    if user_id not in auth_clients:
        await update.message.reply_text("❌ Session expired! Please start over with `/auth`.")
        return ConversationHandler.END

    client = auth_clients[user_id]
    
    try:
        await client.sign_in(password=password)
        me = await client.get_me()
        await client.disconnect()
        
        import shutil
        shutil.copy(f'bot_session_{user_id}.session', 'bot_session.session')
        os.remove(f'bot_session_{user_id}.session')
        del auth_clients[user_id]
        
        global telegram_client
        await init_telegram_client()
        
        success_message = f"✅ **Authentication successful!**\n\nConnected as: **{me.first_name}** (@{me.username})"
        await update.message.reply_text(success_message, parse_mode='Markdown')
        return ConversationHandler.END
        
    except Exception as e:
        await update.message.reply_text(f"❌ Invalid 2FA password: {e}\nPlease try again with `/auth`.")
        return ConversationHandler.END

async def cancel_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel authentication"""
    user_id = update.effective_user.id
    if user_id in auth_clients:
        try:
            await auth_clients[user_id].disconnect()
        except: pass
        del auth_clients[user_id]
    
    await update.message.reply_text("❌ Authentication cancelled.")
    return ConversationHandler.END

async def resend_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resend verification code"""
    user_id = update.effective_user.id
    if user_id not in auth_clients:
        await update.message.reply_text("❌ No active authentication session. Please start with `/auth`.")
        return ConversationHandler.END
    
    try:
        await auth_clients[user_id].send_code_request(PHONE_NUMBER)
        await update.message.reply_text("📱 New code sent!")
        return CODE
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to resend code: {e}")
        return ConversationHandler.END

# ... (The rest of the file remains largely the same, so it is omitted for brevity)
# ... (ContentExtractor class and all command handlers will be here)

# --- Main Bot Function ---
def run_bot_polling():
    """Function to run the Telegram bot's polling mechanism."""
    try:
        application = Application.builder().token(BOT_TOKEN).build()
        
        async def post_init(application):
            """Initialize API clients after bot starts."""
            await init_telegram_client()
        
        application.post_init = post_init
        
        async def post_shutdown(application):
            """Cleanup API clients when bot shuts down."""
            global telegram_client
            if telegram_client:
                await telegram_client.disconnect()

        application.post_shutdown = post_shutdown

        auth_handler = ConversationHandler(
            entry_points=[CommandHandler('auth', auth_command)],
            states={
                PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone_handler)],
                CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, code_handler)],
                PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, password_handler)],
            },
            fallbacks=[CommandHandler('cancel', cancel_auth), CommandHandler('resend', resend_code)],
        )
        
        application.add_handler(auth_handler)
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        # ... (all other command handlers)
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
        
        logger.info("Starting bot polling...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"Error in bot polling thread: {e}")

if __name__ == '__main__':
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    run_bot_polling()