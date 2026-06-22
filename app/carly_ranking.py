"""
carly_ranking.py  —  Ranking engine V2 de Carly (optimizado)

Cambios vs V1:
  (11) Normalizacion robusta de datos sucios (body_type "hatch", trans
       "Automática" con tilde/mayuscula) ANTES de cualquier match.
  (1)  Factor "modernidad" (premia años recientes).
  (2)  economy_score recalibrado para que discrimine.
  (3)  Penalizacion de km alto mas fuerte (en confiabilidad efectiva).
  (4)  Diversidad en el top (no clones del mismo make+body).
  (7)  Fairness visible: cuanto bajo/sobre mercado, numero y texto.
  (8)  "Lo que debes saber": contra honesta por auto.
  (9)  Inspeccion: que revisar segun año/km, sin alarmar.
Filosofia intacta: filtrar duro, puntuar suave, pesos por conversacion.
"""

from dataclasses import dataclass, field
from typing import Optional
import re as _re

CURRENT_YEAR = 2026

# ════════════════════════════════════════════════════════════════════
# CAPA SEMÁNTICA (Fase 1) — qué ES un carro mas alla de su body_type.
# Encuentra el MX-5 aunque este clasificado "sedan". NO escribe a la base.
# Matching por palabra completa (con padding de espacios) para evitar
# falsos positivos tipo "gr" -> "Grand Cherokee".
# ════════════════════════════════════════════════════════════════════
SEGMENT_MODELS = {
    "deportivo": [
        "mx-5", "mx 5", "miata", "brz", "gr86", "gr 86", "fr-s", "frs", "86",
        "supra", "mustang", "camaro", "challenger", "corvette", "370z", "350z",
        "civic si", "civic type r", "type r", "gti", "golf gti", "wrx", "sti",
        "rx-8", "rx 8", "rx-7", "s2000", "mr2", "m3", "m4", "m2", "amg",
        "cayman", "boxster", "911", "gr yaris", "gr corolla", "abarth",
    ],
    "lujo": [
        "clase c", "clase e", "clase s", "c-class", "e-class", "serie 3",
        "serie 5", "serie 7", "320i", "330i", "520i", "x3", "x5", "x6", "x7",
        "q3", "q5", "q7", "q8", "a4", "a6", "a8", "glc", "gle", "gls",
        "range rover", "cayenne", "macan", "panamera", "ls", "es", "rx", "gx",
        "lx", "is", "continental", "ghibli", "levante", "xf", "xe", "f-pace",
    ],
    "7_plazas": [
        "highlander", "santa fe", "sorento", "pilot", "cx-9", "cx 9",
        "telluride", "palisade", "prado", "land cruiser", "fortuner", "montero",
        "pajero", "sequoia", "tahoe", "suburban", "expedition", "durango",
        "atlas", "kodiaq", "outlander", "tiguan allspace", "carnival", "sienna",
        "odyssey", "pacifica", "qx60", "mdx",
    ],
    "convertible": [
        "mx-5", "mx 5", "miata", "z4", "slk", "slc", "boxster", "cabrio",
        "cabriolet", "convertible", "descapotable", "spider", "spyder", "911",
    ],
    "off_road": [
        "wrangler", "4runner", "land cruiser", "prado", "montero", "pajero",
        "fj cruiser", "defender", "bronco", "raptor", "trooper", "samurai",
        "jimny", "troller", "g class", "clase g",
    ],
}


def _norm_blob(s):
    """' make model ' con espacios a los lados para match por palabra."""
    return " " + _re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip() + " "


def _model_matches(model, keywords):
    blob = _norm_blob(model)
    for kw in keywords:
        k = _norm_blob(kw)
        if k != "  " and k in blob:
            return True
    return False


def car_segments(car: dict) -> list:
    """Segmentos semanticos a los que pertenece un carro (lectura, no escritura).
    Combina diccionario de modelos + señales de fuel/body."""
    segs = []
    model = car.get("model")
    for seg, kws in SEGMENT_MODELS.items():
        if _model_matches(model, kws):
            segs.append(seg)
    # electrico / hibrido por fuel_type, no por modelo
    fuel = (car.get("fuel_type") or "").lower()
    if any(k in fuel for k in ("electric", "eléctric", "electrico", "ev", "bev")):
        segs.append("electrico")
    if any(k in fuel for k in ("hibrid", "hybrid", "híbrid")):
        segs.append("hibrido")
    return list(dict.fromkeys(segs))  # dedup, preserva orden


