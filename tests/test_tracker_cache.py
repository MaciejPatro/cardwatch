import tracker_flask
from db import get_session, Item
from datetime import date


def test_refresh_pricecharting_cache_handles_items_without_link(monkeypatch):
    tracker_flask.PRICECHARTING_CACHE.clear()
    session = get_session()
    item_with_link = Item(
        name='WithLink',
        buy_date=date.today(),
        link='http://example.com',
        graded=0,
        price=1.0,
        currency='USD',
    )
    item_no_link = Item(
        name='NoLink',
        buy_date=date.today(),
        link=None,
        graded=0,
        price=2.0,
        currency='USD',
    )
    session.add_all([item_with_link, item_no_link])
    session.commit()
    ids = (item_with_link.id, item_no_link.id)
    session.close()

    monkeypatch.setattr(
        tracker_flask,
        'fetch_pricecharting_prices',
        lambda url: {'psa10_usd': 10.0, 'ungraded_usd': 5.0},
    )

    tracker_flask.refresh_pricecharting_cache()

    assert ids[0] in tracker_flask.PRICECHARTING_CACHE
    assert ids[1] in tracker_flask.PRICECHARTING_CACHE
    assert tracker_flask.PRICECHARTING_CACHE[ids[1]] == {
        'psa10_usd': None,
        'ungraded_usd': None,
    }

    session = get_session()
    session.query(Item).filter(Item.id.in_(ids)).delete(synchronize_session=False)
    session.commit()
    session.close()


def test_refresh_pricecharting_cache_skips_sold_items(monkeypatch):
    tracker_flask.PRICECHARTING_CACHE.clear()
    session = get_session()
    sold_item = Item(
        name='SoldItem',
        buy_date=date.today(),
        link='http://example.com/sold',
        graded=0,
        price=10.0,
        currency='USD',
        sell_date=date.today(),
        sell_price=15.0
    )
    session.add(sold_item)
    session.commit()
    item_id = sold_item.id
    session.close()

    # Mock fetch to raise an error if called with the sold item's URL
    sold_url = 'http://example.com/sold'
    called_urls = []
    def mock_fetch(url):
        called_urls.append(url)
        return {'psa10_usd': 100.0, 'ungraded_usd': 50.0}

    monkeypatch.setattr(
        tracker_flask,
        'fetch_pricecharting_prices',
        mock_fetch,
    )

    tracker_flask.refresh_pricecharting_cache()

    assert item_id in tracker_flask.PRICECHARTING_CACHE
    # Should be None/empty because it was skipped
    assert tracker_flask.PRICECHARTING_CACHE[item_id] == {
        'psa10_usd': None,
        'ungraded_usd': None,
    }
    assert sold_url not in called_urls, "fetch_pricecharting_prices should not be called for the sold item URL"

    session = get_session()
    session.query(Item).filter(Item.id == item_id).delete()
    session.commit()
    session.close()
