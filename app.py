import json
import os
import asyncio

from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from sqlalchemy import func
from db import (
    init_db,
    get_db_session,
    Product,
    Price,
    Daily,
    SingleCard,
    SingleCardPrice,
    SingleCardOffer,
    SingleCardDaily,
    PSA10Price,
    PSA10Offer,
    BookkeepingEntry,
    Item,
)
from scraper import (
    schedule_hourly,
    compute_trend,
    compute_single_trend,
    is_heads_up,
    scrape_once,
    scrape_single_cards,
)
from tracker_utils.deal_finder import calculate_deals, get_market_sentiment
from tracker_utils.invoice_parser import parse_cardmarket_invoice
import tracker_flask
from tracker_flask import tracker_bp, init_tracker_scheduler, save_uploaded_image
from datetime import datetime, timedelta

from config import Config
from logging_config import configure_logging

app = Flask(__name__)
app.config.from_object(Config)
configure_logging(app)

SINGLE_CARD_UPLOAD_FOLDER = os.path.join(app.config['MEDIA_ROOT'], "single_card_images")
os.makedirs(SINGLE_CARD_UPLOAD_FOLDER, exist_ok=True)

BOOKKEEPING_UPLOAD_FOLDER = os.path.join(app.config['MEDIA_ROOT'], "invoices")
os.makedirs(BOOKKEEPING_UPLOAD_FOLDER, exist_ok=True)

init_db()
if not app.config.get("CARDWATCH_DISABLE_SCHEDULER") and (
    os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug
):
    scheduler = schedule_hourly()

app.register_blueprint(tracker_bp)
tracker_scheduler = init_tracker_scheduler()



@app.route("/cardwatch/psa10")
def psa10_list():
    return render_template("psa10_list.html")

@app.route("/cardwatch/psa10/<int:cid>")
def psa10_details(cid):
    with get_db_session() as session:
        card = session.get(SingleCard, cid)
        if not card:
            return "Card not found", 404
        
        # Get offers
        offers = session.query(PSA10Offer).filter_by(card_id=cid).order_by(PSA10Offer.price).all()
        
        # Get history for chart
        history = session.query(PSA10Price).filter_by(card_id=cid).order_by(PSA10Price.ts).all()
        
        chart_data = {
            "labels": [h.ts.strftime("%Y-%m-%d") for h in history],
            "data": [h.low for h in history]
        }
        
    return render_template("psa10_details.html", card=card, offers=offers, chart_data=chart_data)

@app.route("/api/psa10")
def api_psa10_data():
    sort = request.args.get("sort", "name")
    order = request.args.get("order", "asc")
    limit = int(request.args.get("limit", 100))
    offset = int(request.args.get("offset", 0))
    search = request.args.get("search", "").lower()
    language = request.args.get("language", "All")

    with get_db_session() as session:
        query = session.query(SingleCard).filter(SingleCard.category == 'Liked')

        if search:
            query = query.filter(SingleCard.name.ilike(f"%{search}%"))

        if language and language != "All":
            query = query.filter(SingleCard.language == language)

        total = query.count()
        cards = query.all() # Fetch all to manual sort/filter since joins are complex with aggregations
        
        # Manual processing to get latest prices
        data = []
        for c in cards:
            # Latest PSA10
            psa10_entry = session.query(PSA10Price).filter_by(card_id=c.id).order_by(PSA10Price.ts.desc()).first()
            psa10_low = psa10_entry.low if psa10_entry else None
            
            # Latest Raw
            raw_entry = session.query(SingleCardPrice).filter_by(card_id=c.id).order_by(SingleCardPrice.ts.desc()).first()
            raw_low = raw_entry.low if raw_entry else None
            
            # PSA10 History (sparkline)
            history = session.query(PSA10Price.low).filter_by(card_id=c.id).order_by(PSA10Price.ts.desc()).limit(30).all()
            sparkline = [h[0] for h in history][::-1] if history else []

            # Calculate Ratio
            ratio = None
            if psa10_low and raw_low and raw_low > 0:
                ratio = psa10_low / raw_low

            data.append({
                "id": c.id,
                "name": c.name,
                "image_url": c.image_url,
                "psa10_low": psa10_low,
                "raw_low": raw_low,
                "ratio": ratio,
                "psa10_history": sparkline,
                "url": c.url
            })
            
        # Sorting
        reverse = (order == "desc")
        def sort_key(x):
            val = x.get(sort)
            if val is None:
                return -999999 if reverse else 999999
            return val

        data.sort(key=sort_key, reverse=reverse)
        
        # Pagination
        sliced = data[offset : offset + limit]

    return jsonify({"total": total, "rows": sliced})


@app.route("/")
def home():
    return render_template("home.html")


@app.context_processor
def inject_scraper_status():
    status_file = "scraper_status.json"
    status_data = {}
    if os.path.exists(status_file):
        try:
            with open(status_file, "r") as f:
                status_data = json.load(f)
        except Exception:
            pass
    return dict(scraper_status=status_data)

