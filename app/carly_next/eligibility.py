from .contracts import BuyerState, Candidate

def eligible(candidate: Candidate, state: BuyerState) -> bool:
    if not candidate.served or not candidate.fresh or not candidate.indexed or not candidate.addressable:
        return False
    make = state.value("make")
    if make and candidate.make.lower() != str(make).lower():
        return False
    body = state.value("body_type")
    if body and (candidate.body_type or "").lower() != str(body).lower():
        return False
    maximum = state.value("monthly_max")
    if maximum is not None and (candidate.monthly_est is None or candidate.monthly_est > float(maximum)):
        return False
    return True

def filter_eligible(candidates: list[Candidate], state: BuyerState) -> list[Candidate]:
    return [candidate for candidate in candidates if eligible(candidate, state)]
