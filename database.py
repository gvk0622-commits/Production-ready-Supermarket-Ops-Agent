import sqlite3
import json
import threading
from datetime import datetime

DB_FILE = "kirana_store.db"
_db_lock = threading.Lock()

def get_connection():
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        # 1. Inventory Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            sku_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            cost_price REAL NOT NULL,
            mrp REAL NOT NULL,
            sell_price REAL NOT NULL,
            quantity REAL NOT NULL DEFAULT 0,
            unit TEXT NOT NULL,
            reorder_level REAL NOT NULL DEFAULT 0,
            gst_rate REAL NOT NULL, -- percentage e.g. 5.0, 12.0, 18.0
            hsn_code TEXT NOT NULL
        );
        """)
        
        # 2. Khata Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS khata (
            customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            balance REAL NOT NULL DEFAULT 0.0
        );
        """)
        
        # 3. Khata Transactions
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS khata_transactions (
            transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,
            amount REAL NOT NULL,
            type TEXT NOT NULL, -- 'CREDIT' (adds to balance) or 'PAYMENT' (reduces balance)
            timestamp TEXT NOT NULL,
            FOREIGN KEY (customer_id) REFERENCES khata(customer_id)
        );
        """)
        
        # 4. Sales Table (Idempotent tracking with payment_ref/uuid)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            sale_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            payment_mode TEXT NOT NULL, -- 'CASH', 'UPI', 'CARD', 'CREDIT'
            payment_ref TEXT UNIQUE, -- Idempotency token (e.g., UUID or unique telegram update_id)
            total_amount REAL NOT NULL,
            total_tax REAL NOT NULL
        );
        """)
        
        # 5. Sale Items Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS sale_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER,
            sku_id TEXT,
            quantity REAL NOT NULL,
            price REAL NOT NULL, -- price per unit at sale time (inclusive of GST)
            tax_amount REAL NOT NULL, -- total GST collected on this item
            gst_rate REAL NOT NULL,
            FOREIGN KEY (sale_id) REFERENCES sales(sale_id),
            FOREIGN KEY (sku_id) REFERENCES inventory(sku_id)
        );
        """)
        
        # 6. Session Preferences Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS preferences (
            pref_key TEXT PRIMARY KEY,
            pref_value TEXT NOT NULL
        );
        """)
        
        # 7. Multi-turn Bills (State stored out of RAM, session-persistent)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS active_bills (
            chat_id INTEGER PRIMARY KEY,
            bill_items TEXT NOT NULL DEFAULT '[]', -- JSON string of items in active draft
            customer_id INTEGER, -- Optional, if credit customer linked
            payment_mode TEXT, -- Default payment preference
            FOREIGN KEY (customer_id) REFERENCES khata(customer_id)
        );
        """)
        
        conn.commit()
        conn.close()

def seed_database():
    """Seed the database with real Indian grocery SKUs as specified in JD and common items"""
    items = [
        ("AASH_ATTA_5KG", "Aashirvaad Atta 5kg", 210.0, 240.0, 230.0, 20.0, "packet", 5.0, 5.0, "1101"),
        ("TATA_SALT_1KG", "Tata Salt 1kg", 20.0, 28.0, 26.0, 50.0, "packet", 10.0, 0.0, "2501"),  # Essential staples at 0% or 5%
        ("AMUL_BUT_100G", "Amul Butter 100g", 50.0, 62.0, 60.0, 15.0, "piece", 3.0, 12.0, "0405"),  # Dairy packaged at 12%
        ("FORT_SUN_1L", "Fortune Sunflower Oil 1L", 110.0, 135.0, 130.0, 30.0, "litre", 8.0, 5.0, "1512"), # Edible oil at 5%
        ("MAGGI_70G", "Maggi 70g", 11.0, 14.0, 13.5, 100.0, "packet", 15.0, 18.0, "1902"),  # FMCG at 18%
        ("PARLE_G_250G", "Parle-G 250g", 15.0, 20.0, 19.0, 40.0, "packet", 8.0, 18.0, "1905"),
        ("SURF_EXCEL_1KG", "Surf Excel 1kg", 110.0, 140.0, 135.0, 25.0, "packet", 5.0, 18.0, "3402"),  # Detergents at 18%
        ("LOOSE_SUGAR_KG", "Sugar Loose (per kg)", 36.0, 44.0, 42.0, 150.0, "kg", 20.0, 5.0, "1701"),  # Sugar at 5%
        ("LOOSE_RICE_KG", "Basmati Rice (per kg)", 80.0, 110.0, 100.0, 200.0, "kg", 30.0, 0.0, "1006"),  # Unbranded loose grain at 0%
        ("LOOSE_DAL_KG", "Toor Dal Loose (per kg)", 120.0, 160.0, 150.0, 100.0, "kg", 15.0, 0.0, "0713")  # Loose pulse at 0%
    ]
    
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        for item in items:
            cursor.execute("""
            INSERT OR IGNORE INTO inventory (sku_id, name, cost_price, mrp, sell_price, quantity, unit, reorder_level, gst_rate, hsn_code)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, item)
            
        # Seed some dummy customer khata credit lines
        customers = [("Ramesh", 500.0), ("Suresh", 0.0), ("Mahesh", 1500.0)]
        for name, balance in customers:
            cursor.execute("INSERT OR IGNORE INTO khata (name, balance) VALUES (?, ?)", (name, balance))
            
        # Seed some preferences
        cursor.execute("INSERT OR IGNORE INTO preferences (pref_key, pref_value) VALUES ('shop_name', 'Sri Krishna Kirana Store')")
        cursor.execute("INSERT OR IGNORE INTO preferences (pref_key, pref_value) VALUES ('shop_gstin', '33AAAAA1111A1Z0')")
        cursor.execute("INSERT OR IGNORE INTO preferences (pref_key, pref_value) VALUES ('default_payment_mode', 'UPI')")
        
        conn.commit()
        conn.close()

