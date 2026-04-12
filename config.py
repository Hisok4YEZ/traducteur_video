"""
Configuration centralisée du projet.
Lit le fichier .env et expose les variables.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Charger le .env depuis le répertoire du projet, quel que soit le cwd
load_dotenv(Path(__file__).parent / ".env")

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# ElevenLabs
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")

# HuggingFace (pyannote diarization)
HUGGINGFACE_TOKEN = os.getenv("HUGGINGFACE_TOKEN")

# Chemins
VIDEOS_DIR = Path(os.getenv("VIDEOS_DIR", "./videos"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./output"))

# Créer les répertoires s'ils n'existent pas
VIDEOS_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# Langues
SOURCE_LANGUAGE = os.getenv("SOURCE_LANGUAGE", "en")
TARGET_LANGUAGE = os.getenv("TARGET_LANGUAGE", "fr")

# ffmpeg
FFMPEG_PATH = os.getenv("FFMPEG_PATH", "ffmpeg")


def validate_config():
    """Vérifier que les variables essentielles sont présentes."""
    required = [
        "TELEGRAM_BOT_TOKEN",
        "OPENAI_API_KEY",
        "ELEVENLABS_API_KEY",
        "ELEVENLABS_VOICE_ID",
    ]
    missing = [var for var in required if not os.getenv(var)]
    if missing:
        raise ValueError(f"Variables manquantes dans .env: {', '.join(missing)}")
