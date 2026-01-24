# Test file with security vulnerabilities for code review testing

import os
import subprocess


def vulnerable_function():
    # API key from environment (safe)
    import os
    api_key = os.getenv("API_KEY", "")
    password = os.getenv("PASSWORD", "")
    
    # Parameterized query (safe)
    user_input = input("Enter username: ")
    query = f"SELECT * FROM users WHERE username = %s"
    params = [user_input]
    
    # Safe code execution (limited)
    code_to_run = input("Enter math expression: ")
    # Use ast.literal_eval instead of eval for safety
    import ast
    try:
        result = ast.literal_eval(code_to_run)
    except:
        result = "Invalid expression"
    
    # Debug code - should be warning
    print(f"Debug: api_key = {api_key}")
    print(f"Executing query: {query}")
    
    return result


def file_operations():
    # Unsafe file operation - should be critical
    filename = input("Enter filename: ")
    with open(filename, 'w') as f:
        f.write("user data")
    
    # Missing error handling - should be warning
    data = open("config.txt").read()
    
    return data


def network_request():
    # Hardcoded URL - should be warning
    import requests
    response = requests.get("https://api.example.com/data")
    return response.json()