# Social link intake

`POST /resolve-link` now routes recognized Facebook, Instagram and TikTok HTTPS
references to Atlas before the listing-domain guard. Existing listing adapters
continue to use their current path. This captures the URL only; it does not
fetch posts, extract media, connect accounts, or publish vehicles.

Configuration: `ATLAS_SOCIAL_URL` is the Atlas HTTPS base URL and
`ATLAS_SOCIAL_TOKEN` is its existing write token, sent as `X-Atlas-Token`.
The first pilot accepts explicit `SV` or `GT` country selection. Missing
configuration returns 503; a failed Atlas call returns 502. Neither claims
that anything was saved. No redirects are followed and no social URL is fetched.

Successful responses contain `candidate_saved=true`, `candidate_id`,
`status=pending_review`, `saved=false`, `in_inventory=false`,
`live_verified=false`. The UI must handle this as a receipt rather than a
resolved vehicle card. Frontend receipt rendering and deployed configuration
remain separate activation work. WhatsApp links are not vehicle publications;
WhatsApp message intake still needs its own integration.

Requires the companion Atlas inbound candidate patch before activation.
Test: `python -m pytest tests/test_social_intake.py -q`.
