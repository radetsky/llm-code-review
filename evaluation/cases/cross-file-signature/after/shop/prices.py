RATES = {"EUR": 1.0, "USD": 1.08, "GBP": 0.86}

DECIMAL_MARKS = {"de": ",", "fr": ",", "en": "."}


def convert(value: float, currency: str) -> float:
    return value * RATES[currency]


def parse_price(text: str, currency: str, locale: str) -> float:
    """Parse a price in the format of the locale and return it in the given currency."""
    mark = DECIMAL_MARKS[locale]
    value = float(text.replace(mark, "."))
    return convert(value, currency)
