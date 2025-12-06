from datetime import datetime, timedelta
import app as cardapp
from db import get_session, SingleCard, SingleCardPrice, init_db

def test_singles_indicators():
    init_db()
    session = get_session()
    session.query(SingleCardPrice).delete()
    session.query(SingleCard).delete()
    session.commit()

    # Create a card
    card = SingleCard(name="Test Card", url="http://example.com", language="English", condition="NM")
    session.add(card)
    session.commit()

    now = datetime.utcnow()

    # Scenario 1: Supply Drop & Price Outlier
    # Past 7 days: Supply was 100
    session.add(SingleCardPrice(card_id=card.id, ts=now - timedelta(days=7), supply=100, low=10.0, avg5=12.0))
    # Current: Supply is 80 (Drop > 10%), Low is 5.0, Avg5 is 10.0 (Low < 70% of Avg5)
    session.add(SingleCardPrice(card_id=card.id, ts=now, supply=80, low=5.0, avg5=10.0))
    session.commit()

    # We need to mock render_template to inspect the context
    captured_context = {}
    def fake_render_template(template_name, **context):
        captured_context.update(context)
        return "OK"
    
    original_render = cardapp.render_template
    cardapp.render_template = fake_render_template

    try:
        cardapp.singles()
        cards = captured_context.get('cards', [])
        assert len(cards) == 1
        c = cards[0]
        assert c['supply_drop'] is True
        assert c['price_outlier'] is True

    finally:
        cardapp.render_template = original_render
        session.close()

def test_singles_no_indicators():
    init_db()
    session = get_session()
    session.query(SingleCardPrice).delete()
    session.query(SingleCard).delete()
    session.commit()

    card = SingleCard(name="Stable Card", url="http://example.com", language="English", condition="NM")
    session.add(card)
    session.commit()

    now = datetime.utcnow()

    # Scenario 2: Stable Supply & Normal Price
    session.add(SingleCardPrice(card_id=card.id, ts=now - timedelta(days=7), supply=100, low=10.0, avg5=12.0))
    session.add(SingleCardPrice(card_id=card.id, ts=now, supply=95, low=9.0, avg5=10.0)) # Supply drop 5% (ok), Low 90% of Avg (ok)
    session.commit()

    captured_context = {}
    def fake_render_template(template_name, **context):
        captured_context.update(context)
        return "OK"
    
    original_render = cardapp.render_template
    cardapp.render_template = fake_render_template

    try:
        cardapp.singles()
        cards = captured_context.get('cards', [])
        assert len(cards) == 1
        c = cards[0]
        assert c['supply_drop'] is False
        assert c['price_outlier'] is False

    finally:
        cardapp.render_template = original_render
        session.close()
