from sqlalchemy import create_engine, text
from config import Config

def check_counts():
    try:
        engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
        with engine.connect() as conn:
            items_count = conn.execute(text("SELECT COUNT(*) FROM items")).scalar()
            products_count = conn.execute(text("SELECT COUNT(*) FROM products")).scalar()
            single_cards_count = conn.execute(text("SELECT COUNT(*) FROM single_cards")).scalar()
            
            print(f"Items: {items_count}")
            print(f"Products: {products_count}")
            print(f"SingleCards: {single_cards_count}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_counts()
