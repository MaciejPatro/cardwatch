import os
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from threading import Thread
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

from db import get_session, Item
from tracker_utils.pricecharting import fetch_pricecharting_prices
from tracker_utils.utils import (
    get_reference_usd,
    get_reference_chf,
    get_paid_usd,
)
from tracker_utils.fx import get_fx_rates
from apscheduler.schedulers.background import BackgroundScheduler

tracker_bp = Blueprint('tracker', __name__, url_prefix='/tracker')

MEDIA_ROOT = os.path.join(os.path.dirname(__file__), 'media')
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

def save_uploaded_image(image):
    """Save an uploaded image with a unique filename."""
    filename = secure_filename(image.filename)
    unique_filename = f"{uuid.uuid4().hex}_{filename}"
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    relative_path = os.path.join('item_images', unique_filename)
    image.save(os.path.join(MEDIA_ROOT, relative_path))
    return relative_path

def to_dec(val):
    return Decimal(str(val)) if val is not None else Decimal('0')


def _update_cache(items):
    for item in items:
        if item.link:
            PRICECHARTING_CACHE[item.id] = fetch_pricecharting_prices(item.link)
        else:
            PRICECHARTING_CACHE[item.id] = {"psa10_usd": None, "ungraded_usd": None}
    global PRICECHARTING_CACHE_TS
    PRICECHARTING_CACHE_TS = datetime.utcnow().isoformat()


def refresh_pricecharting_cache():
    session = get_session()
    try:
        # Load all items so that entries without a link also get a cache slot.
        # This avoids the tracker appearing empty for items that don't have
        # an associated PriceCharting link. Those items simply get default
        # price information instead of being skipped entirely.
        items = session.query(Item).all()
    finally:
        session.close()
    _update_cache(items)


def schedule_pricecharting_refresh():
    scheduler = BackgroundScheduler()
    scheduler.add_job(refresh_pricecharting_cache, "interval", hours=6)
    scheduler.start()
    return scheduler


def init_tracker_scheduler():
    if os.environ.get("CARDWATCH_DISABLE_SCHEDULER"):
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
        Thread(target=_update_cache, args=(missing,), daemon=True).start()
    return charting_prices

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
        if not (item.sell_price and item.sell_date):
            paid_usd = get_paid_usd(item)
            ref_usd = get_reference_usd(item, charting_prices)
            if ref_usd is not None:
                possible_gain_usd += (ref_usd - paid_usd)
    return possible_gain_usd / fx_chf["USD"]


@tracker_bp.route('/api/cache_ts')
def api_cache_ts():
    return jsonify({"ts": PRICECHARTING_CACHE_TS})

@tracker_bp.route('/')
def item_list():
    session = get_session()
    try:
        items = session.query(Item).order_by(Item.buy_date.desc()).all()
        fx_chf = get_fx_rates("CHF")
        charting_prices = get_charting_prices(items)
        fx_dict = calculate_fx_dict(items, charting_prices, fx_chf)
        possible_gain_chf = calculate_possible_gain_chf(items, charting_prices, fx_chf)

        invested = sum(
            float(item.price) * get_fx_rates(item.currency)["CHF"]
            for item in items if not (item.sell_price and item.sell_date)
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

        return render_template(
            'tracker/item_list.html',
            items=items,
            fx_dict=fx_dict,
            charting_prices=charting_prices,
            invested=invested,
            realized=realized,
            possible_gain_chf=possible_gain_chf,
            total_roi_pct=total_roi_pct,
            bought_finished_chf=bought_finished_chf,
            sold_finished_chf=sold_finished_chf,
            cache_ts=PRICECHARTING_CACHE_TS,
        )
    finally:
        session.close()

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

        image = request.files.get('image')
        image_path = save_uploaded_image(image) if image and image.filename else None

        session = get_session()
        try:
            item = Item(
                name=name,
                buy_date=date.fromisoformat(buy_date),
                link=link,
                graded=graded,
                price=price,
                currency=currency,
                sell_price=sell_price,
                sell_date=sell_date,
                image=image_path,
            )
            session.add(item)
            session.commit()
            flash('Item added.')
            return redirect(url_for('tracker.item_list'))
        finally:
            session.close()
    return render_template('tracker/item_form.html', item=None, currencies=CURRENCIES)

@tracker_bp.route('/edit/<int:item_id>', methods=['GET', 'POST'])
def item_edit(item_id):
    session = get_session()
    try:
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

            image = request.files.get('image')
            if image and image.filename:
                item.image = save_uploaded_image(image)

            session.commit()
            flash('Item updated.')
            return redirect(url_for('tracker.item_list'))
        return render_template('tracker/item_form.html', item=item, currencies=CURRENCIES)
    finally:
        session.close()
