"""Production commercial-advisory layer for Carly.

This is the outermost /carly/chat wrapper. Routine intake is intercepted before
any paid model call, recommendation quality is enforced before both shortlist and
Explore, and common advisor follow-ups stay deterministic.
"""
from __future__ import annotations

import os
import re
import unicodedata
from typing import Any

from . import main_preview as preview
from .carly_commercial import COMMERCIAL_PROMPT, commercialize_response
from .carly_quality_gate import filter_cards, filter_pool, install_rank_quality

app = preview.app
legacy = preview.legacy
guarded = preview.guarded

RUNTIME_COMPOSITION = "commercial-v6-live-regressions"


# ---------------------------------------------------------------------------
# Authoritative cheap quality + depth controls
# ---------------------------------------------------------------------------

def _install_inventory_quality(original):
    """Filter the market pool itself so Explore cannot bypass the quality gate."""
    if getattr(original, "_carly_inventory_quality_wrapped", False):
        return original

    def quality_inventory(profile, *args, **kwargs):
        rows = original(profile, *args, **kwargs)
        return filter_pool(list(rows or []), profile)

    quality_inventory._carly_inventory_quality_wrapped = True
    quality_inventory._carly_inventory_original = original
    return quality_inventory


def _install_rank_cap(original, cap: int = 3):
    """Default Carly to a small curated shortlist instead of six equal-looking picks."""
    if getattr(original, "_carly_rank_cap_wrapped", False):
        return original

    def capped_rank(cars, profile, *args, **kwargs):
        args = list(args)
        if "top_n" in kwargs:
            try:
                kwargs["top_n"] = max(1, min(int(kwargs["top_n"]), cap))
            except Exception:
                kwargs["top_n"] = cap
        elif args:
            try:
                args[0] = max(1, min(int(args[0]), cap))
            except Exception:
                args[0] = cap
        else:
            kwargs["top_n"] = cap
        return original(cars, profile, *args, **kwargs)

    capped_rank._carly_rank_cap_wrapped = True
    capped_rank._carly_rank_cap_original = original
    return capped_rank


# Filter before ranking AND before Explore is built. The prior v4 patch only
# wrapped rank_cars, so raw pool order could still reintroduce L200/Saveiro,
# commercial trucks or damaged rows in the lower recommendation surface.
legacy._carly_inventory = _install_inventory_quality(legacy._carly_inventory)
legacy.rank_cars = _install_rank_cap(install_rank_quality(legacy.rank_cars), cap=3)


# ---------------------------------------------------------------------------
# Live-test intake repair
# ---------------------------------------------------------------------------

