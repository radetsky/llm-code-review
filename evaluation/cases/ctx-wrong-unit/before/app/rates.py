import json
import urllib.parse
import urllib.request

API_URL = "https://rates.example.com/v1/latest"


def fetch_rate(currency: str) -> float:
    query = urllib.parse.urlencode({"symbol": currency})
    with urllib.request.urlopen(f"{API_URL}?{query}", timeout=5) as response:
        return json.load(response)["rate"]


def get_rate(currency: str) -> float:
    return fetch_rate(currency)
