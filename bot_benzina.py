# -*- coding: utf-8 -*-
"""
BOT BENZINA TELEGRAM v2.0
─────────────────────────────────────────────────────────────────
Prezzi carburanti in tempo reale · Dati ufficiali MASE
Risponde ai comandi in qualsiasi momento + report mattutino auto
─────────────────────────────────────────────────────────────────

PREREQUISITI TELEGRAM (5 minuti)
  ① Crea il bot:     Telegram → @BotFather → /newbot → copia il token
  ② Trova il tuo ID: Telegram → @userinfobot → manda /start → copia "Id"
  ③ Sblocca il bot:  Vai sulla chat del tuo bot → manda /start

INSTALLAZIONE (una volta sola)
  pip install "python-telegram-bot[job-queue]==20.7" requests pandas pytz

AVVIO
  python bot_benzina.py
  oppure con variabili d'ambiente:
  BOT_TOKEN="..." CHAT_ID="..." python bot_benzina.py

COMANDI TELEGRAM
  /prezzi              – prezzi carburante (tipo configurato) adesso
  /prezzi gasolio      – prezzi gasolio adesso
  /prezzi benzina self – benzina self-service
  /prezzi gasolio servito – gasolio servito
  /carburanti          – lista tipi disponibili
  /info                – configurazione corrente
  /help                – guida comandi
  /start               – benvenuto

GITHUB ACTIONS (invio automatico gratuito senza lasciare il PC acceso)
  Vedi istruzioni in fondo al file.
"""

# ══════════════════════════════════════════════════════════════════
#  INSTALLAZIONE AUTOMATICA (utile su Colab)
# ══════════════════════════════════════════════════════════════════
import subprocess, sys

# Forza UTF-8 sull'output: evita crash con emoji su terminali Windows (cp1252)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Mappa: nome pacchetto pip → nome modulo importabile
# (non sempre coincidono, es. "python-telegram-bot" si importa come "telegram")
_DEPS = [
    ("python-telegram-bot[job-queue]==20.7", "telegram"),
    ("requests",                             "requests"),
    ("pandas",                               "pandas"),
    ("pytz",                                 "pytz"),
    ("python-dotenv",                        "dotenv"),
]

def _install(pkg: str) -> None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

import importlib
for _pkg, _mod in _DEPS:
    try:
        importlib.import_module(_mod)
    except ImportError:
        print(f"[install] {_pkg}...")
        _install(_pkg)
        importlib.invalidate_caches()

# Carica variabili da .env (se presente) — non fa nulla se il file manca
from dotenv import load_dotenv
load_dotenv()

# ══════════════════════════════════════════════════════════════════
#  IMPORT
# ══════════════════════════════════════════════════════════════════
import io
import logging
import math
import os
import hmac
import hashlib
import json
from datetime import datetime, time as dtime

import pandas as pd
import pytz
import requests
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, MenuButtonWebApp
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackContext,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from database import db

# ══════════════════════════════════════════════════════════════════
#  LOGGING & SILENCER
# ══════════════════════════════════════════════════════════════════
logging.basicConfig(
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M",
    level=logging.INFO,
)
# Silenzia log di sistema troppo rumorosi
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.ERROR)

log = logging.getLogger("bot")

# ══════════════════════════════════════════════════════════════════
#  CONFIGURAZIONE
# ══════════════════════════════════════════════════════════════════
# ⚙️  Modifica i valori qui sotto, oppure usa variabili d'ambiente
# per l'uso su GitHub Actions / server remoto (più sicuro per i token).
# ─────────────────────────────────────────────────────────────────
# ⚙️ Valori predefiniti per i nuovi utenti
DEFAULT_CONFIG = {
    "raggio_km":    10,
    "top_n":        5,
    "carburante":   "Benzina",
    "self_service": True,
    "soglia_alert": 1.55,
    "orario_invio": "08:00",
}

def get_user_cfg(chat_id: int) -> dict:
    """Recupera la config dal DB o usa i default se è un nuovo utente."""
    user = db.get_user(chat_id)
    if not user:
        return {**DEFAULT_CONFIG, "lat": 0, "lon": 0}
    
    # Mapping campi DB -> campi attesi dal codice
    return {
        "lat": user["lat"],
        "lon": user["lon"],
        "raggio_km": user["raggio_km"],
        "top_n": DEFAULT_CONFIG["top_n"],
        "carburante": user["carburante"],
        "self_service": bool(user["self_service"]),
        "soglia_alert": user["soglia_alert"],
        "orario_invio": user["orario_invio"],
    }

