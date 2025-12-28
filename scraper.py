# scraper.py
import asyncio, re, time, random
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from db import (
    get_db_session,
    Product,
    Price,
    SingleCard,
    SingleCardPrice,
    SingleCardOffer,
    upsert_daily,
    upsert_single_daily,
    PSA10Price,
    PSA10Offer,
)
from sqlalchemy import func
from cookie_loader import parse_netscape_cookies
from blocklist_manager import is_blocked
import logging
import json
import os

logger = logging.getLogger(__name__)

STATUS_FILE = "scraper_status.json"

def update_scraper_status(status: str, message: str):
    """Update the scraper status file."""
    try:
        data = {
            "status": status,
            "message": message,
            "timestamp": datetime.utcnow().isoformat()
        }
        # Write mostly atomic
        temp_file = STATUS_FILE + ".tmp"
        with open(temp_file, "w") as f:
            json.dump(data, f)
        os.rename(temp_file, STATUS_FILE)
    except Exception as e:
        logger.error(f"Failed to update scraper status: {e}")


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
    Returns up to 5 lowest euro prices.
    Strategy:
    1. Try to find prices from the specific `country_name`.
    2. If none found, fallback to ALL countries and return the cheapest.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("div.table.article-table.table-striped")
    if not table:
        # Fallback for empty/blocked pages or different layouts
        return []

    rows = table.select("div.article-row")
    
    country_matches = []
    other_matches = []

    for r in rows:
        # 1. Parse Price
        price_span = r.select_one(".col-offer .color-primary")
        if not price_span:
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
        except ValueError:
            continue

        # 2. Parse Country
        loc = r.select_one(".col-seller [aria-label^='Item location:']")
        loc_country = None
        if loc and loc.has_attr("aria-label"):
            lab = loc["aria-label"]
            if ":" in lab:
                loc_country = lab.split(":", 1)[1].strip()
        
        if loc_country == country_name:
            country_matches.append(price)
        else:
            other_matches.append(price)

    # Strategy: Prioritize target country, fallback to global cheapest
    if country_matches:
        country_matches.sort()
        return country_matches[:5]
    
    if other_matches:
        other_matches.sort()
        # Fallback: return cheapest from any country
        return other_matches[:5]

    return []


