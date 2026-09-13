from .contracts import Candidate, SearchPlan

_SELECT = "id,source,make,model,year,price_usd,monthly_est,km,body_type,transmission,quality_score"

class AtlasInventory:
    def __init__(self, client, freshness_cutoff_iso: str):
        self.client = client
        self.freshness_cutoff_iso = freshness_cutoff_iso

    def search(self, plan: SearchPlan) -> list[Candidate]:
        query = self.client.table("scraped_listings").select(_SELECT)
        query = query.eq("country", plan.country.lower())
        query = query.eq("status", "staging").eq("is_addressable", True).eq("listing_state", "indexed")
        if plan.fresh_only:
            query = query.gte("last_seen_at", self.freshness_cutoff_iso)
        if len(plan.make) == 1:
            query = query.ilike("make", plan.make[0])
        if len(plan.body_type) == 1:
            query = query.ilike("body_type", plan.body_type[0])
        if plan.min_price is not None:
            query = query.gte("price_usd", plan.min_price)
        if plan.max_price is not None:
            query = query.lte("price_usd", plan.max_price)
        if plan.min_year is not None:
            query = query.gte("year", plan.min_year)
        rows = query.order("updated_at", desc=True).limit(500).execute().data or []
        return [self._candidate(row) for row in rows]

    @staticmethod
    def _candidate(row: dict) -> Candidate:
        return Candidate(
            id=str(row.get("id")),
            source=row.get("source"),
            make=str(row.get("make") or ""),
            model=str(row.get("model") or ""),
            year=row.get("year"),
            price_usd=row.get("price_usd"),
            monthly_est=row.get("monthly_est"),
            km=row.get("km"),
            body_type=row.get("body_type"),
            transmission=row.get("transmission"),
            quality_score=float(row.get("quality_score") or 0),
        )
