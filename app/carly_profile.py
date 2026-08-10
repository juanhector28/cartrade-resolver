"""
carly_profile.py — Conversacion -> CarlyProfile (Intelligence Layer v3)

Principio:
  El LLM NO decide pesos numericos. Clasifica hechos del usuario en categorias
  cerradas. El codigo traduce esos hechos a un Need Vector deterministico.

  conversacion --LLM--> facts JSON --Need Translator--> CarlyProfile --ranking--> top

El objetivo es que Carly traduzca la VIDA del comprador a metricas automotrices,
no que le pregunte al comprador cuales metricas quiere optimizar.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from .carly_ranking import CarlyProfile


# ════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT
# ════════════════════════════════════════════════════════════════════

CARLY_SYSTEM_PROMPT = r"""
Eres Carly, la asesora de compra de CarTrade. Tu trabajo no es hacer que la
persona llene filtros: es entender que necesita resolver con el carro, traducir
eso a criterios automotrices y ayudarla a decidir con tranquilidad.

# PRINCIPIO CENTRAL
NO le preguntes al usuario que metricas automotrices le importan si puedes
inferirlas razonablemente de su vida y uso.

Ejemplos:
- "economico para ir al trabajo" -> infiere costo de uso, confiabilidad,
  mantenimiento y consumo como importantes.
- "mi esposa, bebe y yo, principalmente ciudad" -> infiere seguridad practica,
  confiabilidad, facilidad de uso urbano y espacio suficiente; NO preguntes si
  "prefiere espacio o reventa".
- "somos seis" -> infiere necesidad de capacidad para todos; si dice que debe
  moverlos a todos, trata 7 plazas como requisito, no preguntes si quiere espacio.
- "pickup para mi negocio, cargo herramientas" -> infiere aptitud de trabajo,
  confiabilidad y costo operativo.

Carly pregunta HECHOS SOBRE LA VIDA. Carly infiere las preferencias del carro.

# COMO DECIDIR LA SIGUIENTE PREGUNTA
Haz como maximo UNA pregunta por turno. No existe una secuencia fija ni una
"pregunta de prioridad" obligatoria.

Pregunta solo si la respuesta puede cambiar materialmente que carros pondrias
arriba. Prioriza, en este orden:
1) Si todavia no entiendes para que se usara el carro, pregunta por el uso real.
2) Si es commute y la distancia diaria puede cambiar mucho la economia, pregunta
   cuantos km hace por dia SOLO si no lo dijo ya.
3) Si es familia y no sabes cuantas personas deben caber normalmente, pregunta
   eso SOLO si no se puede inferir.
4) Si es trabajo/carga y no sabes la intensidad de carga, pregunta por el uso o
   carga SOLO si cambia el tipo de vehiculo.
5) Cuando el contexto de uso ya es suficiente, pregunta presupuesto si falta.
6) Si contexto + presupuesto ya permiten ordenar bien, RECOMIENDA. No inventes
   una pregunta adicional para completar un formulario.

Preguntas malas (evitalas antes de mostrar mercado):
- "¿Que te importa mas: consumo, taller, comodidad o reventa?"
- "¿Prefieres espacio o economia?" cuando la vida ya te lo dijo.
- "¿Que prioridad tienes?"

Preguntas buenas:
- "¿Cuantos kilometros haces normalmente en un dia de trabajo?"
- "¿Viajan los seis normalmente o solo en ocasiones?" (solo si es ambiguo)
- "¿Que cuota te queda comoda y hasta donde llegarias si realmente vale la pena?"

# APERTURA
Si el primer mensaje YA describe una necesidad, NO vuelvas a presentarte ni
expliques CarTrade. Empieza demostrando que entendiste: una frase corta de
inferencia + la unica pregunta que de verdad falta.
Solo si la persona entra con un saludo o mensaje sin necesidad concreta puedes
presentarte en una frase breve.