@app.route("/cardwatch")
@app.route("/cardwatch/")
def index():
    with get_db_session() as s:
        products = s.query(Product).order_by(Product.name).all()
        model = []
        now = datetime.utcnow()
        for p in products:
            trend = compute_trend(s, p.id)
            heads, now_low, avg7 = is_heads_up(s, p.id)

            # current (latest) and first (oldest) recorded prices
            latest = (s.query(Price)
                      .filter_by(product_id=p.id)
                      .order_by(Price.ts.desc())
                      .first())
            first  = (s.query(Price)
                      .filter_by(product_id=p.id)
                      .order_by(Price.ts.asc())
                      .first())

            # past prices for percent changes
            def get_past(delta):
                return (s.query(Price)
                        .filter(Price.product_id == p.id,
                                Price.ts <= now - delta)
                        .order_by(Price.ts.desc())
                        .first())

            past24 = get_past(timedelta(hours=24))
            past7  = get_past(timedelta(days=7))
            past30 = get_past(timedelta(days=30))

            def pct(cur, prev):
                if cur is None or prev is None or prev == 0:
                    return None
                return (cur - prev) / prev * 100.0

            current_low = latest.low if latest else None

            model.append({
                "id": p.id,
                "name": p.name,
                "country": p.country,
                "url": p.url,
                "enabled": bool(p.is_enabled),

                "trend": trend,
                "heads": heads,
                "avg7": avg7,

                "current_low": current_low,
                "first_low": first.low if first else None,
                "pct24": pct(current_low, past24.low if past24 else None),
                "pct7":  pct(current_low, past7.low if past7 else None),
                "pct30": pct(current_low, past30.low if past30 else None),
                "supply": latest.supply if latest else None,

                "last_ts": latest.ts.strftime("%Y-%m-%d %H:%M") if latest else None,
            })
        return render_template("index.html", products=model)



def calculate_card_stats(session, card):
    now = datetime.utcnow()
    latest = (
        session.query(SingleCardPrice)
        .filter_by(card_id=card.id)
        .order_by(SingleCardPrice.ts.desc())
        .first()
    )
    first = (
        session.query(SingleCardPrice)
        .filter_by(card_id=card.id)
        .filter(SingleCardPrice.low.isnot(None))
        .order_by(SingleCardPrice.ts.asc())
        .first()
    )

    def get_past(delta):
        return (
            session.query(SingleCardPrice)
            .filter(
                SingleCardPrice.card_id == card.id,
                SingleCardPrice.ts <= now - delta,
            )
            .order_by(SingleCardPrice.ts.desc())
            .first()
        )

    past7 = get_past(timedelta(days=7))
    past30 = get_past(timedelta(days=30))
    past90 = get_past(timedelta(days=90))

    def pct(cur, prev):
        if cur is None or prev is None or prev == 0:
            return None
        return (cur - prev) / prev * 100.0

    current_low = latest.low if latest else None
    current_supply = latest.supply if latest else None
    avg5 = latest.avg5 if latest else None

    # Indicators
    supply_drop = False
    if current_supply is not None and past7 and past7.supply:
        if current_supply < past7.supply * 0.9:
            supply_drop = True
    
    price_outlier = False
    if current_low is not None and avg5:
        if current_low < avg5 * 0.7:
            price_outlier = True

    # Fetch last 30 days history for sparkline
    # Limit to reasonable number of points (e.g. latest 100) to keep table payload light
    history_query = (
        session.query(SingleCardPrice.low)
        .filter(SingleCardPrice.card_id == card.id)
        .filter(SingleCardPrice.ts >= now - timedelta(days=30))
        .filter(SingleCardPrice.low.isnot(None))
        .order_by(SingleCardPrice.ts.asc())
        .all()
    )
    # Basic downsampling if too many points (simple skip)
    # Basic downsampling if too many points (simple skip)
    history_values = [r.low for r in history_query]
    
    # Sentiment Badge Logic
    trend = compute_single_trend(session, card.id)
    sentiment_badge = "Stagnant"
    supply_trend_up = False
    
    # Check simple supply trend (current vs 7 days ago approx)
    if current_supply is not None and past7 and past7.supply:
        if current_supply > past7.supply * 1.05:
            supply_trend_up = True

    if trend == "up" and supply_drop:
        sentiment_badge = "Bullish"
    elif trend == "down" and supply_trend_up:
        sentiment_badge = "Bearish"

    return {
        "id": card.id,
        "name": card.name,
        "url": card.url,
        "language": card.language,
        "condition": card.condition,
        "image_url": card.image_url,
        "trend": trend,
        "from_price": latest.from_price if latest else None,
        "price_trend": latest.price_trend if latest else None,
        "avg7_price": latest.avg7_price if latest else None,
        "avg1_price": latest.avg1_price if latest else None,
        "current_low": current_low,
        "pct30": pct(current_low, past30.low if past30 else None),
        "pct90": pct(current_low, past90.low if past90 else None),
        "pct_all": pct(current_low, first.low if first else None),
        "last_ts": latest.ts.strftime("%Y-%m-%d %H:%M") if latest else None,
        "supply": current_supply,
        "supply_drop": supply_drop,
        "price_outlier": price_outlier,
        "category": card.category,
        "history_30d": history_values,
        "sentiment_badge": sentiment_badge,
    }


