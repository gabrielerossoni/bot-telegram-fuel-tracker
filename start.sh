#!/bin/bash
set -e

REPO="https://github.com/gabrielerossoni/bot-telegram-fuel-tracker.git"
INSTALL_DIR="$HOME/botbenzina"

echo "============================"
echo "  BOT BENZINA - Setup"
echo "============================"

# --- 1. Docker ---
if ! command -v docker &> /dev/null; then
    echo "[1/4] Installazione Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
else
    echo "[1/4] Docker OK."
fi

# --- 2. Tailscale ---
if ! command -v tailscale &> /dev/null; then
    echo "[2/4] Installazione Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh
else
    echo "[2/4] Tailscale OK."
fi

# --- 3. Codice ---
if [ -d "$INSTALL_DIR" ]; then
    echo "[3/4] Aggiornamento codice..."
    cd "$INSTALL_DIR"
    git pull
else
    echo "[3/4] Clonazione repository..."
    git clone "$REPO" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# --- 4. .env ---
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "================================================"
    echo "  Compila il file .env:"
    echo "  nano $INSTALL_DIR/.env"
    echo ""
    echo "  Inserisci:"
    echo "  - BOT_TOKEN (da @BotFather)"
    echo "  - WEBAPP_URL (lo vedrai dopo il login Tailscale)"
    echo "================================================"
    read -p "Premi INVIO quando hai compilato .env..."
fi

# --- 5. Avvia Tailscale ---
if ! tailscale status &> /dev/null; then
    echo ""
    echo "================================================"
    echo "  Login Tailscale (apri il link che appare)"
    echo "================================================"
    sudo tailscale up --hostname=botbenzina
fi

# Ottieni URL
TAILSCALE_HOSTNAME=$(tailscale status --json | grep -oP '"Self":\s*\{[^}]*"HostName":\s*"([^"]+)"' | grep -oP '"HostName":\s*"\K[^"]+' || tailscale status | head -2 | tail -1 | awk '{print $2}')
TAILSCALE_URL="https://${TAILSCALE_HOSTNAME}"

echo ""
echo "================================================"
echo "  Il tuo URL fisso: $TAILSCALE_URL"
echo ""
echo "  Assicurati che nel .env ci sia:"
echo "  WEBAPP_URL=$TAILSCALE_URL"
echo "================================================"

# Aggiorna .env
sed -i "s|^WEBAPP_URL=.*|WEBAPP_URL=$TAILSCALE_URL|" .env

# --- 6. Avvia bot ---
echo "Avvio bot..."
docker compose down 2>/dev/null || true
docker compose up -d --build

echo ""
echo "================================================"
echo "  TUTTO ATTIVO!"
echo ""
echo "  URL: $TAILSCALE_URL"
echo ""
echo "  Il bot si riavvia da solo al boot."
echo "  Per vedere i log: docker compose logs -f"
echo "================================================"
