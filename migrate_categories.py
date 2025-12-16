import sqlite3
import os

DB_PATH = "cardwatch.db"

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"Database {DB_PATH} not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Check if column exists
        cursor.execute("PRAGMA table_info(items)")
        columns = [info[1] for info in cursor.fetchall()]
        
        if "category" not in columns:
            print("Adding category column...")
            cursor.execute("ALTER TABLE items ADD COLUMN category TEXT")
            
            print("Migrating data...")
            # Migrate not_for_sale=1 to 'Personal Collection'
            cursor.execute("UPDATE items SET category = 'Personal Collection' WHERE not_for_sale = 1")
            
            # Migrate not_for_sale=0 to 'Active'
            cursor.execute("UPDATE items SET category = 'Active' WHERE not_for_sale = 0")
            
            conn.commit()
            print("Migration successful.")
        else:
            print("Column 'category' already exists.")

    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
