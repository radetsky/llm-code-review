import subprocess
import sqlite3

import yaml

ALLOWED_TABLES = {"orders": "orders", "users": "users"}


def count_rows(conn: sqlite3.Connection, owner: int, kind: str = "orders") -> int:
    table = ALLOWED_TABLES[kind]
    query = f"SELECT COUNT(*) FROM {table} WHERE owner = ?"
    cur = conn.execute(query, (owner,))
    return cur.fetchone()[0]


def current_commit(ref: str = "HEAD") -> str:
    result = subprocess.run(
        ["git", "rev-parse", ref], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def load_settings(path: str) -> dict:
    with open(path) as handle:
        return yaml.safe_load(handle)
