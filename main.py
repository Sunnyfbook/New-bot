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

# Import yt-dlp for all video downloads
try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
    logger.info("✅ yt-dlp available for all video downloads")
except ImportError:
    YT_DLP_AVAILABLE = False
    logger.warning("⚠️ yt-dlp not available. Video downloads may fail.")

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

# Initialize Telegram client
telegram_client = None

# Authentication states
PHONE, CODE, PASSWORD = range(3)
auth_clients = {}  # Store clients for each user

async def init_telegram_client():
    """Initialize a single Telegram client for all operations."""
    global telegram_client
    try:
        if API_ID != "your_api_id_here" and API_HASH != "your_api_hash_here":
            # Use a single session file for all operations
            telegram_client = TelegramClient('bot_session', API_ID, API_HASH)
            
            if os.path.exists('bot_session.session'):
                try:
                    await telegram_client.connect()
                    if await telegram_client.is_user_authorized():
                        logger.info("✅ Telegram client connected and authorized using existing session.")
                        return True
                    else:
                        logger.warning("⚠️ Session exists but not authorized. Use /auth to authenticate.")
                        telegram_client = None
                        return False
                except Exception as e:
                    # Catch potential "database is locked" errors here
                    if "database is locked" in str(e):
                         logger.error("❌ Database is locked. This might be due to another process using the session file.")
                    else:
                        logger.error(f"Failed to connect with existing session: {e}")
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
        logger.error(f"Failed to initialize Telegram client: {e}")
        telegram_client = None
        return False

# Pyrogram removed - using FastTelethon only for fast uploads

def get_video_attributes_for_streaming():
    """Get optimized video attributes for streaming without FFmpeg"""
    # Use standard attributes that work well for streaming
    return DocumentAttributeVideo(
        duration=0,  # Let Telegram auto-detect
        w=1920,      # Standard HD width
        h=1080,      # Standard HD height
        supports_streaming=True
    )

async def upload_large_video_api(video_file, caption):
    """Upload large video using a single client with optimized methods."""
    try:
        global telegram_client
        
        # Ensure the single client is initialized and connected
        if not telegram_client or not telegram_client.is_connected():
            logger.info("Initializing or reconnecting Telegram client for upload...")
            if not await init_telegram_client():
                logger.error("Failed to initialize Telegram API client for upload.")
                return False

        file_size = os.path.getsize(video_file)
        file_size_mb = file_size / (1024 * 1024)
        logger.info(f"🚀 Attempting to upload {file_size_mb:.1f}MB video.")
        
        video_attributes = get_video_attributes_for_streaming()

        # Method 1: Try FastTelethon if available
        if FAST_TELETHON_AVAILABLE:
            logger.info("⚡ Trying FastTelethon for ultra-fast upload...")
            try:
                channel_entity = await telegram_client.get_entity(int(CHANNEL_ID))

                progress_bar = tqdm(total=file_size, unit='B', unit_scale=True, desc=f'⚡ FastTelethon Upload: {os.path.basename(video_file)}')

                def fast_progress_callback(done, total):
                    progress_bar.update(done - progress_bar.n)

                file_object = await fast_upload(
                    telegram_client,
                    video_file,
                    progress_bar_function=fast_progress_callback
                )

                result = await telegram_client.send_file(
                    channel_entity,
                    file_object,
                    caption=caption,
                    supports_streaming=True,
                    attributes=[video_attributes],
                    thumb=None
                )

                progress_bar.close()
                logger.info(f"⚡ FastTelethon upload successful: {result.id}")
                return True
            except Exception as e:
                if 'progress_bar' in locals() and progress_bar:
                    progress_bar.close()
                logger.warning(f"FastTelethon failed: {e}. Falling back to standard upload.")

        # Method 2: Fallback to standard Telethon upload
        logger.info("📤 Using standard Telethon upload...")

        # Try different channel ID formats
        channel_id_variants = [
            CHANNEL_ID,  # Current setting from info.py (integer)
            str(CHANNEL_ID),  # As string
            str(CHANNEL_ID).replace('@', ''),  # Without @
        ]

        channel_entity = None
        for variant in channel_id_variants:
            try:
                logger.info(f"Trying channel ID variant: {variant}")
                channel_entity = await telegram_client.get_entity(variant)
                logger.info(f"✅ Successfully found channel: {channel_entity.title}")
                break
            except Exception as e:
                logger.warning(f"Failed to get entity with variant {variant}: {e}")
                continue

        if not channel_entity:
            logger.error("❌ Could not find channel entity with any variant")
            return False

        # Upload the video with tqdm progress bar
        logger.info(f"Starting video upload to channel: {channel_entity.title}")
        logger.info(f"File size: {file_size_mb:.1f}MB - Using tqdm progress tracking...")

        try:
            # Create progress bar
            progress_bar = tqdm(total=file_size, unit='B', unit_scale=True,
                              desc=f'📤 Standard Upload: {os.path.basename(video_file)}')

            def progress_callback(current, total):
                progress_bar.update(current - progress_bar.n)
                # Log upload progress every 10MB
                if current % (10 * 1024 * 1024) == 0:
                    mb_uploaded = current // (1024 * 1024)
                    if total > 0:
                        progress = (current / total) * 100
                        logger.info(f"📤 Uploaded {mb_uploaded}MB ({progress:.1f}%) - {os.path.basename(video_file)}")
                    else:
                        logger.info(f"📤 Uploaded {mb_uploaded}MB - {os.path.basename(video_file)}")

            # Upload file with progress tracking and proper attributes
            with open(video_file, 'rb') as video:
                result = await telegram_client.send_file(
                    channel_entity,
                    video,
                    caption=caption,
                    supports_streaming=True,
                    progress_callback=progress_callback,
                    attributes=[video_attributes],
                    # Additional parameters for better streaming compatibility
                    thumb=None,  # Let Telegram generate thumbnail
                    parse_mode=None
                )

            progress_bar.close()
            logger.info(f"✅ Successfully uploaded video via Telegram API: {result.id}")
            logger.info(f"✅ Video uploaded to channel: {channel_entity.title}")
            logger.info(f"✅ Message ID: {result.id}")
            return True

        except Exception as upload_error:
            if 'progress_bar' in locals():
                progress_bar.close()
            logger.error(f"❌ Upload failed: {upload_error}")
            logger.error(f"❌ Channel: {channel_entity.title}")
            logger.error(f"❌ File: {video_file}")
            return False
        
    except Exception as e:
        logger.error(f"❌ Failed to upload large video via API: {e}")
        return False

async def auth_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start authentication process"""
    user_id = update.effective_user.id
    
    # Check if API credentials are configured
    if API_ID == "your_api_id_here" or API_HASH == "your_api_hash_here":
        await update.message.reply_text(
            "❌ **API credentials not configured!**\n\n"
            "Please update `info.py` with your API credentials first:\n"
            "• Get them from: https://my.telegram.org/apps\n"
            "• Update API_ID, API_HASH, and PHONE_NUMBER in info.py",
            parse_mode='Markdown'
        )
        return ConversationHandler.END
    
    # Check if already authenticated using global client
    global telegram_client

    # Try to initialize client if not already done
    if not telegram_client:
        await init_telegram_client()

    if telegram_client and telegram_client.is_connected():
        try:
            if await telegram_client.is_user_authorized():
                me = await telegram_client.get_me()
                await update.message.reply_text(
                    f"✅ **Already authenticated!**\n\n"
                    f"Connected as: **{me.first_name}** (@{me.username})\n"
                    f"Telegram API is ready for large video uploads.",
                    parse_mode='Markdown'
                )
                return ConversationHandler.END
        except Exception as e:
            logger.warning(f"Auth check failed: {e}")

    
    # Start authentication
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
    
    # Validate phone number
    if not phone.startswith('+') or len(phone) < 10:
        await update.message.reply_text(
            "❌ **Invalid phone number!**\n\n"
            "Please send your phone number in international format:\n"
            "Example: `+1234567890`",
            parse_mode='Markdown'
        )
        return PHONE
    
    try:
        # Create client for this user
        client = TelegramClient(f'bot_session_{user_id}', API_ID, API_HASH)
        auth_clients[user_id] = client
        
        # Send code request
        await client.connect()
        await client.send_code_request(phone)
        
        await update.message.reply_text(
            "📱 **Code sent!**\n\n"
            "A verification code has been sent to your phone.\n"
            "Please send the 5-digit code exactly as received:\n"
            "Example: `12345` or `1 2 3 4 5`",
            parse_mode='Markdown'
        )
        return CODE
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ **Error:** {str(e)}\n\n"
            "Please try again with `/auth`",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

async def code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle verification code input"""
    user_id = update.effective_user.id
    code = update.message.text.strip()
    
    if user_id not in auth_clients:
        await update.message.reply_text(
            "❌ **Session expired!**\n\n"
            "Please start over with `/auth`",
            parse_mode='Markdown'
        )
        return ConversationHandler.END
    
    try:
        client = auth_clients[user_id]
        
        # Format code properly (remove spaces and ensure it's digits)
        code = ''.join(filter(str.isdigit, code))
        
        if len(code) != 5:
            await update.message.reply_text(
                "❌ **Invalid code format!**\n\n"
                "Please enter the 5-digit code exactly as received:\n"
                "Example: `12345` or `1 2 3 4 5`",
                parse_mode='Markdown'
            )
            return CODE
        
        # Sign in with code
        try:
            await client.sign_in(phone=PHONE_NUMBER, code=code)

            # Test connection
            me = await client.get_me()

            # Save session
            await client.disconnect()

            # Copy session file to main session
            import shutil
            if os.path.exists(f'bot_session_{user_id}.session'):
                shutil.copy(f'bot_session_{user_id}.session', 'bot_session.session')
                os.remove(f'bot_session_{user_id}.session')

            # Clean up
            del auth_clients[user_id]

            # Initialize the global telegram client
            global telegram_client
            telegram_client = TelegramClient('bot_session', API_ID, API_HASH)
            await telegram_client.connect()

            # Wait a moment for session file to be fully written
            await asyncio.sleep(2)

            # Prepare success message
            success_message = f"✅ **Authentication successful!**\n\n"
            success_message += f"Connected as: **{me.first_name}** (@{me.username})\n"
            success_message += f"Large video uploads (>50MB) are now enabled!\n\n"

            if FAST_TELETHON_AVAILABLE:
                success_message += f"🚀 **FastTelethon is available!** Ultra-fast uploads will be used."
            else:
                success_message += f"📤 **Standard uploads available.** Large files will use the standard Telegram API."

            await update.message.reply_text(success_message, parse_mode='Markdown')
            return ConversationHandler.END

        except SessionPasswordNeededError:
            # 2FA is enabled, need password
            await update.message.reply_text(
                "🔐 **Two-Factor Authentication Detected!**\n\n"
                "Your account has 2FA enabled. Please send your 2FA password:",
                parse_mode='Markdown'
            )
            return PASSWORD
        
    except Exception as e:
        error_msg = str(e)
        if "code was previously shared" in error_msg.lower():
            await update.message.reply_text(
                "❌ **Code already used!**\n\n"
                "This verification code was already used. Please:\n"
                "1. Wait for a new code\n"
                "2. Or restart with `/auth` to get a fresh code",
                parse_mode='Markdown'
            )
        elif "invalid code" in error_msg.lower():
            await update.message.reply_text(
                "❌ **Invalid code!**\n\n"
                "Please enter the 5-digit code exactly as received:\n"
                "Example: `12345` or `1 2 3 4 5`",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                f"❌ **Authentication failed!**\n\n"
                f"Error: {error_msg}\n"
                f"Please try again with `/auth`",
                parse_mode='Markdown'
            )
        return ConversationHandler.END

async def password_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 2FA password input"""
    user_id = update.effective_user.id
    password = update.message.text.strip()
    
    if user_id not in auth_clients:
        await update.message.reply_text(
            "❌ **Session expired!**\n\n"
            "Please start over with `/auth`",
            parse_mode='Markdown'
        )
        return ConversationHandler.END
    
    try:
        client = auth_clients[user_id]

        # Sign in with password
        await client.sign_in(password=password)

        # Test connection
        me = await client.get_me()

        # Save session
        await client.disconnect()
        
        # Copy session file to main session
        import shutil
        if os.path.exists(f'bot_session_{user_id}.session'):
            shutil.copy(f'bot_session_{user_id}.session', 'bot_session.session')
            os.remove(f'bot_session_{user_id}.session')

        # Clean up
        del auth_clients[user_id]
        
        # Initialize the global telegram client
        global telegram_client
        telegram_client = TelegramClient('bot_session', API_ID, API_HASH)
        await telegram_client.connect()

        # Wait a moment for session file to be fully written
        await asyncio.sleep(2)

        # Prepare success message
        success_message = f"✅ **Authentication successful!**\n\n"
        success_message += f"Connected as: **{me.first_name}** (@{me.username})\n"
        success_message += f"Large video uploads (>50MB) are now enabled!\n\n"

        if FAST_TELETHON_AVAILABLE:
            success_message += f"🚀 **FastTelethon is available!** Ultra-fast uploads will be used."
        else:
            success_message += f"📤 **Standard uploads available.** Large files will use the standard Telegram API."
        
        await update.message.reply_text(success_message, parse_mode='Markdown')
        return ConversationHandler.END
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ **Invalid 2FA password!**\n\n"
            f"Error: {str(e)}\n"
            f"Please try again with `/auth`",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

async def cancel_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel authentication"""
    user_id = update.effective_user.id

    if user_id in auth_clients:
        try:
            await auth_clients[user_id].disconnect()
        except:
            pass
        del auth_clients[user_id]
    
    await update.message.reply_text(
        "❌ **Authentication cancelled!**\n\n"
        "Use `/auth` to try again.",
        parse_mode='Markdown'
    )
    return ConversationHandler.END

