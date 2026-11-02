RATES = {"EUR": 1.0, "USD": 1.08, "GBP": 0.86}


def convert(value: float, currency: str) -> float:
    return value * RATES[currency]


def parse_price(text: str, currency: str) -> float:
    """Parse a price such as '12,50' and return it in the given currency."""
    value = float(text.replace(",", "."))
    return convert(value, currency)
