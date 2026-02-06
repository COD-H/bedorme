import sqlite3
import os
import psycopg2
import time
from urllib.parse import urlparse

DATABASE_URL = os.environ.get("DATABASE_URL")
DB_PATH = os.path.join(os.path.dirname(__file__), 'bedorme.db')
SUSPICIOUS_DB_PATH = os.path.join(os.path.dirname(__file__), 'suspicious_users.db')

def get_db_connection():
    if DATABASE_URL:
        # PostgreSQL connection
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    else:
        # SQLite connection
        conn = sqlite3.connect(DB_PATH)
        return conn

def get_suspicious_connection():
    return sqlite3.connect(SUSPICIOUS_DB_PATH)

def init_suspicious_db():
    conn = get_suspicious_connection()
    try:
        cur = conn.cursor()
        # Table for user data backup
        cur.execute('''CREATE TABLE IF NOT EXISTS deleted_users
                    (user_id INTEGER PRIMARY KEY, 
                    username TEXT,
                    name TEXT, 
                    student_id TEXT, 
                    block TEXT, 
                    dorm_number TEXT, 
                    phone TEXT, 
                    gender TEXT,
                    is_deliverer INTEGER,
                    balance REAL,
                    tokens INTEGER,
                    language TEXT,
                    is_banned INTEGER,
                    deleted_at REAL)''')
        
        # Table for past orders of deleted users
        cur.execute('''CREATE TABLE IF NOT EXISTS deleted_user_orders
                    (order_id INTEGER PRIMARY KEY,
                    customer_id INTEGER,
                    restaurant TEXT,
                    items TEXT,
                    total_price REAL,
                    status TEXT,
                    delivery_lat REAL,
                    delivery_lon REAL,
                    pickup_lat REAL,
                    pickup_lon REAL,
                    created_at REAL,
                    delivered_at REAL)''')

        # Table for unauthorized access attempts
        cur.execute('''CREATE TABLE IF NOT EXISTS security_breaches
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    username TEXT,
                    full_name TEXT,
                    phone TEXT,
                    reason TEXT,
                    timestamp REAL)''')
        conn.commit()
    finally:
        conn.close()

def log_suspicious_access(user_id, username, full_name, phone, reason):
    conn = get_suspicious_connection()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO security_breaches (user_id, username, full_name, phone, reason, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, username, full_name, phone, reason, time.time()))
        conn.commit()
    finally:
        conn.close()

def get_suspicious_data():
    conn = get_suspicious_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM security_breaches ORDER BY timestamp DESC")
        breaches = cur.fetchall()
        cur.execute("SELECT * FROM deleted_users ORDER BY deleted_at DESC")
        deleted = cur.fetchall()
        return {'breaches': breaches, 'deleted': deleted}
    finally:
        conn.close()

def delete_user_completely(user_id):
    """Backs up user data to suspicious DB and removes from main DB."""
    # 1. Fetch info from main DB
    main_conn = get_db_connection()
    susp_conn = get_suspicious_connection()
    try:
        # Get user
        cur = execute_query(main_conn, "SELECT * FROM users WHERE user_id = ?", (user_id,))
        user_row = cur.fetchone()
        
        if user_row:
            # Backup User
            scur = susp_conn.cursor()
            scur.execute("INSERT OR REPLACE INTO deleted_users VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", 
                        (*user_row, time.time()))
            
            # Backup Orders
            cur = execute_query(main_conn, "SELECT order_id, customer_id, restaurant, items, total_price, status, delivery_lat, delivery_lon, pickup_lat, pickup_lon, created_at, delivered_at FROM orders WHERE customer_id = ?", (user_id,))
            orders = cur.fetchall()
            for o in orders:
                scur.execute("INSERT OR REPLACE INTO deleted_user_orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", o)
            
            susp_conn.commit()
            
            # 2. Delete from main DB
            execute_query(main_conn, "DELETE FROM orders WHERE customer_id = ?", (user_id,))
            execute_query(main_conn, "DELETE FROM cafe_contracts WHERE user_id = ?", (user_id,))
            execute_query(main_conn, "DELETE FROM user_history WHERE user_id = ?", (user_id,))
            execute_query(main_conn, "DELETE FROM users WHERE user_id = ?", (user_id,))
            main_conn.commit()
            return True
        return False
    finally:
        main_conn.close()
        susp_conn.close()

