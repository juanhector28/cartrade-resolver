from .contracts import BuyerState, Candidate, RankedCandidate

POLICY_VERSION = "carly-next-rank-v1"

def rank_candidates(candidates: list[Candidate], state: BuyerState) -> list[RankedCandidate]:
    ranked = []
    ceiling = state.value("monthly_max")
    for candidate in candidates:
        budget = 0.6
        if ceiling and candidate.monthly_est is not None:
            budget = max(0.0, min(1.0, 1.0 - (candidate.monthly_est / float(ceiling)) * 0.35))
        preference = 0.5
        if state.soft:
            total = sum(state.soft.values()) or 1.0
            preference = sum(weight * candidate.vehicle_traits.get(key, 0.5) for key, weight in state.soft.items()) / total
        quality = candidate.quality_score / 100.0 if candidate.quality_score > 1 else candidate.quality_score
        score = 0.45 * budget + 0.35 * preference + 0.20 * max(0.0, min(1.0, quality))
        ranked.append(RankedCandidate(candidate=candidate, score=round(score, 6), reasons=("budget_fit", "preference_fit", "listing_quality")))
    return sorted(ranked, key=lambda item: (-item.score, item.candidate.id))
