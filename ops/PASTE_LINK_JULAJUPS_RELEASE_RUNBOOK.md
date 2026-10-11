# Julajups controlled release runbook

## Technical evidence
- Toyota 4Runner 2019 HTTP + browser E2E: https://github.com/juanhector28/cartrade-resolver/actions/runs/38110874264 (12/12 PASS).
- PR #135 CI: 5/5 suites pass at commit 8bdd968.
- Production Carly frontend is hosted separately on Netlify. Staging success does not establish live frontend success.

## Production safety requirements
Do not activate Julajups until third-party data and photo reuse terms have been reviewed and the production integration/security controls are approved.
- Keep PR #135 as draft until production release gates are evidenced and approved.
- Deploy first with environment variable `PASTE_LINK_DISABLED_SOURCES=julajups.sv`; this blocks the source while allowing unrelated resolver operations.
- Confirm `POST /resolve-link` for the Julajups URL returns HTTP 503 when blocked; other permitted sources remain operational.
- Verify CORS, rate limiting, redirects/SSRF rules, timeouts, no persistence, monitoring, and no stale asking prices.
- After legal and engineering approval, remove `julajups.sv` from disabled sources and roll out gradually.
- Verify in CarTrade Netlify UI: individual ad renders correct title/year/current price and photo, missing mileage stays optional, financing CTA preserves vehicle context.
- Roll back immediately by restoring `julajups.sv` in `PASTE_LINK_DISABLED_SOURCES` and deploying configuration. Verify HTTP 503 for that source.
- Never claim commercial rights solely from robots access or browser load.

## Gates still open
See `ops/paste_link_sv_release_controls.json`. All entries remain unapproved until an owner documents evidence.
