import os

os.environ.setdefault("REQUIREMENTS_DB", "/tmp/carly_v33_complex15_requirements.db")
os.environ.setdefault("CACHE_DB", "/tmp/carly_v33_complex15_cache.db")

from app import main_v33 as v33


def body(text: str):
    return {"messages": [{"role": "user", "content": text}], "country": "sv"}


def indexed(**kwargs):
    base = {
        "listing_state": "indexed",
        "is_addressable": True,
        "quality_score": 90,
        "url": "https://example.test/base",
    }
    base.update(kwargs)
    return base


# 1. Exact model + year + transmission + total budget + monthly ceiling must coexist.
def test_01_exact_rav4_with_mixed_hard_constraints():
    c = v33.v31._constraints(body("Toyota RAV4 2022 o más nueva, automática. Presupuesto total US$20,000 y máximo $500 al mes."))
    assert c["exact"][:2] == ("Toyota", "RAV4")
    assert c["min_year"] == 2022
    assert c["require_transmission"] == "automatic"
    assert c["total_budget"] == 20000
    assert c["monthly_max"] == 500


# 2. A clearly softened transmission preference must not become a hard veto.
def test_02_soft_transmission_preference_stays_soft():
    c = v33.v31._constraints(body("Quiero Honda CR-V 2024 o más nueva. Preferiría automática si se puede, máximo $500 al mes."))
    assert c["exact"][:2] == ("Honda", "CR-V")
    assert c["require_transmission"] is None


# 3. Natural '15 mil' cash language must be parsed as total budget.
def test_03_total_budget_with_mil_suffix():
    c = v33.v31._constraints(body("Cuento con 15 mil para comprar el carro de contado."))
    assert c["total_budget"] == 15000


# 4. 'No quiero pasar de' is a normal hard purchase ceiling.
def test_04_total_budget_no_quiero_pasar_de():
    c = v33.v31._constraints(body("No quiero pasar de US$14,500 por el carro."))
    assert c["total_budget"] == 14500


# 5. LATAM thousands separator should not turn 12.500 into twelve dollars.
def test_05_total_budget_dot_thousands_separator():
    c = v33.v31._constraints(body("Mi presupuesto total es de US$12.500 al contado."))
    assert c["total_budget"] == 12500


# 6. Explicit manual transmission on an exact model is hard.
def test_06_exact_tacoma_manual_is_hard():
    c = v33.v31._constraints(body("Toyota Tacoma 2020 o más nueva, manual, máximo $550 al mes."))
    assert c["exact"][:2] == ("Toyota", "Tacoma")
    assert c["require_transmission"] == "manual"


# 7. If the buyer explicitly says either transmission is fine, do not invent a constraint.
def test_07_auto_or_manual_me_da_igual_is_not_hard():
    c = v33.v31._constraints(body("SUV 2022 o más nueva. Automática o manual me da igual. Máximo $450 al mes."))
    assert c["require_transmission"] is None


# 8. Rejecting automatic while naming manual should resolve to manual.
def test_08_negative_auto_resolves_to_manual():
    c = v33.v31._constraints(body("No quiero automática; manual está bien. Máximo $400 al mes."))
    assert c["require_transmission"] == "manual"


# 9. Rejecting manual while naming automatic should resolve to automatic.
def test_09_negative_manual_resolves_to_automatic():
    c = v33.v31._constraints(body("No quiero manual; automática está bien. Máximo $400 al mes."))
    assert c["require_transmission"] == "automatic"


# 10. Four simultaneous hard filters must all be enforced on each candidate.
def test_10_strict_suv_auto_year_payment_all_apply():
    c = v33.v31._constraints(body("Solo SUV automática 2022 o más nueva, máximo $450 al mes."))
    good = indexed(make="Hyundai", model="Tucson", body_type="suv", transmission="Automática", year=2023, monthly_est=420, price_usd=17600)
    sedan = indexed(make="Toyota", model="Corolla", body_type="sedan", transmission="Automática", year=2023, monthly_est=350, price_usd=14700, url="https://example.test/sedan")
    manual = indexed(make="Hyundai", model="Tucson", body_type="suv", transmission="Manual", year=2023, monthly_est=420, price_usd=17600, url="https://example.test/manual")
    old = indexed(make="Hyundai", model="Tucson", body_type="suv", transmission="Automática", year=2021, monthly_est=380, price_usd=16000, url="https://example.test/old")
    over = indexed(make="Kia", model="Sportage", body_type="suv", transmission="Automática", year=2023, monthly_est=475, price_usd=19900, url="https://example.test/over")
    assert v33.v31._hard_ok(good, c)
    assert not v33.v31._hard_ok(sedan, c)
    assert not v33.v31._hard_ok(manual, c)
    assert not v33.v31._hard_ok(old, c)
    assert not v33.v31._hard_ok(over, c)


