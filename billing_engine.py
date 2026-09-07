import json
import uuid
from datetime import datetime
import database

def get_draft_bill(chat_id):
    """Retrieve active draft bill for the chat session, if any"""
    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM active_bills WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "chat_id": row["chat_id"],
            "items": json.loads(row["bill_items"]),
            "customer_id": row["customer_id"],
            "payment_mode": row["payment_mode"]
        }
    else:
        return {
            "chat_id": chat_id,
            "items": [],
            "customer_id": None,
            "payment_mode": None
        }

def save_draft_bill(chat_id, draft):
    """Save the active draft bill to the SQLite database (persistent memory)"""
    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR REPLACE INTO active_bills (chat_id, bill_items, customer_id, payment_mode)
    VALUES (?, ?, ?, ?)
    """, (chat_id, json.dumps(draft["items"]), draft["customer_id"], draft["payment_mode"]))
    conn.commit()
    conn.close()

def clear_draft_bill(chat_id):
    """Clear active draft bill once finalized or abandoned"""
    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM active_bills WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()

def parse_tax_breakdown(price_inclusive, gst_rate, quantity):
    """
    Given a GST-inclusive selling price, split it into Base Price and Tax.
    Indian Retail standard: MRP is inclusive of tax.
    Base = Inclusive / (1 + Rate / 100)
    Tax = Inclusive - Base
    """
    total_inclusive = price_inclusive * quantity
    base_price = total_inclusive / (1.0 + (gst_rate / 100.0))
    gst_amount = total_inclusive - base_price
    cgst = gst_amount / 2.0
    sgst = gst_amount / 2.0
    return {
        "base_total": round(base_price, 2),
        "gst_total": round(gst_amount, 2),
        "cgst": round(cgst, 2),
        "sgst": round(sgst, 2),
        "total": round(total_inclusive, 2)
    }

def add_item_to_draft(chat_id, query_text, quantity=1.0):
    """
    Find SKU by ID or fuzzy text, check if we have enough stock, 
    and append/update quantity in the active draft.
    Does not decrement database stock (only on finalize).
    """
    skus = database.query_sku(query_text)
    if not skus:
        raise KeyError(f"Product matching '{query_text}' could not be found.")
    
    # If ambiguous, raise error and let agent know (it will list them to user)
    if isinstance(skus, list):
        if len(skus) > 1:
            sku_names = [f"'{s['name']}' (ID: {s['sku_id']})" for s in skus]
            raise ValueError(f"Ambiguity found for '{query_text}'. Did you mean: {', '.join(sku_names)}?")
        sku = skus[0]
    else:
        sku = skus
        
    sku_id = sku["sku_id"]
    sku_name = sku["name"]
    unit = sku["unit"]
    
    # Check if we have enough total stock in database
    draft = get_draft_bill(chat_id)
    existing_qty = 0.0
    for item in draft["items"]:
        if item["sku_id"] == sku_id:
            existing_qty = item["quantity"]
            break
            
    total_requested = existing_qty + quantity
    if total_requested <= 0:
        raise ValueError("Total quantity requested must be positive.")
        
    if sku["quantity"] < total_requested:
        raise ValueError(f"Oversell Guard: Failed to add '{sku_name}'. Requested: {total_requested} {unit}, but only {sku['quantity']} {unit} is available in stock.")
        
    # Add or update in draft
    found = False
    for item in draft["items"]:
        if item["sku_id"] == sku_id:
            item["quantity"] = total_requested
            found = True
            break
            
    if not found:
        draft["items"].append({
            "sku_id": sku_id,
            "name": sku_name,
            "sell_price": sku["sell_price"],
            "quantity": quantity,
            "unit": unit,
            "gst_rate": sku["gst_rate"],
            "hsn_code": sku["hsn_code"]
        })
        
    save_draft_bill(chat_id, draft)
    return sku_name, total_requested, unit

def edit_item_in_draft(chat_id, query_text, action, quantity_val=None):
    """
    Modify an item already in the draft.
    action: 'SET_QTY' or 'DROP_ITEM'
    """
    draft = get_draft_bill(chat_id)
    if not draft["items"]:
        raise ValueError("No active draft bill found. Please start a bill first.")
        
    # Match query text with items in draft
    matched_item = None
    for item in draft["items"]:
        if query_text.upper().strip() in (item["sku_id"], item["name"].upper()):
            matched_item = item
            break
            
    if not matched_item:
        # Fuzzy check on draft names
        for item in draft["items"]:
            if query_text.lower().strip() in item["name"].lower():
                matched_item = item
                break
                
    if not matched_item:
        raise KeyError(f"Product '{query_text}' is not present in the current draft bill.")
        
    if action == 'DROP_ITEM':
        draft["items"] = [item for item in draft["items"] if item["sku_id"] != matched_item["sku_id"]]
        save_draft_bill(chat_id, draft)
        return f"Dropped {matched_item['name']} from the bill."
        
    elif action == 'SET_QTY':
        if quantity_val is None or quantity_val <= 0:
            raise ValueError("Quantity must be greater than zero.")
            
        # Get real SKU details to verify stock limit
        sku = database.query_sku(matched_item["sku_id"])
        if isinstance(sku, list):
            sku = sku[0]
            
        if sku["quantity"] < quantity_val:
            raise ValueError(f"Oversell Guard: Cannot change {matched_item['name']} quantity to {quantity_val}. Only {sku['quantity']} {sku['unit']} in stock.")
            
        matched_item["quantity"] = quantity_val
        save_draft_bill(chat_id, draft)
        return f"Updated {matched_item['name']} quantity to {quantity_val} {matched_item['unit']}."

def calculate_draft_totals(draft):
    """Perform full GST split, rounding, and summation over a draft bill"""
    subtotal = 0.0
    tax_total = 0.0
    cgst_total = 0.0
    sgst_total = 0.0
    items_breakdown = []
    
    for item in draft["items"]:
        calculations = parse_tax_breakdown(item["sell_price"], item["gst_rate"], item["quantity"])
        subtotal += calculations["base_total"]
        tax_total += calculations["gst_total"]
        cgst_total += calculations["cgst"]
        sgst_total += calculations["sgst"]
        
        items_breakdown.append({
            "sku_id": item["sku_id"],
            "name": item["name"],
            "quantity": item["quantity"],
            "unit": item["unit"],
            "sell_price": item["sell_price"],
            "gst_rate": item["gst_rate"],
            "hsn_code": item["hsn_code"],
            "base_total": calculations["base_total"],
            "gst_total": calculations["gst_total"],
            "cgst": calculations["cgst"],
            "sgst": calculations["sgst"],
            "total": calculations["total"]
        })
        
    total_amount = subtotal + tax_total
    
    return {
        "items": items_breakdown,
        "subtotal": round(subtotal, 2),
        "tax_total": round(tax_total, 2),
        "cgst_total": round(cgst_total, 2),
        "sgst_total": round(sgst_total, 2),
        "total_amount": round(total_amount, 2)
    }

def finalize_bill(chat_id, payment_mode="UPI", customer_name=None, payment_ref=None):
    """
    Finalize a draft bill:
    1. Validate item stock limits under database lock
    2. Atomic stock decrement
    3. Save sale record (Idempotent check via payment_ref)
    4. If credit (KHATA), update customer's balance
    5. Clean active draft
    """
    draft = get_draft_bill(chat_id)
    if not draft["items"]:
        raise ValueError("Cannot finalize an empty bill.")
        
    if not payment_ref:
        payment_ref = str(uuid.uuid4()) # Dynamic unique token
        
    totals = calculate_draft_totals(draft)
    
    with database._db_lock:
        conn = database.get_connection()
        cursor = conn.cursor()
        
        try:
            # Idempotency check: does this sale exist?
            cursor.execute("SELECT sale_id FROM sales WHERE payment_ref = ?", (payment_ref,))
            existing_sale = cursor.fetchone()
            if existing_sale:
                # Retrieve already generated details
                conn.close()
                return existing_sale["sale_id"], totals, "ALREADY_FINALIZED"
                
            # 1. Verify and atomic lock on stock quantities
            for item in totals["items"]:
                cursor.execute("SELECT quantity, name FROM inventory WHERE sku_id = ?", (item["sku_id"],))
                sku = cursor.fetchone()
                if not sku:
                    raise KeyError(f"Product {item['sku_id']} no longer exists in inventory.")
                if sku["quantity"] < item["quantity"]:
                    raise ValueError(f"Oversell Guard: Cannot finalize. '{sku['name']}' has only {sku['quantity']} units left in stock, but your bill requests {item['quantity']}.")
            
            # 2. Process Credit (KHATA) checks
            customer_id = None
            if payment_mode.upper() == "CREDIT" or customer_name:
                if not customer_name:
                    raise ValueError("A customer name is required for Khata credit ledger billing.")
                    
                cursor.execute("SELECT customer_id, balance FROM khata WHERE name = ?", (customer_name.strip(),))
                cust = cursor.fetchone()
                if not cust:
                    raise KeyError(f"Khata Settle Guard: Settle/credit request refused. No credit profile exists for customer '{customer_name}'. Please register them first.")
                customer_id = cust["customer_id"]
                
                # Update Khata credit balance
                new_balance = cust["balance"] + totals["total_amount"]
                cursor.execute("UPDATE khata SET balance = ? WHERE customer_id = ?", (new_balance, customer_id))
                
                # Transaction log
                timestamp = datetime.now().isoformat()
                cursor.execute("""
                INSERT INTO khata_transactions (customer_id, amount, type, timestamp)
                VALUES (?, ?, 'CREDIT', ?)
                """, (customer_id, totals["total_amount"], timestamp))
                
                payment_mode = "CREDIT" # Ensure aligned
                
            # 3. Create Sale Record
            timestamp = datetime.now().isoformat()
            cursor.execute("""
            INSERT INTO sales (timestamp, payment_mode, payment_ref, total_amount, total_tax)
            VALUES (?, ?, ?, ?, ?)
            """, (timestamp, payment_mode.upper(), payment_ref, totals["total_amount"], totals["tax_total"]))
            sale_id = cursor.lastrowid
            
            # 4. Insert Sale Items and Decrement stock atomatically
            for item in totals["items"]:
                cursor.execute("""
                INSERT INTO sale_items (sale_id, sku_id, quantity, price, tax_amount, gst_rate)
                VALUES (?, ?, ?, ?, ?, ?)
                """, (sale_id, item["sku_id"], item["quantity"], item["sell_price"], item["gst_total"], item["gst_rate"]))
                
                cursor.execute("""
                UPDATE inventory 
                SET quantity = quantity - ? 
                WHERE sku_id = ?
                """, (item["quantity"], item["sku_id"]))
                
            conn.commit()
            conn.close()
            
            # Clear active draft
            clear_draft_bill(chat_id)
            return sale_id, totals, "SUCCESS"
            
        except Exception as e:
            conn.rollback()
            conn.close()
            raise e