async def resend_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resend verification code"""
    user_id = update.effective_user.id

    if user_id not in auth_clients:
        await update.message.reply_text(
            "❌ **No active authentication session!**\n\n"
            "Please start with `/auth` first.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END
    
    try:
        client = auth_clients[user_id]
        await client.send_code_request(PHONE_NUMBER)

        await update.message.reply_text(
            "📱 **New code sent!**\n\n"
            "A fresh verification code has been sent to your phone.\n"
            "Please send the 5-digit code exactly as received:\n"
            "Example: `12345` or `1 2 3 4 5`",
            parse_mode='Markdown'
        )
        return CODE

    except Exception as e:
        await update.message.reply_text(
            f"❌ **Failed to resend code!**\n\n"
            f"Error: {str(e)}\n"
            "Please try `/auth` again.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

# Add the rest of your existing code here (ContentExtractor class, etc.)
# This is just the authentication part - you'll need to copy the rest from o.py

class AdvancedCloudflareBypass:
    """Simplified Cloudflare bypass using only the working Firefox Browser method"""

    def __init__(self):
        self.scraper = None
        self.logger = logging.getLogger(__name__)
        self.setup_scraper()

    def setup_scraper(self):
        """Setup the working Firefox Browser cloudscraper"""
        if not CLOUDSCRAPER_AVAILABLE:
            self.logger.warning("Cloudscraper not available, cannot setup scraper")
            return False

        try:
            # Only use the working Firefox Browser method
            self.scraper = cloudscraper.create_scraper(browser={'browser': 'firefox', 'platform': 'windows', 'mobile': False})
            self.logger.info("✅ Initialized Firefox Browser cloudscraper (working method)")
            return True
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize Firefox cloudscraper: {e}")
            # Fallback to basic scraper
            try:
                self.scraper = cloudscraper.create_scraper()
                self.logger.info("✅ Fallback to basic cloudscraper")
                return True
            except Exception as fallback_error:
                self.logger.error(f"❌ Even fallback scraper failed: {fallback_error}")
                return False

    def get_page_content(self, url, max_retries=3):
        """Get page content using the working Firefox Browser method"""
        if not self.scraper:
            self.logger.error("❌ No cloudscraper available")
            return None
        
        for attempt in range(max_retries):
            try:
                self.logger.info(f"🔄 Trying Firefox Browser (attempt {attempt + 1}/{max_retries})")

                # Add random delay between attempts
                if attempt > 0:
                    delay = random.uniform(1, 3)
                    time.sleep(delay)

                response = self.scraper.get(url, timeout=30)

                if response.status_code == 200:
                    self.logger.info(f"✅ Success with Firefox Browser! Content length: {len(response.text)} characters")
                    return {
                        'content': response.text,
                        'url': response.url,
                        'title': self._extract_title_from_content(response.text)
                    }
                else:
                    self.logger.warning(f"⚠️ Firefox Browser returned status {response.status_code}")

            except Exception as e:
                self.logger.warning(f"⚠️ Firefox Browser failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(random.uniform(2, 5))
        
        self.logger.error("❌ Firefox Browser method failed after all retries")
        return None

    def _extract_title_from_content(self, content):
        """Extract title from HTML content"""
        try:
            soup = BeautifulSoup(content, 'html.parser')
            title_tag = soup.find('title')
            return title_tag.get_text().strip() if title_tag else "No title found"
        except:
            return "No title found"

    def close(self):
        """Close scraper session"""
        if self.scraper:
            try:
                self.scraper.close()
            except:
                pass
            self.scraper = None
        self.logger.info("🔒 Cloudscraper session closed")

class ContentExtractor:
    def __init__(self):
        self.session = requests.Session()
        self.cloudscraper_client = None
        self.logger = logging.getLogger(__name__)

        # Configure session for better reliability with anti-detection headers
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0'
        })

        # Configure session for better connection handling
        adapter = requests.adapters.HTTPAdapter(
            max_retries=3,
            pool_connections=10,
            pool_maxsize=10
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        
        self.temp_dir = tempfile.mkdtemp()
        
        # Initialize aiohttp_chromium session if available
        self.chromium_session = None
        if AIOHTTP_CHROMIUM_AVAILABLE:
            try:
                # Environment-aware configuration for aiohttp_chromium
                self.chromium_session = aiohttp_chromium.ClientSession(
                    headless=IS_VPS,  # Auto-detect based on environment
                    tempdir=None,   # Use system temp directory
                    prevent_focus_stealing=IS_VPS  # Prevent focus issues on VPS
                )
                env_type = "VPS" if IS_VPS else "Local"
                logger.info(f"✅ aiohttp_chromium session initialized for {env_type}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize aiohttp_chromium session: {e}")
                self.chromium_session = None

    async def get_with_chromium_fallback(self, url, max_retries=3):
        """Get URL content with aiohttp_chromium fallback for Cloudflare bypass"""
        try:
            # First try with regular requests
            response = self.session.get(url, timeout=30, allow_redirects=True)
            if response.status_code == 200:
                return response.text

            # If we get a 403 or Cloudflare challenge, try aiohttp_chromium
            if response.status_code in [403, 429, 503] and AIOHTTP_CHROMIUM_AVAILABLE and self.chromium_session:
                logger.info(f"🔄 Cloudflare detected (status {response.status_code}), trying aiohttp_chromium...")

                try:
                    async with self.chromium_session.get(url) as chromium_response:
                        if chromium_response.status == 200:
                            content = await chromium_response.text()
                            logger.info("✅ Successfully bypassed Cloudflare with aiohttp_chromium")
                            return content
                        else:
                            logger.warning(f"⚠️ aiohttp_chromium also failed with status {chromium_response.status}")
                except Exception as e:
                    logger.warning(f"⚠️ aiohttp_chromium failed: {e}")

            # If all else fails, return the original response
            return response.text

        except Exception as e:
            logger.error(f"❌ Error in get_with_chromium_fallback: {e}")
            return None

    def is_imagetwist_url(self, url):
        """Check if URL is from ImageTwist (including all subdomains)"""
        if not url:
            return False
        return 'imagetwist.com' in url.lower()

    def is_vidoza_url(self, url):
        """Check if URL is from Vidoza (including all subdomains)"""
        if not url:
            return False
        return 'vidoza.net' in url.lower()

    def is_streamtape_url(self, url):
        """Check if URL is from Streamtape (including all subdomains)"""
        if not url:
            return False
        return 'streamtape.to' in url.lower() or 'streamtape.com' in url.lower()

    def is_other_image_source(self, url):
        """Check if URL is from other common image hosting services or WordPress uploads"""
        if not url:
            return False
        url_lower = url.lower()
        
        # WordPress uploads directory - prioritize original images
        if '/wp-content/uploads/' in url:
            return True

        return any(domain in url_lower for domain in [
            'imgbox.com', 'hotpic.com', 'imgur.com', 'postimg.cc',
            'imagebam.com', 'pixhost.org', 'imgpile.com', 'imgbb.com',
            'freeimage.host', 'ibb.co', 'imgshare.net'
        ])

    def is_other_video_source(self, url):
        """Check if URL is from other common video hosting services"""
        if not url:
            return False
        url_lower = url.lower()
        return any(domain in url_lower for domain in [
            'streamtape.com', 'doodstream.com', 'streamlare.com',
            'upstream.to', 'streamhub.to', 'streamwish.com',
            'filemoon.sx', 'streamvid.net', 'voe.sx', 'luluvid.com'
        ])

    def is_luluvid_url(self, url):
        """Check if URL is from Luluvid"""
        if not url:
            return False
        return 'luluvid.com' in url.lower()

    def is_stream2z_url(self, url):
        """Check if URL is from Stream2z"""
        if not url:
            return False
        return 'stream2z.com' in url.lower()

    def clean_title(self, title):
        """Clean title by removing site names and extra text"""
        if not title or title == "No title found":
            return title

        # Remove common site suffixes and patterns
        cleaning_patterns = [
            r'\s*-\s*.*?(?:videos?|clips?|movies?|films?)\s*(?:hd|sd)?\s*',  # Remove "- videos hd/sd - sitename"
            r'\s*-\s*[A-Z][a-z]+\s+[a-z]+\s+videos?.*', # Remove "- Site name videos"
            r'\s*-\s*\w+(?:\.\w+)+\s*',  # Remove "- domain.com stuff"
            r'\s*\|\s*.*',  # Remove everything after |
            r'\s*\(\d+\)\s*', # Remove (numbers) at end
            r'\s*\[\d+\]\s*', # Remove [numbers] at end
            r'\s*-\s*sd MMS Masala\s*', # Remove " - MMS Masala"
            r'\s*-\s*MmsDose\s*', # Remove " - MmsDose"
            r'\s*-\s*MMSDose\s*', # Remove " - MMSDose"
            r'\s*-\s*MMS\s+Dose\s*', # Remove " - MMS Dose"
            r'\s*-\s*[A-Z][a-z]+[A-Z][a-z]+\s*', # Remove " - SiteName" patterns
            r'\s*-\s*[A-Z][a-z]+\s*[A-Z][a-z]+\s*', # Remove " - Site Name" patterns
        ]

        clean_title = title
        for pattern in cleaning_patterns:
            clean_title = re.sub(pattern, '', clean_title, flags=re.IGNORECASE)

        # Clean up extra whitespace
        clean_title = ' '.join(clean_title.split())

        # Escape special characters that might cause issues in Telegram
        clean_title = clean_title.replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace(']', '\\]')

        return clean_title

    def extract_title(self, url):
        """Extract title from a given URL with retry logic for connection errors"""
        max_retries = 3
        retry_delay = 2  # seconds

        for attempt in range(max_retries):
            try:
                # Add protocol if missing
                if not url.startswith(('http://', 'https://')):
                    url = 'https://' + url

                # Try with chromium fallback first for better Cloudflare bypass
                if AIOHTTP_CHROMIUM_AVAILABLE and self.chromium_session:
                    try:
                        # Check if we're already in an event loop
                        import asyncio
                        try:
                            loop = asyncio.get_running_loop()
                            # We're in an async context, can't use run_until_complete
                            logger.info("🔄 In async context, skipping aiohttp_chromium for now")
                        except RuntimeError:
                            # No running loop, safe to create one
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            content = loop.run_until_complete(self.get_with_chromium_fallback(url))
                            loop.close()

                            if content:
                                soup = BeautifulSoup(content, 'html.parser')
                                title = soup.find('title')
                                if title and title.text.strip():
                                    return title.text.strip()
                    except Exception as e:
                        logger.warning(f"⚠️ aiohttp_chromium fallback failed: {e}")

                # Fallback to regular requests
                # Special handling for mmsdose.us URLs - use exact headers from test script
                if 'mmsdose.us' in url:
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'DNT': '1',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1',
                        'Sec-Fetch-Dest': 'document',
                        'Sec-Fetch-Mode': 'navigate',
                        'Sec-Fetch-Site': 'same-origin',
                        'Cache-Control': 'max-age=0',
                        'Referer': 'https://mmsdose.us/',
                        'Origin': 'https://mmsdose.us'
                    }
                    # Add a small delay to avoid rate limiting
                    time.sleep(random.uniform(1, 2))
                    response = requests.get(url, headers=headers, timeout=15)
                else:
                    # Use a longer timeout and add retry strategy
                    response = self.session.get(url, timeout=15)
                response.raise_for_status()

                soup = BeautifulSoup(response.content, 'html.parser')

                title = None

                # Look for a span with both 'ipsType_break' and 'ipsContained' classes
                span_title = soup.find('span', class_=['ipsType_break', 'ipsContained'])
                if span_title:
                    # Assuming the actual title is in a nested span
                    nested_span = span_title.find('span')
                    if nested_span:
                        title = nested_span.get_text(strip=True)
                        if title: # If we found it here, use it and clean it
                            return ' '.join(title.split())

                if soup.title:
                    title = soup.title.string

                if not title:
                    og_title = soup.find('meta', property='og:title')
                    if og_title:
                        title = og_title.get('content')

                if not title:
                    twitter_title = soup.find('meta', name='twitter:title')
                    if twitter_title:
                        title = twitter_title.get('content')

                if not title:
                    h1 = soup.find('h1')
                    if h1:
                        title = h1.get_text()

                if title:
                    title = ' '.join(title.split())
                    return title
                else:
                    return "No title found"

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 403:
                    logger.warning(f"🛡️ 403 Forbidden error for {url}, trying cloudscraper bypass...")
                    return self._extract_title_with_cloudscraper(url)
                else:
                    if attempt < max_retries - 1:
                        logger.warning(f"⚠️ HTTP error {e.response.status_code} on attempt {attempt + 1}/{max_retries} for {url}")
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    else:
                        logger.error(f"❌ HTTP error {e.response.status_code} after {max_retries} attempts for {url}")
                        return f"HTTP Error {e.response.status_code}: {str(e)}"
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                    requests.exceptions.RequestException, ConnectionResetError) as e:
                if attempt < max_retries - 1:
                    logger.warning(f"⚠️ Connection error on attempt {attempt + 1}/{max_retries} for {url}: {str(e)}")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                    continue
                else:
                    logger.error(f"❌ Failed to fetch title after {max_retries} attempts for {url}: {str(e)}")
                    return f"Error fetching URL: {str(e)}"
            except Exception as e:
                logger.error(f"❌ Unexpected error extracting title from {url}: {str(e)}")
                return f"Error extracting title: {str(e)}"

        return "Error fetching URL: Max retries exceeded"

    def _extract_title_with_cloudscraper(self, url):
        """Extract title using cloudscraper as fallback for 403 errors"""
        if not CLOUDSCRAPER_AVAILABLE:
            self.logger.warning("Cloudscraper not available for 403 bypass")
            return "Error: 403 Forbidden (Cloudscraper not available)"

        try:
            # Initialize cloudscraper client if not already done
            if not self.cloudscraper_client:
                self.cloudscraper_client = AdvancedCloudflareBypass()

            # Get page content using cloudscraper
            result = self.cloudscraper_client.get_page_content(url)
            if result and result.get('content'):
                soup = BeautifulSoup(result['content'], 'html.parser')

                # Try different title extraction methods
                title = None

                # Method 1: Standard title tag
                title_tag = soup.find('title')
                if title_tag and title_tag.get_text().strip():
                    title = title_tag.get_text().strip()

                # Method 2: Open Graph title
                if not title:
                    og_title = soup.find('meta', property='og:title')
                    if og_title and og_title.get('content'):
                        title = og_title.get('content').strip()

                # Method 3: Twitter card title
                if not title:
                    twitter_title = soup.find('meta', name='twitter:title')
                    if twitter_title and twitter_title.get('content'):
                        title = twitter_title.get('content').strip()

                # Method 4: H1 tag as fallback
                if not title:
                    h1_tag = soup.find('h1')
                    if h1_tag and h1_tag.get_text().strip():
                        title = h1_tag.get_text().strip()

                if title:
                    self.logger.info(f"✅ Successfully extracted title using cloudscraper: {title}")
                    return title
                else:
                    return "No title found (cloudscraper)"
            else:
                self.logger.error("❌ Cloudscraper failed to get page content")
                return "Error: Cloudscraper failed to load page"

        except Exception as e:
            self.logger.error(f"❌ Cloudscraper error extracting title: {e}")
            return f"Error: Cloudscraper failed - {str(e)}"

    def extract_imagetwist_urls(self, url):
        """Extract ImageTwist image URLs from a webpage with retry logic"""
        max_retries = 3
        retry_delay = 2  # seconds

        for attempt in range(max_retries):
            try:
                # Add protocol if missing
                if not url.startswith(('http://', 'https://')):
                    url = 'https://' + url

                # Special handling for mmsdose.us URLs - use exact headers from test script
                if 'mmsdose.us' in url:
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'DNT': '1',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1',
                        'Sec-Fetch-Dest': 'document',
                        'Sec-Fetch-Mode': 'navigate',
                        'Sec-Fetch-Site': 'same-origin',
                        'Cache-Control': 'max-age=0',
                        'Referer': 'https://mmsdose.us/',
                        'Origin': 'https://mmsdose.us'
                    }
                    time.sleep(random.uniform(1, 2))
                    response = requests.get(url, headers=headers, timeout=15)
                else:
                    response = self.session.get(url, timeout=15)
                response.raise_for_status()

                soup = BeautifulSoup(response.content, 'html.parser')
                imagetwist_urls = []

                img_tags = soup.find_all('img')

                for img in img_tags:
                    src = img.get('src')
                    if src and self.is_imagetwist_url(src):
                        imagetwist_urls.append({
                            'url': src,
                            'alt': img.get('alt', ''),
                            'type': 'src'
                        })

                    data_src = img.get('data-src')
                    if data_src and self.is_imagetwist_url(data_src):
                        imagetwist_urls.append({
                            'url': data_src,
                            'alt': img.get('alt', ''),
                            'type': 'data-src'
                        })

                seen_urls = set()
                unique_urls = []
                for item in imagetwist_urls:
                    if item['url'] not in seen_urls:
                        seen_urls.add(item['url'])
                        unique_urls.append(item)

                return unique_urls

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 403:
                    logger.warning(f"🛡️ 403 Forbidden error for {url}, trying cloudscraper bypass for images...")
                    return self._extract_images_with_cloudscraper(url)
                else:
                    if attempt < max_retries - 1:
                        logger.warning(f"⚠️ HTTP error {e.response.status_code} on attempt {attempt + 1}/{max_retries} for ImageTwist extraction")
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    else:
                        logger.error(f"❌ HTTP error {e.response.status_code} after {max_retries} attempts for ImageTwist extraction")
                        return f"HTTP Error {e.response.status_code}: {str(e)}"
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                    requests.exceptions.RequestException, ConnectionResetError) as e:
                if attempt < max_retries - 1:
                    logger.warning(f"⚠️ Connection error on attempt {attempt + 1}/{max_retries} for ImageTwist extraction: {str(e)}")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                    continue
                else:
                    logger.error(f"❌ Failed to extract ImageTwist URLs after {max_retries} attempts: {str(e)}")
                    return f"Error extracting ImageTwist URLs: {str(e)}"
            except Exception as e:
                logger.error(f"❌ Unexpected error extracting ImageTwist URLs: {str(e)}")
                return f"Error extracting ImageTwist URLs: {str(e)}"

        return f"Error extracting ImageTwist URLs: Max retries exceeded"

    def _extract_images_with_cloudscraper(self, url):
        """Extract images using cloudscraper as fallback for 403 errors"""
        if not CLOUDSCRAPER_AVAILABLE:
            self.logger.warning("Cloudscraper not available for 403 bypass")
            return "Error: 403 Forbidden (Cloudscraper not available)"

        try:
            # Initialize cloudscraper client if not already done
            if not self.cloudscraper_client:
                self.cloudscraper_client = AdvancedCloudflareBypass()

            # Get page content using cloudscraper
            result = self.cloudscraper_client.get_page_content(url)
            if result and result.get('content'):
                soup = BeautifulSoup(result['content'], 'html.parser')
                imagetwist_urls = []

                img_tags = soup.find_all('img')

                for img in img_tags:
                    src = img.get('src')
                    if src and (self.is_imagetwist_url(src) or self.is_other_image_source(src)):
                        imagetwist_urls.append({
                            'url': src,
                            'alt': img.get('alt', ''),
                            'type': 'src'
                        })

                    data_src = img.get('data-src')
                    if data_src and (self.is_imagetwist_url(data_src) or self.is_other_image_source(data_src)):
                        imagetwist_urls.append({
                            'url': data_src,
                            'alt': img.get('alt', ''),
                            'type': 'data-src'
                        })

                seen_urls = set()
                unique_urls = []
                for item in imagetwist_urls:
                    if item['url'] not in seen_urls:
                        seen_urls.add(item['url'])
                        unique_urls.append(item)

                # If no specific image sources found, try to find any image-like URLs including WordPress
                if len(unique_urls) == 0:
                    self.logger.info("No specific image sources found, looking for any image-like URLs...")
                    all_links = soup.find_all('a', href=True)
                    for link in all_links:
                        href = link.get('href')
                        # Check for image file extensions or WordPress uploads
                        if href and (any(ext in href.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']) or '/wp-content/uploads/' in href):
                            # For WordPress uploads, ONLY accept original quality versions
                            if '/wp-content/uploads/' in href:
                                # REJECT all thumbnail sizes
                                if any(size in href.lower() for size in [
                                    '-16x16', '-32x32', '-48x48', '-64x64', '-75x75', '-96x96',
                                    '-100x100', '-150x150', '-200x200', '-300x300', '-400x400',
                                    '-thumbnail', '-thumb', '-small', '-medium', '-large'
                                ]):
                                    continue  # Skip ALL thumbnails

                                # Get original version
                                href = re.sub(r'-\d+x\d+(?=\.[a-z]+)', '', href)
                                href = re.sub(r'-scaled(?=\.[a-z]+)', '', href)

                                # ONLY add if it passes quality check
                                if href and not any(size in href for size in ['x', '-thumb', '-small']):
                                    imagetwist_urls.append({
                                        'url': href,
                                        'alt': link.get_text(strip=True),
                                        'type': 'wordpress_original'
                                    })
                            else:
                                # For non-WordPress, add regular image links
                                imagetwist_urls.append({
                                    'url': href,
                                    'alt': link.get_text(strip=True),
                                    'type': 'link'
                                })

                    # Also look for image URLs in text content, including WordPress uploads
                    text_content = soup.get_text()
                    # Look for WordPress uploads in text - ONLY accept originals
                    wp_pattern = r'https?://[^\s]+/wp-content/uploads/[^\s]+\.[a-z]+'
                    wp_matches = re.findall(wp_pattern, text_content, re.IGNORECASE)
                    for match in wp_matches:
                        # REJECT thumbnail versions
                        if any(size in match.lower() for size in [
                            '-16x16', '-32x32', '-48x48', '-64x64', '-75x75', '-96x96',
                            '-100x100', '-150x150', '-200x200', '-300x300', '-400x400',
                            '-thumbnail', '-thumb', '-small', '-medium', '-large'
                        ]):
                            continue  # Skip ALL thumbnails

                        # Get original version
                        original_match = re.sub(r'-\d+x\d+(?=\.[a-z]+)', '', match)
                        original_match = re.sub(r'-scaled(?=\.[a-z]+)', '', original_match)

                        # ONLY add high-quality originals
                        if original_match and not any(item['url'] == original_match for item in imagetwist_urls):
                            imagetwist_urls.append({
                                'url': original_match,
                                'alt': '',
                                'type': 'wordpress_original'
                            })

                    # Look for regular image file extensions
                    image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']
                    for ext in image_extensions:
                        pattern = rf'https?://[^\s]+{re.escape(ext)}'
                        matches = re.findall(pattern, text_content, re.IGNORECASE)
                        for match in matches:
                            if not any(item['url'] == match for item in imagetwist_urls):
                                imagetwist_urls.append({
                                    'url': match,
                                    'alt': '',
                                    'type': 'text'
                                })

                    # Update unique_urls with any new findings
                    seen_urls = set()
                    unique_urls = []
                    for item in imagetwist_urls:
                        if item['url'] not in seen_urls:
                            seen_urls.add(item['url'])
                            unique_urls.append(item)

                self.logger.info(f"✅ Successfully extracted {len(unique_urls)} images using cloudscraper")
                return unique_urls
            else:
                self.logger.error("❌ Cloudscraper failed to get page content for images")
                return "Error: Cloudscraper failed to load page"

        except Exception as e:
            self.logger.error(f"❌ Cloudscraper error extracting images: {e}")
            return f"Error: Cloudscraper failed - {str(e)}"

    def extract_vidoza_urls(self, url):
        """Extract Vidoza URLs from a webpage"""
        try:
            # Add protocol if missing
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url

            response = self.session.get(url, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            vidoza_urls = []

            a_tags = soup.find_all('a', href=True)

            for a in a_tags:
                href = a.get('href')
                if href and self.is_vidoza_url(href):
                    vidoza_urls.append({
                        'url': href,
                        'text': a.get_text(strip=True),
                        'title': a.get('title', '')
                    })

            text_content = soup.get_text()
            vidoza_pattern = r'https?://(?:www\.)?vidoza\.net/[a-zA-Z0-9]+\.html'
            text_urls = re.findall(vidoza_pattern, text_content)

            for text_url in text_urls:
                if not any(item['url'] == text_url for item in vidoza_urls):
                    vidoza_urls.append({
                        'url': text_url,
                        'text': '',
                        'title': ''
                    })

            seen_urls = set()
            unique_urls = []
            for item in vidoza_urls:
                if item['url'] not in seen_urls:
                    seen_urls.add(item['url'])
                    unique_urls.append(item)

            return unique_urls

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 403:
                logger.warning(f"🛡️ 403 Forbidden error for {url}, trying cloudscraper bypass for videos...")
                return self._extract_videos_with_cloudscraper(url)
            else:
                logger.error(f"❌ HTTP error {e.response.status_code} for Vidoza extraction")
                return f"HTTP Error {e.response.status_code}: {str(e)}"
        except Exception as e:
            return f"Error extracting Vidoza URLs: {str(e)}"

    def _extract_videos_with_cloudscraper(self, url):
        """Extract videos using cloudscraper as fallback for 403 errors"""
        if not CLOUDSCRAPER_AVAILABLE:
            self.logger.warning("Cloudscraper not available for 403 bypass")
            return "Error: 403 Forbidden (Cloudscraper not available)"

        try:
            # Initialize cloudscraper client if not already done
            if not self.cloudscraper_client:
                self.cloudscraper_client = AdvancedCloudflareBypass()

            # Get page content using cloudscraper
            result = self.cloudscraper_client.get_page_content(url)
            if result and result.get('content'):
                soup = BeautifulSoup(result['content'], 'html.parser')
                vidoza_urls = []

                a_tags = soup.find_all('a', href=True)

                for a in a_tags:
                    href = a.get('href')
                    if href and self.is_vidoza_url(href):
                        vidoza_urls.append({
                            'url': href,
                            'text': a.get_text(strip=True),
                            'title': a.get('title', '')
                        })

                text_content = soup.get_text()
                # Look for multiple video hosting patterns
                video_patterns = [
                    r'https?://(?:www\.)?vidoza\.net/[a-zA-Z0-9]+\.html',
                    r'https?://(?:www\.)?streamtape\.(?:com|to)/[a-zA-Z0-9]+',
                    r'https?://(?:www\.)?doodstream\.com/[a-zA-Z0-9]+',
                    r'https?://(?:www\.)?streamlare\.com/[a-zA-Z0-9]+',
                    r'https?://(?:www\.)?luluvid\.com/[a-zA-Z0-9]+'
                ]

                for pattern in video_patterns:
                    text_urls = re.findall(pattern, text_content)
                    for text_url in text_urls:
                        if not any(item['url'] == text_url for item in vidoza_urls):
                            vidoza_urls.append({
                                'url': text_url,
                                'text': '',
                                'title': ''
                            })

                seen_urls = set()
                unique_urls = []
                for item in vidoza_urls:
                    if item['url'] not in seen_urls:
                        seen_urls.add(item['url'])
                        unique_urls.append(item)

                # If no specific video sources found, try to find any video-like URLs
                if len(unique_urls) == 0:
                    self.logger.info("No specific video sources found, looking for any video-like URLs...")
                    all_links = soup.find_all('a', href=True)
                    for link in all_links:
                        href = link.get('href')
                        if href and any(ext in href.lower() for ext in ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm']):
                            vidoza_urls.append({
                                'url': href,
                                'text': link.get_text(strip=True),
                                'title': link.get('title', '')
                            })

                    # Also look for video URLs in text content
                    text_content = soup.get_text()
                    video_extensions = ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm']
                    for ext in video_extensions:
                        pattern = rf'https?://[^\s]+{re.escape(ext)}'
                        matches = re.findall(pattern, text_content, re.IGNORECASE)
                        for match in matches:
                            if not any(item['url'] == match for item in vidoza_urls):
                                vidoza_urls.append({
                                    'url': match,
                                    'text': '',
                                    'title': ''
                                })

                    # Update unique_urls with any new findings
                    seen_urls = set()
                    unique_urls = []
                    for item in vidoza_urls:
                        if item['url'] not in seen_urls:
                            seen_urls.add(item['url'])
                            unique_urls.append(item)

                self.logger.info(f"✅ Successfully extracted {len(unique_urls)} videos using cloudscraper")
                return unique_urls
            else:
                self.logger.error("❌ Cloudscraper failed to get page content for videos")
                return "Error: Cloudscraper failed to load page"

        except Exception as e:
            self.logger.error(f"❌ Cloudscraper error extracting videos: {e}")
            return f"Error: Cloudscraper failed - {str(e)}"

    def extract_vidoza_video_url(self, vidoza_url):
        """Extract direct MP4 URL from Vidoza page"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Referer': 'https://vidoza.net/'
            }

            response = self.session.get(vidoza_url, headers=headers, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            video_tag = soup.find('video', id='player_html5_api')
            if video_tag:
                src = video_tag.get('src')
                if src and src.endswith('.mp4'):
                    return src

            source_tags = soup.find_all('source', type='video/mp4')
            for source in source_tags:
                src = source.get('src')
                if src and src.endswith('.mp4'):
                    return src

            all_videos = soup.find_all('video')
            for video in all_videos:
                src = video.get('src')
                if src and '.mp4' in src:
                    return src

                sources = video.find_all('source')
                for source in sources:
                    src = source.get('src')
                    if src and '.mp4' in src:
                        return src

            script_tags = soup.find_all('script')
            for script in script_tags:
                if script.string:
                    mp4_matches = re.findall(r'https?://[^"\']+\.mp4', script.string)
                    if mp4_matches:
                        return mp4_matches[0]

            return None

        except Exception as e:
            logger.error(f"Error extracting video URL from {vidoza_url}: {e}")
            return None

    def extract_streamtape_urls(self, url):
        """Extract Streamtape URLs from a webpage - prioritize links over text"""
        try:
            print(f"🔍 STREAMTAPE DEBUG: Starting extraction from: {url}")

            # Add protocol if missing
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url

            # Try regular request first
            try:
                response = self.session.get(url, timeout=15)
                response.raise_for_status()
                print(f"🔍 STREAMTAPE DEBUG: Successfully fetched page with regular request, content length: {len(response.content)}")
            except Exception as e:
                print(f"🔍 STREAMTAPE DEBUG: Regular request failed ({e}), trying cloudscraper...")
                # Try with cloudscraper if regular request fails
                try:
                    scraper = cloudscraper.create_scraper(browser={'browser': 'firefox', 'platform': 'windows', 'mobile': False})
                    response = scraper.get(url, timeout=15)
                    response.raise_for_status()
                    print(f"🔍 STREAMTAPE DEBUG: Successfully fetched page with cloudscraper, content length: {len(response.content)}")
                except Exception as cloudscraper_error:
                    print(f"🔍 STREAMTAPE DEBUG: ❌ Both regular and cloudscraper requests failed: {cloudscraper_error}")
                    return f"Error extracting Streamtape URLs: {str(cloudscraper_error)}"

            soup = BeautifulSoup(response.content, 'html.parser')
            streamtape_urls = []

            # Method 1: Extract from <a> tags (PRIORITY)
            a_tags = soup.find_all('a', href=True)
            print(f"🔍 STREAMTAPE DEBUG: Found {len(a_tags)} total <a> tags with href")

            streamtape_links_found = 0
            for a in a_tags:
                href = a.get('href')
                if href and 'streamtape' in href.lower():
                    print(f"🔍 STREAMTAPE DEBUG: Found potential streamtape link: {href}")
                    if self.is_streamtape_url(href):
                        streamtape_urls.append({
                            'url': href,
                            'text': a.get_text(strip=True),
                            'title': a.get('title', '')
                        })
                        streamtape_links_found += 1
                        print(f"🔍 STREAMTAPE DEBUG: ✅ Valid streamtape URL from link: {href}")
                    else:
                        print(f"🔍 STREAMTAPE DEBUG: ❌ Invalid streamtape URL: {href}")

            print(f"🔍 STREAMTAPE DEBUG: Found {streamtape_links_found} valid streamtape URLs from links")

            # Method 2: Extract from text content (only if no links found)
            if not streamtape_urls:  # Only search text if no links were found
                print(f"🔍 STREAMTAPE DEBUG: No links found, searching text content...")
                text_content = soup.get_text()
                print(f"🔍 STREAMTAPE DEBUG: Text content length: {len(text_content)}")

                # Pattern to match Streamtape URLs (both /v/ and /e/ formats) - more flexible
                # Support both .com and .to domains
                streamtape_pattern = r'https?://(?:www\.)?streamtape\.(?:to|com)/(?:v|e)/[a-zA-Z0-9]+(?:/[^/\s]*)?(?:\.html)?'
                text_urls = re.findall(streamtape_pattern, text_content)

                # Debug: Print found URLs
                print(f"🔍 STREAMTAPE DEBUG: Found {len(streamtape_urls)} Streamtape URLs from links")
                print(f"🔍 STREAMTAPE DEBUG: Found {len(text_urls)} Streamtape URLs from text pattern")
                print(f"🔍 STREAMTAPE DEBUG: Text URLs found: {text_urls}")

                # Also search for any streamtape mentions in text
                streamtape_mentions = re.findall(r'streamtape[^\s]*', text_content, re.IGNORECASE)
                print(f"🔍 STREAMTAPE DEBUG: Found {len(streamtape_mentions)} streamtape mentions in text: {streamtape_mentions[:5]}")

                if text_urls:
                    # Take only the first text URL found
                    streamtape_urls.append({
                        'url': text_urls[0],
                        'text': '',
                        'title': ''
                    })
                    print(f"🔍 STREAMTAPE DEBUG: ✅ Found Streamtape URL from text: {text_urls[0]}")
            else:
                print(f"🔍 STREAMTAPE DEBUG: Skipping text search - already found {len(streamtape_urls)} URLs from links")

            print(f"🔍 STREAMTAPE DEBUG: Final result - {len(streamtape_urls)} streamtape URLs found")
            for i, url_obj in enumerate(streamtape_urls):
                print(f"🔍 STREAMTAPE DEBUG: URL {i+1}: {url_obj['url']}")

            return streamtape_urls

        except Exception as e:
            print(f"🔍 STREAMTAPE DEBUG: ❌ Error: {str(e)}")
            return f"Error extracting Streamtape URLs: {str(e)}"

    def extract_luluvid_urls(self, url):
        """Extract Luluvid URLs from a webpage - prioritize links over text"""
        try:
            print(f"🔍 LULUVID DEBUG: Starting extraction from: {url}")

            # Add protocol if missing
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url

            # Try regular request first
            try:
                response = self.session.get(url, timeout=15)
                response.raise_for_status()
                print(f"🔍 LULUVID DEBUG: Successfully fetched page with regular request, content length: {len(response.content)}")
            except Exception as e:
                print(f"🔍 LULUVID DEBUG: Regular request failed ({e}), trying cloudscraper...")
                # Try with cloudscraper if regular request fails
                try:
                    scraper = cloudscraper.create_scraper(browser={'browser': 'firefox', 'platform': 'windows', 'mobile': False})
                    response = scraper.get(url, timeout=15)
                    response.raise_for_status()
                    print(f"🔍 LULUVID DEBUG: Successfully fetched page with cloudscraper, content length: {len(response.content)}")
                except Exception as cloudscraper_error:
                    print(f"🔍 LULUVID DEBUG: ❌ Both regular and cloudscraper requests failed: {cloudscraper_error}")
                    return f"Error extracting Luluvid URLs: {str(cloudscraper_error)}"

            soup = BeautifulSoup(response.content, 'html.parser')
            luluvid_urls = []

            # Method 1: Extract from <a> tags (PRIORITY)
            a_tags = soup.find_all('a', href=True)
            print(f"🔍 LULUVID DEBUG: Found {len(a_tags)} total <a> tags with href")

            luluvid_links_found = 0
            for a in a_tags:
                href = a.get('href')
                if href and 'luluvid' in href.lower():
                    print(f"🔍 LULUVID DEBUG: Found potential luluvid link: {href}")
                    if self.is_luluvid_url(href):
                        luluvid_urls.append({
                            'url': href,
                            'text': a.get_text(strip=True),
                            'title': a.get('title', '')
                        })
                        luluvid_links_found += 1
                        print(f"🔍 LULUVID DEBUG: ✅ Valid luluvid URL from link: {href}")
                    else:
                        print(f"🔍 LULUVID DEBUG: ❌ Invalid luluvid URL: {href}")

            print(f"🔍 LULUVID DEBUG: Found {luluvid_links_found} valid luluvid URLs from links")

            # Method 2: Extract from text content (only if no links found)
            if not luluvid_urls:  # Only search text if no links were found
                print(f"🔍 LULUVID DEBUG: No links found, searching text content...")
                text_content = soup.get_text()
                print(f"🔍 LULUVID DEBUG: Text content length: {len(text_content)}")

                # Pattern to match Luluvid URLs
                luluvid_pattern = r'https?://(?:www\.)?luluvid\.com/[a-zA-Z0-9]+'
                text_urls = re.findall(luluvid_pattern, text_content)

                # Debug: Print found URLs
                print(f"🔍 LULUVID DEBUG: Found {len(luluvid_urls)} Luluvid URLs from links")
                print(f"🔍 LULUVID DEBUG: Found {len(text_urls)} Luluvid URLs from text pattern")
                print(f"🔍 LULUVID DEBUG: Text URLs found: {text_urls}")

                # Also search for any luluvid mentions in text
                luluvid_mentions = re.findall(r'luluvid[^\s]*', text_content, re.IGNORECASE)
                print(f"🔍 LULUVID DEBUG: Found {len(luluvid_mentions)} luluvid mentions in text: {luluvid_mentions[:5]}")

                if text_urls:
                    # Take only the first text URL found
                    luluvid_urls.append({
                        'url': text_urls[0],
                        'text': '',
                        'title': ''
                    })
                    print(f"🔍 LULUVID DEBUG: ✅ Found Luluvid URL from text: {text_urls[0]}")
            else:
                print(f"🔍 LULUVID DEBUG: Skipping text search - already found {len(luluvid_urls)} URLs from links")

            print(f"🔍 LULUVID DEBUG: Final result - {len(luluvid_urls)} luluvid URLs found")
            for i, url_obj in enumerate(luluvid_urls):
                print(f"🔍 LULUVID DEBUG: URL {i+1}: {url_obj['url']}")

            return luluvid_urls

        except Exception as e:
            print(f"🔍 LULUVID DEBUG: ❌ Error: {str(e)}")
            return f"Error extracting Luluvid URLs: {str(e)}"

    def extract_streamtape_video_url(self, streamtape_url):
        """Extract direct MP4 URL from Streamtape page using the improved method"""
        try:
            # Validate the URL first
            if not streamtape_url:
                return None

            # Convert embed URLs to video URLs
            if "/e/" in streamtape_url:
                streamtape_url = streamtape_url.replace("/e/", "/v/")

            response = self.session.get(streamtape_url)
            response.raise_for_status()
            html_source = response.text

            norobot_link_pattern = re.compile(r"document\.getElementById\('norobotlink'\)\.innerHTML = (.+?);")
            norobot_link_matcher = norobot_link_pattern.search(html_source)

            if norobot_link_matcher:
                norobot_link_content = norobot_link_matcher.group(1)

                token_pattern = re.compile(r"token=([^&']+)")
                token_matcher = token_pattern.search(norobot_link_content)

                if token_matcher:
                    token = token_matcher.group(1)

                    soup = BeautifulSoup(html_source, 'html.parser')
                    div_element = soup.select_one("div#ideoooolink[style='display:none;']")

                    if div_element:
                        streamtape = div_element.get_text()
                        full_url = f"https:/{streamtape}&token={token}"
                        return f"{full_url}&dl=1"

        except Exception as exception:
            print(f"An error occurred: {exception}")

            return None

    def extract_stream2z_urls(self, url):
        """Extract Stream2z URLs from a webpage"""
        try:
            # Add protocol if missing
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url

            response = self.session.get(url, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            stream2z_urls = []

            # Method 1: Extract from <a> tags (PRIORITY)
            a_tags = soup.find_all('a', href=True)

            for a in a_tags:
                href = a.get('href')
                if href and self.is_stream2z_url(href):
                    stream2z_urls.append({
                        'url': href,
                        'text': a.get_text(strip=True),
                        'title': a.get('title', '')
                    })

            # Method 2: Extract from text content (only if no links found)
            if not stream2z_urls:
                text_content = soup.get_text()
                stream2z_pattern = r'https?://(?:www\.)?stream2z\.com/[a-zA-Z0-9]+'
                text_urls = re.findall(stream2z_pattern, text_content)

                if text_urls:
                    stream2z_urls.append({
                        'url': text_urls[0],
                        'text': '',
                        'title': ''
                    })

            return stream2z_urls

        except Exception as e:
            return f"Error extracting Stream2z URLs: {str(e)}"

    def extract_stream2z_video_url(self, stream2z_url):
        """Extract direct video URL from Stream2z page"""
        try:
            # Validate the URL first
            if not stream2z_url:
                return None

            response = self.session.get(stream2z_url)
            response.raise_for_status()
            html_source = response.text

            # Look for direct video URLs in the page
            video_pattern = re.compile(r'https?://[^"\s]+\.mp4[^"\s]*')
            video_matches = video_pattern.findall(html_source)

            if video_matches:
                return video_matches[0]

            # Look for other video formats
            video_pattern2 = re.compile(r'https?://[^"\s]+\.(?:mp4|avi|mkv|mov|wmv|flv)[^"\s]*')
            video_matches2 = video_pattern2.findall(html_source)

            if video_matches2:
                return video_matches2[0]

            return None

        except Exception as e:
            print(f"Error extracting Stream2z video URL: {e}")
            return None

    def extract_luluvid_video_url(self, luluvid_url):
        """Extract direct video URL from Luluvid page"""
        try:
            # Validate the URL first
            if not luluvid_url:
                return None

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Referer': 'https://luluvid.com/'
            }

            response = self.session.get(luluvid_url, headers=headers, timeout=15)
            response.raise_for_status()

            text_content = response.text

            # Method 1: Look for JWPlayer setup with sources
            jwplayer_pattern = r'jwplayer\s*\(\s*["\'][^"\']*["\']\s*\)\s*\.setup\s*\(\s*\{[^}]*sources\s*:\s*\[\s*\{[^}]*file\s*:\s*["\']([^"\']+)["\']'
            jwplayer_match = re.search(jwplayer_pattern, text_content, re.IGNORECASE | re.DOTALL)
            if jwplayer_match:
                master_m3u8_url = jwplayer_match.group(1)
                self.logger.info(f"✅ Found JWPlayer master M3U8: {master_m3u8_url}")

                # Get the index M3U8 URL from the master playlist
                index_m3u8_url = self._get_index_m3u8_url_sync(master_m3u8_url, luluvid_url)
                if index_m3u8_url:
                    self.logger.info(f"✅ Found index M3U8 URL: {index_m3u8_url}")
                    return index_m3u8_url
                else:
                    # Fallback to master M3U8 if index extraction fails
                    return master_m3u8_url

            # Method 2: Look for direct MP4 links in page content
            mp4_pattern = r'https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*'
            mp4_matches = re.findall(mp4_pattern, text_content, re.IGNORECASE)
            if mp4_matches:
                self.logger.info(f"✅ Found direct MP4 URL: {mp4_matches[0]}")
                return mp4_matches[0]

            # Method 3: Look for M3U8 (HLS) streams
            m3u8_pattern = r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*'
            m3u8_matches = re.findall(m3u8_pattern, text_content, re.IGNORECASE)
            if m3u8_matches:
                self.logger.info(f"✅ Found M3U8 stream URL: {m3u8_matches[0]}")
                return m3u8_matches[0]

            # Method 4: Look for tnmr.org URLs (common luluvid CDN)
            tnmr_pattern = r'https?://[^\s"\'<>]*tnmr\.org[^\s"\'<>]*'
            tnmr_matches = re.findall(tnmr_pattern, text_content, re.IGNORECASE)
            if tnmr_matches:
                self.logger.info(f"✅ Found tnmr.org URL: {tnmr_matches[0]}")
                return tnmr_matches[0]

            # Method 5: Look for JavaScript variables that might contain video URLs
            js_patterns = [
                r'["\']([^"\']*\.mp4[^"\']*)["\']',
                r'["\']([^"\']*\.m3u8[^"\']*)["\']',
                r'src\s*[:=]\s*["\']([^"\']*\.mp4[^"\']*)["\']',
                r'file\s*[:=]\s*["\']([^"\']*\.mp4[^"\']*)["\']',
                r'file\s*[:=]\s*["\']([^"\']*\.m3u8[^"\']*)["\']'
            ]

            for pattern in js_patterns:
                matches = re.findall(pattern, text_content, re.IGNORECASE)
                for match in matches:
                    if match.startswith('http'):
                        self.logger.info(f"✅ Found video URL in JS: {match}")
                        return match

            self.logger.warning(f"❌ No video URL found in {luluvid_url}")
            return None

        except Exception as e:
            self.logger.error(f"Error extracting video URL from {luluvid_url}: {e}")
            return None

    def extract_luluvid_video_url(self, luluvid_url):
        """Extract direct video URL from Luluvid page using EXACT video_extractor.py method"""
        try:
            # Import os at the start
            import os

            # Use the yt-dlp approach (most reliable for Luluvid)
            result = self.download_luluvid_with_ytdlp(luluvid_url)
            if result and os.path.exists(result):
                # Return the downloaded file path instead of URL for compatibility
                return result
            return None

        except Exception as e:
            self.logger.error(f"Error extracting video URL from {luluvid_url}: {e}")
            return None

    def _get_index_m3u8_url_sync(self, master_m3u8_url, referrer_url=None):
        """Extract index M3U8 URL from master playlist (synchronous)"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/vnd.apple.mpegurl,application/x-mpegURL,*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Referer': referrer_url or 'https://luluvid.com/'
            }

            response = self.session.get(master_m3u8_url, headers=headers, timeout=15)
            response.raise_for_status()

            playlist_content = response.text
            self.logger.info(f"📄 Master playlist downloaded: {len(playlist_content)} characters")

            # Parse master playlist to find index M3U8
            lines = playlist_content.split('\n')
            base_url = '/'.join(master_m3u8_url.split('/')[:-1]) + '/'

            for line in lines:
                line = line.strip()
                if line and not line.startswith('#') and '.m3u8' in line:
                    if line.startswith('http'):
                        return line
                    else:
                        return base_url + line

            self.logger.warning("❌ No index M3U8 found in master playlist")
            return None

        except Exception as e:
            self.logger.error(f"❌ Error getting index M3U8 URL: {e}")
            return None

    async def download_image_async(self, image_url, filename=None, referrer_url=None):
        """Download image directly from the source URL using aiohttp (FASTER)"""
        try:
            final_url = image_url

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Sec-Fetch-Dest': 'image',
                'Sec-Fetch-Mode': 'no-cors',
                'Sec-Fetch-Site': 'cross-site',
            }

            if referrer_url:
                headers['Referer'] = referrer_url
            elif self.is_imagetwist_url(final_url):
                headers['Referer'] = 'https://imagetwist.com/'

            if not filename:
                parsed_url = urlparse(final_url)
                filename = os.path.basename(parsed_url.path)
                if not filename or '.' not in filename:
                    match = re.search(r'/([^/]+\.(jpg|jpeg|png|gif|webp))$', final_url, re.I)
                    if match:
                        filename = match.group(1)
                    else:
                        filename = 'image.jpg'

            file_path = os.path.join(self.temp_dir, filename)

            async with aiohttp.ClientSession() as session:
                async with session.get(final_url, headers=headers, timeout=aiohttp.ClientTimeout(total=30), allow_redirects=True) as response:
                    if response.status not in [200, 206]:
                        logger.error(f"HTTP {response.status}: {response.reason}")
                        return None

                    content_type = response.headers.get('content-type', '').lower()

                    if ('text/html' in content_type or
                        b'error' in (await response.read())[:500]):
                        return await self.download_with_alternative_method_async(final_url, filename, referrer_url)

                    content = await response.read()

                    if len(content) < 1000:
                        return None

                    if not any(content_type.startswith(img_type) for img_type in ['image/', 'application/octet-stream']):
                        magic_bytes = content[:10]
                        image_signatures = [
                            b'\xFF\xD8\xFF',  # JPEG
                            b'\x89PNG\r\n\x1a\n',  # PNG
                            b'GIF87a',  # GIF87a
                            b'GIF89a',  # GIF89a
                            b'RIFF',  # WebP (starts with RIFF)
                        ]

                        if not any(magic_bytes.startswith(sig) for sig in image_signatures):
                            return None

                    async with aiofiles.open(file_path, 'wb') as f:
                        await f.write(content)

                    if os.path.getsize(file_path) < 1000:
                        os.remove(file_path)
                        return None

                    return file_path

        except Exception as e:
            logger.error(f"Async download error for {image_url}: {e}")
            return None

    def download_image(self, image_url, filename=None, referrer_url=None):
        """Download image directly from the source URL (synchronous fallback)"""
        try:
            final_url = image_url

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Sec-Fetch-Dest': 'image',
                'Sec-Fetch-Mode': 'no-cors',
                'Sec-Fetch-Site': 'cross-site',
            }

            if referrer_url:
                headers['Referer'] = referrer_url
            elif self.is_imagetwist_url(final_url):
                headers['Referer'] = 'https://imagetwist.com/'

            try:
                response = self.session.get(final_url, headers=headers, timeout=30, allow_redirects=True)
                if response.status_code not in [200, 206]:
                    if response.status_code == 403:
                        return self.download_with_alternative_method(final_url, filename, referrer_url)
                    else:
                        logger.error(f"HTTP {response.status_code}: {response.reason}")
                        return None
            except Exception as e:
                logger.error(f"Request error for {final_url}: {e}")
                return None

            content_type = response.headers.get('content-type', '').lower()

            if ('text/html' in content_type or
                response.content.startswith(b'<!DOCTYPE') or
                response.content.startswith(b'<html') or
                b'error' in response.content.lower()[:500]):
                return self.download_with_alternative_method(final_url, filename, referrer_url)

            if len(response.content) < 1000:
                return None

            if not any(content_type.startswith(img_type) for img_type in ['image/', 'application/octet-stream']):
                magic_bytes = response.content[:10]
                image_signatures = [
                    b'\xFF\xD8\xFF',  # JPEG
                    b'\x89PNG\r\n\x1a\n',  # PNG
                    b'GIF87a',  # GIF87a
                    b'GIF89a',  # GIF89a
                    b'RIFF',  # WebP (starts with RIFF)
                ]

                if not any(magic_bytes.startswith(sig) for sig in image_signatures):
                    return None

            if not filename:
                parsed_url = urlparse(final_url)
                filename = os.path.basename(parsed_url.path)
                if not filename or '.' not in filename:
                    match = re.search(r'/([^/]+\.(jpg|jpeg|png|gif|webp))$', final_url, re.I)
                    if match:
                        filename = match.group(1)
                    else:
                        ext = 'jpg'
                        if 'png' in content_type:
                            ext = 'png'
                        elif 'gif' in content_type:
                            ext = 'gif'
                        elif 'webp' in content_type:
                            ext = 'webp'
                        filename = f'image.{ext}'

            file_path = os.path.join(self.temp_dir, filename)

            with open(file_path, 'wb') as f:
                f.write(response.content)

            if os.path.getsize(file_path) < 1000:
                os.remove(file_path)
                return None

            return file_path

        except Exception as e:
            logger.error(f"Download error for {image_url}: {e}")
            return None

    def download_video_with_ytdlp(self, video_url, filename=None, referrer_url=None):
        """Download any video using yt-dlp."""
        logger.info(f"🎬 Using yt-dlp to download video from: {video_url}")

        if not YT_DLP_AVAILABLE:
            logger.error("❌ yt-dlp is not available.")
            return None

        try:
            # Create output directory if it doesn't exist
            os.makedirs(self.temp_dir, exist_ok=True)

            # Generate output filename
            if not filename:
                filename = "video"

            output_template = os.path.join(self.temp_dir, f"{filename}.%(ext)s")

            ydl_opts = {
                'outtmpl': output_template,
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'quiet': True,
                'no_warnings': True,
                'nocheckcertificate': True,
                'retries': 3,
                'fragment_retries': 3,
            }

            if referrer_url:
                ydl_opts['referer'] = referrer_url

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])

            # Find the downloaded file
            for file in os.listdir(self.temp_dir):
                if file.startswith(filename):
                    filepath = os.path.join(self.temp_dir, file)
                    if os.path.exists(filepath) and os.path.getsize(filepath) > 100:
                         logger.info(f"✅ yt-dlp download successful: {filepath}")
                         return filepath

            logger.error(f"❌ yt-dlp download seems to have failed for {video_url}. No file found.")
            return None

        except Exception as e:
            import traceback
            logger.error(f"❌ yt-dlp download error for {video_url}: {e}")
            logger.error(traceback.format_exc())
            return None

    async def download_m3u8_stream(self, m3u8_url, filename=None, referrer_url=None):
        """Download M3U8 HLS stream and convert to MP4"""
        try:
            logger.info(f"🎬 Starting M3U8 stream download: {m3u8_url}")

            # Check if ffmpeg is available using the new cross-platform method
            ffmpeg_cmd = self.get_ffmpeg_path()
            ffmpeg_available = ffmpeg_cmd is not None

            if not ffmpeg_available:
                logger.warning("⚠️ FFmpeg not available, trying direct download")

            # For luluvid, use video_extractor.py approach as FFmpeg has issues with their protection
            logger.info("🔄 Using video_extractor.py approach for luluvid (FFmpeg has protection issues)")
            return await self._download_m3u8_manual(m3u8_url, filename, referrer_url)

        except Exception as e:
            logger.error(f"❌ M3U8 download error: {e}")
            return None

    def get_ffmpeg_path(self):
        """Get the appropriate FFmpeg path for the current operating system"""
        import subprocess
        import os
        import platform

        # Try different ffmpeg paths based on OS
        if platform.system() == "Windows":
            ffmpeg_paths = [
                'ffmpeg',  # System PATH
                r'c:\ffmpeg\bin\ffmpeg.exe',  # Windows bin folder (current setup)
                r'c:\ffmpeg\ffmpeg.exe',  # Windows root folder
                'ffmpeg.exe',  # Local directory
            ]
        else:  # Linux/Unix/VPS
            ffmpeg_paths = [
                'ffmpeg',  # System PATH (most common on VPS)
                '/usr/bin/ffmpeg',  # Linux standard path
                '/usr/local/bin/ffmpeg',  # Linux alternative path
                '/opt/ffmpeg/bin/ffmpeg',  # Linux custom installation
                '/snap/bin/ffmpeg',  # Snap installation
                '/home/*/bin/ffmpeg',  # User installation
            ]

        # Test each path to find working FFmpeg
        for path in ffmpeg_paths:
            try:
                result = subprocess.run([path, '-version'],
                                      capture_output=True,
                                      check=True,
                                      timeout=5)
                if result.returncode == 0:
                    self.logger.info(f"✅ FFmpeg found at: {path}")
                    return path
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                continue

        # If no FFmpeg found, log warning
        self.logger.warning("⚠️ FFmpeg not found in any standard location")
        self.logger.info("💡 On VPS, install with: sudo apt update && sudo apt install ffmpeg")
        self.logger.info("💡 On Windows, download from: https://ffmpeg.org/download.html")
        return None

    def extract_video_urls_from_page(self, url):
        """Extract video URLs from a webpage with FRESH session (no caching for luluvid)"""
        # Create a fresh session to avoid caching issues with time-sensitive tokens
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

        try:
            print(f"Fetching: {url}")
            response = session.get(url, timeout=30)
            response.raise_for_status()

            content = response.text
            video_urls = []

            # Enhanced video URL patterns for better extraction
            patterns = [
                # Direct video file patterns
                r'["\']([^"\']*\.mp4[^"\']*)["\']',
                r'["\']([^"\']*\.m3u8[^"\']*)["\']',
                r'["\']([^"\']*\.webm[^"\']*)["\']',
                r'["\']([^"\']*\.ts[^"\']*)["\']',

                # JavaScript player patterns
                r'file["\']?\s*:\s*["\']([^"\']+)["\']',
                r'video["\']?\s*:\s*["\']([^"\']+)["\']',
                r'src["\']?\s*:\s*["\']([^"\']+)["\']',
                r'url["\']?\s*:\s*["\']([^"\']+)["\']',
                r'source["\']?\s*:\s*["\']([^"\']+)["\']',

                # HLS specific patterns
                r'master\.m3u8[^"\']*',
                r'playlist\.m3u8[^"\']*',
                r'index\.m3u8[^"\']*',

                # Common streaming patterns
                r'https?://[^"\']*\.m3u8[^"\']*',
                r'https?://[^"\']*\.mp4[^"\']*',
                r'https?://[^"\']*\.ts[^"\']*',

                # Player-specific patterns
                r'jwplayer[^}]*file["\']?\s*:\s*["\']([^"\']+)["\']',
                r'playerjs[^}]*file["\']?\s*:\s*["\']([^"\']+)["\']',
            ]

            for pattern in patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches:
                    if self.is_video_url_valid(match):
                        from urllib.parse import urljoin
                        full_url = urljoin(url, match)
                        video_urls.append(full_url)

            # Remove duplicates
            return list(set(video_urls))

        except Exception as e:
            print(f"Error: {e}")
            return []

    def is_video_url_valid(self, url):
        """Check if URL is a video file"""
        if not url or len(url) < 10:
            return False

        video_extensions = ['.mp4', '.m3u8', '.webm', '.avi', '.mov', '.mkv']
        url_lower = url.lower()

        return any(ext in url_lower for ext in video_extensions)

    def download_hls_to_mp4_exact(self, hls_url, output_file):
        """Download HLS stream directly to MP4 using FFmpeg with enhanced headers"""
        import subprocess  # Import subprocess here

        # Get the appropriate FFmpeg path for this OS
        ffmpeg_path = self.get_ffmpeg_path()
        if not ffmpeg_path:
            print("❌ FFmpeg not available on this system")
            return False

        print(f"Downloading HLS stream to MP4...")
        print(f"URL: {hls_url}")
        print(f"Output: {output_file}")
        print(f"Using FFmpeg: {ffmpeg_path}")

        # FFmpeg command to download HLS directly to MP4 (cross-platform)
        cmd = [
            ffmpeg_path,  # Use detected FFmpeg path
            '-user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            '-referer', 'https://luluvid.com/',
            '-i', hls_url,
            '-c', 'copy',  # Copy streams without re-encoding (faster)
            '-bsf:a', 'aac_adtstoasc',  # Fix AAC audio
            '-f', 'mp4',  # Force MP4 format
            output_file,
            '-y'  # Overwrite output file
        ]

        try:
            print("Starting download...")
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                print(f"Successfully downloaded to: {output_file}")
                return True
            else:
                print(f"FFmpeg error: {result.stderr}")

                # Try with re-encoding if copy fails (cross-platform)
                print("Trying with re-encoding...")
                cmd_reencode = [
                    ffmpeg_path,  # Use detected FFmpeg path
                    '-user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    '-referer', 'https://luluvid.com/',
                    '-i', hls_url,
                    '-c:v', 'libx264',  # Re-encode video
                    '-c:a', 'aac',      # Re-encode audio
                    '-preset', 'fast',  # Fast encoding
                    '-crf', '23',       # Good quality
                    output_file,
                    '-y'
                ]

                result2 = subprocess.run(cmd_reencode, capture_output=True, text=True)

                if result2.returncode == 0:
                    print(f"Successfully downloaded with re-encoding to: {output_file}")
                    return True
                else:
                    print(f"Re-encoding also failed: {result2.stderr}")
                    return False

        except Exception as e:
            print(f"Download failed: {e}")
            return False

    def download_luluvid_with_ytdlp(self, luluvid_url):
        """Download Luluvid video using optimized yt-dlp + FFmpeg stream copy encoding"""
        print("🎬 Using optimized yt-dlp method (10x faster with encoding)")

        try:
            import subprocess
            import os
            import time

            # Create output directory
            os.makedirs(self.temp_dir, exist_ok=True)

            # Generate output filename pattern
            raw_output_pattern = os.path.join(self.temp_dir, "luluvid_raw.%(ext)s")

            # OPTIMIZED yt-dlp command for 10x faster downloads
            cmd = [
                'yt-dlp',
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                '--referer', 'https://luluvid.com/',
                '--output', raw_output_pattern,

                # Speed optimizations (10x faster)
                '--concurrent-fragments', '8',  # Download 8 fragments at once
                '--fragment-retries', '2',      # Fewer retries for speed
                '--retries', '1',               # Fewer retries
                '--socket-timeout', '10',       # Shorter timeout
                '--http-chunk-size', '1048576', # 1MB chunks for faster download

                '--no-warnings',
                '--no-playlist',
                '--format', 'best[ext=mp4]/best',
                luluvid_url
            ]

            print(f"🔍 Processing URL: {luluvid_url}")
            print("🚀 Starting optimized yt-dlp download (10x faster)...")

            download_start = time.time()

            # Execute optimized yt-dlp
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            if result.returncode == 0:
                download_time = time.time() - download_start
                print(f"✅ yt-dlp download successful in {download_time:.1f}s!")

                # Find the downloaded file
                raw_file_path = None
                for file in os.listdir(self.temp_dir):
                    if file.startswith('luluvid_raw') and file.endswith(('.mp4', '.mkv', '.webm')):
                        raw_file_path = os.path.join(self.temp_dir, file)
                        break

                if not raw_file_path or not os.path.exists(raw_file_path):
                    print("❌ Downloaded file not found")
                    return None

                raw_file_size = os.path.getsize(raw_file_path)
                download_speed = (raw_file_size / 1024 / 1024) / download_time if download_time > 0 else 0
                print(f"📁 Raw download: {raw_file_size / 1024 / 1024:.1f}MB ({download_speed:.1f}MB/s)")

                # STEP 2: Ultra-fast FFmpeg stream copy encoding for web optimization
                print("⚡ Starting ultra-fast FFmpeg stream copy encoding...")

                final_output = os.path.join(self.temp_dir, "luluvid_optimized.mp4")

                # Get FFmpeg path
                ffmpeg_path = self.get_ffmpeg_path()
                if not ffmpeg_path:
                    print("⚠️ FFmpeg not available, returning raw file")
                    return raw_file_path

                encode_start = time.time()

                # Ultra-fast FFmpeg stream copy command
                encode_cmd = [
                    ffmpeg_path,
                    '-i', raw_file_path,
                    '-c', 'copy',                # Copy streams without re-encoding
                    '-movflags', '+faststart',   # Optimize for web streaming
                    '-f', 'mp4',                 # Force MP4 format
                    final_output,
                    '-y'                         # Overwrite output
                ]

                encode_result = subprocess.run(encode_cmd, capture_output=True, text=True)

                encode_time = time.time() - encode_start

                if encode_result.returncode == 0:
                    final_file_size = os.path.getsize(final_output)
                    encode_speed = (final_file_size / 1024 / 1024) / encode_time if encode_time > 0 else 0
                    total_time = download_time + encode_time

                    print(f"✅ Encoding completed in {encode_time:.2f}s ({encode_speed:.0f}MB/s)")
                    print(f"📁 Final file: {final_file_size / 1024 / 1024:.1f}MB (web-optimized)")
                    print(f"🏆 Total time: {total_time:.1f}s (download + encoding)")

                    # Clean up raw file
                    try:
                        os.remove(raw_file_path)
                        print("🧹 Cleaned up raw file")
                    except:
                        pass

                    return final_output
                else:
                    print(f"⚠️ Encoding failed: {encode_result.stderr}")
                    print("📁 Returning raw file instead")
                    return raw_file_path

            else:
                print(f"❌ yt-dlp failed: {result.stderr}")
                return None

        except subprocess.TimeoutExpired:
            print("⏰ yt-dlp timeout (5 minutes)")
            return None
        except Exception as e:
            print(f"💥 yt-dlp error: {e}")
            return None
        """Download Luluvid video using EXACT same logic as video_extractor.py main() function"""
        print("=" * 50)
        print("🎬 VIDEO EXTRACTOR")
        print("=" * 50)
        print()

        try:
            import os

            if not page_url:
                print("❌ No URL provided!")
                return None

            if not page_url.startswith(('http://', 'https://')):
                page_url = 'https://' + page_url

            print(f"\n🔍 Extracting video from: {page_url}")
            print()

            # Create output directory
            os.makedirs(self.temp_dir, exist_ok=True)

            # Generate output filename
            if not filename:
                filename = "video.mp4"
            elif not filename.endswith('.mp4'):
                filename += '.mp4'

            output_file = os.path.join(self.temp_dir, filename)

            # IMMEDIATE extraction and download to prevent token expiration
            # (Create completely fresh session like video_extractor.py)
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })

            print(f"Fetching: {page_url}")
            response = session.get(page_url, timeout=30)
            response.raise_for_status()

            content = response.text
            video_urls = []

            # Enhanced video URL patterns for better extraction
            patterns = [
                # Direct video file patterns
                r'["\']([^"\']*\.mp4[^"\']*)["\']',
                r'["\']([^"\']*\.m3u8[^"\']*)["\']',
                r'["\']([^"\']*\.webm[^"\']*)["\']',
                r'["\']([^"\']*\.ts[^"\']*)["\']',

                # JavaScript player patterns
                r'file["\']?\s*:\s*["\']([^"\']+)["\']',
                r'video["\']?\s*:\s*["\']([^"\']+)["\']',
                r'src["\']?\s*:\s*["\']([^"\']+)["\']',
                r'url["\']?\s*:\s*["\']([^"\']+)["\']',
                r'source["\']?\s*:\s*["\']([^"\']+)["\']',

                # HLS specific patterns
                r'master\.m3u8[^"\']*',
                r'playlist\.m3u8[^"\']*',
                r'index\.m3u8[^"\']*',

                # Common streaming patterns
                r'https?://[^"\']*\.m3u8[^"\']*',
                r'https?://[^"\']*\.mp4[^"\']*',
                r'https?://[^"\']*\.ts[^"\']*',

                # Player-specific patterns
                r'jwplayer[^}]*file["\']?\s*:\s*["\']([^"\']+)["\']',
                r'playerjs[^}]*file["\']?\s*:\s*["\']([^"\']+)["\']',
            ]

            for pattern in patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches:
                    if self.is_video_url_valid(match):
                        from urllib.parse import urljoin
                        full_url = urljoin(page_url, match)
                        video_urls.append(full_url)

            # Remove duplicates
            video_urls = list(set(video_urls))

            if not video_urls:
                print("❌ No video URLs found")
                return None

            print(f"✅ Found {len(video_urls)} video URLs")

            # Find HLS stream URL and download IMMEDIATELY
            hls_url = None
            for url in video_urls:
                if '.m3u8' in url and 'tnmr.org' in url:
                    hls_url = url
                    break

            if not hls_url:
                print("❌ No HLS stream found")
                return None

            print(f"🎬 Downloading video IMMEDIATELY (fresh token)...")
            print()

            # Download HLS stream to MP4 with fresh token (INLINE - no separate method calls)
            # Get FFmpeg path for cross-platform compatibility
            ffmpeg_path = self.get_ffmpeg_path()
            if not ffmpeg_path:
                print("❌ FFmpeg not available on this system")
                return None

            cmd = [
                ffmpeg_path,  # Use detected FFmpeg path
                '-user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                '-referer', 'https://luluvid.com/',
                '-i', hls_url,
                '-c', 'copy',
                '-bsf:a', 'aac_adtstoasc',
                '-f', 'mp4',
                output_file,
                '-y'
            ]

            import subprocess
            result = subprocess.run(cmd, capture_output=True, text=True)

            success = result.returncode == 0

            if success:
                print()
                print("🎉 Download completed successfully!")
                print(f"📁 Video saved as: {output_file}")
                if os.path.exists(output_file):
                    file_size = os.path.getsize(output_file)
                    print(f"File size: {file_size / 1024 / 1024:.1f}MB")
                return output_file
            else:
                print(f"❌ FFmpeg error: {result.stderr}")

                # Try with re-encoding if copy fails (cross-platform)
                print("Trying with re-encoding...")
                cmd_reencode = [
                    ffmpeg_path,  # Use detected FFmpeg path
                    '-user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    '-referer', 'https://luluvid.com/',
                    '-i', hls_url,
                    '-c:v', 'libx264',
                    '-c:a', 'aac',
                    '-preset', 'fast',
                    '-crf', '23',
                    output_file,
                    '-y'
                ]

                result2 = subprocess.run(cmd_reencode, capture_output=True, text=True)

                if result2.returncode == 0:
                    print("🎉 Download completed with re-encoding!")
                    if os.path.exists(output_file):
                        file_size = os.path.getsize(output_file)
                        print(f"File size: {file_size / 1024 / 1024:.1f}MB")
                    return output_file
                else:
                    print(f"❌ Re-encoding also failed: {result2.stderr}")
                    return None

        except Exception as e:
            print(f"Error in exact copy method: {e}")
            return None

    def _download_jwplayer_with_ytdlp(self, video_url, filename=None, referrer_url=None):
        """Download JWPlayer video using yt-dlp (simplified approach)"""
        try:
            # Check if yt-dlp is available
            if not YT_DLP_AVAILABLE:
                logger.warning("⚠️ yt-dlp not available, skipping JWPlayer download")
                return None

            import os
            import tempfile

            # Set up filename
            if not filename:
                filename = "luluvid_video"

            # Create a temporary directory for yt-dlp (like in app.py)
            with tempfile.TemporaryDirectory() as tmpdir:
                logger.info(f"🎬 Using yt-dlp to download JWPlayer video from: {video_url}")

                # yt-dlp options (based on working app.py function)
                options = {
                    'format': 'best[height<=1080]',  # Best quality up to 1080p
                    'outtmpl': os.path.join(tmpdir, f'{filename}.%(ext)s'),  # Output template
                    'quiet': True,  # Suppress yt-dlp output
                    'no_warnings': True,
                }

                # Add referrer if provided
                if referrer_url:
                    options['referer'] = referrer_url

                # Use yt-dlp to download the video (exactly like app.py)
                with yt_dlp.YoutubeDL(options) as ydl:
                    ydl.download([video_url])

                # Find the downloaded file in the temporary directory
                downloaded_files = []
                for file in os.listdir(tmpdir):
                    if file.startswith(filename):
                        file_path = os.path.join(tmpdir, file)
                        if os.path.getsize(file_path) > 100000:  # At least 100KB
                            downloaded_files.append(file_path)

                if downloaded_files:
                    # Get the largest file (best quality)
                    largest_file = max(downloaded_files, key=os.path.getsize)
                    file_size = os.path.getsize(largest_file)

                    # Move to final location
                    final_path = os.path.join(self.temp_dir, f"{filename}.mp4")

                    # Copy file to final location
                    import shutil
                    shutil.copy2(largest_file, final_path)

                    logger.info(f"✅ yt-dlp download successful: {final_path} ({file_size / 1024 / 1024:.1f}MB)")
                    return final_path
                else:
                    logger.warning("⚠️ yt-dlp download failed - no valid files found")
                    return None

        except Exception as e:
            logger.error(f"❌ yt-dlp download error: {e}")
            return None

    async def _download_m3u8_manual(self, m3u8_url, filename=None, referrer_url=None):
        """Download luluvid video using video_extractor.py approach (working method)"""
        try:
            import os

            # Set up filename
            if not filename:
                filename = "luluvid_video"

            # Ensure filename ends with .mp4
            if not filename.endswith('.mp4'):
                filename += '.mp4'

            # Use video_extractor.py approach with the luluvid page URL (tested and working!)
            logger.info(f"🎬 Using video_extractor.py approach with luluvid page URL: {referrer_url}")
            video_extractor_result = self.download_luluvid_with_video_extractor(referrer_url, filename, referrer_url)

            if video_extractor_result and os.path.exists(video_extractor_result):
                file_size = os.path.getsize(video_extractor_result)
                logger.info(f"✅ Video_extractor.py approach successful: {video_extractor_result} ({file_size / 1024 / 1024:.1f}MB)")
                return video_extractor_result

            # Fallback to manual M3U8 download if video_extractor.py approach fails
            logger.warning("⚠️ Video_extractor.py approach failed, falling back to manual M3U8 download...")
            return await self._download_m3u8_segments_manual(m3u8_url, filename, referrer_url)

        except Exception as e:
            logger.error(f"❌ M3U8 download error: {e}")
            return None

    async def _download_m3u8_segments_manual(self, m3u8_url, filename=None, referrer_url=None):
        """Fallback: Manual M3U8 segment download and concatenation"""
        try:
            import tempfile
            import os

            # Download M3U8 playlist with proper headers for luluvid
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/vnd.apple.mpegurl,application/x-mpegURL,*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Referer': referrer_url or 'https://luluvid.com/'
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(m3u8_url, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f"❌ Failed to download M3U8 playlist: {response.status}")
                        return None

                    playlist_content = await response.text()
                    logger.info(f"📄 M3U8 playlist downloaded: {len(playlist_content)} characters")

                    # Parse playlist to find segment URLs
                    segment_urls = []
                    base_url = '/'.join(m3u8_url.split('/')[:-1]) + '/'

                    for line in playlist_content.split('\n'):
                        line = line.strip()
                        if line and not line.startswith('#'):
                            if line.startswith('http'):
                                segment_urls.append(line)
                            else:
                                segment_urls.append(base_url + line)

                    logger.info(f"🎬 Found {len(segment_urls)} video segments")

                    if not segment_urls:
                        logger.error("❌ No video segments found in M3U8 playlist")
                        return None

                    # Download segments and concatenate
                    if not filename:
                        filename = "luluvid_video.mp4"

                    # Create temporary file
                    temp_file = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
                    temp_path = temp_file.name
                    temp_file.close()  # Close the file handle so we can write to it

                    # Download segments (limit to reasonable number for testing)
                    downloaded_segments = 0
                    max_segments = min(50, len(segment_urls))  # Increased limit

                    logger.info(f"🎬 Starting manual download of {max_segments} segments...")

                    # Open file for writing
                    with open(temp_path, 'wb') as output_file:
                        for i, segment_url in enumerate(segment_urls[:max_segments]):
                            try:
                                # Use same headers for segments
                                async with session.get(segment_url, headers=headers) as seg_response:
                                    if seg_response.status == 200:
                                        segment_data = await seg_response.read()
                                        output_file.write(segment_data)
                                        downloaded_segments += 1

                                        # Log progress every 10 segments
                                        if (i + 1) % 10 == 0 or i == max_segments - 1:
                                            logger.info(f"📥 Downloaded {i+1}/{max_segments} segments")
                                    else:
                                        logger.warning(f"⚠️ Failed to download segment {i+1}: {seg_response.status}")
                                        # Continue with other segments
                            except Exception as e:
                                logger.warning(f"⚠️ Error downloading segment {i+1}: {e}")
                                # Continue with other segments

                    if downloaded_segments > 0:
                        file_size = os.path.getsize(temp_path)
                        logger.info(f"✅ Manual M3U8 download completed. File size: {file_size / 1024 / 1024:.1f}MB")
                        return temp_path
                    else:
                        logger.error("❌ No segments could be downloaded")
                        if os.path.exists(temp_path):
                            os.unlink(temp_path)
                        return None

        except Exception as e:
            logger.error(f"❌ Manual M3U8 download error: {e}")
            return None

    async def download_video_async(self, video_url, filename=None, referrer_url=None):
        """Download video from any source using yt-dlp."""
        logger.info(f"Initiating download for {video_url} using yt-dlp wrapper.")
        try:
            # yt-dlp can be slow, so run it in an executor to avoid blocking the event loop
            loop = asyncio.get_running_loop()
            video_file = await loop.run_in_executor(
                None,  # Use the default executor
                self.download_video_with_ytdlp,
                video_url,
                filename,
                referrer_url
            )
            return video_file
        except Exception as e:
            import traceback
            logger.error(f"Error executing download_video_with_ytdlp via executor: {e}")
            logger.error(traceback.format_exc())
            return None


    def get_file_size_mb(self, file_path):
        """Get file size in MB"""
        try:
            return os.path.getsize(file_path) / (1024 * 1024)
        except:
            return 0

    def is_file_too_large(self, file_path):
        """Check if file is too large for Telegram (over 2000MB)"""
        try:
            size_mb = self.get_file_size_mb(file_path)
            return size_mb > 2000  # Telegram's limit is 2000MB
        except:
            return False

    async def download_with_alternative_method_async(self, image_url, filename=None, referrer_url=None):
        """Alternative download method with different headers and approaches (async)"""
        try:
            user_agents = [
                'Mozilla/5.0 (iPhone; CPU iPhone OS 14_7_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Mobile/15E148 Safari/604.1',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Android 11; Mobile; rv:68.0) Gecko/68.0 Firefox/88.0'
            ]

            for user_agent in user_agents:
                try:
                    headers = {
                        'User-Agent': user_agent,
                        'Accept': '*/*',
                        'Accept-Language': 'en-US,en;q=0.5',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'DNT': '1',
                        'Connection': 'keep-alive',
                    }

                    if referrer_url:
                        headers['Referer'] = referrer_url
                    elif self.is_imagetwist_url(image_url):
                        headers['Referer'] = 'https://imagetwist.com/'

                    async with aiohttp.ClientSession() as session:
                        async with session.get(image_url, headers=headers, timeout=aiohttp.ClientTimeout(total=30), allow_redirects=True) as response:
                            if response.status in [200, 206]:
                                content_type = response.headers.get('content-type', '').lower()
                                content = await response.read()

                                if (any(img_type in content_type for img_type in ['image/', 'application/octet-stream']) and
                                    len(content) > 1000 and
                                    not content.startswith(b'<!DOCTYPE') and
                                    not content.startswith(b'<html')):

                                    if not filename:
                                        parsed_url = urlparse(image_url)
                                        filename = os.path.basename(parsed_url.path)
                                        if not filename or '.' not in filename:
                                            match = re.search(r'/([^/]+\.(jpg|jpeg|png|gif|webp))$', image_url, re.I)
                                            if match:
                                                filename = match.group(1)
                                            else:
                                                filename = 'image.jpg'

                                    file_path = os.path.join(self.temp_dir, filename)

                                    async with aiofiles.open(file_path, 'wb') as f:
                                        await f.write(content)

                                    return file_path

                except Exception as e:
                    continue

            return None

        except Exception as e:
            logger.error(f"Async alternative download error for {image_url}: {e}")
            return None

    def download_with_alternative_method(self, image_url, filename=None, referrer_url=None):
        """Alternative download method with different headers and approaches (synchronous fallback)"""
        try:
            user_agents = [
                'Mozilla/5.0 (iPhone; CPU iPhone OS 14_7_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Mobile/15E148 Safari/604.1',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Android 11; Mobile; rv:68.0) Gecko/68.0 Firefox/88.0'
            ]

            for user_agent in user_agents:
                try:
                    headers = {
                        'User-Agent': user_agent,
                        'Accept': '*/*',
                        'Accept-Language': 'en-US,en;q=0.5',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'DNT': '1',
                        'Connection': 'keep-alive',
                    }

                    if referrer_url:
                        headers['Referer'] = referrer_url
                    elif self.is_imagetwist_url(image_url):
                        headers['Referer'] = 'https://imagetwist.com/'

                    response = self.session.get(image_url, headers=headers, timeout=30, allow_redirects=True)

                    if response.status_code in [200, 206]:
                        content_type = response.headers.get('content-type', '').lower()

                        if (any(img_type in content_type for img_type in ['image/', 'application/octet-stream']) and
                            len(response.content) > 1000 and
                            not response.content.startswith(b'<!DOCTYPE') and
                            not response.content.startswith(b'<html')):

                            if not filename:
                                parsed_url = urlparse(image_url)
                                filename = os.path.basename(parsed_url.path)
                                if not filename or '.' not in filename:
                                    match = re.search(r'/([^/]+\.(jpg|jpeg|png|gif|webp))$', image_url, re.I)
                                    if match:
                                        filename = match.group(1)
                                    else:
                                        filename = 'image.jpg'

                            file_path = os.path.join(self.temp_dir, filename)

                            with open(file_path, 'wb') as f:
                                f.write(response.content)

                            return file_path

                except Exception as e:
                    continue

            return None

        except Exception as e:
            logger.error(f"Alternative download error for {image_url}: {e}")
            return None

    def extract_images_from_html(self, html_content):
        """Extract image URLs from HTML content"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            images = []

            img_tags = soup.find_all('img')

            for img in img_tags:
                image_data = {}

                src = img.get('src')
                if src:
                    image_data['src'] = src

                data_src = img.get('data-src')
                if data_src:
                    image_data['data_src'] = data_src

                alt = img.get('alt')
                if alt:
                    image_data['alt'] = alt

                img_class = img.get('class')
                if img_class:
                    image_data['class'] = ' '.join(img_class) if isinstance(img_class, list) else img_class

                primary_url = data_src if data_src else src
                if primary_url:
                    image_data['primary_url'] = primary_url
                    images.append(image_data)

            return images

        except Exception as e:
            return f"Error extracting images: {str(e)}"

    def extract_images_from_url(self, url):
        """Extract all images from a webpage URL"""
        try:
            # Add protocol if missing
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url

            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            return self.extract_images_from_html(response.text)

        except requests.exceptions.RequestException as e:
            return f"Error fetching URL: {str(e)}"
        except Exception as e:
            return f"Error extracting images: {str(e)}"

    # Add the sample.py extraction methods to ContentExtractor class
    def extract_title_sample_style(self, url):
        """Extract title using sample.py method - fallback for URLs that don't work with current method"""
        try:
            # Add protocol if missing
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url

            # Special handling for mmsdose.us URLs - use exact headers from test script
            if 'mmsdose.us' in url:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'same-origin',
                    'Cache-Control': 'max-age=0',
                    'Referer': 'https://mmsdose.us/',
                    'Origin': 'https://mmsdose.us'
                }
                time.sleep(random.uniform(1, 2))
                response = requests.get(url, headers=headers, timeout=10)
            else:
                response = self.session.get(url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Use sample.py method: look for h1 with specific class
            title_element = soup.find('h1', class_='text-xl md:text-2xl')
            if title_element:
                title = title_element.get_text(strip=True)
                if title:
                    return self.clean_title(title)

            # Fallback to existing method
            return self.extract_title(url)

        except Exception as e:
            logger.error(f"Error in sample-style title extraction: {e}")
            return self.extract_title(url)  # Fallback to original method

    def extract_image_sample_style(self, url):
        """Extract image using sample.py method - fallback for URLs that don't work with current method"""
        max_retries = 3
        retry_delay = 2  # seconds

        for attempt in range(max_retries):
            try:
                # Add protocol if missing
                if not url.startswith(('http://', 'https://')):
                    url = 'https://' + url

                # Special handling for mmsdose.us URLs - use exact headers from test script
                if 'mmsdose.us' in url:
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'DNT': '1',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1',
                        'Sec-Fetch-Dest': 'document',
                        'Sec-Fetch-Mode': 'navigate',
                        'Sec-Fetch-Site': 'same-origin',
                        'Cache-Control': 'max-age=0',
                        'Referer': 'https://mmsdose.us/',
                        'Origin': 'https://mmsdose.us'
                    }
                    time.sleep(random.uniform(1, 2))
                    response = requests.get(url, headers=headers, timeout=15)
                else:
                    response = self.session.get(url, timeout=15)
                response.raise_for_status()

                soup = BeautifulSoup(response.content, 'html.parser')

                # Use sample.py method: look for ALL img elements with specific classes
                img_elements = soup.find_all('img', class_='rounded object-contain shadow-lg')
                logger.info(f"🔍 Found {len(img_elements)} images with class 'rounded object-contain shadow-lg'")

                # Also look for erome.com specific images
                erome_img_elements = soup.find_all('img', class_='img-front')
                logger.info(f"🔍 Found {len(erome_img_elements)} images with class 'img-front'")

                # Combine both sets of images
                all_img_elements = img_elements + erome_img_elements
                logger.info(f"🔍 Total images to process: {len(all_img_elements)}")

                extracted_images = []

                for i, img_element in enumerate(all_img_elements, 1):
                    logger.info(f"🔍 Processing image {i}/{len(all_img_elements)}")
                    logger.info(f"🔍 Image {i} alt: {img_element.get('alt', 'No alt')}")

                    # Try to get the actual image URL from data-src (lazy loading), srcset, or src
                    image_url = None

                    # First try data-src (for lazy loading)
                    data_src = img_element.get('data-src')
                    if data_src:
                        logger.info(f"🔍 Image {i} has data-src: {data_src}")
                        image_url = data_src
                    else:
                        # Try srcset
                        srcset = img_element.get('srcset', '')
                        if srcset:
                            logger.info(f"🔍 Image {i} has srcset: {srcset[:100]}...")
                            # Extract the highest resolution image from srcset
                            srcset_parts = srcset.split(', ')
                            if srcset_parts:
                                # Get the last (highest resolution) image
                                last_srcset = srcset_parts[-1]
                                image_url = last_srcset.split(' ')[0]
                        else:
                            # Fallback to src attribute
                            src = img_element.get('src')
                            if src:
                                logger.info(f"🔍 Image {i} has src: {src}")
                                image_url = src

                    if image_url:
                        # Convert relative URL to absolute
                        if image_url.startswith('/'):
                            image_url = urljoin(url, image_url)
                        elif not image_url.startswith(('http://', 'https://')):
                            image_url = urljoin(url, image_url)

                        # Filter out data URLs
                        if not image_url.startswith('data:'):
                            logger.info(f"🔍 Image {i} extracted URL: {image_url}")
                            extracted_images.append({
                                'url': image_url,
                                'alt': img_element.get('alt', ''),
                                'type': 'sample_style'
                            })
                        else:
                            logger.warning(f"⚠️ Image {i} has data URL, skipping")
                    else:
                        logger.warning(f"⚠️ Image {i} has no src, data-src, or srcset")

                # Remove duplicates while preserving order
                seen_urls = set()
                unique_images = []
                for img in extracted_images:
                    if img['url'] not in seen_urls:
                        seen_urls.add(img['url'])
                        unique_images.append(img)

                logger.info(f"✅ Extracted {len(unique_images)} unique images from {len(all_img_elements)} found images")
                return unique_images

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                    requests.exceptions.RequestException, ConnectionResetError) as e:
                if attempt < max_retries - 1:
                    logger.warning(f"⚠️ Connection error on attempt {attempt + 1}/{max_retries} for sample-style extraction: {str(e)}")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                    continue
                else:
                    logger.error(f"❌ Failed to extract sample-style images after {max_retries} attempts: {str(e)}")
                    return []
            except Exception as e:
                logger.error(f"❌ Unexpected error in sample-style image extraction: {e}")
                return []

        return []

    def extract_video_sample_style(self, url):
        """Extract videos using sample.py method - fallback for URLs that don't work with current method"""
        try:
            # Add protocol if missing
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url

            # Special handling for mmsdose.us URLs - use exact headers from test script
            if 'mmsdose.us' in url:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'same-origin',
                    'Cache-Control': 'max-age=0',
                    'Referer': 'https://mmsdose.us/',
                    'Origin': 'https://mmsdose.us'
                }
                time.sleep(random.uniform(1, 2))
                response = requests.get(url, headers=headers, timeout=15)
            else:
                response = self.session.get(url, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            video_urls = []

            # Look for video tags
            video_tags = soup.find_all('video')
            for video in video_tags:
                src = video.get('src')
                if src:
                    video_urls.append(urljoin(url, src))

                # Check for source tags inside video
                sources = video.find_all('source')
                for source in sources:
                    src = source.get('src')
                    if src:
                        video_urls.append(urljoin(url, src))

            # Look for iframe sources (embedded videos)
            iframes = soup.find_all('iframe')
            for iframe in iframes:
                src = iframe.get('src')
                if src:
                    video_urls.append(urljoin(url, src))

            # Look for links that might be video files
            links = soup.find_all('a', href=True)
            video_extensions = ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mkv', '.m4v', '.3gp']
            for link in links:
                href = link.get('href')
                if href:
                    parsed_url = urlparse(href)
                    if any(ext in parsed_url.path.lower() for ext in video_extensions):
                        video_urls.append(urljoin(url, href))

            # Look for video URLs in script tags (common for embedded videos)
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string:
                    # Look for video URLs in script content
                    video_patterns = [
                        r'https?://[^\s"\']+\.(?:mp4|avi|mov|wmv|flv|webm|mkv|m4v|3gp)',
                        r'https?://[^\s"\']+\.(?:mp4|avi|mov|wmv|flv|webm|mkv|m4v|3gp)[^\s"\']*',
                        r'["\']([^"\']*\.(?:mp4|avi|mov|wmv|flv|webm|mkv|m4v|3gp))["\']',
                        r'videoUrl["\']?\s*[:=]\s*["\']([^"\']+)["\']',
                        r'src["\']?\s*[:=]\s*["\']([^"\']+\.(?:mp4|avi|mov|wmv|flv|webm|mkv|m4v|3gp))["\']'
                    ]
                    for pattern in video_patterns:
                        matches = re.findall(pattern, script.string, re.IGNORECASE)
                        for match in matches:
                            if isinstance(match, tuple):
                                video_urls.extend(match)
                            else:
                                video_urls.append(match)

            # Look for data attributes that might contain video URLs
            elements_with_data = soup.find_all(attrs={'data-video': True})
            for element in elements_with_data:
                video_url = element.get('data-video')
                if video_url:
                    video_urls.append(urljoin(url, video_url))

            # Look for video URLs in meta tags
            meta_tags = soup.find_all('meta')
            for meta in meta_tags:
                content = meta.get('content', '')
                if any(ext in content.lower() for ext in video_extensions):
                    video_urls.append(content)

            # Remove duplicates and convert to our format
            unique_video_urls = list(set(video_urls))
            result = []
            for video_url in unique_video_urls:
                result.append({
                    'url': video_url,
                    'text': '',
                    'title': '',
                    'type': 'sample_style'
                })

            return result

        except Exception as e:
            logger.error(f"Error in sample-style video extraction: {e}")
            return []

    def extract_actual_video_urls_sample_style(self, video_urls):
        """Extract actual video URLs from embed pages using sample.py method"""
        actual_video_urls = []

        for video_url in video_urls:
            # If it's an embed URL, try to extract the actual video
            if 'embed' in video_url or 'downloaddirect.xyz' in video_url:
                try:
                    logger.info(f"Checking embed URL: {video_url}")
                    response = self.session.get(video_url)
                    if response.status_code == 200:
                        embed_soup = BeautifulSoup(response.text, 'html.parser')

                        # Look for direct video links in the embed page
                        video_links = embed_soup.find_all('a', href=True)
                        for link in video_links:
                            href = link.get('href')
                            if href and any(ext in href.lower() for ext in ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mkv']):
                                actual_video_urls.append(urljoin(video_url, href))

                        # Look for video sources in embed page
                        video_tags = embed_soup.find_all('video')
                        for video in video_tags:
                            src = video.get('src')
                            if src:
                                actual_video_urls.append(urljoin(video_url, src))

                            # Also check for source tags inside video
                            sources = video.find_all('source')
                            for source in sources:
                                src = source.get('src')
                                if src:
                                    actual_video_urls.append(urljoin(video_url, src))

                        # Look for video URLs in script tags of embed page
                        scripts = embed_soup.find_all('script')
                        for script in scripts:
                            if script.string:
                                video_patterns = [
                                    r'https?://[^\s"\']+\.(?:mp4|avi|mov|wmv|flv|webm|mkv)',
                                    r'["\']([^"\']*\.(?:mp4|avi|mov|wmv|flv|webm|mkv))["\']'
                                ]
                                for pattern in video_patterns:
                                    matches = re.findall(pattern, script.string, re.IGNORECASE)
                                    for match in matches:
                                        if isinstance(match, tuple):
                                            actual_video_urls.extend(match)
                                        else:
                                            actual_video_urls.append(match)
                except Exception as e:
                    logger.error(f"Error processing embed URL {video_url}: {e}")
            else:
                # If it's already a direct video URL, keep it
                actual_video_urls.append(video_url)

        return list(set(actual_video_urls))

    def is_hotpic_url(self, url):
        """Check if URL is from hotpic.cc domain"""
        if not url:
            return False
        return 'hotpic.cc' in url.lower()

    def get_hotpic_album_info(self, soup, url):
        """Extract album title and other metadata from hotpic.cc"""
        try:
            # Try to get the title from the main heading
            title_elem = soup.find('h1')
            if title_elem:
                title = title_elem.get_text().strip()
                # Clean up the title to make it a valid folder name
                title = re.sub(r'[^\w\s-]', '', title).strip()
                title = re.sub(r'\s+', ' ', title)
                return title
        except Exception as e:
            logger.warning(f"Could not extract album title: {e}")

        # Fallback: Use the last part of the URL as the title
        return url.rstrip('/').split('/')[-1] or 'downloaded_media'

    def extract_hotpic_media_links(self, url):
        """Extract all media (images and videos) links from hotpic.cc page"""
        try:
            # Add protocol if missing
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url

            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # Get album title
            album_title = self.get_hotpic_album_info(soup, url)

            media_links = []

            # Find all spotlight links which contain the actual media
            for link in soup.find_all('a', class_='spotlight'):
                if link.get('href') and not link['href'].startswith('#'):
                    media_url = link['href']
                    if not media_url.startswith(('http://', 'https://')):
                        media_url = urljoin(url, media_url)

                    # Determine if it's a video or image based on extension
                    if any(ext in media_url.lower() for ext in ['.mp4', '.webm', '.mov']):
                        media_type = 'video'
                    else:
                        media_type = 'image'

                    # Get the title for the filename
                    title = link.get('title', '').strip() or f"media_{len(media_links) + 1}"

                    # Clean up the title to make it a valid filename
                    title = re.sub(r'[^\w\-_\.]', '_', title)
                    title = re.sub(r'_+', '_', title).strip('_')

                    media_links.append({
                        'type': media_type,
                        'url': media_url,
                        'title': title,
                        'album_title': album_title
                    })

            return media_links, album_title
        except Exception as e:
            logger.error(f"Error fetching hotpic media links: {e}")
            return [], "Error"

    def download_hotpic_file(self, url, filepath, headers):
        """Download a file from hotpic.cc URL and save it to the specified path"""
        try:
            with self.session.get(url, headers=headers, stream=True) as r:
                r.raise_for_status()
                with open(filepath, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:  # filter out keep-alive new chunks
                            f.write(chunk)
            return True
        except Exception as e:
            logger.error(f"Error downloading {url}: {e}")
            return False

    def is_erome_url(self, url):
        """Check if URL is from erome.com"""
        return 'erome.com' in url.lower()

    def extract_erome_media_links(self, url):
        """Extract media links from erome.com pages"""
        try:
            # Add protocol if missing
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url

            response = self.session.get(url, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Extract title
            title = "No title found"
            title_tag = soup.find('title')
            if title_tag:
                title = title_tag.get_text().strip()

            # Look for images in erome.com format
            images = []

            # First, look for erome-specific image classes
            img_elements = soup.find_all('img', class_='img-front')
            logger.info(f"🔍 Found {len(img_elements)} images with class 'img-front'")

            for img in img_elements:
                # Try data-src first (lazy loading), then src
                image_url = img.get('data-src') or img.get('src')
                if image_url:
                    # Convert relative URLs to absolute
                    if image_url.startswith('/'):
                        image_url = urljoin(url, image_url)
                    elif not image_url.startswith(('http://', 'https://')):
                        image_url = urljoin(url, image_url)

                    # Filter out data URLs and small images
                    if image_url.startswith('data:'):
                        continue
                    if any(keyword in image_url.lower() for keyword in ['avatar', 'icon', 'logo', 'thumb']):
                        continue

                    images.append({
                        'url': image_url,
                        'title': img.get('alt', ''),
                        'type': 'image'
                    })
                    logger.info(f"🔍 Found erome image: {image_url}")

            # If no images found with img-front class, try all img elements
            if not images:
                logger.info("🔍 No images found with 'img-front' class, trying all img elements...")
                all_img_elements = soup.find_all('img')

                for img in all_img_elements:
                    # Try data-src first (lazy loading), then src
                    image_url = img.get('data-src') or img.get('src')
                    if image_url:
                        # Convert relative URLs to absolute
                        if image_url.startswith('/'):
                            image_url = urljoin(url, image_url)
                        elif not image_url.startswith(('http://', 'https://')):
                            image_url = urljoin(url, image_url)

                        # Filter out data URLs and small images
                        if image_url.startswith('data:'):
                            continue
                        if any(keyword in image_url.lower() for keyword in ['avatar', 'icon', 'logo', 'thumb']):
                            continue

                        images.append({
                            'url': image_url,
                            'title': img.get('alt', ''),
                            'type': 'image'
                        })
                        logger.info(f"🔍 Found general image: {image_url}")

            # Look for videos
            videos = []
            video_elements = soup.find_all('video')
            for video in video_elements:
                src = video.get('src')
                if src:
                    if src.startswith('/'):
                        src = urljoin(url, src)
                    elif not src.startswith(('http://', 'https://')):
                        src = urljoin(url, src)

                    videos.append({
                        'url': src,
                        'title': video.get('title', ''),
                        'type': 'video'
                    })

            # Also look for video sources
            source_elements = soup.find_all('source')
            for source in source_elements:
                src = source.get('src')
                if src:
                    if src.startswith('/'):
                        src = urljoin(url, src)
                    elif not src.startswith(('http://', 'https://')):
                        src = urljoin(url, src)

                    videos.append({
                        'url': src,
                        'title': source.get('title', ''),
                        'type': 'video'
                    })

            # Remove duplicates
            seen_urls = set()
            unique_images = []
            for img in images:
                if img['url'] not in seen_urls:
                    seen_urls.add(img['url'])
                    unique_images.append(img)

            seen_urls = set()
            unique_videos = []
            for vid in videos:
                if vid['url'] not in seen_urls:
                    seen_urls.add(vid['url'])
                    unique_videos.append(vid)

            logger.info(f"🔍 Erome extraction: {len(unique_images)} images, {len(unique_videos)} videos")
            return unique_images + unique_videos, title

        except Exception as e:
            logger.error(f"❌ Error extracting erome media: {e}")
            return [], "No title found"

    def extract_content_comprehensive(self, url):
        """Comprehensive content extraction for various websites (similar to the example script)"""
        try:
            # Add protocol if missing
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url

            logger.info(f"🔍 Starting comprehensive content extraction from: {url}")

            # Special handling for mmsdose.us URLs - use exact headers from test script
            if 'mmsdose.us' in url:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'same-origin',
                    'Cache-Control': 'max-age=0',
                    'Referer': 'https://mmsdose.us/',
                    'Origin': 'https://mmsdose.us'
                }
                time.sleep(random.uniform(1, 2))
            else:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1'
                }

            # Add referer based on domain
            if 'mmsbee' in url:
                headers['Referer'] = 'https://mmsbee42.com/'
            elif 'imagetwist' in url:
                headers['Referer'] = 'https://imagetwist.com/'
            elif 'vidoza' in url:
                headers['Referer'] = 'https://vidoza.net/'
            elif 'streamtape' in url:
                headers['Referer'] = 'https://streamtape.com/'

            # Use requests.get for mmsdose.us URLs, session.get for others
            if 'mmsdose.us' in url:
                response = requests.get(url, headers=headers, timeout=15)
            else:
                response = self.session.get(url, headers=headers, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # Extract title using multiple methods
            title = "No title found"

            # Method 1: Look for h1 with specific classes (like mmsbee)
            title_tag = soup.find('h1', class_='ipsType_pageTitle')
            if title_tag:
                title = title_tag.text.strip()
                logger.info(f"📝 Found title from h1.ipsType_pageTitle: {title}")

            # Method 2: Look for other common title patterns
            if title == "No title found":
                title_tag = soup.find('h1', class_='text-xl md:text-2xl')
                if title_tag:
                    title = title_tag.text.strip()
                    logger.info(f"📝 Found title from h1.text-xl: {title}")

            # Method 3: Look for any h1 tag
            if title == "No title found":
                title_tag = soup.find('h1')
                if title_tag:
                    title = title_tag.text.strip()
                    logger.info(f"📝 Found title from h1: {title}")

            # Method 4: Look for title tag
            if title == "No title found":
                title_tag = soup.find('title')
                if title_tag:
                    title = title_tag.text.strip()
                    logger.info(f"📝 Found title from title tag: {title}")

            # Method 5: Look for meta tags
            if title == "No title found":
                og_title = soup.find('meta', property='og:title')
                if og_title:
                    title = og_title.get('content', '').strip()
                    logger.info(f"📝 Found title from og:title: {title}")

            # Clean the title
            clean_title = self.clean_title(title)
            logger.info(f"📝 Final clean title: {clean_title}")

            # Find the main content area to avoid ads and logos
            content_area = None

            # Method 1: Look for data-role="commentContent" (like mmsbee)
            content_area = soup.find('div', {'data-role': 'commentContent'})
            if content_area:
                logger.info("🔍 Found content area with data-role='commentContent'")

            # Method 2: Look for other common content areas
            if not content_area:
                content_area = soup.find('div', class_='content')
                if content_area:
                    logger.info("🔍 Found content area with class='content'")

            # Method 3: Look for main tag
            if not content_area:
                content_area = soup.find('main')
                if content_area:
                    logger.info("🔍 Found content area with main tag")

            # Method 4: Look for article tag
            if not content_area:
                content_area = soup.find('article')
                if content_area:
                    logger.info("🔍 Found content area with article tag")

            # If no specific content area found, use the whole body
            if not content_area:
                content_area = soup.find('body')
                if content_area:
                    logger.info("🔍 Using body as content area")
                else:
                    content_area = soup
                    logger.info("🔍 Using entire soup as content area")

            # Extract all image URLs from the content area
            logger.info("🔍 Extracting images from content area...")
            images = []

            for img in content_area.find_all('img'):
                img_url = ''
                parent_link = img.find_parent('a')

                # Method 1: Check if parent link is a hosting service
                if parent_link and parent_link.get('href'):
                    href = parent_link.get('href')
                    if any(host in href.lower() for host in ['imagetwist.com', 'imagebam.com', 'imgbox.com', 'imgur.com']):
                        img_url = href
                        logger.info(f"🔍 Found image from parent link: {img_url}")

                # Method 2: Check data-src (lazy loading)
                if not img_url:
                    thumb_url = img.get('data-src') or img.get('src', '')
                    if thumb_url:
                        # Convert thumbnail URLs to full image URLs
                        if '/th/' in thumb_url:
                            img_url = thumb_url.replace('/th/', '/i/')
                        else:
                            img_url = thumb_url
                        logger.info(f"🔍 Found image from data-src/src: {img_url}")

                # Method 3: Check src attribute
                if not img_url:
                    src = img.get('src')
                    if src:
                        img_url = src
                        logger.info(f"🔍 Found image from src: {img_url}")

                if img_url and not img_url.startswith('data:image') and 'uploads/emoticons' not in img_url:
                    # Convert relative URLs to absolute
                    if not img_url.startswith(('http://', 'https://')):
                        img_url = urljoin(url, img_url)

                    # Enhanced WordPress uploads handling - ONLY pass high-quality original images
                    # Prioritize WordPress wp-content/uploads images (usually high quality)
                    is_wordpress_upload = '/wp-content/uploads/' in img_url

                    # For WordPress uploads, ONLY accept original quality images
                    if is_wordpress_upload:
                        # Skip ALL thumbnails and compressed versions
                        if any(size in img_url.lower() for size in [
                            '-16x16', '-32x32', '-48x48', '-64x64', '-75x75', '-96x96',
                            '-100x100', '-150x150', '-200x200', '-300x300', '-400x400',
                            '-thumbnail', '-thumb', '-small', '-medium', '-large'
                        ]):
                            continue  # Skip ALL thumbnail sizes

                        # Remove WordPress size suffixes to get ORIGINAL image
                        original_url = re.sub(r'-\d+x\d+(?=\.[a-z]+)', '', img_url)
                        original_url = re.sub(r'-scaled(?=\.[a-z]+)', '', original_url)

                        # ONLY pass if it's a legitimate original image
                        if original_url == img_url or not any(size in img_url for size in ['x', '-']):
                            img_url = original_url
                            logger.info(f"🔍 PASSED: WordPress original image: {img_url}")
                        else:
                            logger.info(f"❌ REJECTED: WordPress thumbnail: {img_url}")
                            continue  # Skip if not original quality
                    else:
                        # For non-WordPress images, apply strict quality filters
                        skip_keywords = ['avatar', 'icon', 'logo', 'thumb', 'emoji', 'banner', 'ad']
                        if any(keyword in img_url.lower() for keyword in skip_keywords):
                            logger.info(f"❌ REJECTED: Low-quality image: {img_url}")
                            continue

                        # Skip small file sizes (likely low quality)
                        if any(size in img_url.lower() for size in ['32x32', '64x64', '100x100']):
                            logger.info(f"❌ REJECTED: Small image: {img_url}")
                            continue

                    # ONLY add images that pass ALL quality checks
                    if img_url not in [img['url'] for img in images]:
                        image_type = 'wordpress_original' if is_wordpress_upload else 'high_quality'
                        images.append({
                            'url': img_url,
                            'alt': img.get('alt', ''),
                            'type': image_type
                        })
                        if is_wordpress_upload:
                            logger.info(f"✅ ADDED: WordPress original image: {img_url}")
                        else:
                            logger.info(f"✅ ADDED: High-quality image: {img_url}")

            logger.info(f"🔍 Found {len(images)} unique images")

            # Extract video URLs by finding all links in the content area
            logger.info("🔍 Extracting video links from content area...")
            videoza_links = set()
            streamtape_links = set()
            other_video_links = set()

            for link in content_area.find_all('a', href=True):
                href = link.get('href', '')

                # Check for various video hosting services
                if 'vidoza.net' in href:
                    videoza_links.add(href)
                    logger.info(f"🔍 Found Vidoza link: {href}")
                elif 'streamtape.com' in href or 'streamtape.to' in href:
                    streamtape_links.add(href)
                    logger.info(f"🔍 Found Streamtape link: {href}")
                elif any(host in href.lower() for host in ['youtube.com', 'youtu.be', 'vimeo.com', 'dailymotion.com', 'redtube.com', 'pornhub.com']):
                    other_video_links.add(href)
                    logger.info(f"🔍 Found other video link: {href}")

            # Also look for video URLs in text content
            text_content = content_area.get_text()

            # Look for video URLs in text using regex
            video_patterns = [
                r'https?://(?:www\.)?vidoza\.net/[a-zA-Z0-9]+\.html',
                r'https?://(?:www\.)?streamtape\.(?:to|com)/(?:v|e)/[a-zA-Z0-9]+(?:/[^/\s]*)?(?:\.html)?',
                r'https?://(?:www\.)?youtube\.com/watch\?v=[a-zA-Z0-9_-]+',
                r'https?://(?:www\.)?youtu\.be/[a-zA-Z0-9_-]+',
                r'https?://(?:www\.)?vimeo\.com/[0-9]+',
                r'https?://(?:www\.)?dailymotion\.com/video/[a-zA-Z0-9]+',
                r'https?://(?:www\.)?redtube\.com/[0-9]+',
                r'https?://(?:www\.)?pornhub\.com/view_video\.php\?viewkey=[a-zA-Z0-9]+'
            ]

            for pattern in video_patterns:
                matches = re.findall(pattern, text_content)
                print(f"🔍 COMPREHENSIVE DEBUG: Pattern '{pattern}' found {len(matches)} matches: {matches}")
                for match in matches:
                    if 'vidoza.net' in match:
                        videoza_links.add(match)
                        logger.info(f"🔍 Found Vidoza link in text: {match}")
                    elif 'streamtape' in match:
                        streamtape_links.add(match)
                        logger.info(f"🔍 Found Streamtape link in text: {match}")
                        print(f"🔍 COMPREHENSIVE DEBUG: ✅ Added streamtape link: {match}")
                    else:
                        other_video_links.add(match)
                        logger.info(f"🔍 Found other video link in text: {match}")

            logger.info(f"🔍 Found {len(videoza_links)} Vidoza links")
            logger.info(f"🔍 Found {len(streamtape_links)} Streamtape links")
            logger.info(f"🔍 Found {len(other_video_links)} other video links")

            # Convert sets to lists for return
            result = {
                'title': clean_title,
                'images': images,
                'vidoza_links': list(videoza_links),
                'streamtape_links': list(streamtape_links),
                'other_video_links': list(other_video_links)
            }

            logger.info(f"✅ Comprehensive extraction completed for {url}")
            return result

        except Exception as e:
            logger.error(f"❌ Error in comprehensive content extraction: {e}")
            return {
                'title': "Error extracting content",
                'images': [],
                'vidoza_links': [],
                'streamtape_links': [],
                'other_video_links': []
            }

    def download_hosted_image(self, page_url, folder='downloaded_images'):
        """Downloads an image from a hosting page like ImageTwist (from example script)"""
        try:
            logger.info(f"📥 Visiting image page: {page_url}")
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Referer': 'https://mmsbee42.com/'
            }

            # Add referer based on domain
            if 'imagetwist.com' in page_url:
                headers['Referer'] = 'https://imagetwist.com/'
            elif 'imagebam.com' in page_url:
                headers['Referer'] = 'https://imagebam.com/'
            elif 'imgbox.com' in page_url:
                headers['Referer'] = 'https://imgbox.com/'

            response = self.session.get(page_url, headers=headers, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # Find the direct image URL on the hosting page
            img_tag = soup.find('img', class_='pic')
            if not img_tag or not img_tag.get('src'):
                # Try alternative selectors
                img_tag = soup.find('img', id='image')
                if not img_tag or not img_tag.get('src'):
                    img_tag = soup.find('img', class_='image')
                    if not img_tag or not img_tag.get('src'):
                        img_tag = soup.find('img', class_='main-image')

            if not img_tag or not img_tag.get('src'):
                logger.warning(f"⚠️ Could not find direct image link on {page_url}")
                return None

            direct_img_url = img_tag.get('src')
            logger.info(f"📥 Found direct image URL: {direct_img_url}")

            # Create directory if it doesn't exist
            if not os.path.exists(folder):
                os.makedirs(folder)

            # Sanitize filename, ensuring it has an extension
            filename = direct_img_url.split('/')[-1]
            if '.' not in filename:
                filename += '.jpg'  # Assume jpg if no extension
            local_filename = os.path.join(folder, re.sub(r'[^a-zA-Z0-9_.-]', '', filename))

            # Download the actual image
            with self.session.get(direct_img_url, stream=True, headers=headers) as r:
                r.raise_for_status()
                with open(local_filename, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)

            logger.info(f"✅ Successfully downloaded {local_filename}")
            return local_filename

        except Exception as e:
            logger.error(f"❌ Error downloading from {page_url}: {e}")
            return None

    def cleanup(self):
        """Cleanup resources including cloudscraper client"""
        if self.cloudscraper_client:
            self.cloudscraper_client.close()
            self.cloudscraper_client = None
            self.logger.info("🧹 ContentExtractor cleanup completed")

# Initialize content extractor
content_extractor = ContentExtractor()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    welcome_message = """🤖 **Bot Started!**

**📋 Main Commands:**
• `/help` - Show detailed help information
• `/status` - Check current bot status
• `/restart` - Reset bot state (fix stuck operations)
• `/comprehensive <url>` - Extract all content from any website
• `/vidoza <url>` - Extract Vidoza videos
• `/streamtape <url>` - Extract Streamtape videos
• `/hotpic <url>` - Extract hotpic.cc media
• `/images <url>` - Extract images

**🔐 Authentication:**
• `/auth` - Complete authentication (Telegram API + FastTelethon)
• `/auth_status` - Show detailed authentication status
• `/init_api` - Initialize Telegram API client
• `/resend` - Request a fresh verification code
• `/cancel` - Cancel authentication process

**📊 Status & Debug:**
• `/me` - Check current user info
• `/channel` - Test channel access
• `/test_channel` - Test channel access
• `/permissions` - Test bot permissions

**⚡ Speed Optimization:**
• `/speed_status` - Check optimization status
• `/client_status` - Check all upload client statuses
# Pyrogram commands removed - using FastTelethon only

**🚨 If Bot Gets Stuck:**
Use `/restart` to reset the bot state and clear any pending operations.

**For Large Video Uploads (>50MB):**
Use `/auth` to complete full authentication (Telegram API + FastTelethon).

**Note:** If you have Two-Factor Authentication (2FA) enabled, you'll need to provide your 2FA password after the verification code."""
    return await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send help message"""
    help_text = """
🤖 **CamGrabber Bot Help**

**📋 Main Commands:**
• `/start` - Start the bot
• `/help` - Show this help message
• `/restart` - Reset bot state (fix stuck operations)
• `/reset` - Reset bot state (same as restart)
• `/status` - Check current bot status
• `/comprehensive` - Extract all content from any website
• `/images` - Extract images from URL
• `/vidoza` - Extract Vidoza videos from URL
• `/streamtape` - Extract Streamtape videos from URL
• `/hotpic` - Extract media from hotpic.cc URLs

**🔐 Authentication:**
• `/auth` - Complete authentication (Telegram API + FastTelethon)
• `/auth_status` - Show detailed authentication status
• `/init_api` - Initialize Telegram API client
• `/resend` - Resend verification code
• `/cancel` - Cancel authentication

**📊 Status & Debug:**
• `/me` - Check current user info
• `/channel` - Test channel access
• `/test_channel` - Test channel access
• `/permissions` - Test bot permissions
• `/join` - Test channel joining
• `/channels` - List your channels
• `/test` - Test channel access
• `/debug` - Debug channel configuration

**📝 Group Topics:**
• `/setgroup <group_id>` - Set group for topic posting
• `/testgroup` - Test group access and topic creation

**⚡ Speed Optimization:**
• `/install_optimizations` - Install fast upload libraries
• `/speed_status` - Check optimization status
• `/client_status` - Check all upload client statuses
# Pyrogram commands removed - using FastTelethon only

**📤 How to Use:**
1. Send any URL to extract content
2. Bot will find images and videos
3. Content will be posted to channel
4. If group is configured, content will also be posted to group topics

**🔧 Features:**
• ✅ Extract images from ImageTwist
• ✅ Extract videos from Vidoza & Streamtape
• ✅ Download and upload videos
• ✅ Large video support (>50MB)
• ✅ Progress tracking for uploads
• ✅ Group topic creation
• ✅ Automatic content organization
• ✅ Comprehensive website scraping (like mmsbee)
• ✅ Support for multiple image hosting services
• ⚡ FastTelethon for ultra-fast uploads

**🚨 Troubleshooting:**
• If bot gets stuck, use `/restart` to reset state
• If authentication fails, use `/auth` to re-authenticate
• If uploads fail, check `/speed_status` for optimization issues
• Use `/status` to check current bot state

**📞 Support:**
For issues, check the console logs or use debug commands.
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def restart_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset bot state and clear any pending operations"""
    try:
        # Clear all user data and state
        context.user_data.clear()

        # Reset any global state variables
        if hasattr(context, 'bot_data'):
            context.bot_data.clear()

        # Clear any pending operations
        if 'waiting_for_type_selection' in context.user_data:
            del context.user_data['waiting_for_type_selection']
        if 'vidoza_urls' in context.user_data:
            del context.user_data['vidoza_urls']
        if 'streamtape_urls' in context.user_data:
            del context.user_data['streamtape_urls']
        if 'stream2z_urls' in context.user_data:
            del context.user_data['stream2z_urls']
        if 'sample_videos' in context.user_data:
            del context.user_data['sample_videos']
        if 'hotpic_videos' in context.user_data:
            del context.user_data['hotpic_videos']
        if 'erome_videos' in context.user_data:
            del context.user_data['erome_videos']
        if 'clean_title' in context.user_data:
            del context.user_data['clean_title']
        if 'selection_message_id' in context.user_data:
            del context.user_data['selection_message_id']

        await update.message.reply_text(
            "🔄 **Bot Completely Reset!**\n\n"
            "✅ All pending operations cleared\n"
            "✅ Type selection state reset\n"
            "✅ Video processing state cleared\n"
            "✅ Ready to start fresh\n\n"
            "**You can now:**\n"
            "• Send a new URL to process\n"
            "• Use any bot command\n"
            "• Start completely from the beginning\n\n"
            "**Bot is now in a clean state!** 🎯",
            parse_mode='Markdown'
        )

        logger.info(f"Bot completely reset for user {update.effective_user.id}")

    except Exception as e:
        logger.error(f"Error in restart command: {e}")
        await update.message.reply_text(
            f"❌ **Error resetting bot state:** {str(e)}",
            parse_mode='Markdown'
        )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check current bot status and state"""
    try:
        status_info = []

        # Check if waiting for type selection
        if context.user_data.get('waiting_for_type_selection', False):
            status_info.append("🔄 **Waiting for video type selection**")

            # Show what videos are available
            if context.user_data.get('vidoza_urls'):
                status_info.append(f"📹 Vidoza videos: {len(context.user_data['vidoza_urls'])} found")
            if context.user_data.get('streamtape_urls'):
                status_info.append(f"📹 Streamtape videos: {len(context.user_data['streamtape_urls'])} found")
            if context.user_data.get('stream2z_urls'):
                status_info.append(f"📹 Stream2z videos: {len(context.user_data['stream2z_urls'])} found")
            if context.user_data.get('luluvid_urls'):
                status_info.append(f"📹 Luluvid videos: {len(context.user_data['luluvid_urls'])} found")
            if context.user_data.get('sample_videos'):
                status_info.append(f"📹 Sample videos: {len(context.user_data['sample_videos'])} found")
            if context.user_data.get('hotpic_videos'):
                status_info.append(f"📹 Hotpic videos: {len(context.user_data['hotpic_videos'])} found")
            if context.user_data.get('erome_videos'):
                status_info.append(f"📹 Erome videos: {len(context.user_data['erome_videos'])} found")

            status_info.append("\n**To continue:** Select video type (1, 2, 3, 4, 5, or 6)")
            status_info.append("**To restart:** Use `/restart` command")
        else:
            status_info.append("✅ **Bot is ready** - No pending operations")

        # Check authentication status
        global telegram_client

        # Check if session file exists first
        if os.path.exists('bot_session.session'):
            # Try to initialize client if not already done
            if not telegram_client:
                try:
                    await init_telegram_client()
                except Exception as e:
                    logger.warning(f"Failed to initialize client in status: {e}")

            if telegram_client and telegram_client.is_connected():
                try:
                    if await telegram_client.is_user_authorized():
                        status_info.append("🔐 **Telegram API:** Authenticated")
                    else:
                        status_info.append("⚠️ **Telegram API:** Not authenticated - use `/auth`")
                except Exception as e:
                    status_info.append(f"⚠️ **Telegram API:** Connection issue - {str(e)[:50]}")
            else:
                status_info.append("⚠️ **Telegram API:** Session exists but not connected - use `/init_api`")
        else:
            status_info.append("⚠️ **Telegram API:** Not connected - use `/auth`")

        # Show stored title if available
        if context.user_data.get('clean_title'):
            status_info.append(f"📝 **Current title:** {context.user_data['clean_title']}")

        status_message = "\n".join(status_info)
        await update.message.reply_text(status_message, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error in status command: {e}")
        await update.message.reply_text(
            f"❌ **Error checking status:** {str(e)}",
            parse_mode='Markdown'
        )

# Add the rest of your functions here (process_url_complete, etc.)
# Copy from o_backup.py

async def process_url_complete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Complete URL processing: extract everything first, then post to channel, then create topic and post everything"""
    # Check if update.message exists
    if not update.message:
        logger.warning("update.message is None")
        return False

    message_text = update.message.text

    # List to keep track of bot messages sent in the chat for later deletion
    bot_messages_to_delete = []

    # URL regex pattern
    url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+|(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}'

    urls = re.findall(url_pattern, message_text)

    if not urls:
        await update.message.reply_text(
            "❌ No valid URL found in your message. Please send a valid URL.",
            parse_mode='Markdown'
        )
        return False

    for url in urls:
        # Step 1: Extract and store everything first
        extract_msg = await update.message.reply_text("🔍 Extracting content (title, images, videos)...")
        bot_messages_to_delete.append(extract_msg.message_id)

        # Extract title - try original method first, then sample style as fallback, then comprehensive
        title = content_extractor.extract_title(url)
        if not title or title == "No title found":
            logger.info("Original title extraction failed, trying sample style method...")
            title = content_extractor.extract_title_sample_style(url)
        if not title or title == "No title found":
            logger.info("Sample style title extraction failed, trying comprehensive method...")
            comprehensive_result = content_extractor.extract_content_comprehensive(url)
            if comprehensive_result and comprehensive_result['title'] != "Error extracting content":
                title = comprehensive_result['title']
        clean_title = content_extractor.clean_title(title)

        # Store clean_title in context for later use
        context.user_data['clean_title'] = clean_title

        # Extract ImageTwist images - try original method first, then sample style as fallback, then comprehensive
        imagetwist_urls = content_extractor.extract_imagetwist_urls(url)
        logger.info(f"🔍 Original image extraction found: {len(imagetwist_urls) if not isinstance(imagetwist_urls, str) else 'Error'}")

        if not imagetwist_urls or isinstance(imagetwist_urls, str):
            logger.info("Original image extraction failed, trying sample style method...")
            imagetwist_urls = content_extractor.extract_image_sample_style(url)
            logger.info(f"🔍 Sample style extraction found: {len(imagetwist_urls) if not isinstance(imagetwist_urls, str) else 'Error'}")

        if not imagetwist_urls or isinstance(imagetwist_urls, str):
            logger.info("Sample style image extraction failed, trying comprehensive method...")
            comprehensive_result = content_extractor.extract_content_comprehensive(url)
            if comprehensive_result and comprehensive_result['images']:
                # Convert comprehensive images to our format
                imagetwist_urls = []
                for img in comprehensive_result['images']:
                    imagetwist_urls.append({
                        'url': img['url'],
                        'alt': img.get('alt', ''),
                        'type': 'comprehensive'
                    })
                logger.info(f"🔍 Comprehensive extraction found: {len(imagetwist_urls)} images")
        else:
            logger.info(f"🔍 Using original extraction method - found {len(imagetwist_urls)} images")

        # Extract video URLs - try original methods first, then sample style as fallback
        vidoza_urls = content_extractor.extract_vidoza_urls(url)
        streamtape_urls = content_extractor.extract_streamtape_urls(url)
        stream2z_urls = content_extractor.extract_stream2z_urls(url)

        # Filter URLs to ensure each type only contains its own URLs
        if vidoza_urls and not isinstance(vidoza_urls, str):
            vidoza_urls = [v for v in vidoza_urls if content_extractor.is_vidoza_url(v['url'])]

        if streamtape_urls and not isinstance(streamtape_urls, str):
            streamtape_urls = [v for v in streamtape_urls if content_extractor.is_streamtape_url(v['url'])]

        if stream2z_urls and not isinstance(stream2z_urls, str):
            stream2z_urls = [v for v in stream2z_urls if content_extractor.is_stream2z_url(v['url'])]

        # Extract luluvid URLs from the page content
        luluvid_urls = content_extractor.extract_luluvid_urls(url)
        if luluvid_urls and not isinstance(luluvid_urls, str):
            luluvid_urls = [v for v in luluvid_urls if content_extractor.is_luluvid_url(v['url'])]
        else:
            luluvid_urls = []

        # Extract hotpic media if it's a hotpic URL
        hotpic_media = []
        if content_extractor.is_hotpic_url(url):
            media_links, album_title = content_extractor.extract_hotpic_media_links(url)
            if media_links:
                # Convert hotpic media to our standard format
                for media in media_links:
                    if media['type'] == 'video':
                        vidoza_urls.append({
                            'url': media['url'],
                            'text': media['title'],
                            'title': media['title'],
                            'type': 'hotpic'
                        })
                    else:  # image
                        hotpic_media.append(media)

        # Add hotpic images to the existing image list
        if hotpic_media:
            logger.info(f"🔍 Adding {len(hotpic_media)} hotpic images to existing images")
            for media in hotpic_media:
                imagetwist_urls.append({
                    'url': media['url'],
                    'alt': media['title'],
                    'type': 'hotpic'
                })

        # Extract erome media if it's an erome URL
        erome_media = []
        if content_extractor.is_erome_url(url):
            media_links, erome_title = content_extractor.extract_erome_media_links(url)
            if media_links:
                # Convert erome media to our standard format
                for media in media_links:
                    if media['type'] == 'video':
                        vidoza_urls.append({
                            'url': media['url'],
                            'text': media['title'],
                            'title': media['title'],
                            'type': 'erome'
                        })
                    else:  # image
                        erome_media.append(media)

        # Add erome images to the existing image list
        if erome_media:
            logger.info(f"🔍 Adding {len(erome_media)} erome images to existing images")
            for media in erome_media:
                imagetwist_urls.append({
                    'url': media['url'],
                    'alt': media['title'],
                    'type': 'erome'
                })

        # If no videos found with original methods, try sample style, then comprehensive
        if (not vidoza_urls or isinstance(vidoza_urls, str)) and (not streamtape_urls or isinstance(streamtape_urls, str)):
            logger.info("Original video extraction failed, trying sample style method...")
            sample_videos = content_extractor.extract_video_sample_style(url)
            if sample_videos:
                # Process sample videos to extract actual video URLs
                actual_video_urls = content_extractor.extract_actual_video_urls_sample_style([v['url'] for v in sample_videos])
                if actual_video_urls:
                    # Convert to our format
                    vidoza_urls = [{'url': url, 'text': '', 'title': '', 'type': 'sample_style'} for url in actual_video_urls]
                    streamtape_urls = []  # Clear streamtape since we found videos with sample method

        # If still no videos, try comprehensive method
        if (not vidoza_urls or isinstance(vidoza_urls, str)) and (not streamtape_urls or isinstance(streamtape_urls, str)):
            logger.info("Sample style video extraction failed, trying comprehensive method...")
            comprehensive_result = content_extractor.extract_content_comprehensive(url)
            if comprehensive_result:
                # Add Vidoza links from comprehensive extraction
                if comprehensive_result['vidoza_links']:
                    vidoza_urls = [{'url': url, 'text': '', 'title': '', 'type': 'comprehensive'} for url in comprehensive_result['vidoza_links']]
                    logger.info(f"🔍 Comprehensive extraction found {len(vidoza_urls)} Vidoza videos")

                # Add Streamtape links from comprehensive extraction
                if comprehensive_result['streamtape_links']:
                    streamtape_urls = [{'url': url, 'text': '', 'title': '', 'type': 'comprehensive'} for url in comprehensive_result['streamtape_links']]
                    logger.info(f"🔍 Comprehensive extraction found {len(streamtape_urls)} Streamtape videos")

        # Store all extracted data for later processing
        extracted_data = {
            'url': url,
            'title': clean_title,
            'imagetwist_urls': imagetwist_urls if not isinstance(imagetwist_urls, str) else [],
            'vidoza_urls': vidoza_urls if not isinstance(vidoza_urls, str) else [],
            'streamtape_urls': streamtape_urls if not isinstance(streamtape_urls, str) else []
        }

        # Store in context for later processing
        context.user_data['extracted_data'] = extracted_data

        # Step 2: Post everything to channel first
        channel_msg = await update.message.reply_text("📤 Posting content to channel...")
        bot_messages_to_delete.append(channel_msg.message_id)

        # Post title to channel
        if clean_title and clean_title != "No title found":
            try:
                await context.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=clean_title,
                    parse_mode=None
                )
                logger.info(f"📤 Title sent to channel: {clean_title}")
            except Exception as e:
                logger.error(f"❌ Error sending title to channel: {e}")

        # Post images to channel using batch processing (for ALL domains)
        successful_image_downloads = 0
        total_images = len(imagetwist_urls) if not isinstance(imagetwist_urls, str) else 0
        logger.info(f"🔍 About to process {total_images} images using batch upload system...")
        if imagetwist_urls and not isinstance(imagetwist_urls, str):
            logger.info(f"🔍 Processing {len(imagetwist_urls)} images using batch upload (works for ALL domains)...")

            # Download all images first
            downloaded_images = []
            for i, img_data in enumerate(imagetwist_urls, 1):
                try:
                    # Handle both ImageTwist and sample-style images
                    image_url = img_data['url']
                    image_alt = img_data.get('alt', 'unknown')
                    image_type = img_data.get('type', 'imagetwist')

                    logger.info(f"📥 Downloading image {i}/{len(imagetwist_urls)} from: {image_url}")
                    file_path = await content_extractor.download_image_async(
                        image_url,
                        f"image_{i}_{image_alt}.jpg",
                        referrer_url=url
                    )

                    if file_path and os.path.exists(file_path):
                        file_size = os.path.getsize(file_path)
                        if file_size > 1000:
                            downloaded_images.append({
                                'file_path': file_path,
                                'index': i,
                                'file_size': file_size
                            })
                            logger.info(f"✅ Image {i} downloaded successfully ({file_size} bytes)")
                        else:
                            logger.warning(f"⚠️ Image {i} file too small ({file_size} bytes) - likely corrupted")
                    else:
                        logger.warning(f"⚠️ Image {i} download failed - check logs above for HTTP error details")
                except Exception as e:
                    logger.error(f"❌ Error downloading image {i}: {e}")

            # Upload images in batches of 5
            batch_size = 5
            total_batches = (len(downloaded_images) + batch_size - 1) // batch_size

            logger.info(f"📤 Starting batch upload: {len(downloaded_images)} images in {total_batches} batches of {batch_size}")

            for batch_num in range(total_batches):
                start_idx = batch_num * batch_size
                end_idx = min(start_idx + batch_size, len(downloaded_images))
                batch_images = downloaded_images[start_idx:end_idx]

                logger.info(f"📤 Batch {batch_num + 1}/{total_batches}: Uploading images {start_idx + 1}-{end_idx}")

                # Upload batch with retry logic
                max_retries = 3
                retry_delay = 5

                for retry in range(max_retries):
                    try:
                        # Upload all images in this batch
                        for img_data in batch_images:
                            with open(img_data['file_path'], 'rb') as img:
                                await context.bot.send_photo(
                                    chat_id=CHANNEL_ID,
                                    photo=img
                                )
                                successful_image_downloads += 1
                                logger.info(f"📤 Image {img_data['index']} sent to channel ({img_data['file_size']} bytes)")

                        logger.info(f"✅ Batch {batch_num + 1}/{total_batches} completed successfully!")
                        break  # Success, exit retry loop

                    except Exception as upload_error:
                        error_msg = str(upload_error)
                        if "429" in error_msg or "Flood control" in error_msg:
                            if retry < max_retries - 1:
                                logger.warning(f"⚠️ Flood control hit for batch {batch_num + 1}, retrying in {retry_delay}s... (attempt {retry + 1}/{max_retries})")
                                await asyncio.sleep(retry_delay)
                                retry_delay *= 2  # Exponential backoff
                        else:
                                logger.error(f"❌ Failed to upload batch {batch_num + 1} after {max_retries} retries due to flood control")
                    else:
                            logger.error(f"❌ Error uploading batch {batch_num + 1}: {upload_error}")
                            break

                # Wait 3 seconds between batches (except after the last batch)
                if batch_num < total_batches - 1:
                    logger.info(f"⏳ Waiting 3s before next batch...")
                    await asyncio.sleep(3)

            # Clean up downloaded files
            for img_data in downloaded_images:
                try:
                    os.remove(img_data['file_path'])
                except:
                    pass

            logger.info(f"✅ Batch upload completed! {successful_image_downloads}/{len(imagetwist_urls)} images sent successfully!")

        # Post videos to channel (if any)
        if vidoza_urls or streamtape_urls or stream2z_urls:
            # Count the URLs
            vidoza_count = len(vidoza_urls) if not isinstance(vidoza_urls, str) else 0
            streamtape_count = len(streamtape_urls) if not isinstance(streamtape_urls, str) else 0
            stream2z_count = len(stream2z_urls) if not isinstance(stream2z_urls, str) else 0

            # Check if we have sample-style videos, hotpic videos, or erome videos
            sample_videos = []
            hotpic_videos = []
            erome_videos = []
            if vidoza_urls and not isinstance(vidoza_urls, str):
                sample_videos = [v for v in vidoza_urls if v.get('type') == 'sample_style']
                hotpic_videos = [v for v in vidoza_urls if v.get('type') == 'hotpic']
                erome_videos = [v for v in vidoza_urls if v.get('type') == 'erome']

            # Show video selection menu with counts
            luluvid_count = len(luluvid_urls) if luluvid_urls else 0
            if sample_videos or hotpic_videos or erome_videos or luluvid_urls or stream2z_count > 0:
                menu_text = f"🎬 **Found videos! Please select type to download:**\n\n"
                menu_text += f"1 = Vidoza videos ({vidoza_count} found)\n"
                menu_text += f"2 = Streamtape videos ({streamtape_count} found)\n"
                menu_text += f"3 = Stream2z videos ({stream2z_count} found)\n"

                if luluvid_urls:
                    menu_text += f"4 = Luluvid videos ({luluvid_count} found)\n"
                if sample_videos:
                    menu_text += f"5 = Sample-style videos ({len(sample_videos)} found)\n"
                if hotpic_videos:
                    menu_text += f"6 = Hotpic videos ({len(hotpic_videos)} found)\n"
                if erome_videos:
                    menu_text += f"7 = Erome videos ({len(erome_videos)} found)\n"

                menu_text += f"\n**💡 Need to restart?** Use `/restart` or `/reset`"

                selection_msg = await update.message.reply_text(menu_text, parse_mode='Markdown')
            else:
                menu_text = f"🎬 **Found videos! Please select type to download:**\n\n"
                menu_text += f"1 = Vidoza videos ({vidoza_count} found)\n"
                menu_text += f"2 = Streamtape videos ({streamtape_count} found)\n"
                if luluvid_urls:
                    menu_text += f"3 = Luluvid videos ({luluvid_count} found)\n"
                menu_text += f"\n**💡 Need to restart?** Use `/restart` or `/reset`"

                selection_msg = await update.message.reply_text(menu_text, parse_mode='Markdown')
            bot_messages_to_delete.append(selection_msg.message_id)

            # Store video data for later processing
            context.user_data['vidoza_urls'] = vidoza_urls if not isinstance(vidoza_urls, str) else []
            context.user_data['streamtape_urls'] = streamtape_urls if not isinstance(streamtape_urls, str) else []
            context.user_data['stream2z_urls'] = stream2z_urls if not isinstance(stream2z_urls, str) else []
            context.user_data['luluvid_urls'] = luluvid_urls
            context.user_data['sample_videos'] = sample_videos
            context.user_data['hotpic_videos'] = hotpic_videos
            context.user_data['erome_videos'] = erome_videos
            context.user_data['waiting_for_type_selection'] = True
            context.user_data['selection_message_id'] = selection_msg.message_id
            context.user_data['selection_timestamp'] = time.time()  # Add timestamp for timeout

            return True  # Stop here and wait for user selection

        # If no videos, proceed to create topic and post everything
        else:
            # Step 3: Create topic and post everything to group
            if GROUP_ID and clean_title and clean_title != "No title found":
                topic_msg = await update.message.reply_text("📝 Creating group topic and posting content...")
                bot_messages_to_delete.append(topic_msg.message_id)

                try:
                    # Create topic
                    logger.info(f"🎯 Creating group topic with title: {clean_title}")
                    topic_id = await create_group_topic(clean_title, GROUP_ID)

                    if topic_id:
                        logger.info(f"✅ Group topic created successfully: {clean_title} (ID: {topic_id})")

                        # Post title to topic
                        try:
                            client_to_use = telegram_client
                            group_entity = await client_to_use.get_entity(GROUP_ID)
                            await client_to_use.send_message(
                                group_entity,
                                clean_title,
                                reply_to=topic_id
                            )
                            logger.info(f"📤 Title posted to group topic")
                        except Exception as e:
                            logger.error(f"❌ Failed to post title to group topic: {e}")

                        # Post images to topic
                        if successful_image_downloads > 0:
                            try:
                                # Re-download images for group posting
                                image_files_for_group = []
                                for i, img_data in enumerate(imagetwist_urls, 1):
                                    try:
                                        file_path = await content_extractor.download_image_async(
                                            img_data['url'],
                                            f"group_image_{i}_{img_data.get('alt', 'unknown')}.jpg",
                                            referrer_url=url
                                        )
                                        if file_path and os.path.exists(file_path) and os.path.getsize(file_path) > 1000:
                                            image_files_for_group.append(file_path)
                                    except Exception as e:
                                        logger.error(f"Error preparing image for group: {e}")

                                if image_files_for_group:
                                    logger.info(f"⏳ Waiting 3s before posting {len(image_files_for_group)} images to group...")
                                    await asyncio.sleep(3)
                                    await post_images_to_group_topic(image_files_for_group, topic_id, GROUP_ID)
                                    logger.info(f"📤 Images posted to group topic")

                                # Clean up group image files
                                for file_path in image_files_for_group:
                                    try:
                                        os.remove(file_path)
                                    except:
                                        pass
                            except Exception as e:
                                logger.error(f"❌ Failed to post images to group topic: {e}")

                        logger.info(f"✅ All content posted to group topic")
                    else:
                        logger.warning("❌ Failed to create group topic, posting to group without topic.")
                except Exception as e:
                    logger.error(f"❌ Error creating group topic: {e}")
            else:
                logger.warning("❌ No group ID or title available for group posting")

        # Send completion message
        completion_msg = await update.message.reply_text("✅ Processing complete! All content sent to channel and group.")
        bot_messages_to_delete.append(completion_msg.message_id)

    # --- New Logic for Cleaning and Restarting ---
    await asyncio.sleep(3) # Give user a moment to see the completion message

    # Also try to delete the user's original message
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except Exception as e:
        logger.warning(f"Could not delete user message: {e}")

    # Delete all messages sent by the bot in this interaction
    for msg_id in bot_messages_to_delete:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
        except Exception as e:
            logger.warning(f"Could not delete message {msg_id}: {e}")

    # Send the welcome message again to "restart" the chat from the user's perspective
    start_msg = await start(update, context) # Re-send the welcome message

    # Add the start message to cleanup list and delete it after a short delay
    if start_msg:
        await asyncio.sleep(2)
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=start_msg.message_id)
        except Exception as e:
            logger.warning(f"Could not delete start message: {e}")

    return True

async def extract_images_from_html_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Extract images from HTML content"""
    # Check if update.message exists
    if not update.message:
        logger.warning("update.message is None in extract_images_from_html_content")
        return False

    html_content = update.message.text

    bot_messages_to_delete = []

    # Check if message contains HTML img tags
    if '<img' not in html_content.lower():
        return False

    processing_msg = await update.message.reply_text("🔍 Extracting images from HTML...")
    bot_messages_to_delete.append(processing_msg.message_id)

    images = content_extractor.extract_images_from_html(html_content)

    if isinstance(images, str):  # Error message
        error_msg = await update.message.reply_text(f"❌ {images}")
        bot_messages_to_delete.append(error_msg.message_id)

    if not images:
        no_images_msg = await update.message.reply_text("❌ No valid images found in the HTML content.")
        bot_messages_to_delete.append(no_images_msg.message_id)
    else:
        response = f"🖼️ **Found {len(images)} image(s) in HTML content:**\n\n"

        for i, img in enumerate(images, 1):
            response += f"**Image {i}:**\n"
            response += f"🔗 **Primary URL:** `{img['primary_url']}`\n"

            if img.get('src') and img.get('data_src') and img['src'] != img['data_src']:
                response += f"📎 **src:** `{img['src']}`\n"
                response += f"📎 **data-src:** `{img['data_src']}`\n"

            if img.get('alt'):
                response += f"📝 **Alt text:** {img['alt']}\n"

            if img.get('class'):
                response += f"🏷️ **CSS Class:** `{img['class']}`\n"

            response += "\n"

        sent_response_msg = await update.message.reply_text(response, parse_mode='Markdown')
        bot_messages_to_delete.append(sent_response_msg.message_id)

    await asyncio.sleep(3) # Give user a moment to see the completion message
    for msg_id in bot_messages_to_delete:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
        except Exception as e:
            logger.warning(f"Could not delete message {msg_id}: {e}")

    start_msg = await start(update, context) # Re-send the welcome message

    # Delete the start message after a short delay
    if start_msg:
        await asyncio.sleep(2)
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=start_msg.message_id)
        except Exception as e:
            logger.warning(f"Could not delete start message: {e}")

    return True

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages and URLs"""
    try:
        # Check if update.message exists
        if not update.message:
            logger.warning("update.message is None in handle_text")
            return

        # Ignore messages sent by the bot itself
        if update.message.from_user and update.message.from_user.id == context.bot.id:
            logger.info("Ignoring message sent by bot itself")
            return

        # Only process messages from private chats (not groups/channels)
        if update.message.chat.type != 'private':
            logger.info(f"Ignoring message from {update.message.chat.type} chat")
            return

        # Check if we're waiting for type selection
        if context.user_data.get('waiting_for_type_selection', False):
            # Check for timeout (5 minutes)
            selection_timestamp = context.user_data.get('selection_timestamp', 0)
            if time.time() - selection_timestamp > 300:  # 5 minutes timeout
                await update.message.reply_text(
                    "⏰ **Selection timeout!**\n\n"
                    "You took too long to select a video type.\n"
                    "Bot state has been automatically reset.\n\n"
                    "Send a new URL to start fresh!",
                    parse_mode='Markdown'
                )
                context.user_data.clear()
                return

            # Check if user sent a command (starts with /)
            if update.message.text.startswith('/'):
                # Let the command handlers process it
                return

            await handle_type_selection(update, context)
            return

        # Process URL
        await process_url_complete(update, context)

    except Exception as e:
        logger.error(f"Error in handle_text: {e}")
        if update.message:
            await update.message.reply_text(f"❌ Error processing message: {str(e)}")

async def handle_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user's type selection response (Vidoza or Streamtape) - new approach"""
    # Check if update.message exists
    if not update.message:
        logger.warning("update.message is None in handle_type_selection")
        return

    user_selection = update.message.text.strip()
    vidoza_urls = context.user_data.get('vidoza_urls', [])
    streamtape_urls = context.user_data.get('streamtape_urls', [])
    stream2z_urls = context.user_data.get('stream2z_urls', [])
    luluvid_urls = context.user_data.get('luluvid_urls', [])
    sample_videos = context.user_data.get('sample_videos', [])
    hotpic_videos = context.user_data.get('hotpic_videos', [])
    erome_videos = context.user_data.get('erome_videos', [])

    # Parse user selection
    try:
        selected_type = int(user_selection)
        if selected_type == 1 and vidoza_urls:
            urls_to_process = vidoza_urls
            type_name = "Vidoza"
        elif selected_type == 2 and streamtape_urls:
            urls_to_process = streamtape_urls
            type_name = "Streamtape"
        elif selected_type == 3 and stream2z_urls:
            urls_to_process = stream2z_urls
            type_name = "Stream2z"
        elif selected_type == 4 and luluvid_urls:
            urls_to_process = luluvid_urls
            type_name = "Luluvid"
        elif selected_type == 5 and sample_videos:
            urls_to_process = sample_videos
            type_name = "Sample-style"
        elif selected_type == 6 and hotpic_videos:
            urls_to_process = hotpic_videos
            type_name = "Hotpic"
        elif selected_type == 7 and erome_videos:
            urls_to_process = erome_videos
            type_name = "Erome"
        else:
            error_msg = "❌ Invalid selection. Please choose:"
            if vidoza_urls:
                error_msg += " 1 for Vidoza,"
            if streamtape_urls:
                error_msg += " 2 for Streamtape,"
            if stream2z_urls:
                error_msg += " 3 for Stream2z,"
            if luluvid_urls:
                error_msg += " 4 for Luluvid,"
            if sample_videos:
                error_msg += " 5 for Sample-style,"
            if hotpic_videos:
                error_msg += " 6 for Hotpic,"
            if erome_videos:
                error_msg += " 7 for Erome"
            error_msg = error_msg.rstrip(',') + " videos."
            await update.message.reply_text(error_msg)
            return
    except ValueError:
        # Check if it's a command
        if user_selection.startswith('/'):
            await update.message.reply_text(
                "🔄 **Command detected!**\n\n"
                "If you want to restart the bot, please use:\n"
                "• `/restart` - Reset bot state\n"
                "• `/reset` - Same as restart\n"
                "• `/status` - Check current status\n\n"
                "**Or select a video type:**\n"
                "1, 2, 3, 4, or 5",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "❌ **Invalid selection format!**\n\n"
                "**Please choose a number:**\n"
                "1, 2, 3, 4, or 5\n\n"
                "**Or use commands:**\n"
                "• `/restart` - Reset bot\n"
                "• `/status` - Check status",
                parse_mode='Markdown'
            )
        return

    if not urls_to_process:
        await update.message.reply_text(f"❌ No {type_name} URLs found to process.")
        context.user_data.clear()
        return

    # Get the stored title from context
    clean_title = context.user_data.get('clean_title')

    # Step 1: Post videos to channel first
    processing_msg = await update.message.reply_text(f"🎬 Processing {len(urls_to_process)} {type_name} video(s) for channel...")
    bot_messages_to_delete = [processing_msg.message_id]

    successful_downloads = 0

    for i, url_item in enumerate(urls_to_process, 1):
        video_url = url_item['url']

        try:
            extract_msg = await update.message.reply_text(f"🔍 Extracting {type_name} video {i}/{len(urls_to_process)}...")
            bot_messages_to_delete.append(extract_msg.message_id)

            # Extract MP4 URL based on type
            if type_name == 'Vidoza':
                mp4_url = content_extractor.extract_vidoza_video_url(video_url)
            elif type_name == 'Streamtape':
                mp4_url = content_extractor.extract_streamtape_video_url(video_url)
            elif type_name == 'Stream2z':
                mp4_url = content_extractor.extract_stream2z_video_url(video_url)
            elif type_name == 'Luluvid':
                # Luluvid works differently - it downloads directly and returns file path
                logger.info(f"🎬 Processing Luluvid video {i} with video_extractor.py method...")
                processing_msg = await update.message.reply_text(f"🔍 Extracting and downloading Luluvid video {i}...")
                bot_messages_to_delete.append(processing_msg.message_id)

                # For Luluvid, we get the downloaded file directly
                video_file = content_extractor.extract_luluvid_video_url(video_url)

                if video_file and os.path.exists(video_file):
                    file_size = os.path.getsize(video_file)
                    download_success_msg = await update.message.reply_text(
                        f"✅ Luluvid video {i} downloaded successfully ({file_size / 1024 / 1024:.1f}MB). Sending to channel..."
                    )
                    bot_messages_to_delete.append(download_success_msg.message_id)

                    # Process Luluvid video upload directly since we already have the file
                    try:
                        # Check file size to determine sending method
                        file_size_mb = content_extractor.get_file_size_mb(video_file)
                        logger.info(f"Processing Luluvid video {i} - File size: {file_size_mb:.1f}MB")

                        # Check if file is too large for Telegram (2000MB limit)
                        if content_extractor.is_file_too_large(video_file):
                            too_large_msg = await update.message.reply_text(
                                f"⚠️ Luluvid video {i} is too large ({file_size_mb:.1f}MB) for Telegram upload.\n"
                                f"Maximum size is 2000MB. Consider using a video compressor."
                            )
                            bot_messages_to_delete.append(too_large_msg.message_id)
                            continue

                        # Add delay before video upload to avoid flood control
                        if i > 1:  # Don't delay the first video
                            delay = min(3, i // 5)  # Progressive delay: 1s after 5 videos, 2s after 10, 3s after 15
                            logger.info(f"⏳ Waiting {delay}s before uploading Luluvid video {i} to avoid flood control...")
                            await asyncio.sleep(delay)

                        # Upload Luluvid video to channel
                        caption = ""
                        max_retries = 3

                        # Try bot's send_video first for ALL videos (bot can handle up to 2GB)
                        logger.info(f"📤 Using bot send_video for Luluvid video ({file_size_mb:.1f}MB)")
                        logger.info(f"📤 Channel ID: {CHANNEL_ID}")
                        logger.info(f"📤 Video file: {video_file}")

                        bot_upload_success = False
                        for retry in range(max_retries):
                            try:
                                with open(video_file, 'rb') as video:
                                    logger.info(f"📤 Attempting to send Luluvid video to channel {CHANNEL_ID}...")
                                    result = await context.bot.send_video(
                                        chat_id=CHANNEL_ID,
                                        video=video,
                                        caption=caption,
                                        supports_streaming=True,
                                        width=1920,
                                        height=1080
                                    )
                                    logger.info(f"✅ Bot send_video successful! Message ID: {result.message_id}")
                                successful_downloads += 1
                                logger.info(f"✅ Successfully uploaded Luluvid video via bot ({file_size_mb:.1f}MB)")

                                # Store video file for group upload later
                                if 'downloaded_videos' not in context.user_data:
                                    context.user_data['downloaded_videos'] = []
                                context.user_data['downloaded_videos'].append(video_file)

                                bot_upload_success = True
                                break  # Success, exit retry loop
                            except Exception as bot_error:
                                error_msg = str(bot_error)
                                logger.error(f"❌ Bot send_video error for Luluvid: {error_msg}")
                                logger.error(f"❌ Error type: {type(bot_error).__name__}")

                                if "413" in error_msg or "Request Entity Too Large" in error_msg:
                                    logger.info("📤 File too large for bot, trying API upload...")
                                    # Try API upload for large files
                                    api_success = await upload_large_video_api(video_file, caption)
                                    if api_success:
                                        successful_downloads += 1
                                        logger.info(f"✅ Successfully uploaded Luluvid video via API ({file_size_mb:.1f}MB)")

                                        # Store video file for group upload later
                                        if 'downloaded_videos' not in context.user_data:
                                            context.user_data['downloaded_videos'] = []
                                        context.user_data['downloaded_videos'].append(video_file)

                                        bot_upload_success = True
                                        break
                                    else:
                                        logger.error("❌ API upload also failed for Luluvid video")
                                elif "429" in error_msg or "FloodWait" in error_msg:
                                    wait_time = 30 + (retry * 10)  # Progressive backoff
                                    logger.info(f"⏳ Rate limited, waiting {wait_time}s before retry {retry + 1}/{max_retries}")
                                    await asyncio.sleep(wait_time)
                                else:
                                    wait_time = 5 + (retry * 5)  # Progressive backoff
                                    logger.info(f"⏳ Error occurred, waiting {wait_time}s before retry {retry + 1}/{max_retries}")
                                    await asyncio.sleep(wait_time)

                        if not bot_upload_success:
                            upload_fail_msg = await update.message.reply_text(
                                f"❌ Failed to upload Luluvid video {i} after {max_retries} attempts"
                            )
                            bot_messages_to_delete.append(upload_fail_msg.message_id)

                        # Note: Video file cleanup will happen after group upload

                    except Exception as luluvid_error:
                        logger.error(f"❌ Error processing Luluvid video {i}: {luluvid_error}")
                        luluvid_error_msg = await update.message.reply_text(
                            f"❌ Error processing Luluvid video {i}: {str(luluvid_error)}"
                        )
                        bot_messages_to_delete.append(luluvid_error_msg.message_id)

                    # Skip the normal download process since we already processed the file
                    mp4_url = "LULUVID_DIRECT_FILE"  # Special marker
                else:
                    no_file_msg = await update.message.reply_text(
                        f"❌ Could not download Luluvid video {i}: {video_url}"
                    )
                    bot_messages_to_delete.append(no_file_msg.message_id)
                    continue
            elif type_name == 'Sample-style':
                # For sample-style videos, the URL is already the direct video URL
                mp4_url = video_url
            elif type_name == 'Hotpic':
                # For hotpic videos, the URL is already the direct video URL
                mp4_url = video_url
            elif type_name == 'Erome':
                # For erome videos, the URL is already the direct video URL
                mp4_url = video_url
            else:
                continue

            if mp4_url and mp4_url != "LULUVID_DIRECT_FILE":
                found_mp4_msg = await update.message.reply_text(f"✅ Found MP4 URL for {type_name} video {i}. Validating...")
                bot_messages_to_delete.append(found_mp4_msg.message_id)

                # Quick validation check before download
                try:
                    import httpx
                    async with httpx.AsyncClient(timeout=10) as client:
                        response = await client.head(mp4_url)
                        if response.status_code == 404:
                            validation_fail_msg = await update.message.reply_text(f"❌ {type_name} video {i} URL is dead (404). Skipping...")
                            bot_messages_to_delete.append(validation_fail_msg.message_id)
                            continue
                        elif response.status_code not in [200, 206, 302, 301, 307, 308]:
                            validation_warn_msg = await update.message.reply_text(f"⚠️ {type_name} video {i} URL returned {response.status_code}. Trying download anyway...")
                            bot_messages_to_delete.append(validation_warn_msg.message_id)
                except Exception as validation_error:
                    validation_error_msg = await update.message.reply_text(f"⚠️ Could not validate {type_name} video {i}. Trying download anyway...")
                    bot_messages_to_delete.append(validation_error_msg.message_id)

                # Add download progress message
                download_progress_msg = await update.message.reply_text(f"📥 Starting download for {type_name} video {i}...")
                bot_messages_to_delete.append(download_progress_msg.message_id)

                try:
                    video_file = await content_extractor.download_video_async(
                        mp4_url,
                        f"{type_name.lower()}_video_{i}.mp4",
                        referrer_url=video_url
                    )

                    if video_file and os.path.exists(video_file):
                        file_size = os.path.getsize(video_file)
                        download_success_msg = await update.message.reply_text(
                            f"✅ Download completed for {type_name} video {i} ({file_size / 1024 / 1024:.1f}MB). Sending to channel..."
                        )
                        bot_messages_to_delete.append(download_success_msg.message_id)

                        # UPLOAD LOGIC SHOULD BE HERE - after successful download
                        if file_size > 100:  # Reduced threshold from 1000 to 100 bytes
                            # Check file size to determine sending method
                            file_size_mb = content_extractor.get_file_size_mb(video_file)
                            logger.info(f"Processing {type_name} video {i} - File size: {file_size_mb:.1f}MB")

                            # Check if file is too large for Telegram (2000MB limit)
                            if content_extractor.is_file_too_large(video_file):
                                too_large_msg = await update.message.reply_text(
                                    f"⚠️ {type_name} video {i} is too large ({file_size_mb:.1f}MB) for Telegram upload.\n"
                                    f"Maximum size is 2000MB. Consider using a video compressor."
                                )
                                bot_messages_to_delete.append(too_large_msg.message_id)
                                continue

                            try:
                                # Add delay before video upload to avoid flood control
                                if i > 1:  # Don't delay the first video
                                    delay = min(3, i // 5)  # Progressive delay: 1s after 5 videos, 2s after 10, 3s after 15
                                    logger.info(f"⏳ Waiting {delay}s before uploading video {i} to avoid flood control...")
                                    await asyncio.sleep(delay)

                                # Route based on file size
                                caption = ""
                                max_retries = 3
                                retry_delay = 10  # Start with 10 seconds for videos

                                # Try bot's send_video first for ALL videos (bot can handle up to 2GB)
                                logger.info(f"📤 Using bot send_video for video ({file_size_mb:.1f}MB)")
                                logger.info(f"📤 Channel ID: {CHANNEL_ID}")
                                logger.info(f"📤 Video file: {video_file}")

                                bot_upload_success = False
                                for retry in range(max_retries):
                                    try:
                                        with open(video_file, 'rb') as video:
                                            logger.info(f"📤 Attempting to send video to channel {CHANNEL_ID}...")
                                            result = await context.bot.send_video(
                                                chat_id=CHANNEL_ID,
                                                video=video,
                                                caption=caption,
                                                supports_streaming=True,
                                                width=1920,
                                                height=1080
                                            )
                                            logger.info(f"✅ Bot send_video successful! Message ID: {result.message_id}")
                                        successful_downloads += 1
                                        logger.info(f"✅ Successfully uploaded video via bot ({file_size_mb:.1f}MB)")

                                        # Store video file for group upload later
                                        if 'downloaded_videos' not in context.user_data:
                                            context.user_data['downloaded_videos'] = []
                                        context.user_data['downloaded_videos'].append(video_file)

                                        bot_upload_success = True
                                        break  # Success, exit retry loop
                                    except Exception as bot_error:
                                        error_msg = str(bot_error)
                                        logger.error(f"❌ Bot send_video error: {error_msg}")
                                        logger.error(f"❌ Error type: {type(bot_error).__name__}")

                                        if "413" in error_msg or "Request Entity Too Large" in error_msg:
                                            logger.warning(f"⚠️ Video too large for bot API ({file_size_mb:.1f}MB), will try API upload")
                                            break  # Exit bot retry loop, try API upload
                                        elif "429" in error_msg or "Flood control" in error_msg:
                                            if retry < max_retries - 1:
                                                logger.warning(f"⚠️ Flood control hit for video {i}, retrying in {retry_delay}s... (attempt {retry + 1}/{max_retries})")
                                                await asyncio.sleep(retry_delay)
                                                retry_delay *= 2  # Exponential backoff
                                            else:
                                                logger.error(f"❌ Failed to upload video {i} after {max_retries} retries due to flood control")
                                                break
                                        elif "400" in error_msg or "Bad Request" in error_msg:
                                            logger.error(f"❌ Bad request error - check channel ID and bot permissions")
                                            break
                                        elif "403" in error_msg or "Forbidden" in error_msg:
                                            logger.error(f"❌ Forbidden error - bot may not have permission to send videos to channel")
                                            break
                                        else:
                                            logger.error(f"❌ Error uploading video {i}: {bot_error}")
                                            break

                                # If bot upload failed due to file size, try API upload as fallback
                                if not bot_upload_success and file_size_mb > 50:
                                    logger.info(f"🚀 Bot upload failed, trying API upload for large video ({file_size_mb:.1f}MB)")
                                    for retry in range(max_retries):
                                        try:
                                            success = await upload_large_video_api(video_file, caption)
                                            if success:
                                                successful_downloads += 1
                                                logger.info(f"✅ Successfully uploaded large video via API ({file_size_mb:.1f}MB)")

                                                # Store video file for group upload later
                                                if 'downloaded_videos' not in context.user_data:
                                                    context.user_data['downloaded_videos'] = []
                                                context.user_data['downloaded_videos'].append(video_file)

                                                break  # Success, exit retry loop
                                            else:
                                                logger.error(f"❌ Failed to upload large video via API ({file_size_mb:.1f}MB)")
                                                break
                                        except Exception as upload_error:
                                            error_msg = str(upload_error)
                                            if "429" in error_msg or "Flood control" in error_msg:
                                                if retry < max_retries - 1:
                                                    logger.warning(f"⚠️ Flood control hit for large video {i}, retrying in {retry_delay}s... (attempt {retry + 1}/{max_retries})")
                                                    await asyncio.sleep(retry_delay)
                                                    retry_delay *= 2  # Exponential backoff
                                                else:
                                                    logger.error(f"❌ Failed to upload large video {i} after {max_retries} retries due to flood control")
                                                    break
                                            else:
                                                logger.error(f"❌ Error uploading large video {i}: {upload_error}")
                                                break
                                    else:
                                        logger.error(f"❌ Failed to upload large video {i} via API after {max_retries} retries")
                                elif not bot_upload_success:
                                    logger.error(f"❌ Failed to upload video {i} via bot after {max_retries} retries")


                            except Exception as e:
                                logger.error(f"Error sending video: {e}")
                        else:
                            logger.warning(f"⚠️ Video file too small ({file_size} bytes), skipping upload")
                    else:
                        download_fail_msg = await update.message.reply_text(f"❌ Download failed for {type_name} video {i} - File too small or corrupted")
                        bot_messages_to_delete.append(download_fail_msg.message_id)
                        continue

                except Exception as e:
                    error_msg = str(e)
                    if "404" in error_msg or "Not Found" in error_msg:
                        download_error_msg = await update.message.reply_text(f"❌ {type_name} video {i} - URL is dead (404)")
                    elif "403" in error_msg or "Forbidden" in error_msg:
                        download_error_msg = await update.message.reply_text(f"❌ {type_name} video {i} - Access denied (403)")
                    elif "timeout" in error_msg.lower():
                        download_error_msg = await update.message.reply_text(f"❌ {type_name} video {i} - Download timeout")
                    else:
                        download_error_msg = await update.message.reply_text(f"❌ {type_name} video {i} - Error: {error_msg[:50]}...")
                    bot_messages_to_delete.append(download_error_msg.message_id)
                    continue
            elif mp4_url == "LULUVID_DIRECT_FILE":
                # For Luluvid, we already have the video_file from the special extraction process
                logger.info(f"🎬 Luluvid video {i} already downloaded, proceeding to upload...")
            elif mp4_url:
                # This shouldn't happen, but handle it just in case
                logger.warning(f"Unexpected mp4_url value for {type_name}: {mp4_url}")
                continue

                if video_file and os.path.exists(video_file):
                    file_size = os.path.getsize(video_file)
                    if file_size > 100:  # Reduced threshold from 1000 to 100 bytes
                        # Check file size to determine sending method
                        file_size_mb = content_extractor.get_file_size_mb(video_file)
                        logger.info(f"Processing {type_name} video {i} - File size: {file_size_mb:.1f}MB")

                        # Check if file is too large for Telegram (2000MB limit)
                        if content_extractor.is_file_too_large(video_file):
                            too_large_msg = await update.message.reply_text(
                                f"⚠️ {type_name} video {i} is too large ({file_size_mb:.1f}MB) for Telegram upload.\n"
                                f"Maximum size is 2000MB. Consider using a video compressor."
                            )
                            bot_messages_to_delete.append(too_large_msg.message_id)
                            continue

                        try:
                            # Add delay before video upload to avoid flood control
                            if i > 1:  # Don't delay the first video
                                delay = min(3, i // 5)  # Progressive delay: 1s after 5 videos, 2s after 10, 3s after 15
                                logger.info(f"⏳ Waiting {delay}s before uploading video {i} to avoid flood control...")
                                await asyncio.sleep(delay)

                            # Route based on file size
                            caption = ""
                            max_retries = 3
                            retry_delay = 10  # Start with 10 seconds for videos

                            if file_size_mb < 50:
                                # Use bot's send_video for small videos (under 50MB)
                                logger.info(f"📤 Using bot send_video for small video ({file_size_mb:.1f}MB)")
                                logger.info(f"📤 Channel ID: {CHANNEL_ID}")
                                logger.info(f"📤 Video file: {video_file}")
                                for retry in range(max_retries):
                                    try:
                                        with open(video_file, 'rb') as video:
                                            logger.info(f"📤 Attempting to send video to channel {CHANNEL_ID}...")
                                            result = await context.bot.send_video(
                                                chat_id=CHANNEL_ID,
                                                video=video,
                                                caption=caption,
                                                supports_streaming=True,
                                                width=1920,
                                                height=1080
                                            )
                                            logger.info(f"✅ Bot send_video successful! Message ID: {result.message_id}")
                                        successful_downloads += 1
                                        logger.info(f"✅ Successfully uploaded small video via bot ({file_size_mb:.1f}MB)")
                                        break  # Success, exit retry loop
                                    except Exception as bot_error:
                                        error_msg = str(bot_error)
                                        logger.error(f"❌ Bot send_video error: {error_msg}")
                                        logger.error(f"❌ Error type: {type(bot_error).__name__}")

                                        if "429" in error_msg or "Flood control" in error_msg:
                                            if retry < max_retries - 1:
                                                logger.warning(f"⚠️ Flood control hit for small video {i}, retrying in {retry_delay}s... (attempt {retry + 1}/{max_retries})")
                                                await asyncio.sleep(retry_delay)
                                                retry_delay *= 2  # Exponential backoff
                                            else:
                                                logger.error(f"❌ Failed to upload small video {i} after {max_retries} retries due to flood control")
                                                break
                                        elif "400" in error_msg or "Bad Request" in error_msg:
                                            logger.error(f"❌ Bad request error - check channel ID and bot permissions")
                                            break
                                        elif "403" in error_msg or "Forbidden" in error_msg:
                                            logger.error(f"❌ Forbidden error - bot may not have permission to send videos to channel")
                                            break
                                        else:
                                            logger.error(f"❌ Error uploading small video {i}: {bot_error}")
                                            break
                                else:
                                    logger.error(f"❌ Failed to upload small video {i} via bot after {max_retries} retries")
                            else:
                                # Use API upload for large videos (50MB+)
                                logger.info(f"🚀 Using API upload for large video ({file_size_mb:.1f}MB)")
                                for retry in range(max_retries):
                                    try:
                                        success = await upload_large_video_api(video_file, caption)
                                        if success:
                                            successful_downloads += 1
                                            logger.info(f"✅ Successfully uploaded large video via API ({file_size_mb:.1f}MB)")
                                            break  # Success, exit retry loop
                                        else:
                                            logger.error(f"❌ Failed to upload large video via API ({file_size_mb:.1f}MB)")
                                            break
                                    except Exception as upload_error:
                                        error_msg = str(upload_error)
                                        if "429" in error_msg or "Flood control" in error_msg:
                                            if retry < max_retries - 1:
                                                logger.warning(f"⚠️ Flood control hit for large video {i}, retrying in {retry_delay}s... (attempt {retry + 1}/{max_retries})")
                                                await asyncio.sleep(retry_delay)
                                                retry_delay *= 2  # Exponential backoff
                                            else:
                                                logger.error(f"❌ Failed to upload large video {i} after {max_retries} retries due to flood control")
                                                break
                                        else:
                                            logger.error(f"❌ Error uploading large video {i}: {upload_error}")
                                            break
                                else:
                                    logger.error(f"❌ Failed to upload large video {i} via API after {max_retries} retries")
                        except Exception as e:
                            logger.error(f"Error sending video: {e}")
                            # Fallback to send_video with streaming support
                            try:
                                with open(video_file, 'rb') as video:
                                    await context.bot.send_video(
                                        chat_id=CHANNEL_ID,
                                        video=video,
                                        caption="",
                                        supports_streaming=True,
                                        width=1920,
                                        height=1080
                                    )
                                    successful_downloads += 1
                                logger.info(f"Sent video with streaming support ({file_size_mb:.1f}MB)")
                            except Exception as e2:
                                logger.error(f"Failed to send video with streaming: {e2}")
                                # Final fallback to document if video fails
                                try:
                                    with open(video_file, 'rb') as video:
                                        await context.bot.send_document(
                                            chat_id=CHANNEL_ID,
                                            document=video,
                                            caption=""
                                        )
                                        successful_downloads += 1
                                    logger.info(f"Sent video as document final fallback ({file_size_mb:.1f}MB)")
                                except Exception as e3:
                                    logger.error(f"Failed to send video as document: {e3}")
                                    send_fail_msg = await update.message.reply_text(
                                        f"❌ Failed to send {type_name} video {i} to channel: {str(e3)}"
                                    )
                                    bot_messages_to_delete.append(send_fail_msg.message_id)
                    else:
                        corrupt_video_msg = await update.message.reply_text(
                            f"❌ {type_name} video {i} appears to be corrupted or empty."
                        )
                        bot_messages_to_delete.append(corrupt_video_msg.message_id)

                    # Note: Video file cleanup will happen after group upload
                else:
                    download_fail_msg = await update.message.reply_text(
                        f"❌ No valid MP4 URL found for {type_name} video {i}"
                    )
                    bot_messages_to_delete.append(download_fail_msg.message_id)
            else:
                no_mp4_msg = await update.message.reply_text(
                    f"❌ Could not extract MP4 URL from {type_name} video {i}: {video_url}"
                )
                bot_messages_to_delete.append(no_mp4_msg.message_id)

        except Exception as e:
            logger.error(f"Error processing {type_name} video {i}: {e}")
            process_error_msg = await update.message.reply_text(
                f"❌ Error processing {type_name} video {i}: {str(e)}"
            )
            bot_messages_to_delete.append(process_error_msg.message_id)

    # Step 2: Create topic and post everything to group
    if GROUP_ID and clean_title and clean_title != "No title found" and successful_downloads > 0:
        topic_msg = await update.message.reply_text("📝 Creating group topic and posting content...")
        bot_messages_to_delete.append(topic_msg.message_id)

        try:
            # Create topic
            logger.info(f"🎯 Creating group topic with title: {clean_title}")
            topic_id = await create_group_topic(clean_title, GROUP_ID)

            if topic_id:
                logger.info(f"✅ Group topic created successfully: {clean_title} (ID: {topic_id})")

                # Post title to topic
                try:
                    client_to_use = telegram_client
                    group_entity = await client_to_use.get_entity(GROUP_ID)
                    await client_to_use.send_message(
                        group_entity,
                        clean_title,
                        reply_to=topic_id
                    )
                    logger.info(f"📤 Title posted to group topic")
                except Exception as e:
                    logger.error(f"❌ Failed to post title to group topic: {e}")

                # Post images to topic FIRST (if any were extracted)
                extracted_data = context.user_data.get('extracted_data', {})
                imagetwist_urls = extracted_data.get('imagetwist_urls', [])

                if imagetwist_urls and not isinstance(imagetwist_urls, str):
                    try:
                        logger.info(f"📤 Posting {len(imagetwist_urls)} images to group topic")

                        # Re-download images for group posting using batch system
                        logger.info(f"📤 Preparing {len(imagetwist_urls)} images for group posting using batch system...")

                        # Download all images for group
                        group_images = []
                        for i, img_data in enumerate(imagetwist_urls, 1):
                            try:
                                # Handle both ImageTwist and sample-style images
                                image_url = img_data['url']
                                image_alt = img_data.get('alt', 'unknown')
                                image_type = img_data.get('type', 'imagetwist')

                                logger.info(f"📥 Downloading group image {i}/{len(imagetwist_urls)} from: {image_url}")
                                file_path = await content_extractor.download_image_async(
                                    image_url,
                                    f"group_image_{i}_{image_alt}.jpg",
                                    referrer_url=extracted_data.get('url', '')
                                )
                                if file_path and os.path.exists(file_path) and os.path.getsize(file_path) > 1000:
                                    group_images.append(file_path)
                                    logger.info(f"✅ Group image {i} downloaded successfully")
                            except Exception as e:
                                logger.error(f"Error downloading group image {i}: {e}")

                        if group_images:
                            # Upload group images in batches of 5
                            batch_size = 5
                            total_batches = (len(group_images) + batch_size - 1) // batch_size

                            logger.info(f"📤 Starting group batch upload: {len(group_images)} images in {total_batches} batches of {batch_size}")

                            for batch_num in range(total_batches):
                                start_idx = batch_num * batch_size
                                end_idx = min(start_idx + batch_size, len(group_images))
                                batch_images_group = group_images[start_idx:end_idx]

                                logger.info(f"📤 Group Batch {batch_num + 1}/{total_batches}: Uploading images {start_idx + 1}-{end_idx}")

                                # Upload batch with retry logic
                                max_retries = 3
                                retry_delay = 5

                                for retry in range(max_retries):
                                    try:
                                        await post_images_to_group_topic(batch_images_group, topic_id, GROUP_ID)
                                        logger.info(f"✅ Group Batch {batch_num + 1}/{total_batches} completed successfully!")
                                        break  # Success, exit retry loop

                                    except Exception as upload_error:
                                        error_msg = str(upload_error)
                                        if "429" in error_msg or "Flood control" in error_msg:
                                            if retry < max_retries - 1:
                                                logger.warning(f"⚠️ Flood control hit for group batch {batch_num + 1}, retrying in {retry_delay}s... (attempt {retry + 1}/{max_retries})")
                                                await asyncio.sleep(retry_delay)
                                                retry_delay *= 2  # Exponential backoff
                                            else:
                                                logger.error(f"❌ Failed to upload group batch {batch_num + 1} after {max_retries} retries due to flood control")
                                        else:
                                            logger.error(f"❌ Error uploading group batch {batch_num + 1}: {upload_error}")
                                            break

                                # Wait 3 seconds between batches (except after the last batch)
                                if batch_num < total_batches - 1:
                                    logger.info(f"⏳ Waiting 3s before next group batch...")
                                    await asyncio.sleep(3)

                            logger.info(f"✅ Group batch upload completed! {len(group_images)} images posted to group topic!")

                        # Clean up group image files
                        for file_path in group_images:
                            try:
                                os.remove(file_path)
                            except:
                                pass
                    except Exception as e:
                        logger.error(f"❌ Failed to post images to group topic: {e}")

                # Post videos to topic SECOND (re-upload the same videos that were uploaded to channel)
                logger.info(f"📤 Uploading {successful_downloads} videos to group topic...")
                try:
                    # Get the downloaded video files from context
                    downloaded_videos = context.user_data.get('downloaded_videos', [])

                    for i, video_file in enumerate(downloaded_videos, 1):
                        if video_file and os.path.exists(video_file):
                            file_size_mb = content_extractor.get_file_size_mb(video_file)
                            logger.info(f"📤 Uploading video {i} to group topic ({file_size_mb:.1f}MB)")

                            try:
                                # Try bot's send_video first for ALL videos in group (bot can handle up to 2GB)
                                logger.info(f"📤 Using bot send_video for group upload ({file_size_mb:.1f}MB)")
                                group_upload_success = False

                                try:
                                    with open(video_file, 'rb') as video:
                                        result = await context.bot.send_video(
                                            chat_id=GROUP_ID,
                                            video=video,
                                            caption="",
                                            supports_streaming=True,
                                            width=1920,
                                            height=1080,
                                            reply_to_message_id=topic_id
                                        )
                                        logger.info(f"✅ Group video upload successful! Message ID: {result.message_id}")
                                        group_upload_success = True
                                except Exception as group_error:
                                    error_msg = str(group_error)
                                    logger.error(f"❌ Group video upload failed: {group_error}")

                                    if "413" in error_msg or "Request Entity Too Large" in error_msg:
                                        logger.warning(f"⚠️ Video too large for bot API in group ({file_size_mb:.1f}MB), will try API upload")
                                    else:
                                        logger.error(f"❌ Group video upload error: {group_error}")

                                # If bot upload failed due to file size, try API upload as fallback
                                if not group_upload_success and file_size_mb > 50:
                                    logger.info(f"🚀 Bot upload failed, trying API upload for group ({file_size_mb:.1f}MB)")
                                    await upload_to_group_topic(video_file, "", topic_id, GROUP_ID)

                            except Exception as e:
                                logger.error(f"❌ Failed to upload video {i} to group topic: {e}")
                        else:
                            logger.warning(f"⚠️ Video file {i} not found or invalid")

                except Exception as e:
                    logger.error(f"❌ Error uploading videos to group topic: {e}")

                logger.info(f"✅ All content posted to group topic")

                # Clean up video files after group upload is complete
                downloaded_videos = context.user_data.get('downloaded_videos', [])
                for video_file in downloaded_videos:
                    if video_file and os.path.exists(video_file):
                        try:
                            os.remove(video_file)
                            logger.info(f"🧹 Cleaned up video file after group upload: {video_file}")
                        except Exception as cleanup_error:
                            logger.warning(f"⚠️ Could not clean up video file: {cleanup_error}")

                # Clear the downloaded videos list
                context.user_data['downloaded_videos'] = []
            else:
                logger.warning("❌ Failed to create group topic, posting to group without topic.")
        except Exception as e:
            logger.error(f"❌ Error creating group topic: {e}")

            # Clean up video files even if group posting failed
            downloaded_videos = context.user_data.get('downloaded_videos', [])
            for video_file in downloaded_videos:
                if video_file and os.path.exists(video_file):
                    try:
                        os.remove(video_file)
                        logger.info(f"🧹 Cleaned up video file (group posting failed): {video_file}")
                    except Exception as cleanup_error:
                        logger.warning(f"⚠️ Could not clean up video file: {cleanup_error}")

            # Clear the downloaded videos list
            context.user_data['downloaded_videos'] = []
    else:
        logger.warning("❌ No group ID, title, or successful downloads available for group posting")

        # Clean up video files even if group posting is skipped
        downloaded_videos = context.user_data.get('downloaded_videos', [])
        for video_file in downloaded_videos:
            if video_file and os.path.exists(video_file):
                try:
                    os.remove(video_file)
                    logger.info(f"🧹 Cleaned up video file (group posting skipped): {video_file}")
                except Exception as cleanup_error:
                    logger.warning(f"⚠️ Could not clean up video file: {cleanup_error}")

        # Clear the downloaded videos list
        context.user_data['downloaded_videos'] = []

    # Send completion message
    if successful_downloads > 0:
        success_msg = await update.message.reply_text(
            f"✅ Successfully sent {successful_downloads}/{len(urls_to_process)} {type_name} videos to channel and group!",
            parse_mode='Markdown'
        )
        bot_messages_to_delete.append(success_msg.message_id)
    else:
        fail_msg = await update.message.reply_text(
            f"❌ Failed to upload any {type_name} videos. They might be protected or the upload process failed.",
            parse_mode='Markdown'
        )
        bot_messages_to_delete.append(fail_msg.message_id)

    # Clean up messages and context
    await asyncio.sleep(3)

    # Also try to delete the user's selection message
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except Exception as e:
        logger.warning(f"Could not delete user selection message: {e}")

    # Delete the original selection message that was sent by process_url_complete
    selection_message_id = context.user_data.get('selection_message_id')
    if selection_message_id:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=selection_message_id)
        except Exception as e:
            logger.warning(f"Could not delete selection message: {e}")

    # Delete all bot messages
    for msg_id in bot_messages_to_delete:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
        except Exception as e:
            logger.warning(f"Could not delete message {msg_id}: {e}")

    # Clear context and restart
    context.user_data.clear()
    start_msg = await start(update, context)

    # Delete the start message after a short delay
    if start_msg:
        await asyncio.sleep(2)
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=start_msg.message_id)
        except Exception as e:
            logger.warning(f"Could not delete start message: {e}")

async def vidoza_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Extract and download Vidoza videos from a webpage URL"""
    bot_messages_to_delete = []

    if not context.args:
        error_msg = await update.message.reply_text(
            "❌ Please provide a URL after the command.\n"
            "Example: `/vidoza https://example.com`",
            parse_mode='Markdown'
        )
        bot_messages_to_delete.append(error_msg.message_id)
        return

    url = context.args[0]
    processing_msg = await update.message.reply_text("🔍 Searching for Vidoza videos...")
    bot_messages_to_delete.append(processing_msg.message_id)

    vidoza_urls = content_extractor.extract_vidoza_urls(url)

    if isinstance(vidoza_urls, str):  # Error message
        error_response_msg = await update.message.reply_text(f"❌ {vidoza_urls}")
        bot_messages_to_delete.append(error_response_msg.message_id)

    if not vidoza_urls:
        no_videos_msg = await update.message.reply_text("❌ No Vidoza videos found on this webpage.")
        bot_messages_to_delete.append(no_videos_msg.message_id)
    else:
        response = f"🎥 **Found {len(vidoza_urls)} Vidoza video(s) from:** `{url}`\n\n"

        for i, vid in enumerate(vidoza_urls, 1):
            response += f"**Video {i}:**\n"
            response += f"🔗 URL: `{vid['url']}`\n"

            if vid.get('text'):
                response += f"📝 Text: {vid['text']}\n"

            if vid.get('title'):
                response += f"🏷️ Title: {vid['title']}\n"

            response += "\n"

        sent_response_msg = await update.message.reply_text(response, parse_mode='Markdown')
        bot_messages_to_delete.append(sent_response_msg.message_id)

    await asyncio.sleep(3)
    for msg_id in bot_messages_to_delete:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
        except Exception as e:
            logger.warning(f"Could not delete message {msg_id}: {e}")

    start_msg = await start(update, context)

    # Delete the start message after a short delay
    if start_msg:
        await asyncio.sleep(2)
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=start_msg.message_id)
        except Exception as e:
            logger.warning(f"Could not delete start message: {e}")

    return True

async def hotpic_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Extract and download media from hotpic.cc URLs"""
    bot_messages_to_delete = []

    if not context.args:
        error_msg = await update.message.reply_text(
            "❌ Please provide a hotpic.cc URL after the command.\n"
            "Example: `/hotpic https://hotpic.cc/album/TwuRVwdVc3R54`",
            parse_mode='Markdown'
        )
        bot_messages_to_delete.append(error_msg.message_id)
        return

    url = context.args[0]

    # Check if it's a valid hotpic.cc URL
    if not content_extractor.is_hotpic_url(url):
        error_msg = await update.message.reply_text(
            "❌ Please provide a valid hotpic.cc URL.\n"
            "Example: `/hotpic https://hotpic.cc/album/TwuRVwdVc3R54`",
            parse_mode='Markdown'
        )
        bot_messages_to_delete.append(error_msg.message_id)
        return

    # Process the hotpic URL
    await process_hotpic_url(update, context, url)
    return True

async def streamtape_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Extract and download Streamtape videos from a webpage URL"""
    bot_messages_to_delete = []

    if not context.args:
        error_msg = await update.message.reply_text(
            "❌ Please provide a URL after the command.\n"
            "Example: `/streamtape https://example.com`",
            parse_mode='Markdown'
        )
        bot_messages_to_delete.append(error_msg.message_id)
        return

    url = context.args[0]
    processing_msg = await update.message.reply_text("🔍 Searching for Streamtape videos...")
    bot_messages_to_delete.append(processing_msg.message_id)

    streamtape_urls = content_extractor.extract_streamtape_urls(url)

    if isinstance(streamtape_urls, str):  # Error message
        error_response_msg = await update.message.reply_text(f"❌ {streamtape_urls}")
        bot_messages_to_delete.append(error_response_msg.message_id)

    if not streamtape_urls:
        no_videos_msg = await update.message.reply_text("❌ No Streamtape videos found on this webpage.")
        bot_messages_to_delete.append(no_videos_msg.message_id)
    else:
        response = f"🎥 **Found {len(streamtape_urls)} Streamtape video(s) from:** `{url}`\n\n"

        for i, vid in enumerate(streamtape_urls, 1):
            response += f"**Video {i}:**\n"
            response += f"🔗 URL: `{vid['url']}`\n"

            if vid.get('text'):
                response += f"📝 Text: {vid['text']}\n"

            if vid.get('title'):
                response += f"🏷️ Title: {vid['title']}\n"

            response += "\n"

        sent_response_msg = await update.message.reply_text(response, parse_mode='Markdown')
        bot_messages_to_delete.append(sent_response_msg.message_id)

    await asyncio.sleep(3)
    for msg_id in bot_messages_to_delete:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
        except Exception as e:
            logger.warning(f"Could not delete message {msg_id}: {e}")

    start_msg = await start(update, context)

    # Delete the start message after a short delay
    if start_msg:
        await asyncio.sleep(2)
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=start_msg.message_id)
        except Exception as e:
            logger.warning(f"Could not delete start message: {e}")

    return True

async def images_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Extract all images from a webpage URL"""
    bot_messages_to_delete = []

    if not context.args:
        error_msg = await update.message.reply_text(
            "❌ Please provide a URL after the command.\n"
            "Example: `/images https://example.com`",
            parse_mode='Markdown'
        )
        bot_messages_to_delete.append(error_msg.message_id)
        return

    url = context.args[0]
    processing_msg = await update.message.reply_text("🔍 Extracting images from webpage...")
    bot_messages_to_delete.append(processing_msg.message_id)

    images = content_extractor.extract_images_from_url(url)

    if isinstance(images, str):  # Error message
        error_response_msg = await update.message.reply_text(f"❌ {images}")
        bot_messages_to_delete.append(error_response_msg.message_id)

    if not images:
        no_images_msg = await update.message.reply_text("❌ No images found on this webpage.")
        bot_messages_to_delete.append(no_images_msg.message_id)
    else:
        response = f"🖼️ **Found {len(images)} image(s) from:** `{url}`\n\n"

        for i, img in enumerate(images[:10], 1):  # Limit to first 10 images
            response += f"**Image {i}:**\n"
            response += f"🔗 URL: `{img['primary_url']}`\n"

            if img.get('alt'):
                response += f"📝 Alt: {img['alt']}\n"

            if img.get('class'):
                response += f"🏷️ Class: `{img['class']}`\n"

            response += "\n"

        if len(images) > 10:
            response += f"... and {len(images) - 10} more images"

        sent_response_msg = await update.message.reply_text(response, parse_mode='Markdown')
        bot_messages_to_delete.append(sent_response_msg.message_id)

    await asyncio.sleep(3)
    for msg_id in bot_messages_to_delete:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
        except Exception as e:
            logger.warning(f"Could not delete message {msg_id}: {e}")

    start_msg = await start(update, context)

    # Delete the start message after a short delay
    if start_msg:
        await asyncio.sleep(2)
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=start_msg.message_id)
        except Exception as e:
            logger.warning(f"Could not delete start message: {e}")

    return True

async def get_channel_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get information about the configured channel"""
    try:
        # Initialize Telegram client if needed
        global telegram_client
        if not telegram_client:
            await init_telegram_client()

        if not telegram_client:
            await update.message.reply_text(
                "❌ Telegram API client not initialized!\n\n"
                "Please use /auth to authenticate first."
            )
            return

        # Check if client is connected
        if not telegram_client.is_connected():
            await telegram_client.connect()

        await update.message.reply_text(
            f"🔍 Checking channel access...\n\n"
            f"Channel ID: {CHANNEL_ID}"
        )

        try:
            # Try to get channel info
            channel = await telegram_client.get_entity(CHANNEL_ID)
            await update.message.reply_text(
                f"✅ Channel found!\n\n"
                f"Title: {channel.title}\n"
                f"ID: {channel.id}\n"
                f"Username: {getattr(channel, 'username', 'None')}\n"
                f"Access: You have access to this channel"
            )

        except Exception as e:
            await update.message.reply_text(
                f"❌ Cannot access channel!\n\n"
                f"Error: {str(e)}\n\n"
                f"Channel ID: {CHANNEL_ID}\n\n"
                f"Try /channels to see your available channels"
            )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Error: {str(e)}"
        )

async def join_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help user join the channel with their Telegram API account"""
    try:
        # Initialize Telegram client if needed
        global telegram_client
        if not telegram_client:
            await init_telegram_client()

        if not telegram_client:
            await update.message.reply_text(
                "❌ **Telegram API client not initialized!**\n\n"
                "Please use `/auth` to authenticate first.",
                parse_mode='Markdown'
            )
            return

        # Check if client is connected
        if not telegram_client.is_connected():
            await telegram_client.connect()

        # Try to join the channel
        try:
            await update.message.reply_text(
                f"🔗 **Attempting to join channel...**\n\n"
                f"**Channel ID:** `{CHANNEL_ID}`\n\n"
                f"This will allow large video uploads (>50MB).",
                parse_mode='Markdown'
            )

            # Try to get channel info first
            channel = await telegram_client.get_entity(CHANNEL_ID)
            await update.message.reply_text(
                f"✅ **Already have access to channel!**\n\n"
                f"**Channel:** {channel.title}\n"
                f"**Large video uploads should work now!**",
                parse_mode='Markdown'
            )

        except Exception as e:
            await update.message.reply_text(
                f"❌ **Cannot access channel!**\n\n"
                f"**Error:** {str(e)}\n\n"
                f"**To fix this:**\n"
                f"1. **Join the channel** with your Telegram account (`{PHONE_NUMBER}`)\n"
                f"2. **Or ask the channel owner** to add you as a member\n"
                f"3. **Or make the channel public**\n\n"
                f"**Channel ID:** `{CHANNEL_ID}`",
                parse_mode='Markdown'
            )

    except Exception as e:
        await update.message.reply_text(
            f"❌ **Error:** {str(e)}",
            parse_mode='Markdown'
        )

async def list_my_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all channels the user has access to"""
    try:
        # Initialize Telegram client if needed
        global telegram_client
        if not telegram_client:
            await init_telegram_client()

        if not telegram_client:
            await update.message.reply_text(
                "❌ Telegram API client not initialized!\n\n"
                "Please use /auth to authenticate first."
            )
            return

        # Check if client is connected
        if not telegram_client.is_connected():
            await telegram_client.connect()

        await update.message.reply_text(
            "🔍 Searching for your channels...\n\n"
            "This may take a moment..."
        )

        try:
            # Get all dialogs (chats, channels, groups)
            dialogs = await telegram_client.get_dialogs()

            # Filter for channels only
            channels = []
            for dialog in dialogs:
                if hasattr(dialog.entity, 'broadcast') and dialog.entity.broadcast:
                    channels.append({
                        'id': dialog.entity.id,
                        'title': dialog.entity.title,
                        'username': getattr(dialog.entity, 'username', None),
                        'access_hash': dialog.entity.access_hash
                    })

            if not channels:
                await update.message.reply_text(
                    "❌ No channels found!\n\n"
                    "You don't have access to any channels with this account."
                )
                return

            # Create message with channel list
            message = "📋 Your Channels:\n\n"
            for i, channel in enumerate(channels, 1):
                channel_id = f"-100{channel['id']}"
                username_text = f" (@{channel['username']})" if channel['username'] else ""
                message += f"{i}. {channel['title']}{username_text}\n"
                message += f"   ID: {channel_id}\n"
                message += f"   Username: {channel['username'] or 'None'}\n\n"

            message += f"Current bot channel ID: {CHANNEL_ID}\n\n"
            message += "To fix: Update the channel ID in info.py to match one of the above IDs."

            await update.message.reply_text(message)

        except Exception as e:
            await update.message.reply_text(
                f"❌ Error getting channels: {str(e)}"
            )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Error: {str(e)}"
        )

async def debug_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug channel configuration"""
    try:
        message = f"🔍 Channel Debug Info:\n\n"
        message += f"CHANNEL_ID from info.py: {CHANNEL_ID}\n"
        message += f"Type: {type(CHANNEL_ID)}\n"

        # Check if it looks like a username
        if CHANNEL_ID.startswith('@'):
            message += f"⚠️ This looks like a username, not a channel ID!\n"
        elif CHANNEL_ID.startswith('-100'):
            message += f"✅ This looks like a proper channel ID\n"
        else:
            message += f"❓ Unknown format\n"

        await update.message.reply_text(message)

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def test_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test access to channels"""
    try:
        # Initialize Telegram client if needed
        global telegram_client
        if not telegram_client:
            await init_telegram_client()

        if not telegram_client:
            await update.message.reply_text(
                "❌ Telegram API client not initialized!\n\n"
                "Please use /auth to authenticate first."
            )
            return

        # Check if client is connected
        if not telegram_client.is_connected():
            await telegram_client.connect()

        await update.message.reply_text(
            "🔍 Testing channel access...\n\n"
            "This will try to access each channel from your list."
        )

        # Test each channel from the list
        test_channels = [
            "-1002679595778",  # Post Data
            "-1002754242754",  # Bot Log Channel
            "-1002866329325",  # bot Bin Channel
            "-1002695291204",  # Desi Viral MMS
            "-1002570908347",  # Leaked MMS Video
            "-1002259835302",  # Oviya Leaked Video
            "@camgrabber_leaked_mms_video",
            "@oviya_leaked_video"
        ]

        results = []
        for channel_id in test_channels:
            try:
                channel = await telegram_client.get_entity(channel_id)
                results.append(f"✅ {channel_id}: {channel.title}")
            except Exception as e:
                results.append(f"❌ {channel_id}: {str(e)}")

        # Send results
        message = "📋 Channel Access Test Results:\n\n"
        message += "\n".join(results)

        await update.message.reply_text(message)

    except Exception as e:
        await update.message.reply_text(
            f"❌ Error: {str(e)}"
        )

async def check_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check current user identity and session status"""
    try:
        # Initialize Telegram client if needed
        global telegram_client
        if not telegram_client:
            await init_telegram_client()

        if not telegram_client:
            await update.message.reply_text(
                "❌ Telegram API client not initialized!\n\n"
                "Please use /auth to authenticate first."
            )
            return

        # Check if client is connected
        if not telegram_client.is_connected():
            await telegram_client.connect()

        # Get current user info
        me = await telegram_client.get_me()

        message = f"🔍 **Current User Info:**\n\n"
        message += f"**Name:** {me.first_name}\n"
        message += f"**Username:** @{me.username}\n"
        message += f"**Phone:** {me.phone}\n"
        message += f"**ID:** {me.id}\n\n"

        # Check if this matches the expected phone
        expected_phone = PHONE_NUMBER.replace('+', '')  # Remove + if present
        actual_phone = me.phone.replace('+', '')  # Remove + if present

        if actual_phone == expected_phone:
            message += f"✅ **Phone matches:** {me.phone}\n"
        else:
            message += f"❌ **Phone mismatch:** Expected {PHONE_NUMBER}, got {me.phone}\n"

        await update.message.reply_text(message, parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(
            f"❌ Error: {str(e)}"
        )

async def test_bot_permissions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test if bot can send messages to the channel"""
    try:
        await update.message.reply_text(
            f"🔍 Testing bot permissions...\n\n"
            f"Channel: {CHANNEL_ID}"
        )

        # Try to send a test message
        try:
            test_msg = await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text="🤖 Bot test message - checking permissions"
            )
            await update.message.reply_text(
                f"✅ **Bot can send messages to channel!**\n\n"
                f"Test message sent successfully.\n"
                f"Message ID: {test_msg.message_id}"
            )

            # Delete the test message after 5 seconds
            await asyncio.sleep(5)
            try:
                await context.bot.delete_message(
                    chat_id=CHANNEL_ID,
                    message_id=test_msg.message_id
                )
                await update.message.reply_text("🗑️ Test message deleted.")
            except:
                pass

        except Exception as e:
            await update.message.reply_text(
                f"❌ **Bot cannot send messages to channel!**\n\n"
                f"Error: {str(e)}\n\n"
                f"**To fix:**\n"
                f"1. Add the bot as admin to the channel\n"
                f"2. Give the bot permission to send messages"
            )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Error: {str(e)}"
        )

async def create_group_topic(title, group_id):
    """Create a new forum topic in a Telegram group"""
    try:
        global telegram_client

        logger.info(f"🔍 Starting group topic creation for group: {group_id}")

        # Try to use the fast_telegram_client first if available (already connected)
        client_to_use = None

        if telegram_client and telegram_client.is_connected():
            logger.info("📞 Using existing Telegram client for group topic")
            client_to_use = telegram_client
        else:
            # Only initialize if no clients are available
            logger.info("📞 Initializing new Telegram client...")
            if not telegram_client:
                await init_telegram_client()

            if not telegram_client:
                logger.error("❌ Telegram client initialization failed")
                return None

            # Check if client is authorized
            if not await telegram_client.is_user_authorized():
                logger.error("❌ Telegram client not authorized - need to authenticate")
                return None

            # Ensure client is connected
            if not telegram_client.is_connected():
                logger.info("🔌 Connecting to Telegram...")
                await telegram_client.connect()

            client_to_use = telegram_client

        logger.info("✅ Client ready for group topic creation")

        # Get current user info
        try:
            me = await client_to_use.get_me()
            logger.info(f"👤 Current user: {me.first_name} (@{me.username}) - ID: {me.id}")
        except Exception as e:
            logger.error(f"❌ Failed to get current user: {e}")

        # Get group entity directly (like test script)
        try:
            logger.info(f"🔍 Getting group entity: {group_id}")
            group_entity = await client_to_use.get_entity(group_id)
            logger.info(f"✅ Found group: {group_entity.title} (ID: {group_entity.id})")
        except Exception as e:
            logger.error(f"❌ Failed to get group entity: {e}")
            return None

        # Check if group supports topics (like test script)
        try:
            # Check if it's a channel/supergroup
            if not hasattr(group_entity, 'megagroup'):
                logger.error("❌ This chat is not a supergroup. Topics only work in supergroups.")
                return None

            # Check if forum mode is enabled (like test script)
            if not (hasattr(group_entity, 'forum') and group_entity.forum):
                logger.error("❌ Forum mode is not enabled in this group. Enable topics first in group settings.")
                return None

            logger.info("✅ Group supports forum topics")
            supports_forum = True
        except Exception as e:
            logger.warning(f"⚠️ Could not check forum support: {e}")
            supports_forum = False

        # If group doesn't support forum topics, return None
        if not supports_forum:
            logger.info("📝 Group does not support topics. Regular posting will be used.")
            return None

        # Clean title for topic name (max 128 characters)
        topic_name = title[:128] if len(title) > 128 else title
        logger.info(f"📝 Creating topic with name: {topic_name}")

        # Create forum topic using the working API format
        result = await client_to_use(CreateForumTopicRequest(
            channel=group_entity,
            title=topic_name,
            icon_emoji_id=None  # No emoji - this is the working format
        ))

        # Extract topic ID from the result
        topic_id = None
        if hasattr(result, 'updates'):
            for update in result.updates:
                if hasattr(update, 'message') and hasattr(update.message, 'id'):
                    topic_id = update.message.id
                    logger.info(f"✅ Created forum topic: {topic_name} (ID: {topic_id})")
                    break

        if not topic_id:
            logger.warning("❌ Could not get topic ID from topic creation result.")

        return topic_id

    except Exception as e:
        logger.error(f"❌ Failed to create forum topic: {e}")
        logger.error(f"❌ Error type: {type(e).__name__}")
        import traceback
        logger.error(f"❌ Full traceback: {traceback.format_exc()}")
        return None

async def upload_to_group_topic(video_file, caption, topic_id, group_id):
    """Upload video to a forum topic in a group or as regular message"""
    try:
        global telegram_client

        client_to_use = telegram_client
        if not client_to_use or not client_to_use.is_connected():
            await init_telegram_client()
            client_to_use = telegram_client

        if not client_to_use:
            logger.error("❌ Telegram client is not available for group upload.")
            return False

        group_entity = await client_to_use.get_entity(group_id)

        # Get file size
        file_size = os.path.getsize(video_file)
        file_size_mb = file_size / (1024 * 1024)

        # Use FastTelethonhelper for ultra-fast uploads
        if FAST_TELETHON_AVAILABLE:
            logger.info("⚡ Using FastTelethonhelper for ultra-fast group upload")
            try:
                # Use FastTelethonhelper's fast_upload
                from FastTelethonhelper import fast_upload

                # Create progress callback for FastTelethonhelper
                def fast_progress_callback(done, total):
                    if done % (5 * 1024 * 1024) == 0:  # Log every 5MB
                        mb_uploaded = done // (1024 * 1024)
                        if total > 0:
                            progress = (done / total) * 100
                            logger.info(f"⚡ FastTelethonhelper Group: {mb_uploaded}MB ({progress:.1f}%)")
                        else:
                            logger.info(f"⚡ FastTelethonhelper Group: {mb_uploaded}MB")

                # Use FastTelethonhelper's fast_upload
                file_object = await fast_upload(
                    client_to_use,
                    video_file,
                    reply=None,
                    name=os.path.basename(video_file),
                    progress_bar_function=fast_progress_callback
                )

                # Send the file to group as video with streaming support
                result = await client_to_use.send_file(
                    group_entity,
                    file_object,
                    caption=caption,
                    supports_streaming=True,
                    video_note=False,
                    force_document=False,
                    reply_to=topic_id
                )

                logger.info(f"✅ Successfully uploaded to group via FastTelethonhelper: {result.id}")
                return True

            except Exception as e:
                logger.warning(f"FastTelethonhelper failed for group upload: {e}")
                # Fall back to standard method
                logger.info("📤 Falling back to standard upload method for group")

        # Standard upload method (fallback)
        with open(video_file, 'rb') as video:
            result = await client_to_use.send_file(
                group_entity,
                video,
                supports_streaming=True,
                reply_to=topic_id
            )

        logger.info(f"✅ Successfully uploaded to group: {result.id}")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to upload to group: {e}")
        return False

async def post_images_to_group_topic(image_files, topic_id, group_id):
    """Post images to a forum topic in a group or as regular messages"""
    try:
        global telegram_client

        client_to_use = telegram_client
        if not client_to_use or not client_to_use.is_connected():
            await init_telegram_client()
            client_to_use = telegram_client

        if not client_to_use:
            logger.error("❌ Telegram client is not available for image upload.")
            return False

        group_entity = await client_to_use.get_entity(group_id)

        successful_uploads = 0

        for image_file in image_files:
            try:
                with open(image_file, 'rb') as image:
                    result = await client_to_use.send_file(
                        group_entity,
                        image,
                        reply_to=topic_id
                    )

                    successful_uploads += 1
                    logger.info(f"✅ Uploaded image {successful_uploads}/{len(image_files)}")

            except Exception as e:
                logger.error(f"❌ Failed to upload image {image_file}: {e}")

        logger.info(f"✅ Successfully uploaded {successful_uploads}/{len(image_files)} images to group")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to post images to group: {e}")
        return False

# --- Flask App Setup ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Telegram Bot is running!"

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# --- Main Bot Function ---
def run_bot_polling():
    """Function to run the Telegram bot's polling mechanism."""
    try:
        application = Application.builder().token(BOT_TOKEN).build()

        # Initialize API clients at startup (only if session files exist)
        async def post_init(application):
            """Initialize API clients after bot starts - only if already authenticated"""
            try:
                logger.info("🔌 Checking for existing API client sessions...")

                # Only initialize clients if session files already exist (user has authenticated before)
                if os.path.exists('bot_session.session'):
                    logger.info("🔍 Found existing session file - initializing API clients...")

                    # Initialize Telegram client
                    if await init_telegram_client():
                        logger.info("✅ Telegram API client initialized successfully")
                    else:
                        logger.warning("⚠️ Telegram API client initialization failed")

                    # Pyrogram initialization removed - using FastTelethon only
                else:
                    logger.info("ℹ️ No session file found - API clients will be initialized on first use")
                    logger.info("💡 Use /auth command to authenticate and enable large file uploads")

            except Exception as e:
                logger.error(f"❌ Error initializing API clients: {e}")

        # Add post_init callback to initialize API clients
        application.post_init = post_init

        # Add shutdown callback to properly cleanup API clients
        async def post_shutdown(application):
            """Cleanup API clients when bot shuts down"""
            try:
                logger.info("🧹 Cleaning up API clients...")

                global telegram_client

                # Cleanup Telegram client
                if telegram_client:
                    try:
                        if telegram_client.is_connected():
                            await telegram_client.disconnect()
                            logger.info("✅ Telegram client disconnected")
                    except Exception as e:
                        logger.warning(f"⚠️ Error disconnecting Telegram client: {e}")
                    finally:
                        telegram_client = None

                # Pyrogram cleanup removed - no longer used

            except Exception as e:
                logger.error(f"❌ Error cleaning up API clients: {e}")

        # Add post_shutdown callback to cleanup API clients
        application.post_shutdown = post_shutdown

        # Note: Bot commands will be set after the bot starts to avoid event loop conflicts

        # Add conversation handler for authentication
        auth_handler = ConversationHandler(
            entry_points=[CommandHandler('auth', auth_command)],
            states={
                PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone_handler)],
                CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, code_handler)],
                PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, password_handler)],
            },
            fallbacks=[CommandHandler('cancel', cancel_auth), CommandHandler('resend', resend_code)],
        )

        # Add handlers
        application.add_handler(auth_handler)
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("channel", get_channel_info))
        application.add_handler(CommandHandler("join", join_channel))
        application.add_handler(CommandHandler("channels", list_my_channels))
        application.add_handler(CommandHandler("debug", debug_channel))
        application.add_handler(CommandHandler("test", test_access))
        application.add_handler(CommandHandler("me", check_me))
        application.add_handler(CommandHandler("permissions", test_bot_permissions))
        application.add_handler(CommandHandler("setgroup", set_group))
        application.add_handler(CommandHandler("testgroup", test_group_access))
        application.add_handler(CommandHandler("test_channel", test_channel_access))
        application.add_handler(CommandHandler("init_api", init_api_command))
        application.add_handler(CommandHandler("images", images_command))
        application.add_handler(CommandHandler("vidoza", vidoza_command))
        application.add_handler(CommandHandler("streamtape", streamtape_command))
        application.add_handler(CommandHandler("hotpic", hotpic_command))
        application.add_handler(CommandHandler("install_optimizations", install_optimizations))
        application.add_handler(CommandHandler("speed_status", speed_status))
