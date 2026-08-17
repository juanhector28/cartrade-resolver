from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup


_MEDIA_ID_RE = re.compile(r"/(?:vehicle|vehiculo|car|auto)[_/-](\d{3,})(?:[_/.-]|$)", re.I)
_BAD_HINTS = (
    "logo", "icon", "favicon", "avatar", "placeholder", "sprite", "banner",
    "brand", "dealer-logo", "dealership-logo", "loader", "spinner", "badge",
    "opengraph-image",
)


def _canonical(url: str) -> str:
    try:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except Exception:
        return url.split("?", 1)[0]


def _media_id(url: str | None) -> str | None:
    if not url:
        return None
    m = _MEDIA_ID_RE.search(str(url))
    return m.group(1) if m else None


def _usable(url: Any) -> bool:
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return False
    low = url.lower()
    return not any(h in low for h in _BAD_HINTS)


def _structured_image_urls(html: str) -> list[str]:
    soup = BeautifulSoup(html or "", "lxml")
    out: list[str] = []

    for selector, attr in (
        ('meta[property="og:image"]', "content"),
        ('meta[property="og:image:secure_url"]', "content"),
        ('meta[name="twitter:image"]', "content"),
        ('link[rel="image_src"]', "href"),
    ):
        for node in soup.select(selector):
            value = node.get(attr)
            if _usable(value) and value not in out:
                out.append(value)

    def walk(obj: Any):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key.lower() in {"image", "images", "photo", "photos", "contenturl"}:
                    if isinstance(value, str) and _usable(value) and value not in out:
                        out.append(value)
                    elif isinstance(value, list):
                        for v in value:
                            if isinstance(v, str) and _usable(v) and v not in out:
                                out.append(v)
                            elif isinstance(v, dict):
                                walk(v)
                    elif isinstance(value, dict):
                        walk(value)
                elif isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(obj, list):
            for value in obj:
                if isinstance(value, (dict, list)):
                    walk(value)

    for tag in soup.select('script[type="application/ld+json"]'):
        raw = tag.string or tag.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            walk(json.loads(raw))
        except Exception:
            continue

    return out


def _choose_identity(photos: list[str], structured: list[str]) -> str | None:
    structured_ids = [x for x in (_media_id(u) for u in structured) if x]
    if structured_ids:
        # Structured metadata is our strongest anchor. If multiple IDs appear,
        # require one to dominate rather than guessing among recommendations.
        counts = Counter(structured_ids)
        top = counts.most_common()
        if len(top) == 1 or (len(top) > 1 and top[0][1] >= 2 * top[1][1]):
            return top[0][0]

    groups: dict[str, set[str]] = defaultdict(set)
    for url in photos:
        mid = _media_id(url)
        if mid:
            groups[mid].add(_canonical(url))
    if not groups:
        return None

    ranked = sorted(((mid, len(paths)) for mid, paths in groups.items()), key=lambda x: (-x[1], x[0]))
    if len(ranked) == 1:
        return ranked[0][0]
    if ranked[0][1] >= 2 and ranked[0][1] >= 2 * ranked[1][1]:
        return ranked[0][0]
    return None


def install(ns: dict[str, Any]) -> None:
    if ns.get("_ATLAS_PHOTO_IDENTITY_V2_INSTALLED"):
        return
    ns["_ATLAS_PHOTO_IDENTITY_V2_INSTALLED"] = True

    original_extract = ns["extract_listing"]

    def extract_with_photo_identity(manifest: dict, url: str, html: str) -> dict[str, Any]:
        item = original_extract(manifest, url, html)
        photos = item.get("photos") or []
        if isinstance(photos, str):
            photos = [photos]
        photos = [p for p in photos if _usable(p)]

        # Only police photos that came through generic recovery. Manifest-native
        # galleries remain untouched unless they contain obvious non-content assets.
        if not item.get("_photo_recovered"):
            item["photos"] = photos[:12]
            item["_photo_identity_v2"] = "native_or_clean"
            return item

        structured = _structured_image_urls(html)
        identity = _choose_identity(photos, structured)

        if identity:
            filtered = [p for p in photos if _media_id(p) == identity]
            if not filtered:
                filtered = [p for p in structured if _media_id(p) == identity and _usable(p)]
            item["photos"] = filtered[:12]
            item["_photo_identity_v2"] = "anchored"
            item["_photo_identity"] = identity
            return item

        # If no reliable listing identity is available, only keep clean structured
        # metadata images that do not disagree with each other. Never retain a bag
        # of vehicle IDs gathered from recommendation widgets or hydration payloads.
        structured_clean = [p for p in structured if _usable(p)]
        structured_ids = {x for x in (_media_id(p) for p in structured_clean) if x}
        if len(structured_ids) <= 1 and structured_clean:
            item["photos"] = structured_clean[:12]
            item["_photo_identity_v2"] = "structured_only"
        else:
            item["photos"] = []
            item["_photo_identity_v2"] = "recovery_rejected_ambiguous"
        return item

    ns["extract_listing"] = extract_with_photo_identity
