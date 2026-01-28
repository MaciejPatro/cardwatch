import json
import urllib.request
import os
import logging
from datetime import datetime, timedelta
from threading import Lock

# Configure logging
logger = logging.getLogger(__name__)

_CACHE_TTL = timedelta(minutes=30)
_cache = {}
_cache_lock = Lock()

FX_CACHE_FILE = "fx_cache.json"

def _load_from_disk(base):
    if not os.path.exists(FX_CACHE_FILE):
        return None
    try:
        with open(FX_CACHE_FILE, "r") as f:
            data = json.load(f)
            # Check if we have data for this base
            if base in data:
                return data[base]
    except Exception as e:
        logger.warning(f"Failed to load FX cache from disk: {e}")
    return None

def _save_to_disk(base, rates, timestamp):
    data = {}
    # Load existing data first to preserve other bases
    if os.path.exists(FX_CACHE_FILE):
        try:
            with open(FX_CACHE_FILE, "r") as f:
                data = json.load(f)
        except Exception:
            pass # Start fresh if file is corrupt
            
    data[base] = {
        "rates": rates,
        "ts": timestamp.isoformat()
    }
    
    try:
        with open(FX_CACHE_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.warning(f"Failed to save FX cache to disk: {e}")

def get_fx_rates(base="CHF"):
    # Only supports CHF, EUR, USD as target (add more logic if needed)
    now = datetime.utcnow()
    
    # 1. Memory Cache
    with _cache_lock:
        cached = _cache.get(base)
        if cached and now - cached["ts"] < _CACHE_TTL:
            return dict(cached["rates"])

    def _query_rates():
        url = f"https://api.frankfurter.app/latest?from={base}&to=USD,EUR,CHF"
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.load(resp)
        return data.get("rates", {})

    rates = None
    
    # 2. Try Fresh Query
    try:
        rates = _query_rates()
        # If successful, save to disk
        _save_to_disk(base, rates, now)
    except Exception as e:
        logger.error(f"FX API query failed for {base}: {e}")
        
        # 3. Fallback to Disk Cache (Ignore TTL if query failed)
        disk_data = _load_from_disk(base)
        if disk_data:
            logger.info(f"Using disk cache for {base} (timestamp: {disk_data.get('ts')})")
            rates = disk_data["rates"]
        else:
            # 4. Hardcoded Fallback
            logger.warning(f"Using hardcoded fallback rates for {base}")
            rates = {
                "CHF": 1.0,
                "USD": 1.10,
                "EUR": 0.95,
                "PLN": 1.0,
            }

    if rates:
        rates[base] = 1.0
        rates.setdefault("PLN", 1.0) # Ensure PLN exists

        with _cache_lock:
            _cache[base] = {"rates": dict(rates), "ts": now}
            
        return dict(rates)
    
    return {} # Should not happen given the fallback
