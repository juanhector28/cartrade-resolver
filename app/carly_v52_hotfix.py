"""Carly v52 hotfix: buyer-only opening truth and useful vehicle detail."""
from __future__ import annotations

import logging
import re
from functools import wraps
from typing import Any

from . import main_v14 as v14
from . import main_v50 as v50

log = logging.getLogger("carly.v52")


def _role(m: Any) -> str:
    return str((m.get("role") if isinstance(m, dict) else getattr(m, "role", "")) or "").lower()


def _content(m: Any) -> str:
    return str((m.get("content") if isinstance(m, dict) else getattr(m, "content", "")) or "")


def _messages(body: Any) -> list[Any]:
    if body is None:
        return []
    return list((body.get("messages") if isinstance(body, dict) else getattr(body, "messages", None)) or [])


def _shown(body: Any) -> list[dict]:
    if body is None:
        return []
    return list((body.get("shown_cars") if isinstance(body, dict) else getattr(body, "shown_cars", None)) or [])


def _country(body: Any) -> str:
    if body is None:
        return ""
    return str((body.get("country") if isinstance(body, dict) else getattr(body, "country", "")) or "").lower().strip()


_SEARCH_RE = re.compile(r"\b(?:busco|quiero|necesito|estoy\s+buscando|ando\s+buscando)\b", re.I)
_RANGE_RE = re.compile(r"\b(?:entre|de)\s*(?:usd\s*)?\$?\s*([0-9][0-9.,]*)\s*(?:y|a|hasta|-|–|—)\s*(?:usd\s*)?\$?\s*([0-9][0-9.,]*)", re.I)


def _price_range(text: str) -> tuple[float, float] | None:
    match = _RANGE_RE.search(text or "")
    if not match:
        return None
    try:
        lo = float(v50.fastpath._parse_number(match.group(1)))
        hi = float(v50.fastpath._parse_number(match.group(2)))
    except Exception:
        return None
    lo, hi = sorted((lo, hi))
    return (lo, hi) if 1000 <= lo <= hi <= 1_000_000 else None


def _body_label(value: str | None) -> str:
    return {"suv": "SUV", "pickup": "pickup", "sedan": "sedán", "hatchback": "hatchback"}.get(v14._norm(value), str(value or "carro"))


def opening_search_response(body: Any) -> dict | None:
    """First-turn search response from buyer text only. No profile memory or LLM."""
    if body is None or _shown(body):
        return None
    rows = _messages(body)
    users = [m for m in rows if _role(m) == "user"]
    if len(users) != 1 or any(_role(m) == "assistant" for m in rows):
        return None
    text = _content(users[0]).strip()
    if not text or not _SEARCH_RE.search(text):
        return None
    brand = v50._direct_requested_brand(text)
    body_req = v50.v46._explicit_body(text)
    if not brand and not body_req:
        return None
    subject = " ".join(x for x in (str(brand or "").strip(), _body_label(str(body_req)) if body_req else "") if x)
    parts = [f"Entendido: buscas un {subject}"]
    rng = _price_range(text)
    if rng:
        parts.append(f"entre USD {rng[0]:,.0f} y {rng[1]:,.0f}")
    country_name = {"gt": "Guatemala", "sv": "El Salvador", "cr": "Costa Rica", "pa": "Panamá"}.get(_country(body))
    if country_name:
        parts.append(f"en {country_name}")
    return {
        "phase": "conversation",
        "reply": " ".join(parts) + ". ¿Para qué lo vas a usar principalmente: trabajo diario, transporte familiar, negocio o algo más?",
        "token_path": "deterministic_opening_truth_v52",
        "llm_calls": 0,
    }


def _buyer_blob(body: Any) -> str:
    return "\n".join(_content(m) for m in _messages(body) if _role(m) == "user")


def _mission(body: Any) -> str:
    n = v14._norm(_buyer_blob(body))
    children = any(x in n for x in ("hijo", "hijos", "colegio", "escuela", "ninos"))
    work = any(x in n for x in ("trabajo", "oficina", "trabajar"))
    if children and work:
        return "tu uso diario de trabajo y llevar a tus hijos al colegio"
    if children:
        return "tu uso familiar y los trayectos con tus hijos"
    if work:
        return "tu uso diario de trabajo"
    return "tu búsqueda"


