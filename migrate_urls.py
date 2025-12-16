import asyncio
import os
from playwright.async_api import async_playwright
from db import get_db_session, SingleCard, init_db

async def migrate_urls():
    init_db()
    with get_db_session() as session:
        # Find cards with idProduct URLs or that might need language check
        # We focus on cards with 'idProduct' in URL as they are definitely "old style"
        cards = session.query(SingleCard).filter(SingleCard.url.like("%idProduct=%")).all()
        print(f"Found {len(cards)} cards with legacy URLs to check...")

        if not cards:
            return

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-web-security", "--disable-features=IsolateOrigins,site-per-process"]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            updated_count = 0
            for i, card in enumerate(cards):
                print(f"[{i+1}/{len(cards)}] Checking {card.name} (ID {card.id})...")
                try:
                    # Navigate to the idProduct URL
                    await page.goto(card.url, wait_until="domcontentloaded")
                    final_url = page.url
                    
                    # Update URL if it changed and looks like a canonical link (no idProduct query)
                    if final_url != card.url and "idProduct=" not in final_url:
                        # Check for existing card with this URL to avoid IntegrityError
                        existing_card = session.query(SingleCard).filter(SingleCard.url == final_url).first()
                        if existing_card and existing_card.id != card.id:
                            print(f"  -> Duplicate found (ID {existing_card.id}). Deleting current legacy card (ID {card.id})...")
                            session.delete(card)
                            session.commit() # Commit deletion immediately
                            continue

                        print(f"  -> Resolved URL: {final_url}")
                        card.url = final_url
                        
                        # Re-run Language Detection
                        new_lang = "English"
                        if "(Japanese)" in card.name or "(Jer)" in card.name or "(Non-English)" in card.name:
                            new_lang = "Japanese"
                        elif "Non-English" in final_url or "Japanese" in final_url:
                            new_lang = "Japanese"
                        elif "(Chinese)" in card.name:
                            new_lang = "Chinese"
                        
                        if card.language != new_lang:
                            print(f"  -> Updating Language: {card.language} -> {new_lang}")
                            card.language = new_lang
                        
                        updated_count += 1
                        # Commit incrementally or in batches? SQLAlchemy session logic.
                        # We'll commit every 10 for safety
                        if updated_count % 10 == 0:
                            session.commit()
                    
                    await asyncio.sleep(3.0)
                            
                except Exception as e:
                    print(f"  -> Error resolving {card.url}: {e}")
            
            if updated_count > 0:
                session.commit()
                print(f"Finished. Updated {updated_count} cards.")
            else:
                print("Finished. No updates made.")
            
            await browser.close()

if __name__ == "__main__":
    asyncio.run(migrate_urls())
