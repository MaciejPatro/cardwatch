from app import get_db_session, SingleCard, SingleCardPrice

def debug_stats():
    with get_db_session() as s:
        cards = s.query(SingleCard).all()
        print(f"Found {len(cards)} cards.")
        for c in cards:
            first = (
                s.query(SingleCardPrice)
                .filter_by(card_id=c.id)
                .order_by(SingleCardPrice.ts.asc())
                .first()
            )
            latest = (
                s.query(SingleCardPrice)
                .filter_by(card_id=c.id)
                .order_by(SingleCardPrice.ts.desc())
                .first()
            )
            
            first_low = first.low if first else "NO RECORD"
            latest_low = latest.low if latest else "NO RECORD"
            
            print(f"Card: {c.name}")
            print(f"  First Record: {first.ts if first else 'None'} | Low: {first_low}")
            print(f"  Latest Record: {latest.ts if latest else 'None'} | Low: {latest_low}")
            
            if first and first.low is None:
                print("  -> ISSUE DETECTED: First record has None price.")
                # Check if there is ANY record with a price
                first_valid = (
                    s.query(SingleCardPrice)
                    .filter_by(card_id=c.id)
                    .filter(SingleCardPrice.low.isnot(None))
                    .order_by(SingleCardPrice.ts.asc())
                    .first()
                )
                if first_valid:
                    print(f"  -> First VALID record: {first_valid.ts} | Low: {first_valid.low}")
                else:
                    print("  -> NO VALID PRICE RECORDS FOUND.")
            print("-" * 20)

if __name__ == "__main__":
    debug_stats()
