import os
from types import SimpleNamespace

os.environ.setdefault("CACHE_DB", "/tmp/carly-v51-cache.db")
os.environ.setdefault("TRUSTPLUS_DB", "/tmp/carly-v51-trustplus.db")
os.environ.setdefault("CARLY_VISION_JIT_ENABLED", "0")

from app import main_v14 as v14
from app import main_v51 as v51
from app import carly_v52_hotfix as v52


def _family_constraints(passengers=None):
    return {
        "exact": None,
        "intent": {
            "heavy_cargo": False,
            "farm": False,
            "rough": False,
            "student": False,
            "comfort": False,
        },
        "family": True,
        "passengers": passengers,
        "delivery": False,
        "require_body": None,
        "require_transmission": None,
    }


def _candidate():
    return {"make": "Mazda", "model": "CX-30", "year": 2023}


def test_family_intent_without_explicit_size_never_claims_five():
    reply = v51._truthful_reply(_family_constraints(), [_candidate()])
    assert "familia de cinco" not in reply.lower()
    assert "uso familiar" in reply.lower()


def test_explicit_family_of_five_can_keep_five_person_wording():
    reply = v51._truthful_reply(_family_constraints(5), [_candidate()])
    assert "familia de cinco" in reply.lower()


def test_exact_opening_search_is_buyer_only_and_zero_token():
    body = SimpleNamespace(
        country="gt",
        messages=[{"role": "user", "content": "Busco un Mazda SUV entre USD 12,000 y 25,000 en Guatemala"}],
        shown_cars=[],
    )
    out = v52.opening_search_response(body)
    assert out is not None
    assert out["llm_calls"] == 0
    assert out["token_path"] == "deterministic_opening_truth_v52"
    reply = out["reply"].lower()
    assert "mazda suv" in reply
    assert "12,000" in reply and "25,000" in reply
    assert "100 km" not in reply
    assert "ya sé" not in reply
    assert "para qué lo vas a usar" in reply


def _detail_body():
    prompt = "Cuéntame más del Mazda CX-30 2024: ¿por qué me lo recomiendas y qué debería preocuparme?"
    return SimpleNamespace(
        country="gt",
        messages=[
            {"role": "user", "content": "Busco un Mazda SUV entre USD 12,000 y 25,000 en Guatemala"},
            {"role": "assistant", "content": "¿Para qué lo vas a usar principalmente?"},
            {"role": "user", "content": "trabajo y dejar a mis hijos al colegio"},
            {"role": "assistant", "content": "¿Qué cuota mensual te queda cómoda?"},
            {"role": "user", "content": "550 al mes"},
            {"role": "assistant", "content": "Te muestro mis mejores opciones."},
            {"role": "user", "content": prompt},
        ],
        shown_cars=[
            {
                "url": "https://example.test/cx30",
                "make": "Mazda",
                "model": "CX-30",
                "year": 2024,
                "price_usd": 20800,
                "monthly_est": 494,
                "km": 31741,
                "body_type": "suv",
            },
            {
                "url": "https://example.test/cx5",
                "make": "Mazda",
                "model": "CX-5",
                "year": 2024,
                "price_usd": 22800,
                "monthly_est": 540,
                "km": 45000,
                "body_type": "suv",
            },
        ],
    )


def test_production_vehicle_brief_is_concrete_not_generic():
    out = v14._advisor_brief(_detail_body())
    assert out is not None
    assert out["advisor_mode"] == "comparative_vehicle_brief_v52"
    assert out["llm_calls"] == 0
    reply = out["reply"].lower()
    assert "trabajo" in reply and "colegio" in reply
    assert "31,741 km" in reply
    assert "$494/mes" in reply
    assert "$56/mes de margen" in reply
    assert "cx-5 2024" in reply
    assert "$46/mes menos" in reply
    assert "puede encajar por precio y disponibilidad" not in reply
    assert "necesita más evidencia antes de saber" not in reply
    assert "familia de cinco" not in reply
    assert "\n\n" in out["reply"]


def test_model_intelligence_detection_covers_model_questions_not_unit_questions():
    assert v52._is_model_intelligence("¿Cuáles son los pros y contras de este modelo?")
    assert v52._is_model_intelligence("¿Qué problemas conocidos tiene este modelo?")
    assert v52._is_model_intelligence("¿Qué tal sale este modelo?")
    assert v52._is_model_intelligence("¿Cómo es la confiabilidad del Honda HR-V 2023?")
    assert not v52._is_model_intelligence("¿Es buena compra esta unidad?")
    assert not v52._is_model_intelligence("¿Qué opinas de este anuncio?")


def test_model_intelligence_bypasses_unit_brief():
    body = _detail_body()
    body.messages[-1] = {
        "role": "user",
        "content": "Cuéntame los pros y contras del Mazda CX-30 2024 como modelo",
    }
    assert v52.advisor_brief(body) is None
    assert v14._advisor_brief(body) is None


def test_model_intelligence_prompt_is_installed_on_compact_followup_path():
    decision = v52.v50.v47.commercial.preview.room.state.decision
    prompt = str(decision._LOW_TOKEN_FOLLOWUP_PROMPT)
    assert "# MODEL INTELLIGENCE" in prompt
    assert "pros/contras DEL MODELO" in prompt
    assert "No abras con precio" in prompt


def test_production_route_installs_v52_over_v51():
    route = next(r for r in v51.app.routes if getattr(r, "path", None) == "/carly/chat")
    assert getattr(route.endpoint, "_carly_v52_opening_truth", False) is True
    prior = getattr(route.endpoint, "_carly_v52_prior", None)
    assert getattr(prior, "_carly_v51_vehicle_detail", False) is True
