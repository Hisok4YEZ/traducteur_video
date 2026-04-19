#!/usr/bin/env bash
# deploy.sh — Installation et déploiement de tiktok-translator sur Ubuntu 22.04
# Usage : bash deploy.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="tiktok-translator"
PYTHON_BIN="/usr/bin/python3"
VENV_DIR="$PROJECT_DIR/.venv"
BOT_USER="${SUDO_USER:-$(whoami)}"

echo "=== tiktok-translator deploy ==="
echo "Répertoire  : $PROJECT_DIR"
echo "Utilisateur : $BOT_USER"
echo ""

# ── 1. Dépendances système ────────────────────────────────────────────────────
echo "[1/4] Installation des paquets système…"
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv ffmpeg

echo "      Python  : $(python3 --version)"
echo "      ffmpeg  : $(ffmpeg -version 2>&1 | head -1)"

# ── 2. Environnement Python ───────────────────────────────────────────────────
echo "[2/4] Création du venv et installation des dépendances Python…"
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt" --quiet
echo "      Dépendances installées."

# ── 3. Vérification du .env ───────────────────────────────────────────────────
echo "[3/4] Vérification du fichier .env…"
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo ""
    echo "  ATTENTION : $PROJECT_DIR/.env introuvable."
    echo "  Crée-le à partir de .env.example :"
    echo "    cp $PROJECT_DIR/.env.example $PROJECT_DIR/.env"
    echo "    nano $PROJECT_DIR/.env"
    echo ""
fi

# ── 4. Service systemd ────────────────────────────────────────────────────────
echo "[4/4] Configuration du service systemd ($SERVICE_NAME)…"

cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=TikTok Translator Bot
After=network.target

[Service]
Type=simple
User=$BOT_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$VENV_DIR/bin/python $PROJECT_DIR/bot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo ""
echo "=== Déploiement terminé ==="
echo ""
echo "Commandes utiles :"
echo "  sudo systemctl start   $SERVICE_NAME   # démarrer"
echo "  sudo systemctl stop    $SERVICE_NAME   # arrêter"
echo "  sudo systemctl restart $SERVICE_NAME   # redémarrer"
echo "  sudo journalctl -u     $SERVICE_NAME -f  # logs en direct"
echo ""
echo "Lance le bot avec : sudo systemctl start $SERVICE_NAME"
