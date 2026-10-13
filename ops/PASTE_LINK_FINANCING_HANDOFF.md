# Carly Paste the Link -> financing handoff, release plan

## Scope and evidence
- Read-only backend vehicle context: `app/financing_vehicle_context.py` (no credit request).
- Optional browser UI: `assets/cartrade_finance_handoff_preview.js`.
- Browser E2E: `scripts/paste_link_live_frontend_e2e.py`.
- Green workflow: https://github.com/juanhector28/cartrade-resolver/actions/runs/38173499645 (17 checks, mocked source response, no real buyer details).

## Verified
When the customer pastes a vehicle URL, the browser carries the listing URL, title, model year and asking price through request confirmation into an opt-in financing preview. Consent is unchecked initially; the flow refuses to prepare context until clicked. Financing status stays `not_started`. No lender API call occurs. Any unrelated outgoing HTTP POST is intercepted in the CI test.

## Not implemented / release blockers
- This JavaScript is committed in the resolver repo but is **not** included in Netlify's published HTML. The E2E injects it for testing.
- No licensed lender/prequalification API or credit-provider consent wording is configured.
- Contact/lead capture is a **separate** pre-existing CarTrade behavior and must be reviewed before production integration.
- The new UI must **not** claim that bank preapproval was granted or an application was transmitted.
- Pilot domain rights (including photo display) are not commercially cleared by technical tests.
- PR #135 remains draft and must not be merged before release gates in `ops/paste_link_sv_release_controls.json` are approved.

## Controlled frontend integration
1. Copy `assets/cartrade_finance_handoff_preview.js` into the Netlify site's published `assets/` directory, and reference it from the HTML with `<script defer src="/assets/cartrade_finance_handoff_preview.js"></script>`. Alternatively bundle it into the application source; do not point production to a mutable GitHub branch.
2. Retain the existing `#ct-stage`, `data-ct-screen`, and `CT_LAST_URL` contract.
3. Verify the popup appears only on `req2`, validates source URL and asking price, and presents an unchecked consent box.
4. Do an E2E dry-run with **mocked resolver** and no customer data before considering release.
5. Review accessibility, privacy notice, consent text, and permissions; keep the bank handoff disabled until a named, authorized provider is integrated.

## Future lender adapter (not authorized yet)
Only after separate consent for sharing personal information, create a server-side request with idempotency key, validated vehicle context, user consent receipt and bank-specific fields. Use provider credentials on server only. Return `pending`, `error` or real provider verdict; never fabricate credit decisions. Do not expose personal data in URL query strings, localStorage, or browser logs.
