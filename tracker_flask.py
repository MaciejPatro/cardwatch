import os
from collections import OrderedDict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from threading import Thread
import time
import uuid

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    send_from_directory,
    jsonify,
)
from werkzeug.utils import secure_filename

from db import get_db_session, Item, SingleCard, SingleCardPrice, func
from tracker_utils.pricecharting import fetch_pricecharting_prices
from tracker_utils.utils import (
    get_reference_usd,
    get_reference_chf,
    get_paid_usd,
)
from tracker_utils.fx import get_fx_rates
from apscheduler.schedulers.background import BackgroundScheduler

tracker_bp = Blueprint('tracker', __name__, url_prefix='/tracker')


@tracker_bp.app_context_processor
def inject_has_endpoint():
    from flask import current_app

    def has_endpoint(name: str):
        try:
            return name in current_app.view_functions
        except Exception:
            return False

    return {"has_endpoint": has_endpoint}

from config import Config

MEDIA_ROOT = Config.MEDIA_ROOT
UPLOAD_FOLDER = os.path.join(MEDIA_ROOT, 'item_images')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

PRICECHARTING_CACHE = {}
PRICECHARTING_CACHE_TS = None
Q = Decimal('0.01')

@tracker_bp.app_template_filter('dict_get')
def dict_get(d, key):
    return d.get(key)

@tracker_bp.app_template_filter('format_float')
def format_float(value, digits=2):
    try:
        return f"{float(value):.{int(digits)}f}"
    except (TypeError, ValueError):
        return ''

@tracker_bp.route('/media/<path:filename>')
def media(filename):
    return send_from_directory(MEDIA_ROOT, filename)

CURRENCIES = [
    ("CHF", "Swiss Franc"),
    ("EUR", "Euro"),
    ("USD", "US Dollar"),
    ("PLN", "Polish Zloty"),
]

def save_uploaded_image(image, upload_folder=None):
    """Save an uploaded image with a unique filename."""
    upload_folder = upload_folder or UPLOAD_FOLDER
    media_root = os.path.abspath(MEDIA_ROOT)
    target_folder = os.path.abspath(upload_folder)

    if os.path.commonpath([media_root, target_folder]) != media_root:
        raise ValueError("Upload folder must be inside MEDIA_ROOT")

    os.makedirs(target_folder, exist_ok=True)

    filename = secure_filename(image.filename)
    unique_filename = f"{uuid.uuid4().hex}_{filename}"
    relative_dir = os.path.relpath(target_folder, media_root)
    relative_path = os.path.join(relative_dir, unique_filename)
    image.save(os.path.join(target_folder, unique_filename))
    return relative_path

def to_dec(val):
    return Decimal(str(val)) if val is not None else Decimal('0')


def _update_cache(item_dicts):
    """
    Update cache for items.
    item_dicts: list of dicts with 'id', 'link', 'sell_date' keys.
    """
    for item in item_dicts:
        if item['link'] and not item['sell_date']:
            PRICECHARTING_CACHE[item['id']] = fetch_pricecharting_prices(item['link'])
            time.sleep(15)
        else:
            PRICECHARTING_CACHE[item['id']] = {"psa10_usd": None, "ungraded_usd": None}
    global PRICECHARTING_CACHE_TS
    PRICECHARTING_CACHE_TS = datetime.utcnow().isoformat()


def refresh_pricecharting_cache():
    global PRICECHARTING_CACHE_TS
    with get_db_session() as session:
        # Load all items so that entries without a link also get a cache slot.
        # This avoids the tracker appearing empty for items that don't have
        # an associated PriceCharting link. Those items simply get default
        # price information instead of being skipped entirely.
        items = session.query(Item).all()
        # detach items for thread safety by converting to list of dicts
        item_dicts = [{'id': i.id, 'link': i.link, 'sell_date': i.sell_date} for i in items]
        _update_cache(item_dicts)
    PRICECHARTING_CACHE_TS = datetime.utcnow()


