"""Final production integrity layer for Carly discovery + decision quality.

This module sits on top of ``main_guarded``. It turns the most important
post-shortlist rules into runtime invariants instead of relying only on prompt
compliance:

* the latest explicit buyer constraints are pinned before a rerank;
* a follow-up about a named visible car is anchored to that exact unit;
* percentages and exact specs are checked against structured visible-car data;
* an unsafe / ungrounded answer gets one repair attempt before a deterministic
  conservative fallback is returned.
"""
from __future__ import annotations

import json
import re
from typing import Any

from . import main_guarded as guarded
from .carly_guardrails import canonical_context_line, extract_explicit_facts

legacy = guarded.legacy
app = guarded.app

_PERCENT_RE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*%")
_EXACT_AIRBAG_RE = re.compile(r"\b\d+\s+airbags?\b", re.I)
_UNKNOWN_MARKERS = (
    "no tengo", "no aparece", "no esta en los datos", "no está en los datos",
    "no esta confirmado", "no está confirmado", "no puedo confirmar",
    "hay que verificar", "requiere verificacion", "requiere verificación",
    "la inspeccion", "la inspección",
)
_DENIAL_MARKERS = (
    "no te lo recomende", "no te lo recomendé", "no lo recomende",
    "no lo recomendé", "nunca te lo recomende", "nunca te lo recomendé",
)


def _norm(value: Any) -> str:
    s = str(value or "").strip().lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s)


def _car_name(car: dict) -> str:
    return " ".join(str(x) for x in (car.get("make"), car.get("model"), car.get("year")) if x)


def _referenced_cars(latest: str, cars: list[dict]) -> list[dict]:
    """Resolve cars explicitly named in the latest buyer turn.

    Model + year is strongest. Model alone is accepted when unique among the
    visible shortlist. This is deliberately deterministic so the LLM does not
    get to decide which unit the buyer meant.
    """
    text = _norm(latest)
    refs: list[dict] = []
    for car in cars:
        model = _norm(car.get("model"))
        make = _norm(car.get("make"))
        year = str(car.get("year") or "")
        if not model or model not in text:
            continue
        if (year and year in latest) or (make and make in text):
            refs.append(car)

    if refs:
        return refs

    by_model = [car for car in cars if _norm(car.get("model")) and _norm(car.get("model")) in text]
    unique_models = {_norm(car.get("model")) for car in by_model}
    if len(unique_models) == 1:
        return by_model[:1]
    return []


def _allowed_percentages(cars: list[dict]) -> list[float]:
    allowed: list[float] = []
    for car in cars:
        for key in ("value_delta_pct", "match_pct"):
            value = car.get(key)
            if isinstance(value, (int, float)):
                allowed.append(abs(float(value)))
    return allowed


def _needs_unknown_marking(latest: str) -> bool:
    n = _norm(latest)
    return any(x in n for x in ("airbag", "km por litro", "km/l", "accidente", "accidentes"))


def _reply_violations(reply: str, latest: str, refs: list[dict], visible: list[dict]) -> list[str]:
    """Return objective grounding violations in a generated follow-up answer."""
    violations: list[str] = []
    n = _norm(reply)

    if len(refs) == 1:
        focus = refs[0]
        model = _norm(focus.get("model"))
        year = str(focus.get("year") or "")
        if model and model not in n:
            violations.append("missing focused vehicle model")
        if year and year not in reply:
            violations.append("missing focused vehicle year")

    if any(marker in n for marker in _DENIAL_MARKERS):
        violations.append("denied a vehicle already curated in the visible shortlist")

    pct_scope = refs or visible
    allowed = _allowed_percentages(pct_scope)
    for raw in _PERCENT_RE.findall(reply):
        pct = float(raw.replace(",", "."))
        if pct == 100:
            continue
        if not any(abs(pct - expected) <= 1.0 for expected in allowed):
            violations.append(f"ungrounded percentage {pct}%")

    latest_n = _norm(latest)
    if "airbag" in latest_n and _EXACT_AIRBAG_RE.search(reply):
        violations.append("echoed or invented an exact airbag count")

    if _needs_unknown_marking(latest) and not any(_norm(x) in n for x in _UNKNOWN_MARKERS):
        violations.append("failed to distinguish unknown from verified")

    return violations


def _buyer_context_summary(facts: dict) -> str:
    bits = []
    if facts.get("daily_km") is not None:
        bits.append(f"{facts['daily_km']:g} km diarios")
    if facts.get("max_price") is not None:
        bits.append(f"techo ${facts['max_price']:,.0f}")
    if facts.get("max_km") is not None:
        bits.append(f"máximo {facts['max_km']:,.0f} km")
    return ", ".join(bits)


