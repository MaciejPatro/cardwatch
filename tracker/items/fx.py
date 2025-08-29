import requests

def get_fx_rates(base="CHF"):
    # Only supports CHF, EUR, USD as target (add more logic if needed)
    try:
        resp = requests.get(
            "https://api.frankfurter.app/latest",
            params={"from": base, "to": "USD,EUR,CHF"},
            timeout=10,
        )
        data = resp.json()
        # The API gives rates dict, always includes 'CHF', 'USD', 'EUR'
        rates = data.get("rates", {})
        # Ensure base is included as 1.0
        rates[base] = 1.0
        # For missing targets (e.g., PLN), just set dummy rate
        rates.setdefault("PLN", 1.0)
        return rates
    except Exception as e:
        # Fallback static rates in case of error
        return {
            "CHF": 1.0,
            "USD": 1.10,
            "EUR": 0.95,
            "PLN": 1.0
        }
