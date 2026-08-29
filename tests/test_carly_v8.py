from app import carly_fastpath
from app import main_v8


FRONTEND_NOTE = (
    "\n\n[CONTEXTO ACTIVO DE CARTRADE: ubicación seleccionada por el usuario = "
    "San Salvador, El Salvador; país/código = sv; radio = 100 km. "
    "MODO CARLY: conserva un tono conversacional y directo. No repitas preguntas ya respondidas.]"
)


def _live_second_turn(include_assistant=True):
    rows = [
        {"role": "user", "content": "Busco un compacto para ciudad, económico y fácil de estacionar"},
    ]
    if include_assistant:
        rows.append({"role": "assistant", "content": "Entendido. ¿Qué cuota mensual te queda cómoda?"})
    rows.append({"role": "user", "content": "500" + FRONTEND_NOTE})
    return rows


def test_fastpath_reads_visible_500_not_frontend_context_suffix():
    profile = carly_fastpath.extract_fast_profile(_live_second_turn(), country="sv")
    assert profile is not None
    assert profile["max_monthly"] == 500
    assert profile["primary_job"] == "city_runabout"
    assert profile["daily_km"] is None


def test_v7_stale_card_detector_now_accepts_exact_frontend_payload():
    assert main_v8.v7._is_high_confidence_intake_turn(_live_second_turn(), country="sv") is True


def test_missing_assistant_repair_also_handles_frontend_suffix():
    messages = _live_second_turn(include_assistant=False)
    repaired = main_v8.commercial._repair_missing_monthly_context(messages, country="sv")
    profile = carly_fastpath.extract_fast_profile(repaired, country="sv")
    assert profile is not None
    assert profile["max_monthly"] == 500


def test_frontend_radius_is_not_misread_as_daily_usage():
    profile = carly_fastpath.extract_fast_profile(_live_second_turn(), country="sv")
    assert profile["daily_km"] is None