def schedule_pricecharting_refresh():
    scheduler = BackgroundScheduler()
    scheduler.add_job(refresh_pricecharting_cache, "interval", hours=6)
    scheduler.start()
    return scheduler


def init_tracker_scheduler():
    if Config.CARDWATCH_DISABLE_SCHEDULER:
        return None
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true" and os.environ.get("FLASK_DEBUG"):
        return None
    sched = schedule_pricecharting_refresh()
    refresh_pricecharting_cache()
    return sched

def get_charting_prices(items):
    charting_prices = {}
    missing = []
    for item in items:
        data = PRICECHARTING_CACHE.get(item.id)
        if data is not None:
            charting_prices[item.id] = data
        else:
            charting_prices[item.id] = {"psa10_usd": None, "ungraded_usd": None}
            missing.append(item)
    if missing:
        # Convert missing items to detached dicts for the thread
        missing_dicts = [{'id': i.id, 'link': i.link, 'sell_date': i.sell_date} for i in missing]
        Thread(target=_update_cache, args=(missing_dicts,), daemon=True).start()
    return charting_prices


def get_latest_card_prices(session, card_ids):
    """Fetch the latest SingleCardPrice for a list of card IDs.
    Returns a dict {card_id: low_price_eur}."""
    if not card_ids:
        return {}
    
    latest_subq = (
        session.query(SingleCardPrice.card_id, func.max(SingleCardPrice.ts).label('max_ts'))
        .filter(SingleCardPrice.card_id.in_(card_ids))
        .group_by(SingleCardPrice.card_id)
        .subquery()
    )
    
    latest_prices = (
        session.query(SingleCardPrice.card_id, SingleCardPrice.low)
        .join(latest_subq, 
              (SingleCardPrice.card_id == latest_subq.c.card_id) & 
              (SingleCardPrice.ts == latest_subq.c.max_ts))
        .all()
    )
    return {r[0]: r[1] for r in latest_prices}

def calculate_fx_dict(items, charting_prices, fx_chf):
    fx_dict = {}
    usd_to_eur = Decimal(str(get_fx_rates("USD").get("EUR", 1.0)))
    for item in items:
        fx = get_fx_rates(base=item.currency)
        price = float(item.price)
        price_chf = price * fx.get("CHF", 1.0)
        price_eur = price * fx.get("EUR", 1.0)
        price_usd = price * fx.get("USD", 1.0)

        ref_usd = get_reference_usd(item, charting_prices)
        ref_chf = get_reference_chf(ref_usd, fx_chf)
        base = max(price_chf, ref_chf)

        buy_price_eur = to_dec(price_eur).quantize(Q, rounding=ROUND_HALF_UP)
        ref_price_eur = (
            to_dec(ref_usd) * usd_to_eur
        ).quantize(Q, rounding=ROUND_HALF_UP) if ref_usd is not None else None

        if ref_price_eur is not None:
            base_price_eur = max(buy_price_eur, ref_price_eur)
        else:
            base_price_eur = buy_price_eur

        proposed_price_eur = (base_price_eur * Decimal('1.25') / Decimal('0.95')).quantize(Q, rounding=ROUND_HALF_UP)

        realized_revenue = (
            float(item.sell_price) - price_chf if item.sell_price else None
        )
        revenue_pct = (
            (realized_revenue / price_chf) * 100.0
            if realized_revenue is not None and price_chf > 0 else None
        )

        fx_dict[item.id] = {
            "price_chf": price_chf,
            "price_eur": price_eur,
            "price_usd": price_usd,
            "revenue": realized_revenue,
            "revenue_pct": revenue_pct,
            "proposed_price_eur": float(proposed_price_eur),
        }
    return fx_dict

