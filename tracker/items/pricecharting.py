import requests
from bs4 import BeautifulSoup

def fetch_pricecharting_prices(url):
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # PSA10 price (manual_only_price)
        psa10_price = None
        td_psa10 = soup.find("td", id="manual_only_price")
        if td_psa10:
            price_span = td_psa10.find("span", class_="price js-price")
            if price_span:
                s = price_span.get_text(strip=True)
                if s != "-":
                    psa10_price = float(s.replace("$", "").replace(",", ""))

        # Ungraded price (used_price)
        ungraded_price = None
        td_ungraded = soup.find("td", id="used_price")
        if td_ungraded:
            price_span = td_ungraded.find("span", class_="price js-price")
            if price_span:
                s = price_span.get_text(strip=True)
                if s != "-":
                    ungraded_price = float(s.replace("$", "").replace(",", ""))

        return {"psa10_usd": psa10_price, "ungraded_usd": ungraded_price}
    except Exception as e:
        print("Pricecharting scrape error:", e)
        return {}
