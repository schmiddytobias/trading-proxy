import os
import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import requests

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("market-proxy")

app = FastAPI(title="Market Desk Proxy & Cloud Engine", version="3.2-Tradegate-GDrive")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Lokaler Fallback-Pfad + Google Drive Konfiguration
PORTFOLIO_FILE = os.path.join(os.path.dirname(__file__), "portfolio_store.json")
DRIVE_FILENAME = "portfolio_store.json"
DEFAULT_GDRIVE_FOLDER_ID = "1Ty79vWzXZFJXU0MBakNoVyoFW3SVTef_"

# Stammdaten-Mapping: WKN / Ticker / Alias -> ISIN + Offizieller Name + Yahoo-Fallback
SECURITY_MASTER_DB = {
    "NVDA": {"isin": "US67066G1040", "name": "NVIDIA Corp.", "yahoo": "NVD.DE", "country": "USA", "sector": "Technologie", "type": "Aktie"},
    "918422": {"isin": "US67066G1040", "name": "NVIDIA Corp.", "yahoo": "NVD.DE", "country": "USA", "sector": "Technologie", "type": "Aktie"},
    "US67066G1040": {"isin": "US67066G1040", "name": "NVIDIA Corp.", "yahoo": "NVD.DE", "country": "USA", "sector": "Technologie", "type": "Aktie"},
    "NVD.DE": {"isin": "US67066G1040", "name": "NVIDIA Corp.", "yahoo": "NVD.DE", "country": "USA", "sector": "Technologie", "type": "Aktie"},

    "GOOGL": {"isin": "US02079K3059", "name": "Alphabet Inc. (Class A)", "yahoo": "ABEC.DE", "country": "USA", "sector": "Technologie", "type": "Aktie"},
    "A14Y6F": {"isin": "US02079K3059", "name": "Alphabet Inc. (Class A)", "yahoo": "ABEC.DE", "country": "USA", "sector": "Technologie", "type": "Aktie"},
    "US02079K3059": {"isin": "US02079K3059", "name": "Alphabet Inc. (Class A)", "yahoo": "ABEC.DE", "country": "USA", "sector": "Technologie", "type": "Aktie"},
    "ABEC.DE": {"isin": "US02079K3059", "name": "Alphabet Inc. (Class A)", "yahoo": "ABEC.DE", "country": "USA", "sector": "Technologie", "type": "Aktie"},

    "RHM.DE": {"isin": "DE0007030009", "name": "Rheinmetall AG", "yahoo": "RHM.DE", "country": "Deutschland", "sector": "Industrie / Rüstung", "type": "Aktie"},
    "RHM": {"isin": "DE0007030009", "name": "Rheinmetall AG", "yahoo": "RHM.DE", "country": "Deutschland", "sector": "Industrie / Rüstung", "type": "Aktie"},
    "703000": {"isin": "DE0007030009", "name": "Rheinmetall AG", "yahoo": "RHM.DE", "country": "Deutschland", "sector": "Industrie / Rüstung", "type": "Aktie"},
    "DE0007030009": {"isin": "DE0007030009", "name": "Rheinmetall AG", "yahoo": "RHM.DE", "country": "Deutschland", "sector": "Industrie / Rüstung", "type": "Aktie"},

    "SAP.DE": {"isin": "DE0007164600", "name": "SAP SE", "yahoo": "SAP.DE", "country": "Deutschland", "sector": "Technologie", "type": "Aktie"},
    "SAP": {"isin": "DE0007164600", "name": "SAP SE", "yahoo": "SAP.DE", "country": "Deutschland", "sector": "Technologie", "type": "Aktie"},
    "716460": {"isin": "DE0007164600", "name": "SAP SE", "yahoo": "SAP.DE", "country": "Deutschland", "sector": "Technologie", "type": "Aktie"},
    "DE0007164600": {"isin": "DE0007164600", "name": "SAP SE", "yahoo": "SAP.DE", "country": "Deutschland", "sector": "Technologie", "type": "Aktie"},

    "PLTR": {"isin": "US69608A1088", "name": "Palantir Technologies Inc.", "yahoo": "PTX.DE", "country": "USA", "sector": "Technologie", "type": "Aktie"},
    "A2QA4J": {"isin": "US69608A1088", "name": "Palantir Technologies Inc.", "yahoo": "PTX.DE", "country": "USA", "sector": "Technologie", "type": "Aktie"},
    "US69608A1088": {"isin": "US69608A1088", "name": "Palantir Technologies Inc.", "yahoo": "PTX.DE", "country": "USA", "sector": "Technologie", "type": "Aktie"},

    "ASML": {"isin": "NL0010273215", "name": "ASML Holding N.V.", "yahoo": "ASME.DE", "country": "Europa (ex DE)", "sector": "Technologie", "type": "Aktie"},
    "A1J4U4": {"isin": "NL0010273215", "name": "ASML Holding N.V.", "yahoo": "ASME.DE", "country": "Europa (ex DE)", "sector": "Technologie", "type": "Aktie"},
    "NL0010273215": {"isin": "NL0010273215", "name": "ASML Holding N.V.", "yahoo": "ASME.DE", "country": "Europa (ex DE)", "sector": "Technologie", "type": "Aktie"},

    "AVGO": {"isin": "US11135F1012", "name": "Broadcom Inc.", "yahoo": "1YD.DE", "country": "USA", "sector": "Technologie", "type": "Aktie"},
    "A2JG9Z": {"isin": "US11135F1012", "name": "Broadcom Inc.", "yahoo": "1YD.DE", "country": "USA", "sector": "Technologie", "type": "Aktie"},
    "US11135F1012": {"isin": "US11135F1012", "name": "Broadcom Inc.", "yahoo": "1YD.DE", "country": "USA", "sector": "Technologie", "type": "Aktie"},

    "MUV2.DE": {"isin": "DE0008430026", "name": "Münchener Rück AG", "yahoo": "MUV2.DE", "country": "Deutschland", "sector": "Finanzen", "type": "Aktie"},
    "843002": {"isin": "DE0008430026", "name": "Münchener Rück AG", "yahoo": "MUV2.DE", "country": "Deutschland", "sector": "Finanzen", "type": "Aktie"},
    "DE0008430026": {"isin": "DE0008430026", "name": "Münchener Rück AG", "yahoo": "MUV2.DE", "country": "Deutschland", "sector": "Finanzen", "type": "Aktie"},

    "AAPL": {"isin": "US0378331005", "name": "Apple Inc.", "yahoo": "APC.DE", "country": "USA", "sector": "Technologie", "type": "Aktie"},
    "865985": {"isin": "US0378331005", "name": "Apple Inc.", "yahoo": "APC.DE", "country": "USA", "sector": "Technologie", "type": "Aktie"},
    "US0378331005": {"isin": "US0378331005", "name": "Apple Inc.", "yahoo": "APC.DE", "country": "USA", "sector": "Technologie", "type": "Aktie"},

    "MSFT": {"isin": "US5949181045", "name": "Microsoft Corp.", "yahoo": "MSF.DE", "country": "USA", "sector": "Technologie", "type": "Aktie"},
    "870747": {"isin": "US5949181045", "name": "Microsoft Corp.", "yahoo": "MSF.DE", "country": "USA", "sector": "Technologie", "type": "Aktie"},
    "US5949181045": {"isin": "US5949181045", "name": "Microsoft Corp.", "yahoo": "MSF.DE", "country": "USA", "sector": "Technologie", "type": "Aktie"},

    "AMZN": {"isin": "US0231351067", "name": "Amazon.com Inc.", "yahoo": "AMZ.DE", "country": "USA", "sector": "Konsumgüter", "type": "Aktie"},
    "906866": {"isin": "US0231351067", "name": "Amazon.com Inc.", "yahoo": "AMZ.DE", "country": "USA", "sector": "Konsumgüter", "type": "Aktie"},
    "US0231351067": {"isin": "US0231351067", "name": "Amazon.com Inc.", "yahoo": "AMZ.DE", "country": "USA", "sector": "Konsumgüter", "type": "Aktie"},

    "TSLA": {"isin": "US88160R1014", "name": "Tesla Inc.", "yahoo": "TL0.DE", "country": "USA", "sector": "Konsumgüter", "type": "Aktie"},
    "A1CX3T": {"isin": "US88160R1014", "name": "Tesla Inc.", "yahoo": "TL0.DE", "country": "USA", "sector": "Konsumgüter", "type": "Aktie"},
    "US88160R1014": {"isin": "US88160R1014", "name": "Tesla Inc.", "yahoo": "TL0.DE", "country": "USA", "sector": "Konsumgüter", "type": "Aktie"},

    "META": {"isin": "US30303M1027", "name": "Meta Platforms Inc.", "yahoo": "FB2A.DE", "country": "USA", "sector": "Technologie", "type": "Aktie"},
    "A1JWVX": {"isin": "US30303M1027", "name": "Meta Platforms Inc.", "yahoo": "FB2A.DE", "country": "USA", "sector": "Technologie", "type": "Aktie"},
    "US30303M1027": {"isin": "US30303M1027", "name": "Meta Platforms Inc.", "yahoo": "FB2A.DE", "country": "USA", "sector": "Technologie", "type": "Aktie"},

    "A1JX52": {"isin": "IE00B3RBWM25", "name": "Vanguard FTSE All-World UCITS ETF (Dist)", "yahoo": "VGWL.DE", "country": "Global", "sector": "Breit gestreut (Welt)", "type": "ETF"},
    "IE00B3RBWM25": {"isin": "IE00B3RBWM25", "name": "Vanguard FTSE All-World UCITS ETF (Dist)", "yahoo": "VGWL.DE", "country": "Global", "sector": "Breit gestreut (Welt)", "type": "ETF"},
    "A2PKXG": {"isin": "IE00BK5BQT80", "name": "Vanguard FTSE All-World UCITS ETF (Acc)", "yahoo": "VWCE.DE", "country": "Global", "sector": "Breit gestreut (Welt)", "type": "ETF"},
    "IE00BK5BQT80": {"isin": "IE00BK5BQT80", "name": "Vanguard FTSE All-World UCITS ETF (Acc)", "yahoo": "VWCE.DE", "country": "Global", "sector": "Breit gestreut (Welt)", "type": "ETF"},
    "A0RPWH": {"isin": "IE00B4L5Y983", "name": "iShares Core MSCI World UCITS ETF", "yahoo": "EUNL.DE", "country": "Global", "sector": "Breit gestreut (Welt)", "type": "ETF"},
    "IE00B4L5Y983": {"isin": "IE00B4L5Y983", "name": "iShares Core MSCI World UCITS ETF", "yahoo": "EUNL.DE", "country": "Global", "sector": "Breit gestreut (Welt)", "type": "ETF"},
}