def calculate_possible_gain_chf(items, charting_prices, fx_chf):
    possible_gain_usd = 0.0
    for item in items:
        if item.not_for_sale:
            continue
        if not (item.sell_price and item.sell_date):
            paid_usd = get_paid_usd(item)
            ref_usd = get_reference_usd(item, charting_prices)
            if ref_usd is not None:
                possible_gain_usd += (ref_usd - paid_usd)
    return possible_gain_usd / fx_chf["USD"]


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _iterate_months(start: date, end: date):
    current = date(start.year, start.month, 1)
    while current <= end:
        yield current
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)


def calculate_monthly_tracker_stats(items):
    items_with_buy_dates = [item for item in items if item.buy_date]
    if not items_with_buy_dates:
        return []

    all_dates = [item.buy_date for item in items_with_buy_dates]
    all_dates.extend([item.sell_date for item in items if item.sell_date])
    relevant_dates = [d for d in all_dates if d is not None]
    if not relevant_dates:
        return []

    start_month = _month_start(min(relevant_dates))
    end_month = _month_start(max(relevant_dates))

    monthly_totals = OrderedDict(
        (month, {
            'buy_total': Decimal('0'),
            'sell_total': Decimal('0'),
            'cost_sold': Decimal('0'),
            'revenue': Decimal('0'),
            'not_for_sale_total': Decimal('0'),
        })
        for month in _iterate_months(start_month, end_month)
    )

    currency_to_chf = {}
    for item in items_with_buy_dates:
        currency = item.currency
        if currency not in currency_to_chf:
            currency_to_chf[currency] = Decimal(str(get_fx_rates(currency).get('CHF', 1.0)))

    for item in items_with_buy_dates:
        buy_month = _month_start(item.buy_date)
        fx_rate = currency_to_chf.get(item.currency, Decimal('1'))
        buy_value_chf = to_dec(item.price) * fx_rate
        if item.not_for_sale:
            monthly_totals[buy_month]['not_for_sale_total'] += buy_value_chf
        else:
            monthly_totals[buy_month]['buy_total'] += buy_value_chf

        if item.sell_price is not None and item.sell_date:
            sell_month = _month_start(item.sell_date)
            sell_total = to_dec(item.sell_price)
            revenue = sell_total - buy_value_chf
            monthly_totals.setdefault(sell_month, {
                'buy_total': Decimal('0'),
                'sell_total': Decimal('0'),
                'cost_sold': Decimal('0'),
                'revenue': Decimal('0'),
                'not_for_sale_total': Decimal('0'),
            })
            monthly_totals[sell_month]['sell_total'] += sell_total
            monthly_totals[sell_month]['cost_sold'] += buy_value_chf
            monthly_totals[sell_month]['revenue'] += revenue

    results = []
    for month, data in monthly_totals.items():
        buy_total = data['buy_total'].quantize(Q, rounding=ROUND_HALF_UP)
        sell_total = data['sell_total'].quantize(Q, rounding=ROUND_HALF_UP)
        revenue = data['revenue'].quantize(Q, rounding=ROUND_HALF_UP)
        not_for_sale_total = data['not_for_sale_total'].quantize(Q, rounding=ROUND_HALF_UP)
        cost_sold = data['cost_sold']
        roi_pct = None
        if cost_sold > 0:
            roi_pct = (data['revenue'] / cost_sold * Decimal('100')).quantize(Q, rounding=ROUND_HALF_UP)

        results.append({
            'month': month,
            'label': month.strftime('%B %Y'),
            'buy_total': buy_total,
            'sell_total': sell_total,
            'revenue': revenue,
            'not_for_sale_total': not_for_sale_total,
            'cost_sold': cost_sold.quantize(Q, rounding=ROUND_HALF_UP),
            'roi_pct': roi_pct,
        })

    return results


