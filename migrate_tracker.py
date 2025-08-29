import sqlite3
from datetime import date

from db import init_db, get_session, Item


def migrate(src_path="../tracker/db.sqlite3"):
    """Migrate Django tracker items into the SQLAlchemy database."""
    init_db()
    conn = sqlite3.connect(src_path)
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT name, buy_date, link, graded, price, currency, sell_price, sell_date, image FROM items_item"
    ).fetchall()
    session = get_session()
    for row in rows:
        name, buy_date, link, graded, price, currency, sell_price, sell_date, image = row
        item = Item(
            name=name,
            buy_date=date.fromisoformat(buy_date) if buy_date else None,
            link=link or None,
            graded=int(graded or 0),
            price=float(price or 0),
            currency=currency,
            sell_price=float(sell_price) if sell_price is not None else None,
            sell_date=date.fromisoformat(sell_date) if sell_date else None,
            image=image or None,
        )
        session.add(item)
    session.commit()
    session.close()
    conn.close()
    print(f"Migrated {len(rows)} items from {src_path}.")


if __name__ == "__main__":
    migrate()
