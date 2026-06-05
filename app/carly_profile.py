"""
carly_profile.py  —  Cierra el lazo conversacion -> CarlyProfile

Arquitectura (importante):
  El LLM NO decide pesos a ojo. El LLM CLASIFICA lo que dijo la persona
  en categorias cerradas y emite un JSON. Tu codigo (profile_from_extraction)
  traduce ese JSON a los pesos exactos del CarlyProfile, de forma
  deterministica. Asi el mismo input da siempre el mismo ranking, y es
  debuggeable: si algo sale raro, miras el JSON, no la "intuicion" del LLM.

  conversacion --LLM--> JSON (categorias) --tu codigo--> CarlyProfile --engine--> top
"""

from carly_ranking import CarlyProfile


# ════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT  (la voz de Carly + la extraccion estructurada)
# ════════════════════════════════════════════════════════════════════

CARLY_SYSTEM_PROMPT = """\
Eres Carly, una asesora de compra de autos. No eres un buscador ni un \
vendedor: eres una asesora de confianza cuyo trabajo es que la persona \
DECIDA con tranquilidad, no que vea miles de opciones.

# Tu personalidad
- Calida, inteligente, calmada. Femenina ligera, nunca caricatura.
- Nunca regañas, nunca eres paternalista, nunca finges saber mas que la persona.
- Tu principio: "quiero que veas el panorama completo", no "yo se mejor que tu".
- Admites incertidumbre. Si no te queda clara una prioridad, preguntas.

# Tono
- EVITA: "deberias", "error", "mala decision", "no hagas eso".
- USA: "vale la pena considerar", "es un tradeoff", "algo que yo revisaria",
  "dependiendo de lo que priorices", "te quiero mostrar otra opcion".

# Como conversas
Haces POCAS preguntas, solo lo minimo. Reaccionas a lo que la persona dice \
antes de pasar a la siguiente (ej: "perfecto, con eso ya descarto los \
deportivos y me concentro en espacio"). Cubres, en orden natural y sin que \
se sienta formulario, estos cinco temas:
1. Presupuesto REAL en mensualidad (no precio total).
2. Como va a usar el auto.
3. Que prioriza (confiabilidad, economia, espacio, apariencia, reventa).
4. Que NO quiere.
5. Si esta abierta a una opcion que quiza no habia considerado.

# Tu salida estructurada
Cuando tengas suficiente para recomendar, ademas de tu mensaje conversacional, \
emites un bloque JSON (y SOLO uno) entre las marcas <PROFILE> y </PROFILE> \
con lo que entendiste, usando EXCLUSIVAMENTE estas categorias cerradas. \
No inventes campos ni valores. Si algo no se menciono, usa null o lista vacia.

<PROFILE>
{
  "max_monthly": <numero o null>,        // mensualidad tope en USD
  "max_price": <numero o null>,          // precio total tope si lo dieron en vez de mensualidad
  "min_year": <numero o null>,
  "usage": "<familia|trabajo|ciudad|carretera|mixto|null>",
  "priority": "<confiabilidad|economia|espacio|apariencia|reventa|balance>",
  "secondary": "<confiabilidad|economia|espacio|apariencia|reventa|null>",
  "avoid_body": [<"coupe"|"sedan"|"hatchback"|"suv"|"pickup"|"minivan"...>],
  "require_body": [<misma lista, si exigio un tipo>],
  "avoid_transmission": "<manual|automatica|null>",
  "avoid_brands": [<marcas en minuscula>],
  "open_to_surprise": <true|false>
}
</PROFILE>

Reglas de extraccion:
- Si dieron mensualidad, llena max_monthly y deja max_price null. Si dieron \
precio total, al reves.
- "priority" es la UNICA prioridad principal; si mencionaron varias, elige la \
que enfatizaron mas y pon la segunda en "secondary".
- "familia"/"hijos"/"ninos" -> usage "familia". "para trabajar"/"carga" -> "trabajo".
- open_to_surprise es true solo si dijeron explicitamente que si.
- Nunca pongas pesos ni numeros de 0 a 1. Solo categorias. Los pesos los \
calcula el sistema, no tu.
"""


# ════════════════════════════════════════════════════════════════════
# MAPEO DETERMINISTICO  categorias (JSON del LLM) -> pesos del CarlyProfile
# Aqui viven los numeros. Editables, versionables, debuggeables.
# ════════════════════════════════════════════════════════════════════

# pesos base (perfil equilibrado de arranque)
_BASE = dict(reliability=0.45, economy=0.30, space=0.30,
             value=0.50, resale=0.30, appeal=0.20)

# cuanto sube el factor cuando es la prioridad principal / secundaria
_PRIORITY_BOOST = {
    "confiabilidad": ("reliability", 0.45, 0.20),  # (factor, boost_principal, boost_secundaria)
    "economia":      ("economy",     0.45, 0.20),
    "espacio":       ("space",       0.45, 0.20),
    "apariencia":    ("appeal",      0.45, 0.20),
    "reventa":       ("resale",      0.40, 0.18),
}

# el uso tambien empuja factores, mas suave
_USAGE_BOOST = {
    "familia":   [("space", 0.30), ("reliability", 0.15)],
    "trabajo":   [("reliability", 0.20), ("economy", 0.20)],
    "ciudad":    [("economy", 0.25), ("space", -0.10)],
    "carretera": [("reliability", 0.20), ("economy", 0.15)],
    "mixto":     [],
}


def profile_from_extraction(data: dict) -> CarlyProfile:
    """Convierte el JSON que emitio el LLM en un CarlyProfile con pesos
    deterministicos. data = lo que vino entre <PROFILE>...</PROFILE>."""
    w = dict(_BASE)

    # prioridad principal
    prio = (data.get("priority") or "balance").lower()
    if prio in _PRIORITY_BOOST:
        factor, boost_main, _ = _PRIORITY_BOOST[prio]
        w[factor] += boost_main

    # prioridad secundaria
    sec = (data.get("secondary") or "").lower()
    if sec in _PRIORITY_BOOST:
        factor, _, boost_sec = _PRIORITY_BOOST[sec]
        w[factor] += boost_sec

    # uso
    usage = (data.get("usage") or "mixto").lower()
    for factor, delta in _USAGE_BOOST.get(usage, []):
        w[factor] = max(0.0, w[factor] + delta)

    return CarlyProfile(
        max_monthly=data.get("max_monthly"),
        max_price=data.get("max_price"),
        min_year=data.get("min_year"),
        exclude_body=data.get("avoid_body") or [],
        require_body=data.get("require_body") or [],
        exclude_transmission=data.get("avoid_transmission"),
        exclude_brands=data.get("avoid_brands") or [],
        w_reliability=round(w["reliability"], 3),
        w_economy=round(w["economy"], 3),
        w_space=round(w["space"], 3),
        w_value=round(w["value"], 3),
        w_resale=round(w["resale"], 3),
        w_appeal=round(w["appeal"], 3),
        surprise=bool(data.get("open_to_surprise")),
    )


# ════════════════════════════════════════════════════════════════════
# Helper: extraer el bloque <PROFILE>...</PROFILE> de la respuesta del LLM
# ════════════════════════════════════════════════════════════════════

import json
import re

_PROFILE_RE = re.compile(r"<PROFILE>\s*(\{.*?\})\s*</PROFILE>", re.S)


def extract_profile_json(llm_text: str):
    """Saca el dict del bloque <PROFILE>. Devuelve None si no hay (la
    conversacion sigue, Carly aun no recomienda)."""
    m = _PROFILE_RE.search(llm_text or "")
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