# Pyrogram command handlers removed - using FastTelethon only
        application.add_handler(CommandHandler("client_status", client_status))
        application.add_handler(CommandHandler("check_channel", check_channel_access))
        application.add_handler(CommandHandler("list_my_channels", list_my_channels))
        application.add_handler(CommandHandler("restart", restart_command))
        application.add_handler(CommandHandler("reset", restart_command))
        application.add_handler(CommandHandler("status", status_command))
        application.add_handler(CommandHandler("init_api", init_api_command))
        application.add_handler(CommandHandler("auth_status", auth_status_command))
        application.add_handler(CommandHandler("set_commands", set_commands_command))
        application.add_handler(CommandHandler("comprehensive", comprehensive_extract_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

        logger.info("Starting bot polling...")

        # Note: Telegram API client will be initialized on first use
        # Use /init_api command to manually initialize if needed
        if os.path.exists('bot_session.session'):
            logger.info("🔍 Session file found - use /init_api to initialize Telegram API client")

        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Error in bot polling thread: {e}")

def create_progress_bar(current, total, width=30):
    """Create a visual progress bar"""
    percentage = current / total
    filled = int(width * percentage)
    bar = '█' * filled + '░' * (width - filled)
    return f"[{bar}] {percentage*100:.1f}%"

async def upload_progress_callback(current, total):
    """Progress callback for uploads"""
    if total > 0:
        progress_bar = create_progress_bar(current, total)
        file_size_mb = total / (1024 * 1024)
        current_mb = current / (1024 * 1024)
        logger.info(f"📤 Upload Progress: {progress_bar} ({current_mb:.1f}MB / {file_size_mb:.1f}MB)")

async def set_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set the group ID for posting with topics"""
    try:
        # Check if group ID is provided
        if not context.args:
            await update.message.reply_text(
                "❌ **Please provide a group ID!**\n\n"
                "**Usage:** `/setgroup -1001234567890`\n\n"
                "**To get your group ID:**\n"
                "1. Add @userinfobot to your group\n"
                "2. Send any message in the group\n"
                "3. The bot will show you the group ID",
                parse_mode='Markdown'
            )
            return

        group_id = context.args[0]

        # Test if we can access the group
        global telegram_client
        if not telegram_client:
            await init_telegram_client()

        if not telegram_client:
            await update.message.reply_text(
                "❌ **Telegram API client not initialized!**\n\n"
                "Please use `/auth` to authenticate first.",
                parse_mode='Markdown'
            )
            return

        # Check if client is connected
        if not telegram_client.is_connected():
            await telegram_client.connect()

        try:
            # Test group access
            group_entity = await telegram_client.get_entity(group_id)

            # Update the GROUP_ID in info.py
            import info
            info.GROUP_ID = group_id

            await update.message.reply_text(
                f"✅ **Group ID set successfully!**\n\n"
                f"**Group:** {group_entity.title}\n"
                f"**ID:** `{group_id}`\n\n"
                f"**Features enabled:**\n"
                f"• Create topics from titles\n"
                f"• Post videos to topics\n"
                f"• Post images to topics",
                parse_mode='Markdown'
            )

        except Exception as e:
            await update.message.reply_text(
                f"❌ **Cannot access group!**\n\n"
                f"**Error:** {str(e)}\n\n"
                f"**To fix:**\n"
                f"1. Make sure the group ID is correct\n"
                f"2. Add your account to the group\n"
                f"3. Make sure the group allows topics",
                parse_mode='Markdown'
            )

    except Exception as e:
        await update.message.reply_text(
            f"❌ **Error:** {str(e)}",
            parse_mode='Markdown'
        )

async def install_optimizations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Install fast upload optimization libraries"""
    try:
        await update.message.reply_text("⚡ **Installing speed optimization libraries...**\n\nThis will install:\n• FastTelethonhelper (ultra-fast uploads)\n• Pyrogram with TgCrypto (fast alternative method)")

        import subprocess
        import sys

        # Install FastTelethonhelper
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "FastTelethonhelper"])
            await update.message.reply_text("✅ **FastTelethonhelper installed successfully!**")
        except Exception as e:
            await update.message.reply_text(f"❌ **FastTelethonhelper installation failed:** {str(e)}")


        await update.message.reply_text("🔄 **Please restart the bot** to enable the new optimizations!")

    except Exception as e:
        await update.message.reply_text(f"❌ **Installation error:** {str(e)}")

