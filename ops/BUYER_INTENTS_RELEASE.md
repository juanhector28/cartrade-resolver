# CarTrade buyer-interest intake without Router

## Purpose
Capture **buyer interest**, not credit applications, and without importing third-party listings into Atlas. CarTrade may follow up by WhatsApp only with explicit contact consent. There is no automatic seller message and no claimed bank approval.

## Components (draft PR #135)
- `POST /buyer-intents`, `app/buyer_intents.py`: feature-gated, validates HTTPS individual listing, trusted origin, contact consent, request UUID and length. Returns HTTP 201 and opaque receipt **only after Supabase acknowledges the write**. No PII in the response.
- `ops/migrations/20261012_buyer_intents.sql`: separate Supabase table, service-role-only, no public RLS policies.
- `assets/cartrade_buyer_intent_submit.js`: opt-in confirmation dialog for "Pedir este auto"; does not advance if backend fails.
- `scripts/build_cartrade_netlify_preview.py`: combines approved legacy HTML with finance preview + buyer gate and removes obsolete automatic `/deals` capture for pasted links.
- `scripts/paste_link_live_frontend_e2e.py`: fully mocked read-only browser test. Not evidence of an actual production lead.

## Release gates: all required
1. Review privacy notice, consent wording, legal basis, retention period, deletion and operational access to buyer contacts.
2. Add a server-side anti-bot challenge (e.g. Turnstile), production abuse monitoring and a trusted-proxy rate limit. Origin checks alone are not security authentication. Do not enable without these controls.
3. Approve and apply the **isolated** SQL migration in the correct Supabase project; provision backup and confirm service-role is inaccessible to browsers.
4. Decide the private operator inbox/CRM/WhatsApp queue for manual follow-up and its access controls. Database storage by itself is not operational follow-up.
5. Set `BUYER_INTENTS_TABLE=buyer_intents`, `BUYER_INTENTS_ORIGINS=https://cartrade.live,https://www.cartrade.live`, and **only after gates pass** `BUYER_INTENTS_ENABLED=1`.
6. Deploy resolver and compatible Netlify HTML together to a restricted preview before any production release. Test positive receipt, explicit consent, duplicate retry, backend outage, unsupported URLs, browser on mobile and no legacy /deals writes.
7. Check permission for source content/photos and release gates in `ops/paste_link_sv_release_controls.json` separately.

**Current status:** all flags remain OFF; new endpoint and frontend are code only, unmerged. Real contact intake is **not live**.
