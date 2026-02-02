import sqlite3
import os
import psycopg2
import time
from urllib.parse import urlparse

DATABASE_URL = os.environ.get("DATABASE_URL")
DB_PATH = os.path.join(os.path.dirname(__file__), 'bedorme.db')

def get_db_connection():
    if DATABASE_URL:
        # PostgreSQL connection
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    else:
        # SQLite connection
        conn = sqlite3.connect(DB_PATH)
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
        execute_query(conn, "UPDATE orders SET status = 'complete', delivered_at = ? WHERE order_id = ?", (time.time(), order_id,))
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
                        verification_code TEXT,
                        mid_delivery_proof TEXT,
                        proof_timestamp REAL,
                        delivery_proof TEXT,
                        delivery_lat REAL,
                        delivery_lon REAL,
                        pickup_lat REAL,
                        pickup_lon REAL,
                        created_at REAL,
                        delivered_at REAL)''')
            
            # Migration for orders table
            order_columns = [
                ("pickup_lat", "REAL"),
                ("pickup_lon", "REAL"),
                ("created_at", "REAL"),
                ("delivered_at", "REAL")
            ]
            for col_name, col_type in order_columns:
                try:
                    execute_query(conn, f"ALTER TABLE orders ADD COLUMN {col_name} {col_type}")
                except sqlite3.OperationalError:
                    pass

        execute_query(conn, '''CREATE TABLE IF NOT EXISTS ratings
                    (order_id INTEGER,
                    rating INTEGER,
                    comment TEXT)''')

        conn.commit()
    finally:
        conn.close()


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


def create_order(customer_id, restaurant, items, total_price, verification_code, lat=None, lon=None, pickup_lat=None, pickup_lon=None):
    conn = get_db_connection()
    created_at = time.time()
    try:
        cur = conn.cursor()
        query = "INSERT INTO orders (customer_id, restaurant, items, total_price, verification_code, delivery_lat, delivery_lon, pickup_lat, pickup_lon, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        params = (customer_id, restaurant, items, total_price, verification_code, lat, lon, pickup_lat, pickup_lon, created_at)
        
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
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user_row = cur.fetchone()
        
        if not user_row:
            return None
            
        cur.execute("SELECT * FROM user_history WHERE user_id = ? ORDER BY change_timestamp DESC", (user_id,))
        history = cur.fetchall()
        
        cur.execute("SELECT * FROM orders WHERE customer_id = ? OR deliverer_id = ? ORDER BY order_id DESC", (user_id, user_id))
        orders = cur.fetchall()
        
        return {
            'info': user_row,
            'history': history,
            'orders': orders
        }
    finally:
        conn.close()