# clear_pyrogram function removed - Pyrogram no longer used

async def client_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check the status of all upload clients"""
    try:
        status_message = "📊 **Upload Client Status Report**\n\n"

        # Check Telegram API client
        global telegram_client
        if telegram_client and telegram_client.is_connected():
            try:
                me = await telegram_client.get_me()
                status_message += f"• **Telegram API**: ✅ Ready (Connected as {me.first_name})\n"
            except:
                status_message += f"• **Telegram API**: ⚠️ Connected but not authorized\n"
        else:
            status_message += f"• **Telegram API**: ❌ Not connected\n"


        # Check channel access
        status_message += f"\n**📺 Channel Access Check:**\n"
        try:
            if telegram_client and telegram_client.is_connected():
                # Try to get the channel entity
                try:
                    channel_entity = await telegram_client.get_entity(int(CHANNEL_ID))
                    status_message += f"• **Channel Access**: ✅ Can access channel '{channel_entity.title}'\n"
                    status_message += f"• **Channel ID**: `{CHANNEL_ID}`\n"
                except Exception as e:
                    status_message += f"• **Channel Access**: ❌ Cannot access channel\n"
                    status_message += f"• **Error**: {str(e)}\n"
                    status_message += f"• **Channel ID**: `{CHANNEL_ID}`\n"
            else:
                status_message += f"• **Channel Access**: ❌ Cannot check (client not connected)\n"
        except Exception as e:
            status_message += f"• **Channel Access**: ❌ Error checking: {str(e)}\n"

        status_message += f"\n**📋 Summary:**\n"

        # Count ready clients
        ready_count = 0
        if telegram_client and telegram_client.is_connected():
            ready_count += 1
        if fast_telegram_client and fast_telegram_client.is_connected():
            ready_count += 1

        if ready_count == 2:
            status_message += f"🚀 **All clients ready!** Ultra-fast uploads available."
        elif ready_count == 1:
            status_message += f"📤 **Basic uploads available.** Large file support working."
        else:
            status_message += f"❌ **No clients ready.** Run `/auth` to authenticate."

        await update.message.reply_text(status_message, parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(f"❌ **Error checking status:** {str(e)}")

async def check_channel_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check and fix channel access issues"""
    try:
        if not telegram_client or not telegram_client.is_connected():
            await update.message.reply_text("❌ **Telegram API client not connected!**\n\nUse `/auth` to authenticate first.")
            return

        await update.message.reply_text("🔍 **Checking channel access...**")

        # Try to get the channel entity
        try:
            channel_entity = await telegram_client.get_entity(int(CHANNEL_ID))
            await update.message.reply_text(
                f"✅ **Channel Access OK!**\n\n"
                f"📺 **Channel:** {channel_entity.title}\n"
                f"🆔 **ID:** `{CHANNEL_ID}`\n"
                f"👤 **Type:** {'Supergroup' if hasattr(channel_entity, 'megagroup') and channel_entity.megagroup else 'Channel'}\n\n"
                f"🚀 **FastTelethon should work now!**"
            )
        except Exception as e:
            await update.message.reply_text(
                f"❌ **Channel Access Failed!**\n\n"
                f"🆔 **Current Channel ID:** `{CHANNEL_ID}`\n"
                f"❌ **Error:** {str(e)}\n\n"
                f"🔧 **To fix this:**\n"
                f"1. Make sure the bot is an **admin** in the channel\n"
                f"2. Make sure your user account (used for /auth) is also an **admin**\n"
                f"3. Check if the channel ID is correct\n"
                f"4. Try using `/list_my_channels` to see available channels\n\n"
                f"💡 **Note:** Bot API can send messages, but Telethon needs admin access for large files."
            )

    except Exception as e:
        await update.message.reply_text(f"❌ **Error:** {str(e)}")

