# CarTrade Link Resolver

Microservicio que extrae datos de un listado de auto a partir de un URL.
Soporta Encuentra24, OLX, Facebook Marketplace, MercadoLibre y un fallback
genérico de Open Graph.

## Endpoint

```
POST /resolve-link
Content-Type: application/json

{ "url": "https://www.encuentra24.com/el-salvador-es/autos-usados/honda-hr-v-2024/31743871" }
```

Respuesta:

```json
{
  "platform": "encuentra24",
  "url": "https://...",
  "title": { "value": "Honda HR-V 2024", "confidence": "high" },
  "make": { "value": "Honda", "confidence": "high" },
  "model": { "value": "HR-V", "confidence": "high" },
  "year": { "value": 2024, "confidence": "high" },
  "price_usd": { "value": 28500, "confidence": "high" },
  "km": { "value": 5790, "confidence": "high" },
  "transmission": { "value": "Automática", "confidence": "high" },
  "fuel": { "value": "Gasolina", "confidence": "high" },
  "location": { "value": "San Salvador", "confidence": "high" },
  "description": { "value": "...", "confidence": "high" },
  "photos": ["https://photos.encuentra24.com/..."],
  "seller_name": null,
  "scraped_at": "2026-05-31T19:00:00+00:00",
  "errors": [],
  "cached": false,
  "elapsed_seconds": 1.2
}
```

Cada campo opcional viene con un `confidence` en `high|medium|low`. El frontend
decide cómo pre-rellenar según esa confianza.

## Despliegue en Railway (recomendado)

1. Crear un nuevo proyecto en Railway, conectar este repo (o subirlo).
2. Railway detecta `Dockerfile` y `railway.toml` automáticamente.
3. En **Variables**, agregar:
   - `CORS_ORIGINS=https://cartrade.live,https://www.cartrade.live`
4. Deploy. Railway emite una URL tipo `cartrade-resolver-production.up.railway.app`.
5. (Opcional) **Settings → Networking → Custom domain**: agregar
   `resolver.cartrade.live` y configurar el CNAME en Netlify DNS.

### Volumen persistente para cache

Railway → **Volumes** → mount `/data` → SQLite cache sobrevive a redeploys.
Sin volumen el cache se reinicia en cada deploy (no es crítico, solo afecta
performance).

## Despliegue en Fly.io (alternativa)

```bash
fly launch --no-deploy
fly volumes create resolver_data --size 1
fly deploy
```

Editar `fly.toml` para montar `resolver_data` en `/data`.

## Local dev

```bash
pip install -r requirements.txt
playwright install chromium --with-deps
RESOLVER_DEV=1 uvicorn app.main:app --reload --port 8000
```

Probar:

```bash
curl -X POST http://localhost:8000/resolve-link \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.encuentra24.com/el-salvador-es/autos-usados/honda-hr-v-2024/31743871"}'
```

## Health check

```
GET /health
```

Devuelve el estado de cada resolver por plataforma (último OK, último error).
Útil para monitoreo y para saber cuándo una plataforma cambió su markup y hay
que ajustar el resolver.

## Plataformas soportadas

| Plataforma         | Método                         | Confianza esperada |
|--------------------|--------------------------------|--------------------|
| Encuentra24        | httpx + selectolax (directo)   | Alta — 90% campos  |
| OLX (cualquier país)| Playwright headless            | Alta-media — 80%   |
| Facebook Marketplace| Open Graph público             | Media — 40-60%     |
| MercadoLibre       | API oficial                    | Alta — 95% campos  |
| Cualquier otro     | Open Graph genérico (fallback) | Baja — 30-50%      |

## Rate limit

Por defecto: 30 req/hora por IP. Ajustar con vars `RATE_WINDOW_SECONDS`
y `RATE_MAX_REQUESTS`.

## Notas operativas

- **OLX y FB cambian markup periódicamente.** Cuando un resolver empiece a
  fallar consistentemente, revisar `__NEXT_DATA__` (OLX) y los meta tags
  (FB), ajustar el parser. Esperar ~6 meses entre roturas.
- **No bypass de login de FB.** Por diseño solo leemos Open Graph público.
  Cualquier intento de scraping con cuentas autenticadas viola los ToS de
  Meta y trae riesgo legal serio.
- **Snapshots para evidencia legal:** este servicio no los guarda hoy. Si
  más adelante quieren evidencia en disputas Trust+, agregar S3 upload del
  HTML completo en `main.py` después del scrape exitoso.

## Costos estimados

- Railway hobby plan: $5/mo (200 req/día aprox)
- Railway pro plan: $20/mo (cientos-miles req/día)
- S3 snapshots (opcional): $1-5/mo
- Proxies residenciales (si OLX te bloquea a escala): $50-100/mo Bright Data


CarTrade Resolver (FastAPI -> Supabase)
Frontend (cartrade.live) -> this service (Render) -> Supabase.
Keeps Carly's matching logic and your DB schema on the server. The browser never
sees your Supabase key, and the inventory is queried live (no more embedded JSON).
Endpoints
`GET  /health` — liveness.
`POST /carly/search` — body `{ "q": "SUV para familia menos de 15k", "country": "sv", "limit": 3 }`.
Returns ranked matches with `monthly_est`, `tag`, and `why`.
`POST /resolve` — body `{ "url": "https://www.encuentra24.com/.../32434900" }`.
Returns the indexed listing if found, otherwise a "request from seller" lead.
`GET  /stats` — indexed / addressable / GMV by country (for the landing & pitch).
Deploy on Render
New Web Service from this repo/folder.
Build command: `pip install -r requirements.txt`
Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
Environment variables:
`SUPABASE_URL`          = https://<project>.supabase.co
`SUPABASE_SERVICE_KEY`  = your service_role key (server-side only — never in the browser)
`ALLOWED_ORIGINS`       = https://cartrade.live,https://www.cartrade.live
`SUPABASE_TABLE`        = scraped_listings   (optional, this is the default)
Test (after deploy)
```
curl https://YOUR-SERVICE.onrender.com/health
curl -X POST https://YOUR-SERVICE.onrender.com/carly/search \
  -H "Content-Type: application/json" \
  -d '{"q":"pickup para trabajo","country":"gt","limit":3}'
curl https://YOUR-SERVICE.onrender.com/stats
```
Frontend
Set `RESOLVER_BASE` in `carly_api.js` to your Render URL, include it after the hero
markup, and remove the embedded `window.CT_CARS` + old engine. The hero inputs
(`#clzcInp`, chips, `#heroLinkInput`) now hit the live API.
Security notes
The `service_role` key bypasses RLS — keep it ONLY in this server's env, never in client code.
Alternative: use the `anon` key + a read-only RLS SELECT policy on `scraped_listings`,
exposing only safe columns. Slightly more setup, lower blast radius.
CORS is locked to `ALLOWED_ORIGINS`.



