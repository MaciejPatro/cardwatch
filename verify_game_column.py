from db import get_db_session, SingleCard
from sqlalchemy import func

def verify():
    with get_db_session() as s:
        counts = s.query(SingleCard.game, func.count(SingleCard.id)).group_by(SingleCard.game).all()
        print("Game Counts:")
        for game, count in counts:
            print(f"- {game}: {count}")

if __name__ == "__main__":
    verify()