@app.route("/cardwatch/singles")
@app.route("/cardwatch/singles/")
def singles():
    with get_db_session() as s:
        sentiment = get_market_sentiment(s)
    return render_template("singles.html", sentiment=sentiment)


@app.route("/cardwatch/deals")
def deals():
    # Parse filter params
    is_submitted = request.args.get("submitted") == "true"
    
    # Pagination
    page = int(request.args.get("page", 1))
    per_page = 20
    
    if is_submitted:
        show_promos = request.args.get("promos") == "true"
        show_packs = request.args.get("packs") == "true"
        # Language: "English", "Japanese", "All"
        language = request.args.get("language", "English")
    else:
        # Defaults
        show_promos = False
        show_packs = False
        language = "English"
    
    with get_db_session() as s:
        # Get ALL matching deals (sorted)
        all_deals = calculate_deals(s, include_promos=show_promos, language=language, include_packs=show_packs)
    
    # Pagination Logic
    total_deals = len(all_deals)
    total_pages = (total_deals + per_page - 1) // per_page
    
    # Slice
    start = (page - 1) * per_page
    end = start + per_page
    paginated_deals = all_deals[start:end]
    
    return render_template("deals.html", 
                           deals=paginated_deals, 
                           show_promos=show_promos, 
                           language=language, 
                           show_packs=show_packs,
                           page=page,
                           total_pages=total_pages)

@app.route("/cardwatch/single/<int:cid>/category", methods=["POST"])
def update_single_category(cid):
     data = request.json
     new_category = data.get("category")
     # Allow empty string to clear category
     
     with get_db_session() as s:
         card = s.get(SingleCard, cid)
         if not card:
             return jsonify({"success": False, "error": "Not found"}), 404
         
         card.category = new_category
         s.commit()
         return jsonify({"success": True})


@app.route("/cardwatch/singles/delete/<int:cid>", methods=["POST"])
def delete_single(cid):
    with get_db_session() as s:
        card = s.get(SingleCard, cid)
        if not card:
            return jsonify({"success": False, "error": "Not found"}), 404
        
        # Delete image if exists
        if card.image_url:
             # Handle both full absolute path and relative path cases if needed
             # Logic in save_uploaded_image returns relative path from MEDIA_ROOT
             try:
                 # Check if it's a local file relative to MEDIA_ROOT
                 full_path = os.path.join(app.config['MEDIA_ROOT'], card.image_url)
                 if os.path.exists(full_path):
                     os.remove(full_path)
             except OSError as e:
                 print(f"Error deleting image {full_path}: {e}")

        s.delete(card)
        s.commit()
        return jsonify({"success": True})


@app.route("/cardwatch/api/singles/sets")
def api_singles_sets():
    with get_db_session() as s:
        # Get distinct sets, exclude None
        sets = [
            r[0] for r in s.query(SingleCard.set_name)
            .distinct()
            .filter(SingleCard.set_name.isnot(None))
            .order_by(SingleCard.set_name)
            .all()
        ]
        return jsonify(sets)


