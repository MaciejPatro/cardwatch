import argparse
import json
import os
import time
import requests
import uuid
import asyncio
import base64
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from cookie_loader import parse_netscape_cookies
from scraper import update_scraper_status
from db import get_db_session, SingleCard, init_db
from blocklist_manager import is_blocked
from tracker_utils.url_utils import clean_url
from config import Config

# Ensure DB is initialized
init_db()

PRICE_GUIDE_URL = "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_22.json"
DEFAULT_FILENAME = "price_guide_22.json"
IMAGE_DIR = os.path.join(Config.MEDIA_ROOT, "single_card_images")

def download_file(url, filename):
    print(f"Downloading {url} to {filename}...")
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    print("Download complete.")

async def get_card_details(context, product_id, check_url_callback=None, delay=2.0):
    """
    Scrapes the Cardmarket product page for details using Playwright.
    Returns: (name, image_url, language, image_content)
    """
    # Assumption: Game name in URL is 'Riftbound'. If this fails, user might need to correct it.
    url = f"https://www.cardmarket.com/en/Riftbound/Products?idProduct={product_id}"
    print(f"Scraping {url}...")
    
    await asyncio.sleep(delay)
    
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        
        # Check for blocking
        title = await page.title()
        if title == "www.cardmarket.com" or "Just a moment" in title:
            print("[ERROR] Blocked by Cloudflare.")
            update_scraper_status("error", "Import script was blocked by Cloudflare. Cookies need update.")
        else:
            if "Cardmarket" in title and title != "www.cardmarket.com":
                 update_scraper_status("ok", "Import script running normally.")
        
        final_url = clean_url(page.url)
        if "Starter-Deck" in final_url or "Structure-Deck" in final_url:
             print(f"Skipping (Starter Deck URL): {final_url}")
             await page.close()
             return None

        # Optimization: Check if this final URL already exists in DB
        if check_url_callback and check_url_callback(final_url):
            print(f"Skipping (Already exists via URL check): {final_url}")
            await page.close()
            return None

        content = await page.content()
    except Exception as e:
        print(f"Failed to fetch page: {e}")
        await page.close()
        return None

    soup = BeautifulSoup(content, 'html.parser')
    
    # 1. Extract Name
    h1 = soup.find('h1')
    if not h1:
        # Fallback: Check page title maybe?
        print(f"Could not find H1 title. Page Title: {await page.title()}")
        await page.screenshot(path="debug_error.png")
        with open("debug_error.html", "w") as f:
            f.write(content)
        await page.close()
        return None
    
    for span in h1.find_all('span'):
        span.decompose()
    card_name = h1.get_text(strip=True)

    if "Starter Deck" in card_name:
        print(f"Skipping (Starter Deck Name): {card_name}")
        await page.close()
        return None

    # 2. Extract Image URL
    img_tag = soup.select_one('div.tab-content img')
    if not img_tag:
        img_tag = soup.select_one('div.image img')
    
    image_url = None
    if img_tag:
        src = img_tag.get('src')
        if src:
            if src.startswith('//'):
                image_url = 'https:' + src
            elif src.startswith('/'):
                image_url = 'https://www.cardmarket.com' + src
            else:
                image_url = src
    
    if not image_url:
        print("Could not find image URL.")
        await page.screenshot(path="debug_image_error.png")
        with open("debug_image_error.html", "w") as f:
             f.write(content)
    
    # 3. Detect Language
    language = "English" 
    current_url = page.url
    if "(Japanese)" in card_name or "(Jer)" in card_name or "(Non-English)" in card_name: 
        language = "Japanese"
    elif "(Chinese)" in card_name:
        language = "Chinese"
    elif "Non-English" in current_url or "Japanese" in current_url or "Asia" in current_url:
        language = "Japanese"
    elif "Asia" in card_name or "Asian" in card_name:
        language = "Japanese"
    
    # Download Image Content
    image_content = None
    if image_url:
        try:
            print(f"Downloading image {image_url}...")
            # Use Playwright's APIRequestContext to fetch the image using the same context (cookies/proxy)
            response = await context.request.get(image_url)
            if response.ok:
                image_content = await response.body()
            else:
                print(f"Failed to download image: {response.status} {response.status_text}")

        except Exception as e:
             print(f"Error downloading image: {e}")

    await page.close()

    return {
        "name": card_name,
        "image_url": image_url,
        "language": language,
        "image_content": image_content,
        "product_url": final_url
    }

