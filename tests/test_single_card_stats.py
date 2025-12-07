from datetime import datetime, timedelta
import app as cardapp
from db import get_session, SingleCard, SingleCardPrice, init_db

def test_calculate_card_stats():
    init_db()
    session = get_session()
    session.query(SingleCardPrice).delete()
    session.query(SingleCard).delete()
    session.commit()

    # Create a card
    card = SingleCard(name="Stats Card", url="http://example.com", language="English", condition="NM")
    session.add(card)
    session.commit()

    now = datetime.utcnow()

    # Add price history
    # 100 days ago (invalid start)
    session.add(SingleCardPrice(card_id=card.id, ts=now - timedelta(days=100), low=None))
    # 90 days ago (valid start)
    session.add(SingleCardPrice(card_id=card.id, ts=now - timedelta(days=90), low=20.0))
    # 30 days ago
    session.add(SingleCardPrice(card_id=card.id, ts=now - timedelta(days=30), low=15.0))
    # 7 days ago (for supply drop check)
    session.add(SingleCardPrice(card_id=card.id, ts=now - timedelta(days=7), supply=100))
    # Current
    session.add(SingleCardPrice(card_id=card.id, ts=now, low=10.0, supply=80, avg5=20.0, from_price=9.0, price_trend=11.0, avg7_price=12.0, avg1_price=10.5))
    session.commit()

    stats = cardapp.calculate_card_stats(session, card)

    assert stats['id'] == card.id
    assert stats['name'] == "Stats Card"
    assert stats['current_low'] == 10.0
    assert stats['from_price'] == 9.0
    assert stats['price_trend'] == 11.0
    assert stats['avg7_price'] == 12.0
    assert stats['avg1_price'] == 10.5
    
    # Percentages
    # 30d: (10 - 15) / 15 = -33.33%
    assert abs(stats['pct30'] - (-33.333)) < 0.001
    # 90d: (10 - 20) / 20 = -50.00%
    assert abs(stats['pct90'] - (-50.00)) < 0.001
    # All-time (first was 90d ago): -50.00%
    assert abs(stats['pct_all'] - (-50.00)) < 0.001

    # Indicators
    # Supply drop: 80 < 100 * 0.9 (90) -> True
    assert stats['supply_drop'] is True
    # Price outlier: 10 < 20 * 0.7 (14) -> True
    assert stats['price_outlier'] is True

    session.close()