def calculate_sale_time_stats(items):
    total_items = len(items)
    sellable_items = sum(1 for item in items if not item.not_for_sale)
    sale_durations = [
        (item.sell_date - item.buy_date).days
        for item in items
        if item.buy_date and item.sell_date
    ]

    sold_items = len(sale_durations)
    average_sale_days = None
    if sold_items:
        average_sale_days = (
            Decimal(sum(sale_durations)) / Decimal(sold_items)
        ).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)

    active_listings = sum(
        1 for item in items if not item.sell_date and not item.not_for_sale
    )
    not_for_sale_inventory = sum(
        1 for item in items if not item.sell_date and item.not_for_sale
    )

    sell_through_pct = None
    
    # Sell-through rate should only consider "Active" items (cards intended for sale)
    # Exclude "Booster Box Investment", "For Grading", "Personal Collection" etc.
    active_items_pool = [
        item for item in items 
        if item.category == 'Active' or (item.category is None and not item.not_for_sale)
    ]
    
    # From this pool, how many are sold?
    pool_sold = sum(1 for item in active_items_pool if item.sell_date)
    pool_total = len(active_items_pool)

    if pool_total > 0:
        sell_through_pct = (
            (Decimal(pool_sold) / Decimal(pool_total)) * Decimal('100')
        ).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)

    return {
        'average_sale_days': average_sale_days,
        'sold_items': sold_items,
        'active_listings': active_listings,
        'not_for_sale_inventory': not_for_sale_inventory,
        'total_items': total_items,
        'sellable_items': sellable_items,
        'sell_through_pct': sell_through_pct,
    }


@tracker_bp.route('/api/cache_ts')
def api_cache_ts():
    return jsonify({"ts": PRICECHARTING_CACHE_TS})

@tracker_bp.route('/')
def item_list():
    with get_db_session() as session:
        items = session.query(Item).order_by(Item.buy_date.desc()).all()
        fx_chf = get_fx_rates("CHF")
        charting_prices = get_charting_prices(items)
        fx_dict = calculate_fx_dict(items, charting_prices, fx_chf)
        possible_gain_chf = calculate_possible_gain_chf(items, charting_prices, fx_chf)

        # Single Card Prices map for live gain/loss
        card_ids = [item.card_id for item in items if item.card_id]
        single_card_prices = get_latest_card_prices(session, card_ids)
            
        # Enrich fx_dict with gain/loss logic
        for item in items:
            entry = fx_dict.get(item.id)
            if entry and item.card_id:
                current_eur = single_card_prices.get(item.card_id)
                if current_eur is not None:
                    buy_eur = entry["price_eur"]
                    # Calculate gain
                    gain_eur = current_eur - buy_eur
                    entry["live_gain_eur"] = gain_eur
                    entry["current_value_eur"] = current_eur
                else:
                    entry["live_gain_eur"] = None
                    entry["current_value_eur"] = None
            elif entry:
                 entry["live_gain_eur"] = None
                 entry["current_value_eur"] = None

        # Filter logic
        category_filter = request.args.get('category_filter', 'All')
        
        if category_filter != 'All':
            visible_items = [item for item in items if item.category == category_filter]
        else:
            visible_items = items

        invested = sum(
            float(item.price) * get_fx_rates(item.currency)["CHF"]
            for item in items
            if not item.not_for_sale and not (item.sell_price and item.sell_date)
        )
        realized = sum(
            (float(item.sell_price) - float(item.price) * get_fx_rates(item.currency)["CHF"])
            for item in items if item.sell_price and item.sell_date
        )
        sold_invested_chf = sum(
            float(item.price) * get_fx_rates(item.currency)["CHF"]
            for item in items if item.sell_price and item.sell_date
        )
        total_roi_pct = (realized / sold_invested_chf) * 100.0 if sold_invested_chf > 0 else None
        bought_finished_chf = sold_invested_chf
        sold_finished_chf = sum(
            float(item.sell_price)
            for item in items if item.sell_price and item.sell_date
        )
        not_for_sale_total_chf = sum(
            float(item.price) * get_fx_rates(item.currency)["CHF"]
            for item in items if item.not_for_sale
        )

        return render_template(
            'tracker/item_list.html',
            items=visible_items,
            fx_dict=fx_dict,
            charting_prices=charting_prices,
            invested=invested,
            realized=realized,
            possible_gain_chf=possible_gain_chf,
            total_roi_pct=total_roi_pct,
            bought_finished_chf=bought_finished_chf,
            sold_finished_chf=sold_finished_chf,
            cache_ts=PRICECHARTING_CACHE_TS,

            not_for_sale_total_chf=not_for_sale_total_chf,
            category_filter=category_filter,
        )


