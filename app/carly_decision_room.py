"""Decision Room primitives for Carly.

This module is deliberately pure: it turns the existing Carly recommendation
payload into a persistent decision object the frontend can store, render, and
refresh without asking the LLM to reconstruct product state from prose.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def _car_key(car: dict) -> str:
    if car.get("url"):
        return str(car["url"])
    if car.get("id") is not None:
        return f"id:{car['id']}"
    return "|".join(str(car.get(k) or "") for k in ("make", "model", "year", "km", "price_usd"))


def _car_name(car: dict) -> str:
    return " ".join(str(car.get(k)) for k in ("make", "model", "year") if car.get(k)).strip() or "esta unidad"


def _truthy(car: dict, *keys: str) -> bool:
    return any(car.get(k) is True or str(car.get(k) or "").lower() in {"verified", "confirmed", "done", "approved"} for k in keys)


def evidence_for_car(car: dict) -> dict:
    """Separate what CarTrade knows from what still has to be verified."""
    known: list[dict] = []
    pending: list[dict] = []

    def add_known(key: str, label: str, value: Any, source: str = "listing") -> None:
        if value is not None and value != "":
            known.append({"key": key, "label": label, "value": value, "source": source})

    add_known("price", "Precio publicado", car.get("price_usd"), "listing")
    add_known("km", "Kilometraje reportado", car.get("km"), "seller_reported")
    add_known("year", "Año", car.get("year"), "listing")
    add_known("location", "Ubicación", car.get("location"), "listing")
    add_known("transmission", "Transmisión", car.get("transmission"), "listing")
    add_known("body_type", "Tipo", car.get("body_type"), "carly_inferred")

    if _truthy(car, "availability_confirmed", "available_confirmed"):
        known.append({"key": "availability", "label": "Disponibilidad", "value": "Confirmada", "source": "cartrade_verified"})
    else:
        pending.append({"key": "availability", "label": "Confirmar disponibilidad", "owner": "CarTrade"})

    if _truthy(car, "seller_verified", "seller_identity_verified"):
        known.append({"key": "seller", "label": "Vendedor", "value": "Verificado", "source": "cartrade_verified"})
    else:
        pending.append({"key": "seller", "label": "Verificar identidad del vendedor", "owner": "CarTrade"})

    if _truthy(car, "documents_verified", "title_verified", "registry_verified"):
        known.append({"key": "documents", "label": "Documentos", "value": "Verificados", "source": "cartrade_verified"})
    else:
        pending.append({"key": "documents", "label": "Revisar título y documentos", "owner": "CarTrade"})

    if _truthy(car, "inspection_verified", "inspection_complete"):
        known.append({"key": "inspection", "label": "Inspección", "value": "Completada", "source": "cartrade_verified"})
    else:
        pending.append({"key": "inspection", "label": "Inspección de la unidad", "owner": "CarTrade"})

    return {"known": known, "pending": pending}


def execution_for_car(car: dict) -> dict:
    """Turn a recommendation into a transaction state + one concrete next action."""
    if not _truthy(car, "availability_confirmed", "available_confirmed"):
        stage = "discovered"
        action = {"id": "confirm_availability", "label": "Confirmar disponibilidad", "cta": "Confirmar disponibilidad"}
    elif not _truthy(car, "seller_verified", "seller_identity_verified"):
        stage = "availability_confirmed"
        action = {"id": "verify_seller", "label": "Verificar vendedor", "cta": "Verificar vendedor"}
    elif not _truthy(car, "documents_verified", "title_verified", "registry_verified"):
        stage = "seller_verified"
        action = {"id": "verify_documents", "label": "Revisar documentos", "cta": "Revisar documentos"}
    elif not _truthy(car, "inspection_verified", "inspection_complete"):
        stage = "documents_verified"
        action = {"id": "schedule_inspection", "label": "Programar inspección", "cta": "Programar inspección"}
    else:
        stage = "ready_to_close"
        action = {"id": "start_verified_purchase", "label": "Avanzar a cierre", "cta": "Iniciar compra verificada"}
    return {"stage": stage, "next_action": action}


def _decision_seed(country: str | None, profile: dict, recommendations: list[dict]) -> str:
    stable_profile = {k: profile.get(k) for k in (
        "primary_job", "secondary_job", "max_price", "target_price", "max_monthly",
        "target_monthly", "max_km", "min_year", "daily_km", "passengers",
        "require_body", "prefer_body", "require_brands", "prefer_brands",
    ) if profile.get(k) is not None}
    # The top car is not part of the ID: rankings may change while the same buyer
    # decision remains alive.
    payload = {"country": country, "profile": stable_profile}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def decision_id(country: str | None, profile: dict, recommendations: list[dict]) -> str:
    return "dec_" + hashlib.sha256(_decision_seed(country, profile, recommendations).encode("utf-8")).hexdigest()[:14]


def _criterion_summary(profile: dict) -> list[dict]:
    rows: list[dict] = []
    for key, label in (
        ("primary_job", "Uso principal"),
        ("max_price", "Precio máximo"),
        ("max_monthly", "Cuota máxima"),
        ("max_km", "Kilometraje máximo"),
        ("min_year", "Año mínimo"),
        ("daily_km", "Uso diario"),
        ("passengers", "Pasajeros"),
    ):
        if profile.get(key) is not None:
            rows.append({"key": key, "label": label, "value": profile.get(key), "hard": key in {"max_price", "max_monthly", "max_km", "min_year"}})
    for key, label in (("require_body", "Tipo requerido"), ("prefer_body", "Tipo preferido"), ("require_brands", "Marca requerida"), ("prefer_brands", "Marca preferida")):
        value = profile.get(key)
        if value:
            rows.append({"key": key, "label": label, "value": value, "hard": key.startswith("require_")})
    return rows


def _verdict(recommendations: list[dict]) -> dict:
    if not recommendations:
        return {
            "code": "wait",
            "headline": "No compraría por compromiso.",
            "body": "No hay una opción suficientemente fuerte con los criterios actuales.",
            "car_key": None,
        }
    top = recommendations[0]
    name = _car_name(top)
    caveat = top.get("caveat") or top.get("inspect") or "confirmar disponibilidad y completar las verificaciones pendientes"
    return {
        "code": "start_here",
        "headline": f"Empezaría por el {name}.",
        "body": f"Es mi primera unidad para investigar. Antes de comprar, falta {caveat}.",
        "car_key": _car_key(top),
    }


def build_decision(result: dict, country: str | None = None) -> dict:
    profile = dict(result.get("profile") or {})
    recommendations = [dict(c) for c in (result.get("recommendations") or []) if isinstance(c, dict)]
    explore = [dict(c) for c in (result.get("explore") or []) if isinstance(c, dict)]

    enriched = []
    for rank, car in enumerate(recommendations, 1):
        c = dict(car)
        c["decision_rank"] = rank
        c["decision_key"] = _car_key(c)
        c["evidence"] = evidence_for_car(c)
        c["execution"] = execution_for_car(c)
        enriched.append(c)

    did = decision_id(country or profile.get("country"), profile, recommendations)
    return {
        "id": did,
        "version": 1,
        "status": "active" if enriched else "waiting",
        "country": country or profile.get("country"),
        "profile": profile,
        "criteria": _criterion_summary(profile),
        "verdict": _verdict(enriched),
        "recommendations": enriched,
        "explore": explore,
        "considered_count": int(result.get("pool_size") or len(enriched) + len(explore)),
        "market_watch": {
            "enabled": False,
            "refresh_endpoint": "/carly/decision/refresh",
            "supports": ["new_top_pick", "price_drop", "ranking_change", "disappeared"],
        },
    }


def compare_decisions(previous: dict | None, current: dict) -> list[dict]:
    """Explain material market changes without an LLM."""
    if not previous:
        return []
    prev = {c.get("decision_key") or _car_key(c): c for c in previous.get("recommendations") or [] if isinstance(c, dict)}
    cur = {c.get("decision_key") or _car_key(c): c for c in current.get("recommendations") or [] if isinstance(c, dict)}
    changes: list[dict] = []

    prev_top = next(iter(previous.get("recommendations") or []), None)
    cur_top = next(iter(current.get("recommendations") or []), None)
    if prev_top and cur_top and _car_key(prev_top) != _car_key(cur_top):
        changes.append({"type": "new_top_pick", "message": f"{_car_name(cur_top)} ahora es mi #1.", "car_key": _car_key(cur_top)})

    for key, car in cur.items():
        if key not in prev:
            changes.append({"type": "new_candidate", "message": f"Apareció {_car_name(car)} en el shortlist.", "car_key": key})
            continue
        old_p, new_p = prev[key].get("price_usd"), car.get("price_usd")
        if isinstance(old_p, (int, float)) and isinstance(new_p, (int, float)) and new_p < old_p:
            changes.append({"type": "price_drop", "message": f"{_car_name(car)} bajó ${old_p-new_p:,.0f}.", "car_key": key, "from": old_p, "to": new_p})
        old_r, new_r = prev[key].get("decision_rank"), car.get("decision_rank")
        if isinstance(old_r, int) and isinstance(new_r, int) and old_r != new_r:
            changes.append({"type": "ranking_change", "message": f"{_car_name(car)} pasó de #{old_r} a #{new_r}.", "car_key": key, "from": old_r, "to": new_r})

    for key, car in prev.items():
        if key not in cur:
            changes.append({"type": "disappeared", "message": f"{_car_name(car)} salió del shortlist actual.", "car_key": key})
    return changes[:12]


def decorate_response(result: Any, country: str | None = None) -> Any:
    if not isinstance(result, dict):
        return result
    if result.get("phase") == "recommendation":
        result["decision"] = build_decision(result, country=country)
        result["decision_room"] = True
    return result
