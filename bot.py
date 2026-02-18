# -*- coding: utf-8 -*-
import logging
import os
import re
import uuid
import json
import html
import asyncio
import sys
import shutil
import time
import urllib.parse
import traceback
from datetime import timedelta

# Try importing screenshot lib
try:
    import pyautogui
except ImportError:
    pyautogui = None

# Telegram imports
from telegram import Update, Message, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, 
    ContextTypes, CallbackQueryHandler, Defaults
)
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest

# yt-dlp imports
import yt_dlp
from yt_dlp.utils import DownloadError

# --- SETTINGS ---
BOT_TOKEN = os.environ.get("BOT_TOKEN", "input your token here")

DOWNLOAD_DIR = "downloads"
MAX_FILE_SIZE_BYTES = 49 * 1024 * 1024  # 50MB
CLEANUP_INTERVAL_SECONDS = 600          # 10 min
FILE_TTL_SECONDS = 900                  # 15 min
COOKIES_FILE = "cookies.txt"
IMAGES_DB_FILE = "images.json" 
ADMIN_IDS = [233173001] 

# --- LOGGING ---
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- STORAGE ---
video_requests = {}

# --- SYSTEM CHECK ---
FFMPEG_DIR = None 
FFMPEG_EXE = "ffmpeg"

try:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    DOWNLOAD_DIR = os.path.join(script_dir, DOWNLOAD_DIR)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    
    COOKIES_FILE_PATH = os.path.join(script_dir, COOKIES_FILE)
    IMAGES_DB_PATH = os.path.join(script_dir, IMAGES_DB_FILE)
    
    print("\n" + "="*40)
    print("🚀 FAST SYSTEM STARTUP")
    print("="*40)

    # 1. FFMPEG
    local_ffmpeg = os.path.join(script_dir, "ffmpeg.exe")
    if os.path.exists(local_ffmpeg):
        FFMPEG_DIR = script_dir
        FFMPEG_EXE = local_ffmpeg
        print(f"✅ FFmpeg local: {local_ffmpeg}")
    elif shutil.which("ffmpeg"):
        system_ffmpeg = shutil.which("ffmpeg")
        FFMPEG_DIR = os.path.dirname(system_ffmpeg)
        FFMPEG_EXE = system_ffmpeg
        print(f"✅ FFmpeg system: {system_ffmpeg}")
    else:
        print("❌ CRITICAL: FFmpeg NOT FOUND!")

    # 2. Node.js (Quick check)
    found_node = False
    possible_paths = [shutil.which("node"), r"C:\Program Files\nodejs\node.exe", "/usr/bin/node", "/usr/local/bin/node"]
    for p in possible_paths:
        if p and os.path.exists(p):
            node_dir = os.path.dirname(p)
            if node_dir not in os.environ["PATH"]:
                os.environ["PATH"] += os.pathsep + node_dir
            print(f"✅ Node.js: {p}")
            found_node = True
            break
            
    if not found_node: print("⚠️ Node.js missing (Slow YouTube).")
    print("="*40 + "\n")

except Exception as e:
    logger.error(f"Init error: {e}")
    sys.exit(1)

VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.webm', '.mov', '.avi', '.flv', '.ogv', '.ogg', '.m4v', '.3gp', '.ts')
SUPPORTED_DOMAINS = ["youtube.com", "youtu.be", "tiktok.com", "instagram.com", "reddit.com", "twitch.tv", "x.com", "twitter.com", "vk.com", "pin.it", "pinterest.com"]

#================================================================================
#=                       HELPER FUNCTIONS                                       =
#================================================================================

def load_images_db():
    if not os.path.exists(IMAGES_DB_PATH): return {}
    try:
        with open(IMAGES_DB_PATH, 'r', encoding='utf-8') as f: return json.load(f)
    except: return {}

def save_images_db(data):
    try:
        with open(IMAGES_DB_PATH, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=4)
    except: pass

async def periodic_cleanup_task():
    while True:
        try:
            now = time.time()
            with os.scandir(DOWNLOAD_DIR) as it:
                for entry in it:
                    if entry.is_file():
                        if now - entry.stat().st_mtime > FILE_TTL_SECONDS:
                            try: os.remove(entry.path); logger.info(f"🧹 Del: {entry.name}")
                            except: pass
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)

