"""Final production integrity layer for Carly discovery + decision quality.

Post-shortlist turns are deterministic whenever structured vehicle data is enough.
Only genuinely interpretive follow-ups reach the LLM, with a compact prompt/context.
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
_EXACT_FUEL_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:km/l|km\s+por\s+litro|l/100\s*km)\b", re.I)
_EXACT_HP_RE = re.compile(r"\b\d+\s*(?:hp|caballos(?:\s+de\s+fuerza)?)\b", re.I)
_EXACT_ENGINE_RE = re.compile(r"\b\d(?:[.,]\d)?\s*(?:l|litros?)\b", re.I)

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
_ABSOLUTE_UNIT_CLAIMS = (
    "no te va a dar dolores de cabeza", "no te dara dolores de cabeza",
    "no te va a dar problemas", "no te dara problemas",
    "esta en buen estado", "está en buen estado", "esta limpia", "está limpia",
    "esta impecable", "está impecable", "sin problemas mecanicos",
    "sin problemas mecánicos", "sin problemas de documentos",
)
_SPECULATIVE_MECHANICAL_PATTERNS = (
    re.compile(r"manual.{0,100}(?:consume\s+menos|ahorra\s+gasolina|mas\s+economico\s+en\s+combustible)", re.I | re.S),
    re.compile(r"manual.{0,120}(?:mantenimiento|caja).{0,80}mas\s+barat", re.I | re.S),
    re.compile(r"(?:muchos|varios)\s+años?.{0,80}(?:mantenimiento|reparacion|reparación)\s+mayor", re.I | re.S),
)

_LOW_TOKEN_FOLLOWUP_PROMPT = r"""
Eres Carly en follow-up. Responde la ultima pregunta en español neutro, directo,
normalmente 2-5 frases. No reinicies el cuestionario ni emitas PROFILE.
UNIDADES contiene los hechos autoritativos de cada unidad. No inventes specs,
condicion, historial ni porcentajes. Si falta un dato exacto, di que no esta
confirmado. Conocimiento general del modelo solo como tendencia general. Si el
usuario compara, toma posicion para su caso. Si pide siguiente paso, CarTrade
verifica vendedor/unidad, inspeccion, documentos, pago y cierre.
"""


def _norm(value: Any) -> str:
    s = str(value or "").strip().lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s)


def _car_name(car: dict) -> str:
    return " ".join(str(x) for x in (car.get("make"), car.get("model"), car.get("year")) if x)


def _referenced_cars(latest: str, cars: list[dict]) -> list[dict]:
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
    return by_model[:1] if len(unique_models) == 1 else []


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
    return any(x in n for x in (
        "airbag", "km por litro", "km/l", "consumo exacto", "rendimiento exacto",
        "accidente", "accidentes", "caballos", " hp", "potencia", "motor exacto", "cilindrada",
    ))


def _reply_violations(reply: str, latest: str, refs: list[dict], visible: list[dict]) -> list[str]:
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
    if any(_norm(marker) in n for marker in _DENIAL_MARKERS):
        violations.append("denied a vehicle already curated in the visible shortlist")
    allowed = _allowed_percentages(refs or visible)
    for raw in _PERCENT_RE.findall(reply):
        pct = float(raw.replace(",", "."))
        if pct != 100 and not any(abs(pct - expected) <= 1.0 for expected in allowed):
            violations.append(f"ungrounded percentage {pct}%")
    if _EXACT_AIRBAG_RE.search(reply): violations.append("echoed or invented an exact airbag count")
    if _EXACT_FUEL_RE.search(reply): violations.append("invented exact fuel economy")
    if _EXACT_HP_RE.search(reply): violations.append("invented exact horsepower")
    if _EXACT_ENGINE_RE.search(reply): violations.append("invented exact engine displacement")
    if any(_norm(claim) in n for claim in _ABSOLUTE_UNIT_CLAIMS):
        violations.append("unsupported certainty about unit condition or reliability")
    if any(pattern.search(n) for pattern in _SPECULATIVE_MECHANICAL_PATTERNS):
        violations.append("speculative mechanical inference")
    if _needs_unknown_marking(latest) and not any(_norm(x) in n for x in _UNKNOWN_MARKERS):
        violations.append("failed to distinguish unknown from verified")
    return violations


def _buyer_context_summary(facts: dict) -> str:
    bits = []
    if facts.get("daily_km") is not None: bits.append(f"{facts['daily_km']:g} km diarios")
    if facts.get("max_price") is not None: bits.append(f"techo ${facts['max_price']:,.0f}")
    if facts.get("max_km") is not None: bits.append(f"máximo {facts['max_km']:,.0f} km")
    return ", ".join(bits)


def _fallback_followup(latest: str, refs: list[dict], visible: list[dict], facts: dict) -> str:
    focus = refs[0] if refs else (visible[0] if visible else {})
    name = _car_name(focus) or "esta unidad"
    n = _norm(latest)
    if "airbag" in n:
        return f"Sobre el {name}: no tengo confirmado el número exacto de airbags en los datos disponibles. Hay que verificar el equipamiento exacto antes de cerrar."
    if any(x in n for x in ("km por litro", "km/l", "consumo", "rendimiento")):
        return f"Sobre el {name}: el consumo exacto no aparece confirmado en los datos de esta unidad. La inspección de CarTrade contrasta la condición antes del cierre."
    if any(x in n for x in ("caballos", " hp", "potencia")):
        return f"Sobre el {name}: la potencia exacta no está confirmada en los datos disponibles; la versión exacta debe verificarse antes del cierre."
    if "motor" in n or "cilindrada" in n:
        return f"Sobre el {name}: la motorización exacta no está confirmada en los datos disponibles; debe verificarse antes del cierre."
    if "accidente" in n:
        return f"Sobre el {name}: el historial de accidentes no está confirmado. La verificación documental e inspección de CarTrade deben resolverlo."
    context = _buyer_context_summary(facts)
    concrete = []
    if focus.get("price_usd") is not None: concrete.append(f"precio ${float(focus['price_usd']):,.0f}")
    if focus.get("km") is not None: concrete.append(f"{float(focus['km']):,.0f} km reportados")
    if focus.get("transmission"): concrete.append(str(focus.get("transmission")))
    concrete_text = ", ".join(concrete) or "sus datos visibles actuales"
    return f"Sobre el {name}: para tu caso{(' (' + context + ')') if context else ''}, sigue siendo una opción válida. Sí puedo sostener {concrete_text}. Estado, historial y documentos requieren verificación antes de cerrar."


def _compact_messages(messages, keep: int = 6):
    rows = list(messages or [])
    return rows[-keep:] if len(rows) > keep else rows


def _compact_car(car: dict) -> dict:
    keep = (
        "make", "model", "year", "km", "price_usd", "monthly_est", "body_type",
        "transmission", "value_delta_pct", "value_label", "caveat", "inspect",
        "strategy_label", "best_for", "match_pct",
    )
    return {k: car.get(k) for k in keep if car.get(k) is not None}


def _focused_visible(latest: str, visible: list[dict], limit: int = 6) -> tuple[list[dict], list[dict]]:
    """Keep the named unit even when it came from the tail of Explore."""
    refs = _referenced_cars(latest, visible)
    out: list[dict] = []
    seen = set()
    for car in refs + visible:
        key = (car.get("make"), car.get("model"), car.get("year"), car.get("price_usd"))
        if key in seen:
            continue
        seen.add(key)
        out.append(_compact_car(car))
        if len(out) >= limit:
            break
    return out, _referenced_cars(latest, out)


def _deterministic_followup(latest: str, refs: list[dict], visible: list[dict], facts: dict) -> str | None:
    """Answer common fact/advisor questions with zero model tokens."""
    n = _norm(latest)
    if _needs_unknown_marking(latest) and (refs or visible):
        return _fallback_followup(latest, refs, visible, facts)

    focus = refs[0] if len(refs) == 1 else None
    if focus:
        name = _car_name(focus)
        if any(x in n for x in ("cuanto cuesta", "precio", "precio tiene")) and focus.get("price_usd") is not None:
            return f"El {name} está publicado en ${float(focus['price_usd']):,.0f}. Ese es el precio reportado por el anuncio; el valor final se valida antes del cierre."
        if any(x in n for x in ("cuota", "al mes", "mensual")) and focus.get("monthly_est") is not None:
            return f"Para el {name}, la cuota estimada que tengo es de aproximadamente ${float(focus['monthly_est']):,.0f}/mes. Es una estimación hasta la pre-calificación y condiciones finales."
        if any(x in n for x in ("kilometraje", "cuantos km", "kilometros")) and focus.get("km") is not None:
            return f"El anuncio del {name} reporta {float(focus['km']):,.0f} km. CarTrade contrasta el kilometraje dentro de la verificación antes de cerrar."
        if any(x in n for x in ("transmision", "automatico", "manual")) and focus.get("transmission"):
            return f"El {name} aparece publicado con transmisión {focus['transmission']}. Ese dato se confirma con la unidad antes del cierre."
        if any(x in n for x in ("por que este", "por que me lo recomiendas", "why this")):
            facts_bits = []
            if focus.get("monthly_est") is not None:
                facts_bits.append(f"cuota estimada de ${float(focus['monthly_est']):,.0f}/mes")
            if focus.get("price_usd") is not None:
                facts_bits.append(f"precio de ${float(focus['price_usd']):,.0f}")
            if focus.get("value_label"):
                facts_bits.append(str(focus.get("value_label")))
            grounded = ", ".join(facts_bits[:3]) or "los datos concretos de esta unidad"
            tail = focus.get("caveat") or focus.get("inspect") or "estado, historial y documentos"
            return f"Yo empezaría por el {name} porque quedó arriba en tu ranking y combina bien con tu búsqueda. En esta unidad puedo sostener {grounded}. Antes de cerrar, todavía validaría {tail}."
        if any(x in n for x in ("preocupa", "preocupar", "validar", "revisar antes", "que revisar")):
            tail = focus.get("caveat") or focus.get("inspect") or "estado, historial, kilometraje y documentos"
            return f"En el {name}, lo principal que validaría antes de avanzar es {tail}. No asumiría un problema por eso: simplemente es lo que falta confirmar sobre esta unidad."

    if not refs and visible and any(x in n for x in ("cual comprarias", "cual elegirias", "por cual empezarias")):
        top = visible[0]
        name = _car_name(top)
        reason = []
        if top.get("monthly_est") is not None:
            reason.append(f"~${float(top['monthly_est']):,.0f}/mes")
        if top.get("value_label"):
            reason.append(str(top["value_label"]))
        suffix = " y ".join(reason[:2])
        return f"Yo empezaría por el {name}" + (f": {suffix}." if suffix else ".") + " Es el que Carly tiene arriba del shortlist para tu búsqueda actual; después validaría la unidad antes de cerrar."
    return None


def _answer_followup_integrity(body):
    if not legacy._anthropic:
        return None

    facts = extract_explicit_facts(body.messages)
    all_visible = guarded._shown_car_payload(getattr(body, "shown_cars", None) or [])
    latest = guarded._latest_user_text(body)
    visible, refs = _focused_visible(latest, all_visible, limit=6)

    deterministic = _deterministic_followup(latest, refs, visible, facts)
    if deterministic:
        return {"phase": "conversation", "reply": deterministic, "token_path": "deterministic"}

    msgs, frontend_meta = guarded._clean_frontend_context_guarded(_compact_messages(body.messages))
    system = _LOW_TOKEN_FOLLOWUP_PROMPT
    if refs:
        system += "\nFOCO:" + json.dumps(refs, ensure_ascii=False, separators=(",", ":"))
    if getattr(body, "country", None):
        system += f"\nPais:{body.country}."
    canonical = canonical_context_line(facts)
    if canonical:
        system += "\n" + canonical
    if frontend_meta:
        system += "\n" + "\n".join(frontend_meta[-2:])
    system += "\nUNIDADES:" + json.dumps(visible, ensure_ascii=False, separators=(",", ":"))

    resp = legacy._anthropic.messages.create(
        model=legacy.CARLY_MODEL,
        max_tokens=320,
        system=system,
        messages=msgs,
    )
    reply = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text").strip()
    if reply and not _reply_violations(reply, latest, refs, visible):
        out = guarded._sanitize_buyer_reply({"phase": "conversation", "reply": reply})
        out["token_path"] = "compact_llm"
        return out
    return {"phase": "conversation", "reply": _fallback_followup(latest, refs, visible, facts), "token_path": "deterministic_fallback"}


def _apply_result_facts(result: Any, facts: dict) -> Any:
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
