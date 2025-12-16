from sqlalchemy import create_engine, text
from config import Config

def migrate():
    engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
    with engine.connect() as conn:
        print("Adding 'game' column to single_cards table...")
        try:
            conn.execute(text("ALTER TABLE single_cards ADD COLUMN game VARCHAR"))
            print("Column added.")
        except Exception as e:
            print(f"Column might already exist: {e}")

        print("Backfilling existing cards to 'One Piece'...")
        conn.execute(text("UPDATE single_cards SET game = 'One Piece' WHERE game IS NULL"))
        conn.commit()
        print("Migration complete.")

if __name__ == "__main__":
    migrate()
