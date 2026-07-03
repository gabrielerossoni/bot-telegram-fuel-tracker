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

# --- 2. cloudflared ---
if ! command -v cloudflared &> /dev/null; then
    echo "[2/4] Installazione cloudflared..."
    curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /tmp/cloudflared
    sudo mv /tmp/cloudflared /usr/local/bin/cloudflared
    chmod +x /usr/local/bin/cloudflared
else
    echo "[2/4] cloudflared OK."
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
    echo "  Apri .env e inserisci BOT_TOKEN:"
    echo "  nano $INSTALL_DIR/.env"
    echo "================================================"
    read -p "Premi INVIO quando hai compilato .env..."
fi

# --- 5. Servizio cloudflared ---
if [ ! -f /etc/systemd/system/cloudflared.service ]; then
    echo "[4/4] Configurazione tunnel HTTPS..."
    sudo tee /etc/systemd/system/cloudflared.service > /dev/null << 'EOF'
[Unit]
Description=Cloudflare Tunnel
After=network.target docker.service

[Service]
ExecStart=/usr/local/bin/cloudflared tunnel --url http://localhost:8080
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable cloudflared
fi

# --- 6. Avvia bot ---
echo "Avvio bot..."
cd "$INSTALL_DIR"
docker compose up -d --build

# Aspetta che il bot sia pronto
echo "Attendo che il bot risponda..."
for i in $(seq 1 30); do
    if curl -s http://localhost:8080/health > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

# --- 7. Avvia tunnel e cattura URL ---
echo "Avvio tunnel HTTPS..."
sudo systemctl restart cloudflared

echo "Attendo URL del tunnel..."
TUNNEL_URL=""
for i in $(seq 1 30); do
    sleep 2
    TUNNEL_URL=$(sudo journalctl -u cloudflared --no-pager -n 50 2>/dev/null | grep -oP 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' | head -1 || true)
    if [ -n "$TUNNEL_URL" ]; then
        break
    fi
done

if [ -z "$TUNNEL_URL" ]; then
    echo ""
    echo "[ERRORE] URL del tunnel non trovato."
    echo "Prova manualmente:"
    echo "  sudo journalctl -u cloudflared -f"
    echo "  Cerca la riga con https://xxx.trycloudflare.com"
    exit 1
fi

echo ""
echo "================================================"
echo "  TUNNEL TROVATO: $TUNNEL_URL"
echo "================================================"

# Aggiorna .env con l'URL
sed -i "s|^WEBAPP_URL=.*|WEBAPP_URL=$TUNNEL_URL|" .env

# Riavvia il bot con il nuovo URL
echo "Riavvio bot con URL corretto..."
docker compose down && docker compose up -d --build

echo ""
echo "================================================"
echo "  TUTTO ATTIVO!"
echo ""
echo "  Bot:      docker compose logs -f"
echo "  Tunnel:   sudo journalctl -u cloudflared -f"
echo "  Stop:     docker compose down"
echo "            sudo systemctl stop cloudflared"
echo ""
echo "  URL: $TUNNEL_URL"
echo "================================================"
