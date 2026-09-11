import asyncio
import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID", "0"))
DOWNLOAD_DIR = Path(os.environ.get("DOWNLOAD_DIR", "/tmp/musicbot"))
SUB_LANGS = os.environ.get("SUB_LANGS", "es.*,en.*")
AUDIO_LIMIT_MB = 49

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DOWNLOAD_DIR / "downloads.db"

def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS downloads(
        video_id TEXT PRIMARY KEY,
        title TEXT,
        path TEXT,
        playlist TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    con.commit()
    return con

def allowed(update: Update):
    return bool(ALLOWED_USER_ID and update.effective_user and
                update.effective_user.id == ALLOWED_USER_ID)

def is_youtube_url(text):
    return bool(re.search(r"(youtube\.com|youtu\.be)", text or "", re.I))

def human_mb(path):
    return path.stat().st_size / 1024 / 1024

def find_outputs(folder):
    audio = [p for p in folder.rglob("*") if p.suffix.lower() in {".m4a", ".mp3", ".opus", ".webm"}]
    subs = [p for p in folder.rglob("*") if p.suffix.lower() in {".srt", ".vtt", ".ass", ".lrc"}]
    return audio, subs

def download_playlist(url, workdir, progress_cb):
    # Audio only: best audio stream. M4A is preferred when available.
    # Subtitles are saved separately and never cause a video download.
    opts = {
        "format": "m4a/bestaudio/best",
        "outtmpl": str(workdir / "%(playlist_index)03d - %(title)s.%(ext)s"),
        "noplaylist": False,
        "writethumbnail": True,
        "postprocessors": [
            {"key": "FFmpegThumbnailsConvertor", "format": "jpg"},
            {"key": "EmbedThumbnail"},
            {"key": "FFmpegMetadata"},
        ],
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": [x.strip() for x in SUB_LANGS.split(",") if x.strip()],
        "subtitlesformat": "srt/vtt/best",
        "postprocessor_args": ["-loglevel", "error"],
        "ignoreerrors": True,
        "continuedl": True,
        "retries": 5,
        "fragment_retries": 5,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [progress_cb],
        "restrictfilenames": False,
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return info

def save_archive(info, workdir):
    con = db()
    entries = info.get("entries") if isinstance(info, dict) else None
    if entries:
        for e in entries:
            if not e:
                continue
            vid = e.get("id")
            title = e.get("title", "")
            if vid:
                audio = next((p for p in workdir.glob(f"*{title}*")
                              if p.suffix.lower() in {".m4a",".mp3",".opus",".webm"}), None)
                con.execute(
                    "INSERT OR REPLACE INTO downloads(video_id,title,path,playlist) VALUES(?,?,?,?)",
                    (vid, title, str(audio) if audio else "", info.get("title",""))
                )
    con.commit()
    con.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    await update.message.reply_text(
        "🎵 MUSIC BOT\n\n"
        "Envíame una URL de una playlist de YouTube.\n"
        "Descargaré solo el audio, portada y subtítulos disponibles.\n\n"
        "/cancel — cancelar la tarea"
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    task = context.application.bot_data.get(f"task:{update.effective_user.id}")
    if task and not task.done():
        task.cancel()
        await update.message.reply_text("🛑 Cancelando...")
    else:
        await update.message.reply_text("No hay una descarga activa.")

async def process(update, context, url):
    status = await update.message.reply_text("🔎 Analizando playlist...")
    workdir = Path(tempfile.mkdtemp(prefix="music_", dir=DOWNLOAD_DIR))
    loop = asyncio.get_running_loop()
    last_update = [0.0]

    def hook(d):
        now = asyncio.get_event_loop().time()
        if now - last_update[0] < 2:
            return
        last_update[0] = now
        if d.get("status") == "downloading":
            pct = d.get("_percent_str", "?")
            name = d.get("info_dict", {}).get("title", "audio")
            asyncio.run_coroutine_threadsafe(
                status.edit_text(f"⬇️ {pct}\n🎵 {name[:70]}"), loop
            )

    try:
        info = await asyncio.to_thread(download_playlist, url, workdir, hook)
        save_archive(info, workdir)
        audio, subs = find_outputs(workdir)

        if not audio and not subs:
            await status.edit_text("❌ No se pudo obtener contenido de esa playlist.")
            shutil.rmtree(workdir, ignore_errors=True)
            return

        await status.edit_text(
            f"✅ Terminado\n🎵 Audio: {len(audio)}\n💬 Subtítulos: {len(subs)}"
        )

        # Send files individually. Telegram's official Bot API currently limits
        # bot uploads to 50 MB for these methods.
        for p in audio + subs:
            if human_mb(p) > AUDIO_LIMIT_MB:
                await update.message.reply_text(
                    f"⚠️ Omitido por tamaño (> {AUDIO_LIMIT_MB} MB): {p.name}"
                )
                continue
            try:
                if p.suffix.lower() in {".m4a", ".mp3"}:
                    await update.message.reply_audio(audio=p.open("rb"), title=p.stem)
                else:
                    await update.message.reply_document(document=p.open("rb"),
                                                        caption=p.name[:1000])
            except Exception as exc:
                await update.message.reply_text(f"⚠️ Error enviando {p.name}: {exc}")

        shutil.rmtree(workdir, ignore_errors=True)
    except asyncio.CancelledError:
        shutil.rmtree(workdir, ignore_errors=True)
        await status.edit_text("🛑 Descarga cancelada.")
    except Exception as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        await status.edit_text(f"❌ Error: {str(exc)[:1500]}")

async def playlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    text = (update.message.text or "").strip()
    if not is_youtube_url(text):
        await update.message.reply_text("Envíame una URL de YouTube.")
        return
    uid = update.effective_user.id
    old = context.application.bot_data.get(f"task:{uid}")
    if old and not old.done():
        await update.message.reply_text("Ya hay una descarga en curso. Usa /cancel.")
        return
    task = asyncio.create_task(process(update, context, text))
    context.application.bot_data[f"task:{uid}"] = task

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    await update.callback_query.answer()

def main():
    if not TOKEN:
        raise SystemExit("Falta BOT_TOKEN.")
    if not ALLOWED_USER_ID:
        raise SystemExit("Falta ALLOWED_USER_ID.")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, playlist))
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
