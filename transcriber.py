"""
transcriber.py — Transcription audio via l'API Whisper d'OpenAI.
Retourne le texte brut + une liste de segments horodatés.
"""
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI

from config import OPENAI_API_KEY, SOURCE_LANGUAGE

# Taille max acceptée par l'API Whisper (25 Mo)
MAX_FILE_SIZE = 25 * 1024 * 1024

SUPPORTED_EXTENSIONS = {".mp4", ".mp3", ".m4a", ".wav", ".webm", ".ogg", ".flac"}


class TranscriptionError(Exception):
    pass


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class TranscriptionResult:
    text: str
    segments: list[Segment]


def transcribe(file_path: Path | str, language: str | None = None) -> TranscriptionResult:
    """
    Transcrit l'audio d'un fichier vidéo ou audio via Whisper.

    Args:
        file_path: Chemin vers le fichier à transcrire.
        language:  Code langue ISO-639-1 (ex. "en", "fr").
                   Par défaut : SOURCE_LANGUAGE depuis config.py.

    Returns:
        TranscriptionResult avec .text (str) et .segments (list[Segment]).

    Raises:
        TranscriptionError: si la transcription échoue.
    """
    path = Path(file_path)

    if not path.exists():
        raise TranscriptionError(f"Fichier introuvable : {path}")

    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise TranscriptionError(
            f"Format non supporté : {path.suffix}. "
            f"Formats acceptés : {', '.join(SUPPORTED_EXTENSIONS)}"
        )

    if path.stat().st_size > MAX_FILE_SIZE:
        size_mb = path.stat().st_size / 1024 / 1024
        raise TranscriptionError(
            f"Fichier trop volumineux : {size_mb:.1f} Mo (max 25 Mo)."
        )

    lang = language or SOURCE_LANGUAGE

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        with path.open("rb") as audio_file:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language=lang,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )
    except Exception as e:
        raise TranscriptionError(f"Erreur Whisper API : {e}") from e

    text = (response.text or "").strip()
    if not text:
        raise TranscriptionError("Transcription vide reçue depuis Whisper.")

    segments = [
        Segment(start=s.start, end=s.end, text=s.text.strip())
        for s in (response.segments or [])
    ]

    return TranscriptionResult(text=text, segments=segments)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python transcriber.py <chemin_fichier> [langue]")
        sys.exit(1)

    file_arg = sys.argv[1]
    lang_arg = sys.argv[2] if len(sys.argv) >= 3 else None

    try:
        result = transcribe(file_arg, language=lang_arg)
        for seg in result.segments:
            print(f"[{seg.start:.2f}s - {seg.end:.2f}s] {seg.text}")
    except TranscriptionError as e:
        print(f"Erreur : {e}")
        sys.exit(1)
