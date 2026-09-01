"""
carly_profile.py — Conversacion -> CarlyProfile (Intelligence Layer v4)

Cambios v3 -> v4 (objetivo: recomendaciones exquisitas con <=2 preguntas y costo ~0):

  1. FAST PATH DETERMINISTICO (extract_facts_regex): un extractor de regex corre
     ANTES del LLM y llena facts desde el texto crudo (presupuesto, km/dia,
     pasajeros, bebe, job, marca, transmision, carroceria). Si el primer mensaje
     ya trae job + techo de presupuesto, se recomienda SIN llamar al LLM para
     razonar la conversacion: solo se necesita (opcionalmente) una frase de
     presentacion, que puede ser plantilla. Costo LLM: 0 tokens en ese caso.

  2. PRESUPUESTO DURO DE PREGUNTAS (conversation_policy): el codigo, no el LLM,
     decide si se pregunta o se recomienda. Maximo 2 preguntas por conversacion
     (MAX_QUESTIONS). A la tercera oportunidad se recomienda con lo que haya,
     usando defaults razonables por job. El LLM recibe la decision ya tomada
     via directiva inyectada ("RECOMIENDA AHORA" / "puedes hacer 1 pregunta").

  3. PROMPT COMPRIMIDO + CACHE: CARLY_SYSTEM_PROMPT bajo de ~2,400 a ~800
     tokens sin perder reglas operativas (los ejemplos largos se convirtieron
     en reglas). Marcado para prompt caching de Anthropic (cache_control en
     main.py): tras el primer turno, el prompt cacheado cuesta ~10% del precio.
     Turno tipico: ~80-150 tokens no cacheados.

  4. FACTS PRE-LLENADOS SE INYECTAN al LLM como "HECHOS YA CONOCIDOS" para que
     jamas repregunte algo que el regex ya capturo (la causa #1 de preguntas
     desperdiciadas en v3).

La matematica (Need Library, ranking) no cambia: ya era deterministica y buena.
Pipeline: texto --regex--> facts --(LLM solo si falta algo)--> facts completos
          --Need Translator--> CarlyProfile --ranking--> top
"""

from __future__ import annotations

import json
import re
from typing import Optional

from .carly_ranking import CarlyProfile

MAX_QUESTIONS = 2          # techo duro de preguntas por conversacion
MIN_FACTS_TO_RECOMMEND = 2 # job/usage + presupuesto


# ════════════════════════════════════════════════════════════════════
# 1) FAST PATH: regex extractor (0 tokens)
# ════════════════════════════════════════════════════════════════════

def _n(s: str) -> str:
    s = (s or "").lower()
    for a, b in (("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u"),("ñ","n")):
        s = s.replace(a, b)
    return s

_JOB_PATTERNS = [
    # (job, patrones). Orden importa: lo mas especifico primero.
    ("rideshare",        r"\buber\b|\bindriver\b|in ?driver|didi|para trabajar en apps"),
    ("delivery",         r"\bdelivery\b|repartir|entregas|reparto"),
    ("work_vehicle",     r"mi negocio|para el negocio|(?:pickup|picap|palangana).{0,35}para trabajar|cargar (?:herramient|material|mercader)|carga(?:s)? pesada(?:s)?|ripio|para trabajo de campo|finca|construccion"),
    ("family_transport", r"mi (?:esposa|esposo|familia)|toda la familia|los ninos|mis hijos|la bebe|el bebe|somos (?:cuatro|cinco|seis|[4-9])"),
    ("daily_commute",    r"para (ir al|el) trabajo|para la oficina|commute|ir a trabajar"),
    ("first_car",        r"mi primer carro|primer auto|primer vehiculo|estoy aprendiendo"),
    ("long_distance",    r"viajes largos|carretera seguido|interdepartamental|viajar entre"),
    ("city_runabout",    r"solo ciudad|para la ciudad|mandados|vueltas"),
    ("weekend_adventure",r"montana|playa seguido|camping|aventura|off ?road"),
    ("status_lifestyle", r"algo de lujo|que se vea bien|elegante|premium"),
]

_NUM = r"\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?"

