#!/bin/bash
set -e

REPO="https://github.com/TUO_USERNAME/BotBenzina.git"
INSTALL_DIR="$HOME/botbenzina"

echo "============================"
echo "  BOT BENZINA - Deploy"
echo "============================"

# --- Docker check ---
if ! command -v docker &> /dev/null; then
    echo "Docker non trovato. Installazione..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    echo "Docker installato. Fai logout e login, poi riesegui questo script."
    exit 0
fi

if ! docker compose version &> /dev/null; then
    echo "[ERRORE] docker compose non disponibile. Aggiorna Docker."
    exit 1
fi

# --- Clone or update ---
if [ -d "$INSTALL_DIR" ]; then
    echo "Aggiornamento codice..."
    cd "$INSTALL_DIR"
    git pull
else
    echo "Clonazione repository..."
    git clone "$REPO" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# --- .env check ---
if [ ! -f .env ]; then
    echo ""
    echo "[ERRORE] File .env non trovato!"
    echo "Crea il file .env con almeno:"
    echo "  BOT_TOKEN=il_tuo_token"
    echo "  WEBAPP_URL=https://la-tua-url"
    echo ""
    cp .env.example .env 2>/dev/null || true
    exit 1
fi

# --- Deploy ---
echo "Avvio container..."
docker compose up -d --build

echo ""
echo "============================"
echo "  BOT IN ESECUZIONE"
echo "  Logs: docker compose logs -f"
echo "  Stop: docker compose down"
echo "============================"
