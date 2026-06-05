"""
carly_ranking.py  —  Ranking engine V1 de Carly

Filosofia:
  1) FILTRAR duro (restricciones absolutas: mensualidad, exclusiones).
  2) PUNTUAR suave (score 0-100 por carro, suma ponderada de factores).
  Los PESOS de los factores los define la conversacion. La misma base
  de carros se rankea distinto para cada persona. Eso es el moat.

  Sin ML. Reglas. Deterministico, debuggeable, no alucina.
  El LLM hace dos cosas FUERA de aqui: traduce la conversacion a un
  CarlyProfile (los pesos + filtros), y explica el resultado. El ranking
  en si es esta funcion pura.

Enchufa con las columnas que ya tenes en scraped_listings:
  make, model, year, km, price_usd, monthly_est, body_type,
  photo_count, fuel_type, transmission.
"""

from dataclasses import dataclass, field
from typing import Optional


# ════════════════════════════════════════════════════════════════════
# 1) TABLA DE FIABILIDAD  (la armas a mano para los modelos comunes)
#    Escala 0-100. Esto es conocimiento publico y estable: un Corolla
#    es mas confiable que casi todo. No necesitas datos sofisticados.
#    Empeza con 30-40 modelos; lo que no este en la tabla usa el
#    default por marca, y lo que tampoco, un piso neutro.
# ════════════════════════════════════════════════════════════════════

RELIABILITY_BY_MODEL = {
    # Calibrado a los 50 modelos mas comunes del inventario real (CR + SV).
    # Incluye variantes de nombre tal como vienen en la base (crv vs cr-v, etc).
    # Toyota
    ("toyota", "rav4"): 93, ("toyota", "yaris"): 90, ("toyota", "corolla"): 95,
    ("toyota", "corolla cross"): 92, ("toyota", "hilux"): 94, ("toyota", "fortuner"): 90,
    ("toyota", "land cruiser"): 93, ("toyota", "prado"): 91, ("toyota", "4runner"): 92,
    ("toyota", "echo"): 84, ("toyota", "tacoma"): 92,
    # Hyundai
    ("hyundai", "tucson"): 80, ("hyundai", "accent"): 81, ("hyundai", "santa fe"): 79,
    ("hyundai", "elantra"): 80, ("hyundai", "grand i10"): 78, ("hyundai", "creta"): 80,
    # Kia
    ("kia", "sportage"): 79, ("kia", "rio"): 80, ("kia", "sorento"): 78,
    ("kia", "picanto"): 79, ("kia", "seltos"): 79,
    # Nissan
    ("nissan", "qashqai"): 76, ("nissan", "kicks"): 79, ("nissan", "versa"): 77,
    ("nissan", "frontier"): 82, ("nissan", "sentra"): 78, ("nissan", "xtrail"): 76,
    ("nissan", "x-trail"): 76, ("nissan", "tiida"): 75,
    # Honda (la base trae crv Y cr-v por separado: cubrir ambos)
    ("honda", "crv"): 90, ("honda", "cr-v"): 90, ("honda", "civic"): 91,
    ("honda", "pilot"): 84, ("honda", "fit"): 88, ("honda", "hr-v"): 87,
    # Mitsubishi
    ("mitsubishi", "montero sport"): 81, ("mitsubishi", "outlander"): 79,
    ("mitsubishi", "l200"): 82, ("mitsubishi", "montero"): 81, ("mitsubishi", "asx"): 77,
    # Suzuki
    ("suzuki", "grand vitara"): 82, ("suzuki", "vitara"): 82, ("suzuki", "swift"): 83,
    # Chevrolet / Isuzu / Ford / Jeep
    ("chevrolet", "spark"): 72, ("isuzu", "dmax"): 83, ("ford", "explorer"): 69,
    ("jeep", "wrangler"): 66,
    # Premium europeos (confiabilidad mecanica realista, no aspiracional)
    ("bmw", "x5"): 60, ("bmw", "x1"): 62, ("bmw", "x3"): 61,
    ("audi", "q3"): 61, ("audi", "q5"): 60, ("land rover", "range rover"): 52,
}

RELIABILITY_BY_BRAND = {
    "toyota": 90, "honda": 88, "mazda": 83, "suzuki": 81, "subaru": 82,
    "lexus": 92, "mitsubishi": 79, "kia": 78, "hyundai": 79, "nissan": 76,
    "ford": 70, "chevrolet": 69, "volkswagen": 68, "jeep": 64, "renault": 63,
    "peugeot": 62, "fiat": 58, "land rover": 55, "bmw": 62, "mercedes-benz": 63,
    "audi": 61,
}
RELIABILITY_FLOOR = 65  # marca desconocida: ni premio ni castigo fuerte


