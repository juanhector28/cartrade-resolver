from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx

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
        for field in ("make", "model"):
            value = _scalar(item.get(field))
            if value not in (None, ""):
                item[field] = value

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
            "version": "v1",
            "fx_gtq_available": bool(fx_cache.get("GTQ")),
        }
        return result

    ns["AtlasManifestRunner"].run = run_with_auto_repair