def _monthly_ceiling(body: Any, profile: Any) -> float | None:
    try:
        value = v50.v28._extract_monthly(body)
        if value is not None:
            return float(value)
    except Exception:
        pass
    try:
        value = profile.get("max_monthly") if isinstance(profile, dict) else getattr(profile, "max_monthly", None)
        return float(value) if value is not None else None
    except Exception:
        return None


def _model_guidance(car: dict) -> tuple[str, str]:
    model = v14._norm(car.get("model"))
    if model in {"cx 30", "cx30"}:
        return (
            "El CX-30 es el SUV más compacto de esta comparación: ayuda en tráfico, maniobras y parqueo sin salirte del formato SUV.",
            "El costo de ser más compacto es espacio trasero y de carga frente a un CX-5; si la diferencia de cuota es pequeña, ese espacio puede valer más para uso familiar.",
        )
    if model in {"cx 5", "cx5"}:
        return (
            "El CX-5 compra más espacio y practicidad familiar que un CX-30, útil con niños y carga cotidiana.",
            "Ese espacio viene con más tamaño; si el uso es muy urbano, el CX-30 puede ser más cómodo de mover y estacionar.",
        )
    guidance = v14.model_guidance(car)
    pro = str(guidance.get("pros") or "").strip().capitalize()
    con = str(guidance.get("cons") or "").strip().capitalize()
    if pro and not pro.endswith("."):
        pro += "."
    if con and not con.endswith("."):
        con += "."
    return pro, con


def _rival(focus: dict, ranked: list[dict]) -> dict | None:
    return next((car for car in ranked if v14._key(car) != v14._key(focus)), None)


def _comparison(focus: dict, rival: dict | None) -> str:
    if not rival:
        return ""
    bits: list[str] = []
    fm = v14._num(focus.get("monthly_est")); rm = v14._num(rival.get("monthly_est"))
    fk = v14._num(focus.get("km")); rk = v14._num(rival.get("km"))
    fy = v14._num(focus.get("year")); ry = v14._num(rival.get("year"))
    fp = v14._num(focus.get("price_usd")); rp = v14._num(rival.get("price_usd"))
    if fm is not None and rm is not None and abs(fm-rm) >= 5:
        bits.append(f"~${abs(fm-rm):,.0f}/mes {'menos' if fm < rm else 'más'}")
    if fk is not None and rk is not None and abs(fk-rk) >= 1500:
        bits.append(f"{abs(fk-rk):,.0f} km {'menos' if fk < rk else 'más'} reportados")
    if fy is not None and ry is not None and fy != ry:
        delta = abs(int(fy-ry))
        bits.append(f"{delta} año{'s' if delta != 1 else ''} {'más reciente' if fy > ry else 'más antiguo'}")
    if not bits and fp is not None and rp is not None and abs(fp-rp) >= 500:
        bits.append(f"USD {abs(fp-rp):,.0f} {'menos' if fp < rp else 'más'} de precio publicado")
    if not bits:
        return f"Frente al {v14._name(rival)}, todavía no veo una ventaja numérica clara; decidirían espacio, condición e inspección."
    return f"Frente al {v14._name(rival)}, esta unidad tiene {', '.join(bits[:2])}."


def _risk(focus: dict, rival: dict | None, model_tradeoff: str) -> str:
    parts = [model_tradeoff] if model_tradeoff else []
    km = v14._num(focus.get("km")); year = v14._num(focus.get("year"))
    if km is not None and year is not None and year >= 2022 and 15000 <= km <= 60000:
        parts.append(f"Los {km:,.0f} km reportados no me asustan por sí solos, pero sí quiero mantenimiento consistente con ese uso.")
    if rival is not None and v14._norm(focus.get("model")) in {"cx 30", "cx30"} and v14._norm(rival.get("model")) in {"cx 5", "cx5"}:
        fm = v14._num(focus.get("monthly_est")); rm = v14._num(rival.get("monthly_est"))
        if fm is not None and rm is not None and 0 <= rm-fm <= 75:
            parts.append(f"Si el CX-5 cuesta sólo ~${rm-fm:,.0f}/mes más, probaría ambos con los niños: el espacio extra puede justificar la diferencia.")
    return " ".join(parts[:2])


