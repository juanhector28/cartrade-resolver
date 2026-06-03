import sqlite3
from datetime import datetime
from typing import Optional

NORMALIZED_SCHEMA = """
CREATE TABLE IF NOT EXISTS normalized_listings (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_listing_id TEXT NOT NULL,
    source_url TEXT,
    country TEXT NOT NULL,
    make TEXT,
    model TEXT,
    year INTEGER,
    price_usd INTEGER,
    price_local INTEGER,
    currency_local TEXT,
    mileage_km INTEGER,
    body_type TEXT,
    fuel_type TEXT,
    transmission TEXT,
    condition TEXT,
    province TEXT,
    seller_name TEXT,
    seller_phone TEXT,
    whatsapp_phone TEXT,
    financing_available INTEGER,
    monthly_payment_usd INTEGER,
    features TEXT,
    photos TEXT,
    photo_count INTEGER,
    description TEXT,
    first_seen_at TEXT,
    last_seen_at TEXT,
    raw_source TEXT
);
CREATE INDEX IF NOT EXISTS idx_norm_country ON normalized_listings(country);
CREATE INDEX IF NOT EXISTS idx_norm_make_model ON normalized_listings(make, model);
CREATE INDEX IF NOT EXISTS idx_norm_price ON normalized_listings(price_usd);
CREATE INDEX IF NOT EXISTS idx_norm_year ON normalized_listings(year);
"""

def normalize_transmission(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.lower()
    if "auto" in v:
        return "automatic"
    if "manual" in v or "mec" in v:
        return "manual"
    return value.strip()

def normalize_crautos(db_path: str = "crautos.db") -> int:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(NORMALIZED_SCHEMA)

    rows = conn.execute("SELECT * FROM cars").fetchall()
    now = datetime.utcnow().isoformat()
    count = 0

    for r in rows:
        listing_id = f"crautos:{r['id']}"
        existing = conn.execute(
            "SELECT first_seen_at FROM normalized_listings WHERE id = ?",
            (listing_id,),
        ).fetchone()
        first_seen = existing["first_seen_at"] if existing else now

        conn.execute(
            """
            INSERT OR REPLACE INTO normalized_listings (
                id, source, source_listing_id, source_url, country,
                make, model, year, price_usd, price_local, currency_local,
                mileage_km, body_type, fuel_type, transmission, condition,
                province, seller_name, seller_phone, whatsapp_phone,
                financing_available, monthly_payment_usd, features, photos,
                photo_count, description, first_seen_at, last_seen_at, raw_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                listing_id,
                "crautos",
                str(r["id"]),
                r["url"],
                "CR",
                r["marca"],
                r["modelo"],
                r["anio"],
                r["precio_usd"],
                r["precio_crc"],
                "CRC",
                r["kilometraje"],
                r["estilo"],
                r["combustible"],
                normalize_transmission(r["transmision"]),
                r["estado"],
                r["provincia"],
                r["vendedor_nombre"],
                r["vendedor_tel"],
                r["vendedor_wa"],
                r["financiamiento"],
                r["cuota_usd_mes"],
                r["equipamiento"],
                r["fotos"],
                r["n_fotos"],
                r["comentario"],
                first_seen,
                now,
                "cars",
            ),
        )
        count += 1

    conn.commit()
    conn.close()
    return count
