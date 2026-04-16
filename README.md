# ⛽ Bot Benzina Stateless v4.0 🚀

Un bot Telegram professionale per trovare i prezzi dei carburanti più economici intorno a te.

**Questa versione è 100% Stateless**: non usa database (niente SQLite/Postgres). Le preferenze e la posizione sono salvate direttamente nel telefono dell'utente (localStorage) per la massima privacy e facilità di hosting.

## ✨ Caratteristiche

- 📍 **Privacy Totale**: Il server non salva nulla. I tuoi dati restano sul tuo dispositivo.
- 🚀 **Mini App Intelligente**: Dashboard con mappa che ricorda le tue preferenze (tipo carburante, raggio) localmente.
- 🛰 **Fast GPS**: Accedi alla posizione in tempo reale direttamente dalla Mini App.
- 💎 **Premium UI**: Report eleganti in chat con link diretti a Google Maps.
- ☁️ **Cloud Native**: Caricabile su Render, Railway, Vercel o qualsiasi host Python senza configurazioni di database.

## 🛠 Installazione Rapida

```bash
pip install -r requirements.txt
python bot_benzina.py
```

## 🌐 Variabili Ambiente (.env)

```env
BOT_TOKEN=il_tuo_token_qui
WEBAPP_URL=https://tuo-utente.github.io/tuo-repo  # Se usi GitHub Pages
```

## 🚀 Deployment (Frontend su GitHub Pages)

Questa versione supporta il **decoupling**: puoi ospitare la Mini App su GitHub Pages e il bot su un server separato.

1. **Backend (Bot)**: Ospita `bot_benzina.py` su Render/Railway/VPS. Il server ha il supporto **CORS** attivo per dialogare con GitHub.
2. **Frontend (Mini App)**: Carica `index.html` nella root di GitHub Pages e mantieni `app.js` e `style.css` nella cartella `static/`.

## 📁 Struttura

- `bot_benzina.py`: Logica bot e API.
- `index.html`: Entry point Web App (in root per GitHub Pages).
- `static/`: Contiene `app.js` e `style.css`.

---

*Niente database. Niente complicazioni. Solo risparmio.*

## 📄 Licenza

Progetto coperto da Copyright (c) 2026 Gabriele Rossoni. Tutti i diritti riservati.
