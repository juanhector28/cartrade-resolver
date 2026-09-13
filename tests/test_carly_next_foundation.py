from app.carly_next.parser import build_state

def test_market_radius_is_not_daily_km():
    state = build_state(({"role":"user","content":"Busco un Mazda SUV"},), {"country":"GT","radius_km":100})
    assert state.value("daily_km") is None

def test_family_does_not_invent_passengers():
    state = build_state(({"role":"user","content":"Quiero un SUV para mi familia"},), {"country":"GT"})
    assert state.value("passengers") is None
