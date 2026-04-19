# TikTok Translator - Contexte du Projet

## Description
Pipeline Python pour télécharger, transcrire, traduire et doubler automatiquement des vidéos TikTok.

## Stack Technique
- **yt-dlp** : Téléchargement des vidéos
- **Whisper API** : Transcription audio
- **pyannote.audio** : Diarisation des speakers
- **GPT-4o** : Traduction du texte
- **ElevenLabs** : Génération de voix + Instant Voice Cloning par speaker
- **ffmpeg** : Traitement audio/vidéo
- **Telegram Bot** : Interface de contrôle + notifications

## Structure des Fichiers
```
tiktok-translator/
├── .env                   # Variables d'environnement (secrets)
├── .env.example          # Template .env
├── config.py             # Configuration centralisée
├── bot.py                # Bot Telegram (entrypoint)
├── downloader.py         # Téléchargement vidéos (yt-dlp)
├── transcriber.py        # Transcription (Whisper)
├── translator.py         # Traduction (GPT-4o)
├── dubber.py            # Génération voix (ElevenLabs)
├── merger.py            # Fusion vidéo + audio (ffmpeg)
└── pipeline.py          # Orchestration du workflow
```

## État du Projet

### ✅ Fait
- [x] Structure des dossiers
- [x] contexte.md
- [x] .env.example
- [x] config.py (lecture du .env)
- [x] downloader.py (yt-dlp) — `download_video(url) -> Path`
- [x] transcriber.py (Whisper) — `transcribe(file_path, language?) -> TranscriptionResult` (text + segments horodatés)
- [x] translator.py (GPT-4o) — `translate(segments) -> list[Segment]` (1 appel API, espagnol latino)
- [x] dubber.py (ElevenLabs) — `dub(segments, job_id, speaker_labels?, video_path?) -> list[DubbedSegment]` (IVC par speaker si diarisation, sinon voix unique)
- [x] merger.py (audio-separator + ffmpeg) — `merge(video, dubbed_segments, job_id) -> Path` (UVR-MDX-NET-Inst_HQ_3 sépare vocals/Instrumental → Instrumental 80% + segments adelay → output/)
- [x] diarizer.py (pyannote) — `diarize(video, segments, work_dir) -> list[str]` (speaker dominant par segment)
- [x] pipeline.py — `run(url, job_id?) -> Path` (6 étapes, diarisation optionnelle si HUGGINGFACE_TOKEN présent)

- [x] bot.py (Telegram) — `main()` polling, `handle_url` lance `pipeline.run()` via `ThreadPoolExecutor` pour ne pas bloquer asyncio

- [x] requirements.txt (sans pyannote — trop lourd pour 1GB RAM)
- [x] deploy.sh (Ubuntu 22.04 : apt, venv, systemd)
- [x] .env.example (sans HUGGINGFACE_TOKEN)

### 📋 À Faire
- [ ] Tests & validation

## Déploiement (Oracle Cloud Free Tier — Ubuntu 22.04)
- `bash deploy.sh` (en root) : installe python3/ffmpeg, crée le venv, configure systemd
- Service : `tiktok-translator.service` — redémarre automatiquement au reboot
- Logs : `sudo journalctl -u tiktok-translator -f`
- La diarisation pyannote est désactivée en production (HUGGINGFACE_TOKEN absent) — trop lourde pour 1GB RAM

## Environnement
- Python venv : `.venv/`
- Dépendances prod : `yt-dlp`, `python-dotenv`, `openai`, `elevenlabs`, `audio-separator`, `onnxruntime`, `python-telegram-bot`
- Dépendances hors prod : `pyannote.audio` (diarisation, optionnelle, lourde)
- Dépendances abandonnées : `demucs` (torchcodec incompatible Python 3.14), `spleeter` (numpy incompatible Python 3.14)

## Structure des Fichiers (mise à jour)
```
tiktok-translator/
├── diarizer.py           # Diarisation speakers (pyannote)
├── dubber.py             # Génération voix (ElevenLabs + IVC)
...
```

## Choix Techniques Importants
1. **yt-dlp au lieu de youtube-dl** : Maintenance active, plus fiable
2. **Whisper API** : Qualité de transcription, support multilingue
3. **GPT-4o** : Meilleure compréhension contextuelle pour les traductions. Tous les segments envoyés en 1 seul appel (JSON avec start/end/duration/text) pour minimiser les coûts. `temperature=0.3`. La durée est passée dans le prompt pour que GPT adapte la longueur de la traduction.
4. **ElevenLabs** : `eleven_multilingual_v2` + `mp3_44100_128`. `_fit_audio` via ffprobe/atempo (max 1.5×) + atrim. Avec diarisation : IVC via `client.voices.ivc.create(name, files)` — 1 voix clonée par speaker depuis un sample de 30s max. Voix supprimées après job via `client.voices.delete()`.
4b. **pyannote.audio** : `pyannote/speaker-diarization-3.1`. WAV mono 16kHz. Speaker dominant par segment = max overlap. `token=` (pas `use_auth_token=`, obsolète). v4+ retourne un `DiarizeOutput` (dataclass) — `itertracks` est sur `.exclusive_speaker_diarization` (Annotation sans chevauchements). Fallback sur l'objet direct pour versions antérieures. Diarisation optionnelle : si `HUGGINGFACE_TOKEN` absent, pipeline continue sans IVC.
5. **Telegram Bot** : `python-telegram-bot` v22. Pipeline bloquant exécuté dans un `ThreadPoolExecutor(max_workers=2)` via `loop.run_in_executor` pour ne pas bloquer la boucle asyncio. Le bot peut traiter 2 vidéos en parallèle.
6. **audio-separator** : API Python directe (`Separator` + `load_model` + `separate`), pas de subprocess. Modèle `UVR-MDX-NET-Inst_HQ_3.onnx` (ONNX). Requiert aussi `onnxruntime`. Modèle téléchargé automatiquement au 1er lancement (~200 Mo). `separate()` retourne des noms de fichiers sans chemin → résoudre avec `sep_dir / Path(f).name`. Demucs et spleeter abandonnés (incompatibles Python 3.14).
7. **ffmpeg** : `adelay` pour positionner chaque segment mp3 au bon timestamp (en ms), suivi de `volume=1.5`. Délai de +200ms ajouté sur tous les segments sauf le premier (évite le chevauchement avec la fin du segment précédent). `amix` avec `normalize=0`. Vidéo copiée sans réencodage (`-c:v copy`), audio réencodé en AAC 192k.

## Notes
- Chaque module = responsabilité unique (Single Responsibility)
- pipeline.py orchestrera les appels aux modules
- bot.py exposera l'interface utilisateur
