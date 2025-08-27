# scraper.py
import asyncio, re, time
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from db import get_session, Product, Price, upsert_daily
from sqlalchemy import func


PRICE_RE = re.compile(r"([\d.,]+)\s*€")

def parse_supply(html: str):
    """Extract total available items from page HTML.

    The Cardmarket detail page presents this as a definition list with a
    ``<dt>Available items</dt>`` followed by a ``<dd>`` containing the number.
    Parsing the DOM structure is more reliable than searching for the phrase
    "X available items" which may not exist when the count is zero.
    """
    soup = BeautifulSoup(html, "lxml")
    dt = soup.find("dt", string=lambda s: s and s.strip().lower() == "available items")
    if not dt:
        return None
    dd = dt.find_next_sibling("dd")
    if not dd:
        return None
    text = dd.get_text(strip=True)
    m = re.search(r"[\d.,]+", text)
    if not m:
        return None
    raw = m.group(0).replace(".", "").replace(",", "")
    try:
        return int(raw)
    except ValueError:
        return None

def parse_prices_for_country(html: str, country_name: str):
    """
    Returns up to 5 lowest euro prices for rows whose location tooltip says the given country.
    Uses provided DOM hints; robust to minor layout changes by querying by classes and spans.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("div.table.article-table.table-striped")
    if not table:
        return []

    rows = table.select("div.article-row")
    pairs = []
    for r in rows:
        # country: aria-label="Item location: Spain" is on an icon within seller column
        loc = r.select_one(".col-seller [aria-label^='Item location:']")
        loc_country = None
        if loc and loc.has_attr("aria-label"):
            lab = loc["aria-label"]
            if ":" in lab:
                loc_country = lab.split(":", 1)[1].strip()
        if loc_country != country_name:
            continue

        # price lives in .col-offer -> .color-primary with euro
        price_span = r.select_one(".col-offer .color-primary")
        if not price_span:
            # mobile fallback:
            price_span = r.select_one(".mobile-offer-container .color-primary")
        if not price_span:
            continue
        m = PRICE_RE.search(price_span.get_text(strip=True))
        if not m:
            continue

        # normalize "83,00 €" -> 83.00
        raw = m.group(1).replace(".", "").replace(",", ".")
        try:
            price = float(raw)
            pairs.append(price)
        except ValueError:
            continue

    pairs.sort()
    return pairs[:5]

async def fetch_page(context, url: str) -> str:
    page = await context.new_page()
    # cardmarket often requires login to buy, but listing/prices are visible
    resp = await page.goto(url, wait_until="networkidle", timeout=60_000)
    # sometimes anti-bot banners appear; we rely on human-like delays + Chromium
    html = await page.content()
    await page.close()
    return html

async def scrape_once(product_ids=None):
    """Scrape prices for enabled products.

    If ``product_ids`` is provided, only those product ids will be scraped.
    """
    from db import get_session, Product, Price
    print(f"[scraper] Starting scrape run at {datetime.utcnow():%Y-%m-%d %H:%M:%S}")

    session = get_session()
    try:
        q = session.query(Product).filter_by(is_enabled=1)
        if product_ids:
            q = q.filter(Product.id.in_(product_ids))
        products = q.all()
    finally:
        session.close()

    if not products:
        print("[scraper] No enabled products found. Nothing to scrape.")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ))
        for prod in products:
            print(f"[scraper] Fetching prices for {prod.name} ({prod.country})")
            start = time.time()
            try:
                html = await fetch_page(context, prod.url)
                prices = parse_prices_for_country(html, prod.country)
                supply = parse_supply(html)
                if prices:
                    low = min(prices)
                    avg = sum(prices) / len(prices)
                    s = get_session()
                    try:
                        s.add(Price(product_id=prod.id, low=low, avg5=avg,
                                    n_seen=len(prices), supply=supply))
                        s.commit()
                        upsert_daily(s, prod.id)
                    finally:
                        s.close()
                    print(f"[scraper] Stored {len(prices)} prices: low={low:.2f}, avg5={avg:.2f}, supply={supply}")
                else:
                    print("[scraper] No prices found")
                # 15s delay between websites
            except Exception as e:
                print(f"[scraper] Error while processing {prod.name}: {e}")
            finally:
                elapsed = time.time() - start
                remain = max(0, 15.0 - elapsed)
                await asyncio.sleep(remain)

        await context.close()
        await browser.close()
    print(f"[scraper] Scrape run finished at {datetime.utcnow():%Y-%m-%d %H:%M:%S}")

def compute_trend(session, product_id: int, lookback_days: int = 7):
    """
    Compare the latest 7 daily avgs to the prior 7. Return 'up' | 'down' | 'flat'.
    """
    from db import Daily
    rows = (session.query(Daily)
            .filter(Daily.product_id == product_id)
            .order_by(Daily.day.desc()).limit(14).all())
    if len(rows) < 10:
        return "flat"
    recent = [r.avg for r in rows[:7]]
    prev   = [r.avg for r in rows[7:14]]
    if not prev or not recent:
        return "flat"
    r_avg = sum(recent)/len(recent)
    p_avg = sum(prev)/len(prev)
    delta = (r_avg - p_avg) / p_avg if p_avg else 0.0
    if delta > 0.03:   # +3% or more
        return "up"
    if delta < -0.03:  # -3% or more
        return "down"
    return "flat"

def is_heads_up(session, product_id: int):
    """
    Heads-up if the latest hourly low is 10% under the 7-day daily average.
    """
    from db import Price, Daily
    latest = (session.query(Price)
              .filter(Price.product_id == product_id)
              .order_by(Price.ts.desc())
              .first())
    if not latest:
        return False, None, None

    # Average the latest seven daily rows. "LIMIT" on an aggregate query does
    # not restrict the rows considered by the aggregate itself, so we must
    # compute the average over a subquery containing just the most recent
    # seven values.
    subq = (session.query(Daily.avg)
            .filter(Daily.product_id == product_id)
            .order_by(Daily.day.desc())
            .limit(7)
            .subquery())
    avg7 = session.query(func.avg(subq.c.avg)).scalar()
    if avg7 is None:
        return False, latest.low, None
    return latest.low <= 0.90 * float(avg7), latest.low, float(avg7)

# Hourly schedule (at most once/hour)
def schedule_hourly():
    print("[scraper] Starting hourly scheduler")
    sched = BackgroundScheduler(timezone="UTC")
    # run once ASAP after start, then every hour
    sched.add_job(
        lambda: asyncio.run(scrape_once()),
        "interval",
        hours=1,
        next_run_time=datetime.utcnow(),  # <- immediate first run
        max_instances=1
    )
    sched.start()
    return sched

if __name__ == "__main__":
    import asyncio
    asyncio.run(scrape_once())
