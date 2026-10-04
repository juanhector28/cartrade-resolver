"""Read the requested Enlaces vehicle from its public Next.js data, without JS."""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def vehicle_evidence(url: str, html: str) -> dict[str, Any]:
    parsed = urlparse(url)
    match = re.fullmatch(r"/menu/cars/(\d+)/?", parsed.path)
    if parsed.hostname not in {"enlacesautomotrices.com", "www.enlacesautomotrices.com"} or not match:
        return {}
    vehicle_id = int(match.group(1))
    soup = BeautifulSoup(html, "lxml")
    stream = []
    for script in soup.find_all("script"):
        text = script.string or script.get_text()
        if not text.startswith("self.__next_f.push("):
            continue
        try:
            payload = json.loads(text[len("self.__next_f.push("):].rstrip("; ").removesuffix(")"))
            if payload[0] == 1 and isinstance(payload[1], str):
                stream.append(payload[1])
        except (ValueError, IndexError, TypeError):
            continue
    objects = []
    for line in "".join(stream).splitlines():
        if not re.match(r"^[0-9a-f]+:[\[{]", line):
            continue
        try:
            objects.extend(_walk(json.loads(line.split(":", 1)[1])))
        except ValueError:
            continue
    car = next((node["car"] for node in objects
                if isinstance(node.get("car"), dict)
                and node["car"].get("id") == vehicle_id
                and node["car"].get("brand_name")
                and node["car"].get("year")), None)
    if not car:
        return {}
    name = str(car.get("name") or "").strip()
    try:
        year = int(car["year"])
        price = float(car.get("discount_price") or car["price"])
    except (ValueError, TypeError, KeyError):
        return {}
    model = re.sub(r"\s*\b" + str(year) + r"\b\s*$", "", name).strip()
    transmission = str(car.get("transmission_display") or "").strip()
    normalized = transmission.casefold()
    if any(x in normalized for x in ("auto", "tiptronic", "triptronic", "cvt", "dct")):
        transmission = "Automática"
    elif "manual" in normalized or "mec" in normalized:
        transmission = "Manual"
    else:
        transmission = None
    km = None
    try:
        distance = float(car.get("odometer"))
        unit = str(car.get("odometer_unit") or "").upper()
        if unit in {"MI", "MILES", "MILLAS"}:
            km = round(distance * 1.609344)
        elif unit in {"KM", "KMS"}:
            km = round(distance)
    except (ValueError, TypeError):
        pass
    thumbnail = car.get("thumbnail") or {}
    primary = thumbnail.get("image") if isinstance(thumbnail, dict) else None
    photos = [primary] if primary else []
    for node in objects:
        images = node.get("images")
        if isinstance(images, list) and any(isinstance(x, dict) and x.get("image") == primary for x in images):
            photos = list(dict.fromkeys(x["image"] for x in images if isinstance(x, dict) and str(x.get("image", "")).startswith("https://")))
            break
    if price <= 0 or not model:
        return {}
    return {
        "url": url, "make": str(car["brand_name"]).title(), "model": model,
        "year": year, "title": f"{year} {str(car['brand_name']).title()} {model}",
        "price_usd": price, "currency": "GTQ", "km": km,
        "transmission": transmission, "fuel_type": car.get("fuel_type_display"),
        "description": car.get("description"), "photos": photos,
        "source_vehicle_status": car.get("status_display"),
        "source_evidence": "enlaces_next_vehicle_v1",
    }
