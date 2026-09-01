from __future__ import annotations

from typing import Any

from .atlas_listing_validity import listing_validity


_ALLOWED_FUEL = {
    "gasolina": "Gasolina",
    "diesel": "Diesel",
    "diésel": "Diesel",
    "hibrido": "Híbrido",
    "híbrido": "Híbrido",
    "hybrid": "Híbrido",
    "electrico": "Eléctrico",
    "eléctrico": "Eléctrico",
    "electric": "Eléctrico",
    "glp": "GLP",
    "lpg": "GLP",
}


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("name", "value", "title"):
            if value.get(key) not in (None, "", []):
                return _clean_text(value.get(key))
        return ""
    if isinstance(value, list):
        for item in value:
            text = _clean_text(item)
            if text:
                return text
        return ""
    return str(value).strip()


def _normalize_fuel(value: Any) -> str | None:
    text = _clean_text(value).lower()
    if not text:
        return None
    for token, normalized in _ALLOWED_FUEL.items():
        if token in text:
            return normalized
    return None


def _normalize_transmission(value: Any) -> str | None:
    text = _clean_text(value).lower()
    if not text:
        return None
    if "manual" in text or "mec" in text:
        return "Manual"
    if "cvt" in text:
        return "CVT"
    if "secuencial" in text:
        return "Secuencial"
    if "tiptronic" in text:
        return "Tiptronic"
    if "dct" in text or "dual clutch" in text or "doble embrague" in text:
        return "DCT"
    if "autom" in text:
        return "Automática"
    if text in {"otra", "otro", "other"}:
        return "Otra"
    return None


def install(ns: dict[str, Any]) -> None:
    if ns.get("_ATLAS_CONTRACT_V16_INSTALLED"):
        return
    ns["_ATLAS_CONTRACT_V16_INSTALLED"] = True

    original_extract = ns["extract_listing"]
    original_quality = ns.get("_atlas_activation_quality")
    original_run = ns["AtlasManifestRunner"].run
    money_usd = ns["_money_usd"]

    def extract_with_field_contract(manifest: dict, url: str, html: str) -> dict[str, Any]:
        item = original_extract(manifest, url, html)

        if item.get("fuel_type") not in (None, "", []):
            normalized = _normalize_fuel(item.get("fuel_type"))
            if normalized:
                item["fuel_type"] = normalized
            else:
                item.pop("fuel_type", None)
                item["_invalid_fuel_removed"] = True

        if item.get("transmission") not in (None, "", []):
            normalized = _normalize_transmission(item.get("transmission"))
            if normalized:
                item["transmission"] = normalized
            else:
                item.pop("transmission", None)
                item["_invalid_transmission_removed"] = True

        return item

    ns["extract_listing"] = extract_with_field_contract

    if callable(original_quality):
        def quality_with_field_contract(sample):
            out = dict(original_quality(sample) or {})
            rows = list(sample or [])[:5]
            invalid_fuel = 0
            invalid_transmission = 0
            validity_rows: list[dict[str, Any]] = []
            for item in rows:
                if item.get("fuel_type") not in (None, "", []):
                    if _normalize_fuel(item.get("fuel_type")) is None:
                        invalid_fuel += 1
                if item.get("transmission") not in (None, "", []):
                    if _normalize_transmission(item.get("transmission")) is None:
                        invalid_transmission += 1

                normalized = dict(item)
                raw_price = normalized.get("price_native", normalized.get("price_usd"))
                raw_currency = normalized.get("currency_native", normalized.get("currency"))
                normalized["price_usd"] = money_usd(raw_price, raw_currency)
                validity_rows.append(normalized)

            validity = listing_validity(validity_rows)
            out["field_contract_v16"] = True
            out["invalid_fuel_values"] = invalid_fuel
            out["invalid_transmission_values"] = invalid_transmission
            out["core_listing_validity"] = {
                key: value for key, value in validity.items() if key != "valid_rows"
            }

            issues = list(out.get("issues") or [])
            if invalid_fuel or invalid_transmission:
                if "invalid_vehicle_field_values" not in issues:
                    issues.append("invalid_vehicle_field_values")
                out["eligible"] = False
            if not validity["passes_threshold"]:
                if "core_listing_coverage_below_80" not in issues:
                    issues.append("core_listing_coverage_below_80")
                out["eligible"] = False
            out["issues"] = issues
            return out

        ns["_atlas_activation_quality"] = quality_with_field_contract

    async def run_with_sample_contract(self, *args, **kwargs):
        result = await original_run(self, *args, **kwargs)
        normalized_sample = []
        for item in list(result.get("sample") or []):
            row = dict(item)
            raw_price = row.get("price_native", row.get("price_usd"))
            raw_currency = row.get("currency_native", row.get("currency"))
            converted = money_usd(raw_price, raw_currency)
            row["price_native"] = raw_price
            row["currency_native"] = raw_currency
            row["price_usd"] = converted
            row["currency"] = "USD" if converted is not None else raw_currency
            normalized_sample.append(row)
        result["sample"] = normalized_sample
        result["sample_price_contract"] = "native_plus_usd_v1"
        validity = listing_validity(normalized_sample)
        result["core_listing_validity"] = {
            key: value for key, value in validity.items() if key != "valid_rows"
        }
        return result

    ns["AtlasManifestRunner"].run = run_with_sample_contract
