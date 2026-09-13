from .contracts import BuyerState, RankedCandidate

def opening_reply(state: BuyerState) -> str:
    make = state.value("make") or ""
    body = state.value("body_type") or "carro"
    label = (str(make) + " " + str(body)).strip()
    return "Entendido: buscas un " + label + ". ¿Para qué lo vas a usar principalmente?"

def recommendation_reply(ranked: list[RankedCandidate]) -> str:
    if not ranked:
        return "No encontré opciones que cumplan todos tus criterios actuales."
    car = ranked[0].candidate
    return f"Empezaría por el {car.make} {car.model} {car.year or ''}.".strip()
