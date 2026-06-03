import requests

URL = "https://cartrade-resolver.onrender.com/inventory-run/crautos"
payload = {
    "limit": 500,
    "delay": 1
}

r = requests.post(URL, json=payload)

print(r.status_code)
print(r.text)