def execute_query(conn, query, params=()):
    if DATABASE_URL:
        # Postgres uses %s placeholder
        query = query.replace('?', '%s')

    cur = conn.cursor()
    cur.execute(query, params)
    return cur

def mark_order_complete(order_id, lat=None, lon=None):
    conn = get_db_connection()
    try:
        execute_query(conn, "UPDATE orders SET status = 'complete', delivered_at = ?, delivery_lat = ?, delivery_lon = ? WHERE order_id = ?", 
                     (time.time(), lat, lon, order_id))
        conn.commit()
    finally:
        conn.close()

def get_active_users():
    conn = get_db_connection()
    try:
        t_limit = time.time() - 7*24*3600
        # Search for users with orders in the last 7 days
        cur = execute_query(conn, "SELECT * FROM users WHERE user_id IN (SELECT customer_id FROM orders WHERE created_at > ?)", (t_limit,))
        return cur.fetchall()
    finally:
        conn.close()

def get_contract_users():
    conn = get_db_connection()
    try:
        cur = execute_query(conn, "SELECT u.* FROM users u JOIN cafe_contracts c ON u.user_id = c.user_id")
        return cur.fetchall()
    finally:
        conn.close()

def get_regular_users():
    conn = get_db_connection()
    try:
        # Not in cafe_contracts
        cur = execute_query(conn, "SELECT * FROM users WHERE user_id NOT IN (SELECT user_id FROM cafe_contracts WHERE user_id IS NOT NULL)")
        return cur.fetchall()
    finally:
        conn.close()

def search_users(query):
    conn = get_db_connection()
    try:
        q = f"%{query}%"
        cur = execute_query(conn, "SELECT * FROM users WHERE name LIKE ? OR student_id LIKE ? OR phone LIKE ? OR username LIKE ?", (q, q, q, q))
        return cur.fetchall()
    finally:
        conn.close()


