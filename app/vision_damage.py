"""
vision_damage.py  —  Analizador visual de daño (comment 7)

Usa el modelo de vision de Anthropic sobre la foto del anuncio para estimar la
PROBABILIDAD de daño visible. Filosofia dura, no negociable:

  * NUNCA afirma que un carro "esta chocado". Devuelve un RIESGO 0..1 y señales.
  * El copy hacia el usuario siempre es "posible daño visible, requiere
    verificacion" — la certeza la da la inspeccion de CarTrade, no una foto.
  * Corre en BATCH (no en cada /carly/chat: seria lento y caro). Guarda el
    resultado en Supabase; listing_intelligence lo LEE de la columna.

Requiere: `anthropic` en requirements.txt y ANTHROPIC_API_KEY en el entorno
(el mismo cliente que ya usa /carly/chat). El modelo CARLY_MODEL
(claude-sonnet-4-6) soporta vision.
"""

import json
import re

# Umbral por defecto a partir del cual el riesgo se trata como anomalia.
DAMAGE_RISK_THRESHOLD = 0.5

_VISION_SYSTEM = """\
Eres un perito que revisa FOTOS de autos usados en venta. Tu unico trabajo es
estimar, SOLO por lo que se ve en la imagen, la PROBABILIDAD de que el vehiculo
tenga daño visible en carroceria. Reglas absolutas:

- JAMAS concluyas que el carro "esta chocado", "es salvage" o "es perdida
  total". Eso NO se puede afirmar desde una foto. Solo estimas un riesgo.
- Marca señales concretas y visibles: paneles desalineados o deformados, puertas
  o capó que no cierran parejo, guardafangos abollados, faros/calaveras rotos o
  empañados, parachoques desprendido, pintura dispareja o masilla, oxido
  estructural, piezas faltantes, rueda/suspension colapsada, vidrios rotos.
- Diferencia daño de simple suciedad, reflejos, sombras o una foto de mala
  calidad: esos NO son daño. Ante la duda, riesgo BAJO.
- Si la foto no permite juzgar (muy lejana, oscura, solo interior, solo tablero),
  devuelve risk bajo y note null: no inventes daño que no ves.

Responde EXCLUSIVAMENTE con un JSON, sin texto extra, con esta forma:
{"visible_damage_risk": <0.0-1.0>, "signals": ["<señal corta>", ...],
 "note": "<una frase o null>"}
"""

_VISION_USER = (
    "Estima el riesgo de daño visible en carroceria de este auto en venta. "
    "Recuerda: no afirmas que esta chocado, solo estimas la probabilidad y "
    "listas señales concretas. Devuelve solo el JSON."
)


def _parse_json(text):
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    raw = m.group(0)
    try:
        return json.loads(raw)
    except Exception:
        try:
            return json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
        except Exception:
            return None


def analyze_photo_damage(photo_url, client, model="claude-sonnet-4-6"):
    """Devuelve {"visible_damage_risk": float 0..1, "signals": [...],
    "note": str|None} o None si no se pudo evaluar (sin foto, sin cliente,
    error de red o respuesta ilegible). NUNCA lanza: el enriquecimiento no
    debe caerse por una foto."""
    if not photo_url or client is None:
        return None
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=350,
            system=_VISION_SYSTEM,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "url", "url": photo_url}},
                    {"type": "text", "text": _VISION_USER},
                ],
            }],
        )
        text = "".join(getattr(b, "text", "") for b in resp.content
                        if getattr(b, "type", "") == "text")
        data = _parse_json(text)
        if not isinstance(data, dict):
            return None
        risk = data.get("visible_damage_risk")
        try:
            risk = float(risk)
        except (TypeError, ValueError):
            return None
        risk = max(0.0, min(1.0, risk))
        signals = data.get("signals") or []
        if not isinstance(signals, list):
            signals = []
        signals = [str(s)[:60] for s in signals][:6]
        note = data.get("note")
        note = str(note)[:160] if note else None
        return {"visible_damage_risk": round(risk, 3), "signals": signals, "note": note}
    except Exception:
        return None


def enrich_listing_vision(row, client, model="claude-sonnet-4-6"):
    """Toma una fila (dict) con primary_photo y devuelve el dict de update para
    Supabase: {visible_damage_risk, damage_signals, vision_checked_at}. Devuelve
    None si no hubo foto/evaluacion (para no escribir basura)."""
    from datetime import datetime, timezone
    res = analyze_photo_damage(row.get("primary_photo"), client, model)
    if res is None:
        return None
    return {
        "visible_damage_risk": res["visible_damage_risk"],
        "damage_signals": json.dumps(res["signals"], ensure_ascii=False),
        "vision_checked_at": datetime.now(timezone.utc).isoformat(),
    }
