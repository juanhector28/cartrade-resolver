import asyncio
from types import SimpleNamespace

from app import inventory_maintenance as maintenance


def test_failure_advances_rotation_and_survives_restart():
    states = {"cr": {"last_attempt_at": "2026-10-04T04:00:00Z", "state": "failed"}}
    countries = ["cr", "sv", "pa"]
    assert maintenance.next_country(countries, states) == "sv"
    persisted = __import__("json").loads(__import__("json").dumps(states))
    assert maintenance.next_country(countries, persisted) == "sv"
    states["sv"] = {"last_attempt_at": "2026-10-04T04:30:00Z", "state": "failed"}
    assert maintenance.next_country(countries, states) == "pa"


def test_zero_writes_and_partial_failures_are_not_success():
    assert maintenance.completion({"saved_count": 0, "error_count": 0}) == "failed"
    assert maintenance.completion({"saved_count": 2, "error_count": 1}) == "partial"
    assert maintenance.completion({"saved_count": 2}, "HTTP 403") == "failed"
    assert maintenance.completion({"saved_count": 2}) == "succeeded"


def test_search_page_returning_200_does_not_renew_vehicle():
    from app.scrapers.crautos import crautos_scraper
    html = '<h1>Autos Usados</h1><p>Precio ($27,174)</p>'
    assert not maintenance.valid_crautos_detail(crautos_scraper.parse_detail(html, "123"))


def test_existing_refresh_does_not_change_freshness_on_unverified_detail(monkeypatch):
    calls = []
    states = {}
    class Query:
        def __getattr__(self, name):
            def call(*args, **kwargs):
                if name == "update": calls.append(args[0])
                return self
            return call
        def execute(self): return SimpleNamespace(data=[{"id": 42, "url": "https://crautos.com/autosusados/cardetail.cfm?c=123"}])
    db = SimpleNamespace(table=lambda _: Query())
    session = SimpleNamespace(get=lambda *a, **k: SimpleNamespace(text='<h1>Autos Usados</h1>', raise_for_status=lambda: None), close=lambda: None)
    from app.scrapers.crautos import crautos_scraper
    monkeypatch.setattr(crautos_scraper, "make_session", lambda: session)
    monkeypatch.setattr(maintenance, "read_states", lambda _: states)
    monkeypatch.setattr(maintenance, "write_state", lambda db, key, state: states.update({key: dict(state)}))
    monkeypatch.setattr(maintenance.time, "sleep", lambda _: None)
    from app import parsers
    result = maintenance.crautos_batch(SimpleNamespace(supabase=db, parsers=parsers), size=1)
    assert calls == []
    assert result["state"] == "failed" and result["cursor_id"] == 42


def test_runner_records_failure_without_claiming_refresh(monkeypatch):
    states = {}
    async def failed(country, pages):
        main.INVENTORY_JOB_STATUS.update(last_error="cr: HTTP 403", results={})
    class App:
        def get(self, *a, **k): return lambda f: f
        def on_event(self, *a, **k): return lambda f: f
    main = SimpleNamespace(app=App(), supabase=object(), CA_COUNTRIES=["cr", "sv"],
        _run_one=failed, _run_all_ca=failed, INVENTORY_JOB_STATUS={"results": {}})
    monkeypatch.setattr(maintenance, "read_states", lambda _: states)
    monkeypatch.setattr(maintenance, "write_state", lambda db, key, state: states.update({key: dict(state)}))
    maintenance.install(main)
    asyncio.run(main._run_one("cr", 1))
    assert states["cr"]["state"] == "failed"
    assert "last_success_at" not in states["cr"]
    assert asyncio.run(main._pick_next_country()) == "sv"
