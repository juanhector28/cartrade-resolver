# Deals staging contract

- Open `deals-app.html` from a separately hosted HTTPS staging origin, alongside `deals-client.js` and `config.js` populated from `config.example.js`.
- The page authenticates using Supabase OTP. Existing user identities only: `shouldCreateUser:false`.
- Configure Auth email provider and allow-listed redirect URL for the exact staging address. Enable CORS for that address on the resolver, including Authorization header. Do not use wildcard CORS in production.
- Backend must run the draft Deals API branch and have `SUPABASE_ANON_KEY` or equivalent project publishable API key available server-side. Never embed a service-role key in the frontend.
- No deploy of resolver or frontend performed by this change.
- Only draft creation and owner-scoped read work. No loan approvals, seller verification, state mutations, institutional impersonation, or closing.
- BEFORE production: automated API regression tests, authenticated E2E using two distinct users (creation, sign out, sign in on another device, owner access, nonowner 404), successful preflight, network/API failure and token expiry handling.
- Existing Deals MVP stores simulated transactions in localStorage and has auto-advancing mock bank milestones; do not treat it as live or merge its simulated workflows with this real-data screen. This page intentionally excludes those workflows.