def init_db():
    conn = get_db_connection()
    try:
        if DATABASE_URL:
             # PostgreSQL syntax
            execute_query(conn, '''CREATE TABLE IF NOT EXISTS users
                        (user_id BIGINT PRIMARY KEY, 
                        username TEXT,
                        name TEXT, 
                        student_id TEXT, 
                        block TEXT, 
                        dorm_number TEXT, 
                        phone TEXT, 
                        gender TEXT,
                        is_deliverer INTEGER DEFAULT 0,
                        balance REAL DEFAULT 0,
                        tokens INTEGER DEFAULT 0,
                        language TEXT DEFAULT NULL,
                        is_banned INTEGER DEFAULT 0)''')
            
            execute_query(conn, '''CREATE TABLE IF NOT EXISTS orders
                        (order_id SERIAL PRIMARY KEY,
                        customer_id BIGINT,
                        deliverer_id BIGINT,
                        restaurant TEXT,
                        items TEXT,
                        total_price REAL,
                        status TEXT DEFAULT 'pending',
                        order_type TEXT DEFAULT 'regular',
                        verification_code TEXT,
                        mid_delivery_proof TEXT,
                        proof_timestamp REAL,
                        delivery_proof TEXT,
                        delivery_lat REAL,
                        delivery_lon REAL,
                        pickup_lat REAL,
                        pickup_lon REAL,
                        created_at REAL,
                        delivered_at REAL,
                        is_test INTEGER DEFAULT 0)''')
            
            # --- Check for missing columns (Migrations) ---
            try:
                execute_query(conn, "SELECT is_test FROM orders LIMIT 1")
            except Exception:
                # Add is_test column if missing
                print("Migrating DB: Adding is_test column to orders")
                conn.rollback() # Postgres requires rollback after error
                try:
                   execute_query(conn, "ALTER TABLE orders ADD COLUMN is_test INTEGER DEFAULT 0")
                   conn.commit()
                except Exception as e:
                   print(f"Migration failed: {e}")

            execute_query(conn, '''CREATE TABLE IF NOT EXISTS cafe_contracts
                        (id SERIAL PRIMARY KEY, 
                        user_id BIGINT, 
                        cafe_name TEXT, 
                        phone TEXT, 
                        username TEXT, 
                        full_name TEXT, 
                        contract_id TEXT,
                        list_order INTEGER,
                        total_paid REAL DEFAULT 0,
                        balance_used REAL DEFAULT 0,
                        current_balance REAL DEFAULT 0,
                        credit_meals INTEGER DEFAULT 0,
                        start_date REAL)''')
            
            execute_query(conn, '''CREATE TABLE IF NOT EXISTS unavailable_items
                        (restaurant TEXT, item TEXT, PRIMARY KEY (restaurant, item))''')
        else:
            # SQLite syntax
            execute_query(conn, '''CREATE TABLE IF NOT EXISTS users
                        (user_id INTEGER PRIMARY KEY, 
                        username TEXT,
                        name TEXT, 
                        student_id TEXT, 
                        block TEXT, 
                        dorm_number TEXT, 
                        phone TEXT, 
                        gender TEXT,
                        is_deliverer INTEGER DEFAULT 0,
                        balance REAL DEFAULT 0,
                        tokens INTEGER DEFAULT 0,
                        language TEXT DEFAULT NULL,
                        is_banned INTEGER DEFAULT 0)''')

            # Migration: Robustly add columns if they don't exist
            columns_to_add = [
                ("username", "TEXT"),
                ("language", "TEXT DEFAULT NULL"),
                ("gender", "TEXT"),
                ("is_banned", "INTEGER DEFAULT 0")
            ]
            for col_name, col_type in columns_to_add:
                try:
                    execute_query(conn, f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
                except sqlite3.OperationalError:
                    pass  # Column already exists

            execute_query(conn, '''CREATE TABLE IF NOT EXISTS user_history
                        (history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        old_name TEXT,
                        old_username TEXT,
                        old_phone TEXT,
                        old_student_id TEXT,
                        old_block TEXT,
                        old_dorm_number TEXT,
                        old_gender TEXT,
                        change_timestamp REAL)''')
            
            # Migration for user_history
            try:
                execute_query(conn, "ALTER TABLE user_history ADD COLUMN old_gender TEXT")
            except sqlite3.OperationalError:
                pass


            execute_query(conn, '''CREATE TABLE IF NOT EXISTS orders
                        (order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        customer_id INTEGER,
                        deliverer_id INTEGER,
                        restaurant TEXT,
                        items TEXT,
                        total_price REAL,
                        status TEXT DEFAULT 'pending',
                        order_type TEXT DEFAULT 'regular',
                        verification_code TEXT,
                        mid_delivery_proof TEXT,
                        proof_timestamp REAL,
                        delivery_proof TEXT,
                        delivery_lat REAL,
                        delivery_lon REAL,
                        created_at REAL,
                        delivered_at REAL,
                        is_test INTEGER DEFAULT 0)''')
            
            # Migration for orders
            migration_cols = [
                ("order_type", "TEXT DEFAULT 'regular'"),
                ("created_at", "REAL"),
                ("delivered_at", "REAL"),
                ("delivery_lat", "REAL"),
                ("delivery_lon", "REAL"),
                ("pickup_lat", "REAL"),
                ("pickup_lon", "REAL"),
                ("is_test", "INTEGER DEFAULT 0")
            ]
            for col_name, col_type in migration_cols:
                try:
                    execute_query(conn, f"ALTER TABLE orders ADD COLUMN {col_name} {col_type}")
                except sqlite3.OperationalError:
                    pass

        execute_query(conn, '''CREATE TABLE IF NOT EXISTS ratings
                    (order_id INTEGER,
                    rating INTEGER,
                    comment TEXT)''')

        execute_query(conn, '''CREATE TABLE IF NOT EXISTS cafe_contracts
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                    user_id BIGINT, 
                    cafe_name TEXT, 
                    phone TEXT, 
                    username TEXT, 
                    full_name TEXT, 
                    contract_id TEXT,
                    list_order INTEGER,
                    total_paid REAL DEFAULT 0,
                    balance_used REAL DEFAULT 0,
                    current_balance REAL DEFAULT 0,
                    credit_meals INTEGER DEFAULT 0,
                    start_date REAL)''')

        execute_query(conn, '''CREATE TABLE IF NOT EXISTS unavailable_items
                    (restaurant TEXT, item TEXT, PRIMARY KEY (restaurant, item))''')

        execute_query(conn, '''CREATE TABLE IF NOT EXISTS system_config
                    (key TEXT PRIMARY KEY, value TEXT)''')
def add_user(user_id, username, name, student_id, block, dorm_number, phone, gender=None):
    conn = get_db_connection()
    changes = {}
    try:
        # Check if user exists to preserve balance/tokens/role if we are just updating info
        cur = execute_query(conn, 
            "SELECT name, username, phone, student_id, block, dorm_number, gender FROM users WHERE user_id = ?", (user_id,))
        existing = cur.fetchone()

        if existing:
            old_name, old_username, old_phone, old_student_id, old_block, old_dorm_number, old_gender = existing
            
            # Check for changes
            if old_name != name: changes['name'] = (old_name, name)
            if old_phone != phone: changes['phone'] = (old_phone, phone)
            
            if changes:
                execute_query(conn, """INSERT INTO user_history 
                    (user_id, old_name, old_username, old_phone, old_student_id, old_block, old_dorm_number, old_gender, change_timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (user_id, old_name, old_username, old_phone, old_student_id, old_block, old_dorm_number, old_gender, time.time()))

            execute_query(conn, """UPDATE users 
                        SET username=?, name=?, student_id=?, block=?, dorm_number=?, phone=?, gender=? 
                        WHERE user_id=?""",
                    (username, name, student_id, block, dorm_number, phone, gender, user_id))
        else:
            execute_query(conn, "INSERT INTO users (user_id, username, name, student_id, block, dorm_number, phone, gender) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (user_id, username, name, student_id, block, dorm_number, phone, gender))

        conn.commit()
        return changes
    finally:
        conn.close()


def register_deliverer(user_id):
    conn = get_db_connection()
    try:
        execute_query(conn, "UPDATE users SET is_deliverer = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def create_order(customer_id, restaurant, items, total_price, verification_code, lat=None, lon=None, pickup_lat=None, pickup_lon=None, order_type='regular'):
    conn = get_db_connection()
    created_at = time.time()
    try:
        query = "INSERT INTO orders (customer_id, restaurant, items, total_price, verification_code, delivery_lat, delivery_lon, pickup_lat, pickup_lon, created_at, order_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        params = (customer_id, restaurant, items, total_price, verification_code, lat, lon, pickup_lat, pickup_lon, created_at, order_type)
        
        if DATABASE_URL:
            # Postgres: use %s and RETURNING to get ID
            cur = execute_query(conn, query + " RETURNING order_id", params)
            order_id = cur.fetchone()[0]
        else:
            # SQLite
            cur = execute_query(conn, query, params)
            order_id = cur.lastrowid
            
        conn.commit()
        return order_id
    finally:
        conn.close()


def get_pending_orders():
    conn = get_db_connection()
    try:
        query = """SELECT order_id, customer_id, deliverer_id, restaurant, items, total_price, status, order_type, verification_code, 
                   mid_delivery_proof, proof_timestamp, delivery_proof, delivery_lat, delivery_lon, pickup_lat, pickup_lon, created_at, delivered_at 
                   FROM orders WHERE status = 'pending'"""
        cur = execute_query(conn, query)
        orders = cur.fetchall()
        return orders
    finally:
        conn.close()


def assign_deliverer(order_id, deliverer_id):
    conn = get_db_connection()
    try:
        # Atomic Check: Only assign if deliverer_id is NULL or 0 AND status is not cancelled
        cur = execute_query(conn, "UPDATE orders SET deliverer_id = ?, status = 'accepted' WHERE order_id = ? AND (deliverer_id IS NULL OR deliverer_id = 0) AND status != 'cancelled'",
                (deliverer_id, order_id))

        rows_affected = cur.rowcount
        conn.commit()
        return rows_affected > 0
    finally:
        conn.close()


def save_rating(order_id, rating, comment=None):
    conn = get_db_connection()
    try:
        execute_query(conn, "INSERT INTO ratings (order_id, rating, comment) VALUES (?, ?, ?)",
                (order_id, rating, comment))
        conn.commit()
    finally:
        conn.close()


def update_order_status(order_id, status):
    conn = get_db_connection()
    try:
        execute_query(conn, "UPDATE orders SET status = ? WHERE order_id = ?",
                (status, order_id))
        conn.commit()
    finally:
        conn.close()


def set_mid_delivery_proof(order_id, file_id, timestamp):
    conn = get_db_connection()
    try:
        execute_query(conn, "UPDATE orders SET mid_delivery_proof = ?, proof_timestamp = ? WHERE order_id = ?",
                (file_id, timestamp, order_id))
        conn.commit()
    finally:
        conn.close()


def set_delivery_proof(order_id, file_id):
    conn = get_db_connection()
    try:
        execute_query(conn, "UPDATE orders SET delivery_proof = ? WHERE order_id = ?",
                (file_id, order_id))
        conn.commit()
    finally:
        conn.close()


def add_tokens(user_id, amount):
    conn = get_db_connection()
    try:
        execute_query(conn, "UPDATE users SET tokens = tokens + ? WHERE user_id = ?",
                (amount, user_id))
        conn.commit()
    finally:
        conn.close()


def get_user_tokens(user_id):
    conn = get_db_connection()
    try:
        cur = execute_query(conn, "SELECT tokens FROM users WHERE user_id = ?", (user_id,))
        result = cur.fetchone()
        return result[0] if result else 0
    finally:
        conn.close()


def get_order(order_id):
    conn = get_db_connection()
    try:
        # Explicitly define column order to ensure consistent indexing in the UI
        # 0:order_id, 1:customer_id, 2:deliverer_id, 3:restaurant, 4:items, 5:total_price, 6:status, 7:order_type, 8:verification_code, 9+: proof, lat, lon etc.
        query = """SELECT order_id, customer_id, deliverer_id, restaurant, items, total_price, status, order_type, verification_code, 
                   mid_delivery_proof, proof_timestamp, delivery_proof, delivery_lat, delivery_lon, pickup_lat, pickup_lon, created_at, delivered_at 
                   FROM orders WHERE order_id = ?"""
        cur = execute_query(conn, query, (order_id,))
        order = cur.fetchone()
        return order
    finally:
        conn.close()


def get_user(user_id):
    conn = get_db_connection()
    try:
        cur = execute_query(conn, "SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cur.fetchone()
        return user
    finally:
        conn.close()


def get_deliverer_active_job(deliverer_id):
    conn = get_db_connection()
    try:
        query = """SELECT order_id, customer_id, deliverer_id, restaurant, items, total_price, status, order_type, verification_code, 
                   mid_delivery_proof, proof_timestamp, delivery_proof, delivery_lat, delivery_lon, pickup_lat, pickup_lon, created_at, delivered_at 
                   FROM orders WHERE deliverer_id = ? AND status = 'accepted'"""
        cur = execute_query(conn, query, (deliverer_id,))
        order = cur.fetchone()
        return order
    finally:
        conn.close()


def update_order_location(order_id, lat, lon):
    conn = get_db_connection()
    try:
        execute_query(conn, "UPDATE orders SET delivery_lat = ?, delivery_lon = ? WHERE order_id = ?",
                (lat, lon, order_id))
        conn.commit()
    finally:
        conn.close()


def get_user_active_orders(user_id):
    conn = get_db_connection()
    try:
        # User can be customer OR deliverer
        cur = execute_query(conn, "SELECT order_id FROM orders WHERE (customer_id = ? OR deliverer_id = ?) AND status IN ('pending', 'accepted', 'picked_up')", (user_id, user_id))
        orders = cur.fetchall()
        return [o[0] for o in orders]
    finally:
        conn.close()


def set_user_language(user_id, language):
    conn = get_db_connection()
    try:
        execute_query(conn, "UPDATE users SET language = ? WHERE user_id = ?", (language, user_id))
        conn.commit()
    finally:
        conn.close()


def get_user_language(user_id):
    conn = get_db_connection()
    try:
        cur = execute_query(conn, "SELECT language FROM users WHERE user_id = ?", (user_id,))
        res = cur.fetchone()
        return res[0] if res else None
    finally:
        conn.close()

def ban_user(user_id):
    conn = get_db_connection()
    try:
        execute_query(conn, "UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()

def get_full_user_info(user_id):
    conn = get_db_connection()
    try:
        cur = execute_query(conn, "SELECT * FROM users WHERE user_id = ?", (user_id,))
        user_row = cur.fetchone()
        
        if not user_row:
            return None
            
        cur = execute_query(conn, "SELECT * FROM user_history WHERE user_id = ? ORDER BY change_timestamp DESC", (user_id,))
        history = cur.fetchall()
        
        query = """SELECT order_id, customer_id, deliverer_id, restaurant, items, total_price, status, order_type, verification_code, 
                   mid_delivery_proof, proof_timestamp, delivery_proof, delivery_lat, delivery_lon, pickup_lat, pickup_lon, created_at, delivered_at 
                   FROM orders WHERE customer_id = ? OR deliverer_id = ? ORDER BY order_id DESC"""
        cur = execute_query(conn, query, (user_id, user_id))
        orders = cur.fetchall()
        
        return {
            'info': user_row,
            'history': history,
            'orders': orders
        }
    finally:
        conn.close()

def add_cafe_contract(user_id, cafe_name, phone, username, full_name, contract_id, list_order, total_paid):
    conn = get_db_connection()
    try:
        start_date = time.time()
        execute_query(conn, """INSERT INTO cafe_contracts 
                (user_id, cafe_name, phone, username, full_name, contract_id, list_order, total_paid, current_balance, start_date) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, cafe_name, phone, username, full_name, contract_id, list_order, total_paid, total_paid, start_date))
        conn.commit()
    finally:
        conn.close()