def advisor_brief(body: Any) -> dict | None:
    if body is None:
        return None
    latest = v14._latest(body)
    n = v14._norm(latest)
    if not any(x in n for x in ("cuentame", "por que", "recomiendas", "preocupa", "preocuparme", "validar", "revisar", "que tal", "como lo ves", "que opinas")):
        return None
    visible = v14._unique(_shown(body))
    if not visible:
        return None
    focus = v14._focus(latest, visible)
    if focus is None:
        return None
    profile = v14._profile(body, visible)
    ranked = sorted(visible, key=lambda car: v14.advisor_score(car, profile), reverse=True)
    rival = _rival(focus, ranked)
    ceiling = _monthly_ceiling(body, profile)
    year = v14._num(focus.get("year")); km = v14._num(focus.get("km")); monthly = v14._num(focus.get("monthly_est")); price = v14._num(focus.get("price_usd"))
    facts: list[str] = []
    if year is not None:
        facts.append(str(int(year)))
    if km is not None:
        facts.append(f"{km:,.0f} km reportados")
    if monthly is not None:
        facts.append(f"~${monthly:,.0f}/mes")
    elif price is not None:
        facts.append(f"USD {price:,.0f} publicados")
    reading = f"Sí lo mantendría como finalista para {_mission(body)}. "
    if facts:
        reading += "La ficha visible hoy dice " + ", ".join(facts[:3]) + ". "
    if ceiling is not None and monthly is not None:
        margin = ceiling-monthly
        reading += (f"Con tu tope de ~${ceiling:,.0f}/mes, deja ~${margin:,.0f}/mes de margen. " if margin >= 0 else f"Supera tu tope de ~${ceiling:,.0f}/mes por ~${abs(margin):,.0f}/mes. ")
    reading += "No lo llamaría la mejor compra hasta validar esta unidad concreta."
    model_reason, model_tradeoff = _model_guidance(focus)
    why = " ".join(x for x in (model_reason, _comparison(focus, rival)) if x)
    risk = _risk(focus, rival, model_tradeoff) or model_tradeoff or "La unidad todavía necesita evidencia de condición e historial."
    checks = "; ".join(v14._specific_checks(focus)[:3])
    sections = [
        {"title": "Mi lectura", "text": reading},
        {"title": "Por qué sí", "text": why},
        {"title": "Qué me preocupa", "text": risk},
        {"title": "Antes de comprar", "text": f"Validaría {checks}."},
    ]
    return {
        "phase": "conversation",
        "reply": "\n\n".join(f"**{s['title'].upper()}**\n{s['text']}" for s in sections),
        "response_sections": sections,
        "token_path": "deterministic_vehicle_brief_v52",
        "advisor_mode": "comparative_vehicle_brief_v52",
        "llm_calls": 0,
        "clear_recommendations": False,
    }


def install(app: Any) -> None:
    """Install over the already-composed v51 app without changing its entrypoint."""
    v14._advisor_brief = advisor_brief
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        prior = getattr(route, "endpoint", None); dependant = getattr(route, "dependant", None)
        if prior is None or dependant is None or getattr(prior, "_carly_v52_opening_truth", False):
            continue
        @wraps(prior)
        def endpoint(*args: Any, __prior=prior, **kwargs: Any):
            body = v50.v47.commercial._request_body(args, kwargs)
            direct = opening_search_response(body)
            return direct if direct is not None else __prior(*args, **kwargs)
        endpoint._carly_v52_opening_truth = True
        endpoint._carly_v52_prior = prior
        route.endpoint = endpoint
        dependant.call = endpoint
        break
    log.warning("CARLY_V52_HOTFIX installed opening_truth=true useful_vehicle_brief=true")