def _to_num(s: str) -> Optional[float]:
    """Parsea montos LATAM/US sin confundir miles con decimales."""
    raw = re.sub(r"[^\d.,]", "", str(s or ""))
    if not raw:
        return None
    try:
        if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", raw):
            return float(re.sub(r"[.,]", "", raw))
        if "," in raw and "." in raw:
            decimal = "," if raw.rfind(",") > raw.rfind(".") else "."
            thousands = "." if decimal == "," else ","
            return float(raw.replace(thousands, "").replace(decimal, "."))
        if raw.count(",") == 1:
            left, right = raw.split(",")
            return float(left + right) if len(right) == 3 else float(left + "." + right)
        if raw.count(".") == 1:
            left, right = raw.split(".")
            return float(left + right) if len(right) == 3 else float(raw)
        return float(raw.replace(",", "").replace(".", ""))
    except (TypeError, ValueError):
        return None

def extract_facts_regex(text: str) -> dict:
    """Extrae hechos del texto crudo del usuario. Determinista, 0 tokens.
    Devuelve solo claves con evidencia; nunca inventa. Conservador a proposito:
    ante ambiguedad no emite (el LLM o una pregunta lo resuelven)."""
    t = " " + _n(text) + " "
    f: dict = {}

    # ── presupuesto ──────────────────────────────────────────────
    # "ideal 250, llego a 450" es un rango de cuota cuando ambos son montos
    # mensuales plausibles. Se evalua antes que los patrones individuales.
    rng = re.search(
        rf"ideal(?:mente)?(?:\s+de)?\s*\$?\s*(?P<target>{_NUM}).{{0,50}}?"
        rf"(?:maximo|llegar(?:ia)?\s+a|llego\s+a|puedo\s+llegar\s+a|tope)\s*"
        rf"\$?\s*(?P<ceiling>{_NUM})(?:\s*(?:al mes|mensual(?:es)?|por mes))?",
        t,
    )
    target_range = _to_num(rng.group("target")) if rng else None
    max_range = _to_num(rng.group("ceiling")) if rng else None
    if target_range is not None and max_range is not None and 25 <= target_range <= max_range <= 2000:
        f["target_monthly"] = target_range
        f["max_monthly"] = max_range

    # Cuota mensual: acepta el calificador antes del monto ("maximo 300 al
    # mes"), despues del monto y la forma "cuota de 350".
    m = re.search(
        rf"(?:(?P<qual>hasta|maximo|\bmax\b|tope|no mas de)\s+)?"
        rf"(?:cuota(?:\s+de)?\s+)?\$?\s*(?P<amount>{_NUM})\s*"
        rf"(?:al mes|mensual(?:es)?|por mes|de cuota)",
        t,
    )
    if not m:
        m = re.search(
            rf"(?:cuota|mensualidad)\s*(?:maxima|ideal)?\s*(?:de|es)?\s*"
            rf"\$?\s*(?P<amount>{_NUM})",
            t,
        )
    monthly = _to_num(m.group("amount")) if m else None
    monthly_is_max = bool(
        m and re.search(
            r"maximo|hasta|\bmax\b|tope|no mas de",
            t[max(0, m.start() - 30):m.end() + 15],
        )
    )

    # Precio total: "hasta 15000", "$12,500", "presupuesto de 10 mil".
    # Un monto explicitamente mensual nunca cae en esta rama.
    m2 = re.search(
        rf"(?:hasta|maximo|\bmax\b|tope|presupuesto\s+(?:de|es))\s*\$?\s*"
        rf"(?P<amount>{_NUM})\s*(?P<scale>mil|k)?\b",
        t,
    )
    total = _to_num(m2.group("amount")) if m2 else None
    if total is not None and m2 and m2.group("scale") in {"mil", "k"}:
        total *= 1000
    if monthly is not None and monthly <= 2000:
        if "max_monthly" in f:
            pass
        elif monthly_is_max:
            f["max_monthly"] = monthly
        else:
            f["target_monthly"] = monthly
    elif total is not None and total >= 2500 and not re.search(r"al mes|mensual|por mes|de cuota", m2.group(0) if m2 else ""):
        f["max_price"] = total

    # ── uso ──────────────────────────────────────────────────────
    jobs = [j for j, pat in _JOB_PATTERNS if re.search(pat, t)]
    if jobs:
        f["primary_job"] = jobs[0]
        if len(jobs) > 1 and jobs[1] != jobs[0]:
            f["secondary_job"] = jobs[1]

    m = re.search(
        rf"(?P<lo>{_NUM})(?:\s*(?:-|a|hasta)\s*(?P<hi>{_NUM}))?\s*"
        rf"(?:km|kms|kilometros)\s*(?:al dia|por dia|diarios)?",
        t,
    )
    if m:
        lo = _to_num(m.group("lo"))
        hi = _to_num(m.group("hi")) if m.group("hi") else lo
        if lo is not None and hi is not None and 0 < lo <= hi <= 500:
            f["daily_km"] = round((lo + hi) / 2, 1)

    m = re.search(r"somos\s+(dos|tres|cuatro|cinco|seis|siete|\d)", t)
    if m:
        w = {"dos":2,"tres":3,"cuatro":4,"cinco":5,"seis":6,"siete":7}
        f["passengers"] = w.get(m.group(1)) or int(m.group(1))
    if re.search(r"\bbebe\b|sillita|carseat|ninos pequenos|hijos pequenos", t):
        f["small_children"] = True

    if re.search(r"economic|barato de (usar|mantener)|no gastar|gaste poco|ahorr", t):
        f["cost_sensitivity"] = "high"
    if re.search(r"solo (en la )?ciudad|puro trafico", t):
        f["road_mix"] = "city"
    elif re.search(r"pura carretera|solo carretera", t):
        f["road_mix"] = "highway"

    # ── hard vs soft (misma semantica que v3) ────────────────────
    m = re.search(r"(?:solo|tiene que ser|unicamente)\s+(toyota|honda|mazda|hyundai|kia|nissan|mitsubishi|suzuki)", t)
    if m:
        f["require_brands"] = [m.group(1)]
    else:
        m = re.search(r"(?:me gustaria|de preferencia|si se puede)\s+(?:un[a]? )?(toyota|honda|mazda|hyundai|kia|nissan|mitsubishi|suzuki)", t)
        if not m:
            m = re.search(r"(toyota|honda|mazda|hyundai|kia|nissan|mitsubishi|suzuki)\s+si se puede", t)
        if m:
            f["prefer_brands"] = [m.group(1)]
    if re.search(r"no (?:se )?manejo? manual|solo automatic|no manual", t):
        f["avoid_transmission"] = "manual"
    if re.search(r"\bpickup\b|palangana|para cargar material", t) and "work_vehicle" in jobs:
        f["require_body"] = ["pickup"]

    return f


