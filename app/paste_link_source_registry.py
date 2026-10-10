"""Reviewed URL-shape registry for read-only staging.

'enabled' means a single user-supplied listing can be tried after robots review,
NOT that accurate extraction, permitted commercial use or entire source is certified.
Only exact roots and www hosts. No redirects, arbitrary subdomains, catalogs, or
whole-site crawling are enabled here.
"""
from __future__ import annotations
import re
from urllib.parse import urlparse

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
        "route": r"^/car-finder/[a-z0-9][a-z0-9-]+/?$", "enabled": True,
    },
    "carros.com": {
        "name": "Carros.com", "stage": "experimental",
        "route": r"^/car/[a-z0-9]{32}-p[0-9]+/?$", "enabled": True,
    },
    "motorasv.com": {
        "name": "Motora SV", "stage": "route_pending",
        "route": None, "enabled": False,
    },
    "autospublicidad.com": {
        "name": "Autos Publicidad", "stage": "route_pending",
        "route": None, "enabled": False,
    },
    "disazautos.com": {
        "name": "Disaz Autos", "stage": "route_pending",
        "route": None, "enabled": False,
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
        if p.query or p.fragment:
            return None
        host = (p.hostname or "").lower().rstrip(".")
        host = host[4:] if host.startswith("www.") else host
        entry = SOURCES.get(host)
        if not entry or not entry["enabled"]:
            return None
        if not re.fullmatch(entry["route"], p.path.lower()):
            return None
        return host, entry
    except (ValueError, TypeError):
        return None


def public_status():
    return [{"domain": domain, "name": src["name"], "stage": src["stage"],
             "enabled": src["enabled"]} for domain, src in SOURCES.items()]
