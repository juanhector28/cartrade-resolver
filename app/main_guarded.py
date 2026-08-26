"""Production composition root for Carly guardrails.

The existing FastAPI implementation stays in app.main. This module patches only
Carly's decision path at import time and exposes the same `app` object. The
wrapper also separates post-shortlist follow-up advice from fresh recommendation
runs so a question about one visible car does not restart the whole funnel.
"""
from __future__ import annotations

import contextvars
import json
import re
from typing import Any

from . import main as legacy
from . import carly_profile as profile_module
from . import carly_ranking as ranking
from .carly_guardrails import (
    GUARDRAIL_PROMPT,
    apply_explicit_facts,
    canonical_context_line,
    extract_explicit_facts,
    passes_pinned_constraints,
    pin_hard_constraints,
)

_facts_ctx: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "carly_explicit_facts", default={}
)
_market_refs_ctx: contextvars.ContextVar[list] = contextvars.ContextVar(
    "carly_market_refs", default=[]
)

_original_clean_frontend_context = legacy._clean_frontend_context
_original_profile_from_extraction = legacy.profile_from_extraction
_original_passes_filters = ranking.passes_filters
_original_inventory = legacy._carly_inventory
_original_rank_cars = legacy.rank_cars


# A buyer can ask almost anything after the shortlist. Most of those turns should
# be answered directly from the visible cars + conversation context. Only an
# explicit change to search criteria should restart extraction/ranking.
_RERANK_FOLLOWUP_RE = re.compile(
    r"\b(?:"
    r"reordena|reordenar|recomienda(?:me)?\s+(?:de\s+nuevo|otra\s+vez)|"
    r"nuevas?\s+opciones|mas\s+opciones|más\s+opciones|"
    r"cambia(?:r)?\s+(?:tu\s+)?recomendacion|cambia(?:r)?\s+(?:tu\s+)?recomendación|"
    r"cambio\s+una\s+cosa|pensandolo\s+bien|pensándolo\s+bien|"
    r"ahora\s+(?:puedo|quiero|necesito)|subo\s+(?:el\s+)?presupuesto|"
    r"bajo\s+(?:el\s+)?(?:presupuesto|limite|límite)|"
    r"mant[eé]n\s+(?:el\s+)?limite|mant[eé]n\s+(?:el\s+)?límite|"
    r"maximo\s+\$|máximo\s+\$|maximo\s+\d[\d.,]*\s*(?:km|kms)|"
    r"máximo\s+\d[\d.,]*\s*(?:km|kms)|menos\s+de\s+\d[\d.,]*\s*(?:km|kms)|"
    r"hasta\s+\$\s*\d"
    r")\b",
    re.I,
)

_FOLLOWUP_SYSTEM_PROMPT = r"""
Eres Carly, la asesora de compra de CarTrade, y estas en MODO FOLLOW-UP despues
de que la persona ya vio opciones reales.

Tu trabajo en este turno es responder DIRECTAMENTE la ultima pregunta. No
reinicies el cuestionario, no vuelvas a presentar el shortlist completo y NO
emitas <PROFILE> ni ningun bloque estructurado.

REGLAS DE FOLLOW-UP:
1) Usa la conversacion para recordar la vida y restricciones del comprador. No
   sustituyas hechos por supuestos nuevos.
2) Los datos de las unidades visibles que recibes abajo son autoritativos para
   precio, año, km, ubicacion, transmision, señales de mercado y provenance.
3) Si preguntan pros/contras o "por que este", separa:
   - fit del modelo con la necesidad del comprador;
   - datos concretos de ESA unidad;
   - lo que todavia requiere verificacion.
4) Puedes mencionar conocimiento GENERAL de un modelo solo como tendencia general
   ("en general", "suele", "normalmente"), nunca como especificacion exacta de
   esta unidad. Equipamiento, airbags, motor exacto, consumo exacto, historial de
   accidentes, numero de dueños y condicion NO se inventan.
5) Si un dato exacto no esta en las unidades visibles, dilo claramente. No llenes
   el hueco con memoria del modelo. Para historial/condicion/km/documentos, explica
   que la verificacion/inspeccion de CarTrade confirma lo que corresponda.
6) Un precio sobre mercado significa caro frente a comparables, nada mas. No lo
   conviertas en sospecha mecanica o documental.
7) Si comparan dos o mas opciones, toma una posicion para ESTE comprador y explica
   el trade-off. No respondas con "depende" sin criterio.
8) Nunca prometas que una unidad "no dara problemas", "esta limpia" o "esta en
   buen estado" antes de inspeccion.
9) Si preguntan que hacer antes de comprar, el camino es CarTrade: Ver detalles /
   Iniciar compra verificada, contacto con vendedor, verificacion, inspeccion,
   documentos, custodia y cierre segun corresponda. No mandes al comprador a
   buscar mecanico ni negociar por fuera.
10) Responde con la extension que pida la pregunta. Por defecto 3-7 frases o una
    lista corta si pros/contras lo amerita. No cierres cada respuesta con una
    pregunta automatica; solo pregunta si de verdad falta un dato para responder.
"""


