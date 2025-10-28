from datetime import date
from decimal import Decimal

import tracker_flask
from db import get_session, Item, init_db


def fake_get_fx_rates(base):
    rates = {
        'USD': {'CHF': 0.9, 'USD': 1.0, 'EUR': 0.8, 'PLN': 4.0},
        'CHF': {'CHF': 1.0, 'USD': 1.1, 'EUR': 0.95, 'PLN': 4.0},
        'EUR': {'CHF': 1.1, 'USD': 1.2, 'EUR': 1.0, 'PLN': 4.0},
        'PLN': {'CHF': 0.25, 'USD': 0.28, 'EUR': 0.23, 'PLN': 1.0},
    }
    return rates.get(base, {'CHF': 1.0, 'USD': 1.0, 'EUR': 1.0, 'PLN': 1.0})


def test_calculate_monthly_tracker_stats(monkeypatch):
    init_db()
    session = get_session()
    session.query(Item).delete()
    session.commit()

    items = [
        Item(
            name='Alpha',
            buy_date=date(2024, 1, 10),
            link=None,
            graded=0,
            price=100.0,
            currency='USD',
            sell_price=150.0,
            sell_date=date(2024, 3, 5),
            not_for_sale=0,
        ),
        Item(
            name='Beta',
            buy_date=date(2024, 2, 1),
            link=None,
            graded=0,
            price=200.0,
            currency='CHF',
            sell_price=None,
            sell_date=None,
            not_for_sale=0,
        ),
        Item(
            name='Gamma',
            buy_date=date(2024, 3, 15),
            link=None,
            graded=0,
            price=50.0,
            currency='EUR',
            sell_price=80.0,
            sell_date=date(2024, 3, 20),
            not_for_sale=0,
        ),
        Item(
            name='Delta',
            buy_date=date(2024, 3, 25),
            link=None,
            graded=0,
            price=40.0,
            currency='CHF',
            sell_price=None,
            sell_date=None,
            not_for_sale=1,
        ),
    ]

    session.add_all(items)
    session.commit()
    ids = [item.id for item in items]

    try:
        monkeypatch.setattr(tracker_flask, 'get_fx_rates', fake_get_fx_rates)
        items_for_stats = session.query(Item).order_by(Item.buy_date.asc()).all()
        stats = tracker_flask.calculate_monthly_tracker_stats(items_for_stats)
    finally:
        session.query(Item).filter(Item.id.in_(ids)).delete(synchronize_session=False)
        session.commit()
        session.close()

    assert [entry['label'] for entry in stats] == [
        'January 2024',
        'February 2024',
        'March 2024',
    ]

    january, february, march = stats

    assert january['buy_total'] == Decimal('90.00')
    assert january['not_for_sale_total'] == Decimal('0.00')
    assert january['sell_total'] == Decimal('0.00')
    assert january['revenue'] == Decimal('0.00')
    assert january['roi_pct'] is None

    assert february['buy_total'] == Decimal('200.00')
    assert february['not_for_sale_total'] == Decimal('0.00')
    assert february['sell_total'] == Decimal('0.00')
    assert february['revenue'] == Decimal('0.00')
    assert february['roi_pct'] is None

    assert march['buy_total'] == Decimal('55.00')
    assert march['not_for_sale_total'] == Decimal('40.00')
    assert march['sell_total'] == Decimal('230.00')
    assert march['revenue'] == Decimal('85.00')
    assert march['roi_pct'] == Decimal('58.62')


def test_calculate_sale_time_stats():
    init_db()
    session = get_session()
    session.query(Item).delete()
    session.commit()

    items = [
        Item(
            name='Alpha',
            buy_date=date(2024, 1, 1),
            link=None,
            graded=0,
            price=100.0,
            currency='CHF',
            sell_price=120.0,
            sell_date=date(2024, 1, 11),
            not_for_sale=0,
        ),
        Item(
            name='Beta',
            buy_date=date(2024, 2, 1),
            link=None,
            graded=0,
            price=50.0,
            currency='CHF',
            sell_price=None,
            sell_date=None,
            not_for_sale=0,
        ),
        Item(
            name='Gamma',
            buy_date=date(2024, 2, 10),
            link=None,
            graded=0,
            price=75.0,
            currency='CHF',
            sell_price=90.0,
            sell_date=date(2024, 3, 1),
            not_for_sale=0,
        ),
        Item(
            name='Delta',
            buy_date=date(2024, 3, 5),
            link=None,
            graded=0,
            price=30.0,
            currency='CHF',
            sell_price=None,
            sell_date=None,
            not_for_sale=1,
        ),
    ]

    session.add_all(items)
    session.commit()
    ids = [item.id for item in items]

    try:
        stats = tracker_flask.calculate_sale_time_stats(
            session.query(Item).order_by(Item.buy_date.asc()).all()
        )
    finally:
        session.query(Item).filter(Item.id.in_(ids)).delete(synchronize_session=False)
        session.commit()
        session.close()

    assert stats['average_sale_days'] == Decimal('15.0')
    assert stats['sold_items'] == 2
    assert stats['active_listings'] == 1
    assert stats['not_for_sale_inventory'] == 1
    assert stats['total_items'] == 4
    assert stats['sellable_items'] == 3
    assert stats['sell_through_pct'] == Decimal('66.7')