def calculate_financials(items, monthly_stats, single_card_prices=None):
    fx_chf = get_fx_rates("CHF")
    charting_prices = get_charting_prices(items)
    
    total_deployed = Decimal('0')
    current_holdings = Decimal('0')
    not_for_sale_total = Decimal('0')
    sold_cost_basis = Decimal('0')
    inventory_cost_basis = Decimal('0')
    inventory_count = 0
    
    # New Categories
    booster_box_total = Decimal('0')
    grading_total = Decimal('0')

    for item in items:
        fx = Decimal(str(get_fx_rates(item.currency).get('CHF', 1.0)))
        cost_chf = to_dec(item.price) * fx
        
        total_deployed += cost_chf
        
        # Category-based totals
        if item.category == "Personal Collection" or item.not_for_sale:
            not_for_sale_total += cost_chf
        elif item.category == "Booster Box Investment":
            booster_box_total += cost_chf
        elif item.category == "For Grading":
            grading_total += cost_chf
        
        if item.sell_date:
            sold_cost_basis += cost_chf
        else:
            current_holdings += cost_chf
            # Active Inventory logic: Not sold AND (Active OR Booster OR Grading)
            # Basically anything not Personal Collection and not Sold
            if item.category != "Personal Collection" and not item.not_for_sale:
                inventory_cost_basis += cost_chf
                inventory_count += 1

    unrealized_pl = Decimal(str(calculate_possible_gain_chf(items, charting_prices, fx_chf)))
    
    # Add gain from not_for_sale items to Unrealized P&L
    not_for_sale_gain_usd = 0.0
    for item in items:
        if item.not_for_sale and not item.sell_date:
             paid_usd = get_paid_usd(item)
             ref_usd = get_reference_usd(item, charting_prices)
             if ref_usd is not None:
                 not_for_sale_gain_usd += (ref_usd - paid_usd)
    
    if fx_chf.get("USD"):
        unrealized_pl += Decimal(str(not_for_sale_gain_usd / fx_chf["USD"]))

    # Total Live Gain (CHF) calculation
    total_live_gain_chf = Decimal('0')
    if single_card_prices:
        eur_to_chf = Decimal(str(fx_chf.get("EUR", 1.0)))
        usd_to_eur = Decimal(str(get_fx_rates("USD").get("EUR", 1.0))) # For converting buy price if needed, but we have calculate_fx_dict logic
        
        # We need to replicate calculate_fx_dict's buy price logic partially or assume EUR price is available
        # Actually simplest to just re-do buy_eur calculation here for items with card_id
        for item in items:
            if item.card_id and item.card_id in single_card_prices:
                current_eur = single_card_prices[item.card_id]
                if current_eur is not None:
                    # Calculate Buy Price in EUR
                    fx_rates = get_fx_rates(item.currency)
                    buy_price_eur = float(item.price) * fx_rates.get("EUR", 1.0)
                    
                    gain_eur = current_eur - buy_price_eur
                    gain_chf = Decimal(str(gain_eur)) * eur_to_chf
                    total_live_gain_chf += gain_chf

    realized_pl = sum((entry['revenue'] for entry in monthly_stats), Decimal('0'))
    total_net = (realized_pl + unrealized_pl)

    total_roi_pct = None
    if sold_cost_basis > 0:
        total_roi_pct = (realized_pl / sold_cost_basis * Decimal('100')).quantize(Q, rounding=ROUND_HALF_UP)

    return {
        "total_deployed": total_deployed.quantize(Q, rounding=ROUND_HALF_UP),
        "current_holdings": current_holdings.quantize(Q, rounding=ROUND_HALF_UP),
        "not_for_sale_total": not_for_sale_total.quantize(Q, rounding=ROUND_HALF_UP),
        "sold_cost_basis": sold_cost_basis.quantize(Q, rounding=ROUND_HALF_UP),
        "inventory_cost_basis": inventory_cost_basis.quantize(Q, rounding=ROUND_HALF_UP),
        "inventory_count": inventory_count,
        "booster_box_total": booster_box_total.quantize(Q, rounding=ROUND_HALF_UP),
        "grading_total": grading_total.quantize(Q, rounding=ROUND_HALF_UP),
        "realized_pl": realized_pl.quantize(Q, rounding=ROUND_HALF_UP),
        "unrealized_pl": unrealized_pl.quantize(Q, rounding=ROUND_HALF_UP),
        "revenue": realized_pl.quantize(Q, rounding=ROUND_HALF_UP),  # Kept for compatibility
        "total_net": total_net.quantize(Q, rounding=ROUND_HALF_UP),
        "buy_total": sum((entry['buy_total'] for entry in monthly_stats), Decimal('0')).quantize(Q, rounding=ROUND_HALF_UP),
        "sell_total": sum((entry['sell_total'] for entry in monthly_stats), Decimal('0')).quantize(Q, rounding=ROUND_HALF_UP),
        "total_roi_pct": total_roi_pct,
        "total_live_gain_chf": total_live_gain_chf.quantize(Q, rounding=ROUND_HALF_UP),
    }


