#!/usr/bin/env python3
"""
crautos_scraper.py — Scraper de autos usados de crautos.com (Costa Rica)

Uso:
    pip install requests beautifulsoup4 lxml
    python crautos_scraper.py                  # scrape completo (IDs + detalles)
    python crautos_scraper.py --ids-only       # solo recolectar IDs del listado
    python crautos_scraper.py --limit 200      # probar con 200 vehiculos
    python crautos_scraper.py --export         # exportar SQLite -> CSV
    python crautos_scraper.py --delay 1.5      # ajustar rate limit (seg entre requests)

Salida:
    crautos.db   (SQLite, tabla `cars`)
    crautos.csv  (con --export)

Es resumible: si lo cortas, al relanzar salta los IDs ya scrapeados.
"""

import argparse
import os
import csv
import random
import re
import sqlite3
import sys
import time
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://crautos.com"
SEARCH_URL = f"{BASE}/autosusados/searchresults.cfm"
INDEX_URL = f"{BASE}/autosusados/index.cfm"
DETAIL_URL = f"{BASE}/autosusados/cardetail.cfm"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "es-CR,es;q=0.9",
}

# Debug suave para Render Logs. Cambia a "0" si no quieres ruido.
DEBUG_DISCOVERY = os.environ.get("CRAUTOS_DEBUG", "1") == "1"

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

