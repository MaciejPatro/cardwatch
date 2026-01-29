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
            if ',' in amount_str:
                amount_str = amount_str.replace('.', '').replace(',', '.')
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
        "items": []
    }

    # Regex patterns
    # Purchase #1251374885 or Sale #1249109301
    order_match = re.search(r"(Purchase|Sale)\s+#(\d+)", text, re.IGNORECASE)
    if order_match:
        data["type"] = order_match.group(1).lower() # purchase or sale
        data["order_id"] = order_match.group(2)

    # Dates. "Paid: 16.01.2026 07:26" or "Arrived: ..."
    # Logic:
    # If Sale: Arrived > Paid > Sent
    # If Purchase: Paid > Sent > Arrived
    
    date_match = None
    invoice_type = data.get("type", "purchase") # Default to purchase if not found? But regex above finds it.
    
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
    
    header_text = "\n".join(text.split('\n')[:20]) # First 20 lines
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
    
    lines = text.split('\n')
    parsing_items = False
    
    # Categories to look for start
    categories = ["One Piece Singles", "Singles", "Products", "One Piece Booster Boxes", "One Piece Promo Products"] # Add more as needed
    


    # Refactor loop to while with index to allow peeking
    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        idx += 1
        if not line: continue
        
        # Check Categories
        if any(line.startswith(c) and line.endswith(':') for c in categories):
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
                if ',' in price_str:
                    price_str = price_str.replace('.', '').replace(',', '.')
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
                             if ',' in price_str:
                                 price_str = price_str.replace('.', '').replace(',', '.')
                             price = float(price_str)
                             idx += 1 # Consume next line
            
            if qty > 0:
                 # Clean name
                 clean_name = name
                 parts = re.split(r'\s{2,}', name)
                 if len(parts) > 0:
                     clean_name = parts[0]
                     
                 # If Qty > 1, the price listed is the UNIT PRICE on these invoices.
                 # Validated via User feedback: 
                 # 2 Sanji @ 4.49 implies total 8.98.
                 # Article Value check confirms: 19.89 + 2*4.49 + 4.49 = 33.36 EUR.
                 
                 unit_price = price 
                 
                 for _ in range(qty):
                     data["items"].append({
                         "name": clean_name,
                         "raw_line": name, 
                         "price": unit_price
                     })
            else:
                # If we hit something that doesn't look like an item line (e.g. empty lines or footer)
                # and we are far down, maybe stop? But sometimes there are multiple categories.
                # So we just try to match patterns.
                pass

    return data
