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
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackContext,
    CommandHandler,
    ContextTypes,
)

# ══════════════════════════════════════════════════════════════════
#  LOGGING
# ══════════════════════════════════════════════════════════════════
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("bot_benzina")

# ══════════════════════════════════════════════════════════════════
#  CONFIGURAZIONE
# ══════════════════════════════════════════════════════════════════
# ⚙️  Modifica i valori qui sotto, oppure usa variabili d'ambiente
# per l'uso su GitHub Actions / server remoto (più sicuro per i token).
# ─────────────────────────────────────────────────────────────────
CONFIG = {
    # ── Telegram ──────────────────────────────────────────────────
    # Ottienilo da @BotFather (es. "7123456789:AAFxyz...")
    # Imposta BOT_TOKEN nel file .env oppure come variabile d'ambiente
    "bot_token": os.environ.get("BOT_TOKEN", ""),

    # Ottienilo da @userinfobot (solo il numero, es. "123456789")
    # Usato per il report mattutino automatico
    "chat_id": os.environ.get("CHAT_ID", ""),

    # ── La tua posizione ──────────────────────────────────────────
    # maps.google.com → tasto destro su casa tua → clicca le coordinate
    # Imposta LAT e LON nel file .env
    "lat": float(os.environ.get("LAT",  "0")),
    "lon": float(os.environ.get("LON",  "0")),

    # ── Parametri di ricerca ──────────────────────────────────────
    "raggio_km":    int(os.environ.get("RAGGIO",   "10")),   # km
    "top_n":        int(os.environ.get("TOP_N",      "5")),   # stazioni da mostrare

    # "Benzina" | "Gasolio" | "GPL" | "Metano" | "Benzina Special" | "Gasolio Special"
    "carburante":  os.environ.get("CARBURANTE", "Benzina"),

    # True = self-service · False = servito
    "self_service": os.environ.get("SELF_SERVICE", "true").lower() == "true",

    # ── Alert prezzo basso ────────────────────────────────────────
    "soglia_alert": float(os.environ.get("SOGLIA", "1.5")),

    # ── Orario invio automatico (HH:MM, ora italiana) ─────────────
    "orario_invio": os.environ.get("ORARIO", "08:00"),
}

# URL dati ufficiali MASE aggiornati ogni mattina
# I file usano | come separatore (pipe), non ;
URL_ANAGRAFICA = "https://www.mise.gov.it/images/exportCSV/anagrafica_impianti_attivi.csv"
URL_PREZZI     = "https://www.mise.gov.it/images/exportCSV/prezzo_alle_8.csv"

# Cache locale (usata se il download fallisce)
_SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
CACHE_ANA      = os.path.join(_SCRIPT_DIR, "anagrafica_cache.csv")
CACHE_PRE      = os.path.join(_SCRIPT_DIR, "prezzi_cache.csv")

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


