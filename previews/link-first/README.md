# CarTrade | Link First (Netlify preview)

## Goal
Make it possible to submit interest in **any public vehicle listing URL**
without waiting for the extractor, seller integrations, bank Router, inventory
coverage or the internal operator inbox.

**UX:** paste link → WhatsApp → explicit opt-in → receipt only after successful
server storage. Title, price, year and photos are NEVER mandatory.

## Supabase connected synthetic test (2026-10-12)

The standalone `staging-supabase.html` is a single HTML with an inlined
link-first UI and a public Supabase anon JWT. The **service-role key is not in
the HTML**. It calls the deployed Supabase Edge Function
`cartrade-link-first-staging-probe`, which requires JWT and allows only
`https://bright-dragon-cd29a3.netlify.app` as its Origin. The function
accepts a *fixed* synthetic URL, a fixed synthetic request ID, and a boolean
test consent. It never sends or saves the buyer's typed WhatsApp or URL.
The SQL table admits at most one immutable synthetic row; RLS denies
public read/write. The real `buyer_intents` table is unchanged.

Deploy this file into the existing **staging** Netlify site as `index.html`
to test browser → Supabase. Until then, the published staging page is still
the older demo. Run `scripts/test_link_first_supabase_probe.py` and
`scripts/test_link_first_supabase_browser.py` in GitHub Actions to verify
JWT, CORS, fake-only receipts and failure modes without sending real contacts.

**Not ready for real buyers.** Enabling collection requires a *separate*
protected endpoint with verified Turnstile/anti-bot challenges, rate limits,
privacy/retention disclosures, access controls, and an explicit activation
review. Do not copy this demo's synthetic response into real confirmation.

## Selected staging site (2026-10-12)

[https://bright-dragon-cd29a3.netlify.app/](https://bright-dragon-cd29a3.netlify.app/)

This is the user's approved **Netlify staging hostname**, not the production
`cartrade.live`. The site has been checked in desktop and mobile Chromium:
it serves the self-contained link-first demo and accepts no buyer submissions.

The backend's *default* `LINK_FIRST_ALLOWED_ORIGINS` is restricted to this
staging domain. Its feature flag `LINK_FIRST_INTAKE_ENABLED` remains OFF,
it is not mounted to a public production app, and Netlify's current HTML
still explicitly sets `CT_LINK_FIRST_DEMO=true`.

Do not remove the demo flag until the private backend, anti-bot checks,
consent/retention policy and controlled release have been reviewed.
No Netlify dashboard write or site redeploy is performed by the code changes.

## What's actually in this PR?
- `previews/link-first/index.html`: standalone CarTrade landing, one clear CTA,
  **hardcoded demo mode**. No backend traffic or recording of entered phone
  numbers. Suitable for Netlify drag-and-drop into a NEW preview site.
- `assets/cartrade_link_first_request.js`: consented request overlay; without
  demo mode it requires a backend `201` receipt with matching UUID.
- `app/link_first_intake.py`: standalone, feature-gated API router. **Not
  registered in production `app/main.py`**. Arbitrary public HTTPS listing
  links are accepted as data, never scraped. Supabase service-role DB and
  a real anti-abuse verifier must be explicitly injected by the host app.
- `tests/test_link_first_intake.py` & browser E2E: fake database and mocked
  network, real Chromium UI checks.
- `scripts/build_link_first_netlify.py`: generates the ready-to-upload static
  directory and CI ZIP.

## Build
```bash
python scripts/build_link_first_netlify.py --out dist/netlify-preview
```
Open `dist/netlify-preview/index.html` from a local HTTP server or upload
the folder contents to a **new** Netlify site. No change to `cartrade.live`.

## Production rollout (BLOCKED)
1. Approve privacy statement, consent evidence, retention, deletion, support
   ownership, notification policy and access controls.
2. Install server-side anti-bot verification and abuse throttling. The route
   intentionally fails with 503 unless the verifier is injected.
3. Configure private Supabase table `buyer_intents` with service-role-only
   access, feature flags and approved browser origins.
4. Mount the API router in a **restricted staging backend**; run live receipt
   and database-failure tests with fabricated contact details.
5. Add a controlled release mode by removing preview-only `CT_LINK_FIRST_DEMO`,
   set an approved backend endpoint, confirm monitoring and roll back quickly.
6. Obtain explicit production rollout approval before changing Netlify DNS,
   publishing the intake endpoint, or sending lead notifications.

## Out of scope
Financial prequalification, auto-scraping social networks, automated contact
with sellers, importing third-party images, Atlas indexing and production
changes. A public URL is treated as a buyer-provided reference only.
