"""
merger.py — Fusion vidéo + audio doublé via audio-separator + ffmpeg.

Stratégie :
  1. ffmpeg extrait l'audio brut de la vidéo (wav).
  2. audio-separator (UVR-MDX-NET-Inst_HQ_3) sépare vocals / Instrumental.
  3. Instrumental (musique/ambiance) conservé à 80%.
  4. Chaque segment ElevenLabs positionné via `adelay`.
  5. ffmpeg mixe Instrumental + segments, réencode en AAC.
  6. Vidéo copiée sans réencodage (-c:v copy).

Note : le modèle UVR-MDX-NET-Inst_HQ_3.onnx est téléchargé
automatiquement par audio-separator au premier lancement (~200 Mo).
"""
import subprocess
import sys
from pathlib import Path

from config import FFMPEG_PATH, OUTPUT_DIR
from dubber import DubbedSegment

BG_VOLUME = 0.80
SEPARATOR_MODEL = "UVR-MDX-NET-Inst_HQ_3.onnx"


class MergeError(Exception):
    pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(cmd: list[str], step: str) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise MergeError(
            f"{step} a échoué (code {result.returncode}) :\n{result.stderr}"
        )


def _extract_audio(video_path: Path, dest: Path) -> Path:
    """Extrait la piste audio de la vidéo en WAV 44100Hz stéréo."""
    wav_path = dest / "audio.wav"
    try:
        _run(
            [
                FFMPEG_PATH, "-y",
                "-i", str(video_path),
                "-vn", "-ar", "44100", "-ac", "2",
                "-f", "wav", str(wav_path),
            ],
            "Extraction audio (ffmpeg)",
        )
    except FileNotFoundError:
        raise MergeError(
            f"ffmpeg introuvable à '{FFMPEG_PATH}'. "
            "Installez ffmpeg ou corrigez FFMPEG_PATH dans .env."
        )
    return wav_path


def _separate(wav_path: Path, sep_dir: Path) -> Path:
    """
    Utilise l'API Python d'audio-separator pour isoler la piste instrumentale.
    Retourne le chemin du fichier contenant "Instrumental" (musique sans voix).

    Fichiers produits : audio_(Vocals)_<model>.wav
                        audio_(Instrumental)_<model>.wav
    """
    try:
        from audio_separator.separator import Separator
    except ImportError:
        raise MergeError(
            "audio-separator introuvable. Installez-le : pip install audio-separator onnxruntime"
        )

    try:
        sep = Separator(output_dir=str(sep_dir), output_format="WAV")
        sep.load_model(model_filename=SEPARATOR_MODEL)
        output_files: list[str] = sep.separate(str(wav_path))
    except Exception as e:
        raise MergeError(f"Séparation audio-separator échouée : {e}") from e

    # separate() retourne des noms de fichiers sans chemin — on les résout contre sep_dir
    instrumental = next(
        (sep_dir / Path(f).name for f in output_files if "Instrumental" in Path(f).name),
        None,
    )
    if instrumental is None:
        names = [Path(f).name for f in output_files]
        raise MergeError(
            f"Fichier Instrumental introuvable parmi les sorties : {names}"
        )

    if not instrumental.exists():
        raise MergeError(f"Fichier Instrumental résolu mais introuvable : {instrumental}")

    return instrumental


def _ffmpeg_mix(
    video_path: Path,
    instrumental_path: Path,
    dubbed_segments: list[DubbedSegment],
    output_path: Path,
) -> None:
    """
    Inputs :
      [0] vidéo originale (flux vidéo)
      [1] instrumental.wav (musique sans voix)
      [2..N+1] segments mp3 doublés

    filter_complex :
      [1:a] volume=0.80       → [bg]
      [2:a] adelay=START_MS   → [s0]
      …
      [bg][s0]…[sN] amix      → [aout]
    """
    n = len(dubbed_segments)

    cmd = [
        FFMPEG_PATH, "-y",
        "-i", str(video_path),
        "-i", str(instrumental_path),
    ]
    for ds in dubbed_segments:
        cmd += ["-i", str(ds.audio_path)]

    filters: list[str] = []
    filters.append(f"[1:a]volume={BG_VOLUME}[bg]")

    seg_labels: list[str] = []
    for i, ds in enumerate(dubbed_segments):
        offset = 0.0 if i == 0 else 0.2
        delay_ms = int((ds.start + offset) * 1000)
        label = f"s{i}"
        filters.append(f"[{i + 2}:a]adelay={delay_ms}|{delay_ms},volume=1.5[{label}]")
        seg_labels.append(f"[{label}]")

    all_inputs = "[bg]" + "".join(seg_labels)
    filters.append(
        f"{all_inputs}amix=inputs={n + 1}:duration=first:normalize=0[aout]"
    )

    cmd += [
        "-filter_complex", "; ".join(filters),
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_path),
    ]

    try:
        _run(cmd, "Fusion finale (ffmpeg)")
    except FileNotFoundError:
        raise MergeError(
            f"ffmpeg introuvable à '{FFMPEG_PATH}'. "
            "Installez ffmpeg ou corrigez FFMPEG_PATH dans .env."
        )


# ── Interface publique ────────────────────────────────────────────────────────

def merge(
    video_path: Path | str,
    dubbed_segments: list[DubbedSegment],
    job_id: str = "output",
) -> Path:
    """
    Fusionne la vidéo originale avec les segments audio doublés.
    Utilise audio-separator pour isoler la piste instrumentale.

    Args:
        video_path:      Chemin de la vidéo source.
        dubbed_segments: Liste de DubbedSegment (start, end, text, audio_path).
        job_id:          Identifiant du job (nom du fichier de sortie).

    Returns:
        Chemin de la vidéo finale dans output/.

    Raises:
        MergeError: si une étape échoue.
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise MergeError(f"Vidéo introuvable : {video_path}")

    for ds in dubbed_segments:
        if not ds.audio_path.exists():
            raise MergeError(f"Segment audio introuvable : {ds.audio_path}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{job_id}.mp4"

    sep_dir = Path("temp") / job_id / "separator"
    sep_dir.mkdir(parents=True, exist_ok=True)

    print("     → Extraction audio…")
    wav_path = _extract_audio(video_path, sep_dir)

    print(f"     → Séparation vocale ({SEPARATOR_MODEL})…")
    print("       (téléchargement du modèle au 1er lancement, ~200 Mo)")
    instrumental_path = _separate(wav_path, sep_dir)

    print("     → Mixage final (ffmpeg)…")
    _ffmpeg_mix(video_path, instrumental_path, dubbed_segments, output_path)

    if not output_path.exists():
        raise MergeError(f"Fichier de sortie introuvable après fusion : {output_path}")

    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python merger.py <vidéo> [seg0.mp3:start] [seg1.mp3:start] ...")
        print("  ex: python merger.py video.mp4 temp/test/segment_000.mp3:0 temp/test/segment_001.mp3:3.2")
        sys.exit(1)

    video_arg = Path(sys.argv[1])
    test_segments: list[DubbedSegment] = []
    for arg in sys.argv[2:]:
        parts = arg.split(":")
        audio = Path(parts[0])
        start = float(parts[1]) if len(parts) > 1 else 0.0
        test_segments.append(
            DubbedSegment(start=start, end=start + 3.0, text="", audio_path=audio)
        )

    try:
        out = merge(video_arg, test_segments, job_id="test_merge")
        print(f"Vidéo finale : {out}")
    except MergeError as e:
        print(f"Erreur : {e}")
        sys.exit(1)
