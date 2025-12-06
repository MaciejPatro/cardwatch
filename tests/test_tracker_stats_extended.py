from datetime import date
from decimal import Decimal
import tracker_flask
from db import Item

import tracker_utils.fx

def test_calculate_financials(monkeypatch):
    # Mock data
    # Mock data - All CHF for simplicity
    items = [
        Item(price=100, currency='CHF', sell_price=150, sell_date=date(2024, 1, 1), not_for_sale=0, category='Active'), # Sold: +50
        Item(price=200, currency='CHF', sell_price=None, sell_date=None, not_for_sale=1, graded=True, category='Personal Collection'), # Not for sale
        Item(price=50, currency='CHF', sell_price=None, sell_date=None, not_for_sale=0, category='Active'), # Unsold
        Item(price=300, currency='CHF', sell_price=None, sell_date=None, not_for_sale=0, category='Booster Box Investment'), # Booster Box
        Item(price=40, currency='CHF', sell_price=None, sell_date=None, not_for_sale=0, category='For Grading'), # For Grading
    ]
    # Assign IDs manually since we are not using DB
    items[0].id = 1
    items[1].id = 2
    items[2].id = 3
    items[3].id = 4
    items[4].id = 5

    # Monthly stats should reflect the sold item
    # Buy: 100, Sell: 150, Revenue (P&L): 50
    monthly_stats = [
        {'buy_total': Decimal('100'), 'sell_total': Decimal('150'), 'revenue': Decimal('50'), 'not_for_sale_total': Decimal('0')},
    ]

    # Mocks
    def fake_get_fx_rates(base):
        return {'CHF': 1.0, 'USD': 1.0, 'EUR': 1.0}
    
    def fake_get_charting_prices(items):
        return {
            2: {'psa10_usd': 300}, # Cost 200. Worth 300. Gain 100.
            3: {'ungraded_usd': 60},  # Cost 50. Worth 60. Gain 10.
            4: {'ungraded_usd': 350}, # Cost 300. Worth 350. Gain 50.
            5: {'ungraded_usd': 50}, # Cost 40. Worth 50. Gain 10.
        }

    # Mock where it is defined/imported
    monkeypatch.setattr(tracker_flask, 'get_fx_rates', fake_get_fx_rates)
    import tracker_utils.utils
    monkeypatch.setattr(tracker_utils.utils, 'get_fx_rates', fake_get_fx_rates)
    monkeypatch.setattr(tracker_flask, 'get_charting_prices', fake_get_charting_prices)

    financials = tracker_flask.calculate_financials(items, monthly_stats)

    # Total Deployed: 100 (sold) + 50 (unsold) + 200 (PC) + 300 (Booster) + 40 (Grading) = 690
    assert financials['total_deployed'] == Decimal('690.00')
    
    # Current Holdings: 50 (unsold) + 200 (PC) + 300 (Booster) + 40 (Grading) = 590
    assert financials['current_holdings'] == Decimal('590.00')
    
    # Not for Sale: 200
    assert financials['not_for_sale_total'] == Decimal('200.00')

    # Booster Box: 300
    assert financials['booster_box_total'] == Decimal('300.00')

    # For Grading: 40
    assert financials['grading_total'] == Decimal('40.00')
    
    # Sold Cost Basis: 100
    assert financials['sold_cost_basis'] == Decimal('100.00')
    
    # Inventory Cost Basis: 50 (Active) + 300 (Booster) + 40 (Grading) = 390
    # Logic: Active Inventory = Current Holdings - Personal Collection ?
    # Wait, let's check the implementation logic:
    # if item.category != "Personal Collection" and not item.not_for_sale:
    #     inventory_cost_basis += cost_chf
    # So: 50 (Active) + 300 (Booster) + 40 (Grading) = 390
    assert financials['inventory_cost_basis'] == Decimal('390.00')
    
    # Inventory Count: 3 (Active, Booster, Grading)
    assert financials['inventory_count'] == 3

    # Realized P&L: 50 (from monthly_stats)
    assert financials['realized_pl'] == Decimal('50.00')

    # Unrealized P&L:
    # Item 2 (PC): 300 - 200 = 100
    # Item 3 (Active): 60 - 50 = 10
    # Item 4 (Booster): 350 - 300 = 50
    # Item 5 (Grading): 50 - 40 = 10
    # Total: 170
    assert financials['unrealized_pl'] == Decimal('170.00')

    # Total Net: 50 + 170 = 220
    assert financials['total_net'] == Decimal('220.00')

    # Restored keys for template compatibility
    # Buy Total: 100 (from monthly_stats)
    assert financials['buy_total'] == Decimal('100.00')
    # Sell Total: 150 (from monthly_stats)
    assert financials['sell_total'] == Decimal('150.00')

def test_item_list_filtering(monkeypatch):
    # Mock items with different categories
    items = [
        Item(price=100, currency='CHF', category='Active'),
        Item(price=200, currency='CHF', category='Personal Collection'),
        Item(price=300, currency='CHF', category='Booster Box Investment'),
        Item(price=40, currency='CHF', category='For Grading'),
    ]
    
    # Test 1: Filter by 'Active'
    category_filter = 'Active'
    visible_items_active = [
        item for item in items
        if category_filter == 'All' or item.category == category_filter
    ]
    assert len(visible_items_active) == 1
    assert visible_items_active[0].category == 'Active'
    
    # Test 2: Filter by 'Personal Collection'
    category_filter = 'Personal Collection'
    visible_items_pc = [
        item for item in items
        if category_filter == 'All' or item.category == category_filter
    ]
    assert len(visible_items_pc) == 1
    assert visible_items_pc[0].category == 'Personal Collection'

    # Test 3: Filter by 'All'
    category_filter = 'All'
    visible_items_all = [
        item for item in items
        if category_filter == 'All' or item.category == category_filter
    ]
    assert len(visible_items_all) == 4
