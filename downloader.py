"""
downloader.py — Téléchargement des vidéos via yt-dlp.
Retourne le chemin du fichier vidéo téléchargé.
"""
from pathlib import Path

import yt_dlp

from config import VIDEOS_DIR


class DownloadError(Exception):
    pass


def download_video(url: str) -> Path:
    """
    Télécharge une vidéo TikTok depuis l'URL donnée.

    Args:
        url: URL de la vidéo TikTok.

    Returns:
        Chemin (Path) du fichier vidéo téléchargé.

    Raises:
        DownloadError: si le téléchargement échoue.
    """
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

    # yt-dlp écrit le chemin final dans ce conteneur via le hook
    result: dict = {}

    def _on_progress(d: dict) -> None:
        if d["status"] == "finished":
            result["path"] = d["filename"]

    ydl_opts = {
        "outtmpl": str(VIDEOS_DIR / "%(id)s.%(ext)s"),
        "format": "mp4/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [_on_progress],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as e:
        raise DownloadError(f"Échec du téléchargement : {e}") from e

    # Reconstruire le chemin depuis les métadonnées si le hook n'a pas répondu
    if "path" not in result:
        video_id = info.get("id", "")
        ext = info.get("ext", "mp4")
        result["path"] = str(VIDEOS_DIR / f"{video_id}.{ext}")

    path = Path(result["path"])
    if not path.exists():
        raise DownloadError(f"Fichier introuvable après téléchargement : {path}")

    return path


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python downloader.py <url>")
        sys.exit(1)

    url = sys.argv[1]
    try:
        output = download_video(url)
        print(f"Téléchargé : {output}")
    except DownloadError as e:
        print(f"Erreur : {e}")
        sys.exit(1)
