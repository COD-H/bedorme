import sqlite3

DB_PATH = 'bedorme.db'


def display_all_tables(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    tables = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table';").fetchall()
    for table in tables:
        print(f"\nTable: {table[0]}")
        rows = cursor.execute(f"SELECT * FROM {table[0]}").fetchall()
        for row in rows:
            print(row)
    conn.close()


if __name__ == '__main__':
    display_all_tables(DB_PATH)
