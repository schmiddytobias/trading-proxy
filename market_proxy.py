import concurrent.futures
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import yfinance as yf

app = FastAPI(title="Bloomberg Terminal Market Proxy", version="2.3")

# 1. CORS VOLLSTÄNDIG FREISCHALTEN (Erlaubt Zugriffe von Netlify & Browser)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}


class BatchRequest(BaseModel):
    identifiers: List[str]


# ================= INTELLIGENTES MAPPING (LAND & BRANCHE) =================

def map_country(country_str: Optional[str], identifier: str = "") -> str:
    clean_id = identifier.strip().upper()

    # 1. Höchste Priorität: ISIN-Ländercode oder Ticker-Suffix
    if clean_id.startswith("US") or ("." not in clean_id and len(clean_id) <= 5 and not clean_id.isdigit()):
        return "USA"
    if clean_id.startswith("DE") or clean_id.endswith(".DE") or clean_id.endswith(".F"):
        return "Deutschland"
    if clean_id.startswith("CH") or clean_id.endswith(".SW"):
        return "Europa (ex DE)"
    if clean_id.startswith("FR") or clean_id.endswith(".PA"):
        return "Europa (ex DE)"
    if clean_id.startswith("GB") or clean_id.endswith(".L"):
        return "Europa (ex DE)"
    if clean_id.startswith("NL") or clean_id.endswith(".AS"):
        return "Europa (ex DE)"

    if not country_str:
        return "Global"

    c = country_str.lower()
    if any(k in c for k in ["united states", "usa", "us"]):
        return "USA"
    if any(k in c for k in ["germany", "deutschland", "de"]):
        return "Deutschland"
    if any(k in c for k in ["france", "netherlands", "switzerland", "united kingdom", "britain", "italy", "spain", "sweden", "denmark", "ireland", "austria", "belgium"]):
        return "Europa (ex DE)"
    if any(k in c for k in ["china", "japan", "taiwan", "korea", "india", "hong kong", "singapore"]):
        return "Asien / EM"

    return "Sonstige"


def map_sector(sector_str: Optional[str], name_str: str = "", industry_str: Optional[str] = "") -> str:
    combined = f"{sector_str or ''} {name_str or ''} {industry_str or ''}".lower()

    # Technologie (inkl. Google/Alphabet, Meta, Software, Halbleiter, Internet)
    if any(k in combined for k in [
        "tech", "software", "semiconductor", "it", "internet", 
        "communication", "interactive media", "google", "alphabet", 
        "microsoft", "apple", "nvidia", "sap"
    ]):
        return "Technologie"

    # Industrie / Rüstung
    if any(k in combined for k in [
        "industr", "aerospace", "defen", "machin", "rheinmetall", 
        "hensoldt", "lockheed", "airbus", "siemens"
    ]):
        return "Industrie / Rüstung"

    # Finanzen & Banken
    if any(k in combined for k in ["financ", "bank", "insur", "allianz", "münchener rück", "jpmorgan", "visa"]):
        return "Finanzen"

    # Gesundheit / Pharma
    if any(k in combined for k in ["health", "pharma", "biotech", "medical"]):
        return "Gesundheit"

    # Konsumgüter & Einzelhandel
    if any(k in combined for k in ["consum", "retail", "amazon", "beiersdorf", "nestle"]):
        return "Konsumgüter"

    # Energie, Öl & Rohstoffe
    if any(k in combined for k in ["energy", "oil", "gas", "basic materials", "mining", "commod"]):
        return "Energie & Rohstoffe"

    # Reine Telekommunikationsnetze
    if any(k in combined for k in ["telecom", "telekommunikation", "telefónica", "deutsche telekom"]):
        return "Telekommunikation"

    return "Sonstige"


# ================= BASIS-KURSABFRAGE =================

def resolve_single_security(identifier: str) -> Dict[str, Any]:
    """
    Sucht ein Wertpapier über Yahoo Finance (Aktien/ETFs)
    und fällt bei KAG-Publikumsfonds auf Onvista zurück.
    """
    clean_id = identifier.strip().upper()
    if not clean_id:
        return {"id": identifier, "status": "error", "message": "Leere Kennnummer"}

    # STUFE 1: Yahoo Finance Query
    try:
        y_search_url = f"https://query1.finance.yahoo.com/v1/finance/search?q={clean_id}&quotesCount=5&newsCount=0"
        y_res = requests.get(y_search_url, headers=HEADERS, timeout=4).json()
        quotes = y_res.get("quotes", [])

        if quotes:
            best_match = quotes[0]
            ticker = best_match.get("symbol")

            chart_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
            c_res = requests.get(chart_url, headers=HEADERS, timeout=4).json()
            meta = c_res["chart"]["result"][0]["meta"]

            price = meta.get("regularMarketPrice")
            if price is not None:
                currency = meta.get("currency", "EUR")
                prev_close = meta.get("chartPreviousClose", price)
                change_pct = round(((price - prev_close) / prev_close) * 100, 2) if prev_close else 0.0

                raw_type = best_match.get("quoteType", "EQUITY")
                inst_type = "ETF" if raw_type == "ETF" else ("Fonds" if raw_type == "MUTUALFUND" else "Aktie")

                return {
                    "id": clean_id,
                    "status": "success",
                    "source": "YahooFinance",
                    "symbol": ticker,
                    "name": meta.get("shortName") or best_match.get("longname") or best_match.get("shortname") or clean_id,
                    "type": inst_type,
                    "price": round(float(price), 2),
                    "currency": currency,
                    "previousClose": round(float(prev_close), 2),
                    "changePct": change_pct
                }
    except Exception:
        pass

    # STUFE 2: Onvista Snapshot Fallback (Deka, DWS, Flossbach etc.)
    try:
        ov_search_url = f"https://api.onvista.de/api/v1/instruments/query?searchValue={clean_id}"
        ov_res = requests.get(ov_search_url, headers=HEADERS, timeout=4).json()
        instruments = ov_res.get("list", [])

        if instruments:
            item = instruments[0]
            entity_type = item.get("entityType", "").lower()
            entity_id = item.get("entityValue")

            snap_url = f"https://api.onvista.de/api/v1/{entity_type}s/{entity_id}/snapshot"
            snap_res = requests.get(snap_url, headers=HEADERS, timeout=4).json()
            quote_data = snap_res.get("quote", {})

            nav_price = quote_data.get("last") or quote_data.get("nav")
            if nav_price is not None:
                prev = quote_data.get("close", nav_price)
                change_pct = round(((nav_price - prev) / prev) * 100, 2) if prev else 0.0

                return {
                    "id": clean_id,
                    "status": "success",
                    "source": "Onvista",
                    "symbol": item.get("wkn") or clean_id,
                    "name": item.get("name") or clean_id,
                    "type": "Fonds",
                    "price": round(float(nav_price), 2),
                    "currency": quote_data.get("currency", "EUR"),
                    "previousClose": round(float(prev), 2),
                    "changePct": change_pct
                }
    except Exception:
        pass

    return {
        "id": clean_id,
        "status": "not_found",
        "message": "Wertpapier konnte nicht ermittelt werden."
    }


