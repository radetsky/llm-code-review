def summarize(rows):
    t = 0
    c = 0
    for r in rows:
        if r["status"] == "paid":
            t = t + r["amount"]
            c = c + 1
    if c == 0:
        return {"total": 0, "average": 0}
    return {"total": t, "average": t / c}
