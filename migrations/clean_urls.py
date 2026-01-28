import sys
import os

# Add parent directory to path to allow importing modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import get_db_session, SingleCard, Item
from tracker_utils.url_utils import clean_url
from sqlalchemy import func

def run_migration():
    print("Starting URL cleaning migration...")
    with get_db_session() as session:
        # Clean SingleCard URLs
        cards = session.query(SingleCard).all()
        cleaned_count = 0
        deleted_count = 0
        
        for card in cards:
            if not card.url:
                continue
                
            cleaned = clean_url(card.url)
            if cleaned != card.url:
                # Check for conflict
                existing = session.query(SingleCard).filter_by(url=cleaned).first()
                if existing and existing.id != card.id:
                    print(f"Duplicate found for {card.name}")
                    print(f"  Dirty: {card.url}")
                    print(f"  Clean: {cleaned}")
                    print(f"  Existing ID: {existing.id}, Current ID: {card.id}")
                    
                    # Strategy: If the dirty one has a product_id and the clean one doesn't, keep dirty's info
                    # Otherwise, simpler to verify connection manually, but for automation:
                    # Let's delete the dirty one if a clean one exists, assuming clean one is valid.
                    # Or update the clean one with missing info from dirty one?
                    
                    pid_to_transfer = card.product_id if (card.product_id and not existing.product_id) else None
                    
                    print(f"  Deleting dirty duplicate {card.id}")
                    session.delete(card)
                    session.flush() # Ensure delete is processed to free up product_id constraint

                    if pid_to_transfer:
                        print(f"  Transferring product_id {pid_to_transfer} to existing record.")
                        existing.product_id = pid_to_transfer
                    
                    deleted_count += 1
                else:
                    print(f"Cleaning URL for {card.name}: {card.url} -> {cleaned}")
                    card.url = cleaned
                    cleaned_count += 1
        
        # Clean Item URLs (Tracker items)
        items = session.query(Item).all()
        item_cleaned_count = 0
        
        for item in items:
            if not item.link:
                continue
            
            cleaned_link = clean_url(item.link)
            if cleaned_link != item.link:
                print(f"Cleaning Item URL for {item.name}: {item.link} -> {cleaned_link}")
                item.link = cleaned_link
                item_cleaned_count += 1
                
        session.commit()
        print(f"Migration complete.")
        print(f"SingleCards cleaned: {cleaned_count}")
        print(f"SingleCards deleted (duplicates): {deleted_count}")
        print(f"Items cleaned: {item_cleaned_count}")

if __name__ == "__main__":
    run_migration()