LOOKTHROUGH_DATABASE = {
    "DE0008474503": {
        "name": "Deka-Technologie CF", "type": "Fonds", "country": "USA", "currency": "EUR", "sector": "Technologie",
        "breakdown": {
            "countries": {"USA": 84.5, "Taiwan": 6.2, "Niederlande": 4.1, "Sonstige": 5.2},
            "sectors": {"Halbleiter & KI": 48.0, "Software & Cloud": 32.5, "Hardware": 14.5, "Liquidität": 5.0},
            "currencies": {"USD": 88.0, "EUR": 8.0, "Sonstige": 4.0}
        }
    },
    "847450": {
        "name": "Deka-Technologie CF", "type": "Fonds", "country": "USA", "currency": "EUR", "sector": "Technologie",
        "breakdown": {
            "countries": {"USA": 84.5, "Taiwan": 6.2, "Niederlande": 4.1, "Sonstige": 5.2},
            "sectors": {"Halbleiter & KI": 48.0, "Software & Cloud": 32.5, "Hardware": 14.5, "Liquidität": 5.0},
            "currencies": {"USD": 88.0, "EUR": 8.0, "Sonstige": 4.0}
        }
    },
    "IE00B3RBWM25": {
        "name": "Vanguard FTSE All-World UCITS ETF (Dist)", "type": "ETF", "country": "Global", "currency": "EUR", "sector": "Breit gestreut (Welt)",
        "breakdown": {
            "countries": {"USA": 62.0, "Japan": 6.1, "UK": 3.8, "Frankreich": 2.8, "Deutschland": 2.1, "Sonstige": 23.2},
            "sectors": {"Technologie": 26.5, "Finanzen": 15.2, "Gesundheit": 11.4, "Industrie": 10.8, "Konsum": 12.1, "Sonstige": 24.0},
            "currencies": {"USD": 63.5, "EUR": 10.2, "JPY": 6.1, "GBP": 3.8, "Sonstige": 16.4}
        }
    },
    "A1JX52": {
        "name": "Vanguard FTSE All-World UCITS ETF (Dist)", "type": "ETF", "country": "Global", "currency": "EUR", "sector": "Breit gestreut (Welt)",
        "breakdown": {
            "countries": {"USA": 62.0, "Japan": 6.1, "UK": 3.8, "Frankreich": 2.8, "Deutschland": 2.1, "Sonstige": 23.2},
            "sectors": {"Technologie": 26.5, "Finanzen": 15.2, "Gesundheit": 11.4, "Industrie": 10.8, "Konsum": 12.1, "Sonstige": 24.0},
            "currencies": {"USD": 63.5, "EUR": 10.2, "JPY": 6.1, "GBP": 3.8, "Sonstige": 16.4}
        }
    }
}

