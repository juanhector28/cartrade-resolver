import os

os.environ.setdefault("REQUIREMENTS_DB", "/tmp/carly_v33_stress15_requirements.db")
os.environ.setdefault("CACHE_DB", "/tmp/carly_v33_stress15_cache.db")

from app import main_v33 as v32


def body(text: str):
    return {"messages": [{"role": "user", "content": text}], "country": "sv"}


def indexed(**kwargs):
    base = {
        "listing_state": "indexed",
        "is_addressable": True,
        "quality_score": 90,
        "url": "https://example.test/car",
    }
    base.update(kwargs)
    return base


# 1. Typo + punctuation in an exact model must still become a hard exact intent.
def test_01_typo_rav4_is_canonicalized():
    c = v32.v31._constraints(body("Quiero una Toyta RAV-4 automática, máximo US$500 al mes."))
    assert c["exact"][:2] == ("Toyota", "RAV4")
    assert c["monthly_max"] == 500
    assert c["require_transmission"] == "automatic"


# 2. Exact model plus year floor and payment cap must preserve all hard constraints.
def test_02_crv_year_and_payment_are_hard():
    c = v32.v31._constraints(body("Honda CR-V 2024 o más nuevo, automática, máximo $450 al mes."))
    assert c["exact"][:2] == ("Honda", "CR-V")
    assert c["min_year"] == 2024
    assert c["monthly_max"] == 450
    assert c["require_transmission"] == "automatic"


# 3. A strict sedan request must reject a Corolla Cross even if its source body type is wrong.
def test_03_strict_sedan_rejects_corolla_cross():
    c = v32.v31._constraints(body("Solo quiero sedán automático. Máximo US$400 al mes."))
    cross = indexed(make="Toyota", model="Corolla Cross", year=2024, price_usd=13800, monthly_est=328, body_type="sedan", transmission="Automática")
    assert v32._body(cross) == "suv"
    assert not v32.v31._hard_ok(cross, c)


# 4. A strict SUV manual request should reject an automatic SUV.
def test_04_strict_suv_manual_rejects_automatic():
    c = v32.v31._constraints(body("Únicamente SUV manual, máximo $450 al mes."))
    auto = indexed(make="Hyundai", model="Tucson", year=2023, price_usd=15000, monthly_est=357, body_type="suv", transmission="Automática")
    manual = indexed(make="Hyundai", model="Tucson", year=2023, price_usd=15000, monthly_est=357, body_type="suv", transmission="Manual", url="https://example.test/manual")
    assert not v32.v31._hard_ok(auto, c)
    assert v32.v31._hard_ok(manual, c)


# 5. Total purchase budget must not be confused with monthly budget.
def test_05_total_budget_is_enforced():
    c = v32.v31._constraints(body("Tengo hasta US$12,000 para comprar el carro de contado."))
    assert c["total_budget"] == 12000
    expensive = indexed(make="Kia", model="Forte", year=2023, price_usd=13999, body_type="sedan", transmission="Automática")
    affordable = indexed(make="Nissan", model="Versa", year=2022, price_usd=11900, body_type="sedan", transmission="Automática", url="https://example.test/versa")
    assert not v32.v31._hard_ok(expensive, c)
    assert v32.v31._hard_ok(affordable, c)


# 6. Family of six should reject a micro city car and a pickup as primary family recommendations.
def test_06_family_six_rejects_micro_and_pickup():
    c = v32.v31._constraints(body("Somos familia de 6 con dos niños. Máximo US$600 al mes."))
    picanto = indexed(make="Kia", model="Picanto", year=2025, price_usd=14500, body_type="hatchback")
    ranger = indexed(make="Ford", model="Ranger", year=2022, price_usd=21000, body_type="pickup", url="https://example.test/ranger")
    sportage = indexed(make="Kia", model="Sportage", year=2023, price_usd=19000, body_type="suv", url="https://example.test/sportage")
    assert not v32.v31._mission_ok(picanto, c)
    assert not v32.v31._mission_ok(ranger, c)
    assert v32.v31._mission_ok(sportage, c)


# 7. Daily delivery use should favor car formats and reject work pickups.
def test_07_delivery_rejects_pickup():
    c = v32.v31._constraints(body("Lo quiero para delivery todos los días, máximo $250 al mes."))
    hilux = indexed(make="Toyota", model="Hilux", year=2021, price_usd=10000, monthly_est=238, body_type="pickup")
    mirage = indexed(make="Mitsubishi", model="Mirage", year=2024, price_usd=9700, monthly_est=231, body_type="hatchback", url="https://example.test/mirage")
    assert not v32.v31._mission_ok(hilux, c)
    assert v32.v31._mission_ok(mirage, c)


