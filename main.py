from pyrogram import Client, filters, enums
import yt_dlp
import os
from dotenv import load_dotenv
import asyncio

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

app = Client("youtube_downloader_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Store cookies file path here if uploaded
cookies_path = None

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

    # Show "typing" animation
    await client.send_chat_action(message.chat.id, enums.ChatAction.TYPING)

    # Step 1: Extract available formats to show quality options
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

    # Prepare buttons for available video formats
    formats = [f for f in info.get("formats", []) if f.get("filesize") and f.get("ext") == "mp4" and f.get("vcodec") != "none"]
    # Filter unique resolutions and sort by height ascending
    unique_formats = {}
    for f in formats:
        res = f.get("height")
        if res and res not in unique_formats:
            unique_formats[res] = f

    # Sort formats by resolution
    sorted_formats = sorted(unique_formats.items(), key=lambda x: x[0])

    # Build buttons
    buttons = []
    for res, f in sorted_formats:
        buttons.append([f"{res}p"])

    # Save info and formats for callback query (can use a dict, but here simple cache)
    # Store formats in message reply_markup for callback usage
    # We'll keep formats info in-memory keyed by message id
    app.formats_cache = getattr(app, "formats_cache", {})
    app.formats_cache[message.message_id] = sorted_formats

    # Send message with quality options
    keyboard = [[
        {
            "text": f"{res}p",
            "callback_data": f"download_{message.message_id}_{res}"
        }
    ] for res, _ in sorted_formats]

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

    # Get formats stored
    formats = app.formats_cache.get(int(msg_id))
    if not formats:
        return await callback_query.answer("❌ Session expired, please send the URL again.", show_alert=True)

    # Find chosen format
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

    # Inform user about download start
    await callback_query.answer(f"⏳ Downloading {res}p...", show_alert=False)

    # Show upload animation
    await client.send_chat_action(callback_query.message.chat.id, "upload_video")

    # Download video with chosen format
    ydl_opts = {
        'format': f"{chosen_format['format_id']}",
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'quiet': True,
        'cookiefile': cookies_path,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            file_path = ydl.prepare_filename(info)
    except Exception as e:
        return await callback_query.message.edit(f"❌ Download failed: {str(e)}")

    # Send video
    try:
        await callback_query.message.edit("📤 Uploading video...")
        await client.send_video(callback_query.message.chat.id, file_path, caption=info.get("title", "🎬 Your video"))
        os.remove(file_path)
        await callback_query.message.delete_reply_markup()
    except Exception as e:
        await callback_query.message.edit(f"❌ Upload failed: {str(e)}")

app.run()