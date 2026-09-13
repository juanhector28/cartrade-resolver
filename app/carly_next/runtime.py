import uuid
from dataclasses import replace
from .contracts import BuyerState, CarlyResponse, RequestReceipt
from .parser import update_buyer_state
from .query_planner import build_search_plan
from .eligibility import filter_eligible
from .ranking import POLICY_VERSION, rank_candidates
from .routing import classify, latest_user, Route
from .response_policy import opening_reply, recommendation_reply
from .session_store import MemorySessionStore

class CarlyRuntime:
    def __init__(self, inventory, state_store=None):
        self.inventory = inventory
        self.state_store = state_store or MemorySessionStore()

    def handle(self, request):
        request_id = uuid.uuid4().hex[:12]
        session_id = request.session_id or request_id
        state = self.state_store.get(session_id)
        if state is None:
            state = BuyerState(market=dict(request.market or {}))
        elif request.market and request.market != state.market:
            state = replace(state, market=dict(request.market))
        text = latest_user(request)
        if text:
            state = update_buyer_state(state, text, state.revision + 1)
        self.state_store.put(session_id, state)
        route = classify(request, state)
        if route is Route.OPENING_SEARCH and state.value("monthly_max") is None and state.value("max_price") is not None:
            receipt = RequestReceipt(request_id, route.value, state.revision)
            return CarlyResponse("conversation", opening_reply(state), receipt=receipt, buyer_state=state)
        if route in {Route.OPENING_SEARCH, Route.SEARCH, Route.MORE_OPTIONS}:
            candidates = self.inventory.search(build_search_plan(state))
            eligible = filter_eligible(candidates, state)
            ranked = rank_candidates(eligible, state)
            shown = set(request.shown_vehicle_ids)
            page = tuple(item for item in ranked if item.candidate.id not in shown)[:12]
            receipt = RequestReceipt(request_id, route.value, state.revision, len(candidates), len(eligible), len(page), POLICY_VERSION, 0, 0)
            return CarlyResponse("recommendation" if page else "conversation", recommendation_reply(list(page)), page, receipt, state)
        receipt = RequestReceipt(request_id, route.value, state.revision)
        return CarlyResponse("conversation", "Cuéntame qué necesitas del carro.", receipt=receipt, buyer_state=state)