def get_contract_details(user_id, cafe_name):
    conn = get_db_connection()
    try:
        cur = execute_query(conn, "SELECT total_paid, balance_used, current_balance, credit_meals FROM cafe_contracts WHERE user_id = ? AND cafe_name = ?", (user_id, cafe_name))
        row = cur.fetchone()
        if row:
            return {
                'total_paid': row[0],
                'balance_used': row[1],
                'current_balance': row[2],
                'credit_meals': row[3]
            }
        return None
    finally:
        conn.close()

def update_contract_payment(user_id, cafe_name, amount):
    """Subtract amount from balance, track credit meals if balance empty. Max 2 credits."""
    conn = get_db_connection()
    try:
        cur = execute_query(conn, "SELECT current_balance, balance_used, credit_meals FROM cafe_contracts WHERE user_id = ? AND cafe_name = ?", (user_id, cafe_name))
        row = cur.fetchone()
        if row:
            curr_bal, used, credit = row
            
            # If current balance is already negative and credit is >= 2, fail
            if curr_bal <= 0 and credit >= 2:
                return "credit_limit_reached"
                
            new_bal = curr_bal - amount
            new_used = used + amount
            new_credit = credit
            if curr_bal <= 0:
                new_credit += 1
            
            execute_query(conn, "UPDATE cafe_contracts SET current_balance = ?, balance_used = ?, credit_meals = ? WHERE user_id = ? AND cafe_name = ?", 
                          (new_bal, new_used, new_credit, user_id, cafe_name))
            conn.commit()
            return "success"
        return "no_contract"
    finally:
        conn.close()