def _fetch_csv(url: str, cache_file: str) -> bytes:
    """
    Scarica il CSV dall'URL.
    Se il download fallisce (rete, risposta HTML, file troppo piccolo),
    usa la cache locale. Raise RuntimeError se neanche la cache esiste.
    """
    headers = {"User-Agent": "Mozilla/5.0 (BotBenzina/2.0; +github.com/bot-benzina)"}
    try:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()

        ct = r.headers.get("Content-Type", "").lower()
        if "text/html" in ct:
            raise ValueError(f"Risposta HTML invece di CSV (Content-Type: {ct})")

        if len(r.content) < 5_000:
            raise ValueError(f"File troppo piccolo ({len(r.content)} bytes) — forse sito offline")

        with open(cache_file, "wb") as f:
            f.write(r.content)

        log.info("CSV scaricato: %s (%d KB)", os.path.basename(cache_file), len(r.content) // 1024)
        return r.content

    except Exception as e:
        log.warning("Download fallito da %s: %s", url, e)
        if os.path.exists(cache_file):
            mtime = datetime.fromtimestamp(os.path.getmtime(cache_file)).strftime("%d/%m %H:%M")
            log.info("Uso cache locale %s (salvata il %s)", os.path.basename(cache_file), mtime)
            with open(cache_file, "rb") as f:
                return f.read()
        raise RuntimeError(
            f"Download fallito e nessuna cache disponibile.\n"
            f"URL: {url}\nErrore: {e}"
        ) from e


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
    """Scarica e parsa anagrafica e prezzi dal MASE. Usa cache se offline."""
    raw_ana = _fetch_csv(URL_ANAGRAFICA, CACHE_ANA)
    raw_pre = _fetch_csv(URL_PREZZI, CACHE_PRE)
    ana = _parse_csv(raw_ana)
    pre = _parse_csv(raw_pre)
    log.info("Anagrafica: %d impianti | Prezzi: %d rilevazioni", len(ana), len(pre))
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


def formatta_messaggio(stazioni: pd.DataFrame, cfg: dict) -> str:
    """
    Costruisce il testo Markdown del messaggio Telegram.
    Funziona correttamente con le colonne lowercase del DataFrame.
    """
    ora    = datetime.now(TZ_ROMA).strftime("%d/%m/%Y %H:%M")
    modo   = "Self-service" if cfg["self_service"] else "Servito"
    carb   = cfg["carburante"]
    soglia = cfg["soglia_alert"]

    righe = [
        f"⛽ *Prezzi {carb} · {modo}*",
        f"📍 Entro {cfg['raggio_km']} km · {ora}",
        "━" * 28,
    ]

    if stazioni.empty:
        righe.append(
            "❌ Nessuna stazione trovata nel raggio specificato.\n"
            f"Prova ad aumentare `raggio_km` (attuale: {cfg['raggio_km']} km) "
            "oppure cambia tipo di carburante con `/prezzi gasolio`."
        )
        return "\n".join(righe)

    top    = stazioni.head(cfg["top_n"])
    media  = stazioni["prezzo"].mean()
    minimo = stazioni["prezzo"].min()

    for i, (_, row) in enumerate(top.iterrows()):
        # Le colonne sono in lowercase dopo il parsing
        nome    = str(row.get("nome impianto") or row.get("gestore") or "N/D").strip()[:32]
        via     = str(row.get("indirizzo") or "").strip()
        comune  = str(row.get("comune")    or "").strip()
        prezzo  = float(row["prezzo"])
        dist_km = float(row["distanza_km"])
        bandiera = str(row.get("bandiera") or "").strip()

        alert_tag = " 🔔" if prezzo < soglia else ""
        brand_tag = f" `{bandiera}`" if bandiera and bandiera.lower() not in ("nan", "") else ""
        medal     = _MEDAGLIE[i] if i < len(_MEDAGLIE) else f"*{i + 1}.*"

        righe.append(
            f"{medal} *{prezzo:.3f} €/L*{alert_tag}{brand_tag}\n"
            f"   📌 {nome}\n"
            f"   🗺 {via}, {comune} ({dist_km:.1f} km)"
        )
        righe.append("")

    righe.append("━" * 28)
    righe.append(f"📊 Media zona: *{media:.3f} €/L*   Min: *{minimo:.3f} €/L*")
    righe.append(f"🔎 Stazioni analizzate: {len(stazioni)}")

    if minimo < soglia:
        righe.extend([
            "",
            f"🔔 *ALERT PREZZO BASSO!*\n"
            f"   Il minimo ({minimo:.3f} €/L) è sotto soglia ({soglia:.2f} €/L)!",
        ])

    righe.extend([
        "",
        "_Dati ufficiali MASE · aggiornati ogni mattina_",
    ])

    return "\n".join(righe)


# ══════════════════════════════════════════════════════════════════
#  PIPELINE PRINCIPALE
# ══════════════════════════════════════════════════════════════════

async def genera_report(cfg: dict) -> str:
    """
    Scarica → elabora → formatta il messaggio.
    È async per compatibilità con i handler Telegram,
    ma la parte CPU-bound (pandas) è sincrona (dataset piccolo, <50 ms).
    """
    anagrafica, prezzi = scarica_dati()
    stazioni = trova_stazioni_vicine(anagrafica, prezzi, cfg)
    return formatta_messaggio(stazioni, cfg)


# ══════════════════════════════════════════════════════════════════
#  HANDLER TELEGRAM — rispondono ai comandi dell'utente
# ══════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — messaggio di benvenuto."""
    await update.message.reply_text(
        "👋 *Benvenuto su Bot Benzina!*\n\n"
        "Ottengo i prezzi dai dati ufficiali MASE in tempo reale.\n\n"
        "*Comandi disponibili:*\n"
        "• /prezzi — prezzi nella tua zona adesso\n"
        "• /prezzi gasolio — prezzi gasolio\n"
        "• /prezzi benzina servito — benzina servito\n"
        "• /carburanti — lista tipi disponibili\n"
        "• /info — configurazione attuale\n"
        "• /help — questa guida\n\n"
        "_Il bot ti invia automaticamente i prezzi ogni mattina_ ⏰",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/help — guida comandi."""
    await update.message.reply_text(
        "⛽ *Bot Benzina — Guida comandi*\n\n"
        "`/prezzi` — prezzi adesso (tipo configurato)\n"
        "`/prezzi gasolio` — prepend il tipo\n"
        "`/prezzi benzina self` — forza self-service\n"
        "`/prezzi gasolio servito` — forza servito\n"
        "`/carburanti` — tipi disponibili\n"
        "`/info` — configurazione corrente\n"
        "`/start` — benvenuto\n\n"
        "_Dati MASE aggiornati ogni mattina alle 8:00_",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/info — mostra configurazione attuale."""
    cfg  = CONFIG
    modo = "Self-service" if cfg["self_service"] else "Servito"
    await update.message.reply_text(
        "⚙️ *Configurazione attuale*\n\n"
        f"📍 Posizione: `{cfg['lat']:.5f}, {cfg['lon']:.5f}`\n"
        f"📏 Raggio: `{cfg['raggio_km']} km`\n"
        f"⛽ Carburante: `{cfg['carburante']}`\n"
        f"🛠 Modalità: `{modo}`\n"
        f"🔔 Soglia alert: `{cfg['soglia_alert']:.2f} €/L`\n"
        f"📊 Stazioni mostrate: `{cfg['top_n']}`\n"
        f"⏰ Report automatico: `{cfg['orario_invio']}` (ora italiana)\n",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_carburanti(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/carburanti — elenca i tipi supportati."""
    elenco = "\n".join(f"• `{c}`" for c in CARBURANTI_VALIDI)
    await update.message.reply_text(
        f"⛽ *Tipi di carburante disponibili:*\n\n{elenco}\n\n"
        "Esempi:\n"
        "`/prezzi gasolio`\n"
        "`/prezzi GPL`\n"
        "`/prezzi Metano`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_prezzi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /prezzi [carburante] [self|servito]
    Mostra i prezzi adesso. Argomenti opzionali sovrascrivono il CONFIG
    solo per questa richiesta (senza modificare la configurazione globale).
    """
    cfg  = dict(CONFIG)   # copia locale — non modifica il global CONFIG
    args = [a.lower() for a in (context.args or [])]

    # riconosci tipo carburante dagli argomenti ("/prezzi gasolio")
    for carb in CARBURANTI_VALIDI:
        if carb.lower() in args:
            cfg["carburante"] = carb
            break

    # riconosci modalità self / servito
    if "servito" in args:
        cfg["self_service"] = False
    elif "self" in args:
        cfg["self_service"] = True

    modo = "self-service" if cfg["self_service"] else "servito"
    wait_msg = await update.message.reply_text(
        f"🔄 Recupero prezzi *{cfg['carburante']}* ({modo})…",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        testo = await genera_report(cfg)
        await wait_msg.edit_text(testo, parse_mode=ParseMode.MARKDOWN)
    except RuntimeError as e:
        log.error("Errore dati in cmd_prezzi: %s", e)
        await wait_msg.edit_text(
            f"⚠️ *Dati non disponibili*\n\n`{e}`\n\n"
            "Riprova tra qualche minuto.",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        log.error("Errore inatteso in cmd_prezzi: %s", e, exc_info=True)
        await wait_msg.edit_text(
            f"❌ *Errore inatteso:* `{type(e).__name__}: {e}`",
            parse_mode=ParseMode.MARKDOWN,
        )


# ══════════════════════════════════════════════════════════════════
#  JOB SCHEDULATO — report automatico mattutino
# ══════════════════════════════════════════════════════════════════

async def job_report_mattutino(context: CallbackContext) -> None:
    """
    Invia il report mattutino automaticamente all'orario configurato.
    Schedulato dalla job_queue di python-telegram-bot (APScheduler).
    """
    log.info("⏰ Job mattutino avviato")
    cfg = dict(CONFIG)
    try:
        testo = await genera_report(cfg)
        await context.bot.send_message(
            chat_id=cfg["chat_id"],
            text=testo,
            parse_mode=ParseMode.MARKDOWN,
        )
        log.info("✅ Report mattutino inviato a chat_id=%s", cfg["chat_id"])
    except Exception as e:
        log.error("❌ Errore job mattutino: %s", e, exc_info=True)


# ══════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════

def main() -> None:
    token = CONFIG["bot_token"]

    # Validazione token
    if not token or "INCOLLA" in token or len(token) < 20:
        print("⚠️  Imposta il BOT_TOKEN prima di avviare!")
        print("   • Modifica CONFIG['bot_token'] nello script, oppure")
        print("   • Esporta la variabile d'ambiente: set BOT_TOKEN=il_tuo_token")
        raise SystemExit(1)

    print("🤖 Bot Benzina v2.0 — avvio in corso...")
    print(f"   Posizione: {CONFIG['lat']}, {CONFIG['lon']}")
    print(f"   Raggio: {CONFIG['raggio_km']} km | Carburante: {CONFIG['carburante']}")
    print(f"   Report automatico alle: {CONFIG['orario_invio']} (ora italiana)")
    print("   Premi Ctrl+C per fermare.\n")

    # Costruisce l'applicazione con job_queue abilitata
    app = (
        Application.builder()
        .token(token)
        .build()
    )

    # Registra i command handler
    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("help",       cmd_help))
    app.add_handler(CommandHandler("info",       cmd_info))
    app.add_handler(CommandHandler("carburanti", cmd_carburanti))
    app.add_handler(CommandHandler("prezzi",     cmd_prezzi))

    # Scheduler: report mattutino automatico
    orario = CONFIG["orario_invio"]
    try:
        h, m = map(int, orario.split(":"))
    except ValueError:
        print(f"⚠️  Formato orario_invio non valido: '{orario}'. Usa HH:MM (es. '08:00').")
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


# ══════════════════════════════════════════════════════════════════
#  ISTRUZIONI GITHUB ACTIONS (invio automatico gratuito)
# ══════════════════════════════════════════════════════════════════
#
#  Con GitHub Actions il bot gira su server remoto senza tenere
#  il PC acceso. Invio automatico mattutino senza lo scheduler:
#
#  1. Crea un repo PRIVATO su GitHub
#  2. Salva questo file come bot_benzina.py nella root del repo
#  3. Crea .github/workflows/benzina.yml:
#
#     name: Bot Benzina
#     on:
#       schedule:
#         - cron: '0 6 * * 1-5'   # Lun-Ven alle 08:00 (UTC+2 = cron 06:00)
#       workflow_dispatch:          # avvio manuale dalla UI GitHub
#     jobs:
#       run:
#         runs-on: ubuntu-latest
#         steps:
#           - uses: actions/checkout@v4
#           - uses: actions/setup-python@v5
#             with: { python-version: '3.11' }
#           - name: Installa dipendenze
#             run: pip install "python-telegram-bot[job-queue]==20.7" requests pandas pytz -q
#           - name: Invia report benzina
#             run: |
#               python - <<'EOF'
#               import asyncio, os, sys
#               sys.path.insert(0, '.')
#               from bot_benzina import genera_report, CONFIG
#               from telegram import Bot
#               from telegram.constants import ParseMode
#               async def main():
#                   cfg = dict(CONFIG)
#                   testo = await genera_report(cfg)
#                   bot = Bot(token=cfg["bot_token"])
#                   async with bot:
#                       await bot.send_message(chat_id=cfg["chat_id"], text=testo, parse_mode=ParseMode.MARKDOWN)
#               asyncio.run(main())
#               EOF
#             env:
#               BOT_TOKEN: ${{ secrets.BOT_TOKEN }}
#               CHAT_ID:   ${{ secrets.CHAT_ID }}
#
#  4. In Settings → Secrets → Actions aggiungi:
#       BOT_TOKEN → il tuo token da @BotFather
#       CHAT_ID   → il tuo ID da @userinfobot