def _paid_amounts(rows):
    return [row["amount"] for row in rows if row["status"] == "paid"]


def summarize(rows):
    amounts = _paid_amounts(rows)
    if not amounts:
        return {"total": 0, "average": 0}
    total = sum(amounts)
    return {"total": total, "average": total / len(amounts)}
