from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

NAV_VALUES = {
    "inicio", "home", "buscar", "search", "menu", "menú", "vehiculo", "vehículo",
    "vehiculos", "vehículos", "auto", "autos", "carro", "carros", "principal",
}
NON_CAR_HINTS = (
    "/moto-", "/motos/", " motocic", "moto ", "moto-", " atv", "atv ",
    "cuatri", "scooter", "quadric", "motocross", "motocicleta",
)
GENERIC_TITLES = {
    "movilauto", "carros.com", "carros", "encuentra24", "encuentra24.com",
    "vehículos", "vehiculos", "autos", "carros guatemala",
}

_URL_MAKES = {
    "acura", "audi", "bmw", "buick", "byd", "cadillac", "changan", "chery",
    "chevrolet", "chrysler", "citroen", "dodge", "fiat", "ford", "geely",
    "gmc", "honda", "hyundai", "isuzu", "jac", "jeep", "kia", "land-rover",
    "lexus", "mazda", "mercedes", "mercedes-benz", "mg", "mini", "mitsubishi",
    "nissan", "peugeot", "porsche", "ram", "renault", "subaru", "suzuki",
    "toyota", "volkswagen", "volvo",
}


def _url_vehicle_identity_fallbacks(url: str) -> dict[str, Any]:
    """Conservative vehicle identity recovery from detail-page slugs.

    Used only as a fallback when extracted make/model/year are missing or
    polluted. It requires both a known make token and an explicit 4-digit model
    year marker in the final path segment, so generic navigation URLs cannot
    manufacture vehicle identity.
    """
    try:
        slug = unquote(urlparse(str(url or "")).path.rstrip("/").split("/")[-1])
    except Exception:
        return {}
    slug = re.sub(r"\.(?:html?|php)$", "", slug, flags=re.I)
    slug = re.sub(r"[_-]+", "-", slug).strip("-").lower()
    year_match = re.search(r"(?:^|-)m?(19\d{2}|20\d{2})(?:-|$)", slug, re.I)
    if not year_match:
        return {}

    year = int(year_match.group(1))
    head = slug[:year_match.start()].strip("-")
    if not head:
        return {}

    make = None
    remainder = None
    for candidate in sorted(_URL_MAKES, key=len, reverse=True):
        if head == candidate:
            make, remainder = candidate, ""
            break
        prefix = candidate + "-"
        if head.startswith(prefix):
            make, remainder = candidate, head[len(prefix):]
            break
    if not make or not remainder:
        return {}

    # Normalize common make spellings for display without trying to infer trim.
    display_make = {
        "bmw": "BMW",
        "byd": "BYD",
        "gmc": "GMC",
        "jac": "JAC",
        "mg": "MG",
    }.get(make, " ".join(part.capitalize() for part in make.split("-")))

    model = re.sub(r"-+", " ", remainder).strip()
    if not model:
        return {}
    return {
        "make": display_make,
        "model": model.upper(),
        "year": year,
    }


_VISIBLE_LABELS = {
    "make": {"marca", "brand"},
    "model": {"linea", "línea", "model", "modelo"},
    "year": {"año", "ano", "year"},
}


