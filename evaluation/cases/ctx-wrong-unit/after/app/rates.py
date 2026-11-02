import json
import urllib.parse
import urllib.request

from app.cache import Cache

API_URL = "https://rates.example.com/v1/latest"
RATE_CACHE_SECONDS = 300

_cache = Cache()


def fetch_rate(currency: str) -> float:
    query = urllib.parse.urlencode({"symbol": currency})
    with urllib.request.urlopen(f"{API_URL}?{query}", timeout=5) as response:
        return json.load(response)["rate"]


def get_rate(currency: str) -> float:
    cached = _cache.get(currency)
    if cached is not None:
        return cached
    rate = fetch_rate(currency)
    _cache.set(currency, rate, RATE_CACHE_SECONDS)
    return rate