def _fallback_followup(latest: str, refs: list[dict], visible: list[dict], facts: dict) -> str:
    """Safe answer used only if model output fails validation twice."""
    focus = refs[0] if refs else (visible[0] if visible else {})
    name = _car_name(focus) or "esta unidad"
    n = _norm(latest)

    if "airbag" in n:
        return (
            f"Sobre el {name}: no tengo confirmado el número exacto de airbags en los datos "
            "disponibles de esta unidad. No sería correcto completar ese dato con información "
            "general del modelo. Hay que verificar el equipamiento exacto dentro del proceso de "
            "CarTrade antes de cerrar."
        )
    if "km por litro" in n or "km/l" in n:
        return (
            f"Sobre el {name}: el consumo exacto no aparece confirmado en los datos de esta "
            "unidad. Puedo hablar de tendencias generales del modelo, pero no atribuirle una cifra "
            "a este carro sin respaldo. La condición mecánica se contrasta en la inspección de CarTrade."
        )
    if "accidente" in n:
        return (
            f"Sobre el {name}: el historial de accidentes no está confirmado en los datos "
            "disponibles. Eso no significa que haya tenido ni que no haya tenido accidentes. "
            "La verificación documental y la inspección de CarTrade son las que deben resolverlo."
        )

    context = _buyer_context_summary(facts)
    concrete = []
    if focus.get("price_usd") is not None:
        concrete.append(f"precio ${float(focus['price_usd']):,.0f}")
    if focus.get("km") is not None:
        concrete.append(f"{float(focus['km']):,.0f} km reportados")
    if focus.get("transmission"):
        concrete.append(str(focus.get("transmission")))
    concrete_text = ", ".join(concrete) or "sus datos visibles actuales"
    caveat = focus.get("inspect") or focus.get("caveat") or "estado, documentos e historial de la unidad"

    return (
        f"Sobre el {name}: para tu caso{(' (' + context + ')') if context else ''}, sigue siendo "
        f"una opción válida del shortlist. De esta unidad sí puedo sostener {concrete_text}. "
        f"Lo que todavía requiere verificación es {caveat}; no asumiría condición mecánica, historial "
        "ni equipamiento que no estén confirmados. Si la estás considerando seriamente, el siguiente "
        "paso correcto es Ver detalles e iniciar la compra verificada dentro de CarTrade."
    )


def _answer_followup_integrity(body):
    if not legacy._anthropic:
        return None

    msgs, frontend_meta = guarded._clean_frontend_context_guarded(body.messages)
    facts = extract_explicit_facts(body.messages)
    visible = guarded._shown_car_payload(getattr(body, "shown_cars", None) or [])
    latest = guarded._latest_user_text(body)
    refs = _referenced_cars(latest, visible)

    system = guarded._FOLLOWUP_SYSTEM_PROMPT + "\n\n" + guarded.GUARDRAIL_PROMPT
    system += "\n\n# CONTRATO DE DECISION Y GROUNDING\n"
    system += (
        "Toda unidad en UNIDADES VISIBLES fue curada por Carly. Nunca niegues haberla mostrado. "
        "Si el comprador nombra modelo/año, ESA unidad es el foco obligatorio. Repite modelo y año "
        "para dejar claro el anclaje. No calcules, derives ni improvises porcentajes: solo puedes "
        "copiar literalmente value_delta_pct o match_pct de la unidad o unidades que el comprador "
        "está preguntando. Si un dato exacto no existe, responde explícitamente que no está confirmado."
    )
    if refs:
        system += "\nFOCO RESUELTO POR SISTEMA: " + json.dumps(refs, ensure_ascii=False, separators=(",", ":"))
    if getattr(body, "country", None):
        system += f"\nPais/codigo seleccionado: {body.country}."
    if frontend_meta:
        system += "\n" + "\n".join(frontend_meta)
    canonical = canonical_context_line(facts)
    if canonical:
        system += "\n" + canonical
    system += (
        "\n\n# UNIDADES VISIBLES: DATOS AUTORITATIVOS\n"
        + json.dumps(visible, ensure_ascii=False, separators=(",", ":"))
    )

    repair_note = ""
    for _attempt in range(2):
        attempt_system = system + repair_note
        resp = legacy._anthropic.messages.create(
            model=legacy.CARLY_MODEL,
            max_tokens=900,
            system=attempt_system,
            messages=msgs,
        )
        reply = "".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        ).strip()
        if not reply:
            continue
        violations = _reply_violations(reply, latest, refs, visible)
        if not violations:
            return guarded._sanitize_buyer_reply({"phase": "conversation", "reply": reply})
        repair_note = (
            "\n\n# REPARACION OBLIGATORIA\nLa respuesta anterior fue bloqueada por estas violaciones: "
            + "; ".join(violations)
            + ". Genera una respuesta nueva desde cero y elimina esas violaciones."
        )

    return {"phase": "conversation", "reply": _fallback_followup(latest, refs, visible, facts)}


def _apply_result_facts(result: Any, facts: dict) -> Any:
    """Last-resort consistency pin for the public profile returned after rerank."""
    if not isinstance(result, dict) or result.get("phase") != "recommendation" or not facts:
        return result
    profile = result.get("profile")
    if isinstance(profile, dict):
        for key in ("max_price", "max_km", "daily_km"):
            if facts.get(key) is not None:
                profile[key] = facts[key]
    return result


def _patch_decision_route():
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        endpoint = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if endpoint is None or dependant is None:
            continue

        prior_endpoint = endpoint

        def decision_endpoint(*args: Any, __prior=prior_endpoint, **kwargs: Any):
            body = guarded._request_body(args, kwargs)
            facts = extract_explicit_facts(getattr(body, "messages", None) or []) if body is not None else {}
            # Set the context before the legacy path starts. This closes the race /
            # call-order hole where profile extraction could see the previous budget.
            guarded._facts_ctx.set(dict(facts))

            if guarded._should_answer_as_followup(body):
                try:
                    direct = _answer_followup_integrity(body)
                    if direct:
                        return guarded._sanitize_buyer_reply(direct)
                except Exception:
                    legacy.log.exception("Carly integrity follow-up failed; using guarded fallback path")

            result = __prior(*args, **kwargs)
            return guarded._sanitize_buyer_reply(_apply_result_facts(result, facts))

        route.endpoint = decision_endpoint
        dependant.call = decision_endpoint
        break


_patch_decision_route()