@tracker_bp.route('/stats')
def stats_overview():
    with get_db_session() as session:
        items = session.query(Item).order_by(Item.buy_date.asc()).all()
        monthly_stats = calculate_monthly_tracker_stats(items)
        sale_time_stats = calculate_sale_time_stats(items)

        # Chart Data
        chart_data = {
            'labels': [entry['label'] for entry in monthly_stats],
            'bought': [float(entry['buy_total']) for entry in monthly_stats],
            'sold': [float(entry['sell_total']) for entry in monthly_stats],
            'revenue': [float(entry['revenue']) for entry in monthly_stats],
        }

        # Financials
        card_ids = [item.card_id for item in items if item.card_id]
        single_card_prices = get_latest_card_prices(session, card_ids)
        totals = calculate_financials(items, monthly_stats, single_card_prices)
        
        insight_suggestions = [
            'Track the sell-through rate over time to spot changes in demand.',
            'Review active listings that have been live the longest to consider repricing or promotions.',
            'Compare the capital tied up in not-for-sale items against realized revenue to guide future purchases.',
        ]

    return render_template(
        'tracker/stats_overview.html',
        monthly_stats=monthly_stats,
        totals=totals,
        summary_stats=sale_time_stats,
        insight_suggestions=insight_suggestions,
        chart_data=chart_data,
    )


@tracker_bp.route('/stats/revenue-trend')
def revenue_trend():
    with get_db_session() as session:
        items = session.query(Item).order_by(Item.buy_date.asc()).all()
        monthly_stats = calculate_monthly_tracker_stats(items)

    chart_labels = [entry['label'] for entry in monthly_stats]
    chart_revenue = [float(entry['revenue']) for entry in monthly_stats]

    return render_template(
        'tracker/revenue_chart.html',
        monthly_stats=monthly_stats,
        chart_labels=chart_labels,
        chart_revenue=chart_revenue,
    )

