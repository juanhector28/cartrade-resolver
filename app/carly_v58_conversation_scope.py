"""Carly v58: restore conversational intake and make vehicle scope mutable.

Two regressions had combined into a visibly broken conversation:
1) v31 treated an exact model mention as sufficient to search immediately, so a
   first turn like ``Toyota Corolla`` skipped Carly's intake and jumped straight
   to inventory/no-result language.
2) v31 derived the exact model from the concatenation of *all* buyer turns. After
   ``Toyota Corolla`` then ``Cualquier Toyota``, the old Corolla token remained in
   the blob and kept the exact-model constraint alive.

v58 makes make/model scope last-write-wins, adds a real brand-only scope, and
prevents make/model preference alone from bypassing the conversational intake.
"""
from __future__ import annotations

import logging
import re
from functools import wraps
from typing import Any

from . import main_v31 as v31

v28 = v31.v28
legacy = v31.legacy
log = logging.getLogger("carly.v58")

_prior_constraints = v31._constraints
_prior_hard_ok = v31._hard_ok
_prior_query_rows = v31._query_rows
_prior_reply = v31._reply
_prior_apply = v31._apply

_BRANDS = {
    **dict(v31._BRAND_ALIASES),
    "subaru": "Subaru",
    "jeep": "Jeep",
    "bmw": "BMW",
    "audi": "Audi",
    "mercedes": "Mercedes-Benz",
    "mercedes benz": "Mercedes-Benz",
    "isuzu": "Isuzu",
}

_CLEAR_ALL_BRAND_RE = re.compile(
    r"\b(?:cualquier\s+marca|cualquiera\s+marca|me\s+da\s+igual\s+la\s+marca|"
    r"sin\s+preferencia\s+de\s+marca|no\s+importa\s+la\s+marca)\b",
    re.I,
)
_CLEAR_MODEL_RE = re.compile(
    r"\b(?:cualquier\s+modelo|cualquiera\s+modelo|me\s+da\s+igual\s+el\s+modelo|"
    r"no\s+importa\s+el\s+modelo|sin\s+preferencia\s+de\s+modelo)\b",
    re.I,
)
_BROAD_WORD_RE = re.compile(r"\b(?:cualquier|cualquiera|cualquiera\s+de)\b", re.I)
_ONLY_RE = re.compile(
    r"\b(?:solo|solamente|unicamente|únicamente|exclusivamente|nada\s+mas\s+que|"
    r"nada\s+más\s+que|tiene\s+que\s+ser|debe\s+ser)\b",
    re.I,
)
_MISSION_RE = re.compile(
    r"\b(?:trabajo|oficina|commute|universidad|uni|facultad|escuela|familia|hijos?|"
    r"bebe|bebé|negocio|delivery|reparto|uber|rideshare|campo|finca|carga|herramientas|"
    r"construcci[oó]n|carretera|viajes?|ciudad|urbano|uso\s+diario|todos\s+los\s+dias|"
    r"todos\s+los\s+días|primer\s+(?:carro|auto)|moverme|transportarme)\b",
    re.I,
)
_NO_BUDGET_RE = re.compile(
    r"\b(?:no\s+tengo\s+(?:un\s+)?(?:presupuesto|budget)|sin\s+presupuesto|"
    r"el\s+presupuesto\s+no\s+importa|no\s+me\s+importa\s+el\s+precio)\b",
    re.I,
)


