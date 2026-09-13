import uuid
from typing import Protocol

from .contracts import CarlyRequest, CarlyResponse, Candidate, RequestReceipt, SearchPlan
from .eligibility import filter_eligible
from .parser import build_state
from .query_planner import build_search_plan
from .ranking import POLICY_VERSION, rank_candidates
from .response_policy import opening_reply, recommendation_reply
from .routing import Route, classify


class Inventory(Protocol):
    def search(self, plan: SearchPlan) -> list[Candidate]: ...


class CarlyOrchestrator:
    def __init__(self, inventory: Inventory):
        self.inventory = inventory

    def handle(self, request: CarlyRequest) -> CarlyResponse:
        request_id = uuid.uuid4().hex[:12]
        state = build_state(request.messages, request.market)
        route = classify(request, state)

        if route is Route.OPENING_SEARCH and state.value("monthly_max") is None and state.value("max_price") is not None:
            receipt = RequestReceipt(request_id=request_id, route=route.value, buyer_state_revision=state.revision)
            return CarlyResponse(phase="conversation", reply=opening_reply(state), receipt=receipt, buyer_state=state)

        if route in {Route.OPENING_SEARCH, Route.SEARCH, Route.MORE_OPTIONS}:
            plan = build_search_plan(state)
            candidates = self.inventory.search(plan)
            eligible = filter_eligible(candidates, state)
            ranked = rank_candidates(eligible, state)
            already_shown = set(request.shown_vehicle_ids)
            page = tuple(item for item in ranked if item.candidate.id not in already_shown)[:12]
            receipt = RequestReceipt(
                request_id=request_id,
                route=route.value,
                buyer_state_revision=state.revision,
                retrieved=len(candidates),
                eligible=len(eligible),
                served=len(page),
                ranking_policy=POLICY_VERSION,
                llm_calls=0,
                vision_calls=0,
            )
            return CarlyResponse(
                phase="recommendation" if page else "conversation",
                reply=recommendation_reply(list(page)),
                recommendations=page,
                receipt=receipt,
                buyer_state=state,
            )

        receipt = RequestReceipt(request_id=request_id, route=route.value, buyer_state_revision=state.revision)
        return CarlyResponse(
            phase="conversation",
            reply="Cuéntame qué necesitas del carro y lo convierto en criterios de búsqueda.",
            receipt=receipt,
            buyer_state=state,
        )
