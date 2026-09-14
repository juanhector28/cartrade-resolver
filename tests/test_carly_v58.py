from app import carly_v58_conversation_scope as v58


def body(*messages):
    return {"country": "gt", "messages": list(messages)}


def u(text):
    return {"role": "user", "content": text}


def a(text):
    return {"role": "assistant", "content": text}


def test_model_only_turn_stays_in_conversation_instead_of_inventory_miss():
    b = body(u("Toyota Corolla"))
    reply = v58._scope_intake_reply(b)
    assert reply == "Perfecto, tomo Toyota Corolla como tu preferencia. ¿Para qué lo vas a usar principalmente?"
    assert "No encontré" not in reply


def test_cualquier_toyota_releases_stale_corolla_scope():
    b = body(
        u("Toyota Corolla"),
        a("¿Para qué lo vas a usar principalmente?"),
        u("Cualquier toyota"),
    )
    c = v58._constraints(b)
    assert c["exact"] is None
    assert c["require_brand"] == "Toyota"
    assert c["vehicle_scope_broadened"] is True
    reply = v58._scope_intake_reply(b)
    assert "cualquier Toyota" in reply
    assert "Corolla" not in reply


def test_cualquier_modelo_keeps_make_but_releases_exact_model():
    b = body(
        u("Toyota Corolla"),
        a("¿Para qué lo vas a usar principalmente?"),
        u("Cualquier modelo"),
    )
    c = v58._constraints(b)
    assert c["exact"] is None
    assert c["require_brand"] == "Toyota"


def test_scope_turn_with_use_but_no_budget_asks_one_budget_question():
    b = body(u("Toyota Corolla para ir al trabajo"))
    assert v58._scope_intake_reply(b) == "Perfecto. ¿Qué cuota mensual te queda cómoda?"


def test_scope_turn_with_use_and_budget_is_ready_to_search():
    b = body(u("Toyota Corolla para ir al trabajo. Máximo US$450 al mes."))
    assert v58._scope_intake_reply(b) is None


def test_brand_scope_is_a_real_hard_filter():
    c = {"require_brand": "Toyota"}
    assert v58._hard_ok({"make": "Toyota", "model": "Yaris", "is_addressable": True}, c)
    assert not v58._hard_ok({"make": "Honda", "model": "Civic", "is_addressable": True}, c)
