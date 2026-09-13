import os
import time
from types import SimpleNamespace

os.environ.setdefault("CACHE_DB", "/tmp/carly-v51-cache.db")
os.environ.setdefault("TRUSTPLUS_DB", "/tmp/carly-v51-trustplus.db")
os.environ.setdefault("CARLY_VISION_JIT_ENABLED", "0")

from app import main_v14 as v14
from app import main_v51 as v51
from app import carly_v52_hotfix as v52
from app import carly_v53_latency as v53
from app import carly_v54_more_options as v54
from app import carly_v55_model_intelligence as v55


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
    assert getattr(route.endpoint, "_carly_v54_more_options", False) is True
    v54_prior = getattr(route.endpoint, "_carly_v54_prior", None)
    assert getattr(v54_prior, "_carly_v52_opening_truth", False) is True
    prior = getattr(v54_prior, "_carly_v52_prior", None)
    assert getattr(prior, "_carly_v51_vehicle_detail", False) is True


def test_v53_installs_bounded_scanner_under_existing_v41_wrapper():
    assert getattr(v53.v41, "_carly_v53_bounded_vision", False) is True
    assert v53.v41._ORIG_SCAN_UNCACHED is v53._bounded_scan_uncached_finalists
    assert 0 <= v53.INLINE_MAX_LISTINGS <= 3
    assert v53.INLINE_BUDGET_SECONDS <= 8.0


def test_v53_slow_vision_cannot_hold_interactive_request_open(monkeypatch):
    monkeypatch.setattr(v53.v36, "JIT_ENABLED", True)
    monkeypatch.setattr(v53, "INLINE_BUDGET_SECONDS", 0.02)
    monkeypatch.setattr(v53, "INLINE_MAX_LISTINGS", 1)

    def slow_vision(_row):
        time.sleep(0.18)
        return None

    monkeypatch.setattr(v53.v36, "_vision_result", slow_vision)
    row = {
        "id": 1,
        "url": "https://example.test/pickup",
        "primary_photo": "https://example.test/pickup.jpg",
        "visible_damage_risk": None,
    }
    started = time.monotonic()
    completed = v53._bounded_scan_uncached_finalists([row])
    elapsed = time.monotonic() - started

    assert completed == 0
    assert elapsed < 0.10


def _more_options_body():
    return SimpleNamespace(
        country="gt",
        messages=[
            {"role": "user", "content": "SUV cómodo para la ciudad"},
            {"role": "assistant", "content": "¿Qué cuota mensual te queda cómoda?"},
            {"role": "user", "content": "500-600"},
            {"role": "assistant", "content": "Estas son mis mejores recomendaciones."},
            {
                "role": "user",
                "content": "Muéstrame más opciones que mantengan mis criterios, incluyendo alternativas con distintos trade-offs.",
            },
        ],
        shown_cars=[
            {"id": "hrv", "make": "Honda", "model": "HR-V", "year": 2022, "body_type": "suv"},
            {"id": "cx30", "make": "Mazda", "model": "CX-30", "year": 2024, "body_type": "suv"},
            {"id": "hrv-ex", "make": "Honda", "model": "HR-V EX", "year": 2020, "body_type": "suv"},
        ],
    )


def test_v54_detects_exact_demo_more_options_turn():
    body = _more_options_body()
    assert v54._is_more_options(body) is True
    body.shown_cars = []
    assert v54._is_more_options(body) is False


def test_v54_more_options_returns_fresh_continuation_not_generic(monkeypatch):
    body = _more_options_body()
    fresh = [
        {"id": "rav4", "make": "Toyota", "model": "RAV4", "year": 2021},
        {"id": "tucson", "make": "Hyundai", "model": "Tucson", "year": 2022},
    ]
    monkeypatch.setattr(v54.v16, "_dynamic_search", lambda _body: {
        "phase": "recommendation",
        "recommendations": fresh,
        "explore": [],
        "more_options_available": True,
        "more_options_count": 4,
    })
    out = v54._continuation(body)
    assert out is not None
    assert out["route_precedence"] == "more_options_v54"
    assert out["append_recommendations"] is True
    assert out["replace_recommendations"] is False
    assert out["llm_calls"] == 0
    assert "2 opciones adicionales" in out["reply"]
    assert "Tomé tus requisitos como filtros duros" not in out["reply"]


def _model_intelligence_body():
    hidden = (
        "[CONTEXTO ACTIVO DE CARTRADE: estás viendo recomendaciones con precio, kilometraje y cuota. "
        "La interfaz también mantiene la posibilidad de ver más opciones. "
        "FOLLOW-UP INTENT = MODEL_INTELLIGENCE.]"
    )
    return SimpleNamespace(
        country="gt",
        messages=[
            {"role": "user", "content": "SUV familiar para llevar a mis hijos"},
            {"role": "assistant", "content": "¿Qué cuota mensual te queda cómoda?"},
            {"role": "user", "content": "650"},
            {"role": "assistant", "content": "Estas son mis mejores recomendaciones."},
            {"role": "user", "content": "Dame los pros y cons del Honda HR-V 2023\n\n" + hidden},
        ],
        shown_cars=[
            {
                "id": "hrv23",
                "url": "https://example.test/hrv23",
                "make": "Honda",
                "model": "HR-V",
                "year": 2023,
                "km": 19,
                "monthly_est": 402,
                "price_usd": 16900,
                "body_type": "suv",
            },
            {
                "id": "hrv22",
                "url": "https://example.test/hrv22",
                "make": "Honda",
                "model": "HR-V",
                "year": 2022,
                "km": 38000,
                "monthly_est": 362,
                "price_usd": 15200,
                "body_type": "suv",
            },
        ],
    )


def test_v55_classifies_visible_buyer_text_not_hidden_frontend_context():
    body = _model_intelligence_body()
    assert v55._latest_buyer_text(body) == "Dame los pros y cons del Honda HR-V 2023"
    assert v55._is_model_intelligence(body) is True
    # Hidden UI metadata says "ver más opciones"; it must not hijack routing.
    assert v54._is_more_options(body) is False


def test_v55_model_intelligence_gets_outer_precedence_and_clean_prompt(monkeypatch):
    body = _model_intelligence_body()
    captured = {}
    decision = v55.v50.v47.commercial.preview.room.state.decision

    def fake_followup(clean_body):
        captured["latest"] = clean_body.messages[-1]["content"]
        return {
            "phase": "conversation",
            "reply": "LO MEJOR · Buen espacio y practicidad. LO MENOS BUENO · No prioriza desempeño.",
            "token_path": "compact_llm",
        }

    monkeypatch.setattr(decision, "_answer_followup_integrity", fake_followup)
    out = v55._model_intelligence_response(body)
    assert out is not None
    assert out["route_precedence"] == "model_intelligence_v55"
    assert out["model_scope"] is True
    assert "[CONTEXTO ACTIVO" not in captured["latest"]
    assert "precio" not in captured["latest"].lower()
    assert "vin" not in captured["latest"].lower()
    assert "pros y cons" in captured["latest"].lower()


def test_v55_does_not_intercept_unit_purchase_question():
    body = _model_intelligence_body()
    body.messages[-1]["content"] = (
        "¿Es buena compra esta unidad?\n\n"
        "[CONTEXTO ACTIVO DE CARTRADE: FOLLOW-UP INTENT = UNIT_ASSESSMENT.]"
    )
    assert v55._is_model_intelligence(body) is False


def test_v55_is_outermost_production_route_guard():
    route = next(r for r in v51.app.routes if getattr(r, "path", None) == "/carly/chat")
    assert getattr(route.endpoint, "_carly_v55_model_intelligence", False) is True