@app.route("/cardwatch/api/singles/list")
def api_singles_list():
    offset = int(request.args.get("offset", 0))
    limit = int(request.args.get("limit", 10))
    search = request.args.get("search", "").strip()
    sort_field = request.args.get("sort", "name")
    sort_order = request.args.get("order", "asc")
    category_filter = request.args.get("category", "").strip()
    language_filter = request.args.get("language", "").strip()
    game_filter = request.args.get("game", "").strip()
    set_filter = request.args.get("set_name", "").strip()
    min_price = float(request.args.get("min_price", 0)) if request.args.get("min_price") else None
    max_price = float(request.args.get("max_price", 0)) if request.args.get("max_price") else None

    with get_db_session() as s:
        query = s.query(SingleCard)

        # Search
        if search:
            query = query.filter(SingleCard.name.ilike(f"%{search}%"))
        
        # Game Filter
        if game_filter and game_filter != "All":
            query = query.filter(SingleCard.game == game_filter)

        # Set Filter
        if set_filter and set_filter != "All":
            query = query.filter(SingleCard.set_name == set_filter)

        # Language Filter
        if language_filter and language_filter != "All":
            query = query.filter(SingleCard.language == language_filter)

        # Category Filter
        if category_filter:
            if category_filter == "None": # Special case for filtering empty categories
                 query = query.filter((SingleCard.category == None) | (SingleCard.category == ""))
            else:
                 query = query.filter(SingleCard.category == category_filter)
        else:
            # Default: Exclude "Ignore" category cards only when no specific category is selected
            # logic: "All Categories" means "All visible categories" (not ignored ones)
            query = query.filter((SingleCard.category != 'Ignore') | (SingleCard.category.is_(None)))
        
        # Price Filtering Subquery
        from sqlalchemy import text
        
        # Price Subquery for filtering/sorting
        # Re-using the logic from sorting to get the latest price/supply
        # Creating a reusable subquery factory or just defining it cleanly here
        
        if min_price is not None or max_price is not None:
             price_subq = (
                 s.query(SingleCardPrice.low)
                 .filter(SingleCardPrice.card_id == SingleCard.id)
                 .order_by(SingleCardPrice.ts.desc())
                 .limit(1)
                 .scalar_subquery()
             )
             if min_price is not None:
                 query = query.filter(price_subq >= min_price)
             if max_price is not None:
                 query = query.filter(price_subq <= max_price)

        # Sorting
        if sort_field == "name":
            col = SingleCard.name
            query = query.order_by(col.asc() if sort_order == "asc" else col.desc())
        elif sort_field == "language":
            col = SingleCard.language
            query = query.order_by(col.asc() if sort_order == "asc" else col.desc())
        elif sort_field == "current":
             subq = (
                 s.query(SingleCardPrice.low)
                 .filter(SingleCardPrice.card_id == SingleCard.id)
                 .order_by(SingleCardPrice.ts.desc())
                 .limit(1)
                 .scalar_subquery()
             )
             query = query.order_by(subq.asc() if sort_order == "asc" else subq.desc())
        elif sort_field == "supply":
             subq = (
                 s.query(SingleCardPrice.supply)
                 .filter(SingleCardPrice.card_id == SingleCard.id)
                 .order_by(SingleCardPrice.ts.desc())
                 .limit(1)
                 .scalar_subquery()
             )
             query = query.order_by(subq.asc() if sort_order == "asc" else subq.desc())
        elif sort_field == "pct_all":
             # Subquery for current price (latest)
             current_subq = (
                 s.query(SingleCardPrice.low)
                 .filter(SingleCardPrice.card_id == SingleCard.id)
                 .order_by(SingleCardPrice.ts.desc())
                 .limit(1)
                 .scalar_subquery()
             )
             # Subquery for first price (oldest with non-null low)
             first_subq = (
                 s.query(SingleCardPrice.low)
                 .filter(SingleCardPrice.card_id == SingleCard.id)
                 .filter(SingleCardPrice.low.isnot(None))
                 .order_by(SingleCardPrice.ts.asc())
                 .limit(1)
                 .scalar_subquery()
             )
             
             # (current - first) / first
             # Handle division by zero or nulls gracefully if needed, though SQL comparison rules might handle nulls
             diff = (current_subq - first_subq) / first_subq
             
             query = query.order_by(diff.asc() if sort_order == "asc" else diff.desc())
        else:
            # Default fallback sort
            query = query.order_by(SingleCard.name.asc())

        total = query.count()
        cards = query.offset(offset).limit(limit).all()

        rows = []
        for c in cards:
            stats = calculate_card_stats(s, c)
            # Flatten stats into row structure expected by table
            rows.append(stats)

        return jsonify({"total": total, "rows": rows})



@app.route("/cardwatch/single/<int:cid>")
def single_card(cid):
    with get_db_session() as s:
        card = s.get(SingleCard, cid)
        if not card:
            return "Not found", 404
        latest = (
            s.query(SingleCardPrice)
            .filter_by(card_id=card.id)
            .order_by(SingleCardPrice.ts.desc())
            .first()
        )
        stats = calculate_card_stats(s, card)
        return render_template("single_card.html", card=card, latest=latest, stats=stats)