# ==========================================
# GOOGLE DRIVE CLOUD-FUNKTIONEN
# ==========================================
def get_gdrive_service():
    sa_json_str = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON", "").strip()
    if not sa_json_str:
        return None
    try:
        sa_info = json.loads(sa_json_str)
        creds = service_account.Credentials.from_service_account_info(
            sa_info,
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        logger.error("Google Drive Init-Fehler: %s", e)
        return None

def find_drive_file_id(service, folder_id: str) -> str | None:
    query = f"name = '{DRIVE_FILENAME}' and '{folder_id}' in parents and trashed = false"
    results = service.files().list(q=query, spaces="drive", fields="files(id, name)", pageSize=1).execute()
    files = results.get("files", [])
    return files[0]["id"] if files else None

def save_to_gdrive(data: dict) -> bool:
    service = get_gdrive_service()
    if not service:
        return False
    folder_id = os.environ.get("GDRIVE_FOLDER_ID", DEFAULT_GDRIVE_FOLDER_ID).strip()
    json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    media = MediaIoBaseUpload(io.BytesIO(json_bytes), mimetype="application/json", resumable=False)

    existing_file_id = find_drive_file_id(service, folder_id)
    if existing_file_id:
        service.files().update(fileId=existing_file_id, media_body=media).execute()
    else:
        service.files().create(body={"name": DRIVE_FILENAME, "parents": [folder_id]}, media_body=media, fields="id").execute()
    return True

def load_from_gdrive() -> dict | None:
    service = get_gdrive_service()
    if not service:
        return None
    folder_id = os.environ.get("GDRIVE_FOLDER_ID", DEFAULT_GDRIVE_FOLDER_ID).strip()
    existing_file_id = find_drive_file_id(service, folder_id)
    if not existing_file_id:
        return {"holdings": [], "sparplaene": []}

    request_drive = service.files().get_media(fileId=existing_file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request_drive)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)
    return json.loads(fh.read().decode("utf-8"))

