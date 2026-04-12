"""
diarizer.py — Diarisation des speakers via pyannote.audio.

Associe chaque segment Whisper au speaker dominant (celui qui
parle le plus longtemps sur la durée du segment).

Retourne une liste de labels speaker_0, speaker_1, etc.
dans le même ordre que les segments Whisper passés en entrée.
"""
import subprocess
from pathlib import Path

from config import FFMPEG_PATH, HUGGINGFACE_TOKEN
from transcriber import Segment

MODEL_ID = "pyannote/speaker-diarization-3.1"


class DiarizationError(Exception):
    pass


def _extract_wav(video_path: Path, dest: Path) -> Path:
    """Extrait l'audio en WAV mono 16kHz (format optimal pour pyannote)."""
    wav_path = dest / "diarization_audio.wav"
    result = subprocess.run(
        [
            FFMPEG_PATH, "-y",
            "-i", str(video_path),
            "-vn", "-ar", "16000", "-ac", "1",
            "-f", "wav", str(wav_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise DiarizationError(f"Extraction audio échouée : {result.stderr}")
    return wav_path


def _overlap(seg_start: float, seg_end: float, turn_start: float, turn_end: float) -> float:
    """Durée de chevauchement entre deux intervalles."""
    return max(0.0, min(seg_end, turn_end) - max(seg_start, turn_start))


def diarize(video_path: Path | str, segments: list[Segment], work_dir: Path) -> list[str]:
    """
    Associe chaque segment Whisper à un speaker.

    Args:
        video_path: Chemin de la vidéo source.
        segments:   Liste de Segment Whisper (start, end, text).
        work_dir:   Dossier de travail pour les fichiers temporaires.

    Returns:
        Liste de labels (ex. ["speaker_0", "speaker_1", "speaker_0", ...])
        dans le même ordre que `segments`.

    Raises:
        DiarizationError: si la diarisation échoue.
    """
    if not HUGGINGFACE_TOKEN:
        raise DiarizationError("HUGGINGFACE_TOKEN manquant dans .env")

    video_path = Path(video_path)
    work_dir.mkdir(parents=True, exist_ok=True)

    wav_path = _extract_wav(video_path, work_dir)

    try:
        from pyannote.audio import Pipeline
        pipeline = Pipeline.from_pretrained(MODEL_ID, token=HUGGINGFACE_TOKEN)
    except Exception as e:
        raise DiarizationError(f"Chargement du modèle pyannote échoué : {e}") from e

    try:
        diarization = pipeline(str(wav_path))
    except Exception as e:
        raise DiarizationError(f"Diarisation échouée : {e}") from e

    # pyannote v4+ retourne un DiarizeOutput (dataclass), pas une Annotation directe.
    # On utilise exclusive_speaker_diarization : pas de chevauchements, plus propre.
    annotation = (
        diarization.exclusive_speaker_diarization
        if hasattr(diarization, "exclusive_speaker_diarization")
        else diarization  # fallback si version antérieure retourne une Annotation
    )

    # Construire la liste des turns : [(start, end, speaker), ...]
    turns: list[tuple[float, float, str]] = [
        (turn.start, turn.end, speaker)
        for turn, _, speaker in annotation.itertracks(yield_label=True)
    ]

    # Normaliser les labels : SPEAKER_00 → speaker_0, etc.
    raw_labels = sorted({t[2] for t in turns})
    label_map = {raw: f"speaker_{i}" for i, raw in enumerate(raw_labels)}
    turns = [(s, e, label_map[sp]) for s, e, sp in turns]

    # Pour chaque segment Whisper, trouver le speaker dominant (max overlap)
    speaker_labels: list[str] = []
    for seg in segments:
        overlap_by_speaker: dict[str, float] = {}
        for t_start, t_end, speaker in turns:
            ov = _overlap(seg.start, seg.end, t_start, t_end)
            if ov > 0:
                overlap_by_speaker[speaker] = overlap_by_speaker.get(speaker, 0.0) + ov

        if overlap_by_speaker:
            dominant = max(overlap_by_speaker, key=lambda s: overlap_by_speaker[s])
        else:
            dominant = "speaker_0"  # fallback si aucun turn ne couvre le segment

        speaker_labels.append(dominant)

    return speaker_labels


if __name__ == "__main__":
    import sys
    from transcriber import transcribe

    if len(sys.argv) != 2:
        print("Usage: python diarizer.py <chemin_vidéo>")
        sys.exit(1)

    video = Path(sys.argv[1])
    work = Path("temp") / "diarizer_test"

    try:
        result = transcribe(video)
        labels = diarize(video, result.segments, work)
        for seg, label in zip(result.segments, labels):
            print(f"[{seg.start:.1f}s - {seg.end:.1f}s] {label}: {seg.text}")
    except DiarizationError as e:
        print(f"Erreur : {e}")
        sys.exit(1)