def save_image(content, filename):
    os.makedirs(IMAGE_DIR, exist_ok=True)
    ext = ".jpg" 
    unique_name = f"{uuid.uuid4().hex}_{filename}{ext}"
    path = os.path.join(IMAGE_DIR, unique_name)
    with open(path, 'wb') as f:
        f.write(content)
    return unique_name

async def run_import():
    parser = argparse.ArgumentParser(description="Import Riftbound Singles")
    parser.add_argument("--file", default=DEFAULT_FILENAME, help="Path to Price Guide JSON")
    parser.add_argument("--url", default=PRICE_GUIDE_URL, help="URL to download JSON if missing")
    parser.add_argument("--min-price", type=float, default=10.0, help="Minimum Trend Price")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of NEW cards to add")
    parser.add_argument("--dry-run", action="store_true", help="Do not make changes, just print")
    parser.add_argument("--show-duplicates", action="store_true", help="Print duplicate cards found")
    parser.add_argument("--delay", type=float, default=3.0, help="Delay between web requests")

    args = parser.parse_args()

    # 1. Load Data
    # Always download the latest price guide
    download_file(args.url, args.file)
    
    print("Waiting 10 seconds before processing...")
    time.sleep(10)
    
    print(f"Loading {args.file}...")
    with open(args.file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    price_guides = data.get("priceGuides", [])
    print(f"Found {len(price_guides)} items in price guide.")

    new_cards_processed = 0
    query_count = 0
    
    print("Starting Playwright (Chromium)...")
    
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64; rv:146.0) Gecko/20100101 Firefox/146.0",
            extra_http_headers={"Referer": "https://www.cardmarket.com/"}
        )
        try:
            cookies = parse_netscape_cookies("cookies-cardmarket-com.txt")
            clearance_value = ""
            try:
                with open("cf_clearance.txt", "r") as f:
                    clearance_value = f.read().strip()
            except Exception:
                pass

            if clearance_value:
                cf_clearance = {
                    "name": "cf_clearance",
                    "value": clearance_value,
                    "domain": ".cardmarket.com",
                    "path": "/",
                    "secure": True
                }
                cookies.append(cf_clearance)
            await context.add_cookies(cookies)
        except Exception as e:
            print(f"Failed to load cookies: {e}")
        
        with get_db_session() as session:
            for item in price_guides:
                if args.limit and new_cards_processed >= args.limit:
                    print(f"Limit of {args.limit} new cards reached.")
                    break

                product_id = item.get("idProduct")
                trend_price = item.get("trend") 
                avg30_price = item.get("avg30")
                avg7_price = item.get("avg7")
                
                # 4. Filtering
                # Prioritize long-term averages for stability
                if avg30_price is not None:
                    filter_price = avg30_price
                    price_type = "Avg30"
                elif avg7_price is not None:
                    filter_price = avg7_price
                    price_type = "Avg7"
                else:
                    filter_price = trend_price
                    price_type = "Trend"
                
                if filter_price is None or filter_price < args.min_price:
                    continue


                # Check Blocklist
                if is_blocked(product_id=product_id):
                    print(f"Skipping (Blocked ID): {product_id}")
                    continue

                expected_url = f"https://www.cardmarket.com/Riftbound/Products?idProduct={product_id}"

                if is_blocked(url=expected_url):
                    print(f"Skipping (Blocked URL): {expected_url}")
                    continue
                
                # 5. Check Duplicates (Product ID & URL)
                # First check by product_id (fastest, no scraping needed)
                existing_by_id = session.query(SingleCard).filter_by(product_id=product_id).first()
                if existing_by_id:
                    if args.show_duplicates:
                        print(f"[DUPLICATE ID] ID: {product_id} | {existing_by_id.name}")
                    continue

                # Fallback: Check by legacy URL
                existing = session.query(SingleCard).filter_by(url=expected_url).first()
                if existing:
                    if args.show_duplicates:
                        print(f"[DUPLICATE URL] ID: {product_id} | {existing.name}")
                    if not existing.product_id:
                        print(f"Updating product_id for {existing.name} to {product_id}")
                        existing.product_id = product_id
                        session.commit()

                    # Count this as a query/processed item as requested
                    query_count += 1
                    if query_count > 0 and query_count % 10 == 0:
                        print(f"Limit of 10 queries reached (Count: {query_count}). Pausing for 90 seconds...")
                        time.sleep(90)
                    continue
                
                # 6. New Card
                print(f"[NEW MATCH] ID: {product_id} | {price_type} Price: {filter_price}")

                query_count += 1
                if query_count > 0 and query_count % 10 == 0:
                    print(f"Limit of 10 queries reached (Count: {query_count}). Pausing for 90 seconds...")
                    time.sleep(90)
                
                if args.dry_run:
                    # Even in dry run, we might want to test one scrape to verify context?
                    # But typically dry-run avoids network calls if possible, or limited.
                    # The args says "Do not make changes", so we can probably allow scrape to test.
                    # But let's respect that dry-run usually implies testing logic, not hammering server.
                    # IF we want to VERIFY the new scraper logic, we MUST scrape.
                    # Let's scrape but not save.
                    pass

                # Scrape
                def check_url_callback(final_url):
                    if final_url != expected_url:
                        existing_canonical = session.query(SingleCard).filter_by(url=final_url).first()
                        if existing_canonical:
                            # Update product_id if we found it by URL but ID was missing
                            if not existing_canonical.product_id:
                                 print(f"Updating product_id for {existing_canonical.name} to {product_id}")
                                 existing_canonical.product_id = product_id
                                 session.commit()
                            return True
                    return False

                details = await get_card_details(context, product_id, check_url_callback=check_url_callback, delay=args.delay)
                
                if not details:
                    print("Skipping due to scrape failure.")
                    continue

                # Check if the resolved canonical URL already exists
                if details["product_url"] != expected_url:
                    existing_canonical = session.query(SingleCard).filter_by(url=details["product_url"]).first()
                    if existing_canonical:
                        print(f"Skipping (Already exists as migrated URL): {details['name']}")
                        if not existing_canonical.product_id:
                             print(f"Updating product_id for {existing_canonical.name} to {product_id}")
                             existing_canonical.product_id = product_id
                             session.commit()
                        continue
                
                if args.dry_run:
                    print(f"[DRY RUN] Would add: {details['name']}")
                    new_cards_processed += 1
                    continue

                # Save Image
                saved_image_path = None
                if details["image_content"]:
                    saved_image_path = save_image(details["image_content"], str(product_id))
                
                # Auto-Assign Category
                category = None
                if "Booster Box" in details["name"]:
                    category = "Booster Box"
                elif "Pack" in details["name"]:
                    category = "Pack"
                
                # Create DB Record
                new_card = SingleCard(
                    name=details["name"],
                    url=details["product_url"],
                    language=details["language"],
                    condition="Mint or Near Mint",
                    image_url=None,
                    category=category,
                    game="Riftbound",
                    product_id=product_id
                )
                if saved_image_path:
                     new_card.image_url = os.path.join("single_card_images", saved_image_path)

                session.add(new_card)
                session.commit()
                print(f"Added {new_card.name} to database.")
                new_cards_processed += 1
        
        await context.close()
        await browser.close()

def main():
    asyncio.run(run_import())

if __name__ == "__main__":
    main()
