"""
pipeline.py — Orchestration complète du workflow tiktok-translator.

Étapes :
  1. Download  — yt-dlp télécharge la vidéo
  2. Transcribe — Whisper extrait les segments horodatés
  3. Diarize   — pyannote assigne un speaker par segment (optionnel)
  4. Translate  — GPT-4o traduit en espagnol latino
  5. Dub        — ElevenLabs génère un mp3 par segment (voix clonée par speaker si diarisation)
  6. Merge      — ffmpeg assemble la vidéo finale
  7. Cleanup    — suppression des fichiers temp/
"""
import shutil
import time
import uuid
from pathlib import Path

from config import HUGGINGFACE_TOKEN, validate_config
from diarizer import DiarizationError, diarize
from downloader import DownloadError, download_video
from dubber import DubbingError, dub
from merger import MergeError, merge
from transcriber import TranscriptionError, transcribe
from translator import TranslationError, translate


class PipelineError(Exception):
    """Erreur levée avec le nom de l'étape qui a échoué."""
    def __init__(self, step: str, cause: Exception):
        self.step = step
        self.cause = cause
        super().__init__(f"[{step}] {cause}")


def _step(label: str) -> None:
    print(f"\n{'─' * 50}")
    print(f"  {label}")
    print(f"{'─' * 50}")


def run(url: str, job_id: str | None = None) -> Path:
    """
    Lance le pipeline complet pour une URL TikTok.

    Args:
        url:    URL de la vidéo TikTok.
        job_id: Identifiant unique du job (généré automatiquement si absent).

    Returns:
        Chemin de la vidéo finale dans output/.

    Raises:
        PipelineError: si une étape échoue, avec le nom de l'étape et la cause.
    """
    validate_config()

    job_id = job_id or uuid.uuid4().hex[:8]
    t_start = time.time()

    print(f"\nJob : {job_id}")
    print(f"URL : {url}")

    # ── 1. Download ──────────────────────────────────────────────────────────
    _step("1/5  Téléchargement de la vidéo…")
    try:
        video_path = download_video(url)
    except DownloadError as e:
        raise PipelineError("download", e) from e
    print(f"     ✓ {video_path}")

    # ── 2. Transcribe ────────────────────────────────────────────────────────
    _step("2/6  Transcription (Whisper)…")
    try:
        transcription = transcribe(video_path)
    except TranscriptionError as e:
        raise PipelineError("transcribe", e) from e
    print(f"     ✓ {len(transcription.segments)} segments détectés")

    # ── 3. Diarize (optionnel — si HUGGINGFACE_TOKEN présent) ────────────────
    speaker_labels: list[str] | None = None
    if HUGGINGFACE_TOKEN:
        _step("3/6  Diarisation des speakers (pyannote)…")
        try:
            work_dir = Path("temp") / job_id / "diarization"
            speaker_labels = diarize(video_path, transcription.segments, work_dir)
            speakers = sorted(set(speaker_labels))
            print(f"     ✓ {len(speakers)} speaker(s) détecté(s) : {', '.join(speakers)}")
        except DiarizationError as e:
            print(f"     ⚠ Diarisation ignorée : {e}")
            speaker_labels = None
    else:
        print("\n  3/6  Diarisation ignorée (HUGGINGFACE_TOKEN absent)")

    # ── 4. Translate ─────────────────────────────────────────────────────────
    _step("4/6  Traduction GPT-4o (→ espagnol latino)…")
    try:
        translated_segments = translate(transcription.segments)
    except TranslationError as e:
        raise PipelineError("translate", e) from e
    print(f"     ✓ {len(translated_segments)} segments traduits")
    for seg in translated_segments:
        print(f"       [{seg.start:.1f}s - {seg.end:.1f}s] {seg.text}")

    # ── 5. Dub ───────────────────────────────────────────────────────────────
    _step("5/6  Génération voix ElevenLabs…")
    try:
        dubbed_segments = dub(
            translated_segments,
            job_id=job_id,
            speaker_labels=speaker_labels,
            video_path=video_path,
        )
    except DubbingError as e:
        raise PipelineError("dub", e) from e
    print(f"     ✓ {len(dubbed_segments)} fichiers audio générés")

    # ── 6. Merge ─────────────────────────────────────────────────────────────
    _step("6/6  Fusion vidéo + audio (ffmpeg)…")
    try:
        output_path = merge(video_path, dubbed_segments, job_id=job_id)
    except MergeError as e:
        raise PipelineError("merge", e) from e
    print(f"     ✓ {output_path}")

    # ── Cleanup ──────────────────────────────────────────────────────────────
    temp_job_dir = Path("temp") / job_id
    if temp_job_dir.exists():
        shutil.rmtree(temp_job_dir)
        print(f"\n     Temp nettoyé : {temp_job_dir}")

    elapsed = time.time() - t_start
    print(f"\n{'═' * 50}")
    print(f"  Pipeline terminé en {elapsed:.1f}s")
    print(f"  Sortie : {output_path}")
    print(f"{'═' * 50}\n")

    return output_path


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python pipeline.py <url_tiktok>")
        sys.exit(1)

    try:
        run(sys.argv[1])
    except PipelineError as e:
        print(f"\nErreur à l'étape '{e.step}' : {e.cause}")
        sys.exit(1)
