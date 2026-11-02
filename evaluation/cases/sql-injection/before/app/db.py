"""Small data access layer."""

import sqlite3

DB_PATH = "app.db"


def connect():
    return sqlite3.connect(DB_PATH)


def get_user_by_id(user_id: int):
    conn = connect()
    try:
        cur = conn.execute("SELECT id, name, email FROM users WHERE id = ?", (user_id,))
        return cur.fetchone()
    finally:
        conn.close()
