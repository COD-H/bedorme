import sqlite3
import os
import psycopg2
from urllib.parse import urlparse

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db_connection():
    if DATABASE_URL:
        # PostgreSQL connection
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    else:
        # SQLite connection
        conn = sqlite3.connect('bedorme.db')
        return conn

def execute_query(conn, query, params=()):
    if DATABASE_URL:
        # Postgres uses %s placeholder
        query = query.replace('?', '%s')
    
    cur = conn.cursor()
    cur.execute(query, params)
    return cur

def mark_order_complete(order_id):
    conn = get_db_connection()
    try:
        execute_query(conn, "UPDATE orders SET status = 'complete' WHERE order_id = ?", (order_id,))
        conn.commit()
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
                        is_deliverer INTEGER DEFAULT 0,
                        balance REAL DEFAULT 0,
                        tokens INTEGER DEFAULT 0,
                        language TEXT DEFAULT NULL)''')
            
            execute_query(conn, '''CREATE TABLE IF NOT EXISTS orders
                        (order_id SERIAL PRIMARY KEY,
                        customer_id BIGINT,
                        deliverer_id BIGINT,
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
                        is_deliverer INTEGER DEFAULT 0,
                        balance REAL DEFAULT 0,
                        tokens INTEGER DEFAULT 0,
                        language TEXT DEFAULT NULL)''')

            # Migration to add username column if it doesn't exist (for existing databases)
            try:
                execute_query(conn, "ALTER TABLE users ADD COLUMN username TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists

            # Migration to add language column if it doesn't exist
            try:
                execute_query(conn, "ALTER TABLE users ADD COLUMN language TEXT DEFAULT NULL")
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
                        verification_code TEXT,
                        mid_delivery_proof TEXT,
                        proof_timestamp REAL,
                        delivery_proof TEXT,
                        delivery_lat REAL,
                        delivery_lon REAL)''')

        execute_query(conn, '''CREATE TABLE IF NOT EXISTS ratings
                    (order_id INTEGER,
                    rating INTEGER,
                    comment TEXT)''')

        conn.commit()
    finally:
        conn.close()


def add_user(user_id, username, name, student_id, block, dorm_number, phone):
    conn = get_db_connection()
    try:
        # Check if user exists to preserve balance/tokens/role if we are just updating info
        cur = execute_query(conn, 
            "SELECT balance, tokens, is_deliverer FROM users WHERE user_id = ?", (user_id,))
        existing = cur.fetchone()

        if existing:
            balance, tokens, is_deliverer = existing
            execute_query(conn, """UPDATE users 
                        SET username=?, name=?, student_id=?, block=?, dorm_number=?, phone=? 
                        WHERE user_id=?""",
                    (username, name, student_id, block, dorm_number, phone, user_id))
        else:
            execute_query(conn, "INSERT INTO users (user_id, username, name, student_id, block, dorm_number, phone) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, username, name, student_id, block, dorm_number, phone))

        conn.commit()
    finally:
        conn.close()


def register_deliverer(user_id):
    conn = get_db_connection()
    try:
        execute_query(conn, "UPDATE users SET is_deliverer = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def create_order(customer_id, restaurant, items, total_price, verification_code, lat=None, lon=None):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        query = "INSERT INTO orders (customer_id, restaurant, items, total_price, verification_code, delivery_lat, delivery_lon) VALUES (?, ?, ?, ?, ?, ?, ?)"
        params = (customer_id, restaurant, items, total_price, verification_code, lat, lon)
        
        if DATABASE_URL:
            # Postgres: use %s and RETURNING to get ID
            query = query.replace('?', '%s') + " RETURNING order_id"
            cur.execute(query, params)
            order_id = cur.fetchone()[0]
        else:
            # SQLite
            cur.execute(query, params)
            order_id = cur.lastrowid
            
        conn.commit()
        return order_id
    finally:
        conn.close()


def get_pending_orders():
    conn = get_db_connection()
    try:
        cur = execute_query(conn, "SELECT * FROM orders WHERE status = 'pending'")
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
        cur = execute_query(conn, "SELECT * FROM orders WHERE order_id = ?", (order_id,))
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
        cur = execute_query(conn, 
            "SELECT * FROM orders WHERE deliverer_id = ? AND status = 'accepted'", (deliverer_id,))
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
    try:
        # Get recent active orders
        cur = execute_query(conn, "SELECT order_id FROM orders WHERE customer_id = ? AND status IN ('pending', 'accepted', 'assigned')", (user_id,))
        rows = cur.fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()