EQUIPMENT_FIELDS = [
    "Dirección Hidráulica", "Cierre central", "Asientos eléctricos", "Vidrios tintados",
    "Vidrios eléctricos", "Bolsa de aire", "Alarma", "Espejos eléctricos", "Frenos ABS",
    "Aire acondicionado", "Desempañador Trasero", "Sunroof", "Aros de lujo", "Turbo",
    "Tapicería de cuero", "Halógenos", "Cámara 360", "Android Auto", "Control crucero",
    "Radio con USB", "Revisión Técnica al día", "Control electrónico de estabilidad",
    "Control de descenso", "Caja de cambios dual", "Cámara de retroceso",
    "Sensores de retroceso", "Sensores frontales", "Control de radio en el volante",
    "Volante multifuncional", "Aire acondicionado climatizado", "Asiento con memoria",
    "Retrovisores auto-retractibles", "Luces de Xenón", "Sensor de lluvia",
    "Llave inteligente", "Apple CarPlay", "Computadora de viaje", "Volante ajustable",
    "Bluetooth",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS cars (
    id              INTEGER PRIMARY KEY,
    url             TEXT,
    marca           TEXT,
    modelo          TEXT,
    anio            INTEGER,
    precio_crc      INTEGER,
    precio_usd      INTEGER,
    moneda_original TEXT,
    cilindrada_cc   INTEGER,
    estilo          TEXT,
    pasajeros       INTEGER,
    combustible     TEXT,
    transmision     TEXT,
    estado          TEXT,
    kilometraje     INTEGER,
    placa_termina   TEXT,
    color_exterior  TEXT,
    color_interior  TEXT,
    puertas         INTEGER,
    impuestos_pagos TEXT,
    negociable      TEXT,
    recibe_vehiculo TEXT,
    provincia       TEXT,
    fecha_ingreso   TEXT,
    vistas          INTEGER,
    comentario      TEXT,
    vendedor_nombre TEXT,
    vendedor_tel    TEXT,
    vendedor_wa     TEXT,
    financiamiento  INTEGER,
    cuota_usd_mes   INTEGER,
    equipamiento    TEXT,
    n_fotos         INTEGER,
    fotos           TEXT,
    scraped_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_marca ON cars(marca);
CREATE INDEX IF NOT EXISTS idx_anio ON cars(anio);
CREATE INDEX IF NOT EXISTS idx_precio ON cars(precio_crc);
"""


def make_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    # Helps older ColdFusion sites keep search/pagination state consistently.
    s.headers.update({"Referer": INDEX_URL})
    return s


def fetch(session, method, url, retries=4, **kw):
    for attempt in range(retries):
        try:
            r = session.request(method, url, timeout=30, **kw)
            if r.status_code == 200:
                return r
            if r.status_code in (429, 503):
                wait = 20 * (attempt + 1)
                print(f"  [{r.status_code}] backoff {wait}s ...")
                time.sleep(wait)
                continue
            print(f"  [{r.status_code}] {url}")
        except requests.RequestException as e:
            print(f"  [err] {e} (intento {attempt + 1})")
            time.sleep(5 * (attempt + 1))
    return None


# ---------------------------------------------------------------- FASE 1: IDs

def discover_form_defaults(session):
    """Lee el formulario de busqueda de index.cfm y arma el payload con defaults,
    para no depender de nombres de campos hardcodeados."""
    r = fetch(session, "GET", INDEX_URL)
    if not r:
        sys.exit("No se pudo cargar index.cfm")
    soup = BeautifulSoup(r.text, "lxml")
    form = None
    for f in soup.find_all("form"):
        action = (f.get("action") or "").lower()
        if "searchresults" in action:
            form = f
            break
    payload = {}
    if form:
        for sel in form.find_all("select"):
            name = sel.get("name")
            if not name:
                continue
            opt = sel.find("option", selected=True) or sel.find("option")
            payload[name] = opt.get("value", "") if opt else ""
        for inp in form.find_all("input"):
            name = inp.get("name")
            if not name:
                continue
            t = (inp.get("type") or "text").lower()
            if t in ("text", "hidden"):
                payload[name] = inp.get("value", "")
            elif t in ("checkbox", "radio") and inp.get("checked") is not None:
                payload[name] = inp.get("value", "on")
    # fallback: payload conocido del sitio si el parseo del form falla
    if not payload:
        payload = {
            "brand": "00", "modelostr": "", "style": "00", "fuel": "0",
            "trans": "0", "financed": "", "recibe": "", "province": "0",
            "doors": "0", "yearfrom": "1960", "yearto": "2027",
            "pricefrom": "100000", "priceto": "0", "orderby": "0",
        }
    # rango maximo de anios si los campos existen
    for k in payload:
        kl = k.lower()
        if "yearfrom" in kl or kl == "ano1":
            payload[k] = "1960"
        if "yearto" in kl or kl == "ano2":
            payload[k] = "2027"
    return payload



def extract_ids(html):
    """Extract CRAutos detail IDs from any HTML response.

    Keep the patterns focused on cardetail.cfm links so we do not accidentally
    collect unrelated query-string parameters named c.
    """
    patterns = [
        r"cardetail\.cfm\?c=(\d+)",
        r"cardetail\.cfm\?car=(\d+)",
        r"/autosusados/cardetail\.cfm\?c=(\d+)",
        r"https?://(?:www\.)?crautos\.com/autosusados/cardetail\.cfm\?c=(\d+)",
    ]

    ids = set()
    for p in patterns:
        ids.update(re.findall(p, html, flags=re.I))
    return ids


def extract_pagination_urls(html, current_url):
    """Find pagination/search URLs that may contain additional listing IDs."""
    soup = BeautifulSoup(html, "lxml")
    urls = set()

    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href:
            continue

        abs_url = urljoin(current_url, href)
        low = abs_url.lower()

        if "crautos.com/autosusados/" not in low:
            continue

        # Keep search/listing pages only, not every detail page.
        if ("searchresults.cfm" in low or "index.cfm" in low) and (
            "p=" in low or "page" in low or "pag" in low or "start" in low
        ):
            urls.add(abs_url)

    return urls


def collect_ids(session, delay, max_pages=200):
    """Collect CRAutos listing IDs using several discovery strategies.

    More robust than only POSTing searchresults.cfm?p=N:
    - The index page may already contain a batch of listings.
    - CRAutos may expose pagination as links rather than honoring ?p=N.
    - Some ColdFusion pages return the same first page when the wrong pagination
      parameter is used, so we stop when pages are repeated.
    """
    payload = discover_form_defaults(session)
    print(f"Payload de busqueda: {payload}")

    all_ids = set()
    seen_page_signatures = set()
    visited_urls = set()
    queued_urls = []

    def handle_response(resp, label):
        nonlocal all_ids, queued_urls

        if not resp:
            return set()

        html = resp.text or ""
        signature = hash(html[:5000])

        ids = extract_ids(html)
        pagination_urls = extract_pagination_urls(html, resp.url)

        if DEBUG_DISCOVERY:
            soup = BeautifulSoup(html, "lxml")
            page_title = soup.title.get_text(" ", strip=True) if soup.title else "NO_TITLE"
            sample = re.sub(r"\s+", " ", html[:900]).strip()
            print(f"  DEBUG {label} URL_FINAL={resp.url}")
            print(f"  DEBUG {label} TITLE={page_title}")
            print(f"  DEBUG {label} HTML_SAMPLE={sample}")
            print(f"  DEBUG {label} IDS_SAMPLE={sorted(list(ids))[:12]}")
            print(f"  DEBUG {label} PAGINATION_LINKS={sorted(list(pagination_urls))[:8]}")

        if signature in seen_page_signatures:
            print(f"  {label}: pagina repetida; ids={len(ids)}; saltando")
            return set()

        seen_page_signatures.add(signature)

        new = ids - all_ids
        all_ids |= ids

        print(f"  {label}: {len(ids)} ids ({len(new)} nuevos, total {len(all_ids)})")

        for u in pagination_urls:
            if u not in visited_urls:
                queued_urls.append(u)

        return new

    # 1) Index page.
    r0 = fetch(session, "GET", INDEX_URL)
    if r0:
        visited_urls.add(r0.url)
        handle_response(r0, "index.cfm")

    # 2) First search POST.
    r1 = fetch(session, "POST", SEARCH_URL, data=payload)
    if r1:
        visited_urls.add(r1.url)
        handle_response(r1, "search POST inicial")

    # 3) Try common pagination parameter names with both POST and GET.
    page_params = ["p", "page", "Page", "PageNum", "pagina", "offset"]
    empty_streak = 0

    for page in range(1, max_pages + 1):
        page_added_anything = False

        for param in page_params:
            params = {param: page}

            r = fetch(session, "POST", SEARCH_URL, params=params, data=payload)
            if r:
                visited_urls.add(r.url)
                new = handle_response(r, f"POST {param}={page}")
                if new:
                    page_added_anything = True

            r = fetch(session, "GET", SEARCH_URL, params={**payload, **params})
            if r:
                visited_urls.add(r.url)
                new = handle_response(r, f"GET {param}={page}")
                if new:
                    page_added_anything = True

            time.sleep(delay + random.uniform(0, 0.25))

        if page_added_anything:
            empty_streak = 0
        else:
            empty_streak += 1

        # Follow pagination URLs discovered in the HTML.
        while queued_urls and len(visited_urls) < max_pages * 4:
            u = queued_urls.pop(0)
            if u in visited_urls:
                continue
            visited_urls.add(u)
            rr = fetch(session, "GET", u)
            if rr:
                new = handle_response(rr, f"link {len(visited_urls)}")
                if new:
                    page_added_anything = True
            time.sleep(delay + random.uniform(0, 0.25))

        if page > 2 and empty_streak >= 2:
            break

    return all_ids


# ----------------------------------------------------------- FASE 2: DETALLES

def parse_int(s):
    if s is None:
        return None
    digits = re.sub(r"[^\d]", "", str(s))
    return int(digits) if digits else None


def parse_detail(html, car_id):
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text("\n", strip=True)
    d = {"id": int(car_id), "url": f"{DETAIL_URL}?c={car_id}",
         "scraped_at": datetime.utcnow().isoformat()}

    # Titulo: "Marca Modelo Anio" del og:title o h1
    title = None
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        title = og["content"]
    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(" ", strip=True) if h1 else ""
    m = re.match(r"\s*(\S+)\s+(.*?)\s+((?:19|20)\d{2})\b", title)
    if m:
        d["marca"], d["modelo"], d["anio"] = m.group(1), m.group(2).strip(), int(m.group(3))

    # Precios (colones y dolares; cualquiera puede ser el principal)
    crc = re.search(r"¢\s*([\d,\.]+)", title) or re.search(r"¢\s*([\d,\.]+)", text)
    usd = re.search(r"\$\s*([\d,\.]+)", title) or re.search(r"\(\$\s*([\d,\.]+)\)", text)
    d["precio_crc"] = parse_int(crc.group(1)) if crc else None
    d["precio_usd"] = parse_int(usd.group(1)) if usd else None
    d["moneda_original"] = "USD" if (title.strip().find("$") != -1 and
                                     title.strip().find("¢") > title.strip().find("$") >= 0) else "CRC"

    # Tabla de especificaciones (label -> valor)
    spec_map = {
        "Cilindrada": ("cilindrada_cc", parse_int),
        "Estilo": ("estilo", str.strip),
        "# de pasajeros": ("pasajeros", parse_int),
        "Combustible": ("combustible", str.strip),
        "Transmisión": ("transmision", str.strip),
        "Estado": ("estado", str.strip),
        "Kilometraje": ("kilometraje", parse_int),
        "Placa": ("placa_termina", str.strip),
        "Color exterior": ("color_exterior", str.strip),
        "Color interior": ("color_interior", str.strip),
        "# de puertas": ("puertas", parse_int),
        "Ya pagó impuestos": ("impuestos_pagos", str.strip),
        "Precio negociable": ("negociable", str.strip),
        "Se recibe vehículo": ("recibe_vehiculo", str.strip),
        "Provincia": ("provincia", str.strip),
        "Fecha de ingreso": ("fecha_ingreso", str.strip),
    }
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) >= 2:
            label = tds[0].get_text(" ", strip=True)
            value = tds[1].get_text(" ", strip=True)
            for key, (field, conv) in spec_map.items():
                if label.startswith(key):
                    try:
                        d[field] = conv(value)
                    except (ValueError, TypeError):
                        d[field] = value
                    break

    # Fecha de ingreso -> ISO
    fi = d.get("fecha_ingreso")
    if fi:
        m = re.search(r"(\d{1,2})\s+de\s+(\w+)\s+del?\s+(\d{4})", fi, re.I)
        if m and m.group(2).lower() in MESES:
            d["fecha_ingreso"] = (f"{m.group(3)}-{MESES[m.group(2).lower()]:02d}"
                                  f"-{int(m.group(1)):02d}")

    # Vistas
    m = re.search(r"visto\s+([\d,]+)\s+veces", text)
    d["vistas"] = parse_int(m.group(1)) if m else None

    # Comentario del vendedor (og:description)
    ogd = soup.find("meta", attrs={"property": "og:description"})
    d["comentario"] = ogd["content"].strip() if ogd and ogd.get("content") else None

    # Vendedor
    m = re.search(r"Nombre:\s*([^\n]+)", text)
    d["vendedor_nombre"] = m.group(1).strip() if m else None
    m = re.search(r"Teléfono:\s*([\d\-\s\+]+)", text)
    d["vendedor_tel"] = m.group(1).strip() if m else None
    m = re.search(r"whatsapp\.com/send\?phone=(\d+)", html)
    d["vendedor_wa"] = m.group(1) if m else None

    # Financiamiento + cuota
    d["financiamiento"] = 1 if ("Financiamiento disponible" in text or "Cuota" in text) else 0
    m = re.search(r"Cuota\s*\*?\s*\$?\s*([\d,]+)\s*/mes", text)
    d["cuota_usd_mes"] = parse_int(m.group(1)) if m else None

    # Equipamiento presente (las tablas de extras solo listan lo que el carro TIENE)
    found = [eq for eq in EQUIPMENT_FIELDS if eq in text]
    d["equipamiento"] = "|".join(found) if found else None

    # Fotos
    fotos = sorted(set(re.findall(
        rf"(https://crautos\.com/clasificados/usados/{car_id}-\d+\.jpg)", html)))
    d["fotos"] = "|".join(fotos) if fotos else None
    d["n_fotos"] = len(fotos)

    return d


def save_car(conn, d):
    cols = ", ".join(d.keys())
    qs = ", ".join("?" * len(d))
    conn.execute(f"INSERT OR REPLACE INTO cars ({cols}) VALUES ({qs})",
                 list(d.values()))
    conn.commit()


def export_csv(conn, path="crautos.csv"):
    cur = conn.execute("SELECT * FROM cars ORDER BY id")
    rows = cur.fetchall()
    headers = [c[0] for c in cur.description]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)
    print(f"Exportados {len(rows)} registros -> {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/tmp/crautos.db")
    ap.add_argument("--delay", type=float, default=1.0,
                    help="segundos entre requests (default 1.0)")
    ap.add_argument("--limit", type=int, default=0, help="max detalles a scrapear")
    ap.add_argument("--ids-only", action="store_true")
    ap.add_argument("--export", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.executescript(SCHEMA)

    if args.export:
        export_csv(conn)
        return

       session = make_session()

    print("== Fase 1: recolectando IDs del listado ==")

    import asyncio
    from .crautos_discover_httpx import discover_crautos

    discovered = asyncio.run(
        discover_crautos(
            limit=args.limit if args.limit > 0 else None,
            delay=args.delay
        )
    )

    ids = {cid for cid, url in discovered}

    print(f"Total IDs encontrados: {len(ids)}")
    with open("/tmp/crautos_ids.txt", "w") as f:
        f.write("\n".join(sorted(ids)))

    if args.ids_only:
        return

    done = {str(r[0]) for r in conn.execute("SELECT id FROM cars")}
    pending = sorted(ids - done)
    if args.limit:
        pending = pending[:args.limit]
    print(f"== Fase 2: {len(pending)} detalles pendientes ({len(done)} ya en DB) ==")

    for i, car_id in enumerate(pending, 1):
        r = fetch(session, "GET", DETAIL_URL, params={"c": car_id})
        if r:
            try:
                save_car(conn, parse_detail(r.text, car_id))
            except Exception as e:
                print(f"  [parse err] id={car_id}: {e}")
        if i % 50 == 0:
            print(f"  {i}/{len(pending)} ({datetime.now():%H:%M:%S})")
        time.sleep(args.delay + random.uniform(0, 0.4))

    print("Listo. Ejecuta con --export para generar el CSV.")


if __name__ == "__main__":
    main()
