# Paste the Link · El Salvador · Coverage scoreboard

**Updated:** 2026-10-10. **Scope:** paste an individual vehicle URL; *not* Atlas inventory coverage.

| Metric | Verified count |
|---|---:|
| Target sites requested | 56 (list not yet independently reconciled) |
| Distinct domains observed in SV Atlas | 9 |
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
