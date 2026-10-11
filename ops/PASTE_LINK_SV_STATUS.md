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

## Staging multisitio: first four-browser pilot (10 Oct 2026 local / 11 Oct UTC)

**Public staging:** https://cartrade-paste-link-staging.onrender.com

**Evidence:** https://github.com/juanhector28/cartrade-resolver/actions/runs/38097370645

Four different individual listing URLs passed full Chromium browser validation, with all five client-facing checks passed on each URL:

| Domain | Vehicle | Asking price | Model year | Mileage (normalized) | Photo visually loaded |
|---|---|---:|---:|---:|---|
| carroselsalvador.com | Kia Sportage | USD 5,700 | 2006 | 160,934 km | Yes |
| tucarro.sv | Ford Expedition | USD 16,500 | 2018 | 300,000 km | Yes |
| caragencia.com | Chevrolet TrailBlazer | USD 13,900 | 2023 | 65,983 km | Yes |
| carros.com | Honda Civic | USD 9,500 | 2015 | 125,837 km | Yes |

The staging source registry has 8 observed sites: 4 enabled for a single URL supplied by the tester and 4 awaiting confirmation of a distinct listing URL shape. These are **one-sample-per-domain E2E checks**, not a claim that an entire domain is covered or ready for production. The full target universe remains 56 Atlas source entries (not all independent vehicle domains). Three additional Carros El Salvador individual listings had already passed the parser-level real-page audit.

The staging environment does not access or write Supabase and has no persistent inventory/cache, and no production deployment has occurred. It respects robots directives and uses bounded URL routes and per-IP throttling. Live audit workflows are manual after the initial receipt to avoid repeated third-party requests. Image display and content reuse permissions must be reviewed before commercial rollout.

## Second source batch: 7/7 browser samples PASS (10 Oct 2026 local)

**Staging:** https://cartrade-paste-link-staging.onrender.com

**Recorded browser run:** https://github.com/juanhector28/cartrade-resolver/actions/runs/38098249341

**Screenshot artifact:** https://github.com/juanhector28/cartrade-resolver/actions/runs/38098249341/artifacts/11686982519

Chromium opened the staging UI, pasted one real listing URL per domain, and verified correct listing price, visible title, visible year, displayed mileage and HTML image loading (`naturalWidth > 0`). **7/7 listing examples passed, 35/35 per-field UI checks.**

| Domain | Vehicle example | Asking price | Normalized km | Photo loaded |
|---|---|---:|---:|---|
| carroselsalvador.com | Kia Sportage 2006 | USD 5,700 | 160,934 | Yes |
| tucarro.sv | Ford Expedition 2018 | USD 16,500 | 300,000 | Yes |
| caragencia.com | Chevrolet TrailBlazer 2023 | USD 13,900 | 65,983 | Yes |
| carros.com | Honda Civic 2015 | USD 9,500 | 125,837 | Yes |
| motorasv.com | Kia Forte 2017 | USD 7,200 | 111,000 | Yes |
| disazautos.com | Kia Seltos 2023 | USD 18,900 | 83,172 | Yes |
| autospublicidad.com | Toyota Tacoma 2020 | USD 23,500 | 107,826 | Yes |

AutosPublicidad's page labels its odometer only as "67" in a field but explicitly says "67 mil millas" in its description; the parser converts only when the unit is explicit. Images come from that vehicle's own ID-based gallery. The other two new domain samples passed extractor-level and browser-level tests without requiring their own dedicated rules.

**Scope limitations:** only one browser-validated sample on six domains, three earlier extractor-level samples on Carros El Salvador; not domain-wide certification, current inventory/price guarantees, permission to commercially re-display third-party content, or production integration. Existing Carly production is unchanged. Nissan El Salvador stays disabled because the Atlas examples are model-catalog pages without verifiable per-car asking prices. Automated external-domain workflows have been reverted to manual-only after validation.