def parse_single_card_offers(html: str, language: str, is_sealed: bool = False):
    """Return up to 20 lowest offers with details (seller, price, country).
    
    Returns list of dicts: {'seller': str, 'price': float, 'country': str}
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("div.table.article-table.table-striped")
    rows = table.select("div.article-row") if table else soup.select("div.article-row")
    if not rows:
        return []
        
    offers = []
    lang_norm = language.strip().lower()
    
    for r in rows:
        # 1. Condition Check
        if not is_sealed:
            badge = r.select_one(".article-condition .badge")
            cond = badge.get_text(strip=True).lower() if badge else None
            if cond not in {"nm", "m"}:
                continue
        
        # 2. Language Check
        lang_icon = r.select_one(
            ".product-attributes .icon[data-bs-original-title], .product-attributes .icon[aria-label]"
        )
        lang_text = None
        if lang_icon:
            lang_text = lang_icon.get("data-bs-original-title") or lang_icon.get("aria-label")
        if not lang_text or lang_norm not in lang_text.lower():
            continue

        # 3. Price
        price_span = r.select_one(".col-offer .color-primary") or r.select_one(
            ".mobile-offer-container .color-primary"
        )
        if not price_span:
            continue
        m = PRICE_RE.search(price_span.get_text(strip=True))
        if not m:
            continue
        try:
            raw_price = float(m.group(1).replace(".", "").replace(",", "."))
        except ValueError:
            continue

        # 4. Seller & Country
        seller_name = "Unknown"
        country = None
        
        # Seller name is usually in the first anchor of col-seller or just text
        seller_elem = r.select_one(".col-seller a") or r.select_one(".col-seller")
        if seller_elem:
           seller_name = seller_elem.get_text(strip=True)
           
        # Country is often in aria-label of an icon in col-seller
        loc_elem = r.select_one(".col-seller .icon[aria-label^='Item location']")
        if loc_elem:
            label = loc_elem.get("aria-label", "")
            if ":" in label:
                country = label.split(":", 1)[1].strip()

        offers.append({
            "seller": seller_name,
            "price": raw_price,
            "country": country
        })

        if len(offers) >= 20:
             break

    # Sort by price ascending
    offers.sort(key=lambda x: x["price"])
    return offers


def parse_single_card_summary(html: str):
    """Extract headline pricing data from the Cardmarket single card page."""

    def extract(label: str):
        soup_dt = soup.find(
            "dt",
            string=lambda s: bool(s)
            and label.lower() in s.strip().lower(),
        )
        if not soup_dt:
            return None
        dd = soup_dt.find_next_sibling("dd")
        if not dd:
            return None
        m = PRICE_RE.search(dd.get_text(" ", strip=True))
        if not m:
            return None
        try:
            return float(m.group(1).replace(".", "").replace(",", "."))
        except ValueError:
            return None

    soup = BeautifulSoup(html, "lxml")
    soup = BeautifulSoup(html, "lxml")
    return {
        "from_price": extract("from"),
        "price_trend": extract("price trend"),
        "avg7": extract("7-day"),
        "avg1": extract("1-day"),
    }

def process_psa10_data(session, card, html):
    """Parse and save PSA10 offers from the expanded HTML."""
    soup = BeautifulSoup(html, 'html.parser')
    rows = soup.select("div.article-row")
    
    psa10_offers = []
    lowest_price = None

    for row in rows:
        comment_col = row.select_one(".product-comments")
        comment_text = comment_col.get_text(strip=True) if comment_col else ""
        text_lower = comment_text.lower()
        
        if "psa10" in text_lower or "psa 10" in text_lower or "psa-10" in text_lower:
            price_elem = row.select_one(".col-offer .color-primary") or row.select_one(".price-container .color-primary")
            if not price_elem:
                continue
            
            price_str = price_elem.get_text(strip=True).replace("€", "").replace(".", "").replace(",", ".").strip()
            try:
                price = float(price_str)
            except ValueError:
                continue
            
            seller_elem = row.select_one(".col-seller a") or row.select_one(".col-seller")
            seller = seller_elem.get_text(strip=True) if seller_elem else "Unknown"
            
            psa10_offers.append({
                "seller": seller,
                "price": price,
                "comment": comment_text
            })

            if lowest_price is None or price < lowest_price:
                lowest_price = price
    
    psa10_found = len(psa10_offers) > 0
    # We log this summary inside the main loop or here? Let's log here for clarity.
    # But current logic has 'summary' variable in main loop printed? No, we print explicit summary line.
    logger.info(f"[{card.name}] PSA10 Summary: Found: {'Yes' if psa10_found else 'No'} ({len(psa10_offers)} offers). Low: {lowest_price}")

    if psa10_offers:
        # Clear old offers
        session.query(PSA10Offer).filter(PSA10Offer.card_id == card.id).delete()
        
        # Add new offers
        for offer in psa10_offers:
            db_offer = PSA10Offer(
                card_id=card.id,
                seller_name=offer["seller"],
                price=offer["price"],
                comment=offer["comment"]
            )
            session.add(db_offer)
        
        # Add Price History (if we have a low)
        if lowest_price is not None:
            db_price = PSA10Price(
                card_id=card.id,
                low=lowest_price
            )
            session.add(db_price)
        session.commit()

async def fetch_page(context, url: str, expand_results: bool = False, card_name: str = None) -> str:
    page = await context.new_page()

    # Data Usage Tracking
    total_data_bytes = 0
    async def track_data(response):
        nonlocal total_data_bytes
        try:
            # Fallback: Content-Length header (fast)
            length = int(response.headers.get('content-length', 0))
            if length == 0:
                # If header missing/zero (chunked/gzipped), try getting body size
                # Note: this might slightly slow down if bodies are huge, but we blocked huge things.
                try:
                    body = await response.body()
                    length = len(body)
                except Exception:
                    pass 
            total_data_bytes += length
        except Exception:
            pass
        
        if response.status in [403, 429]:
            logger.warning(f"[{card_name or 'Unknown'}] Network error: {response.status} {response.url}")

    page.on("response", track_data)

    # BLOCK Resource Types & Tracking to save bandwidth
    import re
    # Patterns for common trackers/analytics/ads
    TRACKING_REGEX = re.compile(r"(google-analytics|googletagmanager|facebook|doubleclick|twitter|criteo|hotjar|bing|pinterest|tiktok|snapchat|linkedin|ads|analytics|tracker)", re.IGNORECASE)

    await page.route("**/*", lambda route: route.abort() 
        if route.request.resource_type in ["image", "stylesheet", "font", "media"] or TRACKING_REGEX.search(route.request.url)
        else route.continue_()
    )
    # cardmarket often requires login to buy, but listing/prices are visible
    resp = await page.goto(url, wait_until="networkidle", timeout=60_000)
    
    # Handle "Show more results" if requested
    if expand_results:
            show_more_clicked = False
            click_count = 0
            # Limit to ~300 results (50 per load -> 6 clicks)
            MAX_CLICKS = 6
            
            # Initial count
            initial_rows = await page.locator("div.article-row").count()
            current_rows = initial_rows
            
            while True:
                if click_count >= MAX_CLICKS:
                     if card_name:
                          logger.warning(f"[{card_name}] Max 'Show more' clicks ({MAX_CLICKS}) reached. Stopping expansion.")
                     break

                load_more = page.get_by_role("button", name="Show more results")
                if await load_more.is_visible():
                    # Wait longer before clicking (2.5 - 4.5s)
                    await page.wait_for_timeout(random.uniform(2500, 4500))

                    if not await load_more.is_enabled():
                        # If visible but disabled, maybe it's loading? Wait a bit.
                        await page.wait_for_timeout(2000)
                        if not await load_more.is_enabled():
                             logger.warning(f"[{card_name}] 'Show more' button is disabled. Stopping.")
                             break

                    click_count += 1
                    if card_name:
                         logger.info(f"[{card_name}] Clicking 'Show more results' (merged query, click {click_count})...")
                    show_more_clicked = True
                    try:
                        await load_more.click(timeout=8000)
                    except Exception:
                        try:
                            await page.evaluate("(btn) => btn.click()", await load_more.element_handle())
                        except Exception:
                            logger.warning(f"[{card_name}] Failed to click 'Show more'. Stopping.")
                            break 
                    
                    # Wait longer for content to load (4 - 7s)
                    await page.wait_for_timeout(random.uniform(4000, 7000))
                    
                    try:
                        spinner = page.locator(".spinner, .loader")
                        if await spinner.count() > 0 and await spinner.first.is_visible():
                            # Increased timeout to 15s to assume it might be slow
                            await spinner.first.wait_for(state="hidden", timeout=15000)
                    except Exception as e:
                         # If spinner wait fails, just wait a bit more
                         await page.wait_for_timeout(2000)

                    # Check if we actually got more items
                    new_row_count = await page.locator("div.article-row").count()
                    if new_row_count <= current_rows:
                        logger.warning(f"[{card_name}] No new items loaded after clicking 'Show more' (Count: {new_row_count}). Stopping.")
                        break
                    
                    current_rows = new_row_count
                else:
                    break
            if card_name and show_more_clicked:
                 logger.info(f"[{card_name}] expanded results ({click_count} clicks).")

    # sometimes anti-bot banners appear; we rely on human-like delays + Chromium
    html = await page.content()
    
    # Check for blocking
    title = await page.title()
    if title == "www.cardmarket.com" or "Just a moment" in title:
        logger.error("Scraper blocked by Cloudflare")
        update_scraper_status("error", "Scraper is blocked by Cloudflare (Just a moment / Redirect). Cookies need update.")
    else:
        # If we successfully got a product page, clear error? 
        # Only if we are fairly sure. "Cardmarket" is generic, but product pages usually have the product name.
        if "Cardmarket" in title and title != "www.cardmarket.com":
             update_scraper_status("ok", "Scraper is running normally.")
        
    kb_used = total_data_bytes / 1024
    if card_name:
        logger.info(f"[{card_name}] Page Size: {kb_used:.2f} KB")

    await page.close()
    return html

async def scrape_once(product_ids=None):
    """Scrape prices for enabled sealed products.

    If ``product_ids`` is provided, only those product ids will be scraped.
    """
    from db import get_session, Product, Price
    print(f"[scraper] Starting scrape run at {datetime.utcnow():%Y-%m-%d %H:%M:%S}")

    with get_db_session() as session:
        q = session.query(Product).filter_by(is_enabled=1)
        if product_ids:
            q = q.filter(Product.id.in_(product_ids))
        products = q.all()

        if not products:
            logger.info("No enabled products found. Nothing to scrape.")
            return

        # Avoid hitting the website twice for the same product within the
        # configured window. We look up the latest scrape timestamp in bulk
        # so we only need one query for all products.
        cutoff = datetime.utcnow() - timedelta(minutes=45)
        latest_rows = (
            session.query(Price.product_id, func.max(Price.ts))
            .filter(Price.product_id.in_([p.id for p in products]))
            .group_by(Price.product_id)
            .all()
        )
        last_seen = {pid: ts for pid, ts in latest_rows if ts is not None}
        # Sort by last_seen to prioritize "oldest update first" (resume behavior)
        default_ts = datetime.min
        products = [p for p in products if last_seen.get(p.id, cutoff - timedelta(seconds=1)) < cutoff]
        products.sort(key=lambda p: last_seen.get(p.id, default_ts))

    if not products:
        logger.info("Skipping sealed scrape: all products fetched recently")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            extra_http_headers={"Referer": "https://www.cardmarket.com/"}
        )
        try:
            cookies = parse_netscape_cookies("cookies-cardmarket-com.txt")
            cf_clearance = {
                "name": "cf_clearance",
                "value": "h2wrFuqEEa.5iDLkOpZPs8DAVlo5qRcvbBQ1iSyrFoQ-1765547636-1.2.1.1-Q4t2zwopbqf5jblLRLdH4uC.LjH.YpEIk4uXEfb8arzACQ9WXTQHfB39zUnjOZDJrA6CZ1PXu_WRVTKxrehSCzrxwjgSV1XziLqbBxFyhTJ9SW0Ic2IrT5Vng9QpU7ZztKPdvGwat9PjegGaePjTRDq30uhQuYc6O1UM_BrC5iqPMQ7UoobQegRUH4XxVnP6hTXPBsN.txeH35bs5hCyLAQ5wSgzlCayi4MU3uE_obg",
                "domain": ".cardmarket.com",
                "path": "/",
                "secure": True
            }
            cookies.append(cf_clearance)
            await context.add_cookies(cookies)
        except Exception as e:
            logger.error(f"Failed to load cookies: {e}")
        

        for prod in products:
            if is_blocked(product_id=prod.id, url=prod.url):
                 logger.info(f"Skipping blocked product: {prod.name} (ID: {prod.id})")
                 continue
            
            logger.info(f"Fetching prices for {prod.name} ({prod.country})")
            start = time.time()
            try:
                # Add language filter for sealed English products to avoid French/Italian items
                target_url = prod.url
                if "japanese" not in prod.name.lower() and " jp" not in prod.name.lower():
                    sep = "&" if "?" in target_url else "?"
                    target_url += f"{sep}language=1"

                html = await fetch_page(context, target_url)
                prices = parse_prices_for_country(html, prod.country)
                supply = parse_supply(html)
                if prices:
                    low = min(prices)
                    avg = sum(prices) / len(prices)
                    with get_db_session() as s:
                        s.add(Price(product_id=prod.id, low=low, avg5=avg,
                                    n_seen=len(prices), supply=supply))
                        s.commit()
                        upsert_daily(s, prod.id)
                    logger.info(f"Stored {len(prices)} prices: low={low:.2f}, avg5={avg:.2f}, supply={supply}")
                else:
                    logger.warning("No prices found")
            except Exception as e:
                logger.error(f"Error while processing {prod.name}: {e}")
            finally:
                elapsed = time.time() - start
                remain = max(0, random.uniform(10, 20) - elapsed)
                await asyncio.sleep(remain)
        
        await context.close()
        await browser.close()

    logger.info(f"Scrape run finished at {datetime.utcnow():%Y-%m-%d %H:%M:%S}")





async def scrape_single_cards(card_ids=None):
    """Scrape single-card prices and headline stats."""
    logger.info(f"Starting single-card scrape at {datetime.utcnow():%Y-%m-%d %H:%M:%S}")

    with get_db_session() as session:
        # Filter enabled cards AND exclude those categorized as "Ignore" or "Don"
        q = session.query(SingleCard).filter(
            SingleCard.is_enabled == 1,
            (SingleCard.category.notin_(["Ignore", "Don"])) | (SingleCard.category.is_(None))
        )
        if card_ids:
            q = q.filter(SingleCard.id.in_(card_ids))
        cards = q.all()

        if not cards:
            logger.info("No enabled single cards found. Nothing to scrape.")
            return

        cutoff = datetime.utcnow() - timedelta(minutes=45)
        latest_rows = (
            session.query(SingleCardPrice.card_id, func.max(SingleCardPrice.ts))
            .filter(SingleCardPrice.card_id.in_([c.id for c in cards]))
            .group_by(SingleCardPrice.card_id)
            .all()
        )
        last_seen = {cid: ts for cid, ts in latest_rows if ts is not None}
        # Sort by last_seen to prioritize "oldest update first" (resume behavior)
        default_ts = datetime.min
        cards = [c for c in cards if last_seen.get(c.id, cutoff - timedelta(seconds=1)) < cutoff]
        cards.sort(key=lambda c: last_seen.get(c.id, default_ts))

    if not cards:
        logger.info("Skipping single-card scrape: all cards fetched recently")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            extra_http_headers={"Referer": "https://www.cardmarket.com/"}
        )
        try:
            cookies = parse_netscape_cookies("cookies-cardmarket-com.txt")
            cf_clearance = {
                "name": "cf_clearance",
                "value": "h2wrFuqEEa.5iDLkOpZPs8DAVlo5qRcvbBQ1iSyrFoQ-1765547636-1.2.1.1-Q4t2zwopbqf5jblLRLdH4uC.LjH.YpEIk4uXEfb8arzACQ9WXTQHfB39zUnjOZDJrA6CZ1PXu_WRVTKxrehSCzrxwjgSV1XziLqbBxFyhTJ9SW0Ic2IrT5Vng9QpU7ZztKPdvGwat9PjegGaePjTRDq30uhQuYc6O1UM_BrC5iqPMQ7UoobQegRUH4XxVnP6hTXPBsN.txeH35bs5hCyLAQ5wSgzlCayi4MU3uE_obg",
                "domain": ".cardmarket.com",
                "path": "/",
                "secure": True
            }
            cookies.append(cf_clearance)
            await context.add_cookies(cookies)
        except Exception as e:
            logger.error(f"Failed to load cookies: {e}")

        consecutive_errors = 0
        
        for card in cards:
            if consecutive_errors >= 3:
                logger.error("Too many consecutive errors (likely blocked). Cooling down for 60 minutes...")
                await asyncio.sleep(3600)
                consecutive_errors = 0 # Reset after cooling down, or should we break? Let's reset and try one more time or just continue slowly.
                # Actually, maybe better to just break this run?
                # But looking at requirements, 'paused' is better.
            
            if is_blocked(product_id=card.product_id, url=card.url):
                 logger.info(f"Skipping blocked card: {card.name} (ID: {card.product_id})")
                 continue

            if "Don!!" in card.name:
                 logger.info(f"Skipping Don card: {card.name}")
                 continue

            logger.info(
                f"Fetching single card {card.name} ({card.language}, {card.condition})"
            )
            start = time.time()
            try:
                # Add language filter param for better pre-filtering
                target_url = card.url
                if card.language == "English":
                    sep = "&" if "?" in target_url else "?"
                    target_url += f"{sep}language=1"

                # Check if we need to do PSA10 expansion (Merged Query)
                is_liked = (card.category == 'Liked')
                
                html = await fetch_page(context, target_url, expand_results=is_liked, card_name=card.name)
                
                # Determine if this is a sealed product (Booster Box, Pack, etc.)
                # We skip condition checks for these.
                cat_lower = (card.category or "").lower()
                is_sealed = "booster" in cat_lower or "pack" in cat_lower or "display" in cat_lower
                
                offers = parse_single_card_offers(html, card.language, is_sealed=is_sealed)
                prices = [o["price"] for o in offers]
                
                summary = parse_single_card_summary(html)
                supply = parse_supply(html)

                if prices or any(v is not None for v in summary.values()):
                    consecutive_errors = 0 # Success!
                    
                    # Always derive chart points from the scraped listings so the
                    # low/avg lines match the table rows shown on the website.
                    low = min(prices) if prices else None
                    # Use top 5 for average consistency with old logic
                    top5 = prices[:5]
                    avg = sum(top5) / len(top5) if top5 else None
                    
                    with get_db_session() as s:
                        # 1. Save Stats History (SingleCardPrice)
                        s.add(
                            SingleCardPrice(
                                card_id=card.id,
                                low=low,
                                avg5=avg,
                                n_seen=len(prices) if prices else None,
                                supply=supply,
                                from_price=summary.get("from_price"),
                                price_trend=summary.get("price_trend"),
                                avg7_price=summary.get("avg7"),
                                avg1_price=summary.get("avg1"),
                            )
                        )
                        
                        # 2. Update Offers (SingleCardOffer)
                        # Clear old offers for this card
                        s.query(SingleCardOffer).filter_by(card_id=card.id).delete()
                        
                        # Insert new offers
                        for o in offers:
                            s.add(SingleCardOffer(
                                card_id=card.id,
                                seller_name=o["seller"],
                                price=o["price"],
                                country=o["country"]
                            ))

                        s.commit()
                        upsert_single_daily(s, card.id)
                        
                        # 3. Process PSA10 if applicable (merged in same session)
                        if is_liked:
                             process_psa10_data(s, card, html)

                    logger.info(
                        f"Stored single card stats (low={low}, avg5={avg}, supply={supply})"
                    )
                else:
                    logger.warning("No prices found for single card")
                    consecutive_errors += 1
            except Exception as e:
                logger.error(f"Error while processing {card.name}: {e}")
                consecutive_errors += 1
            finally:
                elapsed = time.time() - start
                remain = max(0, random.uniform(20, 30) - elapsed)
                await asyncio.sleep(remain)

        await context.close()
        await browser.close()

    logger.info(
        f"Single-card scrape finished at {datetime.utcnow():%Y-%m-%d %H:%M:%S}"
    )


async def scrape_all(product_ids=None, single_card_ids=None):
    await scrape_once(product_ids)
    await scrape_single_cards(single_card_ids)

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


def compute_single_trend(session, card_id: int, lookback_days: int = 7):
    """Trend for individual cards using the dedicated daily table."""
    from db import SingleCardDaily

    rows = (
        session.query(SingleCardDaily)
        .filter(SingleCardDaily.card_id == card_id)
        .order_by(SingleCardDaily.day.desc())
        .limit(lookback_days * 2)
        .all()
    )
    if len(rows) < lookback_days + 3:
        return "flat"
    recent = [r.avg for r in rows[:lookback_days] if r.avg is not None]
    prev = [r.avg for r in rows[lookback_days : lookback_days * 2] if r.avg is not None]
    if not prev or not recent:
        return "flat"
    r_avg = sum(recent) / len(recent)
    p_avg = sum(prev) / len(prev)
    delta = (r_avg - p_avg) / p_avg if p_avg else 0.0
    if delta > 0.03:
        return "up"
    if delta < -0.03:
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
# Dynamically schedule next run after completion
def run_and_reschedule(scheduler):
    try:
        logger.info("Starting scheduled scrape...")
        asyncio.run(scrape_all())
    except Exception as e:
        logger.error(f"Scrape job failed: {e}")
    finally:
        # Schedule next run 4 hours from NOW (completion time)
        next_run = datetime.utcnow() + timedelta(hours=4)
        logger.info(f"Scrape finished. Next run scheduled for {next_run} UTC")
        scheduler.add_job(
            lambda: run_and_reschedule(scheduler),
            "date",
            run_date=next_run
        )

# Fixed delay schedule (Wait 4h AFTER finish)
def schedule_hourly():
    logger.info("Starting scheduler (dynamic 4h delay after finish)")
    sched = BackgroundScheduler(timezone="UTC")
    
    # Start the first job immediately
    sched.add_job(
        lambda: run_and_reschedule(sched),
        "date",
        run_date=datetime.utcnow() + timedelta(seconds=10) # small buffer
    )
    
    sched.start()
    return sched

if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
    
    # Run continuous scheduler
    sched = schedule_hourly()
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        sched.shutdown()
