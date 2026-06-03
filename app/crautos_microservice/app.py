import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, BackgroundTasks, Query
from pydantic import BaseModel

from normalizer import normalize_crautos

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crautos.db"
SCRAPER_PATH = BASE_DIR / "crautos_scraper.py"

app = FastAPI(title="Carly CRAutos Microservice", version="0.1.0")

class ScrapeRequest(BaseModel):
    limit: Optional[int] = 100
    delay: float = 1.0
    ids_only: bool = False

class Candidate(BaseModel):
    id: str
    source: str
    title: str
    year: Optional[int]
    price_usd: Optional[int]
    mileage_km: Optional[int]
    transmission: Optional[str]
    province: Optional[str]
    source_url: Optional[str]
    photo_count: Optional[int]
    score: int
    why: List[str]


def run_scraper(limit: Optional[int], delay: float, ids_only: bool) -> dict:
    cmd = [
        sys.executable,
        str(SCRAPER_PATH),
        "--db", str(DB_PATH),
        "--delay", str(delay),
    ]
    if limit:
        cmd += ["--limit", str(limit)]
    if ids_only:
        cmd.append("--ids-only")

    result = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True)
    normalized = 0
    if result.returncode == 0 and not ids_only:
        normalized = normalize_crautos(str(DB_PATH))
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "normalized_rows": normalized,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
    }

@app.get("/health")
def health():
    return {"ok": True, "service": "crautos"}

@app.post("/scrape/crautos")
def scrape_crautos(req: ScrapeRequest):
    return run_scraper(req.limit, req.delay, req.ids_only)

@app.post("/scrape/crautos/background")
def scrape_crautos_background(req: ScrapeRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(run_scraper, req.limit, req.delay, req.ids_only)
    return {"ok": True, "message": "Scrape started in background"}

@app.post("/normalize/crautos")
def normalize():
    rows = normalize_crautos(str(DB_PATH))
    return {"ok": True, "normalized_rows": rows}

@app.get("/candidates/crautos", response_model=List[Candidate])
def candidates(
    budget_max_usd: Optional[int] = None,
    year_min: Optional[int] = None,
    make: Optional[str] = None,
    model: Optional[str] = None,
    transmission: Optional[str] = Query(None, description="automatic or manual"),
    body_type: Optional[str] = None,
    max_results: int = 10,
):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    where = ["country = 'CR'"]
    params = []
    if budget_max_usd:
        where.append("price_usd IS NOT NULL AND price_usd <= ?")
        params.append(budget_max_usd)
    if year_min:
        where.append("year IS NOT NULL AND year >= ?")
        params.append(year_min)
    if make:
        where.append("LOWER(make) LIKE ?")
        params.append(f"%{make.lower()}%")
    if model:
        where.append("LOWER(model) LIKE ?")
        params.append(f"%{model.lower()}%")
    if transmission:
        where.append("LOWER(transmission) LIKE ?")
        params.append(f"%{transmission.lower()}%")
    if body_type:
        where.append("LOWER(body_type) LIKE ?")
        params.append(f"%{body_type.lower()}%")

    sql = f"""
    SELECT * FROM normalized_listings
    WHERE {' AND '.join(where)}
    LIMIT 500
    """
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    scored = []
    for r in rows:
        score = 50
        why = []

        if r["price_usd"]:
            if budget_max_usd and r["price_usd"] <= budget_max_usd:
                score += 15
                why.append("Dentro del presupuesto")
            elif not budget_max_usd:
                score += 5
        if r["year"]:
            if year_min and r["year"] >= year_min:
                score += 15
                why.append("Cumple el año mínimo")
            elif r["year"] >= 2018:
                score += 8
        if r["photo_count"] and r["photo_count"] >= 5:
            score += 8
            why.append("Buen set de fotos")
        if r["mileage_km"] and r["mileage_km"] <= 100000:
            score += 8
            why.append("Kilometraje razonable")
        if r["financing_available"]:
            score += 4
            why.append("Financiamiento disponible")
        if not why:
            why.append("Coincide con los filtros principales")

        title = " ".join(str(x) for x in [r["make"], r["model"]] if x)
        scored.append(Candidate(
            id=r["id"],
            source=r["source"],
            title=title,
            year=r["year"],
            price_usd=r["price_usd"],
            mileage_km=r["mileage_km"],
            transmission=r["transmission"],
            province=r["province"],
            source_url=r["source_url"],
            photo_count=r["photo_count"],
            score=min(score, 100),
            why=why[:4],
        ))

    scored.sort(key=lambda x: x.score, reverse=True)
    return scored[:max_results]