# ════════════════════════════════════════════════════════════════════
# 2) POLITICA DE CONVERSACION: el codigo decide preguntar vs recomendar
# ════════════════════════════════════════════════════════════════════

def merge_facts(known: dict, new: dict) -> dict:
    """Combina turnos; una correccion explicita posterior reemplaza lo previo."""
    out = dict(known or {})
    for k, v in (new or {}).items():
        if v not in (None, [], ""):
            out[k] = v
    return out


def _has_budget(f: dict) -> bool:
    return any(f.get(k) is not None for k in ("max_monthly", "max_price", "target_monthly", "target_price"))


def _has_use(f: dict) -> bool:
    return bool(f.get("primary_job") or f.get("usage"))


def next_question(f: dict) -> Optional[str]:
    """LA pregunta de mayor valor (Importance x Uncertainty x Variance,
    resuelto en codigo por prioridad). None = nada que valga la pena preguntar."""
    if not _has_use(f):
        return "¿Para que lo vas a usar principalmente? (trabajo diario, familia, negocio...)"
    if not _has_budget(f):
        return "¿Que cuota mensual te queda comoda, y hasta donde llegarias si algo realmente lo vale?"
    job = f.get("primary_job")
    if job == "daily_commute" and f.get("daily_km") is None:
        return "¿Como cuantos kilometros haces en un dia normal?"
    if job == "family_transport" and f.get("passengers") is None:
        return "¿Cuantos viajan normalmente en el carro?"
    if job in ("work_vehicle", "delivery") and not f.get("cargo_level"):
        return "¿Que tanto cargas: cosas ligeras o carga pesada seguido?"
    return None