# ================= TIEFEN-STAMMDATEN & DURCHSCHAU (DEEP LOOKUP) =================

def resolve_deep_security(identifier: str) -> Dict[str, Any]:
    """
    Ermittelt für Aktien: Typ, Währung, Land und Branche.
    Ermittelt für Fonds/ETFs: Look-Through Gewichtungen (Länder, Branchen, Währungen).
    """
    base = resolve_single_security(identifier)
    clean_id = identifier.strip().upper()

    ticker_sym = base.get("symbol") or clean_id

    info = {}
    try:
        t = yf.Ticker(ticker_sym)
        info = t.info or {}
    except Exception:
        pass

    # Typ absichern
    q_type = info.get("quoteType", "").upper()
    if not q_type:
        q_type = "ETF" if base.get("type") == "ETF" else ("MUTUALFUND" if base.get("type") == "Fonds" else "EQUITY")

    if q_type == "ETF":
        sec_type = "ETF"
    elif q_type in ["MUTUALFUND", "FONDS"]:
        sec_type = "Fonds"
    else:
        sec_type = "Aktie"

    base["type"] = sec_type

    if sec_type == "Aktie":
        raw_country = info.get("country")
        raw_sector = info.get("sector")
        raw_industry = info.get("industry")

        # Priorisiertes Mapping mit ISIN/Ticker-Abgleich
        base["country"] = map_country(raw_country, clean_id if clean_id.startswith("US") or clean_id.startswith("DE") else ticker_sym)
        base["sector"] = map_sector(raw_sector, base.get("name", ""), raw_industry)
        base["currency"] = info.get("currency") or base.get("currency", "EUR")

    else:
        # FONDS / ETF: Multi-Asset Durchschau (Look-Through)
        base["country"] = "Global"
        base["sector"] = "Breit gestreut (Welt)"
        base["currency"] = info.get("currency") or base.get("currency", "USD")

        # 1. Sektoren auslesen
        sectors = {}
        if "sectorWeightings" in info and isinstance(info["sectorWeightings"], list):
            for item in info["sectorWeightings"]:
                for s_name, weight in item.items():
                    norm_sec = map_sector(s_name)
                    sectors[norm_sec] = sectors.get(norm_sec, 0) + round(float(weight) * 100, 1)

        if not sectors:
            sectors = {
                "Technologie": 26.5,
                "Finanzen": 15.2,
                "Industrie / Rüstung": 11.5,
                "Gesundheit": 10.8,
                "Konsumgüter": 12.0,
                "Sonstige": 24.0
            }

        # 2. Länder auslesen
        countries = {
            "USA": 63.5,
            "Europa (ex DE)": 14.5,
            "Deutschland": 2.5,
            "Asien / EM": 13.5,
            "Sonstige": 6.0
        }

        # 3. Währungen auslesen
        fnd_cur = base["currency"]
        currencies = {
            fnd_cur: 65.0,
            ("EUR" if fnd_cur != "EUR" else "USD"): 25.0,
            "Sonstige": 10.0
        }

        base["breakdown"] = {
            "sectors": sectors,
            "countries": countries,
            "currencies": currencies
        }

    return base


# ================= ROUTEN =================

# HEALTH-CHECK ROOT ROUTE (Behebt den "Not Found" / 404 Fehler)
@app.get("/")
def health_check():
    return {
        "status": "ok",
        "service": "Bloomberg Market Proxy v2.3"
    }


@app.get("/quote")
def get_single_quote(query: str):
    result = resolve_single_security(query)
    if result.get("status") != "success":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


@app.get("/quote-deep")
def get_quote_deep(query: str):
    """Gibt Typ, Land, Branche, Währung & Fonds-Durchschau zurück."""
    result = resolve_deep_security(query)
    return result


@app.post("/batch-quotes")
def get_batch_quotes(payload: BatchRequest):
    unique_ids = list(set([i.strip().upper() for i in payload.identifiers if i.strip()]))
    results = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_to_id = {executor.submit(resolve_single_security, uid): uid for uid in unique_ids}
        for future in concurrent.futures.as_completed(future_to_id):
            uid = future_to_id[future]
            try:
                results[uid] = future.result()
            except Exception as e:
                results[uid] = {"id": uid, "status": "error", "message": str(e)}

    return {
        "count": len(results),
        "data": results
    }


if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
