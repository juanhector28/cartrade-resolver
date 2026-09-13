"""Carly v52: block unstated daily-km claims + strengthen vehicle-detail advice.

This layer keeps v51 routing but adds two demo-critical truth guarantees:
1) Carly may not assert a buyer's daily driving distance unless the buyer wrote it.
2) Vehicle-detail follow-ups explain the actual comparative fit instead of falling
   back to generic 'price and availability' language for Mazda CX-family SUVs.
"""
from __future__ import annotations

import logging
import re
from functools import wraps
from typing import Any

from . import main_v14 as v14
from . import main_v51 as v51
from .carly_vehicle_brief import model_guidance as _base_model_guidance

app = v51.app
log = logging.getLogger("carly.v52")

_DAILY_KM_BUYER_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:km|kms|kil[oó]metros)\s*(?:diarios?|al\s+d[ií]a|por\s+d[ií]a)\b",
    re.I,
)
_DAILY_KM_REPLY_RE = re.compile(
    r"(?:[,;]\s*)?(?:y\s+)?(?:ya\s+)?(?:s[eé]\s+que\s+)?(?:t[uú]\s+)?(?:manejas?|recorres?|haces?)\s+"
    r"(?:unos?\s+|aprox(?:imadamente)?\s+)?\d+(?:[.,]\d+)?\s*(?:km|kms|kil[oó]metros)\s*"
    r"(?:diarios?|al\s+d[ií]a|por\s+d[ií]a)(?:\s+en\s+[^.?!,;]+)?",
    re.I,
)


def _buyer_text(body: Any) -> str:
    chunks: list[str] = []
    for msg in list(getattr(body, "messages", None) or []):
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
        if role == "user" and content:
            chunks.append(str(content))
    return "\n".join(chunks)


def _strip_unstated_daily_km(reply: str, buyer_text: str) -> str:
    """Remove any daily-km assertion unless it is grounded in a buyer message."""
    if not reply or _DAILY_KM_BUYER_RE.search(buyer_text or ""):
        return reply
    cleaned = _DAILY_KM_REPLY_RE.sub("", reply)
    cleaned = re.sub(r"\s+([,.;:?!])", r"\1", cleaned)
    cleaned = re.sub(r"([,;])\s*([,;])", r"\1", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    cleaned = re.sub(r"\b(?:y|pero)\s+(?=[¿?])", "", cleaned, flags=re.I)
    return cleaned


def _cx_guidance(car: dict) -> dict:
    blob = " ".join(str(car.get(k) or "") for k in ("make", "model")).lower()
    if "mazda" in blob and "cx-30" in blob.replace("cx 30", "cx-30"):
        return {
            "pros": "su tamaño compacto, cuota y maniobrabilidad lo hacen especialmente lógico para trabajo diario y llevar a los niños al colegio sin subir al tamaño de un CX-5",
            "cons": "frente a un CX-5 sacrifica espacio trasero y capacidad de carga; si sillas, equipaje o viajes familiares pesan mucho, ese es el trade-off que más revisaría",
        }
    if "mazda" in blob and "cx-5" in blob.replace("cx 5", "cx-5"):
        return {
            "pros": "aporta más espacio trasero y de carga para uso familiar, manteniendo el formato SUV que estás buscando",
            "cons": "ese espacio extra normalmente viene con más tamaño y puede costar más en cuota o precio que un CX-30 comparable",
        }
    return _base_model_guidance(car)


# main_v14 resolves this module global at request time.
v14.model_guidance = _cx_guidance


def _better_relative_sentence(focus: dict, ranked: list[dict], pos: int | None) -> str:
    if not ranked or pos is None:
        return "Lo mantendría como candidato, pero todavía tiene que ganarse la recomendación con la verificación de la unidad."
    if pos != 1:
        leader = ranked[0]
        return f"Hoy lo tengo #{pos}; pondría primero al {v14._name(leader)} por mejor ajuste global con los datos disponibles."
    if len(ranked) == 1:
        return "Es mi mejor candidato visible, aunque todavía necesito una alternativa comparable y la verificación de la unidad para llamarlo favorito."

    rival = ranked[1]
    bits: list[str] = []
    fm = v14._num(focus.get("monthly_est")); rm = v14._num(rival.get("monthly_est"))
    fk = v14._num(focus.get("km")); rk = v14._num(rival.get("km"))
    fy = v14._num(focus.get("year")); ry = v14._num(rival.get("year"))
    fp = v14._num(focus.get("price_usd")); rp = v14._num(rival.get("price_usd"))
    if fm is not None and rm is not None and abs(fm-rm) >= 5:
        bits.append(f"cuota ~${fm:,.0f}/mes frente a ~${rm:,.0f}/mes")
    if fk is not None and rk is not None and abs(fk-rk) >= 5000:
        bits.append(f"{fk:,.0f} km frente a {rk:,.0f} km")
    if fy is not None and ry is not None and fy != ry:
        bits.append(f"{int(fy)} frente a {int(ry)}")
    if fp is not None and rp is not None and abs(fp-rp) >= 500:
        bits.append(f"precio ${fp:,.0f} frente a ${rp:,.0f}")
    evidence = "; ".join(bits[:2])
    if evidence:
        return f"Con los datos visibles hoy lo tengo primero frente al {v14._name(rival)} por {evidence}. Esa ventaja todavía depende de verificar la unidad."
    return f"Con los datos visibles hoy lo tengo primero frente al {v14._name(rival)} por mejor ajuste global; la diferencia todavía depende de verificar ambas unidades."


v14._relative_sentence = _better_relative_sentence


def _patch_truth_guard() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        prior = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if prior is None or dependant is None or getattr(prior, "_carly_v52_truth_guard", False):
            continue

        @wraps(prior)
        def endpoint(*args: Any, __prior=prior, **kwargs: Any):
            body = v51.v50.v47.commercial._request_body(args, kwargs)
            result = __prior(*args, **kwargs)
            if isinstance(result, dict) and isinstance(result.get("reply"), str):
                original = result["reply"]
                result["reply"] = _strip_unstated_daily_km(original, _buyer_text(body))
                if result["reply"] != original:
                    result["buyer_truth_guard"] = "daily_km_removed_v52"
                    log.warning("CARLY_V52 removed unstated daily-km claim")
            return result

        endpoint._carly_v52_truth_guard = True
        endpoint._carly_v52_prior = prior
        route.endpoint = endpoint
        dependant.call = endpoint
        break


_patch_truth_guard()
log.warning("CARLY_V52 installed daily_km_truth=true vehicle_brief_specificity=true")
