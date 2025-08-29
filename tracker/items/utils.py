from items.fx import get_fx_rates


def get_psa10_chf(psa10_usd, fx_chf):
    """Converts a PSA10 price from USD to CHF using current rates."""
    if psa10_usd is not None and fx_chf and fx_chf.get("USD"):
        return float(psa10_usd) / fx_chf["USD"]
    return 0.0

def valuation_base(price_chf, psa10_chf):
    return max(price_chf, psa10_chf)

def get_reference_usd(item, charting_prices):
    """Return PSA10 if graded, ungraded if not"""
    prices = charting_prices.get(item.id, {})
    return prices.get("psa10_usd") if item.graded else prices.get("ungraded_usd")

def get_reference_chf(ref_usd, fx_chf):
    """Convert reference USD price to CHF using correct FX"""
    if ref_usd:
        return ref_usd / fx_chf["USD"]
    return 0.0

def get_paid_usd(item):
    fx = get_fx_rates(base=item.currency)
    return float(item.price) * fx.get("USD", 1.0)
