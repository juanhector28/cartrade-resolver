from app.carly_next import CarlyRequest, CarlyRuntime

class EmptyInventory:
    def search(self, plan):
        return []

def test_state_is_kept_by_session():
    runtime = CarlyRuntime(EmptyInventory())
    runtime.handle(CarlyRequest(messages=({"role":"user","content":"Busco un Mazda SUV"},), market={"country":"GT"}, session_id="s1"))
    result = runtime.handle(CarlyRequest(messages=({"role":"user","content":"550 al mes"},), market={"country":"GT"}, session_id="s1"))
    assert result.buyer_state.value("make") == "Mazda"
    assert result.buyer_state.value("monthly_max") == 550