# ==========================================
# TRADEGATE + YAHOO HYBRID-KURSABFRAGE
# ==========================================
def parse_german_float(val) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val) if val > 0 else None
    s = str(val).strip().replace(".", "").replace(",", ".")
    try:
        num = float(s)
        return num if num > 0 else None
    except ValueError:
        return None

def fetch_tradegate_quote(isin: str) -> dict | None:
    """Fragt Live-Euro-Kurse direkt von Tradegate (07:30 - 22:00 Uhr) ab."""
    if not isin or len(isin) != 12:
        return None
    try:
        url = f"https://data.tradegate.de/kurse.php?isin={isin}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": "https://www.tradegate.de/"
        }
        r = requests.get(url, headers=headers, timeout=4)
        if not r.ok:
            return None
        data = r.json()
        if not isinstance(data, dict) or data.get("error"):
            return None

        last_p = parse_german_float(data.get("last"))
        bid_p = parse_german_float(data.get("bid"))
        ask_p = parse_german_float(data.get("ask"))
        close_p = parse_german_float(data.get("close"))

        price = last_p or (round((bid_p + ask_p) / 2, 2) if (bid_p and ask_p) else (bid_p or ask_p or close_p))
        if not price or price <= 0:
            return None

        chg_pct = 0.0
        delta_raw = data.get("delta")
        if delta_raw is not None:
            parsed_delta = parse_german_float(str(delta_raw).replace("%", "").replace("+", ""))
            if parsed_delta is not None:
                chg_pct = -parsed_delta if str(delta_raw).strip().startswith("-") else parsed_delta
        elif close_p and close_p > 0:
            chg_pct = ((price - close_p) / close_p) * 100.0

        return {
            "status": "success",
            "price": round(price, 2),
            "changePct": round(chg_pct, 2),
            "currency": "EUR",
            "source": "Tradegate"
        }
    except Exception as e:
        logger.debug("Tradegate-Abruf für %s nicht verfügbar: %s", isin, e)
        return None

