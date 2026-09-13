# Carly Next

Clean-room recommendation runtime.

## Invariants

- No imports from `main_vXX` modules.
- No monkey-patching or route mutation.
- Market metadata stays structured and never becomes buyer speech.
- Buyer facts carry provenance and are updated from user messages only.
- BuyerState is session-authoritative; transcript history is compatibility input, not state authority.
- Eligibility runs before ranking.
- Ranking is deterministic and performs no LLM or vision calls.
- Atlas is accessed only through the inventory adapter.
- Every recommendation response carries a request receipt with route, counts, policy version, LLM calls and vision calls.

Pipeline:

`Request -> BuyerState -> Route -> SearchPlan -> Atlas -> Eligibility -> Rank -> Response`
