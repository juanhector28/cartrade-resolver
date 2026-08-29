from types import SimpleNamespace

from app import main_v15 as v15


def _car(i, year=2022):
    return {
        "id": str(i),
        "url": f"https://cars.test/{i}",
        "make": "Suzuki",
        "model": f"Alto {i}",
        "year": year,
        "km": 20000 + i,
        "price_usd": 7000 + i,
        "body_type": "hatchback",
    }


def test_continuation_intent_spanish():
    assert v15._is_continuation("Muéstrame las siguientes 6 opciones que mantienen mis criterios, sin repetir ninguna de las anteriores.")
    assert v15._is_continuation("Ver 6 más")
    assert not v15._is_continuation("Cuéntame más del Suzuki Alto")


def test_continuation_excludes_seen_and_returns_six(monkeypatch):
    shown = [_car(1), _car(2), _car(3)]
    pool = shown + [_car(i) for i in range(4, 14)]
    body = SimpleNamespace(
        shown_cars=shown,
        country="sv",
        messages=[{"role": "user", "content": "Muéstrame las siguientes 6 opciones sin repetir ninguna anterior"}],
    )
    profile = SimpleNamespace(primary_job="city_runabout", max_monthly=None, prefer_body=[], require_body=[])

    monkeypatch.setattr(v15, "_latest", lambda body: body.messages[-1]["content"])
    monkeypatch.setattr(v15, "_profile", lambda body, visible: profile)
    monkeypatch.setattr(v15.commercial.legacy, "_carly_inventory", lambda profile, country=None: pool)
    monkeypatch.setattr(v15.commercial.legacy, "_carly_card", lambda row: dict(row))

    result = v15._continuation(body)
    urls = [c["url"] for c in result["recommendations"]]

    assert result["phase"] == "recommendation"
    assert result["llm_calls"] == 0
    assert result["token_path"] == "deterministic_continuation"
    assert len(urls) == 6
    assert not ({c["url"] for c in shown} & set(urls))
    assert result["more_options_count"] == 4


def test_continuation_truthfully_exhausts(monkeypatch):
    shown = [_car(1), _car(2), _car(3)]
    body = SimpleNamespace(
        shown_cars=shown,
        country="sv",
        messages=[{"role": "user", "content": "Ver 6 más"}],
    )
    profile = SimpleNamespace(primary_job="city_runabout", max_monthly=None, prefer_body=[], require_body=[])

    monkeypatch.setattr(v15, "_latest", lambda body: "Ver 6 más")
    monkeypatch.setattr(v15, "_profile", lambda body, visible: profile)
    monkeypatch.setattr(v15.commercial.legacy, "_carly_inventory", lambda profile, country=None: shown)

    result = v15._continuation(body)
    assert result["continuation_exhausted"] is True
    assert result["more_options_available"] is False
    assert result["more_options_count"] == 0
    assert result["llm_calls"] == 0
