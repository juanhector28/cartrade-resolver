from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse, urldefrag

import httpx
from bs4 import BeautifulSoup


USER_AGENT = os.getenv(
    "ATLAS_RUNNER_USER_AGENT",
    "Mozilla/5.0 (compatible; CarTradeAtlas/0.1; +https://cartrade.live)",
)

_DETAIL_HINTS = (
    "/vehiculo/", "/vehicle/", "/vehicles/", "/car/", "/cars/", "/auto/",
    "/autos/", "/listing/", "/anuncio/", "/detalle/", "/detail/",
)
_HUB_HINTS = (
    "buscador", "search", "catalog", "catalogo", "inventory", "inventario",
    "vehicles", "vehiculos", "autos", "carros", "used", "usados",
)
_SKIP_HINTS = (
    "privacy", "privacidad", "terms", "terminos", "about", "nosotros", "contact",
    "login", "register", "registro", "blog", "news", "noticias", "facebook.com",
    "instagram.com", "tiktok.com", "x.com", "wa.me", "mailto:", "tel:",
)
_ASSET_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".pdf", ".zip", ".css", ".js")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_url(base: str, href: str | None) -> str | None:
    if not href:
        return None
    href = href.strip()
    if not href or href.startswith(("javascript:", "mailto:", "tel:")):
        return None
    url = urljoin(base, href)
    url, _ = urldefrag(url)
    p = urlparse(url)
    if p.scheme not in {"http", "https"}:
        return None
    if p.path.lower().endswith(_ASSET_EXT):
        return None
    return url


def _same_site(a: str, b: str) -> bool:
    def host(u: str) -> str:
        return urlparse(u).netloc.lower().removeprefix("www.")
    return host(a) == host(b)


def _url_score(url: str) -> int:
    low = url.lower()
    score = 0
    if any(h in low for h in _DETAIL_HINTS):
        score += 20
    if re.search(r"/\d{3,}(?:[-/?#]|$)", low):
        score += 4
    if len(urlparse(url).path.strip("/").split("/")) >= 2:
        score += 2
    if any(h in low for h in _HUB_HINTS):
        score -= 3
    if any(h in low for h in _SKIP_HINTS):
        score -= 30
    return score


def _deep_values(obj: Any, path: str) -> list[Any]:
    """Find a dotted JSON-LD path anywhere in an object/@graph tree."""
    parts = [p for p in (path or "").split(".") if p]
    out: list[Any] = []

    def at(node: Any, idx: int):
        if idx >= len(parts):
            out.append(node)
            return
        if isinstance(node, list):
            for item in node:
                at(item, idx)
            return
        if not isinstance(node, dict):
            return
        key = parts[idx]
        if key in node:
            at(node[key], idx + 1)
        for child_key in ("@graph", "itemListElement"):
            child = node.get(child_key)
            if child is not None:
                at(child, idx)

    def walk(node: Any):
        at(node, 0)
        if isinstance(node, dict):
            for v in node.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                if isinstance(v, (dict, list)):
                    walk(v)

    walk(obj)
    # stable de-duplication
    seen = set()
    dedup = []
    for v in out:
        try:
            k = json.dumps(v, sort_keys=True, ensure_ascii=False)
        except Exception:
            k = repr(v)
        if k not in seen:
            seen.add(k); dedup.append(v)
    return dedup


def _jsonld_docs(soup: BeautifulSoup) -> list[Any]:
    docs = []
    for tag in soup.select('script[type="application/ld+json"]'):
        raw = tag.string or tag.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            docs.append(json.loads(raw))
        except Exception:
            continue
    return docs


def _text_value(node) -> Any:
    if node is None:
        return None
    return node.get_text(" ", strip=True)


def _first_scalar(value: Any) -> Any:
    if isinstance(value, list):
        return _first_scalar(value[0]) if value else None
    if isinstance(value, dict):
        for k in ("value", "name", "url", "contentUrl"):
            if k in value:
                return _first_scalar(value[k])
        return None
    return value


