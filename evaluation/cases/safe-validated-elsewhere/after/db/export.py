import csv

from db.names import ensure_identifier


def write_csv(rows, path: str) -> None:
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)


def export_table(conn, table: str, owner_id: int, path: str) -> int:
    name = ensure_identifier(table)
    query = f"SELECT * FROM {name} WHERE owner_id = ?"
    rows = conn.execute(query, (owner_id,)).fetchall()
    write_csv(rows, path)
    return len(rows)