def is_contract_user(user_id, cafe_name):
    conn = get_db_connection()
    try:
        cur = execute_query(conn, "SELECT 1 FROM cafe_contracts WHERE user_id = ? AND cafe_name = ?", (user_id, cafe_name))
        return cur.fetchone() is not None
    finally:
        conn.close()

def get_all_admins():
    """List all users who are deliverers."""
    conn = get_db_connection()
    try:
        cur = execute_query(conn, "SELECT user_id, username, name, phone FROM users WHERE is_deliverer = 1")
        return cur.fetchall()
    finally:
        conn.close()

def set_user_as_admin(user_id, is_admin=1):
    conn = get_db_connection()
    try:
        execute_query(conn, "UPDATE users SET is_deliverer = ? WHERE user_id = ?", (is_admin, user_id))
        conn.commit()
    finally:
        conn.close()

def get_user_by_username(username):
    """Find a user_id by username from the users table."""
    if not username:
        return None
    username = username.lstrip('@').lower()
    conn = get_db_connection()
    try:
        # Check both with and without @
        cur = execute_query(conn, "SELECT user_id FROM users WHERE LOWER(username) = ? OR LOWER(username) = ?", (username, f"@{username}"))
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()

def toggle_item_availability(restaurant, item):
    """Toggle whether an item is available. Returns True if now available, False if now unavailable."""
    conn = get_db_connection()
    try:
        cur = execute_query(conn, "SELECT 1 FROM unavailable_items WHERE restaurant = ? AND item = ?", (restaurant, item))
        if cur.fetchone():
            execute_query(conn, "DELETE FROM unavailable_items WHERE restaurant = ? AND item = ?", (restaurant, item))
            conn.commit()
            return True
        else:
            execute_query(conn, "INSERT INTO unavailable_items (restaurant, item) VALUES (?, ?)", (restaurant, item))
            conn.commit()
            return False
    finally:
        conn.close()