def _norm_label(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    return text[:-1].strip() if text.endswith(":") else text


def _polluted_vehicle_scalar(value: Any) -> bool:
    text = str(_scalar(value) or "").strip()
    if not text:
        return False
    low = text.lower()
    return (
        len(text) > 80
        or len(text.split()) >= 8
        or "@" in text
        or any(token in low for token in (" inicio ", " inventario ", " contacto ", " calculadora "))
    )


def _visible_photo_fallbacks(html: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(html or "", "lxml")
    candidates: list[str] = []

    def add(raw: Any):
        if not raw:
            return
        value = str(raw).strip()
        if not value:
            return
        value = urljoin(page_url, value)
        if not value.startswith(("http://", "https://")):
            return
        low = value.lower()
        if any(token in low for token in ("logo", "favicon", "icon-", "/icons/", "avatar", "wordmark")):
            return
        if value not in candidates:
            candidates.append(value)

    for selector, attr in (
        ('meta[property="og:image"]', "content"),
        ('meta[name="twitter:image"]', "content"),
        ('link[rel="image_src"]', "href"),
    ):
        node = soup.select_one(selector)
        if node is not None:
            add(node.get(attr))

    if not candidates:
        for node in soup.select("img[src], img[data-src], img[data-lazy-src]"):
            add(node.get("src") or node.get("data-src") or node.get("data-lazy-src"))
            if len(candidates) >= 12:
                break

    return candidates[:12]


def _visible_core_fallbacks(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html or "", "lxml")
    for tag in soup.select("script,style,noscript,template"):
        tag.decompose()
    tokens = [re.sub(r"\s+", " ", x).strip() for x in soup.stripped_strings]
    out: dict[str, Any] = {}

    for idx, token in enumerate(tokens):
        label = _norm_label(token)
        field = next((name for name, labels in _VISIBLE_LABELS.items() if label in labels), None)
        if not field:
            continue
        for candidate in tokens[idx + 1: idx + 4]:
            value = candidate.strip()
            if not value or _norm_label(value) in {x for labels in _VISIBLE_LABELS.values() for x in labels}:
                continue
            if field == "year":
                match = re.fullmatch(r"(19\d{2}|20\d{2})", value)
                if match:
                    out["year"] = int(match.group(1))
                    break
                continue
            if len(value) <= 60 and len(value.split()) <= 6 and "@" not in value:
                out[field] = value
                break

    visible = " ".join(tokens[:1200])
    prices = []
    for match in re.finditer(r"(?<![A-Z0-9])(?:(GTQ|Q|USD|US\$|\$)\s*)([0-9][0-9.,\s]{2,})", visible, re.I):
        cur = (match.group(1) or "").upper()
        raw = match.group(2).strip()
        try:
            value = float(raw.replace(" ", "").replace(",", ""))
        except ValueError:
            continue
        if 500 <= value <= 5_000_000:
            prices.append((match.start(), cur, value))
    if prices:
        _, cur, value = prices[0]
        out["price_usd"] = value
        out["currency"] = "GTQ" if cur in {"Q", "GTQ"} else "USD"

    return out


def _scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("name", "value", "title", "description"):
            if value.get(key) not in (None, "", []):
                return _scalar(value.get(key))
        return None
    if isinstance(value, list):
        for candidate in value:
            scalar = _scalar(candidate)
            if scalar not in (None, ""):
                return scalar
        return None
    if isinstance(value, str):
        return value.strip() or None
    return value


def _is_non_car(item: dict[str, Any]) -> bool:
    evidence = " ".join(
        str(_scalar(item.get(k)) or "")
        for k in ("url", "title", "make", "model")
    ).lower().replace("autos-motos", "")
    return any(h in evidence for h in NON_CAR_HINTS)


def install(ns: dict[str, Any]) -> None:
    """Install generic Atlas semantic repairs into atlas_manifest_runner.

    This is intentionally source-agnostic. Site-specific selector repair still
    belongs in Atlas manifests; this layer fixes recurrent shape/normalization
    defects that should not require one-off scraper code.
    """
    if ns.get("_ATLAS_AUTO_REPAIR_V1_INSTALLED"):
        return
    ns["_ATLAS_AUTO_REPAIR_V1_INSTALLED"] = True

    original_extract = ns["extract_listing"]
    original_money_usd = ns["_money_usd"]
    original_run = ns["AtlasManifestRunner"].run
    number = ns["_number"]

    fx_cache: dict[str, float] = {}
    fx_cache_at: dict[str, float] = {}

    def repaired_extract(manifest: dict, url: str, html: str) -> dict[str, Any]:
        item = original_extract(manifest, url, html)

        original_title = item.get("title")
        visible = _visible_core_fallbacks(html)
        url_identity = _url_vehicle_identity_fallbacks(url)

        for field in ("make", "model"):
            value = _scalar(item.get(field))
            if value not in (None, "") and not _polluted_vehicle_scalar(value):
                item[field] = value
            elif visible.get(field) not in (None, ""):
                item[field] = visible[field]
            elif url_identity.get(field) not in (None, ""):
                item[field] = url_identity[field]

        try:
            current_year = int(item.get("year"))
        except Exception:
            current_year = 0
        if not 1950 <= current_year <= datetime.now(timezone.utc).year + 2:
            if visible.get("year"):
                item["year"] = int(visible["year"])
            elif url_identity.get("year"):
                item["year"] = int(url_identity["year"])

        if item.get("price_usd") in (None, "", []) and visible.get("price_usd") is not None:
            item["price_usd"] = visible["price_usd"]
            if visible.get("currency"):
                item["currency"] = visible["currency"]

        photos = item.get("photos") or []
        if isinstance(photos, str):
            photos = [photos]
        photos = [p for p in photos if isinstance(p, str) and p.startswith("http")]
        if not photos:
            images = item.get("images")
            if isinstance(images, str) and images.startswith("http"):
                photos = [images]
            elif isinstance(images, list):
                photos = [p for p in images if isinstance(p, str) and p.startswith("http")]
        if not photos:
            photos = _visible_photo_fallbacks(html, url)
        if photos:
            item["photos"] = photos[:12]
            item["images"] = photos[0]

        title = _scalar(original_title)
        if isinstance(original_title, (dict, list)) or not title or str(title).lower() in GENERIC_TITLES:
            built = " ".join(
                str(v).strip()
                for v in (item.get("year"), item.get("make"), item.get("model"))
                if v not in (None, "", [])
            ).strip()
            if built:
                item["title"] = built
            elif title:
                item["title"] = title
        elif title:
            item["title"] = title

        for field in ("fuel_type", "transmission"):
            value = _scalar(item.get(field))
            if isinstance(value, str) and value.lower() in NAV_VALUES:
                item.pop(field, None)
            elif value not in (None, ""):
                item[field] = value

        semantic_reject = _is_non_car(item)
        if semantic_reject:
            item["_semantic_reject_reason"] = "non_car_listing"

        required = item.get("_required_fields") or manifest.get("required_fields") or []
        item["_required_ok"] = bool(
            not semantic_reject
            and all(item.get(k) not in (None, "", []) for k in required)
        )
        item["_auto_repaired"] = True
        return item

    ns["extract_listing"] = repaired_extract

    def money_usd_with_cache(raw_price: Any, currency: str | None) -> float | None:
        converted = original_money_usd(raw_price, currency)
        if converted is not None:
            return converted
        n = number(raw_price)
        cur = str(currency or "").upper().strip()
        rate = fx_cache.get(cur)
        if n is not None and rate and rate > 0:
            return round(n / rate, 2)
        return None

    ns["_money_usd"] = money_usd_with_cache

    async def refresh_fx(country: str | None) -> None:
        country = str(country or "").upper()
        if country != "GT":
            return

        try:
            override = float(os.getenv("ATLAS_FX_GTQ_PER_USD", "") or 0)
        except Exception:
            override = 0
        if override > 0:
            fx_cache["GTQ"] = override
            fx_cache_at["GTQ"] = time.time()
            return

        last = float(fx_cache_at.get("GTQ") or 0)
        if fx_cache.get("GTQ") and time.time() - last < 43200:
            return

        soap = '''<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
 xmlns:xsd="http://www.w3.org/2001/XMLSchema"
 xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <TipoCambioDia xmlns="http://www.banguat.gob.gt/variables/ws/" />
  </soap:Body>
</soap:Envelope>'''
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": '"http://www.banguat.gob.gt/variables/ws/TipoCambioDia"',
        }
        try:
            async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
                response = await client.post(
                    "https://banguat.gob.gt/variables/ws/TipoCambio.asmx",
                    content=soap.encode("utf-8"),
                    headers=headers,
                )
            response.raise_for_status()
            refs = re.findall(
                r"<referencia>\s*([0-9]+(?:\.[0-9]+)?)\s*</referencia>",
                response.text,
                re.I,
            )
            if refs:
                rate = float(refs[-1])
                if 5.0 < rate < 15.0:
                    fx_cache["GTQ"] = rate
                    fx_cache_at["GTQ"] = time.time()
        except Exception:
            # FX failure is not repaired with a guessed rate. The semantic gate
            # remains closed until official data or an explicit override exists.
            return

    def activation_quality_v2(sample: list[dict[str, Any]] | None) -> dict[str, Any]:
        sample = list(sample or [])[:5]
        n = len(sample)
        if n < 3:
            return {
                "eligible": False,
                "sample_size": n,
                "score": 0.0,
                "issues": ["semantic_sample_too_small"],
            }

        nested_core = 0
        navigation_pollution = 0
        non_car = 0
        normalizable_price = 0
        plausible_year = 0
        usable_photo = 0
        core_scalar = 0

        for item in sample:
            nested_here = False
            for field in ("title", "make", "model"):
                if isinstance(item.get(field), (dict, list)):
                    nested_core += 1
                    nested_here = True
            if not nested_here and all(_scalar(item.get(f)) for f in ("title", "make", "model")):
                core_scalar += 1

            for field in ("fuel_type", "transmission"):
                value = str(_scalar(item.get(field)) or "").lower()
                if value in NAV_VALUES:
                    navigation_pollution += 1

            if _is_non_car(item):
                non_car += 1

            if money_usd_with_cache(item.get("price_usd"), item.get("currency")) is not None:
                normalizable_price += 1

            try:
                year = int(item.get("year"))
                if 1950 <= year <= datetime.now(timezone.utc).year + 2:
                    plausible_year += 1
            except Exception:
                pass

            photos = item.get("photos") or []
            if isinstance(photos, str):
                photos = [photos]
            if any(
                isinstance(p, str) and p.startswith("http") and "logo" not in p.lower()
                for p in photos
            ):
                usable_photo += 1

        issues: list[str] = []
        if nested_core:
            issues.append("nested_core_fields")
        if core_scalar / n < 0.80:
            issues.append("core_field_quality_low")
        if navigation_pollution:
            issues.append("navigation_text_in_vehicle_fields")
        if non_car / n > 0.20:
            issues.append("non_car_inventory_detected")
        if normalizable_price / n < 0.80:
            issues.append("price_currency_not_normalizable")
        if plausible_year / n < 0.80:
            issues.append("year_quality_low")
        if usable_photo / n < 0.80:
            issues.append("usable_photo_coverage_low")

        checks = 7
        return {
            "eligible": not issues,
            "sample_size": n,
            "score": round(max(0.0, (checks - len(issues)) / checks), 4),
            "issues": issues,
            "nested_core_fields": nested_core,
            "navigation_pollution": navigation_pollution,
            "non_car_ratio": round(non_car / n, 4),
            "normalizable_price_pct": round(normalizable_price / n * 100, 2),
            "plausible_year_pct": round(plausible_year / n * 100, 2),
            "usable_photo_coverage_pct": round(usable_photo / n * 100, 2),
            "core_scalar_pct": round(core_scalar / n * 100, 2),
        }

    # The semantic wrapper resolves this global at runtime, so replacing it
    # upgrades the gate without another wrapper layer.
    ns["_atlas_activation_quality"] = activation_quality_v2

    async def run_with_auto_repair(self, *args, **kwargs):
        country = kwargs.get("country")
        if country is None and len(args) >= 2:
            country = args[1]
        await refresh_fx(country)
        result = await original_run(self, *args, **kwargs)
        result["auto_repair"] = {
            "enabled": True,
            "version": "v2-visible-labels",
            "fx_gtq_available": bool(fx_cache.get("GTQ")),
        }
        return result

    ns["AtlasManifestRunner"].run = run_with_auto_repair
