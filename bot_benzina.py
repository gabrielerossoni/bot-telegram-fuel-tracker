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
from datetime import datetime, time as dtime

import pandas as pd
import pytz
import requests
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
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

def genera_infografica(top_stazioni: pd.DataFrame, carburante: str, chat_id: int):
    """Genera una card grafica riassuntiva dei prezzi migliori."""
    if top_stazioni.empty: return None
    
    file_path = f"report_{chat_id}.png"
    plt.figure(figsize=(8, 5))
    plt.axis('off')
    
    # Background color e stile
    plt.gcf().set_facecolor('#1e1e1e')
    
    y_pos = 0.85
    plt.text(0.5, 0.95, f"REPORT {carburante.upper()}", color='white', 
             fontsize=22, weight='bold', ha='center', va='center')
    plt.text(0.5, 0.88, "Top 3 Distributori più economici", color='#aaaaaa', 
             fontsize=12, ha='center', va='center')
    
    colors = ['#FFD700', '#C0C0C0', '#CD7F32'] # Oro, Argento, Bronzo
    
    for i, (_, row) in enumerate(top_stazioni.head(3).iterrows()):
        nome = str(row.get("nome impianto") or row.get("gestore") or "N/D").strip()[:30]
        prezzo = float(row["prezzo"])
        brand = str(row.get("bandiera") or "stazione").strip()
        
        # Disegna Box
        rect = plt.Rectangle((0.1, y_pos - 0.2), 0.8, 0.18, color='#2d2d2d', 
                             ec=colors[i], lw=2, transform=plt.gca().transAxes)
        plt.gca().add_patch(rect)
        
        # Testo
        plt.text(0.15, y_pos - 0.08, f"{i+1}. {brand.upper()}", color='white', 
                 fontsize=14, weight='bold', transform=plt.gca().transAxes)
        plt.text(0.15, y_pos - 0.14, nome, color='#aaaaaa', 
                 fontsize=10, transform=plt.gca().transAxes)
        plt.text(0.85, y_pos - 0.12, f"{prezzo:.3f}€/L", color=colors[i], 
                 fontsize=18, weight='bold', ha='right', transform=plt.gca().transAxes)
        
        y_pos -= 0.22

    # Salva
    plt.savefig(file_path, bbox_inches='tight', dpi=100, facecolor='#1e1e1e')
    plt.close()
    return file_path



# ══════════════════════════════════════════════════════════════════
#  PIPELINE PRINCIPALE
# ══════════════════════════════════════════════════════════════════

async def genera_e_invia_report(bot, chat_id, cfg):
    """Pipeline completa: scarica, elabora e invia il report con infografica."""
    try:
        anagrafica, prezzi = scarica_dati()
        stazioni = trova_stazioni_vicine(anagrafica, prezzi, cfg)
        
        ora = datetime.now(TZ_ROMA).strftime("%H:%M")
        data = datetime.now(TZ_ROMA).strftime("%d/%m")
        modo = "Self" if cfg["self_service"] else "Servito"
        
        if stazioni.empty:
            await bot.send_message(chat_id=chat_id, text="❌ Nessun prezzo trovato in zona.")
            return

        top = stazioni.head(cfg["top_n"])
        media = stazioni["prezzo"].mean()
        minimo = stazioni["prezzo"].min()

        # Genera Infografica (solo se ci sono dati)
        img_path = genera_infografica(top, cfg["carburante"], chat_id)
        
        # Testo report
        testo = (
            f"⛽ *SaaS DASHBOARD* • {data}\n"
            f"🏷 `{cfg['carburante'].upper()}` • {modo}\n\n"
        )

        buttons = []
        for i, (_, row) in enumerate(top.iterrows()):
            brand = str(row.get("bandiera") or "").strip()
            prezzo = float(row["prezzo"])
            dist = float(row["distanza_km"])
            lat, lon = row["_lat"], row["_lon"]
            
            emoji = get_brand_emoji(brand)
            status = "🔥" if prezzo < cfg["soglia_alert"] else "✅" if prezzo <= media else "⚖️"
            testo += f"{_MEDAGLIE[i] if i < 10 else '•'} *{prezzo:.3f} €/L* {status}\n   {emoji} ({dist:.1f} km)\n"
            
            if i < 3:
                maps_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
                buttons.append([InlineKeyboardButton(f"📍 {i+1}. Vai da {brand if brand else 'lui'}", url=maps_url)])

        # Invio Foto + Testo
        if img_path and os.path.exists(img_path):
            try:
                with open(img_path, "rb") as photo:
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=photo,
                        caption=testo,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=InlineKeyboardMarkup(buttons) if buttons else None
                    )
            finally:
                if os.path.exists(img_path):
                    os.remove(img_path)
        else:
            await bot.send_message(chat_id=chat_id, text=testo, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

        # Alert Prezzo Bersaglio
        if minimo <= cfg["soglia_alert"]:
            await bot.send_message(
                chat_id=chat_id,
                text=f"🔔 *ALERT PREZZO BERSAGLIO!*\nAbbiamo trovato {cfg['carburante']} a *{minimo:.3f} €/L*, che è pari o sotto la tua soglia di {cfg['soglia_alert']:.2f}€!",
                parse_mode=ParseMode.MARKDOWN
            )
            
    except Exception as e:
        log.error("Errore report: %s", e, exc_info=True)
        await bot.send_message(chat_id=chat_id, text=f"⚠️ Errore recupero dati: `{e}`")



# ══════════════════════════════════════════════════════════════════
#  HANDLER TELEGRAM — rispondono ai comandi dell'utente
# ══════════════════════════════════════════════════════════════════

MAIN_MENU = ReplyKeyboardMarkup([
    [KeyboardButton("⛽ Prezzi Vicini", request_location=False)],
    [KeyboardButton("📍 Invia Posizione attuale", request_location=True)],
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

def main() -> None:
    # Gestione modalità CLI
    if "--report" in sys.argv:
        import asyncio
        asyncio.run(run_once())
        return

    if not BOT_TOKEN or len(BOT_TOKEN) < 20:
        print("⚠️  Imposta BOT_TOKEN nel file .env!")
        raise SystemExit(1)

    # Pulizia vecchi file CSV di cache se presenti (SaaS 3.0 non li usa più)
    for f in ["anagrafica_cache.csv", "prezzi_cache.csv"]:
        if os.path.exists(f): 
            try: os.remove(f)
            except: pass

    print("\n" + "═"*45)
    print("  🚀  BOT BENZINA SaaS v3.0  🚀")
    print("═"*45)
    print("  Database: SQLite (bot_data.db)")
    print("  Status:   Multi-user enabled")
    print("═"*45)
    print("  Bot in ascolto... premi Ctrl+C per uscire.\n")


    # Costruisce l'applicazione con job_queue abilitata
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Registra i handler
    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("help",       cmd_help))
    app.add_handler(CommandHandler("carburanti", cmd_carburanti))
    app.add_handler(CommandHandler("prezzi",     cmd_prezzi))
    
    # Handler SaaS
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_menu))


    # Scheduler: report mattutino automatico (default 08:00)
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

    log.info("Bot in ascolto — usa /prezzi su Telegram per ottenere i prezzi ora")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()