# 8. Finca + rough road + 3 passengers + heavy tools must reject a tiny farm pickup.
def test_08_farm_heavy_tools_rejects_small_pickup_but_accepts_double_cab():
    c = v32.v31._constraints(body("Para finca, calle de grava, 3 pasajeros y herramientas pesadas. Máximo $500 al mes."))
    saveiro = indexed(make="Volkswagen", model="Saveiro", year=2022, price_usd=12000, monthly_est=286, body_type="pickup")
    hilux = indexed(make="Toyota", model="Hilux", year=2021, price_usd=18000, monthly_est=428, body_type="pickup", description="Doble cabina 4x4", url="https://example.test/hilux-double")
    assert not v32.v31._mission_ok(saveiro, c)
    assert v32.v31._mission_ok(hilux, c)


# 9. First-car intent should score a sane sedan above a pickup when both meet budget.
def test_09_first_car_scores_sedan_above_pickup():
    c = v32.v31._constraints(body("Es mi primer carro para moverme en ciudad. Máximo $350 al mes."))
    sedan = indexed(make="Kia", model="Forte", year=2023, price_usd=13999, monthly_est=333, body_type="sedan")
    pickup = indexed(make="Nissan", model="Frontier", year=2017, price_usd=14000, monthly_est=333, body_type="pickup", url="https://example.test/frontier")
    assert v32.v31._score(sedan, c) > v32.v31._score(pickup, c)


# 10. Explicit collision/repair language is an automatic quality veto.
def test_10_damage_language_is_rejected():
    damaged = indexed(make="Nissan", model="Kicks", year=2025, price_usd=14500, body_type="suv", description="Poco daño a reparar")
    assert not v32.v31._quality_ok(damaged)


# 11. Mechanical danger must also be an automatic quality veto.
def test_11_mechanical_danger_is_rejected():
    broken = indexed(make="Chery", model="Tiggo 2", year=2020, price_usd=8400, body_type="suv", description="Solo venta de contado, sin pedal del acelerador")
    assert not v32.v31._quality_ok(broken)


# 12. A recent car at an absurd absolute price is verification territory, never Top 3.
def test_12_absolute_price_anomaly_is_rejected():
    sentra = indexed(make="Nissan", model="Sentra", year=2020, price_usd=500, body_type="sedan")
    assert v32._price_anomaly(sentra, [sentra])


# 13. Peer pricing should catch a suspicious discount even when it clears the absolute floor.
def test_13_peer_median_catches_suspicious_discount():
    suspicious = indexed(make="Toyota", model="Hilux", year=2021, price_usd=7000, body_type="pickup")
    peers = [
        suspicious,
        indexed(make="Toyota", model="Hilux", year=2020, price_usd=16500, body_type="pickup", url="https://example.test/h1"),
        indexed(make="Toyota", model="Hilux", year=2021, price_usd=18000, body_type="pickup", url="https://example.test/h2"),
        indexed(make="Toyota", model="Hilux", year=2022, price_usd=17500, body_type="pickup", url="https://example.test/h3"),
    ]
    assert v32._price_anomaly(suspicious, peers)


# 14. After an exact miss, alternatives may relax model but must preserve SUV/year/payment constraints.
def test_14_exact_miss_relaxes_model_only():
    c = v32.v31._constraints(body("Busco Honda CR-V 2024 o más nuevo, máximo $450 al mes. Muéstrame alternativas si no hay."))
    alt = v32._effective_constraints(c, exact_miss=True)
    good = indexed(make="Mazda", model="CX-30", year=2024, price_usd=17000, monthly_est=405, body_type="suv")
    old = indexed(make="Mazda", model="CX-30", year=2023, price_usd=16000, monthly_est=381, body_type="suv", url="https://example.test/old")
    over = indexed(make="Kia", model="Sportage", year=2024, price_usd=20000, monthly_est=476, body_type="suv", url="https://example.test/over")
    sedan = indexed(make="Toyota", model="Corolla", year=2024, price_usd=15000, monthly_est=357, body_type="sedan", url="https://example.test/sedan")
    assert alt["exact"] is None and alt["require_body"] == "suv"
    assert v32.v31._hard_ok(good, alt)
    assert not v32.v31._hard_ok(old, alt)
    assert not v32.v31._hard_ok(over, alt)
    assert not v32.v31._hard_ok(sedan, alt)


# 15. Contradictory hard constraints must not leak a superficially attractive exact model.
def test_15_contradictory_sedan_plus_rav4_does_not_surface_rav4():
    c = v32.v31._constraints(body("Solo quiero sedán, pero que sea Toyota RAV4. Máximo $500 al mes."))
    rav4 = indexed(make="Toyota", model="RAV4", year=2022, price_usd=18000, monthly_est=428, body_type="suv")
    assert c["exact"][:2] == ("Toyota", "RAV4")
    assert c["require_body"] == "sedan"
    assert not v32.v31._hard_ok(rav4, c)