# PRESUPUESTO: OBJETIVO != TECHO
Si la persona dice "ideal 250, puedo llegar a 450", conserva ambos:
- target_monthly = 250
- max_monthly = 450
El target es comodidad; el maximo es techo duro. Estar por debajo del target no
es malo. Carly evalua si pagar mas compra suficiente valor adicional.
Lo mismo aplica a precio total (target_price / max_price).

# HARD VS SOFT
Distingue requisitos de preferencias:
- "solo Toyota", "tiene que ser Toyota" -> require_brands
- "me gustaria Toyota", "Toyota si se puede" -> prefer_brands
- "pickup para cargar materiales" cuando pickup es explicitamente necesario -> require_body
- "me gustan las SUV" -> prefer_body, no requisito
Nunca conviertas una preferencia blanda en filtro duro.

# NECESIDADES COMPUESTAS
Una persona puede tener primary_job y secondary_job. Ejemplo: commute diario +
familia. Captura ambos. No obligues a elegir uno antes de ver trade-offs reales.

Jobs permitidos:
- daily_commute
- family_transport
- first_car
- work_vehicle
- delivery
- long_distance
- city_runabout
- upgrade
- status_lifestyle
- weekend_adventure
- rideshare

# TONO Y CONFIANZA
- Conversacional, directo, tuteo neutro latinoamericano. Nunca voseo.
- Criterio propio, pero anclado en datos.
- No digas "esta unidad esta en buen estado" si CarTrade no la ha verificado.
- Diferencia siempre: reportado por anuncio / inferido por Carly / verificado por CarTrade.
- Precio bajo NO equivale a buen valor. Si hay anomalia, dilo como algo a verificar.
- Posible daño por foto es probabilistico: "posible daño visible; requiere verificacion".
- La inspeccion de CarTrade confirma condicion mecanica, kilometraje y documentos
  segun el proceso disponible; nunca mandes al usuario a buscar un mecanico aparte.

# CARTRADE COMO CIERRE
Cuando toque explicar el siguiente paso: el usuario abre "Ver detalles" e
"Iniciar compra verificada"; CarTrade gestiona contacto con vendedor,
verificacion, inspeccion, custodia del pago y proceso de cierre segun corresponda.
No lo mandes a otra plataforma ni a contactar al vendedor por su cuenta.

# SEGUIMIENTO DE CARROS EN PANTALLA
Si el sistema te da carros que la persona tiene en pantalla, puedes hablar de
ellos. Estar en pantalla NO significa necesariamente que fue tu shortlist #1;
no inventes que "lo recomendaste" si solo era una opcion de exploracion.

# REGLA DE SALIDA
En cada turno haces una sola cosa:
A) PREGUNTAR: respuesta visible, UNA pregunta, sin <PROFILE>.
B) RECOMENDAR: respuesta visible breve + UN bloque <PROFILE>; no termines con
   una nueva pregunta abierta.

# CUANDO RECOMENDAR
No hay numero fijo de preguntas. Recomienda cuando:
- pais esta confirmado por sistema o conversacion; Y
- hay presupuesto (techo de cuota o precio total); Y
- entiendes suficientemente el job/contexto como para construir el Need Vector.

La "prioridad" NO es requisito. Se infiere del job y los hechos. Si el usuario
la declara espontaneamente, capturala, pero nunca hagas una pregunta solo para
obtenerla.

# SALIDA ESTRUCTURADA AL RECOMENDAR
El LLM CLASIFICA hechos; NO emite pesos numericos ni ideal_vector. Los numeros los
calcula el codigo de forma deterministica.