def _sanitize_frontend_meta(items: list[str]) -> list[str]:
    """Keep location metadata but remove radius numbers that can become fake usage."""
    cleaned = []
    for item in items or []:
        text = str(item or "")
        text = re.sub(
            r"\b(?:radio|radius|rango)\s*:?\s*\d+(?:[.,]\d+)?\s*km\b",
            "",
            text,
            flags=re.I,
        )
        text = re.sub(r"\s*[·|]\s*\d+(?:[.,]\d+)?\s*km\b", "", text, flags=re.I)
        text = re.sub(r"\s{2,}", " ", text).strip(" ;,·|")
        if text:
            cleaned.append(text)
    return cleaned


def _clean_frontend_context_guarded(messages):
    cleaned, meta = _original_clean_frontend_context(messages)
    facts = extract_explicit_facts(messages)
    _facts_ctx.set(dict(facts))

    safe_meta = _sanitize_frontend_meta(meta)
    canonical = canonical_context_line(facts)
    if canonical:
        safe_meta.append(canonical)
    return cleaned, safe_meta


def _profile_from_extraction_guarded(data: dict):
    facts = _facts_ctx.get({})
    apply_explicit_facts(data, facts)
    profile = _original_profile_from_extraction(data)
    return pin_hard_constraints(profile, data)


def _passes_filters_guarded(car, profile):
    if car.get("_carly_reference_only"):
        return False
    if not _original_passes_filters(car, profile):
        return False
    return passes_pinned_constraints(car, profile)


def _load_market_references(country: str | None, limit: int = 5000) -> list[dict]:
    """Broad, profile-independent market set for stable price comparisons."""
    if not legacy.supabase:
        return []
    try:
        q = (
            legacy.supabase.table("scraped_listings")
            .select("url,make,model,price_usd")
            .eq("status", "staging")
            .not_.is_("price_usd", "null")
            .limit(limit)
        )
        if country:
            q = q.eq("country", country)
        return q.execute().data or []
    except Exception:
        legacy.log.exception("Carly market-reference pull failed")
        return []


def _carly_inventory_guarded(profile, country=None, pool=600):
    """Return only rows that satisfy every pinned hard constraint."""
    _market_refs_ctx.set(_load_market_references(country))

    fetch_pool = min(3000, max(int(pool or 600) * 3, int(pool or 600)))
    rows = _original_inventory(profile, country=country, pool=fetch_pool)
    eligible = [r for r in rows if ranking.passes_filters(r, profile)]
    return eligible[: int(pool or 600)]


def _rank_cars_guarded(cars, profile, top_n=5):
    """Rank eligible cars while comparing price against the broader market."""
    live = list(cars or [])
    live_urls = {r.get("url") for r in live if r.get("url")}
    references = []
    for row in _market_refs_ctx.get([]):
        if row.get("url") and row.get("url") in live_urls:
            continue
        ref = dict(row)
        ref["_carly_reference_only"] = True
        references.append(ref)
    return _original_rank_cars(live + references, profile, top_n=top_n)


def _request_body(args: tuple[Any, ...], kwargs: dict[str, Any]):
    body = kwargs.get("body")
    if body is not None:
        return body
    for arg in args:
        if hasattr(arg, "messages") and hasattr(arg, "shown_cars"):
            return arg
    return None


def _latest_user_text(body) -> str:
    if body is None:
        return ""
    for message in reversed(list(getattr(body, "messages", None) or [])):
        role = getattr(message, "role", None)
        content = getattr(message, "content", None)
        if isinstance(message, dict):
            role = message.get("role")
            content = message.get("content")
        if str(role or "").lower() == "user":
            return str(content or "").strip()
    return ""


def _should_answer_as_followup(body) -> bool:
    """Visible cars + no explicit criteria change => answer, don't rerank."""
    if body is None or not (getattr(body, "shown_cars", None) or []):
        return False
    latest = _latest_user_text(body)
    if not latest:
        return False
    return not bool(_RERANK_FOLLOWUP_RE.search(latest))


