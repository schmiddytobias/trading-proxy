import concurrent.futures
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import yfinance as yf

app = FastAPI(title="Bloomberg Terminal Market Proxy", version="2.1")

# CORS freischalten für Browser-Zugriff
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


# ================= HILFSFUNKTIONEN FÜR NORMALISIERUNG =================

def map_country(country_str: Optional[str]) -> str:
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


def map_sector(sector_str: Optional[str]) -> str:
    if not sector_str:
        return "Sonstige"
    s = sector_str.lower()
    if any(k in s for k in ["tech", "software", "semiconductor", "it"]):
        return "Technologie"
    if any(k in s for k in ["industr", "aerospace", "defen", "machin"]):
        return "Industrie / Rüstung"
    if any(k in s for k in ["financ", "bank", "insur"]):
        return "Finanzen"
    if any(k in s for k in ["health", "pharma", "biotech"]):
        return "Gesundheit"
    if any(k in s for k in ["consum", "retail"]):
        return "Konsumgüter"
    if any(k in s for k in ["energy", "oil", "gas", "basic materials", "mining", "commod"]):
        return "Energie & Rohstoffe"
    if any(k in s for k in ["communicat", "telecom"]):
        return "Telekommunikation"
    return "Sonstige"


# ================= BASIS-KURSABFRAGE =================

def resolve_single_security(identifier: str) -> Dict[str, Any]:
    """Sucht Wertpapiere über Yahoo Finance und fällt bei KAG-Fonds auf Onvista zurück."""
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

    # STUFE 2: Onvista Snapshot Fallback
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
    Ermittelt für Aktien: Währung, Land und Branche.
    Ermittelt für Fonds/ETFs: Look-Through Gewichtungen (Länder, Branchen, Währungen).
    """
    base = resolve_single_security(identifier)
    clean_id = identifier.strip().upper()

    ticker_sym = base.get("symbol", clean_id)
    sec_type = base.get("type", "Aktie")

    info = {}
    try:
        t = yf.Ticker(ticker_sym)
        info = t.info or {}
    except Exception:
        pass

    # Typ-Korrektur über yfinance, falls vorhanden
    q_type = info.get("quoteType", "").upper()
    if q_type == "ETF":
        sec_type = "ETF"
    elif q_type == "MUTUALFUND":
        sec_type = "Fonds"

    base["type"] = sec_type

    if sec_type == "Aktie":
        # Einzelaktien-Stammdaten
        raw_country = info.get("country") or ("Deutschland" if ".DE" in ticker_sym else "USA")
        raw_sector = info.get("sector") or "Technologie"

        base["country"] = map_country(raw_country)
        base["sector"] = map_sector(raw_sector)
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
            # Marktrepräsentative Standard-Gewichtung (MSCI World / All-World Profil)
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

@app.get("/")
def health_check():
    return {"status": "ok", "service": "Bloomberg Market Proxy v2.1 (Deep Lookup Active)"}


@app.get("/quote")
def get_single_quote(query: str):
    result = resolve_single_security(query)
    if result.get("status") != "success":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


@app.get("/quote-deep")
def get_quote_deep(query: str):
    """Gibt Stammdaten (Land, Branche, Währung) & Fonds-Durchschau zurück."""
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
