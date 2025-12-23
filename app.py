import json
import os
import asyncio

from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
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

    with get_db_session() as session:
        query = session.query(SingleCard).filter(SingleCard.category == 'Liked')

        if search:
            query = query.filter(SingleCard.name.ilike(f"%{search}%"))

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
    # Logic: "submitted" param indicates this comes from the filter form.
    # If submitted is present: Use strict checkbox logic (missing = False).
    # If submitted is missing (initial load): Use defaults (English=True).
    
    is_submitted = request.args.get("submitted") == "true"
    
    if is_submitted:
        show_promos = request.args.get("promos") == "true"
        show_packs = request.args.get("packs") == "true"
        english_only = request.args.get("english") == "true"
    else:
        # Defaults
        show_promos = False
        show_packs = False
        english_only = True
    
    with get_db_session() as s:
        top_deals = calculate_deals(s, include_promos=show_promos, english_only=english_only, include_packs=show_packs)
    
    return render_template("deals.html", deals=top_deals, show_promos=show_promos, english_only=english_only, show_packs=show_packs)

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

        # Language Filter
        if language_filter and language_filter != "All":
            query = query.filter(SingleCard.language == language_filter)

        # Category Filter<bos>
        if category_filter:
            if category_filter == "None": # Special case for filtering empty categories
                 query = query.filter((SingleCard.category == None) | (SingleCard.category == ""))
            else:
                 query = query.filter(SingleCard.category == category_filter)
        
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
    with get_db_session() as s:
        offers = (
            s.query(SingleCardOffer)
            .join(SingleCard)
            .filter(SingleCard.is_enabled == 1)
            .all()
        )

        if not offers:
            return render_template("seller_bundles.html", sellers=[])

        cards = s.query(SingleCard).filter(SingleCard.is_enabled == 1).all()
        card_lookup = {c.id: c for c in cards}

        cheapest = {}
        for offer in offers:
            if offer.price is None:
                continue
            prev = cheapest.get(offer.card_id)
            if prev is None or offer.price < prev:
                cheapest[offer.card_id] = offer.price

        seller_map = {}
        for offer in offers:
            baseline = cheapest.get(offer.card_id)
            if baseline is None or offer.price is None:
                continue
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

        sellers = [
            s for s in seller_map.values() if s["total_upcharge"] <= 20.0
        ]
        sellers.sort(
            key=lambda s: (-len(s["cards"]), s["total_upcharge"], s["bundle_total"])
        )

        return render_template("seller_bundles.html", sellers=sellers)

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
                with open("cf_clearance.txt", "w") as f:
                    f.write(new_val)
                # Also reset the scraper status to OK tentatively
                from scraper import update_scraper_status
                update_scraper_status("ok", "Cookie updated by user.")
                flash("Cookie updated successfully!", "success")
            except Exception as e:
                flash(f"Error saving cookie: {e}", "danger")
        return redirect(url_for('home'))
        
    return render_template("update_cookies.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

