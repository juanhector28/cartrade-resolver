# Atlas El Salvador → Carly: private preview

This first bridge is **preview-only**. It does not replace or modify any production Carly recommendation route, Supabase inventory, CarTrade frontend, index, or publisher. It is off by default.

## Requirements for an isolated staging deployment

Set all variables **on a staging Resolver instance only**:

```text
CARLY_ATLAS_PREVIEW_ENABLED=1
CARLY_ATLAS_SV_BASE_URL=https://cartrade-atlas-production.up.railway.app
ATLAS_SV_SEARCH_TOKEN=<private Atlas service bearer token>
CARLY_ATLAS_PREVIEW_TOKEN=<independent random 32+ character secret>
```

Never put either token in Netlify/frontend JavaScript or commit it. Atlas credentials stay on the server. Do not reuse the preview token as the Atlas token. In the live Carly instance leave `CARLY_ATLAS_PREVIEW_ENABLED` unset/0.

## Private smoke test

```bash
curl -sS "https://STAGING_RESOLVER_HOST/internal/carly/atlas-sv-preview?q=Toyota&limit=5" \
  -H "X-Carly-Atlas-Preview-Token: <your private preview token>"
```

Expect `200` with `mode=atlas_sv_private_preview`, `published=false`,
`customer_facing=false`, and `requires_availability_confirmation=true`
on each vehicle. Expect `403` without the preview token.

The bridge reads `/internal/sv-search/search` (not the new-car catalog endpoint). It only exposes the six established used-vehicle source IDs:
EasyCar, AutosPublicidad, Excel Usados, Autosale, Julajups, xAutoMarket.
Source records with no original HTTPS URL, photo, vehicle make/model/year or
defensible price are not returned.

**Important:** Eligible previews may be empty. This means no qualifying result under current filters, **not** that the real marketplace is empty.

## Go/no-go before customer traffic

1. Verify two consecutive technically qualified capture cycles for the six sources in Atlas operations.
2. Test photograph rendering and original source deep links on mobile.
3. Measure stale references and duplicate candidates against the operator dashboard.
4. Separately validate availability with the seller/dealer. An indexed listing alone is not verified stock.
5. Only after approval: design and test a separate feature-flagged Carly recommendation integration. The private preview must never become a public search API just by leaking a browser token.

No additional scraping or automatic publisher activation is introduced by this bridge.
