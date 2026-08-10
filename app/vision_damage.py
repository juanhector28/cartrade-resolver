"""
vision_damage.py — Analizador visual probabilístico de daño para Carly.

Objetivo:
  * detectar SEÑALES VISIBLES compatibles con daño por impacto/reparación;
  * nunca afirmar que un auto "está chocado" ni inferir historial/salvage;
  * analizar varias fotos del mismo listing en UNA sola llamada;
  * usar el resultado como una señal de Listing Intelligence, no como veredicto.

El resultado persistido sigue siendo compatible con el esquema actual:
  visible_damage_risk, damage_signals, vision_checked_at.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Iterable, Optional

# Umbral compartido conceptualmente con carly_ranking.VISUAL_DAMAGE_THRESHOLD.
DAMAGE_RISK_THRESHOLD = 0.50
MAX_VISION_PHOTOS = 4

_VISION_SYSTEM = """\
Revisas fotografías de un MISMO auto usado en venta. Tu tarea NO es diagnosticar
historial de accidentes. Solo debes estimar, a partir de evidencia visual concreta,
el riesgo de que las fotos muestren daño de carrocería compatible con impacto o una
reparación relevante que merece verificación presencial.

REGLAS:
- Nunca afirmes que el auto "está chocado", "es salvage", "tuvo accidente" o es
  "pérdida total". Una foto no permite concluir eso.
- Evalúa TODAS las imágenes juntas: pueden mostrar ángulos distintos del mismo auto.
- Prioriza señales de impacto/reparación: paneles o gaps claramente desalineados,
  piezas deformadas, parachoques/faros desprendidos o rotos, guardafangos hundidos,
  puertas/capó que no alinean, rueda/suspensión visiblemente fuera de posición,
  vidrio roto, piezas faltantes, diferencias de pintura fuertes/localizadas que sean
  compatibles con reparación.
- Rayones leves, pequeños dents de estacionamiento, suciedad, reflejos, sombras,
  stickers, diferencias de iluminación y mala calidad fotográfica NO bastan para
  elevar el riesgo de forma importante.
- No "premies" un auto por no ver daño. Si los ángulos son insuficientes, simplemente
  reporta cobertura baja. La ausencia de evidencia visible NO equivale a auto sano.
- Una señal clara en una sola foto puede justificar riesgo alto aunque la cobertura
  total sea incompleta.

CALIBRACIÓN DEL RIESGO:
- 0.00–0.15: no hay señal concreta visible en las fotos disponibles.
- 0.20–0.45: indicios débiles/ambiguos que pueden ser ángulo, luz o cosmética menor.
- 0.50–0.75: al menos una señal concreta compatible con daño/reparación relevante.
- 0.80–1.00: varias señales claras o daño visible fuerte en las fotos.