@tracker_bp.route('/add', methods=['GET', 'POST'])
def item_add():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        buy_date = request.form.get('buy_date')
        link = request.form.get('link', '').strip() or None
        graded = 1 if request.form.get('graded') else 0
        price = float(request.form.get('price') or 0)
        currency = request.form.get('currency', 'CHF')
        sell_price_val = request.form.get('sell_price')
        sell_price = float(sell_price_val) if sell_price_val else None
        sell_date_val = request.form.get('sell_date')
        sell_date = date.fromisoformat(sell_date_val) if sell_date_val else None
        not_for_sale = 1 if request.form.get('not_for_sale') else 0

        image = request.files.get("image")
        # The line below was redundant in the provided snippet, as not_for_sale was already defined.
        # not_for_sale = 1 if request.form.get("not_for_sale") else 0 
        category = request.form.get("category", "Active")
        
        # Sync not_for_sale with category for backward compatibility
        if category == "Personal Collection":
            not_for_sale = 1
        elif category == "Active":
            not_for_sale = 0
        # For other categories, default to not_for_sale=0 unless specified
        
        image_filename = None
        if image and image.filename:
            image_filename = save_uploaded_image(image) # Changed to save_uploaded_image to match existing function name

        with get_db_session() as session:
            new_item = Item(
                name=name,
                buy_date=date.fromisoformat(buy_date), # Kept original date conversion
                link=link,
                graded=graded,

                price=price,
                currency=currency,
                sell_price=sell_price,
                sell_date=sell_date,
                image=image_filename,
                not_for_sale=not_for_sale,
                category=category,
                card_id=int(request.form.get('card_id')) if request.form.get('card_id') else None
            )

            session.add(new_item) # Changed to new_item
            session.commit()
            flash('Item added.')
            return redirect(url_for('tracker.item_list'))
    return render_template('tracker/item_form.html', item=None, currencies=CURRENCIES)

@tracker_bp.route('/edit/<int:item_id>', methods=['GET', 'POST'])
def item_edit(item_id):
    with get_db_session() as session:
        item = session.get(Item, item_id)
        if not item:
            return 'Not found', 404
        if request.method == 'POST':
            item.name = request.form.get('name', '').strip()
            item.buy_date = date.fromisoformat(request.form.get('buy_date'))
            item.link = request.form.get('link', '').strip() or None
            item.graded = 1 if request.form.get('graded') else 0
            item.price = float(request.form.get('price') or 0)
            item.currency = request.form.get('currency', 'CHF')
            sp = request.form.get('sell_price')
            item.sell_price = float(sp) if sp else None
            sd = request.form.get('sell_date')
            item.sell_date = date.fromisoformat(sd) if sd else None
            item.not_for_sale = 1 if request.form.get('not_for_sale') else 0
            item.category = request.form.get('category', 'Active')
            cid_val = request.form.get('card_id')
            item.card_id = int(cid_val) if cid_val else None

            # Sync not_for_sale with category
            if item.category == 'Personal Collection':
                item.not_for_sale = 1
            elif item.category == 'Active':
                item.not_for_sale = 0

            image = request.files.get('image')
            if image and image.filename:
                item.image = save_uploaded_image(image)

            session.commit()
            flash('Item updated.')
            return redirect(url_for('tracker.item_list'))
        return render_template('tracker/item_form.html', item=item, currencies=CURRENCIES)


@tracker_bp.route('/delete/<int:item_id>', methods=['POST'])
def item_delete(item_id):
    global PRICECHARTING_CACHE_TS
    with get_db_session() as session:
        item = session.get(Item, item_id)
        if item:
            if item.image:
                try:
                    os.remove(os.path.join(MEDIA_ROOT, item.image))
                except OSError:
                    pass
            session.delete(item)
            session.commit()
            PRICECHARTING_CACHE.pop(item_id, None)
            PRICECHARTING_CACHE_TS = datetime.utcnow().isoformat()
            flash('Item deleted.')
        else:
            flash('Item not found.')
        return redirect(url_for('tracker.item_list'))