@app.route("/cardwatch/seller-bundles")
@app.route("/cardwatch/seller-bundles/")
def seller_bundles():
    # Filter params
    f_lang = request.args.get("language", "All")
    f_country = request.args.get("country", "All")
    try:
        f_min_cards = int(request.args.get("min_cards", 0))
    except (ValueError, TypeError):
        f_min_cards = 0

    with get_db_session() as s:
        # Base query
        query = (
            s.query(SingleCardOffer)
            .join(SingleCard)
            .filter(SingleCard.is_enabled == 1)
        )

        # Apply filters
        if f_lang != "All":
            query = query.filter(SingleCard.language == f_lang)
        
        if f_country != "All":
            query = query.filter(SingleCardOffer.country == f_country)

        offers = query.all()

        # Get available options for dropdowns (global, unfiltered list mainly, or filtered? usually global for filters)
        # Actually standard UX is to show all available options
        all_languages = [r[0] for r in s.query(SingleCard.language).distinct().order_by(SingleCard.language).all() if r[0]]
        all_countries = [r[0] for r in s.query(SingleCardOffer.country).distinct().order_by(SingleCardOffer.country).all() if r[0]]

        if not offers:
            return render_template("seller_bundles.html", 
                                   sellers=[], 
                                   all_languages=all_languages, 
                                   all_countries=all_countries,
                                   f_lang=f_lang,
                                   f_country=f_country,
                                   f_min_cards=f_min_cards)

        # For "cheapest" calculation, we should probably consider the global cheapest for that card,
        # OR the cheapest within the filtered set?
        # Usually "cheapest" means "market price", so global lowest is better reference.
        # Let's fetch global cheapest for involved cards to be fair.
        # But to avoid N+1, let's just fetch all enabled cards again or rely on what we have.
        # Actually, let's use the query logic from before but careful about what "cheapest" means.
        # If I filter by "Japan", do I compare against "Japan" cheapest or "Global" cheapest?
        # The prompt says: "within 20% of the lowest price for each card."
        # Usually that implies global lowest.
        
        # Implementation: Fetch ALL offers for the relevant cards to determine global lowest,
        # THEN filter the offers we want to display.
        # But that might be heavy. 
        # For now, let's stick to calculating cheapest based on what we fetched, 
        # BUT if we filter by country, "lowest price" might become "lowest price in that country".
        # If the user wants to see if a bundle is good deal globally, comparing to local only might be misleading.
        # However, checking "global cheapest" requires querying all offers for these cards.
        
        # Let's do a separate query for "global cheapest" for the cards present in our filtered offers.
        card_ids = set(o.card_id for o in offers)
        
        # Get global cheapest for these cards
        global_cheapest_rows = (
             s.query(SingleCardOffer.card_id, func.min(SingleCardOffer.price))
             .filter(SingleCardOffer.card_id.in_(card_ids))
             .filter(SingleCardOffer.price.isnot(None))
             .group_by(SingleCardOffer.card_id)
             .all()
        )
        cheapest_map = {row[0]: row[1] for row in global_cheapest_rows}

        cards = s.query(SingleCard).filter(SingleCard.id.in_(card_ids)).all()
        card_lookup = {c.id: c for c in cards}

        seller_map = {}
        for offer in offers:
            baseline = cheapest_map.get(offer.card_id)
            if baseline is None or offer.price is None:
                continue
            
            # 20% rule
            if offer.price > baseline * 1.2:
                continue

            key = (offer.seller_name, offer.country)
            entry = seller_map.setdefault(
                key,
                {
                    "seller": offer.seller_name,
                    "country": offer.country,
                    "cards": [],
                    "total_upcharge": 0.0,
                    "bundle_total": 0.0,
                    "cheapest_total": 0.0,
                },
            )

            upcharge = offer.price - baseline
            entry["cards"].append(
                {
                    "card": card_lookup.get(offer.card_id),
                    "price": offer.price,
                    "baseline": baseline,
                    "upcharge": upcharge,
                }
            )
            entry["total_upcharge"] += upcharge
            entry["bundle_total"] += offer.price
            entry["cheapest_total"] += baseline

        # Filter by min_cards
        sellers = [
            s for s in seller_map.values() 
            if s["total_upcharge"] <= 20.0 and len(s["cards"]) >= f_min_cards
        ]
        sellers.sort(
            key=lambda s: (-len(s["cards"]), s["total_upcharge"], s["bundle_total"])
        )

        return render_template("seller_bundles.html", 
                               sellers=sellers,
                               all_languages=all_languages, 
                               all_countries=all_countries,
                               f_lang=f_lang,
                               f_country=f_country,
                               f_min_cards=f_min_cards)

@app.route("/cardwatch/product/<int:pid>")
def product(pid):
    with get_db_session() as s:
        p = s.get(Product, pid)
        if not p:
            return "Not found", 404
        return render_template("product.html", product=p)


@app.route("/cardwatch/api/product/<int:pid>/series")
def api_series(pid):
    with get_db_session() as s:
        points = s.query(Price).filter_by(product_id=pid).order_by(Price.ts).all()
        return jsonify([{"t": pr.ts.isoformat(), "low": pr.low, "avg5": pr.avg5} for pr in points])

@app.route("/cardwatch/api/product/<int:pid>/daily")
def api_daily(pid):
    with get_db_session() as s:
        points = s.query(Daily).filter_by(product_id=pid).order_by(Daily.day).all()
        return jsonify([{"d": d.day.isoformat(), "low": d.low, "avg": d.avg} for d in points])


@app.route("/cardwatch/api/single/<int:cid>/series")
def api_single_series(cid):
    with get_db_session() as s:
        points = (
            s.query(SingleCardPrice)
            .filter_by(card_id=cid)
            .order_by(SingleCardPrice.ts)
            .all()
        )
        return jsonify(
            [
                {"t": pr.ts.isoformat(), "low": pr.low, "avg5": pr.avg5}
                for pr in points
            ]
        )


@app.route("/cardwatch/api/single/<int:cid>/daily")
def api_single_daily(cid):
    with get_db_session() as s:
        points = (
            s.query(SingleCardDaily)
            .filter_by(card_id=cid)
            .order_by(SingleCardDaily.day)
            .all()
        )
        return jsonify(
            [
                {"d": d.day.isoformat(), "low": d.low, "avg": d.avg}
                for d in points
            ]
        )

@app.route("/cardwatch/add", methods=["POST"])
def add():
    name = request.form.get("name", "").strip()
    url = request.form.get("url", "").strip()
    country = request.form.get("country", "").strip()
    if not (name and url and country):
        flash("Please provide name, url, and country.")
        return redirect(url_for("index"))
    pid = None
    try:
        with get_db_session() as s:
            p = Product(name=name, url=url, country=country)
            s.add(p)
            s.commit()
            pid = p.id
            flash("Added.")
    except Exception as e:
        flash(f"Error: {e}")
    if pid:
        try:
            asyncio.run(scrape_once([pid]))
        except Exception as e:
            print(f"[app] Error scraping new product {pid}: {e}")
    return redirect(url_for("index"))


