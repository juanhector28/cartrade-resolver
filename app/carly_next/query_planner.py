from .contracts import BuyerState, SearchPlan


def build_search_plan(state: BuyerState) -> SearchPlan:
    country = str(state.market.get("country") or state.market.get("country_code") or "").upper()
    if not country:
        raise ValueError("market.country is required")
    make = state.value("make")
    body = state.value("body_type")
    return SearchPlan(
        country=country,
        make=(make,) if make else (),
        body_type=(body,) if body else (),
        min_price=state.value("min_price"),
        max_price=state.value("max_price"),
        max_monthly=state.value("monthly_max"),
        min_year=state.value("min_year"),
        transmission=state.value("transmission"),
    )