async def extract_urls(text: str):
    return re.findall(r'(https?://[^\s<>"\']+)', text)

def parse_time(t_str: str) -> float:
    try:
        parts = t_str.split(':')
        if len(parts) == 3: return float(parts[0])*3600 + float(parts[1])*60 + float(parts[2])
        if len(parts) == 2: return float(parts[0])*60 + float(parts[1])
        return float(parts[0])
    except: return 0.0

async def safe_status_update(msg: Message, text: str):
    if not msg: return
    if not msg.from_user.is_bot: return
    try: await msg.edit_text(text)
    except BadRequest: pass
    except Exception as e: logger.warning(f"Status warning: {e}")

#================================================================================
#=                       DOWNLOAD LOGIC                                         =
#================================================================================

async def check_if_url_has_video_FAST(url: str) -> bool:
    url_lower = url.lower()
    if any(domain in url_lower for domain in SUPPORTED_DOMAINS): return True
    parsed = urllib.parse.urlparse(url_lower)
    if any(parsed.path.endswith(ext) for ext in VIDEO_EXTENSIONS): return True
    return False

async def select_best_format(url: str, unique_id: uuid.UUID, loop):
    ydl_opts = {
        'quiet': True, 'skip_download': True, 'noplaylist': True,
        'socket_timeout': 10 
    }
    if os.path.exists(COOKIES_FILE_PATH): ydl_opts['cookiefile'] = COOKIES_FILE_PATH

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
            
        title = info.get('title', 'Video')
        return "bestvideo+bestaudio/best", "ok", title
        
    except DownloadError as e:
        err = str(e).lower()
        reason = "error"
        if "private" in err: reason = "private"
        elif "sign in" in err: reason = "login_req"
        elif "bot" in err: reason = "bot_block"
        return None, reason, None
    except Exception:
        return None, "unknown", None

async def convert_video(input_path, output_path, trim=None):
    cmd = [FFMPEG_EXE, '-y', '-i', input_path]
    if trim:
        start, end = trim
        cmd.extend(['-ss', str(start), '-to', str(end)])
        
    cmd.extend([
        '-c:v', 'libx264', '-preset', 'superfast', 
        '-crf', '23', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '128k',
        '-movflags', '+faststart',
        output_path
    ])
    
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    
    if proc.returncode != 0:
        logger.error(f"FFmpeg Error: {stderr.decode('utf-8', errors='ignore')}")
        return False
    return True

#================================================================================
#=                       HANDLERS                                               =
#================================================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 Бот летает! Кидай ссылки.")