# Retencion de valor (reventa). Quien aguanta precio en CA/CR.
RESALE_BY_BRAND = {
    "toyota": 95, "honda": 88, "lexus": 90, "subaru": 80, "mazda": 78,
    "suzuki": 76, "mitsubishi": 75, "nissan": 70, "hyundai": 68, "kia": 67,
    "ford": 60, "chevrolet": 58, "volkswagen": 60, "bmw": 55, "mercedes-benz": 57,
}
RESALE_FLOOR = 60

# Espacio por carroceria (body_type). 0-100.
SPACE_BY_BODY = {
    "suv": 88, "pickup": 90, "minivan": 95, "wagon": 85, "crossover": 82,
    "sedan": 65, "hatchback": 55, "coupe": 35, "convertible": 25,
}
SPACE_FLOOR = 60

# Deseabilidad / "verse bien" por carroceria (proxy honesto).
APPEAL_BY_BODY = {
    "suv": 82, "crossover": 80, "pickup": 78, "coupe": 85, "convertible": 88,
    "sedan": 65, "hatchback": 62, "minivan": 45, "wagon": 55,
}
APPEAL_FLOOR = 60


# ════════════════════════════════════════════════════════════════════
# 2) PERFIL DEL COMPRADOR  (lo produce el LLM desde la conversacion)
#    Pesos: cuanto importa cada factor (0-1, no tienen que sumar 1).
#    Filtros: restricciones duras.
# ════════════════════════════════════════════════════════════════════

@dataclass
class CarlyProfile:
    # filtros duros
    max_monthly: Optional[float] = None     # mensualidad tope (usa monthly_est)
    max_price: Optional[float] = None        # precio tope alternativo
    min_year: Optional[int] = None
    exclude_body: list = field(default_factory=list)        # ej ["coupe"]
    exclude_transmission: Optional[str] = None              # ej "manual"
    exclude_brands: list = field(default_factory=list)
    require_body: list = field(default_factory=list)        # ej ["suv","pickup"]

    # pesos (0-1). Default: equilibrado.
    w_reliability: float = 0.5
    w_economy: float = 0.3
    w_space: float = 0.3
    w_value: float = 0.5
    w_resale: float = 0.3
    w_appeal: float = 0.2

    surprise: bool = False   # prompt 5: permitir una opcion lateral


# ════════════════════════════════════════════════════════════════════
# 3) HELPERS de normalizacion
# ════════════════════════════════════════════════════════════════════

def _norm(s):
    return (s or "").strip().lower()


def reliability_score(make, model):
    key = (_norm(make), _norm(model))
    if key in RELIABILITY_BY_MODEL:
        return RELIABILITY_BY_MODEL[key]
    return RELIABILITY_BY_BRAND.get(_norm(make), RELIABILITY_FLOOR)


def resale_score(make):
    return RESALE_BY_BRAND.get(_norm(make), RESALE_FLOOR)


def space_score(body_type):
    return SPACE_BY_BODY.get(_norm(body_type), SPACE_FLOOR)


def appeal_from_body(body_type):
    return APPEAL_BY_BODY.get(_norm(body_type), APPEAL_FLOOR)


def economy_score(km, year, fuel_type):
    """Proxy de economia: km bajo + carro no muy viejo + no consumidores
    obvios. 0-100. Sin datos de consumo real, esto es una aproximacion
    honesta que se puede refinar luego."""
    s = 60.0
    if km is not None:
        if km < 40000: s += 20
        elif km < 80000: s += 10
        elif km < 130000: s += 0
        elif km < 180000: s -= 12
        else: s -= 22
    if year is not None:
        age = 2026 - year
        if age <= 3: s += 8
        elif age <= 7: s += 3
        elif age >= 14: s -= 10
    f = _norm(fuel_type)
    if f in ("hibrido", "hybrid", "electrico", "electric"): s += 12
    if f in ("diesel",): s += 4
    return max(0.0, min(100.0, s))


