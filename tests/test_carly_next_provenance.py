from app.carly_next.parser import build_state

def test_explicit_daily_km_has_user_provenance():
    state = build_state(({"role":"user","content":"Manejo 100 km al día y busco un Mazda SUV"},), {"country":"GT"})
    assert state.value("daily_km") == 100
    assert state.hard["daily_km"].provenance.source == "user"

def test_explicit_family_count_is_kept():
    state = build_state(({"role":"user","content":"Somos familia de 5 y queremos un SUV"},), {"country":"GT"})
    assert state.value("passengers") == 5