def _role(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role") or "").lower()
    return str(getattr(message, "role", "") or "").lower()


def _content(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return str(getattr(message, "content", "") or "")


def _messages(body: Any) -> list[Any]:
    if isinstance(body, dict):
        return list(body.get("messages") or [])
    return list(getattr(body, "messages", None) or [])


def _clean_user(text: Any) -> str:
    try:
        return v28._clean_user(str(text or ""))
    except Exception:
        return str(text or "").split("[CONTEXTO ACTIVO DE CARTRADE:", 1)[0].strip()


def _brand_in_turn(text: str) -> str | None:
    n = v28._norm(text)
    # Long aliases first so "mercedes benz" wins before "mercedes".
    for alias, canonical in sorted(_BRANDS.items(), key=lambda kv: len(kv[0]), reverse=True):
        if re.search(rf"\b{re.escape(v28._norm(alias))}\b", n):
            return canonical
    return None


def _scope_state(body: Any) -> dict[str, Any]:
    """Return last-write-wins make/model scope from visible buyer turns only."""
    exact = None
    brand = None
    seen = False
    latest_scope_text = ""
    exact_only = False
    broadened = False

    for message in _messages(body):
        if _role(message) != "user":
            continue
        text = _clean_user(_content(message)).strip()
        if not text:
            continue

        if _CLEAR_ALL_BRAND_RE.search(text):
            exact = None
            brand = None
            seen = True
            broadened = True
            latest_scope_text = text
            exact_only = False
            continue

        turn_exact = v31._canonical_exact(text)
        turn_brand = _brand_in_turn(text)

        # An explicit exact model replaces any previous model/brand scope.
        if turn_exact:
            exact = turn_exact
            brand = turn_exact[0]
            seen = True
            broadened = False
            latest_scope_text = text
            exact_only = bool(_ONLY_RE.search(text))
            continue

        # "Cualquier Toyota", a bare brand, or another brand-only turn replaces
        # the old exact model. This is the concrete stale-Corolla regression.
        if turn_brand:
            normalized = v28._norm(text)
            bare_brand = normalized in {
                v28._norm(alias) for alias, canonical in _BRANDS.items() if canonical == turn_brand
            }
            if _BROAD_WORD_RE.search(text) or _CLEAR_MODEL_RE.search(text) or bare_brand:
                exact = None
                brand = turn_brand
                seen = True
                broadened = True
                latest_scope_text = text
                exact_only = False
                continue

        # "Cualquier modelo" without repeating the make means keep the current
        # make but release the previous exact model.
        if _CLEAR_MODEL_RE.search(text) and brand:
            exact = None
            seen = True
            broadened = True
            latest_scope_text = text
            exact_only = False

    return {
        "seen": seen,
        "exact": exact,
        "brand": brand,
        "latest_scope_text": latest_scope_text,
        "exact_only": exact_only,
        "broadened": broadened,
    }


def _constraints(body: Any) -> dict[str, Any]:
    c = dict(_prior_constraints(body))
    scope = _scope_state(body)
    if scope["seen"]:
        c["exact"] = scope["exact"]
        c["require_brand"] = scope["brand"]
        c["exact_only"] = bool(scope["exact"] and scope["exact_only"])
        c["vehicle_scope_broadened"] = scope["broadened"]
    else:
        c.setdefault("require_brand", None)
        c.setdefault("vehicle_scope_broadened", False)
    return c


def _hard_ok(card: dict, c: dict[str, Any]) -> bool:
    if not _prior_hard_ok(card, c):
        return False
    brand = c.get("require_brand")
    if brand and v28._norm(card.get("make")) != v28._norm(brand):
        return False
    return True


def _query_rows(c: dict[str, Any], country: str) -> list[dict]:
    brand = c.get("require_brand")
    if not brand or c.get("exact"):
        return _prior_query_rows(c, country)
    client = getattr(legacy, "supabase", None)
    if client is None:
        return []
    try:
        response = (
            client.table("scraped_listings").select(v31._SELECT)
            .eq("country", country).eq("is_addressable", True)
            .ilike("make", f"%{brand}%")
            .order("updated_at", desc=True).limit(500).execute()
        )
        return [dict(r) for r in (response.data or [])]
    except Exception:
        log.exception("Carly v58 brand-scoped inventory query failed")
        return []


def _reply(c: dict[str, Any], top: list[dict], exact_miss: bool = False) -> str:
    brand = c.get("require_brand")
    if brand and not c.get("exact"):
        if not top:
            return f"No encontré {brand} elegibles que cumplan tus criterios actuales."
        return f"Abrí la búsqueda a cualquier {brand} y ordené las mejores unidades para tu uso y presupuesto."
    return _prior_reply(c, top, exact_miss=exact_miss)


def _mission_known(body: Any, c: dict[str, Any] | None = None) -> bool:
    c = c or _constraints(body)
    intent = c.get("intent") or {}
    if any(bool(intent.get(key)) for key in ("student", "farm", "heavy_cargo", "family")):
        return True
    if c.get("delivery") or c.get("first_car"):
        return True
    text = " ".join(
        _clean_user(_content(m)) for m in _messages(body) if _role(m) == "user"
    )
    return bool(_MISSION_RE.search(text))


def _budget_known(body: Any, c: dict[str, Any] | None = None) -> bool:
    c = c or _constraints(body)
    if c.get("monthly_max") is not None or c.get("total_budget") is not None:
        return True
    text = " ".join(
        _clean_user(_content(m)) for m in _messages(body) if _role(m) == "user"
    )
    return bool(_NO_BUDGET_RE.search(text))


def _ready(body: Any, c: dict[str, Any] | None = None) -> bool:
    c = c or _constraints(body)
    return _mission_known(body, c) and _budget_known(body, c)


def _scope_intake_reply(body: Any) -> str | None:
    scope = _scope_state(body)
    if not scope["seen"]:
        return None
    c = _constraints(body)
    if _ready(body, c):
        return None

    if not _mission_known(body, c):
        if scope["exact"]:
            label = f"{scope['exact'][0]} {scope['exact'][1]}"
            return f"Perfecto, tomo {label} como tu preferencia. ¿Para qué lo vas a usar principalmente?"
        if scope["brand"]:
            if scope["broadened"]:
                return f"Perfecto, abro el criterio a cualquier {scope['brand']}. ¿Para qué lo vas a usar principalmente?"
            return f"Perfecto, tomo {scope['brand']} como preferencia. ¿Para qué lo vas a usar principalmente?"
        return "Perfecto. ¿Para qué lo vas a usar principalmente?"

    if not _budget_known(body, c):
        return "Perfecto. ¿Qué cuota mensual te queda cómoda?"
    return None


def _apply(body: Any, prior_result: Any) -> Any:
    # The original v31 exact-model bypass is no longer allowed to override the
    # conversation before Carly knows both use and affordability.
    c = _constraints(body)
    if (c.get("exact") or c.get("require_brand")) and not _ready(body, c):
        return prior_result
    return _prior_apply(body, prior_result)


def _request_body(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    body = kwargs.get("body")
    if body is not None:
        return body
    for arg in args:
        if isinstance(arg, dict) and "messages" in arg:
            return arg
        if hasattr(arg, "messages"):
            return arg
    return None


def _install_route_guard(app: Any) -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        prior = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if prior is None or dependant is None or getattr(prior, "_carly_v58_scope_intake", False):
            continue

        @wraps(prior)
        def endpoint(*args: Any, __prior=prior, **kwargs: Any):
            body = _request_body(args, kwargs)
            try:
                reply = _scope_intake_reply(body)
            except Exception:
                log.exception("Carly v58 scope-intake guard failed; falling through")
                reply = None
            if reply:
                return {
                    "phase": "conversation",
                    "reply": reply,
                    "route_precedence": "vehicle_scope_intake_v58",
                    "recommendations": [],
                    "explore": [],
                    "recommendation_count": 0,
                    "explore_count": 0,
                }
            return __prior(*args, **kwargs)

        endpoint._carly_v58_scope_intake = True
        endpoint._carly_v58_prior = prior
        route.endpoint = endpoint
        dependant.call = endpoint
        break


def install(app: Any) -> None:
    v31._constraints = _constraints
    v31._hard_ok = _hard_ok
    v31._query_rows = _query_rows
    v31._reply = _reply
    v31._apply = _apply
    _install_route_guard(app)

    # Import-time regressions for the exact screenshot failure.
    first = {
        "country": "gt",
        "messages": [{"role": "user", "content": "Toyota Corolla"}],
    }
    c1 = _constraints(first)
    if c1.get("exact", ())[:2] != ("Toyota", "Corolla"):
        raise RuntimeError("Carly v58 exact-model scope regression")
    r1 = _scope_intake_reply(first) or ""
    if "¿Para qué lo vas a usar principalmente?" not in r1 or "No encontré" in r1:
        raise RuntimeError("Carly v58 exact model skipped conversational intake")

    broadened = {
        "country": "gt",
        "messages": [
            {"role": "user", "content": "Toyota Corolla"},
            {"role": "assistant", "content": "¿Para qué lo vas a usar principalmente?"},
            {"role": "user", "content": "Cualquier toyota"},
        ],
    }
    c2 = _constraints(broadened)
    if c2.get("exact") is not None or c2.get("require_brand") != "Toyota":
        raise RuntimeError("Carly v58 stale exact model survived brand broadening")
    r2 = _scope_intake_reply(broadened) or ""
    if "cualquier Toyota" not in r2 or "Corolla" in r2:
        raise RuntimeError("Carly v58 brand broadening conversation regression")

    log.warning(
        "CARLY_V58 installed conversational_scope=true last_write_wins_model=true brand_scope=true"
    )
