from datetime import date
from decimal import Decimal
import tracker_flask
from db import get_session, Item, init_db

def test_sell_through_rate_filtering_active_only():
    init_db()
    session = get_session()
    # Clear existing items
    session.query(Item).delete()
    session.commit()

    active_unsold = Item(
        name='Active Unsold',
        buy_date=date(2024, 1, 1),
        price=10.0,
        currency='USD',
        category='Active',
        not_for_sale=0
    )
    active_sold = Item(
        name='Active Sold',
        buy_date=date(2024, 1, 1),
        price=10.0,
        currency='USD',
        sell_price=20.0,
        sell_date=date(2024, 1, 2),
        category='Active',
        not_for_sale=0
    )
    booster_box = Item(
        name='Booster Box',
        buy_date=date(2024, 1, 1),
        price=100.0,
        currency='USD',
        category='Booster Box Investment',
        not_for_sale=0 # Technically these might be 0 or 1 depending on logic, but category matters
    )
    grading_itm = Item(
        name='To Grade',
        buy_date=date(2024, 1, 1),
        price=50.0,
        currency='USD',
        category='For Grading',
        not_for_sale=0
    )
    
    # Even if we sell a booster (hypothetically), it shouldn't count if we only want "Active cards" 
    # But usually trackers might sell boosters. 
    # The requirement is "sell through rate should be based on actively selling cards not other items (gradin/pc/booster)"
    # So we assume even if sold, if it's a booster category, it escapes the calc.
    booster_sold = Item(
        name='Booster Sold',
        buy_date=date(2024, 1, 1),
        price=100.0,
        currency='USD',
        sell_price=120.0,
        sell_date=date(2024, 1, 10),
        category='Booster Box Investment',
        not_for_sale=0
    )

    items = [active_unsold, active_sold, booster_box, grading_itm, booster_sold]
    session.add_all(items)
    session.commit()

    try:
        query_items = session.query(Item).order_by(Item.buy_date.asc()).all()
        stats = tracker_flask.calculate_sale_time_stats(query_items)
        
        # Calculation:
        # Active Pool: active_unsold (1), active_sold (1). Total 2.
        # Sold in Pool: active_sold (1).
        # Rate: 1/2 = 50.0%
        
        # If boosters were included:
        # Pool: 2 active + 1 booster unsold + 1 booster sold + 1 grading = 5? Or maybe grading excluded?
        # The key is checking it matches 50.0%
        
        assert stats['sell_through_pct'] == Decimal('50.0')

    finally:
        session.query(Item).delete()
        session.commit()
        session.close()

if __name__ == "__main__":
    try:
        test_sell_through_rate_filtering_active_only()
        print("Test passed!")
    except AssertionError as e:
        print(f"Test failed: {e}")
        exit(1)
    except Exception as e:
        print(f"An error occurred: {e}")
        exit(1)
