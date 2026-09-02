import os

os.environ.setdefault("REQUIREMENTS_DB", "/tmp/carly_v34_requirements.db")
os.environ.setdefault("CACHE_DB", "/tmp/carly_v34_cache.db")

from app import main_v34 as v34


def body(text: str):
    return {"messages": [{"role": "user", "content": text}], "country": "sv"}


def test_hrv_is_exact_honda_model():
    c = v34.v31._constraints(body("Honda HR-V 2023 o más nueva. No quiero manual; automática está bien. Máximo $450 al mes."))
    assert c["exact"] == ("Honda", "HR-V", "suv")
    assert c["min_year"] == 2023
    assert c["require_transmission"] == "automatic"
    assert c["monthly_max"] == 450


def test_hrv_compact_spelling_is_exact_too():
    c = v34.v31._constraints(body("Solo HRV 2024, máximo $500 al mes."))
    assert c["exact"] == ("Honda", "HR-V", "suv")


def test_url_a_reparar_is_severe_risk():
    card = {
        "make": "Kia", "model": "Soul", "year": 2023, "price_usd": 9600,
        "url": "https://www.encuentra24.com/el-salvador-es/autos-usados/kia-soul-2023-automatico-bolsas-buenas-a-reparar-ya-esta-fuera-de-aduana/32754961",
    }
    assert v34.v28._hard_risk(card, card)
    assert not v34.v31._quality_ok(card)


def test_url_poco_dano_is_severe_risk():
    card = {
        "make": "Nissan", "model": "Kicks", "year": 2025, "price_usd": 14500,
        "url": "https://example.test/nissan-kicks-2025-poco-dano-a-reparar",
    }
    assert v34.v28._hard_risk(card, card)


def test_exact_empty_reply_does_not_claim_visible_alternatives():
    c = v34.v31._constraints(body("Solo Toyota RAV4 2022 o más nueva, máximo $500 al mes."))
    reply = v34.v31._reply(c, [], exact_miss=True)
    assert "opciones que ves" not in reply.lower()
    assert "no encontré" in reply.lower()


def test_generic_empty_reply_is_truthful():
    c = v34.v31._constraints(body("Solo SUV manual 2021 o más nueva, máximo $400 al mes."))
    reply = v34.v31._reply(c, [], exact_miss=False)
    assert "no encontré unidades" in reply.lower()
    assert "lo que ves cumple" not in reply.lower()
