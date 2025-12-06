import urllib.request
from bs4 import BeautifulSoup

def fetch_pricecharting_prices(url):
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        soup = BeautifulSoup(html, "html.parser")

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
