from pyrogram import Client, filters, enums
import yt_dlp
import os
from dotenv import load_dotenv
import asyncio

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Create downloads folder if it doesn't exist
if not os.path.exists("downloads"):
    os.makedirs("downloads")

app = Client("youtube_downloader_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Store cookies file path here if uploaded
cookies_path = None

def sizeof_fmt(num, suffix="B"):
    # Converts bytes to human readable format (e.g. 2.3 MB)
    for unit in ["", "K", "M", "G", "T", "P", "E", "Z"]:
        if abs(num) < 1024.0:
            return f"{num:3.1f} {unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f} Y{suffix}"

@app.on_message(filters.command("start"))
async def start_handler(client, message):
    await message.reply_text(
        "👋 Hello! Send me a YouTube video URL to download.\n\n"
        "You can also upload your YouTube browser cookies file (cookies.txt) to download age-restricted videos."
    )

@app.on_message(filters.document & filters.private)
async def receive_cookies(client, message):
    global cookies_path

    if message.document.file_name.endswith(".txt") or message.document.file_name.endswith(".cookies"):
        # Download the cookies file
        file_path = await message.download()
        cookies_path = file_path
        await message.reply("✅ Cookies file received! Now you can send YouTube links that require login.")
    else:
        await message.reply("❌ Please upload a valid cookies.txt file.")

@app.on_message(filters.text & ~filters.command("start"))
async def download_video(client, message):
    url = message.text.strip()
    if not url.startswith("http"):
        return await message.reply_text("⚠️ Please send a valid YouTube URL!")

    await client.send_chat_action(message.chat.id, enums.ChatAction.TYPING)

    ydl_opts_info = {
        'quiet': True,
        'skip_download': True,
        'no_warnings': True,
        'cookiefile': cookies_path,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return await message.reply(f"❌ Extraction error: {str(e)}")

    formats = [f for f in info.get("formats", []) if f.get("filesize") and f.get("ext") == "mp4" and f.get("vcodec") != "none"]
    unique_formats = {}
    for f in formats:
        res = f.get("height")
        if res and res not in unique_formats:
            unique_formats[res] = f

    sorted_formats = sorted(unique_formats.items(), key=lambda x: x[0])

    app.formats_cache = getattr(app, "formats_cache", {})
    app.formats_cache[message.message_id] = sorted_formats

    keyboard = [[
        {
            "text": f"{res}p ({sizeof_fmt(f.get('filesize', 0))})",
            "callback_data": f"download_{message.message_id}_{res}"
        }
    ] for res, f in sorted_formats]

    await message.reply(
        f"🎬 *{info.get('title', 'Video')}*\n\nChoose download quality:",
        reply_markup={"inline_keyboard": keyboard},
        parse_mode="markdown"
    )

@app.on_callback_query()
async def on_quality_selected(client, callback_query):
    data = callback_query.data
    if not data.startswith("download_"):
        return

    _, msg_id, res_str = data.split("_")
    res = int(res_str)

    formats = app.formats_cache.get(int(msg_id))
    if not formats:
        return await callback_query.answer("❌ Session expired, please send the URL again.", show_alert=True)

    chosen_format = None
    for height, f in formats:
        if height == res:
            chosen_format = f
            break
    if not chosen_format:
        return await callback_query.answer("❌ Format not found.", show_alert=True)

    url_message = await client.get_messages(callback_query.message.chat.id, int(msg_id))
    video_url = url_message.text or url_message.caption or None
    if not video_url:
        return await callback_query.answer("❌ Cannot find video URL.", show_alert=True)

    await callback_query.answer(f"⏳ Downloading {res}p...", show_alert=False)
    await client.send_chat_action(callback_query.message.chat.id, enums.ChatAction.UPLOAD_VIDEO)

    progress_msg = await callback_query.message.edit(f"⏳ Starting download of {res}p...")

    def progress_hook(d):
        if d['status'] == 'downloading':
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded_bytes = d.get('downloaded_bytes', 0)
            percent = downloaded_bytes / total_bytes * 100 if total_bytes else 0
            progress_text = (
                f"⏳ Downloading {res}p...\n"
                f"{percent:.1f}% of {sizeof_fmt(total_bytes)}"
            )
            now = asyncio.get_event_loop().time()
            if not hasattr(progress_hook, "last_edit") or now - progress_hook.last_edit > 2:
                asyncio.create_task(progress_msg.edit(progress_text))
                progress_hook.last_edit = now
        elif d['status'] == 'finished':
            asyncio.create_task(progress_msg.edit("✅ Download finished, uploading now..."))

    ydl_opts = {
        'format': f"{chosen_format['format_id']}",
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'quiet': True,
        'cookiefile': cookies_path,
        'progress_hooks': [progress_hook],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            file_path = ydl.prepare_filename(info)
    except Exception as e:
        return await callback_query.message.edit(f"❌ Download failed: {str(e)}")

    async def upload_progress(current, total):
        percent = current / total * 100
        await progress_msg.edit(f"📤 Uploading video... {percent:.1f}%")

    try:
        await client.send_video(
            callback_query.message.chat.id,
            file_path,
            caption=info.get("title", "🎬 Your video"),
            progress=upload_progress,
            progress_args=(),
        )
        os.remove(file_path)
        await progress_msg.delete_reply_markup()
        await progress_msg.edit("✅ Upload completed!")
    except Exception as e:
        await progress_msg.edit(f"❌ Upload failed: {str(e)}")

app.run()