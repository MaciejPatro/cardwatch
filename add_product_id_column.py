import sqlite3
import os
from config import Config

DB_PATH = Config.SQLALCHEMY_DATABASE_URI.replace("sqlite:///", "")

def migrate():
    print(f"Migrating database at {DB_PATH}...")
    
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Check if column exists
        cursor.execute("PRAGMA table_info(single_cards)")
        columns = [info[1] for info in cursor.fetchall()]
        
        if "product_id" in columns:
            print("Column 'product_id' already exists in 'single_cards'. Skipping.")
        else:
            print("Adding 'product_id' column to 'single_cards'...")
            cursor.execute("ALTER TABLE single_cards ADD COLUMN product_id INTEGER")
            cursor.execute("CREATE UNIQUE INDEX ix_single_cards_product_id ON single_cards (product_id)")
            conn.commit()
            print("Migration successful.")
            
    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
