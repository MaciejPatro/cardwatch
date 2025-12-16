from db import get_db_session, SingleCard, init_db

init_db()
with get_db_session() as s:
    cards = s.query(SingleCard).filter_by(category="Don").all()
    print(f"Found {len(cards)} 'Don' cards:")
    for c in cards:
        print(f"- {c.name}")
