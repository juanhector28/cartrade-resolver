# Carly frontend v12 contract patch

The backend now emits `clear_recommendations=true` for a fresh mission and must be treated as authoritative.

Required frontend behavior:

1. On `clear_recommendations=true`, remove every active recommendation surface, including Decision Room and the rich shortlist, and clear `__carlyLastMarketData`, `__carlyLastReply`, `__ctV204Cars`, `__cmpCards`, `__shownCars`, `__lastRecoIds` and shortlist-mode classes.
2. The Decision Room fetch interceptor must process `clear_recommendations=true` before ignoring responses without `decision`.
3. Opening Carly with a new first query must not auto-offer or render the old decision. Resume remains explicit when opening Carly without a new query.
4. Render `recommendations` and `explore` as separate tiers. Only `recommendations` count as strong recommendations.
5. The existing formatter should render the deterministic brief labels in bold (`MI LECTURA`, `POR QUÉ ME GUSTA`, `OJO CON`, `CARTRADE LO VERIFICA`).

A patched standalone frontend artifact was prepared from `CarTrade_frontend_Carly_commercial_v1.html`; this repository does not contain the production frontend source, so deploying that HTML remains a separate frontend deployment step.