def yahoo_search_metadata(query: str) -> dict:
    """Sucht über die Yahoo-Search-API nach offiziellem Namen, ISIN und Ticker."""
    try:
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={requests.utils.quote(query)}&quotesCount=5&newsCount=0"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=4)
        if r.ok:
            quotes = r.json().get("quotes", [])
            if quotes:
                # Bevorzuge deutsche Börsenplätze (.DE), falls vorhanden
                de_match = next((q for q in quotes if str(q.get("symbol", "")).endswith(".DE")), None)
                best = de_match or quotes[0]
                return {
                    "symbol": best.get("symbol", query),
                    "name": best.get("longname") or best.get("shortname") or "",
                    "type": "ETF" if best.get("quoteType") == "ETF" else "Aktie"
                }
    except Exception:
        pass
    return {}

def resolve_security_info(identifier: str) -> dict:
    clean = identifier.strip().upper()
    if clean in SECURITY_MASTER_DB:
        return SECURITY_MASTER_DB[clean].copy()

    isin = clean if (len(clean) == 12 and clean[:2].isalpha()) else None
    meta = yahoo_search_metadata(clean)
    yahoo_sym = meta.get("symbol") or clean
    name = meta.get("name") or clean
    sec_type = meta.get("type") or ("Fonds" if clean.startswith(("DE000", "LU")) else "Aktie")

    return {
        "isin": isin,
        "name": name,
        "yahoo": yahoo_sym,
        "country": "Deutschland" if yahoo_sym.endswith(".DE") else "Global",
        "sector": "Technologie",
        "type": sec_type
    }

