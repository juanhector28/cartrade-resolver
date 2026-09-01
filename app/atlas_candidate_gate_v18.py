from __future__ import annotations

import re
from collections import Counter
from typing import Any
from urllib.parse import urlparse


ENGINE = "atlas-candidate-gate-v18"

_ASSET_EXT = (
    ".css", ".js", ".mjs", ".map", ".png", ".jpg", ".jpeg", ".gif", ".svg",
    ".webp", ".ico", ".pdf", ".xml", ".json", ".woff", ".woff2", ".ttf", ".eot", ".zip",
)
_HARD_NOISE = (
    "/cdn-cgi/", "email-protection", "/wp-content/", "/wp-includes/", "/assets/",
    "/static/", "/fonts/", "/font/", "/scripts/", "/script/", "/styles/", "/style/",
    "/css/", "/js/",
)
_MARKETING = (
    "compramos-tu-auto", "compramos-tu-carro", "vende-tu-auto", "vende-tu-carro",
    "encontra-tu-auto", "encuentra-tu-auto", "sell-your-car", "financiamiento", "financing",
    "credito", "credit", "prestamo", "loan", "beneficios", "benefits", "promociones",
    "promotions", "campana", "campaign", "discover-kia", "descubre-kia", "test-drive",
    "cotiza", "cotizar", "quote", "contacto", "contact", "nosotros", "about-us",
    "servicios", "services", "postventa", "post-venta", "garantia", "warranty",
)
_RENTAL = (
    "alquiler-de-autos", "alquiler-de-carros", "alquiler-de-vehiculos", "rent-a-car",
    "rental-car", "car-rental", "renta-de-autos", "renta-de-carros", "reservar-auto",
)
_DETAIL_SEGMENTS = {"vehiculo", "vehicle", "car", "auto", "listing", "anuncio", "detalle", "detail", "unidad", "unit"}
_INVENTORY_SEGMENTS = {"vehiculos", "vehicles", "cars", "autos", "carros", "usados", "seminuevos", "inventario", "inventory", "stock"}
_YEAR = re.compile(r"(?<!\d)(?:m|modelo)?(19[89]\d|20[0-3]\d)(?!\d)", re.I)
_ID = re.compile(r"(?:^|[-_/=])(\d{4,})(?:$|[-_/?&.])")


def candidate_decision(url: str, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = str(url or "").strip()
    low = raw.lower()
    parsed = urlparse(raw)
    path = parsed.path.lower().rstrip("/")
    segments = [x for x in path.split("/") if x]
    leaf = segments[-1] if segments else ""

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {"accept": False, "reason": "invalid_url", "score": -100}
    if not path:
        return {"accept": False, "reason": "root_navigation", "score": -80}
    if path.endswith(_ASSET_EXT) or any(token in low for token in _HARD_NOISE):
        return {"accept": False, "reason": "asset_or_noise", "score": -100}
    if any(token in low for token in _RENTAL):
        return {"accept": False, "reason": "rental_route", "score": -95}
    if any(token in low for token in _MARKETING):
        return {"accept": False, "reason": "marketing_route", "score": -90}

    year = bool(_YEAR.search(path))
    ident = bool(_ID.search(low))
    parent_segments = set(segments[:-1])
    explicit_detail = bool(parent_segments.intersection(_DETAIL_SEGMENTS))
    inventory_parent = bool(parent_segments.intersection(_INVENTORY_SEGMENTS))
    descriptive_leaf = len(leaf) >= 9 and (leaf.count("-") >= 2 or leaf.count("_") >= 2)

    score = 0
    if year:
        score += 50
    if ident:
        score += 45
    if explicit_detail:
        score += 28
    if inventory_parent:
        score += 10
    if descriptive_leaf:
        score += 12

    selector = str((manifest or {}).get("listing_url_selector") or "").strip()
    if selector and selector not in {"a[href]", "a"}:
        score += 5

    # Generic model pages such as /forte-sedan.html are intentionally rejected.
    # Detail-ish routes without a year/id are accepted only when the route itself
    # explicitly says detail/listing/unit and the leaf has listing-like structure.
    accept = bool(year or ident or (explicit_detail and descriptive_leaf))
    reason = "vehicle_detail_evidence" if accept else "insufficient_detail_evidence"
    return {
        "accept": accept,
        "reason": reason,
        "score": score,
        "year": year,
        "id": ident,
        "explicit_detail": explicit_detail,
        "descriptive_leaf": descriptive_leaf,
    }


def filter_candidate_urls(urls: list[str], manifest: dict[str, Any] | None = None, limit: int | None = None) -> tuple[list[str], dict[str, Any]]:
    accepted: list[tuple[int, str]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    reasons: Counter[str] = Counter()

    for url in urls or []:
        raw = str(url or "").strip()
        if not raw or raw in seen:
            continue
        seen.add(raw)
        decision = candidate_decision(raw, manifest)
        if decision["accept"]:
            accepted.append((int(decision.get("score") or 0), raw))
        else:
            reason = str(decision.get("reason") or "rejected")
            reasons[reason] += 1
            if len(rejected) < 12:
                rejected.append({"url": raw, "reason": reason})

    accepted.sort(key=lambda row: (-row[0], len(row[1]), row[1]))
    cap = max(1, int(limit)) if limit is not None else len(accepted)
    kept = [url for _, url in accepted[:cap]]
    before = len(seen)
    return kept, {
        "engine": ENGINE,
        "candidate_urls_before_filter": before,
        "candidate_urls_after_filter": len(kept),
        "candidate_urls_rejected": before - len(kept),
        "rejection_reasons": dict(sorted(reasons.items())),
        "rejected_sample": rejected,
        "accepted_sample": kept[:8],
    }
