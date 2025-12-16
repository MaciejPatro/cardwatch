import sys
from db import init_db, get_db_session, SingleCard

def assign_categories():
    init_db()
    
    with get_db_session() as session:
        cards = session.query(SingleCard).all()
        print(f"Checking {len(cards)} cards for category assignment...")
        
        updated_count = 0
        booster_count = 0
        pack_count = 0
        don_count = 0
        removed_count = 0
        
        for card in cards:
            # Skip if already categorized (optional, but requested "retroactive" usually implies filling gaps or fixing)
            # User said "assignment to categories for existing records", implies we should enforce it.
            # I will overwrite to ensure consistency with the new logic.
            
            new_cat = card.category
            
            if "Booster Box" in card.name:
                new_cat = "Booster Box"
            elif "Pack" in card.name:
                new_cat = "Pack"
            elif "Don!!" in card.name:
                new_cat = "Don"
            
            # Fix false positives for Don
            if new_cat == "Don" and "Don!!" not in card.name:
                new_cat = None
            
            if new_cat != card.category:
                card.category = new_cat
                updated_count += 1
                if new_cat == "Booster Box":
                    booster_count += 1
                elif new_cat == "Pack":
                    pack_count += 1
                elif new_cat == "Don":
                    don_count += 1
                elif new_cat is None:
                    # We know it was something else before, likely Don if we are in this cleanup flow
                    # But simpler just to count "uncategorized" or specifically track what we changed
                    # For now just trust the count.
                    removed_count += 1

        if updated_count > 0:
            session.commit()
            print(f"Update complete.")
            print(f"Total updated: {updated_count}")
            print(f"  - Booster Boxes: {booster_count}")
            print(f"  - Packs: {pack_count}")
            print(f"  - Don: {don_count}")
            print(f"  - Removed Don (Corrected): {removed_count}")
        else:
            print("No updates needed.")

if __name__ == "__main__":
    assign_categories()
