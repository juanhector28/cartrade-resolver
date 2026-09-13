from typing import Protocol
from .contracts import CarlyRequest, Candidate, SearchPlan
from .parser import build_state
from .query_planner import build_search_plan
from .eligibility import filter_eligible
from .ranking import rank_candidates

class Inventory(Protocol):
    def search(self, plan: SearchPlan) -> list[Candidate]: ...

class CarlyOrchestrator:
    def __init__(self, inventory: Inventory):
        self.inventory = inventory

    def search(self, request: CarlyRequest):
        state = build_state(request.messages, request.market)
        plan = build_search_plan(state)
        candidates = self.inventory.search(plan)
        eligible = filter_eligible(candidates, state)
        ranked = rank_candidates(eligible, state)
        return {"state": state, "plan": plan, "ranked": ranked[:12]}