Responde EXCLUSIVAMENTE JSON:
{
  "visible_damage_risk": <0.0-1.0>,
  "coverage": "low"|"medium"|"high",
  "signals": ["señal visual concreta", ...],
  "note": "frase corta o null"
}
"""

_VISION_USER = (
    "Evalúa estas fotos del mismo vehículo. Devuelve solo el JSON calibrado. "
    "Si no puedes ver suficiente carrocería, usa coverage='low'; no inventes daño."
)


def _parse_json(text: str | None) -> Optional[dict]:
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    raw = m.group(0)
    for candidate in (raw, re.sub(r",\s*([}\]])", r"\1", raw)):
        try:
            data = json.loads(candidate)
            return data if isinstance(data, dict) else None
        except Exception:
            pass
    return None


def _normalize_photo_urls(value) -> list[str]:
    """Acepta list/tuple, JSON string o string delimitado y devuelve URLs únicas."""
    if not value:
        return []

    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                value = parsed
            else:
                value = [s]
        except Exception:
            # Compatibilidad con scrapers que guardan fotos separadas por |.
            value = s.split("|") if "|" in s else [s]

    if not isinstance(value, (list, tuple)):
        value = [value]

    out, seen = [], set()
    for raw in value:
        if not isinstance(raw, str):
            continue
        url = raw.strip()
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def select_vision_photos(photos, primary_photo: str | None = None,
                         limit: int = MAX_VISION_PHOTOS) -> list[str]:
    """Elige hasta `limit` fotos repartidas por el set, preservando primary primero.

    Los marketplaces suelen ordenar frente/lateral/trasera/interior. Tomar solo las
    primeras N puede perder la trasera; muestrear posiciones repartidas mejora
    cobertura sin multiplicar llamadas al modelo.
    """
    limit = max(1, int(limit or 1))
    urls = _normalize_photo_urls(photos)
    primary = _normalize_photo_urls(primary_photo)

    if primary:
        p = primary[0]
        urls = [p] + [u for u in urls if u != p]

    if len(urls) <= limit:
        return urls
    if limit == 1:
        return urls[:1]

    # Primary/primera + muestras equidistantes hasta el final.
    idxs = [round(i * (len(urls) - 1) / (limit - 1)) for i in range(limit)]
    chosen = []
    for i in idxs:
        u = urls[i]
        if u not in chosen:
            chosen.append(u)
    # Redondeo puede duplicar índices en sets pequeños; rellena si hace falta.
    for u in urls:
        if len(chosen) >= limit:
            break
        if u not in chosen:
            chosen.append(u)
    return chosen[:limit]


def _sanitize_result(data: dict) -> Optional[dict]:
    risk = data.get("visible_damage_risk")
    try:
        risk = float(risk)
    except (TypeError, ValueError):
        return None
    risk = max(0.0, min(1.0, risk))

    coverage = str(data.get("coverage") or "low").lower().strip()
    if coverage not in {"low", "medium", "high"}:
        coverage = "low"

    signals = data.get("signals") or []
    if not isinstance(signals, list):
        signals = []
    signals = [str(s).strip()[:90] for s in signals if str(s).strip()][:6]

    note = data.get("note")
    note = str(note).strip()[:180] if note else None

    # Una respuesta sin señal concreta no debería disparar un riesgo >= umbral.
    # Es un guardrail contra outputs mal calibrados del modelo.
    if risk >= DAMAGE_RISK_THRESHOLD and not signals:
        risk = min(risk, DAMAGE_RISK_THRESHOLD - 0.01)

    return {
        "visible_damage_risk": round(risk, 3),
        "coverage": coverage,
        "signals": signals,
        "note": note,
    }


def analyze_listing_damage(photo_urls: Iterable[str], client,
                           model: str = "claude-sonnet-4-6") -> Optional[dict]:
    """Analiza varias fotos del mismo listing en una sola llamada.

    Nunca lanza excepciones: la visión es enriquecimiento best-effort y no debe
    tumbar ingestión, ranking ni chat.
    """
    photos = select_vision_photos(list(photo_urls or []), limit=MAX_VISION_PHOTOS)
    if not photos or client is None:
        return None

    content = [
        {"type": "image", "source": {"type": "url", "url": url}}
        for url in photos
    ]
    content.append({"type": "text", "text": _VISION_USER})

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=450,
            system=_VISION_SYSTEM,
            messages=[{"role": "user", "content": content}],
        )
        text = "".join(
            getattr(b, "text", "") for b in resp.content
            if getattr(b, "type", "") == "text"
        )
        data = _parse_json(text)
        return _sanitize_result(data) if data else None
    except Exception:
        return None


def analyze_photo_damage(photo_url, client, model="claude-sonnet-4-6"):
    """Backward-compatible wrapper para callers antiguos de una sola foto."""
    photos = select_vision_photos([], primary_photo=photo_url, limit=1)
    return analyze_listing_damage(photos, client, model)


def enrich_listing_vision(row, client, model="claude-sonnet-4-6"):
    """Devuelve columnas compatibles con el esquema actual de Supabase.

    Usa `photos` si existe y cae a `primary_photo`. `coverage`/`note` sirven para
    observabilidad interna, pero no se persisten para no exigir migración de DB.
    """
    photos = select_vision_photos(
        row.get("photos"),
        primary_photo=row.get("primary_photo"),
        limit=MAX_VISION_PHOTOS,
    )
    res = analyze_listing_damage(photos, client, model)
    if res is None:
        return None

    # Guardamos solo señales visuales reales. Coverage bajo no es "daño".
    return {
        "visible_damage_risk": res["visible_damage_risk"],
        "damage_signals": json.dumps(res["signals"], ensure_ascii=False),
        "vision_checked_at": datetime.now(timezone.utc).isoformat(),
    }