def fetch_single_quote(identifier: str):
    orig_id = identifier.strip().upper()
    sec = resolve_security_info(orig_id)

    # 1. Primär: Tradegate Live-Kurs in EUR (07:30 - 22:00 Uhr), falls ISIN bekannt
    if sec.get("isin"):
        tg_res = fetch_tradegate_quote(sec["isin"])
        if tg_res and tg_res.get("status") == "success":
            return orig_id, tg_res

    # 2. Sekundär: Yahoo Finance Fallback (bevorzugt .DE Euro-Ticker)
    yahoo_sym = sec.get("yahoo") or orig_id
    try:
        ticker = yf.Ticker(yahoo_sym)
        hist = ticker.history(period="2d")
        if hist.empty:
            info = ticker.fast_info
            price = getattr(info, "last_price", None) or getattr(info, "regular_market_price", None)
            prev = getattr(info, "previous_close", None) or price
            cur = getattr(info, "currency", "EUR" if yahoo_sym.endswith(".DE") else "USD")
            chg = (((price - prev) / prev) * 100) if prev and price else 0.0
            if price:
                return orig_id, {
                    "status": "success",
                    "price": round(float(price), 2),
                    "changePct": round(float(chg), 2),
                    "currency": cur,
                    "source": "Yahoo"
                }
            return orig_id, {"status": "not_found"}

        current_price = float(hist["Close"].iloc[-1])
        prev_close = float(hist["Close"].iloc[-2]) if len(hist) > 1 else current_price
        chg_pct = ((current_price - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0
        cur = "EUR" if yahoo_sym.endswith(".DE") else "USD"
        try:
            cur = ticker.fast_info.currency or cur
        except Exception:
            pass

        return orig_id, {
            "status": "success",
            "price": round(current_price, 2),
            "changePct": round(chg_pct, 2),
            "currency": cur,
            "source": "Yahoo"
        }
    except Exception as ex:
        logger.warning("Quote-Fehler für %s (%s): %s", orig_id, yahoo_sym, ex)
        return orig_id, {"status": "error", "message": str(ex)}

# ==========================================
# API ENDPUNKTE
# ==========================================
@app.get("/")
def health_check():
    gdrive_configured = bool(os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON", "").strip())
    return {
        "status": "online",
        "service": "Market Desk Proxy & Cloud Engine",
        "version": "3.2-Tradegate-GDrive",
        "gdrive_connected": gdrive_configured
    }

@app.post("/save-portfolio")
async def save_portfolio(request: Request):
    try:
        data = await request.json()
        with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        gdrive_ok = save_to_gdrive(data)
        logger.info("Depot gespeichert (%d Positionen, Google Drive: %s).", len(data.get("holdings", [])), gdrive_ok)
        return {
            "status": "success",
            "storage": "google_drive" if gdrive_ok else "local_fallback"
        }
    except Exception as e:
        logger.error("Fehler beim Speichern des Depots: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/load-portfolio")
def load_portfolio():
    try:
        drive_data = load_from_gdrive()
        if drive_data is not None:
            with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
                json.dump(drive_data, f, ensure_ascii=False, indent=2)
            return drive_data

        if os.path.exists(PORTFOLIO_FILE):
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"holdings": [], "sparplaene": []}
    except Exception as e:
        logger.error("Fehler beim Laden des Depots: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/batch-quotes")
async def batch_quotes(request: Request):
    payload = await request.json()
    identifiers = payload.get("identifiers", [])
    if not identifiers:
        raise HTTPException(status_code=400, detail="Keine Identifiers angegeben")

    results = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(fetch_single_quote, ident) for ident in identifiers]
        for f in futures:
            ident, res = f.result()
            results[ident] = res

    return {"status": "ok", "count": len(results), "data": results}

@app.get("/quote-deep")
def quote_deep(query: str = ""):
    clean = query.strip().upper()
    if not clean:
        raise HTTPException(status_code=400, detail="Keine Query angegeben")

    if clean in LOOKTHROUGH_DATABASE:
        base = LOOKTHROUGH_DATABASE[clean]
        _, quote_res = fetch_single_quote(clean)
        price = quote_res.get("price") if quote_res.get("status") == "success" else None
        return {
            "status": "success",
            "name": base["name"],
            "type": base["type"],
            "country": base["country"],
            "currency": base["currency"],
            "sector": base["sector"],
            "price": price,
            "breakdown": base.get("breakdown")
        }

    sec = resolve_security_info(clean)
    _, quote_res = fetch_single_quote(clean)

    name = sec.get("name") or clean
    cur = quote_res.get("currency") or "EUR"
    price = quote_res.get("price") if quote_res.get("status") == "success" else None
    country = sec.get("country", "Global")
    sector = sec.get("sector", "Technologie")
    sec_type = sec.get("type", "Aktie")

    # Zusätzliche Metadaten über yfinance versuchen, falls Name noch dem Kürzel entspricht
    if name == clean:
        try:
            t = yf.Ticker(sec.get("yahoo") or clean)
            info = t.info or {}
            name = info.get("longName") or info.get("shortName") or clean
            c_raw = info.get("country")
            if c_raw in ["United States", "US"]:
                country = "USA"
            elif c_raw == "Germany":
                country = "Deutschland"
            if info.get("sector"):
                sector = info.get("sector")
        except Exception:
            pass

    return {
        "status": "success",
        "name": name,
        "type": sec_type,
        "country": country,
        "currency": cur,
        "sector": sector,
        "price": round(float(price), 2) if price else None,
        "source": quote_res.get("source", "Hybrid")
    }
