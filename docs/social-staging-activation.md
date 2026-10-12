# Social intake staging activation

Staging `/api/resolve` accepts Facebook, Instagram and TikTok URLs with an
explicit SV/GT country. The page presents a receipt only when Atlas confirms
candidate_saved and returns a candidate ID. Vehicle cards stay hidden on the
receipt path. Missing configuration remains a 503 with no success message.

The existing staging Render service is `cartrade-paste-link-staging` in the
confirmed CarTrade workspace. Its branch is
`feat/paste-link-sv-observed-domains-20261010` and auto-deploy is disabled.

Activation prerequisites:

1. Deploy Atlas PR 149 (URL-only candidates must enter awaiting_metadata).
2. Integrate resolver PR 137 into the staging branch.
3. In the staging Render environment, set ATLAS_SOCIAL_URL to
   https://cartrade-atlas-production.up.railway.app and ATLAS_SOCIAL_TOKEN
   to the existing Atlas API write token. Do not expose it in HTML or chat.
4. Trigger staging deploy, submit real post URLs and confirm the returned IDs
   in Atlas's candidate queue. Confirm no confirmed-inventory writes occur.

Railway's connected OAuth tools return variable names only. ATLAS_API_TOKEN
exists, but its value cannot be read through this connection. No token was
rotated, fabricated or copied and no deployment was triggered in this step.

Local validation: 14 staging tests passing, including three platform routes
using the real Atlas engine with a mocked HTTP transport. They test persisted
candidate receipts and failure behavior; they are not deployed network tests.
To repeat the cross-repository integration check, checkout the companion Atlas
branch and run:

`PYTHONPATH=.:../cartrade-atlas/overrides python -m pytest
tests/test_paste_link_staging.py scripts/social_staging_integration_test.py -q`

This changes the staging page only. The Netlify production frontend has not
been changed or deployed.