def segment_or_filter(segment: str) -> Optional[str]:
    """Construye el filtro OR de PostgREST para traer modelos de un segmento
    desde Supabase (para que el MX-5 entre al pool aunque sea baja calidad)."""
    kws = SEGMENT_MODELS.get(segment)
    if not kws:
        return None
    parts = [f"model.ilike.*{kw}*" for kw in kws]
    return ",".join(parts)



# ──────────────────────────── TABLAS ───────────────────────────────
RELIABILITY_BY_MODEL = {
    ("toyota","rav4"):93,("toyota","yaris"):90,("toyota","corolla"):95,
    ("toyota","corolla cross"):92,("toyota","hilux"):94,("toyota","fortuner"):90,
    ("toyota","land cruiser"):93,("toyota","prado"):91,("toyota","4runner"):92,
    ("toyota","echo"):84,("toyota","tacoma"):92,
    ("hyundai","tucson"):80,("hyundai","accent"):81,("hyundai","santa fe"):79,
    ("hyundai","elantra"):80,("hyundai","grand i10"):78,("hyundai","creta"):80,
    ("kia","sportage"):79,("kia","rio"):80,("kia","sorento"):78,
    ("kia","picanto"):79,("kia","seltos"):79,
    ("nissan","qashqai"):76,("nissan","kicks"):79,("nissan","versa"):77,
    ("nissan","frontier"):82,("nissan","sentra"):78,("nissan","xtrail"):76,
    ("nissan","x-trail"):76,("nissan","tiida"):75,
    ("honda","crv"):90,("honda","cr-v"):90,("honda","civic"):91,
    ("honda","pilot"):84,("honda","fit"):88,("honda","hr-v"):87,("honda","hrv"):87,
    ("mitsubishi","montero sport"):81,("mitsubishi","outlander"):79,
    ("mitsubishi","l200"):82,("mitsubishi","montero"):81,("mitsubishi","asx"):77,
    ("suzuki","grand vitara"):82,("suzuki","vitara"):82,("suzuki","swift"):83,
    ("chevrolet","spark"):72,("isuzu","dmax"):83,("ford","explorer"):69,
    ("jeep","wrangler"):66,
    ("bmw","x5"):60,("bmw","x1"):62,("bmw","x3"):61,
    ("audi","q3"):61,("audi","q5"):60,("land rover","range rover"):52,
}
RELIABILITY_BY_BRAND = {
    "toyota":90,"honda":88,"mazda":83,"suzuki":81,"subaru":82,"lexus":92,
    "mitsubishi":79,"kia":78,"hyundai":79,"nissan":76,"ford":70,"chevrolet":69,
    "volkswagen":68,"jeep":64,"renault":63,"peugeot":62,"fiat":58,
    "land rover":55,"bmw":62,"mercedes-benz":63,"audi":61,
}
RELIABILITY_FLOOR = 65
RESALE_BY_BRAND = {
    "toyota":95,"honda":88,"lexus":90,"subaru":80,"mazda":78,"suzuki":76,
    "mitsubishi":75,"nissan":70,"hyundai":68,"kia":67,"ford":60,"chevrolet":58,
    "volkswagen":60,"bmw":55,"mercedes-benz":57,
}
RESALE_FLOOR = 60
SPACE_BY_BODY = {"suv":88,"pickup":90,"minivan":95,"wagon":85,"crossover":82,
    "sedan":65,"hatchback":55,"coupe":35,"convertible":25}
SPACE_FLOOR = 60
APPEAL_BY_BODY = {"suv":82,"crossover":80,"pickup":78,"coupe":85,"convertible":88,
    "sedan":65,"hatchback":62,"minivan":45,"wagon":55}
APPEAL_FLOOR = 60

# ─────────────────── (11) NORMALIZACION ─────────────────────────────
def _norm(s):
    s = (s or "").strip().lower()
    for a,b in (("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u"),("ñ","n")):
        s = s.replace(a,b)
    return s

