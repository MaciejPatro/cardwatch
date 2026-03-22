import re
import subprocess
import os
from datetime import datetime


def parse_cardmarket_invoice(pdf_path):
    """
    Parses a Cardmarket PDF invoice.
    Returns a dict with:
      - order_id
      - date (Paid date preferred, else Arrived)
      - seller_name
      - total_amount
      - currency
      - shipping_cost
      - vat_cost
      - items: list of {name, price, quantity}
    """
    print(f"Parsing {pdf_path}...")
    try:
        # Extract Text
        args = ["pdftotext", "-layout", pdf_path, "-"]
        result = subprocess.run(args, capture_output=True, text=True)
        text = result.stdout

    except Exception as e:
        print(f"Error reading PDF: {e}")
        return None
    except FileNotFoundError:
        print("pdftotext command not found.")
        return None

    def parse_amount(line_label):
        # Look for Label followed by spaces then amount then Currency
        # Amount format: 1.234,56 or 14,00
        # Simplistic regex for "14,00 EUR"
        pattern = re.compile(rf"{line_label}\s+([\d.,]+)\s+([A-Z]{{3}})")
        match = pattern.search(text)
        if match:
            # Normalize 1.234,56 -> 1234.56
            # or 14,00 -> 14.00
            amount_str = match.group(1)

            # Simple locale handling: replace dot with nothing (thousands), replace comma with dot
            if "," in amount_str:
                amount_str = amount_str.replace(".", "").replace(",", ".")
            return float(amount_str), match.group(2)
        return None

    data = {
        "order_id": None,
        "date": None,
        "seller_name": None,
        "total_amount": 0.0,
        "currency": "EUR",
        "shipping_cost": 0.0,
        "vat_cost": 0.0,
        "items": [],
    }

    # Regex patterns
    # Purchase #1251374885 or Sale #1249109301
    order_match = re.search(r"(Purchase|Sale)\s+#(\d+)", text, re.IGNORECASE)
    if order_match:
        data["type"] = order_match.group(1).lower()  # purchase or sale
        data["order_id"] = order_match.group(2)

    # Dates. "Paid: 16.01.2026 07:26" or "Arrived: ..."
    # Logic:
    # If Sale: Arrived > Paid > Sent
    # If Purchase: Paid > Sent > Arrived

    date_match = None
    invoice_type = data.get("type", "purchase")  # Default to purchase if not found? But regex above finds it.

    if invoice_type == "sale":
        # Prefer Arrived
        date_match = re.search(r"Arrived:\s+(\d{2}\.\d{2}\.\d{4})", text)
        if not date_match:
            date_match = re.search(r"Paid:\s+(\d{2}\.\d{2}\.\d{4})", text)
    else:
        # Prefer Paid (Purchase)
        date_match = re.search(r"Paid:\s+(\d{2}\.\d{2}\.\d{4})", text)
        if not date_match:
            date_match = re.search(r"Sent:\s+(\d{2}\.\d{2}\.\d{4})", text)

    # Fallbacks for both if primary choices failed
    if not date_match:
        if invoice_type == "sale":
            date_match = re.search(r"Sent:\s+(\d{2}\.\d{2}\.\d{4})", text)
        else:
            date_match = re.search(r"Arrived:\s+(\d{2}\.\d{2}\.\d{4})", text)

    if date_match:
        try:
            data["date"] = datetime.strptime(date_match.group(1), "%d.%m.%Y").strftime("%Y-%m-%d")
        except ValueError:
            pass

    # Seller
    # Seller - Razurack
    seller_match = re.search(r"Seller\s+-\s+(.+?)\s{2,}", text)
    if seller_match:
        data["seller_name"] = seller_match.group(1).strip()

    # Check for Import Tax condition (Germany)
    # Heuristic: Check if "Germany" appears in the Buyer/Address section?
    # Or generically in the first few lines?
    # User said: "Purchase #1251301090 ... delivery address is in Germany"
    # The address usually appears in the header block.
    # Let's check for "Germany" in the text, but try to avoid "Made in Germany" or card names.
    # Usually address block is at the top.

    header_text = "\n".join(text.split("\n")[:20])  # First 20 lines
    if "Germany" in header_text or "Deutschland" in header_text:
        data["shipping_country"] = "Germany"
    else:
        data["shipping_country"] = "Switzerland"

    # Financials
    # Article Value              14,00 EUR
    # Shipping                   1,79 EUR
    # Vat                        1,28 EUR
    # Trustee service fee        0,34 EUR

    vat_match = parse_amount("Vat")
    if vat_match:
        data["vat_cost"] = vat_match[0]

    trustee_match = parse_amount("Trustee service fee")
    if trustee_match:
        data["trustee_fee"] = trustee_match[0]

    total_match = parse_amount("Total")
    if total_match:
        data["total_amount"] = total_match[0]
        data["currency"] = total_match[1]

    ship_match = parse_amount("Shipping")
    if ship_match:
        data["shipping_cost"] = ship_match[0]

    # Items extraction
    # Everything after "One Piece Singles:" (or similar category)
    # The layout is usually:
    # Qty Name ... Price
    # 1 Nico Robin ... 14,00 EUR

    # Strategy: Find lines that end with a price and currency, check if they start with a number
    # This is a bit heuristic.

    lines = text.split("\n")
    parsing_items = False

    # Categories to look for start
    categories = [
        "One Piece Singles",
        "Singles",
        "Products",
        "One Piece Booster Boxes",
        "One Piece Promo Products",
    ]  # Add more as needed

    # Refactor loop to while with index to allow peeking
    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        idx += 1
        if not line:
            continue

        # Check Categories
        if any(line.startswith(c) and line.endswith(":") for c in categories):
            parsing_items = True
            continue

        if parsing_items:
            # Check for end of items? (Empty lines sometimes separate, or next Section)
            # Usually strict sections.
            if "Total" in line and "EUR" in line:
                # End of items likely
                parsing_items = False
                continue

            # Case 1: One line match
            # Regex: Start with digits, then space, then text, then space, amounts currency
            item_pattern = re.match(r"^(\d+)\s+(.+?)\s{2,}([\d.,]+)\s+([A-Z]{3})", line)

            qty = 0
            name = ""
            price = 0.0

            if item_pattern:
                qty = int(item_pattern.group(1))
                name = item_pattern.group(2).strip()
                price_str = item_pattern.group(3)
                if "," in price_str:
                    price_str = price_str.replace(".", "").replace(",", ".")
                price = float(price_str)
            else:
                # Case 2: Split line
                # Starts with digit
                start_match = re.match(r"^(\d+)\s+(.+)$", line)
                if start_match:
                    # Check next line for price
                    if idx < len(lines):
                        next_line = lines[idx].strip()
                        # Look for price at end of next line
                        price_match = re.search(r"([\d.,]+)\s+([A-Z]{3})$", next_line)
                        if price_match:
                            # Found it
                            qty = int(start_match.group(1))
                            name = start_match.group(2).strip()
                            price_str = price_match.group(1)
                            if "," in price_str:
                                price_str = price_str.replace(".", "").replace(",", ".")
                            price = float(price_str)
                            idx += 1  # Consume next line

            if qty > 0:
                # Clean name
                clean_name = name
                parts = re.split(r"\s{2,}", name)
                if len(parts) > 0:
                    clean_name = parts[0]

                # If Qty > 1, the price listed is the UNIT PRICE on these invoices.
                # Validated via User feedback:
                # 2 Sanji @ 4.49 implies total 8.98.
                # Article Value check confirms: 19.89 + 2*4.49 + 4.49 = 33.36 EUR.

                unit_price = price

                for _ in range(qty):
                    data["items"].append({"name": clean_name, "raw_line": name, "price": unit_price})
            else:
                # If we hit something that doesn't look like an item line (e.g. empty lines or footer)
                # and we are far down, maybe stop? But sometimes there are multiple categories.
                # So we just try to match patterns.
                pass

    return data


