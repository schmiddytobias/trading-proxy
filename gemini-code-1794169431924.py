import concurrent.futures
from typing import List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests

app = FastAPI(title="Bloomberg Terminal Market Proxy", version="2.0")

# CORS freischalten, damit das Web-Dashboard aus dem Browser ungehindert zugreifen darf
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


def resolve_single_security(identifier: str) -> Dict[str, Any]:
    """
    Sucht ein Wertpapier über Yahoo Finance (Aktien/ETFs)
    und fällt bei KAG-Publikumsfonds auf Onvista zurück.
    """
    clean_id = identifier.strip().upper()
    if not clean_id:
        return {"id": identifier, "status": "error", "message": "Leere Kennnummer"}

    # STUFE 1: Yahoo Finance Query (Aktien, ETFs, US-/EU-Titel)
    try:
        y_search_url = f"https://query1.finance.yahoo.com/v1/finance/search?q={clean_id}&quotesCount=5&newsCount=0"
        y_res = requests.get(y_search_url, headers=HEADERS, timeout=4).json()
        quotes = y_res.get("quotes", [])

        if quotes:
            best_match = quotes[0]
            ticker = best_match.get("symbol")

            # Chart-Endpunkt für Realtime-/Delayed-Kurs und Stammdaten
            chart_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
            c_res = requests.get(chart_url, headers=HEADERS, timeout=4).json()
            meta = c_res["chart"]["result"][0]["meta"]

            price = meta.get("regularMarketPrice")
            if price is not None:
                currency = meta.get("currency", "EUR")
                prev_close = meta.get("chartPreviousClose", price)
                change_pct = round(((price - prev_close) / prev_close) * 100, 2) if prev_close else 0.0

                raw_type = best_match.get("quoteType", "EQUITY")
                inst_type = "ETF" if raw_type == "ETF" else ("MUTUAL_FUND" if raw_type == "MUTUALFUND" else "Aktie")

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

    # STUFE 2: Onvista Snapshot Fallback (Deka, DWS, Flossbach, Union Investment etc.)
    try:
        ov_search_url = f"https://api.onvista.de/api/v1/instruments/query?searchValue={clean_id}"
        ov_res = requests.get(ov_search_url, headers=HEADERS, timeout=4).json()
        instruments = ov_res.get("list", [])

        if instruments:
            item = instruments[0]
            entity_type = item.get("entityType", "").lower()
            entity_id = item.get("entityValue")

            # Zieht den aktuellen KAG-Rücknahmepreis (NAV)
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


# ================= ROUTEN =================

@app.get("/")
def health_check():
    """Health-Check für Render und Uptime-Monitore."""
    return {"status": "ok", "service": "Bloomberg Market Proxy"}


@app.get("/quote")
def get_single_quote(query: str):
    """Einzelabfrage für die WKN/ISIN-Eingabemaske."""
    result = resolve_single_security(query)
    if result.get("status") != "success":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


@app.post("/batch-quotes")
def get_batch_quotes(payload: BatchRequest):
    """Parallele Batch-Abfrage für das gesamte Depot auf einen Schlag."""
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
    # Port dynamisch für Render Cloud oder lokal 8000
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("market_proxy:app", host="0.0.0.0", port=port, reload=False)