# Token necessario per l'avvio (da .env)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# URL dati ufficiali MASE aggiornati ogni mattina
URL_ANAGRAFICA = "https://www.mise.gov.it/images/exportCSV/anagrafica_impianti_attivi.csv"
URL_PREZZI     = "https://www.mise.gov.it/images/exportCSV/prezzo_alle_8.csv"

# Brand mapping per icone premium
BRAND_MAP = {
    "eni": "🐕", "agip": "🐕", "q8": "⛵", "ip": "🟦", "tamoil": "🔴",
    "esso": "🐅", "shell": "🐚", "repsol": "🟠", "costo": "⚪", "conad": "🛒",
    "auchan": "🛒", "carrefour": "🛒", "coop": "🛒", "eg": "🟦", "api": "🟦",
}

def get_brand_emoji(brand: str) -> str:
    brand = str(brand).lower()
    for k, v in BRAND_MAP.items():
        if k in brand: return v
    return "⛽"

# Tipi di carburante riconosciuti dal dataset MASE
CARBURANTI_VALIDI = [
    "Benzina", "Gasolio", "GPL", "Metano",
    "Benzina Special", "Gasolio Special",
]

TZ_ROMA = pytz.timezone("Europe/Rome")

# ══════════════════════════════════════════════════════════════════
#  FUNZIONI DATI
# ══════════════════════════════════════════════════════════════════

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza in km tra due coordinate GPS (formula di Haversine)."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _fetch_csv(url: str) -> bytes:
    """Scarica il CSV in memoria senza salvare su disco."""
    headers = {"User-Agent": "Mozilla/5.0 (BotBenzina/2.0; +github.com/bot-benzina)"}
    try:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        if "text/html" in r.headers.get("Content-Type", "").lower():
            raise ValueError("Risposta HTML invece di CSV")
        if len(r.content) < 5_000:
            raise ValueError("File troppo piccolo — sito MASE probabilmente offline")
        return r.content
    except Exception as e:
        log.error("Download fallito da %s: %s", url, e)
        raise RuntimeError(f"Impossibile scaricare dati MASE: {e}") from e


def _parse_csv(raw: bytes) -> pd.DataFrame:
    """
    Parsa un CSV MASE:
      - Riga 0:  data estrazione ("Estrazione del YYYY-MM-DD") → skiprows=1
      - Riga 1:  intestazione colonne
      - Separatore: | (pipe)
      - Encoding: latin-1
    Restituisce DataFrame con colonne in lowercase e strip.
    """
    text = raw.decode("latin-1", errors="replace")
    df = pd.read_csv(
        io.StringIO(text),
        sep="|",
        dtype=str,
        on_bad_lines="skip",
        skiprows=1,          # salta la riga "Estrazione del ..."
    )
    df.columns = df.columns.str.strip().str.lower()
    return df