<PROFILE>
{
  "country": "<sv|cr|gt|hn|ni|pa|null>",
  "target_monthly": <numero o null>,
  "max_monthly": <numero o null>,
  "target_price": <numero o null>,
  "max_price": <numero o null>,
  "min_year": <numero o null>,

  "primary_job": "<job permitido|null>",
  "secondary_job": "<job permitido|null>",
  "usage": "<familia|trabajo|ciudad|carretera|mixto|null>",

  "daily_km": <numero o null>,
  "passengers": <entero o null>,
  "small_children": <true|false|null>,
  "road_mix": "<city|highway|mixed|null>",
  "cargo_level": "<none|light|medium|heavy|null>",
  "holding_period": "<short|medium|long|null>",
  "cost_sensitivity": "<low|medium|high|null>",

  "priority": "<confiabilidad|economia|espacio|apariencia|reventa|balance|null>",
  "secondary": "<confiabilidad|economia|espacio|apariencia|reventa|null>",

  "avoid_body": [],
  "require_body": [],
  "prefer_body": [],
  "intent_segment": "<deportivo|lujo|7_plazas|convertible|off_road|electrico|hibrido|null>",
  "avoid_transmission": "<manual|automatica|null>",
  "avoid_brands": [],
  "prefer_brands": [],
  "require_brands": [],
  "open_to_surprise": <true|false>
}
</PROFILE>

Reglas de extraccion:
- Si dicen "ideal X, maximo Y", guarda X como target y Y como max.
- Si dan solo un monto como "maximo", va en max. Si dicen "quiero pagar X" sin
  aclarar maximo, usa X como target y deja max null SOLO si el contexto sugiere
  que no era techo; si necesitas techo para buscar, pregunta una vez.