def value_score(car, comps):
    """Que tan bien esta de precio vs comparables del MISMO make/model.
    Esto SOLO lo podes hacer porque tenes el corpus. Es el factor mas
    diferenciador: 'esta barato/caro vs el mercado real'.
    comps = lista de price_usd de carros del mismo modelo (incluido este).
    Devuelve 0-100: mas alto = mejor precio (mas barato vs mercado)."""
    price = car.get("price_usd")
    valid = [p for p in comps if p and p > 0]
    if not price or len(valid) < 3:
        return 60.0  # sin comparables suficientes: neutro
    avg = sum(valid) / len(valid)
    if avg <= 0:
        return 60.0
    ratio = price / avg          # <1 = mas barato que el promedio
    # mapear ratio a score: 0.80 del promedio -> ~90 ; 1.20 -> ~30
    s = 60.0 + (1.0 - ratio) * 150.0
    return max(0.0, min(100.0, s))


# ════════════════════════════════════════════════════════════════════
# 4) FILTRO DURO
# ════════════════════════════════════════════════════════════════════

def passes_filters(car, profile: CarlyProfile):
    m = car.get("monthly_est")
    if profile.max_monthly is not None and m is not None and m > profile.max_monthly:
        return False
    p = car.get("price_usd")
    if profile.max_price is not None and p is not None and p > profile.max_price:
        return False
    y = car.get("year")
    if profile.min_year is not None and y is not None and y < profile.min_year:
        return False
    bt = _norm(car.get("body_type"))
    if profile.require_body and bt not in [_norm(b) for b in profile.require_body]:
        return False
    if bt in [_norm(b) for b in profile.exclude_body]:
        return False
    if profile.exclude_transmission and _norm(car.get("transmission")) == _norm(profile.exclude_transmission):
        return False
    if _norm(car.get("make")) in [_norm(b) for b in profile.exclude_brands]:
        return False
    return True


# ════════════════════════════════════════════════════════════════════
# 5) SCORING + RANKING
# ════════════════════════════════════════════════════════════════════

def score_car(car, profile: CarlyProfile, comps_by_model):
    make, model = car.get("make"), car.get("model")
    comps = comps_by_model.get((_norm(make), _norm(model)), [])

    factors = {
        "reliability": reliability_score(make, model),
        "economy": economy_score(car.get("km"), car.get("year"), car.get("fuel_type")),
        "space": space_score(car.get("body_type")),
        "value": value_score(car, comps),
        "resale": resale_score(make),
        "appeal": appeal_from_body(car.get("body_type")),
    }
    weights = {
        "reliability": profile.w_reliability,
        "economy": profile.w_economy,
        "space": profile.w_space,
        "value": profile.w_value,
        "resale": profile.w_resale,
        "appeal": profile.w_appeal,
    }
    wsum = sum(weights.values()) or 1.0
    total = sum(factors[k] * weights[k] for k in factors) / wsum
    return round(total, 1), factors


def rank_cars(cars, profile: CarlyProfile, top_n=5):
    """cars: lista de dicts (filas de Supabase). Devuelve los top_n con
    su score y el desglose de factores, listos para que el LLM explique."""
    # comparables por modelo, para value_score (precio vs mercado real)
    comps_by_model = {}
    for c in cars:
        key = (_norm(c.get("make")), _norm(c.get("model")))
        comps_by_model.setdefault(key, []).append(c.get("price_usd"))

    survivors = [c for c in cars if passes_filters(c, profile)]
    scored = []
    for c in survivors:
        total, factors = score_car(c, profile, comps_by_model)
        scored.append({"car": c, "score": total, "factors": factors})
    scored.sort(key=lambda x: x["score"], reverse=True)

    top = scored[:top_n]

    # "permission to surprise": si lo permitio, intercambia el ultimo
    # del top por la mejor opcion de una carroceria que NO aparece en el
    # top, para meter una alternativa lateral con buen score.
    if profile.surprise and len(scored) > top_n:
        bodies_in_top = {_norm(x["car"].get("body_type")) for x in top}
        for cand in scored[top_n:]:
            if _norm(cand["car"].get("body_type")) not in bodies_in_top:
                top[-1] = {**cand, "surprise": True}
                break

    return top


# ════════════════════════════════════════════════════════════════════
# 6) ETIQUETA "MEJOR PARA"  (el eje en que cada opcion gana)
#    Da las 3-5 opciones diferenciadas por filosofia, no clones.
# ════════════════════════════════════════════════════════════════════

def best_for_label(factors):
    """En que eje brilla este carro vs los demas factores. Para la
    columna 'Mejor para' del comparativo."""
    ejes = {
        "reliability": "Tranquilidad",
        "economy": "Ahorro",
        "space": "Familia",
        "value": "Mejor precio",
        "resale": "Inversion",
        "appeal": "Estilo",
    }
    top_factor = max(factors, key=factors.get)
    return ejes.get(top_factor, "Balance")