@app.route("/cardwatch/singles/add", methods=["POST"])
def add_single():
    name = request.form.get("name", "").strip()
    url = request.form.get("url", "").strip()
    language = request.form.get("language", "").strip()
    image_file = request.files.get("image")

    if not (name and url and language):
        flash("Please provide name, url, and language.")
        return redirect(url_for("singles"))

    if language not in ("English", "Japanese"):
        flash("Language must be English or Japanese.")
        return redirect(url_for("singles"))

    image_url = None
    if image_file and image_file.filename:
        try:
            image_url = save_uploaded_image(
                image_file, upload_folder=SINGLE_CARD_UPLOAD_FOLDER
            )
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for("singles"))

    cid = None
    try:
        with get_db_session() as s:
            card = SingleCard(
                name=name,
                url=url,
                language=language,
                condition="Mint or Near Mint",
                image_url=image_url,
            )
            s.add(card)
            s.commit()
            cid = card.id
            flash("Single card added.")
    except Exception as e:
        flash(f"Error: {e}")

    if cid:
        try:
            asyncio.run(scrape_single_cards([cid]))
        except Exception as e:
            print(f"[app] Error scraping new single card {cid}: {e}")
    return redirect(url_for("singles"))

@app.route("/cardwatch/edit/<int:pid>", methods=["GET", "POST"])
def edit(pid):
    with get_db_session() as s:
        p = s.get(Product, pid)
        if not p:
            return "Not found", 404
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            url = request.form.get("url", "").strip()
            country = request.form.get("country", "").strip()
            if not (name and url and country):
                flash("Please provide name, url, and country.")
            else:
                try:
                    p.name = name
                    p.url = url
                    p.country = country
                    s.commit()
                    flash("Updated.")
                    return redirect(url_for("index"))
                except Exception as e:
                    s.rollback()
                    flash(f"Error: {e}")
        return render_template("edit.html", product=p)

@app.route("/cardwatch/toggle/<int:pid>")
def toggle(pid):
    with get_db_session() as s:
        p = s.query(Product).get(pid)
        if not p: return "Not found", 404
        p.is_enabled = 0 if p.is_enabled else 1
        s.commit()
        return redirect(url_for("index"))

@app.route("/cardwatch/delete/<int:pid>", methods=["POST"])
def delete(pid):
    with get_db_session() as s:
        p = s.query(Product).get(pid)
        if not p: return "Not found", 404
        s.delete(p)
        s.commit()
        flash("Deleted.")
        return redirect(url_for("index"))

@app.route("/update-cookies", methods=["GET", "POST"])
def update_cookies():
    if request.method == "POST":
        new_val = request.form.get("cf_clearance", "").strip()
        if new_val:
            try:
                from cookie_loader import update_cookie_in_file
                update_cookie_in_file("cookies-cardmarket-com.txt", "cf_clearance", new_val)
                
                # Also reset the scraper status to OK tentatively
                from scraper import update_scraper_status
                update_scraper_status("ok", "Cookie updated by user.")
                flash("Cookie updated successfully!", "success")
            except Exception as e:
                flash(f"Error saving cookie: {e}", "danger")
        return redirect(url_for('home'))
        
    return render_template("update_cookies.html")



@app.route("/cardwatch/bookkeeping")
def bookkeeping():
    try:
        year = int(request.args.get("year", datetime.now().year))
        month = int(request.args.get("month", datetime.now().month))
    except ValueError:
        year = datetime.now().year
        month = datetime.now().month

    with get_db_session() as s:
        entries = s.query(BookkeepingEntry).filter(
            func.extract('year', BookkeepingEntry.date) == year,
            func.extract('month', BookkeepingEntry.date) == month
        ).order_by(BookkeepingEntry.date.desc()).all()

        return render_template("bookkeeping.html", entries=entries, year=year, month=month)

@app.route("/cardwatch/bookkeeping/add", methods=["POST"])
def add_bookkeeping_entry():
    date_str = request.form.get("date")
    entry_type = request.form.get("entry_type") # 'cost', 'gain'
    description = request.form.get("description")
    amount = float(request.form.get("amount", 0.0))
    currency = request.form.get("currency") # 'EUR', 'CHF'
    rate = float(request.form.get("exchange_rate", 1.0))
    is_private = "is_private_collection" in request.form
    market_value = request.form.get("market_value")
    market_value = float(market_value) if market_value else None

    # Calculate other currency
    amount_eur = 0.0
    amount_chf = 0.0
    
    if currency == 'EUR':
        amount_eur = amount
        amount_chf = amount * rate
    else:
        amount_chf = amount
        amount_eur = amount / rate if rate > 0 else 0

    # File Upload
    file_path = None
    file = request.files.get("invoice")
    if file and file.filename:
        import uuid
        from werkzeug.utils import secure_filename
        
        ext = os.path.splitext(file.filename)[1]
        filename = f"{uuid.uuid4().hex}{ext}"
        
        # Organization: invoices/year/month/
        entry_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        subfolder = os.path.join(str(entry_date.year), str(entry_date.month)) # careful with 1 vs 01, str(int) is no padding
        
        abs_folder = os.path.join(BOOKKEEPING_UPLOAD_FOLDER, subfolder)
        os.makedirs(abs_folder, exist_ok=True)
        
        save_path = os.path.join(abs_folder, filename)
        file.save(save_path)
        
        # Store relative path for serving if needed, or just relative to MEDIA_ROOT
        # or relative to invoices folder. Let's store relative to MEDIA_ROOT, so "invoices/2025/1/file.pdf"
        file_path = os.path.join("invoices", subfolder, filename)

    with get_db_session() as s:
        entry = BookkeepingEntry(
            date=datetime.strptime(date_str, "%Y-%m-%d").date(),
            entry_type=entry_type,
            description=description,
            amount_eur=amount_eur,
            amount_chf=amount_chf,
            original_currency=currency,
            exchange_rate=rate,
            file_path=file_path,
            is_private_collection=1 if is_private else 0,
            market_value=market_value
        )
        s.add(entry)
        s.commit()
        
    return redirect(url_for('bookkeeping', year=entry.date.year, month=entry.date.month))