def get_unavailable_items(restaurant=None):
    """Get list of unavailable items. If restaurant provided, only for that one."""
    conn = get_db_connection()
    try:
        if restaurant:
            cur = execute_query(conn, "SELECT item FROM unavailable_items WHERE restaurant = ?", (restaurant,))
            return [r[0] for r in cur.fetchall()]
        else:
            cur = execute_query(conn, "SELECT restaurant, item FROM unavailable_items")
            return cur.fetchall()
    finally:
        conn.close()

def set_test_mode(enabled: bool):
    """Sets the system-wide test mode flag."""
    conn = get_db_connection()
    try:
        val = "1" if enabled else "0"
        conn.cursor().execute("INSERT OR REPLACE INTO system_config (key, value) VALUES ('test_mode', ?)", (val,))
        conn.commit()
    finally:
        conn.close()

def is_test_mode_active():
    """Checks if test mode is active."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        # Handle table missing if not init (rare but possible during migration)
        try:
            cur.execute("SELECT value FROM system_config WHERE key = 'test_mode'")
            row = cur.fetchone()
            if row and row[0] == "1":
                return True
        except Exception:
            pass
        return False
    finally:
        conn.close()

def clear_stats_data():
    """Marks all existing completed orders as test data (is_test=1) to reset stats."""
    conn = get_db_connection()
    try:
        # Mark all current orders as test
        conn.cursor().execute("UPDATE orders SET is_test = 1 WHERE is_test = 0")
        conn.commit()
        return True
    except Exception as e:
        print(f"Failed to clear stats: {e}")
        return False
    finally:
        conn.close()