async def list_my_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List channels where the user is an admin"""
    try:
        if not telegram_client or not telegram_client.is_connected():
            await update.message.reply_text("❌ **Telegram API client not connected!**\n\nUse `/auth` to authenticate first.")
            return

        await update.message.reply_text("🔍 **Fetching channels where you have admin access...**")

        channels = []

        try:
            # Get dialogs (channels and groups)
            async for dialog in telegram_client.iter_dialogs():
                if dialog.is_channel:
                    try:
                        entity = await telegram_client.get_entity(dialog.id)
                        # Check if user is admin
                        try:
                            participant = await telegram_client.get_participants(dialog.id, filter='admins')
                            is_admin = any(p.id == (await telegram_client.get_me()).id for p in participant)
                            if is_admin:
                                channels.append(f"📺 **{dialog.name}**\n   ID: `{dialog.id}`\n   ✅ You are admin")
                        except:
                            # If we can't check admin status, still show the channel
                            channels.append(f"📺 **{dialog.name}**\n   ID: `{dialog.id}`\n   ⚠️ Admin status unknown")
                    except Exception as e:
                        channels.append(f"📺 **{dialog.name}**\n   ID: `{dialog.id}`\n   ❌ Access error: {str(e)}")
        except Exception as e:
            await update.message.reply_text(f"❌ **Error fetching channels:** {str(e)}")
            return

        if not channels:
            await update.message.reply_text("ℹ️ **No channels found where you have admin access.**\n\nMake sure you're an admin in the channels you want to use.")
            return

        message = "📋 **Channels with Admin Access:**\n\n" + "\n\n".join(channels)
        message += f"\n\n💡 **To use a channel:**\n"
        message += f"1. Copy the ID from above\n"
        message += f"2. Update `CHANNEL_ID` in `info.py`\n"
        message += f"3. Make sure the bot is also an admin\n"
        message += f"4. Restart the bot"

        await update.message.reply_text(message, parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(f"❌ **Error:** {str(e)}")

async def speed_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check the status of speed optimization libraries"""
    try:
        status_text = "⚡ **Speed Optimization Status:**\n\n"

        # Check FastTelethonhelper
        if FAST_TELETHON_AVAILABLE:
            status_text += "✅ **FastTelethonhelper:** Available (ultra-fast uploads)\n"
        else:
            status_text += "❌ **FastTelethonhelper:** Not available (normal)\n"


        status_text += "\n**Upload Method Priority:**\n"
        if FAST_TELETHON_AVAILABLE:
            status_text += "1. ⚡ FastTelethon (ultra-fast)\n"
            status_text += "2. 📤 Standard Telethon (fallback)\n"
        else:
            status_text += "1. 📤 Standard Telethon (fallback)\n"

        if FAST_TELETHON_AVAILABLE:
            status_text += "\n✅ **Fast-upload optimizations are available!**"
        else:
            status_text += "\n⚠️ **No optimizations available.** Use `/install_optimizations` to install faster upload methods."

        await update.message.reply_text(status_text, parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(f"❌ **Error checking status:** {str(e)}")

async def init_api_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually initialize Telegram API client"""
    try:
        global telegram_client

        await update.message.reply_text("🔍 **Initializing Telegram API client...**")

        # Check if session file exists
        if not os.path.exists('bot_session.session'):
            await update.message.reply_text(
                "❌ **No session file found!**\n\n"
                "Please use `/auth` to authenticate first."
            )
            return

        # Disconnect existing client if any
        if telegram_client and telegram_client.is_connected():
            try:
                await telegram_client.disconnect()
                logger.info("Disconnected existing client")
            except:
                pass
            telegram_client = None

        # Initialize the client
        success = await init_telegram_client()

        if success and telegram_client and telegram_client.is_connected():
            try:
                if await telegram_client.is_user_authorized():
                    me = await telegram_client.get_me()
                    await update.message.reply_text(
                        f"✅ **Telegram API client initialized successfully!**\n\n"
                        f"**User:** {me.first_name} (@{me.username})\n"
                        f"**Phone:** {me.phone}\n"
                        f"**Status:** Ready for uploads!\n\n"
                        f"Now use `/auth_status` to verify the connection."
                    )
                else:
                    await update.message.reply_text(
                        "⚠️ **Session exists but not authorized!**\n\n"
                        "Please use `/auth` to complete authentication."
                    )
            except Exception as e:
                await update.message.reply_text(
                    f"❌ **Authorization check failed:** {str(e)}\n\n"
                    "Please use `/auth` to re-authenticate."
                )
        else:
            await update.message.reply_text(
                "❌ **Failed to initialize Telegram API client!**\n\n"
                "Please check your API credentials in `info.py` and use `/auth` to authenticate."
            )

    except Exception as e:
        await update.message.reply_text(f"❌ **Error:** {str(e)}")

async def test_channel_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test if bot can access the channel"""
    try:
        await update.message.reply_text(f"🧪 **Testing channel access...**\n\nChannel ID: `{CHANNEL_ID}`", parse_mode='Markdown')

        # Test sending a simple message
        try:
            test_msg = await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text="🧪 **Channel Access Test**\n\nThis is a test message to verify bot permissions."
            )
            await update.message.reply_text(f"✅ **Channel access successful!**\n\nMessage ID: `{test_msg.message_id}`", parse_mode='Markdown')

            # Delete the test message
            try:
                await context.bot.delete_message(chat_id=CHANNEL_ID, message_id=test_msg.message_id)
                await update.message.reply_text("🗑️ Test message deleted successfully.")
            except:
                await update.message.reply_text("⚠️ Test message sent but couldn't be deleted (this is normal).")

        except Exception as e:
            error_msg = str(e)
            if "400" in error_msg:
                await update.message.reply_text(f"❌ **Bad Request (400)**\n\nChannel ID `{CHANNEL_ID}` is invalid or doesn't exist.", parse_mode='Markdown')
            elif "403" in error_msg:
                await update.message.reply_text(f"❌ **Forbidden (403)**\n\nBot doesn't have permission to send messages to channel `{CHANNEL_ID}`.\n\nMake sure the bot is added as an admin to the channel.", parse_mode='Markdown')
            elif "404" in error_msg:
                await update.message.reply_text(f"❌ **Not Found (404)**\n\nChannel `{CHANNEL_ID}` not found.", parse_mode='Markdown')
            else:
                await update.message.reply_text(f"❌ **Error:** {error_msg}")

    except Exception as e:
        await update.message.reply_text(f"❌ **Test failed:** {str(e)}")

