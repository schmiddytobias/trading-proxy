import os
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import yfinance as yf

# Logging Setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("market-proxy")

app = FastAPI(title="Bloomberg Terminal Proxy & Cloud Engine", version="3.0")

# Vollständige CORS-Freigabe für dein Terminal (Web & Handy)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PORTFOLIO_FILE = os.path.join(os.path.dirname(__file__), "portfolio_store.json")

# Look-through Datenbank für Fonds / ETFs
LOOKTHROUGH_DATABASE = {
    "DE0008474503": {
        "name": "Deka-Technologie CF",
        "type": "Fonds",
        "country": "USA",
        "currency": "EUR",
        "sector": "Technologie",
        "breakdown": {
            "countries": {"USA": 84.5, "Taiwan": 6.2, "Niederlande": 4.1, "Sonstige": 5.2},
            "sectors": {"Halbleiter & KI": 48.0, "Software & Cloud": 32.5, "Hardware": 14.5, "Liquidität": 5.0},
            "currencies": {"USD": 88.0, "EUR": 8.0, "Sonstige": 4.0}
        }
    },
    "847450": {
        "name": "Deka-Technologie CF",
        "type": "Fonds",
        "country": "USA",
        "currency": "EUR",
        "sector": "Technologie",
        "breakdown": {
            "countries": {"USA": 84.5, "Taiwan": 6.2, "Niederlande": 4.1, "Sonstige": 5.2},
            "sectors": {"Halbleiter & KI": 48.0, "Software & Cloud": 32.5, "Hardware": 14.5, "Liquidität": 5.0},
            "currencies": {"USD": 88.0, "EUR": 8.0, "Sonstige": 4.0}
        }
    },
    "IE00B3RBWM25": {
        "name": "Vanguard FTSE All-World UCITS ETF (Dist)",
        "type": "ETF",
        "country": "Global",
        "currency": "EUR",
        "sector": "Breit gestreut (Welt)",
        "breakdown": {
            "countries": {"USA": 62.0, "Japan": 6.1, "UK": 3.8, "Frankreich": 2.8, "Deutschland": 2.1, "Sonstige": 23.2},
            "sectors": {"Technologie": 26.5, "Finanzen": 15.2, "Gesundheit": 11.4, "Industrie": 10.8, "Konsum": 12.1, "Sonstige": 24.0},
            "currencies": {"USD": 63.5, "EUR": 10.2, "JPY": 6.1, "GBP": 3.8, "Sonstige": 16.4}
        }
    },
    "A1JX52": {
        "name": "Vanguard FTSE All-World UCITS ETF (Dist)",
        "type": "ETF",
        "country": "Global",
        "currency": "EUR",
        "sector": "Breit gestreut (Welt)",
        "breakdown": {
            "countries": {"USA": 62.0, "Japan": 6.1, "UK": 3.8, "Frankreich": 2.8, "Deutschland": 2.1, "Sonstige": 23.2},
            "sectors": {"Technologie": 26.5, "Finanzen": 15.2, "Gesundheit": 11.4, "Industrie": 10.8, "Konsum": 12.1, "Sonstige": 24.0},
            "currencies": {"USD": 63.5, "EUR": 10.2, "JPY": 6.1, "GBP": 3.8, "Sonstige": 16.4}
        }
    },
    "IE00BK5BQT80": {
        "name": "Vanguard FTSE All-World UCITS ETF (Acc)",
        "type": "ETF",
        "country": "Global",
        "currency": "EUR",
        "sector": "Breit gestreut (Welt)",
        "breakdown": {
            "countries": {"USA": 62.0, "Japan": 6.1, "UK": 3.8, "Frankreich": 2.8, "Deutschland": 2.1, "Sonstige": 23.2},
            "sectors": {"Technologie": 26.5, "Finanzen": 15.2, "Gesundheit": 11.4, "Industrie": 10.8, "Konsum": 12.1, "Sonstige": 24.0},
            "currencies": {"USD": 63.5, "EUR": 10.2, "JPY": 6.1, "GBP": 3.8, "Sonstige": 16.4}
        }
    },
    "A2PKXG": {
        "name": "Vanguard FTSE All-World UCITS ETF (Acc)",
        "type": "ETF",
        "country": "Global",
        "currency": "EUR",
        "sector": "Breit gestreut (Welt)",
        "breakdown": {
            "countries": {"USA": 62.0, "Japan": 6.1, "UK": 3.8, "Frankreich": 2.8, "Deutschland": 2.1, "Sonstige": 23.2},
            "sectors": {"Technologie": 26.5, "Finanzen": 15.2, "Gesundheit": 11.4, "Industrie": 10.8, "Konsum": 12.1, "Sonstige": 24.0},
            "currencies": {"USD": 63.5, "EUR": 10.2, "JPY": 6.1, "GBP": 3.8, "Sonstige": 16.4}
        }
    }
}

