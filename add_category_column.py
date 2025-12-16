import sys
from sqlalchemy import text
from db import get_db_session

def add_column():
    print("Checking if 'category' column exists in 'single_cards'...")
    with get_db_session() as session:
        try:
            # Check if column exists
            result = session.execute(text("PRAGMA table_info(single_cards)")).fetchall()
            columns = [row[1] for row in result]
            
            if "category" in columns:
                print("'category' column already exists.")
            else:
                print("Adding 'category' column...")
                session.execute(text("ALTER TABLE single_cards ADD COLUMN category VARCHAR"))
                session.commit()
                print("Column added successfully.")
                
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    add_column()
