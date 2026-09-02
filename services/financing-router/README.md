# Atlas Financing Router

Independent financing-orchestration service inside the CarTrade ecosystem.

## Boundary

- CarTrade owns discovery and customer experience.
- Trust+ supplies portable person and asset credentials.
- The router normalizes applications, evaluates eligibility and orchestrates bank adapters.
- Each bank remains lender of record and owns pricing, underwriting, capital and credit risk.

## Run locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

## Test

```bash
PYTHONPATH=. pytest -q
```

## First vertical slice

1. `POST /v1/applications` with an `Idempotency-Key`.
2. `POST /v1/applications/{id}/submit`.
3. `GET /v1/applications/{id}/offers`.
4. `POST /v1/applications/{id}/offers/{offer_id}/accept`.
5. `GET /v1/applications/{id}/timeline`.

The included Banco Atlántida adapter is a deterministic sandbox, not a representation of the bank's actual credit policy.

## Production gates

Before production traffic:

- replace `MemoryStore` with Postgres and unique idempotency constraints;
- add CarTrade service authentication and per-field encryption;
- add explicit consent scopes and immutable audit export;
- replace sandbox rules with bank-approved eligibility and API contracts;
- add signed bank webhooks, retry/outbox processing and secrets management;
- complete legal and security review.
