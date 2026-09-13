from app.carly_next import CarlyRequest, CarlyRuntime, Candidate

class OneCarInventory:
    def search(self, plan):
        return [Candidate("1","Mazda","CX-30",2024,22000,500,18000,"suv",quality_score=.9)]

def test_search_returns_observable_receipt():
    runtime = CarlyRuntime(OneCarInventory())
    request = CarlyRequest(messages=({"role":"user","content":"Busco Mazda SUV, 550 al mes"},), market={"country":"GT"}, session_id="receipt")
    result = runtime.handle(request)
    assert result.receipt.route in {"opening_search", "search"}
    assert result.receipt.retrieved == 1
    assert result.receipt.eligible == 1
    assert result.receipt.served == 1
    assert result.receipt.ranking_policy == "carly-next-rank-v1"
    assert result.receipt.llm_calls == 0
    assert result.receipt.vision_calls == 0