_BODY_CANON = {
    "hatch":"hatchback","hatchback":"hatchback","hb":"hatchback","compacto":"hatchback",
    "sedan":"sedan","saloon":"sedan",
    # LATAM: "camioneta" = SUV (Ford EcoSport, Tucson...), NUNCA pickup
    "suv":"suv","sport utility":"suv","todo terreno":"suv","todoterreno":"suv","4x4":"suv",
    "camioneta":"suv","jeepeta":"suv","yipeta":"suv",
    "crossover":"crossover","cuv":"crossover",
    "pickup":"pickup","pick-up":"pickup","pick up":"pickup","picap":"pickup",
    "troca":"pickup","palangana":"pickup","doble cabina":"pickup",
    "minivan":"minivan","van":"minivan","minibus":"minivan","microbus":"minivan",
    "busito":"minivan","buseta":"minivan",
    "wagon":"wagon","station wagon":"wagon","familiar":"wagon",
    "coupe":"coupe","convertible":"convertible","cabrio":"convertible",
}
def canon_body(b):
    b = _norm(b); return _BODY_CANON.get(b, b)
def canon_transmission(t):
    t = _norm(t)
    if t.startswith("auto") or "cvt" in t: return "automatica"
    if t.startswith("man"): return "manual"
    return t
def canon_fuel(f):
    f = _norm(f)
    if f in ("hibrido","hybrid"): return "hibrido"
    if f in ("electrico","electric","ev"): return "electrico"
    if f == "diesel": return "diesel"
    if f in ("gasolina","gas","regular","super"): return "gasolina"
    return f
def canon_model(m):
    return _norm(m)

# ──────────────────────────── PERFIL ───────────────────────────────
@dataclass
class CarlyProfile:
    max_monthly: Optional[float] = None
    max_price: Optional[float] = None
    min_year: Optional[int] = None
    exclude_body: list = field(default_factory=list)
    exclude_transmission: Optional[str] = None
    exclude_brands: list = field(default_factory=list)
    require_brands: list = field(default_factory=list)
    require_body: list = field(default_factory=list)
    intent_segment: Optional[str] = None   # deportivo|lujo|7_plazas|convertible|off_road|electrico|hibrido
    ideal_vector: Optional[dict] = None     # carro ideal abstracto (vector 0..1 por dimension)
    ideal_weights: Optional[dict] = None     # cuanto pesa cada dimension
    w_reliability: float = 0.45
    w_economy: float = 0.30
    w_space: float = 0.30
    w_value: float = 0.50
    w_resale: float = 0.30
    w_appeal: float = 0.20
    w_modernity: float = 0.35
    surprise: bool = False

# ──────────────────────────── FACTORES ─────────────────────────────
def reliability_base(make, model):
    key = (_norm(make), canon_model(model))
    if key in RELIABILITY_BY_MODEL: return RELIABILITY_BY_MODEL[key]
    return RELIABILITY_BY_BRAND.get(_norm(make), RELIABILITY_FLOOR)

def reliability_score(make, model, km):
    base = reliability_base(make, model)
    if km is not None:
        if km < 50000: base += 3
        elif km < 90000: base += 0
        elif km < 130000: base -= 6
        elif km < 180000: base -= 14
        else: base -= 22
    return max(0.0, min(100.0, base))

def resale_score(make): return RESALE_BY_BRAND.get(_norm(make), RESALE_FLOOR)
def space_score(bt): return SPACE_BY_BODY.get(canon_body(bt), SPACE_FLOOR)

def appeal_score(bt, year):
    base = APPEAL_BY_BODY.get(canon_body(bt), APPEAL_FLOOR)
    if year:
        age = CURRENT_YEAR - year
        if age <= 3: base += 8
        elif age >= 12: base -= 8
    return max(0.0, min(100.0, base))

def modernity_score(year):
    if not year: return 55.0
    age = CURRENT_YEAR - year
    if age <= 2: return 100.0
    if age <= 4: return 90.0
    if age <= 6: return 78.0
    if age <= 8: return 64.0
    if age <= 10: return 50.0
    if age <= 13: return 35.0
    return 20.0