# 11. Exact miss may relax model, but not body/year/payment/transmission.
def test_11_exact_miss_preserves_transmission_and_other_hards():
    c = v33.v31._constraints(body("Honda CR-V 2024 o más nueva, automática, máximo $450 al mes. Si no hay, dame alternativas."))
    alt = v33._effective_constraints(c, True)
    good = indexed(make="Honda", model="HR-V", body_type="suv", transmission="Automática", year=2024, monthly_est=430, price_usd=18000)
    manual = indexed(make="Honda", model="HR-V", body_type="suv", transmission="Manual", year=2024, monthly_est=430, price_usd=18000, url="https://example.test/manual-hrv")
    assert alt["exact"] is None
    assert alt["require_body"] == "suv"
    assert alt["require_transmission"] == "automatic"
    assert v33.v31._hard_ok(good, alt)
    assert not v33.v31._hard_ok(manual, alt)


# 12. Family mission + explicit transmission should jointly reject tiny/manual options.
def test_12_family_five_baby_auto_combines_mission_and_hard_filter():
    c = v33.v31._constraints(body("Somos 5 con un bebé. Quiero automática y no más de $500 al mes."))
    picanto = indexed(make="Kia", model="Picanto", body_type="hatchback", transmission="Automática", year=2025, monthly_est=345, price_usd=14500)
    manual_hrv = indexed(make="Honda", model="HR-V", body_type="suv", transmission="Manual", year=2023, monthly_est=426, price_usd=17900, url="https://example.test/manual-hrv")
    auto_hrv = indexed(make="Honda", model="HR-V", body_type="suv", transmission="Automática", year=2023, monthly_est=426, price_usd=17900, url="https://example.test/auto-hrv")
    assert not v33.v31._mission_ok(picanto, c)
    assert not v33.v31._hard_ok(manual_hrv, c)
    assert v33.v31._hard_ok(auto_hrv, c) and v33.v31._mission_ok(auto_hrv, c)


# 13. Delivery can carry total-price, monthly and transmission limits simultaneously.
def test_13_delivery_mixed_budget_and_transmission():
    c = v33.v31._constraints(body("Para delivery diario, automática. Presupuesto total 10 mil y máximo $250 al mes."))
    good = indexed(make="Mitsubishi", model="Mirage", body_type="hatchback", transmission="Automática", year=2024, price_usd=9700, monthly_est=231)
    expensive = indexed(make="Kia", model="Rio", body_type="hatchback", transmission="Automática", year=2023, price_usd=10500, monthly_est=249, url="https://example.test/rio")
    pickup = indexed(make="Toyota", model="Hilux", body_type="pickup", transmission="Automática", year=2018, price_usd=9500, monthly_est=226, url="https://example.test/hilux")
    assert c["total_budget"] == 10000 and c["monthly_max"] == 250
    assert v33.v31._hard_ok(good, c) and v33.v31._mission_ok(good, c)
    assert not v33.v31._hard_ok(expensive, c)
    assert not v33.v31._mission_ok(pickup, c)


# 14. Rough finca + four passengers + heavy cargo + automatic requires the right pickup class.
def test_14_finca_four_people_heavy_cargo_auto():
    c = v33.v31._constraints(body("Finca con grava y lodo, 4 pasajeros, herramientas pesadas. Automática, máximo $550 al mes."))
    saveiro = indexed(make="Volkswagen", model="Saveiro", body_type="pickup", transmission="Automática", year=2022, price_usd=12000, monthly_est=286)
    manual_frontier = indexed(make="Nissan", model="Frontier", body_type="pickup", transmission="Manual", year=2022, price_usd=19000, monthly_est=452, description="Doble cabina 4x4", url="https://example.test/frontier-manual")
    auto_frontier = indexed(make="Nissan", model="Frontier", body_type="pickup", transmission="Automática", year=2022, price_usd=19000, monthly_est=452, description="Doble cabina 4x4", url="https://example.test/frontier-auto")
    assert not v33.v31._mission_ok(saveiro, c)
    assert not v33.v31._hard_ok(manual_frontier, c)
    assert v33.v31._hard_ok(auto_frontier, c) and v33.v31._mission_ok(auto_frontier, c)


# 15. Exact-model ranking must still eject damaged and absurdly-priced exact listings.
def test_15_exact_search_quality_and_price_gates_beat_exact_match():
    c = v33.v31._constraints(body("Solo Toyota RAV4 automática, máximo $500 al mes y no quiero pasar de $20,000."))
    cheap = indexed(make="Toyota", model="RAV4", body_type="suv", transmission="Automática", year=2020, price_usd=1200, monthly_est=29, url="https://example.test/cheap")
    damaged = indexed(make="Toyota", model="RAV4", body_type="suv", transmission="Automática", year=2022, price_usd=17000, monthly_est=405, description="Poco daño a reparar", url="https://example.test/damaged")
    clean = indexed(make="Toyota", model="RAV4", body_type="suv", transmission="Automática", year=2022, price_usd=18500, monthly_est=440, url="https://example.test/clean")
    ranked, filtered = v33._rank_rows([cheap, damaged, clean], c)
    assert [r["url"] for r in ranked] == ["https://example.test/clean"]
    assert filtered == 2