async def auth_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed authentication status"""
    try:
        global telegram_client

        status_info = []
        status_info.append("🔐 **Detailed Authentication Status:**\n")

        # Check session file
        if os.path.exists('bot_session.session'):
            status_info.append("✅ **Session file:** Found")
        else:
            status_info.append("❌ **Session file:** Not found")

        # Check global client
        if telegram_client:
            status_info.append("✅ **Global client:** Initialized")
            if telegram_client.is_connected():
                status_info.append("✅ **Connection:** Connected")
                try:
                    if await telegram_client.is_user_authorized():
                        me = await telegram_client.get_me()
                        status_info.append(f"✅ **Authorization:** Authenticated as {me.first_name} (@{me.username})")
                        status_info.append(f"📱 **Phone:** {me.phone}")
                    else:
                        status_info.append("❌ **Authorization:** Not authorized")
                except Exception as e:
                    status_info.append(f"❌ **Authorization:** Error - {str(e)[:50]}")
            else:
                status_info.append("❌ **Connection:** Not connected")
        else:
            status_info.append("❌ **Global client:** Not initialized")

        # Test direct session file access
        if os.path.exists('bot_session.session'):
            try:
                test_client = TelegramClient('bot_session', API_ID, API_HASH)
                await test_client.connect()
                if await test_client.is_user_authorized():
                    me = await test_client.get_me()
                    status_info.append(f"✅ **Direct session test:** Working - {me.first_name}")
                else:
                    status_info.append("❌ **Direct session test:** Not authorized")
                await test_client.disconnect()
            except Exception as e:
                status_info.append(f"❌ **Direct session test:** Error - {str(e)[:50]}")

        status_message = "\n".join(status_info)
        await update.message.reply_text(status_message, parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(f"❌ **Error:** {str(e)}")

async def set_commands_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set bot commands for the Telegram menu"""
    try:
        from telegram import BotCommand

        commands = [
            BotCommand("start", "Start the bot"),
            BotCommand("help", "Show help information"),
            BotCommand("status", "Check current bot status"),
            BotCommand("auth", "Setup Telegram API authentication"),
            BotCommand("auth_status", "Show detailed authentication status"),
            BotCommand("init_api", "Initialize Telegram API client"),
            BotCommand("restart", "Reset bot state"),
            BotCommand("comprehensive", "Extract all content from website"),
            BotCommand("vidoza", "Extract Vidoza videos"),
            BotCommand("streamtape", "Extract Streamtape videos"),
            BotCommand("images", "Extract images"),
            BotCommand("hotpic", "Extract hotpic.cc media"),
            BotCommand("me", "Check current user info"),
            BotCommand("channel", "Test channel access"),
            BotCommand("permissions", "Test bot permissions"),
            BotCommand("speed_status", "Check optimization status"),
            BotCommand("pyrogram_auth", "Authenticate Pyrogram"),
        ]

        await context.bot.set_my_commands(commands)
        await update.message.reply_text(
            "✅ **Bot commands set successfully!**\n\n"
            "All commands are now available as clickable buttons in the Telegram menu.\n"
            "You can see them by typing '/' in the chat or using the menu button.",
            parse_mode='Markdown'
        )

    except Exception as e:
        await update.message.reply_text(f"❌ **Error setting commands:** {str(e)}")