@app.route("/cardwatch/bookkeeping/upload-invoice", methods=["POST"])
def upload_invoice():
    file = request.files.get("invoice_file")
    if not file:
        return jsonify({"success": False, "error": "No file provided"}), 400
        
    import uuid
    from werkzeug.utils import secure_filename
    
    ext = os.path.splitext(file.filename)[1]
    if ext.lower() != ".pdf":
         return jsonify({"success": False, "error": "Only PDF supported"}), 400

    filename = f"{uuid.uuid4().hex}{ext}"
    temp_folder = os.path.join(BOOKKEEPING_UPLOAD_FOLDER, "temp")
    os.makedirs(temp_folder, exist_ok=True)
    
    save_path = os.path.join(temp_folder, filename)
    file.save(save_path)
    
    # Parse
    data = parse_cardmarket_invoice(save_path)
    if not data:
         return jsonify({"success": False, "error": "Could not parse invoice"}), 500
         
    # Return data + temp filename
    return jsonify({"success": True, "data": data, "temp_filename": filename})


@app.route("/cardwatch/bookkeeping/confirm-invoice", methods=["POST"])
def confirm_invoice():
    req = request.json
    data = req.get("data")
    temp_filename = req.get("temp_filename")
    
    if not data or not temp_filename:
        return jsonify({"success": False, "error": "Missing data"}), 400

    # Move file
    temp_path = os.path.join(BOOKKEEPING_UPLOAD_FOLDER, "temp", temp_filename)
    if not os.path.exists(temp_path):
        return jsonify({"success": False, "error": "Temp file lost"}), 400
        
    date_str = data.get("date", datetime.now().strftime("%Y-%m-%d"))
    entry_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    
    subfolder = os.path.join(str(entry_date.year), str(entry_date.month))
    abs_folder = os.path.join(BOOKKEEPING_UPLOAD_FOLDER, subfolder)
    os.makedirs(abs_folder, exist_ok=True)
    
    final_path = os.path.join(abs_folder, temp_filename)
    os.rename(temp_path, final_path)
    
    # Relative path for DB
    file_path = os.path.join("invoices", subfolder, temp_filename)
    
    # DB Operations
    with get_db_session() as s:
        # 1. Create Bookkeeping Entry (Cost)
        bk_entry = BookkeepingEntry(
            date=entry_date,
            entry_type="cost",
            description=f"Invoice {data.get('order_id')} - {data.get('seller_name')}",
            amount_eur=data.get("total_amount"),
            amount_chf=0.0, # Assuming invoice is EUR, logic for rate?
            original_currency=data.get("currency", "EUR"), 
            # We don't have rate in PDF usually. Default to 1.0 or user should have provided?
            # For simplicity let's stick to 1.0 for now or fetch recent rate?
            # User request didn't specify. We will default to 1.0 logic from before:
            exchange_rate=0.95,  # Placeholder default, maybe should accept from frontend
            file_path=file_path,
            is_private_collection=0
        )
        
        # Calculate CHF roughly or keep 0 and user edits?
        # Let's use the 0.95 hardcoded or pass from frontend if we added a field in the modal.
        # Ideally frontend modal should calculate it. 
        # But here we are confirming auto-parsed data.
        # Let's check if req has rate.
        rate = float(req.get("exchange_rate", 0.95))
        bk_entry.exchange_rate = rate
        if bk_entry.original_currency == 'EUR':
             bk_entry.amount_chf = bk_entry.amount_eur * rate
        else: # assuming CHF
             bk_entry.amount_eur = bk_entry.amount_chf / rate if rate > 0 else 0
             
        s.add(bk_entry)
        s.flush() # get ID
        
        # 2. Create Items
        items_data = data.get("items", [])
        total_items_price = sum(i["price"] for i in items_data)
        total_shipping_vat = data.get("shipping_cost", 0) + data.get("vat_cost", 0)
        
        for item in items_data:
            # Distribute shipping/vat proportionally by value?
            # Logic: (item_price / total_items_price) * total_shipping
            # Handle div by zero
            share = 0
            if total_items_price > 0:
                share = (item["price"] / total_items_price) * total_shipping_vat
            else:
                # split evenly?
                share = total_shipping_vat / len(items_data) if items_data else 0
                
            db_item = Item(
                name=item["name"],
                buy_date=entry_date,
                price=item["price"],
                currency=data.get("currency", "EUR"),
                extra_costs=share,
                external_id=data.get("order_id"),
                bookkeeping_id=bk_entry.id,
                
                # Defaults
                category="Active",
                graded=0,
                not_for_sale=0
            )
            s.add(db_item)
            
        s.commit()
        
    return jsonify({"success": True})


    return jsonify({"success": True})


