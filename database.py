import sqlite3


def mark_order_complete(order_id):
    conn = sqlite3.connect('bedorme.db')
    c = conn.cursor()
    c.execute(
        "UPDATE orders SET status = 'complete' WHERE order_id = ?", (order_id,))
    conn.commit()
    conn.close()


def init_db():
    conn = sqlite3.connect('bedorme.db')
    c = conn.cursor()

    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, 
                  name TEXT, 
                  student_id TEXT, 
                  block TEXT, 
                  dorm_number TEXT, 
                  phone TEXT, 
                  is_deliverer INTEGER DEFAULT 0,
                  balance REAL DEFAULT 0,
                  tokens INTEGER DEFAULT 0)''')

    # Orders table
    c.execute('''CREATE TABLE IF NOT EXISTS orders
                 (order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  customer_id INTEGER,
                  deliverer_id INTEGER,
                  restaurant TEXT,
                  items TEXT,
                  total_price REAL,
                  status TEXT DEFAULT 'pending',
                  verification_code TEXT,
                  mid_delivery_proof TEXT,
                  proof_timestamp REAL,
                  delivery_proof TEXT,
                  delivery_lat REAL,
                  delivery_lon REAL)''')

    # Ratings table
    c.execute('''CREATE TABLE IF NOT EXISTS ratings
                 (order_id INTEGER,
                  rating INTEGER,
                  comment TEXT)''')

    conn.commit()
    conn.close()


def add_user(user_id, name, student_id, block, dorm_number, phone):
    conn = sqlite3.connect('bedorme.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (user_id, name, student_id, block, dorm_number, phone) VALUES (?, ?, ?, ?, ?, ?)",
              (user_id, name, student_id, block, dorm_number, phone))
    conn.commit()
    conn.close()


def register_deliverer(user_id):
    conn = sqlite3.connect('bedorme.db')
    c = conn.cursor()
    c.execute("UPDATE users SET is_deliverer = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def create_order(customer_id, restaurant, items, total_price, verification_code, lat=None, lon=None):
    conn = sqlite3.connect('bedorme.db')
    c = conn.cursor()
    c.execute("INSERT INTO orders (customer_id, restaurant, items, total_price, verification_code, delivery_lat, delivery_lon) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (customer_id, restaurant, items, total_price, verification_code, lat, lon))
    order_id = c.lastrowid
    conn.commit()
    conn.close()
    return order_id


def get_pending_orders():
    conn = sqlite3.connect('bedorme.db')
    c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE status = 'pending'")
    orders = c.fetchall()
    conn.close()
    return orders


def assign_deliverer(order_id, deliverer_id):
    conn = sqlite3.connect('bedorme.db')
    c = conn.cursor()

    # Atomic Check: Only assign if deliverer_id is NULL or 0 AND status is not cancelled
    c.execute("UPDATE orders SET deliverer_id = ?, status = 'accepted' WHERE order_id = ? AND (deliverer_id IS NULL OR deliverer_id = 0) AND status != 'cancelled'",
              (deliverer_id, order_id))

    rows_affected = c.rowcount
    conn.commit()
    conn.close()

    return rows_affected > 0


def save_rating(order_id, rating, comment=None):
    conn = sqlite3.connect('bedorme.db')
    c = conn.cursor()
    c.execute("INSERT INTO ratings (order_id, rating, comment) VALUES (?, ?, ?)",
              (order_id, rating, comment))
    conn.commit()
    conn.close()


def update_order_status(order_id, status):
    conn = sqlite3.connect('bedorme.db')
    c = conn.cursor()
    c.execute("UPDATE orders SET status = ? WHERE order_id = ?",
              (status, order_id))
    conn.commit()
    conn.close()


def set_mid_delivery_proof(order_id, file_id, timestamp):
    conn = sqlite3.connect('bedorme.db')
    c = conn.cursor()
    c.execute("UPDATE orders SET mid_delivery_proof = ?, proof_timestamp = ? WHERE order_id = ?",
              (file_id, timestamp, order_id))
    conn.commit()
    conn.close()


def set_delivery_proof(order_id, file_id):
    conn = sqlite3.connect('bedorme.db')
    c = conn.cursor()
    c.execute("UPDATE orders SET delivery_proof = ? WHERE order_id = ?",
              (file_id, order_id))
    conn.commit()
    conn.close()


def add_tokens(user_id, amount):
    conn = sqlite3.connect('bedorme.db')
    c = conn.cursor()
    c.execute("UPDATE users SET tokens = tokens + ? WHERE user_id = ?",
              (amount, user_id))
    conn.commit()
    conn.close()


def get_user_tokens(user_id):
    conn = sqlite3.connect('bedorme.db')
    c = conn.cursor()
    c.execute("SELECT tokens FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0


def get_order(order_id):
    conn = sqlite3.connect('bedorme.db')
    c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
    order = c.fetchone()
    conn.close()
    return order


def get_user(user_id):
    conn = sqlite3.connect('bedorme.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user


def get_deliverer_active_job(deliverer_id):
    conn = sqlite3.connect('bedorme.db')
    c = conn.cursor()
    c.execute(
        "SELECT * FROM orders WHERE deliverer_id = ? AND status = 'accepted'", (deliverer_id,))
    order = c.fetchone()
    conn.close()
    return order
