from datetime import datetime, timedelta
from sqlalchemy import func
from db import SingleCard, SingleCardPrice, SingleCardOffer, SingleCardDaily

def get_market_sentiment(session):
    """
    Returns counts of cards trending UP, DOWN, or FLAT over the last 7 days.
    """
    # We can use the compute_single_trend function logic here or re-implement for bulk?
    # Ideally we iterate valid cards and check their trend.
    # For performance, maybe we can do a bulk query, but iterating ~1000 cards is fast enough in memory for now.
    
    # We need to import compute_single_trend from scraper (or move it to a shared util, but circle imports...)
    # Let's duplicate the simple 7-day trend logic for now or import it if safe.
    # scraper imports db, so importing scraper here (called by app) might be safe if done inside function or if scraper doesn't import app.
    # scraper does NOT import app.
    from scraper import compute_single_trend

    cards = session.query(SingleCard).filter(SingleCard.is_enabled == 1).filter((SingleCard.category != 'Ignore') | (SingleCard.category.is_(None))).all()
    
    rising = 0
    falling = 0
    flat = 0
    
    for c in cards:
        trend = compute_single_trend(session, c.id, lookback_days=7)
        if trend == "up":
            rising += 1
        elif trend == "down":
            falling += 1
        else:
            flat += 1
            
    return {"rising": rising, "falling": falling, "flat": flat}


def calculate_deals(session, include_promos=False, english_only=True, include_packs=False, language=None):
    """
    Identify and rank the best deals across all enabled single cards.
    Returns a list of dicts with deal details, sorted by Score descending.
    """
    query = session.query(SingleCard).filter(SingleCard.is_enabled == 1)
    
    if language and language != "All":
        query = query.filter(SingleCard.language == language)
    elif english_only: # Legacy fallback if language param not used
        query = query.filter(SingleCard.language == 'English')
        
    cards = query.all()
    deals = []
    
    now = datetime.utcnow()
    
    for card in cards:
        # Refinement: Filter packs if requested
        if not include_packs:
            if card.category and "pack" in card.category.lower():
                continue
                
        # Get latest stats
        latest_price = (
            session.query(SingleCardPrice)
            .filter_by(card_id=card.id)
            .order_by(SingleCardPrice.ts.desc())
            .first()
        )
        
        if not latest_price:
            continue
            
        # Get active offers
        offers = (
            session.query(SingleCardOffer)
            .filter_by(card_id=card.id)
            .order_by(SingleCardOffer.price.asc())
            .all()
        )
        
        if not offers:
            continue
            
        # Refinement: Exclude expensive cards (> €5000)
        # We check the latest scraping pricing for a rough check, or just filter offers later.
        if (latest_price.avg5 or 0) > 5000:
            continue

        # Refinement: Filter out special tournament promos
        if not include_promos:
            # Keywords: "Championship", "Serial", "Treasure Cup", "Regional"
            # We check card.name and card.category
            name_lower = card.name.lower()
            url_lower = card.url.lower()
            
            if "special-tournaments-promos" in url_lower:
                continue
                
            if any(x in name_lower for x in ["championship", "serial", "treasure cup", "regional", "prize"]):
                continue
            
        # --- 1. Calculate Market Value (MV) ---
        # Formula: MV = (0.50 * Internal_Avg7) + (0.50 * Website_Avg7)
        
        # Internal Avg7: query daily history
        # We can use SingleCardDaily for this.
        daily_rows = (
            session.query(SingleCardDaily)
            .filter(SingleCardDaily.card_id == card.id)
            .order_by(SingleCardDaily.day.desc())
            .limit(7)
            .all()
        )
        
        internal_avgs = [d.avg for d in daily_rows if d.avg]
        internal_avg7 = sum(internal_avgs) / len(internal_avgs) if internal_avgs else (latest_price.avg5 or 0)
        
        website_avg7 = latest_price.avg7_price or internal_avg7 # fallback to internal if missing
        
        if internal_avg7 == 0 and website_avg7 == 0:
            continue
            
        mv = (0.50 * internal_avg7) + (0.50 * website_avg7)
        
        # --- 2. Trend & Supply Multipliers ---
        from scraper import compute_single_trend # Delayed import
        trend_direction = compute_single_trend(session, card.id, lookback_days=7)
        
        trend_mult = 1.0
        if trend_direction == "up":
            trend_mult = 1.1
        elif trend_direction == "down":
            trend_mult = 0.9
            
        # Supply check
        supply = latest_price.supply or 0
        supply_mult = 1.0
        if supply < 10:
            supply_mult = 1.15
        elif supply < 50:
            supply_mult = 1.05
        elif supply > 200:
            supply_mult = 0.95
            
        # Sentinel Logic
        # Price RISING + Supply DROPPING
        # Check supply trend? Simple check: current supply vs 7 days ago
        # For valid comparison we need history. Let's approximate with just the multiplier for now or add complex check later.
        # Strict implementation of sentinel:
        if trend_direction == "up" and supply < 50: # Proxy for dropping supply context without historical query
             trend_mult += 0.05 # Boost
        if trend_direction == "down" and supply > 100:
             trend_mult -= 0.05 # Penalty

        # --- 3. Score Offers ---
        for offer in offers:
            if mv <= 0: continue
            
            discount_pct = (mv - offer.price) / mv * 100.0
            
            # Skip negative discounts (overpriced) unless we want to show everything?
            # Let's show only "deals" (positive discount or close to it)
            if discount_pct < -10: 
                continue # Ignore terrible deals
            
            # Refinement: Explicitly skip individual offers > 5000
            if offer.price > 5000:
                continue
                
            final_score = discount_pct * trend_mult * supply_mult
            
            deals.append({
                "card": card,
                "offer": offer,
                "mv": mv,
                "discount_pct": discount_pct,
                "score": final_score,
                "trend": trend_direction,
                "supply": supply
            })
            
    # Sort by Score Descending
    deals.sort(key=lambda x: x["score"], reverse=True)
    
    return deals  # Return all for pagination