@app.route("/cardwatch/bookkeeping/delete/<int:entry_id>", methods=["POST"])
def delete_bookkeeping_entry(entry_id):
    with get_db_session() as s:
        entry = s.query(BookkeepingEntry).filter_by(id=entry_id).first()
        if entry:
            # Unlink items (set bookkeeping_id to NULL)
            items = s.query(Item).filter_by(bookkeeping_id=entry.id).all()
            for item in items:
                item.bookkeeping_id = None
                
            # If file attached, we could delete it, but maybe keep it safe?
            # User didn't specify. Let's keep file for now to avoid data loss.
            
            s.delete(entry)
            s.commit()
            
    return redirect(request.referrer or url_for('bookkeeping'))


@app.route("/cardwatch/bookkeeping/export_pdf")
def export_bookkeeping_pdf():
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        import io
        
        year = int(request.args.get("year", datetime.now().year))
        month = int(request.args.get("month", datetime.now().month))
        
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
        elements = []
        
        styles = getSampleStyleSheet()
        elements.append(Paragraph(f"Bookkeeping Report - {month}/{year}", styles['Title']))
        elements.append(Spacer(1, 12))
        
        # Fetch data
        with get_db_session() as s:
            entries = s.query(BookkeepingEntry).filter(
                func.extract('year', BookkeepingEntry.date) == year,
                func.extract('month', BookkeepingEntry.date) == month
            ).order_by(BookkeepingEntry.date).all()
            
            # Table Data
            data = [['Date', 'Description', 'Type', 'Amount (EUR)', 'Amount (CHF)', 'Private']]
            
            total_eur = 0
            total_chf = 0
            
            for e in entries:
                row = [
                    e.date.strftime("%Y-%m-%d"),
                    e.description[:50],
                    e.entry_type.upper(),
                    f"{e.amount_eur:.2f}",
                    f"{e.amount_chf:.2f}",
                    "Yes" if e.is_private_collection else "No"
                ]
                data.append(row)
                
                # Calc totals (Cost is usually negative in bookkeeping? 
                # But here we store absolute values and have type. 
                # Let's simple sum: Gain - Cost
                sign = 1 if e.entry_type == 'gain' else -1
                total_eur += e.amount_eur * sign
                total_chf += e.amount_chf * sign

            # Totals Row
            data.append(['', 'TOTAL', '', f"{total_eur:.2f}", f"{total_chf:.2f}", ''])
            
            # Table Style
            table = Table(data)
            style = TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -2), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('ALIGN', (3, 1), (4, -1), 'RIGHT'), # Amounts right align
            ])
            
            # Color rows based on type in loop (skip header and total)
            for i, e in enumerate(entries):
                row_idx = i + 1
                color = colors.lightgreen if e.entry_type == 'gain' else colors.lightpink
                style.add('BACKGROUND', (0, row_idx), (-1, row_idx), color)
                
            table.setStyle(style)
            elements.append(table)
            
            # Stock Items List?
            # User said "print to pdf the bookkeeping and stock"
            # Maybe list items allocated this month? or just total Stock added?
            # Let's add a second table for Stock Items acquired this month
            
            elements.append(Spacer(1, 24))
            elements.append(Paragraph("Stock Items Acquired", styles['Heading2']))
            
            items = s.query(Item).filter(
                func.extract('year', Item.buy_date) == year,
                func.extract('month', Item.buy_date) == month
            ).all()
            
            if items:
                item_data = [['Buying Date', 'Name', 'Price', 'Extra Costs (Ship/Tax)', 'Total Cost']]
                for i in items:
                    total_cost = i.price + (i.extra_costs or 0)
                    item_data.append([
                        i.buy_date.strftime("%Y-%m-%d"),
                        i.name[:60],
                        f"{i.price:.2f} {i.currency}",
                        f"{i.extra_costs:.2f}",
                        f"{total_cost:.2f}"
                    ])
                
                item_table = Table(item_data)
                item_table.setStyle(TableStyle([
                     ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                     ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                     ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ]))
                elements.append(item_table)
            else:
                elements.append(Paragraph("No stock items acquired this month.", styles['Normal']))

        doc.build(elements)
        buffer.seek(0)
        
        from flask import send_file
        return send_file(buffer, as_attachment=True, download_name=f"Bookkeeping_{year}_{month}.pdf", mimetype='application/pdf')
        
    except ImportError:
        return "ReportLab is not installed.", 500
    except Exception as e:
        return f"Error generating PDF: {e}", 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