async def test_channel_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test access to the current channel ID"""
    try:
        await update.message.reply_text(
            f"🔍 Testing channel access...\n\n"
            f"Current CHANNEL_ID: `{CHANNEL_ID}`"
        )

        # Initialize Telegram client if needed
        global telegram_client
        if not telegram_client:
            await init_telegram_client()

        if not telegram_client:
            await update.message.reply_text(
                "❌ Telegram API client not initialized!\n\n"
                "Please use /auth to authenticate first."
            )
            return

        # Check if client is connected
        if not telegram_client.is_connected():
            await telegram_client.connect()

        # Try different channel ID formats for private channels
        channel_id_variants = [
            CHANNEL_ID,  # Current setting from info.py (integer)
            str(CHANNEL_ID),  # As string
            str(CHANNEL_ID).replace('@', ''),  # Without @
            # For private channels, try without -100 prefix
            str(CHANNEL_ID).replace('-100', ''),
            # Try with different prefixes for private channels
            f"-100{str(CHANNEL_ID).replace('-100', '')}",
            f"-1001{str(CHANNEL_ID).replace('-100', '')}",
        ]

        results = []
        for variant in channel_id_variants:
            try:
                channel = await telegram_client.get_entity(variant)
                results.append(f"✅ {variant}: {channel.title}")
            except Exception as e:
                results.append(f"❌ {variant}: {str(e)}")

        # Send results
        message = "📋 Channel Access Test Results:\n\n"
        message += "\n".join(results)

        await update.message.reply_text(message)

    except Exception as e:
        await update.message.reply_text(
            f"❌ Error: {str(e)}"
        )

async def comprehensive_extract_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comprehensive content extraction command for various websites"""
    try:
        # Check if URL is provided
        if not context.args:
            await update.message.reply_text(
                "❌ **Please provide a URL!**\n\n"
                "**Usage:** `/comprehensive <url>`\n\n"
                "**Example:** `/comprehensive https://mmsbee42.com/index.php?/topic/127341-jungle-me-mangal-and-pro-cameraman/`\n\n"
                "**Supported websites:**\n"
                "• mmsbee42.com\n"
                "• Any website with ImageTwist links\n"
                "• Any website with Vidoza/Streamtape links\n"
                "• General websites with images and videos",
                parse_mode='Markdown'
            )
            return

        url = context.args[0]

        # Send initial message
        status_msg = await update.message.reply_text("🔍 **Starting comprehensive content extraction...**\n\nThis will extract:\n• Title\n• Images (including hosted images)\n• Video links\n• All media content")

        try:
            # Use the comprehensive extraction function
            result = content_extractor.extract_content_comprehensive(url)

            if not result or result['title'] == "Error extracting content":
                await update.message.edit_text("❌ **Failed to extract content from the URL**\n\nPlease check if the URL is valid and accessible.")
                return

            # Display results
            title = result['title']
            images = result['images']
            vidoza_links = result['vidoza_links']
            streamtape_links = result['streamtape_links']
            other_video_links = result['other_video_links']

            # Create result message
            result_text = f"✅ **Comprehensive Extraction Complete!**\n\n"
            result_text += f"📝 **Title:** {title}\n\n"

            if images:
                result_text += f"🖼️ **Images Found:** {len(images)}\n"
                for i, img in enumerate(images[:5], 1):  # Show first 5 images
                    result_text += f"  {i}. {img['url'][:50]}...\n"
                if len(images) > 5:
                    result_text += f"  ... and {len(images) - 5} more\n"
                result_text += "\n"

            if vidoza_links:
                result_text += f"🎬 **Vidoza Videos:** {len(vidoza_links)}\n"
                for i, link in enumerate(vidoza_links[:3], 1):  # Show first 3
                    result_text += f"  {i}. {link}\n"
                if len(vidoza_links) > 3:
                    result_text += f"  ... and {len(vidoza_links) - 3} more\n"
                result_text += "\n"

            if streamtape_links:
                result_text += f"🎬 **Streamtape Videos:** {len(streamtape_links)}\n"
                for i, link in enumerate(streamtape_links[:3], 1):  # Show first 3
                    result_text += f"  {i}. {link}\n"
                if len(streamtape_links) > 3:
                    result_text += f"  ... and {len(streamtape_links) - 3} more\n"
                result_text += "\n"

            if other_video_links:
                result_text += f"🎬 **Other Video Links:** {len(other_video_links)}\n"
                for i, link in enumerate(other_video_links[:3], 1):  # Show first 3
                    result_text += f"  {i}. {link}\n"
                if len(other_video_links) > 3:
                    result_text += f"  ... and {len(other_video_links) - 3} more\n"
                result_text += "\n"

            if not images and not vidoza_links and not streamtape_links and not other_video_links:
                result_text += "⚠️ **No media content found**\n\n"

            result_text += "**💡 Next Steps:**\n"
            result_text += "• Use `/images <url>` to download images\n"
            result_text += "• Use `/vidoza <url>` to download Vidoza videos\n"
            result_text += "• Use `/streamtape <url>` to download Streamtape videos\n"
            result_text += "• Send the URL directly to process everything automatically"

            await status_msg.edit_text(result_text, parse_mode='Markdown')

        except Exception as e:
            logger.error(f"Error in comprehensive extraction: {e}")
            await status_msg.edit_text(f"❌ **Error during extraction:** {str(e)}")

    except Exception as e:
        await update.message.reply_text(f"❌ **Error:** {str(e)}")

