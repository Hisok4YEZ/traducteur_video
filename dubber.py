"""
dubber.py — Génération audio par segment via ElevenLabs TTS.

Si des labels de speakers sont fournis (diarisation) :
  - Extrait un sample audio de 30s max par speaker depuis la vidéo
  - Clone une voix ElevenLabs par speaker via Instant Voice Cloning (IVC)
  - Génère chaque segment avec la voix du bon speaker
  - Supprime les voix clonées après le job

Sans diarisation : utilise ELEVENLABS_VOICE_ID depuis config.py.

Après génération, chaque audio est ajusté (atempo / atrim) pour
tenir dans sa durée cible.
"""
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from elevenlabs.client import ElevenLabs

from config import ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, FFMPEG_PATH
from transcriber import Segment

TEMP_DIR = Path("temp")
MAX_ATEMPO = 1.5
SAMPLE_DURATION = 30  # secondes de sample pour le clonage


class DubbingError(Exception):
    pass


@dataclass
class DubbedSegment:
    start: float
    end: float
    text: str
    audio_path: Path


# ── Helpers durée ─────────────────────────────────────────────────────────────

def _get_duration(audio_path: Path) -> float:
    """Retourne la durée en secondes d'un fichier audio via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise DubbingError(f"ffprobe échoué sur {audio_path} : {result.stderr}")

    data = json.loads(result.stdout)
    for stream in data.get("streams", []):
        if "duration" in stream:
            return float(stream["duration"])

    raise DubbingError(f"Durée introuvable dans ffprobe pour {audio_path}")


def _fit_audio(audio_path: Path, target_duration: float) -> Path:
    """
    Ajuste l'audio pour tenir dans target_duration secondes.
    atempo jusqu'à MAX_ATEMPO, puis atrim si insuffisant.
    """
    actual = _get_duration(audio_path)
    if actual <= target_duration:
        return audio_path

    ratio = actual / target_duration
    atempo = min(ratio, MAX_ATEMPO)
    truncate = ratio > MAX_ATEMPO

    fitted_path = audio_path.with_suffix(".fitted.mp3")
    filters: list[str] = [f"atempo={atempo:.4f}"]
    if truncate:
        filters.append(f"atrim=0:{target_duration:.4f}")

    result = subprocess.run(
        [
            FFMPEG_PATH, "-y",
            "-i", str(audio_path),
            "-af", ",".join(filters),
            "-c:a", "libmp3lame", "-b:a", "128k",
            str(fitted_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise DubbingError(f"ffmpeg atempo échoué sur {audio_path} : {result.stderr}")

    fitted_path.replace(audio_path)
    return audio_path


# ── Clonage de voix ───────────────────────────────────────────────────────────

def _extract_speaker_sample(
    video_path: Path,
    segments: list[Segment],
    speaker_labels: list[str],
    speaker: str,
    dest: Path,
) -> Path:
    """
    Extrait et concatène jusqu'à SAMPLE_DURATION secondes de parole
    du speaker depuis la vidéo originale.
    Retourne le chemin du fichier WAV produit.
    """
    # Collecte les segments du speaker, du plus long au plus court
    speaker_segs = [
        seg for seg, label in zip(segments, speaker_labels)
        if label == speaker
    ]
    speaker_segs.sort(key=lambda s: s.end - s.start, reverse=True)

    sample_path = dest / f"{speaker}_sample.wav"
    concat_list = dest / f"{speaker}_concat.txt"

    clips: list[Path] = []
    total = 0.0

    for i, seg in enumerate(speaker_segs):
        if total >= SAMPLE_DURATION:
            break
        duration = min(seg.end - seg.start, SAMPLE_DURATION - total)
        clip_path = dest / f"{speaker}_clip_{i}.wav"

        result = subprocess.run(
            [
                FFMPEG_PATH, "-y",
                "-i", str(video_path),
                "-ss", f"{seg.start:.3f}",
                "-t", f"{duration:.3f}",
                "-vn", "-ar", "44100", "-ac", "1",
                str(clip_path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            clips.append(clip_path)
            total += duration

    if not clips:
        raise DubbingError(f"Aucun clip extrait pour {speaker}")

    if len(clips) == 1:
        clips[0].rename(sample_path)
    else:
        # Concaténation via ffmpeg concat
        with concat_list.open("w") as f:
            for clip in clips:
                f.write(f"file '{clip.resolve()}'\n")
        result = subprocess.run(
            [
                FFMPEG_PATH, "-y",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_list),
                "-c", "copy",
                str(sample_path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise DubbingError(f"Concat sample {speaker} échoué : {result.stderr}")

    return sample_path


def _clone_voices(
    client: ElevenLabs,
    video_path: Path,
    segments: list[Segment],
    speaker_labels: list[str],
    job_dir: Path,
) -> dict[str, str]:
    """
    Clone une voix ElevenLabs par speaker.

    Returns:
        Dict speaker_label → voice_id cloné.
    """
    speakers = sorted(set(speaker_labels))
    samples_dir = job_dir / "samples"
    samples_dir.mkdir(exist_ok=True)

    voice_map: dict[str, str] = {}

    for speaker in speakers:
        print(f"     → Clonage voix {speaker}…")
        sample_path = _extract_speaker_sample(
            video_path, segments, speaker_labels, speaker, samples_dir
        )
        try:
            with sample_path.open("rb") as f:
                voice = client.voices.ivc.create(
                    name=f"{speaker}_{job_dir.name}",
                    files=[f],
                )
            voice_map[speaker] = voice.voice_id
        except Exception as e:
            raise DubbingError(f"IVC échoué pour {speaker} : {e}") from e

    return voice_map


def _delete_cloned_voices(client: ElevenLabs, voice_map: dict[str, str]) -> None:
    """Supprime les voix clonées après le job pour ne pas saturer le compte."""
    for speaker, voice_id in voice_map.items():
        try:
            client.voices.delete(voice_id)
        except Exception:
            pass  # non-fatal


# ── Interface publique ────────────────────────────────────────────────────────

def dub(
    segments: list[Segment],
    job_id: str = "output",
    speaker_labels: list[str] | None = None,
    video_path: Path | str | None = None,
) -> list[DubbedSegment]:
    """
    Génère un fichier audio pour chaque segment via ElevenLabs TTS.

    Args:
        segments:        Liste de Segment traduits (start, end, text).
        job_id:          Identifiant du job.
        speaker_labels:  Liste de labels speaker par segment (optionnel).
                         Si fourni, clone une voix par speaker (IVC).
        video_path:      Vidéo source pour extraire les samples (requis si speaker_labels).

    Returns:
        Liste de DubbedSegment avec le chemin audio ajusté de chaque segment.

    Raises:
        DubbingError: si la génération ou l'ajustement d'un segment échoue.
    """
    if not segments:
        return []

    use_diarization = bool(speaker_labels and video_path)

    if use_diarization and len(speaker_labels) != len(segments):
        raise DubbingError(
            f"Nombre de speaker_labels ({len(speaker_labels)}) != "
            f"nombre de segments ({len(segments)})."
        )

    job_dir = TEMP_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    try:
        client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
    except Exception as e:
        raise DubbingError(f"Impossible d'initialiser le client ElevenLabs : {e}") from e

    # Clonage de voix si diarisation disponible
    voice_map: dict[str, str] = {}
    if use_diarization:
        voice_map = _clone_voices(client, Path(video_path), segments, speaker_labels, job_dir)

    dubbed: list[DubbedSegment] = []

    try:
        for i, seg in enumerate(segments):
            audio_path = job_dir / f"segment_{i:03d}.mp3"
            target_duration = seg.end - seg.start

            voice_id = (
                voice_map.get(speaker_labels[i], ELEVENLABS_VOICE_ID)
                if use_diarization
                else ELEVENLABS_VOICE_ID
            )

            try:
                audio_bytes = b"".join(
                    client.text_to_speech.convert(
                        voice_id=voice_id,
                        text=seg.text,
                        model_id="eleven_multilingual_v2",
                        output_format="mp3_44100_128",
                    )
                )
            except Exception as e:
                raise DubbingError(
                    f"Erreur ElevenLabs sur le segment {i} "
                    f"({seg.start:.2f}s - {seg.end:.2f}s) : {e}"
                ) from e

            audio_path.write_bytes(audio_bytes)

            try:
                audio_path = _fit_audio(audio_path, target_duration)
            except DubbingError as e:
                print(f"     ⚠ Ajustement segment {i} ignoré : {e}")

            dubbed.append(DubbedSegment(
                start=seg.start,
                end=seg.end,
                text=seg.text,
                audio_path=audio_path,
            ))

    finally:
        # Toujours nettoyer les voix clonées, même en cas d'erreur partielle
        if voice_map:
            _delete_cloned_voices(client, voice_map)

    return dubbed


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python dubber.py '<texte1>' ['<texte2>' ...]")
        sys.exit(1)

    test_segments = [
        Segment(start=i * 3.0, end=(i + 1) * 3.0, text=arg)
        for i, arg in enumerate(sys.argv[1:])
    ]

    try:
        results = dub(test_segments, job_id="test")
        for ds in results:
            print(f"[{ds.start:.2f}s - {ds.end:.2f}s] {ds.text} → {ds.audio_path}")
    except DubbingError as e:
        print(f"Erreur : {e}")
        sys.exit(1)
