"""
bot.py — Bot Telegram : interface utilisateur du pipeline tiktok-translator.

Usage :
  .venv/bin/python bot.py

Commandes :
  /start  — message de bienvenue
  <url>   — lance le pipeline sur l'URL TikTok reçue
"""
import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from config import TELEGRAM_BOT_TOKEN
from pipeline import PipelineError, run

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TIKTOK_URL_RE = re.compile(r"https?://(www\.|vm\.|vt\.)?tiktok\.com/\S+")

# Executor dédié pour exécuter le pipeline (bloquant) sans bloquer la boucle asyncio
_executor = ThreadPoolExecutor(max_workers=2)


# ── Handlers ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Envoie-moi une URL TikTok et je te renvoie la vidéo doublée en espagnol latino."
    )


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    url = message.text.strip()

    if not TIKTOK_URL_RE.search(url):
        await message.reply_text("❌ URL non reconnue. Envoie un lien TikTok valide.")
        return

    status_msg = await message.reply_text("⏳ Traitement en cours…")

    loop = asyncio.get_event_loop()
    try:
        output_path = await loop.run_in_executor(
            _executor,
            lambda: run(url),
        )
    except PipelineError as e:
        logger.error("Pipeline échoué (%s) : %s", e.step, e.cause)
        await status_msg.edit_text(
            f"❌ Erreur à l'étape *{e.step}* :\n`{e.cause}`",
            parse_mode="Markdown",
        )
        return
    except Exception as e:
        logger.exception("Erreur inattendue")
        await status_msg.edit_text(f"❌ Erreur inattendue : {e}")
        return

    await status_msg.edit_text("✅ Terminé ! Envoi de la vidéo…")

    try:
        with output_path.open("rb") as video_file:
            await message.reply_video(
                video=video_file,
                caption="🎬 Vidéo doublée en espagnol latino",
            )
        await status_msg.delete()
    except Exception as e:
        logger.error("Échec envoi vidéo : %s", e)
        await status_msg.edit_text(
            f"✅ Pipeline OK mais échec d'envoi : {e}\n\nFichier : `{output_path}`",
            parse_mode="Markdown",
        )


# ── Entrypoint ────────────────────────────────────────────────────────────────

def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN manquant dans .env")

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))

    logger.info("Bot démarré. En attente de messages…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