@app.get("/")
def health_check():
    return {
        "status": "online",
        "service": "Bloomberg Terminal Proxy & Cloud Engine",
        "version": "3.0"
    }

# ==========================================
# CLOUD SYNCHRONISATION (PORTFOLIO & SPARPLÄNE)
# ==========================================

@app.post("/save-portfolio")
async def save_portfolio(request: Request):
    try:
        data = await request.json()
        with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("Depot erfolgreich in Cloud gespeichert (%d Positionen).", len(data.get("holdings", [])))
        return {"status": "success", "message": "Portfolio in Cloud gespeichert"}
    except Exception as e:
        logger.error("Fehler beim Speichern des Depots: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/load-portfolio")
def load_portfolio():
    try:
        if os.path.exists(PORTFOLIO_FILE):
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        return {"holdings": [], "sparplaene": []}
    except Exception as e:
        logger.error("Fehler beim Laden des Depots: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# KURSABFRAGEN & BATCH-QUOTES
# ==========================================

def fetch_single_quote(identifier: str):
    clean_id = identifier.strip().upper()
    try:
        ticker = yf.Ticker(clean_id)
        hist = ticker.history(period="2d")
        if hist.empty:
            info = ticker.fast_info
            price = getattr(info, "last_price", None) or getattr(info, "regular_market_price", None)
            prev = getattr(info, "previous_close", None) or price
            cur = getattr(info, "currency", "EUR" if clean_id.endswith(".DE") else "USD")
            chg = (((price - prev) / prev) * 100) if prev and price else 0.0
            if price:
                return clean_id, {
                    "status": "success",
                    "price": round(float(price), 2),
                    "changePct": round(float(chg), 2),
                    "currency": cur
                }
            return clean_id, {"status": "not_found"}

        current_price = float(hist["Close"].iloc[-1])
        prev_close = float(hist["Close"].iloc[-2]) if len(hist) > 1 else current_price
        chg_pct = ((current_price - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0

        cur = "EUR" if clean_id.endswith(".DE") else "USD"
        try:
            cur = ticker.fast_info.currency or cur
        except Exception:
            pass

        return clean_id, {
            "status": "success",
            "price": round(current_price, 2),
            "changePct": round(chg_pct, 2),
            "currency": cur
        }
    except Exception as ex:
        logger.warning("Fehler bei Quote fuer %s: %s", clean_id, ex)
        return clean_id, {"status": "error", "message": str(ex)}

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

    return {
        "status": "ok",
        "count": len(results),
        "data": results
    }

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

    try:
        t = yf.Ticker(clean)
        info = t.info or {}
        fast = t.fast_info

        name = info.get("shortName") or info.get("longName") or clean
        cur = getattr(fast, "currency", None) or info.get("currency") or ("EUR" if clean.endswith(".DE") else "USD")
        price = getattr(fast, "last_price", None) or getattr(fast, "regular_market_price", None) or info.get("currentPrice")

        country = info.get("country", "Global")
        if country in ["United States", "US"]:
            country = "USA"
        elif country in ["Germany"]:
            country = "Deutschland"

        sector = info.get("sector", "Technologie")

        return {
            "status": "success",
            "name": name,
            "type": "Aktie" if not info.get("quoteType") == "ETF" else "ETF",
            "country": country,
            "currency": cur,
            "sector": sector,
            "price": round(float(price), 2) if price else None
        }
    except Exception as e:
        logger.warning("Quote-deep fehlgeschlagen fuer %s: %s", clean, e)
        raise HTTPException(status_code=500, detail=str(e))