def economy_score(km, year, fuel_type):
    f = canon_fuel(fuel_type)
    if f == "electrico": s = 95.0
    elif f == "hibrido": s = 88.0
    elif f == "diesel": s = 70.0
    else: s = 58.0
    if km is not None:
        if km < 40000: s += 12
        elif km < 80000: s += 6
        elif km < 130000: s -= 2
        elif km < 180000: s -= 10
        else: s -= 18
    if year:
        age = CURRENT_YEAR - year
        if age <= 4: s += 6
        elif age >= 13: s -= 8
    return max(0.0, min(100.0, s))

def value_score(price, comps):
    valid = [p for p in comps if p and p > 0]
    if not price or len(valid) < 3:
        return 60.0, None, "precio de referencia"
    avg = sum(valid)/len(valid)
    if avg <= 0: return 60.0, None, "precio de referencia"
    ratio = price/avg
    delta_pct = round((ratio-1.0)*100, 1)
    # Outlier guard: precio absurdamente bajo (>60% bajo el promedio) casi
    # siempre es dato basura (mal parseado), no una ganga. No lo premies como
    # "bajisimo bajo mercado"; marcalo neutro para que no suba en el ranking.
    if ratio < 0.40:
        return 55.0, delta_pct, "precio a verificar"
    s = max(0.0, min(100.0, 60.0 + (1.0-ratio)*150.0))
    # Etiqueta clara: nada de "0% en precio de mercado" (confunde).
    if -8 < delta_pct < 8:
        label = "precio justo de mercado"   # cerca de la mediana
    elif delta_pct <= -8:
        label = "bajo el mercado"
    else:
        label = "sobre el mercado"
    return s, delta_pct, label

# ════════════════════════════════════════════════════════════════════
# MOTOR DE SIMILITUD (Fase A) — ideal abstracto -> cercania -> (luego) aprendizaje
# El LLM construye el "carro ideal" como vector; cada carro real tiene el mismo
# tipo de vector; medimos distancia ponderada. Mas cerca = mejor fit. Reusa los
# scores que ya existen, asi que es debuggable y barato. NO escribe a la base aun.
# ════════════════════════════════════════════════════════════════════
VECTOR_DIMS = ["deportividad", "espacio", "confiabilidad", "economia",
               "lujo", "reventa", "modernidad", "aptitud_trabajo"]

_LUJO_BRANDS = {"mercedes-benz", "mercedes", "bmw", "audi", "land rover",
                "porsche", "jaguar", "infiniti", "acura", "volvo", "cadillac",
                "lexus", "mini", "maserati", "bentley", "genesis"}
_BODY_ON_FRAME = {"hilux", "land cruiser", "prado", "fortuner", "4runner",
                  "montero", "pajero", "wrangler", "tacoma", "ranger"}


def car_vector(car: dict) -> dict:
    """Vector de atributos 0..1 de un carro real, derivado de señales que ya
    tenemos (segmentos, scores, fuel, año, marca, body). Esto es lo que se compara
    contra el ideal. En Fase B este vector se cachea en Supabase."""
    segs = car_segments(car)
    make = (car.get("make") or "").lower().strip()
    body = canon_body(car.get("body_type"))
    model = car.get("model")
    km, year = car.get("km"), car.get("year")

    # deportividad: segmento manda; si no, muy baja (un SUV no es deportivo)
    if "deportivo" in segs:
        deportividad = 1.0
    elif "convertible" in segs:
        deportividad = 0.85
    else:
        deportividad = {"coupe": 0.6, "hatch": 0.35}.get(body, 0.15)

    # espacio: por body + boost si es 7 plazas
    espacio = (space_score(body) / 100.0)
    if "7_plazas" in segs:
        espacio = min(1.0, espacio + 0.2)

    lujo = 1.0 if "lujo" in segs else (0.7 if make in _LUJO_BRANDS else 0.2)

    trabajo = 0.2
    if body == "pickup":
        trabajo = 0.9
    elif "off_road" in segs or _model_matches(model, _BODY_ON_FRAME):
        trabajo = 0.8
    elif body == "suv":
        trabajo = 0.4

    return {
        "deportividad": round(deportividad, 3),
        "espacio": round(espacio, 3),
        "confiabilidad": round(reliability_score(make, model, km) / 100.0, 3),
        "economia": round(economy_score(km, year, car.get("fuel_type")) / 100.0, 3),
        "lujo": round(lujo, 3),
        "reventa": round(resale_score(make) / 100.0, 3),
        "modernidad": round(modernity_score(year) / 100.0, 3),
        "aptitud_trabajo": round(trabajo, 3),
    }


