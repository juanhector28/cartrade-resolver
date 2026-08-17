from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


_BAD_IMAGE_HINTS = (
    "logo", "icon", "favicon", "avatar", "placeholder", "sprite", "banner",
    "brand", "dealer-logo", "dealership-logo", "loader", "spinner", "badge",
)
_GOOD_IMAGE_HINTS = (
    "/vehicle", "/vehicles", "vehicle_", "/vehiculo", "/vehiculos", "/car/",
    "/cars/", "/auto/", "/autos/", "/photo", "/photos", "/images/vehicles",
    "/media/vehicles", "/uploads/photos", "/inventory/",
)
_IMAGE_EXT_RE = re.compile(r"\.(?:jpe?g|png|webp)(?:\?|$)", re.I)
_ABS_IMAGE_RE = re.compile(
    r"https?:\\?/\\?/[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%\\-]+?(?:jpe?g|png|webp)(?:\?[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%\\-]*)?",
    re.I,
)


def _clean_candidate(page_url: str, raw: str | None) -> str | None:
    if not raw:
        return None
    value = str(raw).strip().strip("\"'")
    if not value or value.startswith(("data:", "blob:")):
        return None
    value = value.replace("\\/", "/").replace("&amp;", "&")
    try:
        value = urljoin(page_url, value)
    except Exception:
        return None
    if not value.startswith(("http://", "https://")):
        return None
    low = value.lower()
    if any(h in low for h in _BAD_IMAGE_HINTS):
        return None
    if not _IMAGE_EXT_RE.search(low):
        return None
    return value


def _score(url: str, source: str, width: int | None = None, height: int | None = None) -> int:
    low = url.lower()
    score = 0
    if any(h in low for h in _GOOD_IMAGE_HINTS):
        score += 8
    if source in {"og:image", "twitter:image", "image_src"}:
        score += 5
    if source == "json_or_script":
        score += 3
    if source == "img":
        score += 2
    if width and height and width >= 300 and height >= 200:
        score += 3
    path = urlparse(url).path.lower()
    if re.search(r"(?:vehicle|vehiculo|car|auto)[_-]?\d", path):
        score += 4
    if any(h in low for h in _BAD_IMAGE_HINTS):
        score -= 20
    return score


def _collect(page_url: str, html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    candidates: dict[str, int] = {}

    def add(raw: str | None, source: str, width: int | None = None, height: int | None = None):
        url = _clean_candidate(page_url, raw)
        if not url:
            return
        score = _score(url, source, width, height)
        if score < 4:
            return
        candidates[url] = max(score, candidates.get(url, -999))

    for selector, attr, source in (
        ('meta[property="og:image"]', "content", "og:image"),
        ('meta[property="og:image:secure_url"]', "content", "og:image"),
        ('meta[name="twitter:image"]', "content", "twitter:image"),
        ('link[rel="image_src"]', "href", "image_src"),
    ):
        for node in soup.select(selector):
            add(node.get(attr), source)

    for img in soup.select("img"):
        width = None
        height = None
        try:
            width = int(re.sub(r"\D", "", str(img.get("width") or "")) or 0) or None
            height = int(re.sub(r"\D", "", str(img.get("height") or "")) or 0) or None
        except Exception:
            pass
        for attr in ("src", "data-src", "data-lazy-src", "data-original", "data-image"):
            add(img.get(attr), "img", width, height)
        for attr in ("srcset", "data-srcset"):
            rawset = img.get(attr)
            if rawset:
                for part in str(rawset).split(","):
                    add(part.strip().split(" ")[0], "img", width, height)

    # Many modern vehicle sites serialize gallery URLs into hydration JSON or
    # inline scripts instead of rendering every image as an <img> immediately.
    for match in _ABS_IMAGE_RE.findall(html or ""):
        add(match, "json_or_script")

    ordered = [u for u, _ in sorted(candidates.items(), key=lambda kv: (-kv[1], kv[0]))]
    return ordered[:12]


def _usable_existing(photos: Any) -> list[str]:
    if isinstance(photos, str):
        photos = [photos]
    out = []
    for raw in photos or []:
        if not isinstance(raw, str):
            continue
        low = raw.lower()
        if raw.startswith("http") and not any(h in low for h in _BAD_IMAGE_HINTS):
            out.append(raw)
    return out


def install(ns: dict[str, Any]) -> None:
    if ns.get("_ATLAS_PHOTO_REPAIR_V1_INSTALLED"):
        return
    ns["_ATLAS_PHOTO_REPAIR_V1_INSTALLED"] = True

    original_extract = ns["extract_listing"]

    def extract_with_photo_recovery(manifest: dict, url: str, html: str) -> dict[str, Any]:
        item = original_extract(manifest, url, html)
        existing = _usable_existing(item.get("photos"))
        recovered = _collect(url, html)

        if not existing and recovered:
            item["photos"] = recovered
            item["_photo_recovered"] = True
        elif existing and len(existing) < 3 and recovered:
            merged = []
            for candidate in existing + recovered:
                if candidate not in merged:
                    merged.append(candidate)
            item["photos"] = merged[:12]
            item["_photo_recovered"] = len(merged) > len(existing)
        elif existing:
            item["photos"] = existing[:12]

        return item

    ns["extract_listing"] = extract_with_photo_recovery
