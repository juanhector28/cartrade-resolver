from .contracts import BuyerState, Candidate, RankedCandidate

POLICY_VERSION = "carly-next-rank-v1"


def _trait(candidate: Candidate, key: str) -> float:
    if key in candidate.vehicle_traits:
        return float(candidate.vehicle_traits[key])
    body = (candidate.body_type or "").lower()
    model = (candidate.model or "").lower().replace(" ", "-")
    if key == "family_practicality":
        if model in {"cx-5", "cx5", "rav4", "cr-v", "crv", "tucson", "sportage"}:
            return 0.92
        if body == "suv":
            return 0.80
    if key == "city_maneuverability":
        if model in {"cx-30", "cx30", "kicks", "hr-v", "hrv"}:
            return 0.90
        if body == "hatchback":
            return 0.90
        if body == "sedan":
            return 0.75
    if key == "cargo_space":
        if body == "pickup":
            return 0.90
        if body == "suv":
            return 0.75
    if key == "comfort" and body == "suv":
        return 0.72
    if key == "fuel_economy" and body in {"sedan", "hatchback"}:
        return 0.75
    return 0.50


def rank_candidates(candidates: list[Candidate], state: BuyerState) -> list[RankedCandidate]:
    ranked = []
    ceiling = state.value("monthly_max")
    for candidate in candidates:
        budget = 0.60
        if ceiling and candidate.monthly_est is not None:
            budget = max(0.0, min(1.0, 1.0 - (candidate.monthly_est / float(ceiling)) * 0.35))
        preference = 0.50
        if state.soft:
            total = sum(state.soft.values()) or 1.0
            preference = sum(weight * _trait(candidate, key) for key, weight in state.soft.items()) / total
        quality = candidate.quality_score / 100.0 if candidate.quality_score > 1 else candidate.quality_score
        score = 0.45 * budget + 0.35 * preference + 0.20 * max(0.0, min(1.0, quality))
        ranked.append(RankedCandidate(candidate=candidate, score=round(score, 6), reasons=("budget_fit", "preference_fit", "listing_quality")))
    return sorted(ranked, key=lambda item: (-item.score, item.candidate.id))