- "economico", "barato de mantener", "no gastar" -> cost_sensitivity high.
- "70 km diarios" -> daily_km 70.
- familia de seis / movernos todos -> passengers 6 e intent_segment 7_plazas.
- hijos/bebe -> small_children true.
- No emitas ideal_vector ni ideal_weights. Nunca pongas pesos 0..1 en el JSON.
"""


# ════════════════════════════════════════════════════════════════════
# NEED LIBRARY: facts -> ideal vector + weights (deterministico)
# ════════════════════════════════════════════════════════════════════

_DIMS = (
    "deportividad", "espacio", "confiabilidad", "economia",
    "lujo", "reventa", "modernidad", "aptitud_trabajo",
)

# target = que nivel del atributo encaja con ese job; importance = cuanto importa
_JOB_LIBRARY = {
    "daily_commute": {
        "target": {"deportividad": .20, "espacio": .35, "confiabilidad": .92,
                   "economia": .92, "lujo": .20, "reventa": .62,
                   "modernidad": .62, "aptitud_trabajo": .15},
        "importance": {"confiabilidad": 1.0, "economia": 1.0, "reventa": .45,
                       "modernidad": .45, "espacio": .25},
    },
    "family_transport": {
        "target": {"deportividad": .15, "espacio": .82, "confiabilidad": .94,
                   "economia": .72, "lujo": .25, "reventa": .68,
                   "modernidad": .68, "aptitud_trabajo": .25},
        "importance": {"espacio": 1.0, "confiabilidad": 1.0, "economia": .65,
                       "modernidad": .50, "reventa": .45},
    },
    "first_car": {
        "target": {"deportividad": .25, "espacio": .45, "confiabilidad": .95,
                   "economia": .88, "lujo": .20, "reventa": .72,
                   "modernidad": .60, "aptitud_trabajo": .15},
        "importance": {"confiabilidad": 1.0, "economia": .9, "reventa": .65,
                       "modernidad": .45},
    },
    "work_vehicle": {
        "target": {"deportividad": .10, "espacio": .80, "confiabilidad": .94,
                   "economia": .70, "lujo": .10, "reventa": .65,
                   "modernidad": .55, "aptitud_trabajo": .95},
        "importance": {"aptitud_trabajo": 1.0, "confiabilidad": 1.0,
                       "espacio": .8, "economia": .7, "reventa": .4},
    },
    "delivery": {
        "target": {"deportividad": .10, "espacio": .72, "confiabilidad": .94,
                   "economia": .94, "lujo": .10, "reventa": .55,
                   "modernidad": .55, "aptitud_trabajo": .78},
        "importance": {"economia": 1.0, "confiabilidad": 1.0,
                       "aptitud_trabajo": .8, "espacio": .65},
    },
    "long_distance": {
        "target": {"deportividad": .20, "espacio": .60, "confiabilidad": .95,
                   "economia": .92, "lujo": .35, "reventa": .60,
                   "modernidad": .65, "aptitud_trabajo": .20},
        "importance": {"confiabilidad": 1.0, "economia": 1.0,
                       "espacio": .45, "modernidad": .5},
    },
    "city_runabout": {
        "target": {"deportividad": .20, "espacio": .35, "confiabilidad": .90,
                   "economia": .92, "lujo": .20, "reventa": .55,
                   "modernidad": .62, "aptitud_trabajo": .10},
        "importance": {"economia": 1.0, "confiabilidad": .85,
                       "modernidad": .4, "espacio": .25},
    },
    "upgrade": {
        "target": {"deportividad": .50, "espacio": .55, "confiabilidad": .80,
                   "economia": .55, "lujo": .55, "reventa": .62,
                   "modernidad": .82, "aptitud_trabajo": .25},
        "importance": {"modernidad": .9, "confiabilidad": .6,
                       "reventa": .5, "lujo": .45},
    },
    "status_lifestyle": {
        "target": {"deportividad": .58, "espacio": .50, "confiabilidad": .68,
                   "economia": .35, "lujo": .95, "reventa": .58,
                   "modernidad": .82, "aptitud_trabajo": .15},
        "importance": {"lujo": 1.0, "modernidad": .75,
                       "deportividad": .55},
    },
    "weekend_adventure": {
        "target": {"deportividad": .40, "espacio": .70, "confiabilidad": .88,
                   "economia": .50, "lujo": .30, "reventa": .65,
                   "modernidad": .60, "aptitud_trabajo": .82},
        "importance": {"aptitud_trabajo": .95, "confiabilidad": .85,
                       "espacio": .7, "reventa": .4},
    },
    "rideshare": {
        "target": {"deportividad": .10, "espacio": .66, "confiabilidad": .95,
                   "economia": .96, "lujo": .18, "reventa": .62,
                   "modernidad": .65, "aptitud_trabajo": .20},
        "importance": {"economia": 1.0, "confiabilidad": 1.0,
                       "espacio": .55, "reventa": .5},
    },
}

_LEGACY_USAGE_TO_JOB = {
    "familia": "family_transport",
    "trabajo": "work_vehicle",
    "ciudad": "city_runabout",
    "carretera": "long_distance",
}

_PRIORITY_TO_DIM = {
    "confiabilidad": "confiabilidad",
    "economia": "economia",
    "espacio": "espacio",
    "apariencia": "deportividad",
    "reventa": "reventa",
}


def _num(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _int(v) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _derive_need_vector(data: dict):
    """Traduce hechos cerrados a (ideal_vector, ideal_weights, evidence).

    Los numeros viven aqui, no en el LLM. primary_job pesa 1.0 y secondary 0.55.
    Los modificadores de contexto (km/dia, pasajeros, carga...) pueden dominar un
    prior cuando son hechos mas concretos.
    """
    accum = {d: 0.5 * 0.05 for d in _DIMS}
    weight_acc = {d: 0.05 for d in _DIMS}
    evidence = []

    def add(dim, target, importance, why):
        if dim not in accum or importance <= 0:
            return
        accum[dim] += _clamp01(target) * importance
        weight_acc[dim] += importance
        if why and why not in evidence:
            evidence.append(why)

    primary = (data.get("primary_job") or "").strip().lower() or None
    secondary = (data.get("secondary_job") or "").strip().lower() or None
    if primary not in _JOB_LIBRARY:
        primary = _LEGACY_USAGE_TO_JOB.get((data.get("usage") or "").lower())

    for job, strength in ((primary, 1.0), (secondary, 0.55)):
        spec = _JOB_LIBRARY.get(job or "")
        if not spec:
            continue
        evidence.append(job)
        for d, target in spec["target"].items():
            imp = spec["importance"].get(d, 0.15) * strength
            add(d, target, imp, job)

    # Hechos de vida mas concretos que el job general.
    daily_km = _num(data.get("daily_km"))
    if daily_km is not None:
        evidence.append(f"daily_km:{round(daily_km)}")
        if daily_km >= 50:
            add("economia", .97, 1.15, "high_daily_km")
            add("confiabilidad", .95, .85, "high_daily_km")
        elif daily_km <= 15:
            # Sigue importando ser economico, pero el consumo deja de dominar.
            add("economia", .78, .35, "low_daily_km")
            add("confiabilidad", .90, .55, "low_daily_km")
        else:
            add("economia", .90, .75, "medium_daily_km")

    passengers = _int(data.get("passengers"))
    if passengers is not None:
        evidence.append(f"passengers:{passengers}")
        if passengers >= 6:
            add("espacio", 1.0, 1.35, "six_plus_passengers")
            add("confiabilidad", .94, .75, "six_plus_passengers")
        elif passengers >= 4:
            add("espacio", .84, .85, "family_passengers")
        elif passengers >= 2:
            add("espacio", .62, .45, "passengers")

    if data.get("small_children") is True:
        add("espacio", .76, .70, "small_children")
        add("confiabilidad", .95, .85, "small_children")
        add("modernidad", .70, .35, "small_children")

    road = (data.get("road_mix") or "").lower()
    if road == "city":
        add("economia", .92, .65, "city_use")
        add("espacio", .45, .20, "city_use")
    elif road == "highway":
        add("confiabilidad", .95, .75, "highway_use")
        add("economia", .90, .65, "highway_use")
    elif road == "mixed":
        add("confiabilidad", .92, .50, "mixed_use")
        add("economia", .86, .50, "mixed_use")

    cargo = (data.get("cargo_level") or "").lower()
    if cargo == "heavy":
        add("aptitud_trabajo", 1.0, 1.35, "heavy_cargo")
        add("espacio", .90, .85, "heavy_cargo")
        add("confiabilidad", .95, .70, "heavy_cargo")
    elif cargo == "medium":
        add("aptitud_trabajo", .82, .85, "medium_cargo")
        add("espacio", .78, .60, "medium_cargo")
    elif cargo == "light":
        add("aptitud_trabajo", .55, .40, "light_cargo")

    holding = (data.get("holding_period") or "").lower()
    if holding == "short":
        add("reventa", .92, .95, "short_holding")
    elif holding == "long":
        add("confiabilidad", .97, .75, "long_holding")
        add("reventa", .60, .25, "long_holding")

    cost = (data.get("cost_sensitivity") or "").lower()
    if cost == "high":
        add("economia", .94, .85, "high_cost_sensitivity")
        add("reventa", .68, .30, "high_cost_sensitivity")
    elif cost == "low":
        add("economia", .55, .20, "low_cost_sensitivity")

    # Solo si el usuario lo declaro espontaneamente. Nunca hace falta preguntarlo.
    for key, strength in (("priority", 1.10), ("secondary", .55)):
        dim = _PRIORITY_TO_DIM.get((data.get(key) or "").lower())
        if dim:
            target = .98 if dim != "deportividad" else .90
            add(dim, target, strength, f"explicit_{key}:{dim}")

    ideal = {d: round(accum[d] / weight_acc[d], 3) for d in _DIMS}
    maxw = max(weight_acc.values()) or 1.0
    weights = {d: round(max(.08, weight_acc[d] / maxw), 3) for d in _DIMS}
    return ideal, weights, evidence


def _need_confidence(data: dict, evidence: list[str]) -> float:
    score = .20
    if data.get("primary_job") or data.get("usage"):
        score += .25
    if data.get("max_monthly") is not None or data.get("max_price") is not None:
        score += .20
    if any(data.get(k) is not None for k in ("daily_km", "passengers", "small_children")):
        score += .15
    if any(data.get(k) for k in ("road_mix", "cargo_level", "holding_period")):
        score += .10
    if data.get("priority"):
        score += .05
    if len(evidence) >= 4:
        score += .05
    return round(min(1.0, score), 3)


# ════════════════════════════════════════════════════════════════════
# PROFILE CONSTRUCTION
# ════════════════════════════════════════════════════════════════════


def profile_from_extraction(data: dict) -> CarlyProfile:
    """Facts JSON -> CarlyProfile deterministico.

    Compatibilidad: acepta campos viejos (usage/priority/secondary), pero IGNORA
    cualquier ideal_vector numerico que pudiera mandar un prompt viejo.
    """
    ideal, ideal_weights, evidence = _derive_need_vector(data)

    passengers = _int(data.get("passengers"))
    intent_segment = (data.get("intent_segment") or None)
    if passengers is not None and passengers >= 6:
        intent_segment = "7_plazas"

    max_monthly = _num(data.get("max_monthly"))
    target_monthly = _num(data.get("target_monthly"))
    max_price = _num(data.get("max_price"))
    target_price = _num(data.get("target_price"))

    # Si solo hubo target, no lo convertimos silenciosamente en hard ceiling.
    # El prompt debe preguntar techo antes de recomendar; este fallback evita crash.
    p = CarlyProfile(
        max_monthly=max_monthly,
        max_price=max_price,
        target_monthly=target_monthly,
        target_price=target_price,
        min_year=_int(data.get("min_year")),
        exclude_body=data.get("avoid_body") or [],
        require_body=data.get("require_body") or [],
        prefer_body=data.get("prefer_body") or [],
        intent_segment=intent_segment,
        ideal_vector=ideal,
        ideal_weights=ideal_weights,
        exclude_transmission=data.get("avoid_transmission"),
        exclude_brands=data.get("avoid_brands") or [],
        require_brands=data.get("require_brands") or [],
        prefer_brands=data.get("prefer_brands") or [],
        primary_job=data.get("primary_job") or _LEGACY_USAGE_TO_JOB.get((data.get("usage") or "").lower()),
        secondary_job=data.get("secondary_job"),
        daily_km=_num(data.get("daily_km")),
        passengers=passengers,
        need_confidence=_need_confidence(data, evidence),
        need_evidence=evidence,
        surprise=bool(data.get("open_to_surprise")),
    )

    # Fallback weights para rutas sin similarity; se derivan del mismo need vector.
    iw = ideal_weights
    p.w_reliability = round(.20 + .80 * iw.get("confiabilidad", .5), 3)
    p.w_economy = round(.20 + .80 * iw.get("economia", .5), 3)
    p.w_space = round(.20 + .80 * iw.get("espacio", .5), 3)
    p.w_resale = round(.15 + .65 * iw.get("reventa", .5), 3)
    p.w_appeal = round(.10 + .55 * max(iw.get("deportividad", .2), iw.get("lujo", .2)), 3)
    p.w_modernity = round(.15 + .65 * iw.get("modernidad", .5), 3)
    p.w_value = .72 if (data.get("cost_sensitivity") or "").lower() == "high" else .52
    return p


# ════════════════════════════════════════════════════════════════════
# PROFILE BLOCK PARSER
# ════════════════════════════════════════════════════════════════════

_PROFILE_RE = re.compile(r"<PROFILE>\s*(\{.*?\})\s*</PROFILE>", re.S)


def extract_profile_json(llm_text: str):
    """Extrae el dict del bloque <PROFILE>; None = seguir conversando."""
    m = _PROFILE_RE.search(llm_text or "")
    if not m:
        return None
    raw = m.group(1)
    try:
        return json.loads(raw)
    except Exception:
        try:
            cleaned = re.sub(r",\s*([}\]])", r"\1", raw)
            return json.loads(cleaned)
        except Exception:
            return None