def validate_ideal(ideal, weights=None):
    """Sanea el ideal que emite el LLM: solo dims conocidas, valores 0..1, pesos
    normalizados. Si viene inservible, devuelve (None, None) -> fallback al ranking."""
    if not isinstance(ideal, dict):
        return None, None
    iv = {}
    for d in VECTOR_DIMS:
        v = ideal.get(d)
        if isinstance(v, (int, float)):
            iv[d] = max(0.0, min(1.0, float(v)))
    if not iv:
        return None, None
    w = {}
    if isinstance(weights, dict):
        for d in iv:
            wv = weights.get(d)
            if isinstance(wv, (int, float)) and wv > 0:
                w[d] = float(wv)
    # peso por defecto 1.0 para dims sin peso explícito
    for d in iv:
        w.setdefault(d, 1.0)
    return iv, w


def similarity_score(ideal: dict, car_vec: dict, weights: dict | None = None) -> float:
    """0..100. Distancia euclidiana ponderada ideal↔carro -> similitud.
    Solo cuentan las dimensiones que el ideal especifico (las que importan)."""
    if not ideal:
        return 50.0
    weights = weights or {d: 1.0 for d in ideal}
    num = 0.0; wsum = 0.0
    for d, target in ideal.items():
        cv = car_vec.get(d, 0.5)
        w = weights.get(d, 1.0)
        num += w * (target - cv) ** 2
        wsum += w
    if wsum <= 0:
        return 50.0
    dist = (num / wsum) ** 0.5          # 0 (idéntico) .. 1 (opuesto)
    return round(max(0.0, min(100.0, (1.0 - dist) * 100.0)), 1)


def import_status(car: dict) -> Optional[str]:
    """Detecta autos de subasta/aduana (recuperación/salvamento importado de USA)
    por señales en la descripcion. Devuelve 'subasta_aduana' o None.
    Señales fuertes (casi sin falsos positivos) marcan solo; 'arranca y camina'
    es de apoyo (puede ser carro viejo honesto), marca solo si acompaña a otra
    señal o el precio es bajisimo para el año."""
    desc = (car.get("description") or "").lower()
    if not desc:
        return None
    fuerte = any(k in desc for k in (
        "aduana", "en camino", "subasta", "liquidaci", "según subasta", "segun subasta"))
    apoyo = any(k in desc for k in ("arranca y camina", "arranca y maneja"))
    # "•Arranca" o "arranca y maneja" como viñeta destacada (patrón de recuperación
    # cuando es viñeta seca, no frase). Distingue del Tiburón ("arranca bien" en
    # medio de una frase) por estar al inicio de viñeta o seguido de otra viñeta.
    vineta = ("•arranca" in desc.replace(" ", "") or "\u2022arranca" in desc
              or bool(_re.search(r"[•\-\*]\s*arranca\b", desc)))
    if fuerte:
        return "subasta_aduana"
    year, price = car.get("year"), car.get("price_usd")
    reciente_barato = bool(year and price and (CURRENT_YEAR - year) <= 7 and price < 13000)
    if apoyo and reciente_barato:
        return "subasta_aduana"
    if vineta and reciente_barato:
        return "subasta_aduana"
    return None


def looks_like_junk(car: dict) -> bool:
    """Guard de basura de datos (en PARALELO al motor, no es parte de el).
    Atrapa registros claramente rotos: sin año, precio irrisorio. NO detecta
    carros chocados (eso necesita señal de origen/imagen, fuera de alcance)."""
    year = car.get("year")
    price = car.get("price_usd")
    if year in (None, 0):
        return True                     # un listing real trae año (mata el Mustang null)
    if price is not None and price < 2000:
        return True                     # bajo $2k en CA = chatarra/partes/error
    return False