def conversation_policy(facts: dict, questions_asked: int) -> dict:
    """Decision del turno. Devuelve:
    {"action": "recommend"} o
    {"action": "ask", "question": "..."}.
    Regla: recomendar en cuanto haya uso + presupuesto, o al agotar el cupo."""
    if questions_asked >= MAX_QUESTIONS:
        return {"action": "recommend"}
    if _has_use(facts) and _has_budget(facts):
        q = next_question(facts)
        # Con uso + presupuesto ya se puede ordenar bien. Solo gastamos la
        # pregunta contextual si aun queda cupo Y reordenaria el top (km/pasajeros).
        if q and questions_asked < MAX_QUESTIONS - 1:
            return {"action": "ask", "question": q}
        return {"action": "recommend"}
    q = next_question(facts)
    if q:
        return {"action": "ask", "question": q}
    return {"action": "recommend"}


def apply_job_defaults(f: dict) -> dict:
    """Defaults razonables cuando se recomienda con cupo agotado. No pisan nada
    declarado; solo evitan un Need Vector vacio."""
    out = dict(f)
    if not _has_use(out):
        out["primary_job"] = "daily_commute"     # el caso base del mercado
    if out.get("primary_job") == "family_transport" and out.get("passengers") is None:
        out["passengers"] = 4
    return out


# ════════════════════════════════════════════════════════════════════
# 3) SYSTEM PROMPT v4 (compacto; ~800 tokens; cachear con cache_control)
#    El bloque {DIRECTIVE} y {KNOWN_FACTS} se inyectan por turno (no cacheados).
# ════════════════════════════════════════════════════════════════════

CARLY_SYSTEM_PROMPT = r"""
Eres Carly, asesora de compra de CarTrade. Entiendes que necesita resolver la
persona con el carro y lo traduces a criterios automotrices. Tuteo neutro
latinoamericano, directo, calido, sin voseo.

REGLA MADRE: pregunta HECHOS DE LA VIDA (km/dia, quien viaja, que carga),
NUNCA metricas de carro ("¿prefieres espacio o economia?" esta prohibido).
Infieres las metricas tu.

FORMATO DE TURNO (el sistema te dira cual aplica en DIRECTIVA):
A) PREGUNTAR: 1 frase que demuestre que entendiste + LA pregunta indicada.
   Nada mas. Sin <PROFILE>.
B) RECOMENDAR: 1-2 frases de sintesis + bloque <PROFILE>. Sin pregunta final.

Si el primer mensaje ya trae una necesidad, no te presentes: demuestra que
entendiste. Solo saludas si el usuario entro sin necesidad concreta.

PRESUPUESTO: "ideal X, llego a Y" -> target=X, max=Y. Target es comodidad,
max es techo duro. Estar bajo el target nunca es malo.

HARD vs SOFT: "solo Toyota" -> require_brands. "me gustaria Toyota" ->
prefer_brands. Jamas conviertas preferencia blanda en filtro duro.

JOBS: daily_commute, family_transport, first_car, work_vehicle, delivery,
long_distance, city_runabout, upgrade, status_lifestyle, weekend_adventure,
rideshare. Puede haber primary y secondary.

HONESTIDAD: distingue reportado por anuncio / inferido por Carly / verificado
por CarTrade. Precio bajo no es buen valor; anomalia = "a verificar". El cierre
siempre via CarTrade (Ver detalles, Iniciar compra verificada); nunca mandes al
usuario a contactar vendedores ni buscar mecanico aparte.

<PROFILE> emite SOLO clasificaciones, jamas pesos numericos:
{"country":"sv|cr|gt|hn|ni|pa|null","target_monthly":n,"max_monthly":n,
"target_price":n,"max_price":n,"min_year":n,"primary_job":"...","secondary_job":null,
"usage":"familia|trabajo|ciudad|carretera|mixto|null","daily_km":n,"passengers":n,
"small_children":bool,"road_mix":"city|highway|mixed|null",
"cargo_level":"none|light|medium|heavy|null","holding_period":"short|medium|long|null",
"cost_sensitivity":"low|medium|high|null","priority":null,"secondary":null,
"avoid_body":[],"require_body":[],"prefer_body":[],
"intent_segment":"deportivo|lujo|7_plazas|convertible|off_road|electrico|hibrido|null",
"avoid_transmission":null,"avoid_brands":[],"prefer_brands":[],"require_brands":[],
"open_to_surprise":bool}
Campos sin evidencia: null/[]. "economico" -> cost_sensitivity high. familia de
seis -> passengers 6 + intent_segment 7_plazas. bebe -> small_children true.
"""


