# ⛽ Bot Benzina Stateless v4.0

Un bot Telegram per trovare i prezzi dei carburanti più economici intorno a te.

**100% Stateless**: niente database. Le preferenze restano nel telefono dell'utente (localStorage).

## Caratteristiche

- Privacy totale — il server non salva nulla
- Mini App con mappa Leaflet e preferenze locali
- Report eleganti con link a Google Maps
- Dati ufficiali MASE aggiornati quotidianamente
- Deploy con Docker in un solo comando

## Deploy con Docker

```bash
chmod +x start.sh
./start.sh
```

Lo script installa Docker (se serve), clona il repo e avvia il container.

Oppure manualmente:

```bash
docker compose up -d --build
```

## Variabili Ambiente (.env)

```env
BOT_TOKEN=il_tuo_token_qui
WEBAPP_URL=https://la-tua-url        # URL pubblico HTTPS della WebApp
PORT=8080                             # Porta del server (default 8080)
```

## Struttura

- `bot_benzina.py` — logica bot e API server
- `index.html` — WebApp entry point
- `static/app.js` — frontend mappa e dashboard
- `static/style.css` — stili
- `Dockerfile` + `docker-compose.yml` — deploy Docker

---

*Niente database. Niente complicazioni. Solo risparmio.*

## Licenza

Copyright (c) 2026 Gabriele Rossoni. Tutti i diritti riservati.
