# Carly CRAutos Microservice

Primera versión para integrar el scraper de CRAutos a CarTrade/Carly.

## Qué contiene

- `crautos_scraper.py`: scraper original.
- `app.py`: API FastAPI.
- `normalizer.py`: convierte `cars` a `normalized_listings`.
- `requirements.txt`: dependencias.

## Instalar

```bash
cd crautos_microservice
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Correr API

```bash
uvicorn app:app --reload --port 8000
```

## Probar salud

```bash
curl http://localhost:8000/health
```

## Correr scraper limitado

```bash
curl -X POST http://localhost:8000/scrape/crautos \
  -H "Content-Type: application/json" \
  -d '{"limit": 50, "delay": 1.2}'
```

## Pedir candidatos

```bash
curl "http://localhost:8000/candidates/crautos?budget_max_usd=18000&year_min=2018&transmission=automatic&max_results=5"
```

## Idea de producción

Para producción, no correr scraping en el request principal. Usar:

```bash
POST /scrape/crautos/background
```

o un cron job que corra cada 6-12 horas.