def scarica_dati() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Scarica e parsa anagrafica e prezzi dal MASE direttamente in memoria."""
    raw_ana = _fetch_csv(URL_ANAGRAFICA)
    raw_pre = _fetch_csv(URL_PREZZI)
    ana = _parse_csv(raw_ana)
    pre = _parse_csv(raw_pre)
    log.info("Dati caricati in memoria: %d impianti, %d prezzi", len(ana), len(pre))
    return ana, pre


def _col(df: pd.DataFrame, *candidati: str) -> str:
    """
    Cerca la prima colonna del DataFrame che contiene uno dei pattern candidati.
    Raise RuntimeError se nessuna trovata.
    """
    cols = df.columns.tolist()
    for pattern in candidati:
        found = next((c for c in cols if pattern in c), None)
        if found:
            return found
    raise RuntimeError(
        f"Nessuna colonna trovata con pattern {candidati}.\n"
        f"Colonne disponibili: {cols}"
    )


def trova_stazioni_vicine(
    anagrafica: pd.DataFrame,
    prezzi: pd.DataFrame,
    cfg: dict,
) -> pd.DataFrame:
    """
    Pipeline:
      1. Converte le coordinate lat/lon dell'anagrafica
      2. Calcola la distanza di ogni impianto dalla posizione utente
      3. Filtra per raggio_km
      4. Unisce i prezzi (filtrando per carburante e self/servito)
      5. Ordina per prezzo crescente

    Restituisce DataFrame con almeno le colonne:
      prezzo, distanza_km, nome impianto, gestore, indirizzo, comune, bandiera
    """
    # ── 1. Coordinate anagrafica ──────────────────────────────────
    # Colonne attese dopo lowercase: 'latitudine', 'longitudine'
    lat_col = _col(anagrafica, "latitudine", "lat")
    lon_col = _col(anagrafica, "longitudine", "lon")

    ana = anagrafica.copy()
    ana["_lat"] = pd.to_numeric(
        ana[lat_col].str.replace(",", ".", regex=False), errors="coerce"
    )
    ana["_lon"] = pd.to_numeric(
        ana[lon_col].str.replace(",", ".", regex=False), errors="coerce"
    )
    ana = ana.dropna(subset=["_lat", "_lon"])

    if ana.empty:
        raise RuntimeError("Anagrafica vuota dopo la conversione delle coordinate.")

    # ── 2. Calcolo distanza e filtro raggio ───────────────────────
    user_lat, user_lon = cfg["lat"], cfg["lon"]
    ana["distanza_km"] = ana.apply(
        lambda r: haversine(user_lat, user_lon, r["_lat"], r["_lon"]),
        axis=1,
    )
    vicine = ana[ana["distanza_km"] <= cfg["raggio_km"]].copy()
    log.info("Stazioni entro %d km: %d", cfg["raggio_km"], len(vicine))

    if vicine.empty:
        return pd.DataFrame()

    # ── 3. ID impianto nell'anagrafica ────────────────────────────
    # Colonna: 'idimpianto'
    id_ana = _col(vicine, "idimpianto")
    vicine["_id"] = vicine[id_ana].str.strip()

    # ── 4. Prezzi: trova colonne e filtra ─────────────────────────
    # Struttura prezzi: idImpianto | descCarburante | prezzo | isSelf | dtComu
    # Dopo lowercase:   idimpianto | desccarburante  | prezzo | isself | dtcomu
    pre = prezzi.copy()

    id_pre     = _col(pre, "idimpianto")
    carb_col   = _col(pre, "desccarburante", "carburante")
    prezzo_col = _col(pre, "prezzo")
    self_col   = _col(pre, "isself", "self")

    pre["_id"]     = pre[id_pre].str.strip()
    pre["_prezzo"] = pd.to_numeric(
        pre[prezzo_col].str.replace(",", ".", regex=False), errors="coerce"
    )
    pre["_self"]   = pre[self_col].str.strip()
    pre["_carb"]   = pre[carb_col].str.strip()

    is_self_val = "1" if cfg["self_service"] else "0"

    pre_ok = pre[
        pre["_carb"].str.contains(cfg["carburante"], case=False, na=False) &
        (pre["_self"] == is_self_val)
    ].dropna(subset=["_prezzo"]).copy()

    if pre_ok.empty:
        log.warning(
            "Nessun prezzo trovato per carburante='%s' self=%s",
            cfg["carburante"], is_self_val,
        )
        return pd.DataFrame()

    # ── 5. Merge e ordina ─────────────────────────────────────────
    merged = vicine.merge(
        pre_ok[["_id", "_prezzo"]],
        on="_id",
        how="inner",
    ).rename(columns={"_prezzo": "prezzo"})

    merged = merged.dropna(subset=["prezzo"])
    merged = merged.sort_values("prezzo").reset_index(drop=True)

    return merged


# ══════════════════════════════════════════════════════════════════
#  FORMATTAZIONE MESSAGGIO
# ══════════════════════════════════════════════════════════════════

# Medaglie/numeri fino a 10 stazioni (espandibile)
_MEDAGLIE = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

def genera_messaggio_premium(top_stazioni: pd.DataFrame, cfg: dict, data_str: str) -> tuple[str, list]:
    """Crea un messaggio elegante e i relativi pulsanti interattivi."""
    if top_stazioni.empty: 
        return "❌ Nessun prezzo trovato nei paraggi.", []
    
    modo = "Self" if cfg["self_service"] else "Servito"
    testo = [
        f"⛽ *{cfg['carburante'].upper()}* • {modo}",
        f"📍 _Raggio: {cfg['raggio_km']}km • {data_str}_",
        "─" * 15,
        ""
    ]
    
    buttons = []
    # Pulsante per aprire la Mini App Dashboard
    url_dashboard = os.environ.get("WEBAPP_URL")
    if url_dashboard:
        buttons.append([InlineKeyboardButton("🚀 Apri Dashboard Mappa", web_app=WebAppInfo(url=url_dashboard))])
    
    for i, (_, row) in enumerate(top_stazioni.iterrows()):
        brand = str(row.get("bandiera") or "Generico").strip().upper()
        prezzo = float(row["prezzo"])
        dist = float(row["distanza_km"])
        lat, lon = row["_lat"], row["_lon"]
        emoji = get_brand_emoji(brand)
        
        # Formattazione riga
        medaglia = _MEDAGLIE[i] if i < len(_MEDAGLIE) else "•"
        testo.append(f"{medaglia} *{prezzo:.3f} €/L* — {emoji} {brand}")
        testo.append(f"   └ 📏 {dist:.1f} km")
        
        # Pulsanti navigazione per i primi 3
        if i < 3:
            maps_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
            buttons.append([InlineKeyboardButton(f"📍 Vai da {brand} (#{i+1})", url=maps_url)])

    return "\n".join(testo), buttons



# ══════════════════════════════════════════════════════════════════
#  PIPELINE PRINCIPALE
# ══════════════════════════════════════════════════════════════════

async def genera_e_invia_report(bot, chat_id, cfg):
    """Pipeline completa: scarica, elabora e invia il report interattivo."""
    try:
        anagrafica, prezzi = scarica_dati()
        stazioni = trova_stazioni_vicine(anagrafica, prezzi, cfg)
        
        data_str = datetime.now(TZ_ROMA).strftime("%d/%m")
        
        if stazioni.empty:
            await bot.send_message(chat_id=chat_id, text="❌ Nessun prezzo trovato in zona.")
            return

        top = stazioni.head(cfg["top_n"])
        minimo = stazioni["prezzo"].min()

        # Genera Messaggio Premium
        testo, buttons = genera_messaggio_premium(top, cfg, data_str)
        
        await bot.send_message(
            chat_id=chat_id, 
            text=testo, 
            parse_mode=ParseMode.MARKDOWN, 
            reply_markup=InlineKeyboardMarkup(buttons)
        )

        # Alert Prezzo Bersaglio
        if minimo <= cfg["soglia_alert"]:
            await bot.send_message(
                chat_id=chat_id,
                text=f"🔔 *ALERT PREZZO BERSAGLIO!*\n{cfg['carburante']} trovato a *{minimo:.3f} €/L*!",
                parse_mode=ParseMode.MARKDOWN
            )
            
    except Exception as e:
        log.error("Errore report: %s", e, exc_info=True)
        await bot.send_message(chat_id=chat_id, text=f"⚠️ Errore recupero dati: `{e}`")



# ══════════════════════════════════════════════════════════════════
#  HANDLER TELEGRAM — rispondono ai comandi dell'utente
# ══════════════════════════════════════════════════════════════════

MAIN_MENU = ReplyKeyboardMarkup([
    [KeyboardButton("⛽ Prezzi Vicini")],
    [KeyboardButton("🚀 Apri Dashboard", web_app=WebAppInfo(url=os.environ.get("WEBAPP_URL", "")))],
    [KeyboardButton("📍 Invia Posizione", request_location=True)],
    [KeyboardButton("⚙️ Impostazioni"), KeyboardButton("📖 Aiuto")]
], resize_keyboard=True)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — messaggio di benvenuto e registrazione."""
    chat_id = update.effective_chat.id
    db.create_or_update_user(chat_id)
    
    await update.message.reply_text(
        "🚀 *Benvenuto su Bot Benzina Pro!*\n\n"
        "Questo bot ti aiuta a trovare i distributori più economici intorno a te.\n\n"
        "📍 *Per iniziare*: Clicca il tasto qui sotto per inviare la tua posizione attuale.\n"
        "⏰ *Automatico*: Riceverai un report ogni mattina alle 08:00.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MAIN_MENU
    )

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce l'invio della posizione GPS da parte dell'utente."""
    loc = update.message.location
    chat_id = update.effective_chat.id
    
    db.create_or_update_user(chat_id, lat=loc.latitude, lon=loc.longitude)
    
    await update.message.reply_text(
        f"✅ *Posizione aggiornata!*\n"
        f"Ora cercherò i prezzi intorno a: `{loc.latitude:.5f}, {loc.longitude:.5f}`.\n\n"
        "Clicca '⛽ Prezzi Vicini' per vedere i risultati.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MAIN_MENU
    )

async def cmd_prezzi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/prezzi [carburante] [self|servito] o pulsante menu."""
    chat_id = update.effective_chat.id
    cfg = get_user_cfg(chat_id)
    
    if cfg["lat"] == 0:
        await update.message.reply_text("📍 Prima devi inviare la tua posizione!")
        return

    # Se invocato via comando con argomenti
    args = [a.lower() for a in (context.args or [])]
    for carb in CARBURANTI_VALIDI:
        if carb.lower() in args: cfg["carburante"] = carb
    if "servito" in args: cfg["self_service"] = False
    elif "self" in args: cfg["self_service"] = True

    await genera_e_invia_report(context.bot, chat_id, cfg)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/help — guida comandi."""
    await update.message.reply_text(
        "⛽ *Bot Benzina Pro — Guida*\n\n"
        "•usa i tasti in basso per le funzioni principali\n"
        "•`/prezzi gasolio` — cerca carburante specifico\n"
        "•`/prezzi benzina servito` — forza servito\n"
        "•`/carburanti` — lista tipi disponibili\n"
        "•`/start` — resetta o inizia da capo\n\n"
        "_I prezzi sono aggiornati ogni mattina dal MASE._",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_carburanti(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/carburanti — elenca i tipi supportati."""
    elenco = "\n".join(f"• `{c}`" for c in CARBURANTI_VALIDI)
    await update.message.reply_text(
        f"⛽ *Tipi disponibili:*\n\n{elenco}",
        parse_mode=ParseMode.MARKDOWN
    )