# ──────────────────────────── FILTRO ───────────────────────────────
def passes_filters(car, p: CarlyProfile):
    if looks_like_junk(car): return False   # basura de datos: sin año / precio irrisorio
    m = car.get("monthly_est")
    if p.max_monthly is not None and m is not None and m > p.max_monthly: return False
    pr = car.get("price_usd")
    if p.max_price is not None and pr is not None and pr > p.max_price: return False
    y = car.get("year")
    if p.min_year is not None and y is not None and y < p.min_year: return False
    bt = canon_body(car.get("body_type"))
    req = [canon_body(b) for b in p.require_body]
    if req and bt not in req: return False
    if bt in [canon_body(b) for b in p.exclude_body]: return False
    if p.exclude_transmission and \
       canon_transmission(car.get("transmission")) == canon_transmission(p.exclude_transmission):
        return False
    if _norm(car.get("make")) in [_norm(b) for b in p.exclude_brands]: return False
    if p.require_brands and _norm(car.get("make")) not in [_norm(b) for b in p.require_brands]: return False
    return True

# ──────────────────────────── SCORING ──────────────────────────────
def score_car(car, p: CarlyProfile, comps_by_model):
    make, model = car.get("make"), car.get("model")
    km, year = car.get("km"), car.get("year")
    comps = comps_by_model.get((_norm(make), canon_model(model)), [])
    v_score, v_delta, v_label = value_score(car.get("price_usd"), comps)
    factors = {
        "reliability": reliability_score(make, model, km),
        "economy": economy_score(km, year, car.get("fuel_type")),
        "space": space_score(car.get("body_type")),
        "value": v_score,
        "resale": resale_score(make),
        "appeal": appeal_score(car.get("body_type"), year),
        "modernity": modernity_score(year),
    }
    weights = {
        "reliability": p.w_reliability, "economy": p.w_economy, "space": p.w_space,
        "value": p.w_value, "resale": p.w_resale, "appeal": p.w_appeal,
        "modernity": p.w_modernity,
    }
    wsum = sum(weights.values()) or 1.0
    total = sum(factors[k]*weights[k] for k in factors)/wsum

    # MOTOR DE SIMILITUD: si el LLM construyo un "carro ideal", la cercania a ese
    # ideal MANDA (mezclada con el valor/precio para no premiar caro). Esto
    # reemplaza el boost fijo: el MX-5 gana por estar cerca del ideal deportivo,
    # no por un +18 arbitrario.
    iv = getattr(p, "ideal_vector", None)
    if iv:
        cv = car_vector(car)
        sim = similarity_score(iv, cv, getattr(p, "ideal_weights", None))
        # 80% cercania al ideal + 20% qué tan buen trato es (fairness)
        total = 0.8 * sim + 0.2 * factors.get("value", 60.0)
    elif getattr(p, "intent_segment", None):
        # Fallback: si hubo segmento pero el LLM no emitio vector, usa el boost.
        segs = car_segments(car)
        if p.intent_segment in segs:
            total = min(100.0, total + 18.0)
        else:
            total = max(0.0, total - 12.0)
    return round(total,1), factors, {"value_delta_pct": v_delta, "value_label": v_label}

# ──────────────── (8) CONTRA + (9) INSPECCION ──────────────────────
def honest_caveat(car, factors):
    # Subasta/aduana manda sobre cualquier otro caveat: honestidad primero.
    if import_status(car) == "subasta_aduana":
        return "Viene importado de subasta/aduana (auto de recuperación); la inspección de daños es clave antes de cerrar."
    km = car.get("km")
    if factors["modernity"] < 50:
        return "No es de los mas nuevos, pero bien cuidado puede dar muchos kilometros tranquilos."
    if km and km > 130000:
        return "Tiene bastante kilometraje; vale una buena revision mecanica antes de cerrar."
    if factors["appeal"] < 55:
        return "No es el mas vistoso, pero gana en sentido practico."
    if factors["economy"] < 60:
        return "El consumo no es su fuerte; tenelo en cuenta si haces muchos kilometros."
    if factors["resale"] < 62:
        return "Su reventa es algo mas baja que un Toyota o Honda; importa si lo cambias pronto."
    segs = car_segments(car)
    if "deportivo" in segs or "convertible" in segs:
        return "Es un deportivo de verdad: prioriza emocion y estilo sobre espacio y consumo."
    if "lujo" in segs:
        return "Premium de verdad; el mantenimiento y repuestos suelen costar mas que un japones."
    return "Opcion equilibrada, sin peros importantes para lo que buscas."