def parse_ebay_invoice(pdf_path):
    """
    Parses an Ebay PDF invoice.
    """
    print(f"Parsing Ebay {pdf_path}...")
    try:
        args = ["pdftotext", "-layout", pdf_path, "-"]
        result = subprocess.run(args, capture_output=True, text=True)
        text = result.stdout
    except Exception as e:
        print(f"Error: {e}")
        return None

    data = {
        "order_id": None,
        "date": None,
        "seller_name": "eBay",  # Default, maybe extract specific seller?
        "total_amount": 0.0,
        "currency": "USD",
        "shipping_cost": 0.0,
        "vat_cost": 0.0,
        "items": [],
    }

    # 1. Order ID: Bestellnr. 19-14145-56417
    # "Bestellnr.         19-14145-56417"
    order_match = re.search(r"Bestellnr\.\s+([\d-]+)", text)
    if order_match:
        data["order_id"] = order_match.group(1)

    # 2. Date: Kaufdatum 27. Jan 2026
    # "Kaufdatum          27. Jan 2026"
    date_match = re.search(r"Kaufdatum\s+(\d{2}\.\s+\w{3}\s+\d{4})", text)
    if date_match:
        d_str = date_match.group(1)
        # Handle German months if needed: Jan, Feb, Mär, Apr, Mai, Jun, Jul, Aug, Sep, Okt, Nov, Dez
        # Mapping for standard English
        replacements = {"Mär": "Mar", "Mai": "May", "Okt": "Oct", "Dez": "Dec"}
        for k, v in replacements.items():
            d_str = d_str.replace(k, v)
        try:
            # Try parse "27. Jan 2026"
            # Remove '.' after day if strptime needs specific format
            # "27. Jan 2026" -> "%d. %b %Y"
            dt = datetime.strptime(d_str, "%d. %b %Y")
            data["date"] = dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    # 3. Seller: "Von: eBay Marketplaces GmbH" (or similar)
    # The actual seller of item is usually listed in items or descriptions?
    # PDF Header: "Von: eBay Marketplaces GmbH" (This is the invoicer, but platform is Ebay)
    # Let's keep seller_name as "eBay (Order ID)" or similar?
    # The receipt says "Rechnung Von: eBay...".
    # But usually we buy from a user.
    # The snippet shows "Sold by..." isn't obvious in header.
    # We'll use "eBay" for now.

    # 4. Totals and Currency
    # Look for "Gesamtbetrag" and then currency pattern
    # Regex: Gesamtbetrag\s+(US|USD|EUR)\s*\$?([\d.,]+)
    # Handle missing space: GesamtbetragUS
    total_match = re.search(r"Gesamtbetrag\s*(?:[A-Z]{2,3})?\s*\$?([\d.,]+)", text)
    if total_match:
        # Currency might be jammed or separated
        # Check text around match or default to USD if "US" found
        if "EUR" in total_match.group(0):
            data["currency"] = "EUR"
        else:
            data["currency"] = "USD"

        amt_str = total_match.group(1)
        amt_str = amt_str.replace(".", "").replace(",", ".")
        data["total_amount"] = float(amt_str)

    # 5. Shipping & VAT (Summary block at bottom)
    # Flexible regex because spaces might be lost: "VersandkostenUS $34,00"

    # Shipping:
    ship_match = re.search(r"Versandkosten\s*(?:[A-Z]{2,3})?\s*\$?([\d.,]+)", text)
    if ship_match:
        s_str = ship_match.group(1).replace(".", "").replace(",", ".")
        data["shipping_cost"] = float(s_str)

    # MwSt / VAT:
    # Look for "MwSt." followed by amount in the summary block.
    # Handle indentation: "(?:^|\n)\s*MwSt\."
    vat_matches = re.finditer(r"(?:^|\n)\s*MwSt\.\s*(?:[A-Z]{2,3})?\s*\$?([\d.,]+)", text)
    for m in vat_matches:
        v_str = m.group(1).replace(".", "").replace(",", ".")
        data["vat_cost"] = float(v_str)

    # 6. Items
    lines = text.split("\n")

    data["items"] = []

    pending_desc = []
    current_item = None

    # Headers/Garbage to ignore
    ignore_starts = [
        "Rechnungsdetails",
        "Artikelnr",
        "Rechnungsnummer",
        "Rechnungsdatum",
        "Bestellnr",
        "Kaufdatum",
        "Versand aus",
        "Rechnung",
        "Von:",
        "Adresse",
        "Lieferadresse",
        "MwSt.-",
        "Satz",
        "Betrag",
        "Nettobetrag",
        "Versandkosten",
        "Gesamtbetrag",
        "MwSt.",
        "Kosten)",
    ]

    # Garbage exact matches (e.g. columns wrapping)
    ignore_exact = ["US", "EUR", "CHF", "Satz       Betrag", "Betrag", "Kosten", "$0,00", "US $0,00"]

    for line in lines:
        line_s = line.strip()

        # RESET on Blank Line (Crucial for separating items from previous footer garbage)
        if not line_s:
            current_item = None
            current_items = None
            continue

        # Check for Ignorable Headers
        if any(line_s.startswith(x) for x in ignore_starts):
            current_item = None
            current_items = None
            pending_desc = []
            continue

        if line_s in ignore_exact:
            continue

        # Check for Item ID start (12 digits)
        id_match = re.match(r"^(\d{12})(.*)$", line_s)

        if id_match:
            # NEW ITEM START
            rest_of_line = id_match.group(2)

            # Extract financials from this line
            fin_match = re.search(r"(\d+)\s*(?:US|EUR|CHF)\s*\$?([\d.,]+)", rest_of_line)

            price_val = 0.0
            qty = 1
            desc_part = rest_of_line

            if fin_match:
                qty_str = fin_match.group(1)
                price_str = fin_match.group(2).replace(".", "").replace(",", ".")
                price_val = float(price_str)

                desc_part = rest_of_line[: fin_match.start()].strip()

                # Handle Quantity Collision
                if len(qty_str) > 1 and int(qty_str) > 10:
                    suffix = qty_str[:-1]
                    desc_part += " " + suffix
                    qty = int(qty_str[-1])  # Assume last digit is qty if collision? Heuristic.
                    # Actually, usually '1' is the quantity. If collision: "Card Game1".
                    # If Qty is 10? "Card Game10".
                    # Let's rely on fin_match regex: (\d+).
                    # If regex grabbed "1", then qty is 1.
                else:
                    qty = int(qty_str)

            # Cleanup specific garbage from desc_part if any
            desc_part = re.sub(r"US\s*\$[\d.,]+", "", desc_part).strip()

            # Assemble Name
            full_name = " ".join(pending_desc) + " " + desc_part
            full_name = full_name.strip()

            # Shorten Logic
            hash_match = re.search(r"(#\S+.*)", full_name)
            if hash_match:
                full_name = hash_match.group(1)

            # Create items based on quantity
            for _ in range(qty):
                new_item = {"name": full_name, "price": price_val}
                data["items"].append(new_item)

            # Track the last added item (pointer to the last copy? Or just one of them to append description?)
            # Usually description flows to all copies.
            # But if we have 5 items in list, we must update ALL 5 if description continues?
            # Or just assume description is fully captured?
            # Looking at PDF, description CAN continue: "Card Game" on line 29.
            # So we need to update all items generated from this ID.
            # Let's store a list of current_items
            current_items = data["items"][-qty:]  # The last 'qty' items

            pending_desc = []

        elif "current_items" in locals() and current_items:
            # Check for page numbers
            if re.search(r"\d+\s+of\s+\d+", line_s):
                continue

            # Strip Garbage (Financial columns wrapping)
            clean_line = re.sub(r"(?:US|EUR|CHF)?\s*\$\s*[\d.,]+", "", line_s).strip()

            # If line becomes empty or just symbols, ignore
            if not clean_line or re.match(r"^[\d.,%]+$", clean_line):
                continue

            # Also ignore standalone currency noise which regex might miss if logic differs
            if clean_line in ["US", "EUR", "CHF", "$0,00"]:
                continue

            for item in current_items:
                item["name"] += " " + clean_line

                # Re-apply Shorten Logic
                if "#" in item["name"]:
                    hm = re.search(r"(#\S+.*)", item["name"])
                    if hm:
                        item["name"] = hm.group(1)

        else:
            # Pending description for NEXT item
            if re.search(r"\d+\s+of\s+\d+", line_s):
                continue

            # Don't capture footer summary garbage as pending desc
            if re.search(r"(?:US|EUR|CHF)?\s*\$\s*[\d.,]{3,}", line_s):
                continue

            # More aggressive garbage filter for pending
            if line_s in ignore_exact:
                continue

            pending_desc.append(line_s)

    return data


