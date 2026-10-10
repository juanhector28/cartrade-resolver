# Paste the Link · El Salvador · Coverage scoreboard

**Updated:** 2026-10-10. **Scope:** paste an individual vehicle URL; *not* Atlas inventory coverage.

| Metric | Verified count |
|---|---:|
| Target sites requested | **56; reconciled to Atlas PR #133 exact source IDs** |
| Distinct domains observed in Supabase SV inventory | 9 |
| Additional domains enabled by draft PR #135 | 8 |
| Public individual vehicle pages reviewed | 3 |
| E2E resolver extractions validated against original pages | **0** |
| Domains authorized and confirmed functional | **0** |
| Production rollout of PR #135 | **Not performed** |

## Observed individual vehicle pages

| Domain | Vehicle | Published price | Year | Mileage | Photo visible | Server-side resolver verified |
|---|---|---:|---:|---|---|---|
| carroselsalvador.com | KIA Sportage | USD 5,700 | 2006 | 100,000 mi | Yes | No |
| caragencia.com | Chevrolet TrailBlazer | USD 13,900 | 2023 | 41,000; seller says miles | Not audited | No |
| carros.com | Honda Civic | USD 9,500 | 2015 | 125,837 km | Not audited | No |

Evidence: public pages of each corresponding URL in `ops/paste_link_sv_coverage.json`. These are reference expectations, **not extraction responses**.

## Rollout gates

1. Validate source permission and robots/terms for each site.
2. Test 3+ real listing pages per candidate site, including images and price, on the actual resolver's outbound network.
3. Confirm no catalog-page false positives and no wrong-price matches from related inventory.
4. Threat-model SSRF for DNS resolution, redirects and custom ports before broadening the URL allowlist.
5. Approve/deploy only after all security checks and full CI success.
6. Capture results and timestamps here; do not mark a site functional solely because an allowlist test passed.

Machine-readable source of this view: `ops/paste_link_sv_coverage.json`.

## Full source census linked

The JSON scorecard now includes the full **56-source registry** from `juanhector28/cartrade-atlas`, PR #133, `overrides/atlas/sv_sources/report.json`. In that earlier Atlas **collector** run: 32 sources had observed links, 12 had enumerated catalogs/feeds, three were blocked, three empty/closed, four without independent auto inventory, one catalog-only, one legacy gallery. Atlas reports 1,405 raw source records, 1,315 field-valid records, and **0 sources verified in production**. These must not be counted as successful Paste the Link resolutions.

Each of the 56 source rows separately records individual Paste the Link status for price, photo, year, mileage and access review. All start **unverified** until actual request-response checks from the resolver pass.

## First real public listing diagnostic (10 Oct 2026)

**Result: 3/3 individual vehicle URLs passed the parser-level live test** on GitHub Actions runner, with one robots.txt check and 3 bounded individual-page GET requests. No page HTML or photos were retained.

| Listing | Current asking price extracted | Year | Odometer normalized | Photo URL returned |
|---|---:|---:|---:|---|
| KIA Sportage | USD 5,700 | 2006 | 160,934 km (100,000 mi) | Yes |
| Honda Accord | USD 8,500 | 2015 | 209,215 km (130,000 mi) | Yes |
| Ford Escape | USD 10,700 | 2015 | 236,574 km (147,000 mi) | Yes |

GitHub evidence: https://github.com/juanhector28/cartrade-resolver/actions/runs/38095284698

**Not yet demonstrated:** production /resolve-link full HTTP integration; actual image loading/rendering in Carly; independent commercial-content rights; future prices and availability. Therefore domain-wide production certification remains pending, even though three real listings passed.

## Carly isolated staging integration: PASS

**Live test environment:** https://cartrade-paste-link-staging.onrender.com

The Render free Python service is deployed from the PR #135 branch and explicitly runs `app.paste_link_staging:app`, not the production app. It has no Supabase configuration, no automatic saved listings, and an exact single-domain allowlist. Free services may cold-start.

**True end-to-end receipt:** https://github.com/juanhector28/cartrade-resolver/actions/runs/38096244781

GitHub Actions ran an HTTP health check, an actual `POST /api/resolve`, and a headless Chromium session that opened the staging page, clicked the CTA, and rendered a car card. All 12 checks passed, including `HTMLImageElement.naturalWidth > 0`, confirming the photo actually loads in the browser.

Confirmed individual staging E2E: KIA Sportage 2006, USD 5,700, 160,934 km.

**Important distinction:** Three source listing URLs passed the parser-level live checks; only the Kia has a full staging browser E2E. The other 55 sources and any commercial redisplay rights are not certified. The existing production Carly /resolve-link and frontend remain unchanged. Stage is an isolated scoped preview, not the full production Carly frontend.
