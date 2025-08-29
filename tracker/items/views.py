from django.shortcuts import render, redirect, get_object_or_404
from .models import Item
from .forms import ItemForm
from .pricecharting import fetch_pricecharting_prices
from .utils import get_reference_usd, get_reference_chf, get_paid_usd
from .fx import get_fx_rates
from decimal import Decimal, ROUND_HALF_UP

PRICECHARTING_CACHE = {}
Q = Decimal('0.01')

def to_dec(val):
    return Decimal(str(val)) if val is not None else Decimal('0')

def get_charting_prices(items):
    charting_prices = {}
    for item in items:
        if item.link:
            if item.link in PRICECHARTING_CACHE:
                prices = PRICECHARTING_CACHE[item.link]
            else:
                prices = fetch_pricecharting_prices(item.link)
                PRICECHARTING_CACHE[item.link] = prices
            charting_prices[item.id] = prices
        else:
            charting_prices[item.id] = {"psa10_usd": None, "ungraded_usd": None}
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

        # Determine reference USD (psa10 or ungraded depending on grading flag)
        ref_usd = get_reference_usd(item, charting_prices)
        ref_chf = get_reference_chf(ref_usd, fx_chf)

        # Base in CHF for sell_xxx prices
        base = max(price_chf, ref_chf)

        # Proposed price in EUR: max(buy EUR, ref EUR) with 25% ROI after 5% fee
        buy_price_eur = Decimal(str(price_eur)).quantize(Q, rounding=ROUND_HALF_UP)
        ref_price_eur = (
                Decimal(str(ref_usd)) * usd_to_eur
        ).quantize(Q, rounding=ROUND_HALF_UP) if ref_usd is not None else None

        if ref_price_eur is not None:
            base_price_eur = max(buy_price_eur, ref_price_eur)
        else:
            base_price_eur = buy_price_eur

        proposed_price_eur = (base_price_eur * Decimal('1.25') / Decimal('0.95')).quantize(Q, rounding=ROUND_HALF_UP)

        # Revenue
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

def item_list(request):
    items = Item.objects.all().order_by("-buy_date")
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
    # Totals for finished (sold) items
    bought_finished_chf = sum(
        float(item.price) * get_fx_rates(item.currency)["CHF"]
        for item in items if item.sell_price and item.sell_date
    )
    sold_finished_chf = sum(
        float(item.sell_price)
        for item in items if item.sell_price and item.sell_date
    )

    total_roi_pct = (realized / sold_invested_chf) * 100.0 if sold_invested_chf > 0 else None

    return render(request, "tracker/item_list.html", {
        "items": items,
        "fx_dict": fx_dict,
        "charting_prices": charting_prices,
        "invested": invested,
        "realized": realized,
        "possible_gain_chf": possible_gain_chf,
        "total_roi_pct": total_roi_pct,
        "bought_finished_chf": bought_finished_chf,
        "sold_finished_chf": sold_finished_chf,
    })

def item_add(request):
    if request.method == "POST":
        form = ItemForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect("item_list")
    else:
        form = ItemForm()
    return render(request, "tracker/item_form.html", {"form": form})

def item_edit(request, pk):
    item = get_object_or_404(Item, pk=pk)
    if request.method == "POST":
        form = ItemForm(request.POST, request.FILES, instance=item)
        if form.is_valid():
            form.save()
            return redirect("item_list")
    else:
        form = ItemForm(instance=item)
    return render(request, "tracker/item_form.html", {"form": form})
