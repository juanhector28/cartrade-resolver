from enum import Enum
from .contracts import BuyerState, CarlyRequest

class Route(str, Enum):
    OPENING_SEARCH = "opening_search"
    SEARCH = "search"
    MORE_OPTIONS = "more_options"
    VEHICLE_DETAIL = "vehicle_detail"
    GENERAL_CONVERSATION = "general_conversation"

def latest_user(request: CarlyRequest) -> str:
    for message in reversed(request.messages):
        if str(message.get("role", "")).lower() == "user":
            return str(message.get("content", ""))
    return ""

def classify(request: CarlyRequest, state: BuyerState) -> Route:
    text = latest_user(request).lower()
    user_count = sum(1 for message in request.messages if str(message.get("role", "")).lower() == "user")
    if request.shown_vehicle_ids and any(term in text for term in ("cuéntame", "por qué", "qué tal", "preocupa", "opinas")):
        return Route.VEHICLE_DETAIL
    if any(term in text for term in ("más opciones", "otros carros", "otras opciones")):
        return Route.MORE_OPTIONS
    has_search = any(key in state.hard for key in ("make", "body_type", "max_price", "monthly_max"))
    if user_count == 1 and has_search:
        return Route.OPENING_SEARCH
    if has_search and (state.value("monthly_max") is not None or state.value("max_price") is not None):
        return Route.SEARCH
    return Route.GENERAL_CONVERSATION
