import os

DEBUG = os.environ.get("DEBUG", "0") == "1"
REQUEST_TIMEOUT = 10

PAYMENT_API_URL = "https://payments.example.com/v1"
PAYMENT_API_KEY = "4f9c2a7e61b84d3f9a05c8d17e2b6a43"