def parse_ricardo_invoice(pdf_path):
    """
    Parses a Ricardo.ch PDF invoice.
    Returns a dict with:
      - order_id
      - date
      - seller_name
      - total_amount
      - currency
      - shipping_cost
      - vat_cost
      - items: list of {name, price}
      - type: 'sale'
    """
    print(f"Parsing Ricardo {pdf_path}...")
    try:
        args = ["pdftotext", "-layout", pdf_path, "-"]
        result = subprocess.run(args, capture_output=True, text=True)
        text = result.stdout
    except Exception as e:
        print(f"Error reading PDF: {e}")
        return None
    except FileNotFoundError:
        print("pdftotext command not found.")
        return None

    data = {
        "order_id": None,
        "date": None,
        "seller_name": "Ricardo.ch Seller",
        "total_amount": 0.0,
        "currency": "CHF",
        "shipping_cost": 0.0,
        "vat_cost": 0.0,
        "items": [],
        "type": "sale",  # Always sale
    }

    order_match = re.search(r"Artikelnummer\s+(\d+)", text)
    if order_match:
        data["order_id"] = order_match.group(1)

    date_match = re.search(r"Kaufdatum\s+(\d{1,2}\.\s*[A-Za-zäöü]+\.?\s*\d{4})", text)
    if date_match:
        d_str = date_match.group(1)
        replacements = {"März": "Mar", "Mär": "Mar", "Mai": "May", "Okt": "Oct", "Dez": "Dec"}
        for k, v in replacements.items():
            d_str = d_str.replace(k, v)
        try:
            d_str = re.sub(r"[\.\,]", " ", d_str)
            d_str = re.sub(r"\s+", " ", d_str).strip()
            dt = datetime.strptime(d_str, "%d %b %Y")
            data["date"] = dt.strftime("%Y-%m-%d")
        except ValueError as e:
            print("Date parse error", e)

    ship_match = re.search(r"Total Lieferkosten(?:.*)(?:CHF|EUR)\s+([\d.,]+)", text)
    if ship_match:
        data["shipping_cost"] = float(ship_match.group(1).replace("'", "").replace(",", ""))

    lines = text.split("\n")
    parsing_items = False

    current_item_name = []

    for idx, line in enumerate(lines):
        if "Artikel" in line and "Anzahl" in line and "Kaufdatum" in line and "Preis" in line:
            parsing_items = True
            continue

        if parsing_items:
            if "Total Lieferkosten" in line or "Total Artikel" in line:
                parsing_items = False
                continue

            line_s = line.strip()
            if not line_s:
                continue

            item_match = re.match(
                r"^(.*?)\s+(\d+)\s+(\d{1,2}\.\s+[a-zA-ZäöüÄÖÜ]+\.?\s+\d{4}.*?)\s+(CHF|EUR)\s+([\d.,]+)$", line_s
            )

            if item_match:
                name_part = item_match.group(1).strip()
                qty = int(item_match.group(2))
                currency = item_match.group(4)
                price = float(item_match.group(5).replace("'", "").replace(",", ""))
                data["currency"] = currency

                current_item_name = [name_part]
                data["items"].append({"name": name_part, "price": price, "qty": qty})
            else:
                if line_s and "CHF" not in line_s and "EUR" not in line_s and not re.match(r"^\d{1,2}\.", line_s):
                    if data["items"]:
                        data["items"][-1]["name"] += " " + line_s

    subtotal = sum(i["price"] * i.get("qty", 1) for i in data["items"])
    data["total_amount"] = subtotal + data["shipping_cost"]

    expanded_items = []
    for item in data["items"]:
        qty = item.pop("qty", 1)
        name = re.sub(r"\s+", " ", item["name"])
        for _ in range(qty):
            expanded_items.append({"name": name, "price": item["price"]})
    data["items"] = expanded_items

    return data
