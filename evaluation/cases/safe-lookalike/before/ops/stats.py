import sqlite3

ALLOWED_TABLES = {"orders": "orders", "users": "users"}


def count_rows(conn: sqlite3.Connection, owner: int) -> int:
    cur = conn.execute("SELECT COUNT(*) FROM orders WHERE owner = ?", (owner,))
    return cur.fetchone()[0]