def _shown_car_payload(cars) -> list[dict]:
    keep = (
        "make", "model", "year", "km", "price_usd", "monthly_est", "body_type",
        "transmission", "location", "value_delta_pct", "value_label", "caveat",
        "inspect", "anomalies", "provenance", "strategy_label", "best_for",
        "match_pct", "match_display", "value",
    )
    out = []
    for car in list(cars or [])[:12]:
        if not isinstance(car, dict):
            try:
                car = dict(car)
            except Exception:
                continue
        out.append({k: car.get(k) for k in keep if car.get(k) is not None})
    return out


def _answer_followup(body):
    """Direct post-shortlist answer grounded only in visible-car unit facts."""
    if not legacy._anthropic:
        return None

    msgs, frontend_meta = _clean_frontend_context_guarded(body.messages)
    facts = extract_explicit_facts(body.messages)
    system = _FOLLOWUP_SYSTEM_PROMPT + "\n\n" + GUARDRAIL_PROMPT

    if getattr(body, "country", None):
        system += (
            "\n\n# CONTEXTO CONFIRMADO POR EL SISTEMA\n"
            f"Pais/codigo seleccionado: {body.country}."
        )
    if frontend_meta:
        system += "\n" + "\n".join(frontend_meta)
    canonical = canonical_context_line(facts)
    if canonical and canonical not in system:
        system += "\n" + canonical

    cars = _shown_car_payload(getattr(body, "shown_cars", None) or [])
    system += (
        "\n\n# UNIDADES VISIBLES: DATOS AUTORITATIVOS DE ESTA CONVERSACION\n"
        + json.dumps(cars, ensure_ascii=False, separators=(",", ":"))
        + "\nNo inventes campos que no aparezcan aqui. Si el usuario pregunta un dato "
          "exacto ausente, di que no esta confirmado en los datos disponibles."
    )

    resp = legacy._anthropic.messages.create(
        model=legacy.CARLY_MODEL,
        max_tokens=900,
        system=system,
        messages=msgs,
    )
    reply = "".join(
        block.text for block in resp.content if getattr(block, "type", "") == "text"
    ).strip()
    # Follow-up mode never exposes internal structured protocol even if the model
    # tries to emit it.
    reply = re.sub(r"<PROFILE>.*?</PROFILE>", "", reply, flags=re.S | re.I).strip()
    reply = re.sub(r"<PROFILE>.*$", "", reply, flags=re.S | re.I).strip()
    if not reply:
        return None
    return {"phase": "conversation", "reply": reply}


def _patch_carly_route():
    """Add direct follow-up mode and preserve explicit zero-match behavior."""
    for route in getattr(legacy.app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        endpoint = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if endpoint is None or dependant is None:
            continue

        original_endpoint = endpoint

        def guarded_endpoint(*args: Any, __original=original_endpoint, **kwargs: Any):
            body = _request_body(args, kwargs)
            if _should_answer_as_followup(body):
                try:
                    direct = _answer_followup(body)
                    if direct:
                        return direct
                except Exception:
                    legacy.log.exception("Carly direct follow-up failed; falling back to legacy path")

            result = __original(*args, **kwargs)
            if (
                isinstance(result, dict)
                and result.get("phase") == "recommendation"
                and not result.get("recommendations")
            ):
                result["reply"] = (
                    "Con tus limites exactos no encontre una opcion suficientemente fuerte. "
                    "No voy a saltarme una restriccion que me diste. Si quieres abrir una, "
                    "te digo exactamente cual conviene flexibilizar y que opciones aparecen."
                )
            return result

        route.endpoint = guarded_endpoint
        dependant.call = guarded_endpoint
        break


ranking.passes_filters = _passes_filters_guarded
ranking.rank_cars = _rank_cars_guarded
legacy._clean_frontend_context = _clean_frontend_context_guarded
legacy.profile_from_extraction = _profile_from_extraction_guarded
legacy._carly_inventory = _carly_inventory_guarded
legacy.rank_cars = _rank_cars_guarded

profile_module.CARLY_SYSTEM_PROMPT = (
    profile_module.CARLY_SYSTEM_PROMPT + "\n\n" + GUARDRAIL_PROMPT
)
legacy.CARLY_SYSTEM_PROMPT = profile_module.CARLY_SYSTEM_PROMPT

_patch_carly_route()

app = legacy.app