_STANDALONE_SMALL_AMOUNT_RE = re.compile(
    r"^\s*\$?\s*([0-9]+(?:[.,][0-9]+)?)\s*(?:usd|d[oó]lares?)?\s*$",
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


def _repair_missing_monthly_context(messages: list[Any], country: str | None = None) -> list[Any]:
    """Recover a standalone `$500` even if the UI omitted Carly's prior question.

    The latest live test showed a client-state race where the first numeric reply
    reached the backend without the immediately preceding assistant turn. We only
    repair when Carly's deterministic state says intent is known, budget is still
    missing, and the latest buyer message is a plausible monthly amount (<$2k).
    """
    rows = list(messages or [])
    blocker = preview.deterministic_intake_reply(rows, country=country)
    if blocker != "Entendido. ¿Qué cuota mensual te queda cómoda?":
        return rows

    last_user_idx = None
    for idx in range(len(rows) - 1, -1, -1):
        if _role(rows[idx]) == "user":
            last_user_idx = idx
            break
    if last_user_idx is None:
        return rows

    match = _STANDALONE_SMALL_AMOUNT_RE.match(_content(rows[last_user_idx]))
    if not match:
        return rows
    try:
        amount = float(match.group(1).replace(",", "."))
    except ValueError:
        return rows
    if not 25 <= amount < 2000:
        return rows

    repaired = list(rows)
    repaired.insert(
        last_user_idx,
        {"role": "assistant", "content": "Entendido. ¿Qué cuota mensual te queda cómoda?"},
    )
    return repaired


# ---------------------------------------------------------------------------
# Deterministic compound advisor follow-up
# ---------------------------------------------------------------------------

def _norm_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip()


def _install_compound_followup_fix() -> None:
    """Prioritize 'why this + what to verify' over incidental fact handlers."""
    decision = preview.room.state.decision
    original = getattr(decision, "_deterministic_followup", None)
    if original is None or getattr(original, "_carly_compound_fixed", False):
        return

    def fixed_followup(latest, refs, visible, facts):
        n = _norm_text(latest)
        focus = refs[0] if len(refs or []) == 1 else None
        explain = any(x in n for x in (
            "por que me lo recomiendas", "por que lo recomiendas", "por que este",
            "por que lo elegiste", "cuentame mas de",
        ))
        concern = any(x in n for x in (
            "preocupar", "preocupa", "que deberia revisar", "que revisar",
            "que validaria", "que validar",
        ))

        if focus and (explain or concern):
            name = " ".join(
                str(x) for x in (focus.get("make"), focus.get("model"), focus.get("year")) if x
            ) or "esta unidad"
            reasons = []
            monthly = focus.get("monthly_est")
            price = focus.get("price_usd")
            body = _norm_text(focus.get("body_type"))
            if body in {"hatchback", "sedan"}:
                reasons.append("encaja con el formato urbano/compacto de tu búsqueda")
            if monthly is not None:
                reasons.append(f"su cuota estimada ronda ${float(monthly):,.0f}/mes")
            if price is not None:
                reasons.append(f"está publicado en ${float(price):,.0f}")
            if focus.get("value_label"):
                reasons.append(str(focus.get("value_label")))
            reason_text = "; ".join(reasons[:3]) or "quedó bien posicionado con los datos disponibles"

            caveat = focus.get("caveat") or focus.get("inspect")
            if caveat:
                verify_text = str(caveat)
            else:
                verify_text = "estado real, historial, disponibilidad, kilometraje y documentos"

            support_note = ""
            mainstream = {
                "toyota", "honda", "nissan", "kia", "hyundai", "mazda", "suzuki",
                "mitsubishi", "chevrolet", "ford", "volkswagen",
            }
            if _norm_text(focus.get("make")) not in mainstream:
                support_note = (
                    " También comprobaría disponibilidad y costo local de repuestos/talleres, "
                    "porque ese dato no está confirmado en la ficha."
                )

            if explain and concern:
                return (
                    f"Yo empezaría por el {name} porque {reason_text}. "
                    f"Pero no lo compraría a ciegas: antes validaría {verify_text}."
                    + support_note
                )
            if explain:
                return f"Yo empezaría por el {name} porque {reason_text}. Antes de cerrar, validaría {verify_text}." + support_note
            return f"En el {name}, antes de avanzar validaría {verify_text}." + support_note

        return original(latest, refs, visible, facts)

    fixed_followup._carly_compound_fixed = True
    fixed_followup._carly_compound_original = original
    decision._deterministic_followup = fixed_followup


_install_compound_followup_fix()


try:
    if COMMERCIAL_PROMPT.strip() not in str(legacy.CARLY_SYSTEM_PROMPT):
        legacy.CARLY_SYSTEM_PROMPT += COMMERCIAL_PROMPT
except Exception:
    pass
try:
    if COMMERCIAL_PROMPT.strip() not in str(guarded._FOLLOWUP_SYSTEM_PROMPT):
        guarded._FOLLOWUP_SYSTEM_PROMPT += COMMERCIAL_PROMPT
except Exception:
    pass


@app.get("/carly/runtime")
def carly_runtime():
    return {
        "ok": True,
        "composition": RUNTIME_COMPOSITION,
        "token_strategy": "rules-first",
        "intake_fastpath": True,
        "quality_gate": True,
        "explore_quality_gate": True,
        "default_curated_recommendations": 3,
        "followup_max_tokens": 320,
        "git_commit": os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT") or None,
    }


def _request_body(args, kwargs):
    try:
        return guarded._request_body(args, kwargs)
    except Exception:
        return None


def _profile_for_result(result: Any):
    if not isinstance(result, dict):
        return None
    data = result.get("profile")
    if not isinstance(data, dict):
        return None
    try:
        return legacy.profile_from_extraction(dict(data))
    except Exception:
        return None


def _final_quality_gate(result: Any) -> Any:
    """Final safety net. Shortlist=3; Explore must match the same buyer mission."""
    if not isinstance(result, dict) or result.get("phase") != "recommendation":
        return result
    profile = _profile_for_result(result)
    if profile is None:
        return result

    cards = filter_cards(list(result.get("recommendations") or []), profile, limit=3)
    result["recommendations"] = cards
    result["favorite"] = cards[0] if cards else None
    result["recommendation_count"] = len(cards)
    result["recommendation_quality_policy"] = "quality_over_quota"

    curated_urls = {c.get("url") for c in cards if c.get("url")}
    explore = filter_cards(list(result.get("explore") or []), profile, limit=18)
    result["explore"] = [c for c in explore if c.get("url") not in curated_urls][:12]

    decision = result.get("decision")
    if isinstance(decision, dict):
        decision_cards = filter_cards(list(decision.get("recommendations") or []), profile, limit=3)
        decision["recommendations"] = decision_cards
        # Explore used to be copied before the outer gate, which let raw inventory
        # survive even when root Explore had been cleaned.
        decision["explore"] = list(result.get("explore") or [])
        if "favorite" in decision:
            decision["favorite"] = decision_cards[0] if decision_cards else None

    return result


def _deterministic_outer_fastpath(body, messages: list[Any]) -> dict | None:
    """Resolve common intake before entering any older/LLM route layer."""
    if body is None or (getattr(body, "shown_cars", None) or []):
        return None

    country = getattr(body, "country", None)
    parse_messages = _repair_missing_monthly_context(messages, country=country)
    fast = preview.extract_fast_profile(parse_messages, country=country)
    if fast:
        try:
            policy = preview.preview_policy(parse_messages, has_visible_cars=False)
            direct = preview._preview_result(
                body,
                {**policy, "reason": "outer_deterministic_fastpath"},
                data=fast,
            )
            if direct is not None:
                direct["token_path"] = "deterministic"
                return direct
        except Exception:
            legacy.log.exception("Carly outer deterministic preview failed")

    blocker = preview.deterministic_intake_reply(messages, country=country)
    if blocker:
        return {
            "phase": "conversation",
            "reply": blocker,
            "token_path": "deterministic",
        }
    return None


def _patch_commercial_route() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        endpoint = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if endpoint is None or dependant is None:
            continue
        prior = endpoint

        def commercial_endpoint(*args: Any, __prior=prior, **kwargs: Any):
            body = _request_body(args, kwargs)
            messages = list(getattr(body, "messages", None) or []) if body is not None else []

            direct = _deterministic_outer_fastpath(body, messages)
            if direct is not None:
                direct = _final_quality_gate(direct)
                if direct.get("phase") == "conversation":
                    return direct
                return commercialize_response(direct, messages=messages)

            result = __prior(*args, **kwargs)
            result = _final_quality_gate(result)
            return commercialize_response(result, messages=messages)

        route.endpoint = commercial_endpoint
        dependant.call = commercial_endpoint
        break


_patch_commercial_route()