# --- ПОИСК КАРТИНОК (База + Локальные файлы) ---
async def unknown_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg: return
    
    # 1. Парсим текст (или капшн)
    text = msg.text or msg.caption or ""
    parts = text.split()
    if not parts: return
    
    # 2. Получаем команду "/katz" -> "katz"
    cmd = parts[0]
    if not cmd.startswith('/'): return
    cmd_clean = cmd[1:].split('@')[0].lower()

    # 3. Сначала ищем в JSON базе (быстро)
    db = load_images_db()
    if cmd_clean in db:
        await msg.reply_photo(photo=db[cmd_clean], reply_to_message_id=msg.message_id)
        return

    # 4. Если нет в базе — ищем ФАЙЛ в папке скрипта
    # Перебираем возможные расширения
    found_file = None
    for ext in ['.jpg', '.png', '.webp', '.jpeg', '.gif']:
        local_path = os.path.join(script_dir, f"{cmd_clean}{ext}")
        if os.path.exists(local_path):
            found_file = local_path
            break
    
    if found_file:
        try:
            # Отправляем файл как фото
            sent_msg = await msg.reply_photo(
                photo=open(found_file, 'rb'), 
                reply_to_message_id=msg.message_id
            )
            # 5. АВТО-КЕШИРОВАНИЕ: Сохраняем FileID в базу, чтобы в следующий раз было быстрее
            db[cmd_clean] = sent_msg.photo[-1].file_id
            save_images_db(db)
            logger.info(f"📸 Auto-saved /{cmd_clean} to DB.")
        except Exception as e:
            logger.error(f"Error sending local file {found_file}: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    text = msg.text or msg.caption or ""
    
    urls = await extract_urls(text)
    urls = [x for x in urls if "t.me" not in x]
    
    if not urls: return

    is_bulk = len(urls) > 1 or update.effective_chat.type != ChatType.PRIVATE

    for url in urls:
        if not await check_if_url_has_video_FAST(url):
            continue

        if is_bulk:
            asyncio.create_task(execute_download(msg, url, None, is_silent_error=True))
        else:
            req_id = str(uuid.uuid4())[:8]
            video_requests[req_id] = url
            
            kb = [
                [InlineKeyboardButton("🚀 Скачать", callback_data=f"dl|{req_id}")],
                [InlineKeyboardButton("✂️ Обрезать", callback_data=f"ask_trim|{req_id}")]
            ]
            await msg.reply_text(
                f"📹 {url}", 
                reply_markup=InlineKeyboardMarkup(kb),
                disable_web_page_preview=True
            )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() 
    
    data = query.data.split('|')
    action = data[0]
    req_id = data[1]
    
    url = video_requests.get(req_id)
    if not url:
        await query.edit_message_text("⚠️ Ссылка устарела.")
        return

    if action == "dl":
        await query.edit_message_text("🚀 Поехали...")
        asyncio.create_task(execute_download(query.message, url, None))
        del video_requests[req_id]
        
    elif action == "ask_trim":
        prompt_msg = await query.message.reply_text("✂️ Таймкод (например `10-20`):", reply_markup=ForceReply(selective=True))
        context.chat_data[f"trim_req_{prompt_msg.message_id}"] = req_id

async def handle_trim_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg.reply_to_message:
        await handle_message(update, context)
        return

    prompt_id = msg.reply_to_message.message_id
    req_id = context.chat_data.get(f"trim_req_{prompt_id}")
    
    if not req_id: 
        await handle_message(update, context)
        return

    url = video_requests.get(req_id)
    if not url:
        await msg.reply_text("⚠️ Ссылка истекла.")
        return

    try:
        txt = msg.text.strip()
        parts = txt.split('-')
        if len(parts) != 2: raise ValueError
        start = parse_time(parts[0].strip())
        end = parse_time(parts[1].strip())
        if start >= end: raise ValueError
        
        status_msg = await msg.reply_text(f"✂️ Режу {start}-{end}s...")
        asyncio.create_task(execute_download(status_msg, url, (start, end)))
        
        del video_requests[req_id]
        del context.chat_data[f"trim_req_{prompt_id}"]
    except:
        await msg.reply_text("⚠️ Пример: `10-20`")

# --- ADMIN COMMANDS ---
async def screenshot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    if pyautogui is None: return
    status_msg = await update.message.reply_text("📸 ...")
    try:
        loop = asyncio.get_running_loop()
        path = await loop.run_in_executor(None, lambda: pyautogui.screenshot().save(os.path.join(DOWNLOAD_DIR, "sc.png")) or os.path.join(DOWNLOAD_DIR, "sc.png"))
        await update.message.reply_photo(photo=open(path, 'rb'))
        os.remove(path)
        await status_msg.delete()
    except: await status_msg.edit_text("Error")

async def add_pic_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    msg = update.effective_message
    
    photo_id = None
    if msg.reply_to_message and msg.reply_to_message.photo: photo_id = msg.reply_to_message.photo[-1].file_id
    elif msg.photo: photo_id = msg.photo[-1].file_id
    
    if not photo_id: return await msg.reply_text("❌ Где фото?")
    
    name = None
    if context.args: name = context.args[0]
    elif msg.caption: 
        parts = msg.caption.split()
        if len(parts) > 1: name = parts[1]
            
    if not name: return await msg.reply_text("❌ `/addpic name`")
    
    name = name.lower().replace('/', '')
    db = load_images_db(); db[name] = photo_id; save_images_db(db)
    await msg.reply_text(f"✅ `/{name}`")

async def remove_pic_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    if not context.args: return
    cmd = context.args[0].lower().replace('/', '')
    db = load_images_db()
    if cmd in db: del db[cmd]; save_images_db(db); await update.message.reply_text(f"🗑 `/{cmd}` deleted")

# --- EXECUTION ENGINE ---
async def execute_download(status_msg, url, trim, is_silent_error=False):
    uid = uuid.uuid4(); loop = asyncio.get_running_loop()
    
    fmt, reason, title = await select_best_format(url, uid, loop)
    
    if not fmt:
        if not is_silent_error:
            asyncio.create_task(safe_status_update(status_msg, f"❌ Недоступно ({reason})"))
        return

    out_tmpl = os.path.join(DOWNLOAD_DIR, f"%(title).50s_{uid}.%(ext)s")
    
    ydl_opts = {
        'outtmpl': out_tmpl, 
        'format': fmt, 
        'noplaylist': True, 
        'writethumbnail': True,
        'filesize_limit': MAX_FILE_SIZE_BYTES + 50*1024*1024,
        'quiet': True,
        'ffmpeg_location': FFMPEG_DIR
    }
    if os.path.exists(COOKIES_FILE_PATH): ydl_opts['cookiefile'] = COOKIES_FILE_PATH

    v_path = None
    t_path = None
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl: 
            await loop.run_in_executor(None, lambda: ydl.download([url]))
        
        for f in os.listdir(DOWNLOAD_DIR):
            if str(uid) in f:
                if f.endswith(('.mp4', '.mkv', '.mov', '.webm')): v_path = os.path.join(DOWNLOAD_DIR, f)
                elif f.endswith(('.jpg', '.png', '.webp')): t_path = os.path.join(DOWNLOAD_DIR, f)
        
        if not v_path: raise Exception("Download failed")

        final_mp4 = os.path.join(DOWNLOAD_DIR, f"final_{uid}.mp4")
        
        asyncio.create_task(safe_status_update(status_msg, "⚙️ Обработка..."))

        success = await convert_video(v_path, final_mp4, trim=trim)
        
        if success and os.path.exists(final_mp4) and os.path.getsize(final_mp4) > 0:
            try: os.remove(v_path)
            except: pass
            v_path = final_mp4

        if os.path.getsize(v_path) > 49.9 * 1024 * 1024:
            if not is_silent_error: 
                 asyncio.create_task(status_msg.reply_text("❌ > 50MB"))
        else:
            asyncio.create_task(safe_status_update(status_msg, "⬆️ Отправка..."))
            
            with open(v_path, 'rb') as v:
                th = open(t_path, 'rb') if t_path else None
                tgt = status_msg.reply_to_message or status_msg
                await tgt.reply_video(
                    video=v, thumbnail=th, caption=html.escape(title), 
                    parse_mode=ParseMode.HTML, write_timeout=120, supports_streaming=True
                )
                if th: th.close()
            
            if status_msg.from_user.is_bot:
                asyncio.create_task(status_msg.delete())

    except Exception as e:
        logger.error(f"Exec fail: {e}")
        if not is_silent_error and "processing" not in str(e).lower():
             try: await status_msg.reply_text("❌ Ошибка")
             except: pass
    finally:
        for f in os.listdir(DOWNLOAD_DIR): 
            if str(uid) in f: 
                try: os.remove(os.path.join(DOWNLOAD_DIR, f))
                except: pass

async def main():
    if BOT_TOKEN == "YOUR_TOKEN_HERE": return

    defaults = Defaults(parse_mode=ParseMode.HTML)
    
    application = Application.builder().token(BOT_TOKEN).defaults(defaults).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("screenshot", screenshot_command))
    application.add_handler(CommandHandler("addpic", add_pic_command))
    application.add_handler(CommandHandler("removepic", remove_pic_command))
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    application.add_handler(MessageHandler(filters.REPLY & filters.TEXT & ~filters.COMMAND, handle_trim_reply))
    application.add_handler(MessageHandler((filters.TEXT | filters.CAPTION) & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command_handler))

    asyncio.create_task(periodic_cleanup_task())

    await application.initialize()
    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    
    logger.info("🤖 Bot started (FINAL).")
    stop_event = asyncio.Event()
    try: await stop_event.wait()
    except asyncio.CancelledError: pass
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
    except Exception: traceback.print_exc()