# Concurrency Guarded Database Tool Actions

def query_sku(query_text):
    """Find SKU details by ID or fuzzy text search on name"""
    conn = get_connection()
    cursor = conn.cursor()
    # Try exact match on ID
    cursor.execute("SELECT * FROM inventory WHERE sku_id = ?", (query_text.strip(),))
    row = cursor.fetchone()
    if row:
        conn.close()
        return dict(row)
    
    # Try fuzzy match on name
    cursor.execute("SELECT * FROM inventory WHERE name LIKE ?", (f"%{query_text.strip()}%",))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_all_inventory():
    """Retrieve full inventory list"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inventory")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_low_stock_items():
    """Identify items whose quantity is below or equal to their reorder level"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inventory WHERE quantity <= reorder_level")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_new_sku(sku_id, name, cost_price, mrp, sell_price, quantity, unit, reorder_level, gst_rate, hsn_code):
    """Integrates a brand new SKU into the inventory. Enforces non-negative values."""
    if cost_price < 0 or mrp < 0 or sell_price < 0 or quantity < 0 or reorder_level < 0:
        raise ValueError("Financial figures and inventory counts cannot be negative.")
    if sell_price < cost_price:
        raise ValueError(f"Warning: Selling price (₹{sell_price}) cannot be lower than cost price (₹{cost_price}).")
    
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT OR REPLACE INTO inventory (sku_id, name, cost_price, mrp, sell_price, quantity, unit, reorder_level, gst_rate, hsn_code)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (sku_id.upper().strip(), name.strip(), cost_price, mrp, sell_price, quantity, unit.strip().lower(), reorder_level, gst_rate, hsn_code.strip()))
        conn.commit()
        conn.close()

def update_stock_quantity(sku_id, quantity_change):
    """Receive stock or manually adjust it. Positive adds stock, negative reduces stock."""
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT quantity, name FROM inventory WHERE sku_id = ?", (sku_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            raise KeyError(f"SKU {sku_id} not found in database.")
        
        current_qty = row["quantity"]
        new_qty = current_qty + quantity_change
        if new_qty < 0:
            conn.close()
            raise ValueError(f"Oversell Guard: Current stock for {row['name']} is {current_qty}, cannot reduce by {-quantity_change}.")
            
        cursor.execute("UPDATE inventory SET quantity = ? WHERE sku_id = ?", (new_qty, sku_id))
        conn.commit()
        conn.close()

# Khata (Credit Ledger) Actions

def get_khata_customer(name):
    """Get customer credit line details"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM khata WHERE name LIKE ?", (f"%{name.strip()}%",))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def record_khata_credit(customer_name, amount, payment_ref=None):
    """Record a purchase on credit (adds to customer's balance)"""
    if amount <= 0:
        raise ValueError("Credit amount must be greater than zero.")
    
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM khata WHERE name = ?", (customer_name.strip(),))
        customer = cursor.fetchone()
        
        if not customer:
            # Create a new khata customer dynamically if not exists, after validating
            cursor.execute("INSERT INTO khata (name, balance) VALUES (?, ?)", (customer_name.strip(), amount))
            customer_id = cursor.lastrowid
        else:
            customer_id = customer["customer_id"]
            new_balance = customer["balance"] + amount
            cursor.execute("UPDATE khata SET balance = ? WHERE customer_id = ?", (new_balance, customer_id))
            
        timestamp = datetime.now().isoformat()
        cursor.execute("""
        INSERT INTO khata_transactions (customer_id, amount, type, timestamp)
        VALUES (?, ?, 'CREDIT', ?)
        """, (customer_id, amount, timestamp))
        
        conn.commit()
        conn.close()
        return customer_id

def record_khata_payment(customer_name, amount):
    """Settle an existing credit balance. Enforces safety rule: don't settle non-existent khata."""
    if amount <= 0:
        raise ValueError("Payment amount must be greater than zero.")
        
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM khata WHERE name = ?", (customer_name.strip(),))
        customer = cursor.fetchone()
        
        if not customer:
            conn.close()
            raise KeyError(f"Safety Rule Violations: Settle request refused. No khata account exists for '{customer_name}'. Please create/record a purchase first.")
            
        customer_id = customer["customer_id"]
        current_balance = customer["balance"]
        new_balance = current_balance - amount
        
        # Balance can go slightly negative (overpayment credit) but we'll allow it or cap at 0
        cursor.execute("UPDATE khata SET balance = ? WHERE customer_id = ?", (new_balance, customer_id))
        
        timestamp = datetime.now().isoformat()
        cursor.execute("""
        INSERT INTO khata_transactions (customer_id, amount, type, timestamp)
        VALUES (?, ?, 'PAYMENT', ?)
        """, (customer_id, amount, timestamp))
        
        conn.commit()
        conn.close()
        return new_balance

# Persistent Session Storage (Owner Preferences)

def set_preference(key, value):
    with _db_lock:
        conn = get_connection()
        conn.execute("INSERT OR REPLACE INTO preferences (pref_key, pref_value) VALUES (?, ?)", (key.strip(), value.strip()))
        conn.commit()
        conn.close()

def get_preference(key, default=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT pref_value FROM preferences WHERE pref_key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row["pref_value"] if row else default

def get_all_preferences():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM preferences")
    rows = cursor.fetchall()
    conn.close()
    return {r["pref_key"]: r["pref_value"] for r in rows}
