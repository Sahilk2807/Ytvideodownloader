from pyrogram import Client, filters
import yt_dlp
import os

API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

app = Client("youtube_downloader_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(filters.command("start"))
async def start_handler(client, message):
    await message.reply_text("👋 Hello! Send me a YouTube video URL to download it under 50MB!")

@app.on_message(filters.text & ~filters.command(["start"]))
async def download_video(client, message):
    url = message.text.strip()
    if not url.startswith("http"):
        return await message.reply_text("⚠️ Please send a valid YouTube URL!")

    sent_msg = await message.reply("⏳ Downloading, please wait...")

    try:
        ydl_opts = {
            'format': 'best[filesize<50M]/best',
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'quiet': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)

        await sent_msg.edit("📤 Uploading to Telegram...")
        await message.reply_video(video=file_path, caption=info.get("title", "🎬 Your video"))
        os.remove(file_path)

    except Exception as e:
        await sent_msg.edit(f"❌ Error: {str(e)}")

app.run()