async def test_group_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test access to the configured group"""
    try:
        global telegram_client

        if not telegram_client:
            await init_telegram_client()

        if not telegram_client:
            await update.message.reply_text("❌ Telegram client not initialized")
            return

        # Check if client is authorized
        if not await telegram_client.is_user_authorized():
            await update.message.reply_text("❌ Telegram client not authorized - use /auth first")
            return

        # Get current user
        me = await telegram_client.get_me()
        await update.message.reply_text(f"👤 **Current User:**\n• Name: {me.first_name}\n• Username: @{me.username}\n• ID: {me.id}")

        # Test group access
        await update.message.reply_text(f"🔍 **Testing group access for:** `{GROUP_ID}`")

        # Try different group ID formats
        group_id_variants = [
            GROUP_ID,  # Original
            GROUP_ID.replace('-100', ''),  # Without -100 prefix
            int(GROUP_ID),  # As integer
            int(GROUP_ID.replace('-100', '')),  # Integer without prefix
        ]

        group_entity = None
        for variant in group_id_variants:
            try:
                await update.message.reply_text(f"🔍 Trying variant: `{variant}`")
                group_entity = await telegram_client.get_entity(variant)
                await update.message.reply_text(f"✅ **Group Found!**\n• Title: {group_entity.title}\n• ID: {group_entity.id}\n• Type: {type(group_entity).__name__}")
                break
            except Exception as e:
                await update.message.reply_text(f"❌ Failed with variant `{variant}`: {str(e)}")
                continue

        if not group_entity:
            await update.message.reply_text("❌ **Could not access group with any variant**")
            return

        # Check group permissions
        try:
            full_channel = await telegram_client(GetFullChannelRequest(channel=group_entity))
            await update.message.reply_text(f"📊 **Group Info:**\n• Participants: {full_channel.full_chat.participants_count}\n• Forum: {'Yes' if hasattr(full_channel.full_chat, 'forum') and full_channel.full_chat.forum else 'No'}")
        except Exception as e:
            await update.message.reply_text(f"⚠️ Could not get full group info: {str(e)}")

        # Test topic creation
        try:
            test_topic = await telegram_client(CreateForumTopicRequest(
                channel=group_entity,
                title="Test Topic",
                icon_emoji_id=None  # No emoji - working format
            ))

            # Extract topic ID from the result
            if hasattr(test_topic, 'updates') and test_topic.updates:
                topic_id = test_topic.updates[0].id
                await update.message.reply_text(f"✅ **Topic Creation Test:** Success! Topic ID: {topic_id}")
            else:
                await update.message.reply_text("✅ **Topic Creation Test:** Success!")

            await update.message.reply_text("✅ **Group access confirmed!** Forum topics will work.")
        except Exception as e:
            await update.message.reply_text(f"❌ **Topic Creation Test Failed:** {str(e)}")
            await update.message.reply_text("⚠️ **Group will use regular posting** (no forum topics)")
            await update.message.reply_text("✅ **Group access confirmed!** Regular posting will work.")

    except Exception as e:
        await update.message.reply_text(f"❌ **Error:** {str(e)}")

if __name__ == '__main__':
    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    # Run the bot polling (without async initialization)
    run_bot_polling()