def inspection_focus(car):
    year, km = car.get("year"), car.get("km")
    age = CURRENT_YEAR - year if year else 0
    pts = []
    if km and km > 120000: pts += ["transmision","suspension"]
    if age >= 8: pts += ["historial de mantenimiento","fugas de aceite"]
    if canon_fuel(car.get("fuel_type")) == "hibrido" and age >= 6:
        pts += ["estado de la bateria hibrida"]
    if not pts: pts = ["estado general y documentos al dia"]
    seen = []
    for x in pts:
        if x not in seen: seen.append(x)
    return seen[:3]

# ──────────────────── RANKING + (4) DIVERSIDAD ─────────────────────
def best_for_label(factors, car=None):
    # Si el carro tiene un carácter de segmento claro, eso manda sobre el factor
    # crudo (evita que un Mini o un MX-5 salgan "Familia").
    if car is not None:
        segs = car_segments(car)
        if "deportivo" in segs or "convertible" in segs:
            return "Manejo"
        if "lujo" in segs:
            return "Lujo"
        if "off_road" in segs:
            return "Aventura"
        if "7_plazas" in segs:
            return "Familia"
    ejes = {"reliability":"Tranquilidad","economy":"Ahorro","space":"Familia",
            "value":"Mejor precio","resale":"Inversion","appeal":"Estilo",
            "modernity":"Lo mas nuevo"}
    return ejes.get(max(factors, key=factors.get), "Balance")

def rank_cars(cars, profile: CarlyProfile, top_n=5):
    comps_by_model = {}
    for c in cars:
        key = (_norm(c.get("make")), canon_model(c.get("model")))
        comps_by_model.setdefault(key, []).append(c.get("price_usd"))

    survivors = [c for c in cars if passes_filters(c, profile)]
    scored = []
    for c in survivors:
        total, factors, meta = score_car(c, profile, comps_by_model)
        entry = {
            "car": c, "score": total, "factors": factors,
            "value_delta_pct": meta["value_delta_pct"], "value_label": meta["value_label"],
            "best_for": best_for_label(factors, c),
            "caveat": honest_caveat(c, factors),
            "inspect": inspection_focus(c),
        }
        # Umbral de cercania (estricto): si hay un ideal, solo entran los carros
        # que de verdad se parecen al ideal. Asi una busqueda de "deportivo de
        # lujo" no se ensucia con un Kia Rio de subasta solo por ser barato.
        iv = getattr(profile, "ideal_vector", None)
        if iv:
            sim = similarity_score(iv, car_vector(c), getattr(profile, "ideal_weights", None))
            entry["similarity"] = sim
        scored.append(entry)

    iv = getattr(profile, "ideal_vector", None)
    if iv:
        SIM_MIN = 62.0   # estricto: por debajo de esto, no calza de verdad
        fits = [e for e in scored if e.get("similarity", 0) >= SIM_MIN]
        # No dejar a la persona sin nada: si hay muy pocos sobre el umbral,
        # garantiza al menos los 3 mas cercanos (Carly explicara que hay pocos).
        if len(fits) < 3:
            scored.sort(key=lambda x: x.get("similarity", 0), reverse=True)
            fits = scored[:3]
        scored = fits

    scored.sort(key=lambda x: x["score"], reverse=True)

    # (4) diversidad: evita clones make+body
    top, seen = [], set()
    for e in scored:
        c = e["car"]; combo = (_norm(c.get("make")), canon_body(c.get("body_type")))
        if combo in seen: continue
        top.append(e); seen.add(combo)
        if len(top) >= top_n: break
    if len(top) < top_n:
        for e in scored:
            if e not in top:
                top.append(e)
                if len(top) >= top_n: break

    # (prompt 5) sorpresa
    if profile.surprise and len(scored) > len(top):
        bodies = {canon_body(x["car"].get("body_type")) for x in top}
        for cand in scored:
            if cand in top: continue
            if canon_body(cand["car"].get("body_type")) not in bodies:
                top[-1] = {**cand, "surprise": True}; break

    return top