def _number(value: Any) -> float | None:
    value = _first_scalar(value)
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).replace("\xa0", " ").strip()
    # Keep digits and separators; choose the last sensible numeric token.
    tokens = re.findall(r"\d[\d.,\s]*", s)
    if not tokens:
        return None
    token = tokens[-1].replace(" ", "")
    # 1,234.56 vs 1.234,56 vs 185,000
    if "," in token and "." in token:
        if token.rfind(".") > token.rfind(","):
            token = token.replace(",", "")
        else:
            token = token.replace(".", "").replace(",", ".")
    elif token.count(",") == 1 and len(token.split(",")[-1]) <= 2:
        token = token.replace(",", ".")
    else:
        token = token.replace(",", "")
    try:
        return float(token)
    except Exception:
        return None


def _transform(value: Any, transform: str | None) -> Any:
    if value is None or not transform:
        return value
    if transform == "money_to_usd_number":
        n = _number(value)
        return round(n, 2) if n is not None else None
    if transform == "year_int":
        m = re.search(r"\b(19\d{2}|20\d{2})\b", str(_first_scalar(value) or ""))
        return int(m.group(1)) if m else None
    if transform == "distance_to_km":
        n = _number(value)
        if n is None:
            return None
        s = str(value).lower()
        if "mile" in s or "milla" in s:
            n *= 1.609344
        return int(round(n))
    if transform == "normalize_fuel":
        s = str(_first_scalar(value) or "").strip().lower()
        if "diesel" in s or "diésel" in s: return "Diesel"
        if "gas" in s: return "Gasolina"
        if "hybrid" in s or "hibr" in s: return "Híbrido"
        if "electric" in s or "eléctr" in s or "electr" in s: return "Eléctrico"
        return str(_first_scalar(value)).strip() or None
    if transform == "normalize_transmission":
        s = str(_first_scalar(value) or "").strip().lower()
        if "manual" in s or "mec" in s: return "Manual"
        if "auto" in s: return "Automática"
        return str(_first_scalar(value)).strip() or None
    if transform == "image_list":
        if isinstance(value, list):
            vals = value
        else:
            vals = [value]
        out = []
        for item in vals:
            if isinstance(item, dict):
                item = item.get("url") or item.get("contentUrl")
            if isinstance(item, str) and item.startswith("http") and item not in out:
                out.append(item)
        return out[:12]
    return value


def _extract_method(method: dict, soup: BeautifulSoup, html: str, docs: list[Any]) -> Any:
    kind = method.get("kind")
    value = None
    if kind == "jsonld":
        path = method.get("path") or ""
        for doc in docs:
            vals = _deep_values(doc, path)
            if vals:
                value = vals[0] if len(vals) == 1 else vals
                break
    elif kind in {"css", "attribute"}:
        selector = method.get("selector")
        if selector:
            try:
                node = soup.select_one(selector)
            except Exception:
                node = None
            if node is not None:
                attr = method.get("attribute")
                value = node.get(attr) if attr else _text_value(node)
    elif kind == "regex":
        pattern = method.get("pattern")
        if pattern:
            try:
                m = re.search(pattern, html, re.I | re.S)
                value = m.group(1) if m and m.groups() else (m.group(0) if m else None)
            except Exception:
                value = None
    return _transform(value, method.get("transform"))