# ══════════════════════════════════════════════════════════════════
#  SERVER WEB APP (API per la Dashboard)
# ══════════════════════════════════════════════════════════════════

def verify_telegram_init_data(init_data: str) -> dict:
    """Valida i dati provenienti dalla Web App per sicurezza."""
    if not init_data: return None
    try:
        from urllib.parse import parse_qs, unquote
        parsed = {k: v[0] for k, v in parse_qs(init_data).items()}
        hash_check = parsed.pop('hash', None)
        
        # Crea stringa di controllo
        data_check_string = "\n".join([f"{k}={v}" for k, v in sorted(parsed.items())])
        
        # Crea chiave segreta (HMAC-SHA256 del token con "WebAppData")
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        if calculated_hash == hash_check:
            user_data = json.loads(parsed['user'])
            return user_data
    except Exception as e:
        log.error("Errore validazione TWA: %s", e)
    return None

async def web_api_prices(request):
    """Endpoint che restituisce i prezzi JSON per la Web App."""
    init_data = request.query.get('initData')
    user = verify_telegram_init_data(init_data)
    
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)
    
    chat_id = user['id']
    cfg = get_user_cfg(chat_id)
    
    if cfg["lat"] == 0:
        return web.json_response({"error": "Posizione non impostata"}, status=400)
        
    try:
        anagrafica, prezzi = scarica_dati()
        stazioni = trova_stazioni_vicine(anagrafica, prezzi, cfg)
        
        # Converti DataFrame in lista di dizionari "puliti"
        stations_list = []
        for _, row in stazioni.head(15).iterrows():
            stations_list.append({
                "nome_impianto": row.get("nome impianto", ""),
                "bandiera": row.get("bandiera", ""),
                "prezzo": float(row["prezzo"]),
                "distanza_km": float(row["distanza_km"]),
                "_lat": float(row["_lat"]),
                "_lon": float(row["_lon"])
            })
            
        return web.json_response({
            "config": cfg,
            "stations": stations_list
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def start_web_server():
    """Avvia il server web aiohttp in background."""
    app = web.Application()
    app.router.add_get('/api/prices', web_api_prices)
    # Serve i file statici dalla cartella 'static'
    app.router.add_static('/', path='static', name='static', show_index=True)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    log.info("🌐 Web App Server attivo su http://localhost:8080")



async def handle_text_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce i click sui pulsanti del menu testuale o coordinate manuali."""
    text = str(update.message.text).strip()
    chat_id = update.effective_chat.id
    
    if text == "⛽ Prezzi Vicini":
        await cmd_prezzi(update, context)
    elif text == "⚙️ Impostazioni":
        cfg = get_user_cfg(chat_id)
        modo = "Self" if cfg["self_service"] else "Servito"
        await update.message.reply_text(
            "⚙️ *Le tue Preferenze*\n\n"
            f"⛽ Carburante: `{cfg['carburante']}`\n"
            f"🛠 Modalità: `{modo}`\n"
            f"📏 Raggio: `{cfg['raggio_km']} km`\n"
            f"⏰ Report: `{cfg['orario_invio']}`\n\n"
            "_Per ora usa i comandi per cambiare (es. /prezzi gasolio)_",
            parse_mode=ParseMode.MARKDOWN
        )
    elif text == "📖 Aiuto":
        await cmd_help(update, context)
    
    # Riconoscimento manuale coordinate (es. "45.12, 9.34")
    elif "," in text:
        try:
            lat_s, lon_s = text.split(",")
            lat, lon = float(lat_s.strip()), float(lon_s.strip())
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                db.create_or_update_user(chat_id, lat=lat, lon=lon)
                await update.message.reply_text(f"✅ Posizione impostata manualmente: `{lat}, {lon}`")
            else:
                raise ValueError()
        except:
            pass # Non è una coordinata, ignora

# ══════════════════════════════════════════════════════════════════
#  JOB SCHEDULATO — report automatico mattutino
# ══════════════════════════════════════════════════════════════════

async def job_report_mattutino(context: CallbackContext) -> None:
    """Invia il report mattutino a TUTTI gli utenti registrati nel DB."""
    all_users = db.get_all_users()
    log.info("⏰ Job mattutino: invio a %d utenti", len(all_users))
    
    for user_data in all_users:
        chat_id = user_data["chat_id"]
        cfg = get_user_cfg(chat_id)
        if cfg["lat"] == 0: continue # Salta utenti senza posizione
        
        try:
            await genera_e_invia_report(context.bot, chat_id, cfg)
        except Exception as e:
            log.error("Errore invio report a %s: %s", chat_id, e)

# ══════════════════════════════════════════════════════════════════
#  MAIN / CLI MODE
# ══════════════════════════════════════════════════════════════════

async def run_once():
    """Modalità singola per GitHub Actions (usa il primo utente o variabile d'ambiente)."""
    from telegram import Bot
    token = os.environ.get("BOT_TOKEN", "")
    chat_id = os.environ.get("CHAT_ID", "")
    
    if not token or not chat_id:
        log.error("BOT_TOKEN e CHAT_ID necessari per run_once")
        return

    bot = Bot(token=token)
    cfg = get_user_cfg(int(chat_id))
    # Se il DB è vuoto per questo chat_id, usa i default di env
    if cfg["lat"] == 0:
        cfg["lat"] = float(os.environ.get("LAT", 0))
        cfg["lon"] = float(os.environ.get("LON", 0))

    async with bot:
        await genera_e_invia_report(bot, int(chat_id), cfg)

async def on_startup(app: Application):
    """Callback eseguito all'avvio del bot."""
    await start_web_server()
    
    # Imposta il Menu Button (quello a sinistra del campo testo)
    url = os.environ.get("WEBAPP_URL")
    if url:
        try:
            await app.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="Mappa", web_app=WebAppInfo(url=url))
            )
            log.info("✅ Menu Button configurato con successo")
        except Exception as e:
            log.error("❌ Errore configurazione Menu Button: %s", e)

def main() -> None:
    # Gestione modalità CLI
    if "--report" in sys.argv:
        import asyncio
        asyncio.run(run_once())
        return

    if not BOT_TOKEN or len(BOT_TOKEN) < 20:
        print("⚠️  Imposta BOT_TOKEN nel file .env!")
        raise SystemExit(1)

    # Pulizia vecchi file CSV
    for f in ["anagrafica_cache.csv", "prezzi_cache.csv"]:
        if os.path.exists(f): 
            try: os.remove(f)
            except: pass

    print("\n" + "═"*45)
    print("  🚀  BOT BENZINA SaaS v3.1  🚀")
    print("═"*45)
    print("  Dashboard: http://localhost:8080")
    print("  Status:    Premium UI & Mini App")
    print("═"*45)

    # Costruisce l'applicazione
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(on_startup) # Avvia il web server all'avvio
        .build()
    )

    # Handler
    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("help",       cmd_help))
    app.add_handler(CommandHandler("carburanti", cmd_carburanti))
    app.add_handler(CommandHandler("prezzi",     cmd_prezzi))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_menu))

    # Scheduler
    orario = os.environ.get("ORARIO", "08:00")
    try:
        h, m = map(int, orario.split(":"))
    except ValueError:
        h, m = 8, 0

    app.job_queue.run_daily(
        job_report_mattutino,
        time=dtime(hour=h, minute=m, second=0, tzinfo=TZ_ROMA),
        name="report_mattutino",
    )

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()