def build_turn_directive(facts: dict, decision: dict) -> str:
    """Bloque por-turno que se inyecta DESPUES del system prompt cacheado.
    Es lo unico no cacheado: ~60-120 tokens."""
    known = {k: v for k, v in facts.items() if v not in (None, [], "")}
    lines = ["HECHOS YA CONOCIDOS (no los repreguntes): " + (json.dumps(known, ensure_ascii=False) if known else "ninguno")]
    if decision["action"] == "recommend":
        lines.append("DIRECTIVA: RECOMIENDA AHORA (formato B). Emite <PROFILE> con los hechos conocidos + lo nuevo de este mensaje.")
    else:
        lines.append(f'DIRECTIVA: formato A. Haz exactamente esta pregunta (puedes reformularla natural): "{decision["question"]}"')
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════
# 4) TURNO COMPLETO (orquestador que main.py llama)
# ════════════════════════════════════════════════════════════════════

def plan_turn(user_text: str, known_facts: dict, questions_asked: int) -> dict:
    """Corre el fast path y la politica. Devuelve todo lo que main.py necesita:
    {"facts": dict actualizado,
     "decision": {"action": ...},
     "needs_llm": bool,          # False = se puede responder con plantilla
     "directive": str}           # bloque a inyectar si se llama al LLM
    """
    facts = merge_facts(known_facts, extract_facts_regex(user_text))
    decision = conversation_policy(facts, questions_asked)
    # Las preguntas de intake ya vienen redactadas por la politica, por lo que
    # nunca necesitan LLM. Una recomendacion solo puede saltarlo cuando uso y
    # presupuesto quedaron resueltos deterministicamente.
    needs_llm = decision["action"] == "recommend" and not (
        _has_use(facts) and _has_budget(facts)
    )
    if decision["action"] == "recommend":
        facts = apply_job_defaults(facts)
    return {
        "facts": facts,
        "decision": decision,
        "needs_llm": needs_llm,
        "directive": build_turn_directive(facts, decision),
    }


# ════════════════════════════════════════════════════════════════════
# NEED LIBRARY (sin cambios funcionales vs v3)
# ════════════════════════════════════════════════════════════════════

_DIMS = (
    "deportividad", "espacio", "confiabilidad", "economia",
    "lujo", "reventa", "modernidad", "aptitud_trabajo",
)

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

    daily_km = _num(data.get("daily_km"))
    if daily_km is not None:
        evidence.append(f"daily_km:{round(daily_km)}")
        if daily_km >= 50:
            add("economia", .97, 1.15, "high_daily_km")
            add("confiabilidad", .95, .85, "high_daily_km")
        elif daily_km <= 15:
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
# PROFILE CONSTRUCTION (sin cambios vs v3)
# ════════════════════════════════════════════════════════════════════

def profile_from_extraction(data: dict) -> CarlyProfile:
    ideal, ideal_weights, evidence = _derive_need_vector(data)

    passengers = _int(data.get("passengers"))
    intent_segment = (data.get("intent_segment") or None)
    if passengers is not None and passengers >= 6:
        intent_segment = "7_plazas"

    p = CarlyProfile(
        max_monthly=_num(data.get("max_monthly")),
        max_price=_num(data.get("max_price")),
        target_monthly=_num(data.get("target_monthly")),
        target_price=_num(data.get("target_price")),
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
# PROFILE BLOCK PARSER (sin cambios)
# ════════════════════════════════════════════════════════════════════

_PROFILE_RE = re.compile(r"<PROFILE>\s*(\{.*?\})\s*</PROFILE>", re.S)


def extract_profile_json(llm_text: str):
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
