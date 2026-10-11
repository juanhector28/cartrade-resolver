"""Reviewed URL-shape registry for read-only staging.

'enabled' means a single user-supplied listing can be tried after robots review,
NOT that accurate extraction, permitted commercial use or entire source is certified.
Only exact roots and www hosts. No redirects, arbitrary subdomains, catalogs, or
whole-site crawling are enabled here.
"""
from __future__ import annotations
import re
from urllib.parse import urlparse, parse_qsl

SOURCES = {
    "carroselsalvador.com": {
        "name": "Carros El Salvador", "stage": "browser_verified",
        "route": r"^/anuncios/[a-z0-9][a-z0-9-]+/?$", "enabled": True,
    },
    "tucarro.sv": {
        "name": "TuCarro.sv", "stage": "experimental",
        "route": r"^/[a-z0-9][a-z0-9-]*/[a-f0-9]{8}/?$", "enabled": True,
    },
    "caragencia.com": {
        "name": "CarAgencia", "stage": "experimental",
        "route": r"^/(?:es/)?car-finder/[a-z0-9][a-z0-9-]+/?$", "enabled": True,
    },
    "carros.com": {
        "name": "Carros.com", "stage": "experimental",
        "route": r"^/car/[a-z0-9]{32}-p[0-9]+/?$", "enabled": True,
    },
    "motorasv.com": {
        "name": "Motora SV", "stage": "experimental",
        "route": r"^/cars/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}/?$", "enabled": True,
    },
    "autospublicidad.com": {
        "name": "Autos Publicidad", "stage": "experimental",
        "route": r"^/sv/detalles/?$", "enabled": True,
        "query_mode": "autospublicidad_vehicle",
    },
    "disazautos.com": {
        "name": "Disaz Autos", "stage": "experimental",
        "route": r"^/product-page/[a-z0-9][a-z0-9-]+/?$", "enabled": True,
    },
    "carvimax.com": {
        "name": "Carvimax", "stage": "experimental",
        "route": r"^/[a-z0-9][a-z0-9-]+/[1-9][0-9]{0,6}/?$", "enabled": True,
    },
    "easycar.com.sv": {
        "name": "EasyCar", "stage": "javascript_required",
        "route": r"^/car/[1-9][0-9]{0,6}/?$", "enabled": True,
    },
    "eurosportautos.com": {
        "name": "Eurosport Autos", "stage": "access_review",
        "route": r"^/vehiculo/[a-z0-9][a-z0-9-]+/?$", "enabled": True,
    },
    "crediq.com": {
        "name": "CrediQ", "stage": "access_review",
        "route": r"^/sv/product/[a-z0-9][a-z0-9-]+/?$", "enabled": True,
    },
    "julajups.sv": {
        "name": "Julajups", "stage": "experimental",
        "route": r"^/anuncio/[a-z0-9][a-z0-9-]+-[a-z0-9]{10}/?$", "enabled": True,
    },
    # Wave 4 candidate routes from Atlas SV individual listing receipts.
    # Disabled until the site-local robots/metadata preflight has passed.
    "usados.excelautomotriz.com": {
        "name": "Excel Usados", "stage": "candidate_review",
        "route": r"^/autos-el-salvador/[a-z0-9][a-z0-9-]+/?$", "enabled": False,
    },
    "encuentra24.com": {
        "name": "Encuentra24", "stage": "candidate_review",
        "route": r"^/el-salvador-es/autos-usados/[a-z0-9][a-z0-9-]+/[1-9][0-9]{5,11}/?$",
        "enabled": False,
    },
    "finder.porsche.com": {
        "name": "Porsche Finder", "stage": "candidate_review",
        "route": r"^/sv/es-sv/details/[a-z0-9][a-z0-9-]+/?$",
        "enabled": False, "query_mode": "porsche_finder_detail",
    },
    "xautomarket.com": {
        "name": "xAutoMarket", "stage": "candidate_review",
        "route": r"^/comprar/[a-z0-9]{5,20}/?$", "enabled": False,
    },
    "credipro.com.sv": {
        "name": "Credipro", "stage": "candidate_review",
        "route": r"^/stock/?$", "enabled": False,
        "fragment_mode": "vehicle_detail",
    },
    # New source discovered beyond the 56-entry Atlas SV census.
    "sv.anuto.app": {
        "name": "Anuto El Salvador", "stage": "candidate_review",
        "route": r"^/ad/[a-z0-9][a-z0-9.-]+-[a-z0-9]{20}/?$", "enabled": False,
    },
    "nissanelsalvador.com": {
        "name": "Nissan El Salvador", "stage": "route_pending",
        "route": None, "enabled": False,
    },
}
def source_for_url(url: str):
    """Return (canonical host, source definition) only for permitted listing route."""
    if not isinstance(url, str) or len(url) > 2048:
        return None
    try:
        p = urlparse(url)
        if p.scheme != "https" or p.username or p.password or p.port is not None:
            return None
        if p.fragment:
            return None
        host = (p.hostname or "").lower().rstrip(".")
        host = host[4:] if host.startswith("www.") else host
        entry = SOURCES.get(host)
        if not entry or not entry["enabled"]:
            return None
        if not re.fullmatch(entry["route"], p.path.lower()):
            return None
        if entry.get("query_mode") == "autospublicidad_vehicle":
            if len(p.query) > 160:
                return None
            try:
                query = parse_qsl(p.query, strict_parsing=True, max_num_fields=2)
            except ValueError:
                return None
            if len(query) != 2 or {k for k, _ in query} != {"auto", "id"}:
                return None
            params = dict(query)
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,70}", params["auto"], re.I):
                return None
            if not re.fullmatch(r"[1-9][0-9]{0,6}", params["id"]):
                return None
        elif p.query:
            return None
        return host, entry
    except (ValueError, TypeError):
        return None


def public_status():
    return [{"domain": domain, "name": src["name"], "stage": src["stage"],
             "enabled": src["enabled"]} for domain, src in SOURCES.items()]
