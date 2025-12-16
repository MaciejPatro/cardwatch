import sys
import os

from db import get_db_session, SingleCard, init_db

def fix_languages():
    init_db()
    with get_db_session() as s:
        cards = s.query(SingleCard).all()
        print(f"Checking {len(cards)} cards...")
        
        updated_count = 0
        for card in cards:
            old_lang = card.language
            new_lang = "English"
            
            # Logic matching the updated importer
            if "(Japanese)" in card.name or "(Jer)" in card.name or "(Non-English)" in card.name or "Asia" in card.name or "Asian" in card.name:
                new_lang = "Japanese"
            elif "(Chinese)" in card.name:
                new_lang = "Chinese"
            elif card.url and ("Non-English" in card.url or "Japanese" in card.url or "Asia" in card.url):
                new_lang = "Japanese"
            
            if old_lang != new_lang:
                print(f"Updating '{card.name}' ID {card.id}: {old_lang} -> {new_lang}")
                card.language = new_lang
                updated_count += 1
        
        if updated_count > 0:
            s.commit()
            print(f"Successfully updated {updated_count} cards.")
        else:
            print("No cards needed updating.")

if __name__ == "__main__":
    fix_languages()