def extract_listing(manifest: dict, url: str, html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    docs = _jsonld_docs(soup)
    fields = manifest.get("fields") or {}
    out: dict[str, Any] = {"url": url}
    for field, spec in fields.items():
        chosen = None
        for method in spec.get("methods") or []:
            chosen = _extract_method(method, soup, html, docs)
            if chosen not in (None, "", []):
                break
        if chosen not in (None, "", []):
            out[field] = chosen

    # URL in the page is useful, but the requested URL is canonical enough for identity.
    out["url"] = str(out.get("url") or url)

    # Extra normalization evidence that the v1.1 manifest does not yet expose as fields.
    for doc in docs:
        currencies = _deep_values(doc, "offers.priceCurrency")
        if currencies:
            out["currency"] = str(_first_scalar(currencies[0]) or "").upper() or None
            break
    if not out.get("currency"):
        text = soup.get_text(" ", strip=True)[:5000]
        if re.search(r"\bUSD\b|US\$|\$\s*\d", text, re.I): out["currency"] = "USD"
        elif re.search(r"\bGTQ\b|Q\s*\d", text, re.I): out["currency"] = "GTQ"

    required = manifest.get("required_fields") or [
        k for k, v in fields.items() if isinstance(v, dict) and v.get("required")
    ]
    out["_required_ok"] = all(out.get(k) not in (None, "", []) for k in required)
    out["_required_fields"] = required
    return out


def _money_usd(raw_price: Any, currency: str | None) -> float | None:
    """Conservative currency normalization for staging rows.

    Unknown/non-USD currencies are NOT silently mislabeled as USD. Optional
    per-currency units-per-USD rates can be supplied through env vars, e.g.
    ATLAS_FX_GTQ_PER_USD=7.65. Shadow extraction remains valid without them.
    """
    n = _number(raw_price)
    if n is None:
        return None
    cur = (currency or "USD").upper()
    if cur in {"USD", "US$", "$"}:
        return round(n, 2)
    env_key = f"ATLAS_FX_{cur}_PER_USD"
    try:
        per_usd = float(os.getenv(env_key, ""))
    except Exception:
        per_usd = 0
    if per_usd > 0:
        return round(n / per_usd, 2)
    return None


class AtlasManifestRunner:
    def __init__(self, supabase=None):
        self.supabase = supabase
        self.timeout = float(os.getenv("ATLAS_RUNNER_TIMEOUT", "25"))
        self.concurrency = max(1, min(int(os.getenv("ATLAS_RUNNER_CONCURRENCY", "4")), 8))

    async def _fetch(self, client: httpx.AsyncClient, url: str) -> str:
        r = await client.get(url)
        r.raise_for_status()
        ctype = (r.headers.get("content-type") or "").lower()
        if "html" not in ctype and "xhtml" not in ctype:
            raise ValueError(f"non_html_content:{ctype[:80]}")
        return r.text

    async def _discover(self, client: httpx.AsyncClient, manifest: dict, scan_limit: int) -> tuple[list[str], list[dict]]:
        starts = manifest.get("start_urls") or [manifest.get("base_url")]
        starts = [u for u in starts if u]
        if not starts:
            return [], []
        base = starts[0]
        pages: list[tuple[str, str]] = []
        debug: list[dict] = []

        # Start pages plus a few obvious catalog/search hubs found on them.
        hub_urls: list[str] = []
        for start in starts[:4]:
            try:
                html = await self._fetch(client, start)
                pages.append((start, html))
                soup = BeautifulSoup(html, "lxml")
                for a in soup.select("a[href]"):
                    u = _clean_url(start, a.get("href"))
                    if not u or not _same_site(base, u):
                        continue
                    low = u.lower()
                    if any(h in low for h in _HUB_HINTS) and not any(h in low for h in _DETAIL_HINTS):
                        if u not in starts and u not in hub_urls:
                            hub_urls.append(u)
            except Exception as exc:
                debug.append({"page": start, "error": str(exc)[:200]})

        for hub in hub_urls[:3]:
            try:
                html = await self._fetch(client, hub)
                pages.append((hub, html))
            except Exception as exc:
                debug.append({"page": hub, "error": str(exc)[:200]})

        selector = manifest.get("listing_url_selector") or "a[href]"
        attr = manifest.get("listing_url_attribute") or "href"
        candidates: dict[str, int] = {}
        for page_url, html in pages:
            soup = BeautifulSoup(html, "lxml")
            try:
                nodes = soup.select(selector)
            except Exception:
                nodes = soup.select("a[href]")
            for node in nodes:
                href = node.get(attr) if hasattr(node, "get") else None
                u = _clean_url(page_url, href)
                if not u or not _same_site(base, u) or u in starts:
                    continue
                score = _url_score(u)
                if score > candidates.get(u, -999):
                    candidates[u] = score
        ordered = [u for u, _ in sorted(candidates.items(), key=lambda kv: (-kv[1], kv[0]))]
        debug.append({
            "pages_scanned": [u for u, _ in pages],
            "candidate_count": len(ordered),
            "top_candidates": ordered[:10],
        })
        return ordered[:scan_limit], debug

    def _db_record(self, source_id: str, country: str, domain: str, manifest_version: int | None, item: dict) -> dict:
        photos = item.get("photos") or []
        if isinstance(photos, str):
            photos = [photos]
        photos = [p for p in photos if isinstance(p, str) and p.startswith("http")][:12]
        currency = item.get("currency")
        raw_price = item.get("price_usd")
        price_usd = _money_usd(raw_price, currency)
        now = _now_iso()
        raw = {k: v for k, v in item.items() if not k.startswith("_")}
        raw["atlas"] = {
            "source_id": source_id,
            "manifest_version": manifest_version,
            "shadow": True,
            "raw_price": raw_price,
            "raw_currency": currency,
        }
        return {
            "source": f"atlas:{domain}",
            "country": country.lower(),
            "url": item.get("url"),
            "title": item.get("title"),
            "make": item.get("make"),
            "model": item.get("model"),
            "year": item.get("year"),
            "km": item.get("km"),
            "price_usd": price_usd,
            "currency": "USD" if price_usd is not None else currency,
            "fuel_type": item.get("fuel_type"),
            "transmission": item.get("transmission"),
            "photos": photos,
            "photo_count": len(photos),
            "primary_photo": photos[0] if photos else None,
            "raw_payload": raw,
            "scraped_at": now,
            "updated_at": now,
            "last_seen_at": now,
            "status": "staging",
            "is_addressable": False,
            "listing_state": "indexed",
        }

    async def run(
        self,
        source_id: str,
        country: str,
        domain: str,
        manifest: dict,
        manifest_version: int | None = None,
        limit: int = 20,
        scan_limit: int = 80,
        persist: bool = True,
    ) -> dict[str, Any]:
        started = datetime.now(timezone.utc)
        limit = max(1, min(int(limit), 100))
        scan_limit = max(limit, min(int(scan_limit), 300))
        rendering = (manifest.get("crawl_rendering") or "http").lower()
        if rendering not in {"http", "static", "html"}:
            return {
                "ok": False, "source_id": source_id, "reason": "rendering_not_supported_yet",
                "crawl_rendering": rendering,
            }

        headers = {"User-Agent": USER_AGENT, "Accept-Language": "es,en;q=0.8"}
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            candidates, discovery_debug = await self._discover(client, manifest, scan_limit)
            sem = asyncio.Semaphore(self.concurrency)

            async def one(url: str):
                async with sem:
                    try:
                        html = await self._fetch(client, url)
                        item = extract_listing(manifest, url, html)
                        return {"url": url, "item": item, "error": None}
                    except Exception as exc:
                        return {"url": url, "item": None, "error": str(exc)[:240]}

            # Work in small waves and stop once enough valid vehicles are proven.
            valid: list[dict] = []
            attempted = 0
            errors: list[dict] = []
            wave = max(self.concurrency * 2, 8)
            for i in range(0, len(candidates), wave):
                batch = candidates[i:i + wave]
                results = await asyncio.gather(*(one(u) for u in batch))
                attempted += len(results)
                for res in results:
                    if res["error"]:
                        errors.append({"url": res["url"], "error": res["error"]})
                        continue
                    item = res["item"] or {}
                    if item.get("_required_ok"):
                        valid.append(item)
                        if len(valid) >= limit:
                            break
                if len(valid) >= limit:
                    break

        valid = valid[:limit]
        saved = 0
        save_errors: list[str] = []
        if persist and self.supabase:
            for item in valid:
                try:
                    record = self._db_record(source_id, country, domain, manifest_version, item)
                    self.supabase.table("scraped_listings").upsert(record, on_conflict="url").execute()
                    saved += 1
                except Exception as exc:
                    save_errors.append(str(exc)[:240])
        elif persist and not self.supabase:
            save_errors.append("supabase_not_connected")

        required_success_pct = round((len(valid) / attempted * 100), 2) if attempted else 0.0
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        ok = bool(len(valid) >= min(2, limit) and required_success_pct >= 20 and (not persist or saved > 0))
        return {
            "ok": ok,
            "source_id": source_id,
            "country": country.upper(),
            "domain": domain,
            "manifest_version": manifest_version,
            "candidate_urls": len(candidates),
            "attempted": attempted,
            "valid_listings": len(valid),
            "saved_shadow": saved,
            "required_success_pct": required_success_pct,
            "persist": persist,
            "addressable": False,
            "elapsed_seconds": round(elapsed, 2),
            "sample": [
                {k: v for k, v in item.items() if not k.startswith("_")}
                for item in valid[:5]
            ],
            "discovery_debug": discovery_debug,
            "errors": errors[:10],
            "save_errors": save_errors[:10],
        }
