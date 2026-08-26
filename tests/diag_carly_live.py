"""Small live diagnostic used by production smoke when Carly returns HTTP 5xx."""
from __future__ import annotations
import json
import os
import urllib.error
import urllib.request

BASE = os.environ.get("CARLY_BASE_URL", "https://cartrade-resolver.onrender.com").rstrip("/")


def request(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "CarTrade-Diag/1.0"},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            body = response.read().decode("utf-8", "replace")
            print(json.dumps({"path": path, "status": response.status, "body": body[:4000]}, ensure_ascii=False))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        print(json.dumps({"path": path, "status": exc.code, "body": body[:4000]}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"path": path, "error": repr(exc)}, ensure_ascii=False))


if __name__ == "__main__":
    request("/health")
    request("/carly/chat", {
        "messages": [{"role": "user", "content": "Busco un carro para ir a la universidad, máximo $12,000."}],
        "country": "sv",
        "top_n": 3,
    })
