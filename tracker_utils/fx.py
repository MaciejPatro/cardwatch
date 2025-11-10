import json
import urllib.request
from datetime import datetime, timedelta
from threading import Lock


_CACHE_TTL = timedelta(minutes=30)
_cache = {}
_cache_lock = Lock()

def get_fx_rates(base="CHF"):
    # Only supports CHF, EUR, USD as target (add more logic if needed)
    now = datetime.utcnow()
    with _cache_lock:
        cached = _cache.get(base)
        if cached and now - cached["ts"] < _CACHE_TTL:
            return dict(cached["rates"])

    try:
        url = f"https://api.frankfurter.app/latest?from={base}&to=USD,EUR,CHF"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.load(resp)
        rates = data.get("rates", {})
    except Exception:
        rates = {
            "CHF": 1.0,
            "USD": 1.10,
            "EUR": 0.95,
            "PLN": 1.0,
        }

    rates[base] = 1.0
    rates.setdefault("PLN", 1.0)

    with _cache_lock:
        _cache[base] = {"rates": dict(rates), "ts": now}

    return dict(rates)
