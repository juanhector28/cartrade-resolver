"""URL → Platform detection."""
from __future__ import annotations
from urllib.parse import urlparse
from .resolvers.base import Platform
from .paste_link_source_registry import SOURCES, source_for_url


def detect(url: str) -> Platform:
    """Detect platform from URL. Returns 'unknown' if no match."""
    try:
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return "unknown"

    if host == "encuentra24.com":
        return "encuentra24"
    if host in {"olx.com.sv", "olx.com.br", "olx.com.mx", "olx.com.ar", "olx.com.pe", "olx.com"}:
        return "olx"
    if host in {"facebook.com", "fb.com", "m.facebook.com"}:
        return "facebook"
    if host in ALLOWED_DOMAINS and ("mercadolibre." in host or "mercadolivre." in host):
        return "mercadolibre"
    return "unknown"


# Whitelist of domains we will resolve. Anything else returns 400 from main.
ALLOWED_DOMAINS = (
    "encuentra24.com",
    # SV domains observed in Atlas inventory; approval to access must still be reviewed.
    "caragencia.com", "carros.com", "motorasv.com", "tucarro.sv",
    "autospublicidad.com", "carroselsalvador.com", "disazautos.com",
    "julajups.sv",
    "olx.com.sv", "olx.com.br", "olx.com.mx", "olx.com.ar", "olx.com.pe", "olx.com",
    "facebook.com", "fb.com", "m.facebook.com",
    "mercadolibre.com.sv", "mercadolibre.com.mx", "mercadolibre.com.ar",
    "mercadolibre.com.co", "mercadolibre.com.pe", "mercadolivre.com.br",
    "articulo.mercadolibre.com.sv", "articulo.mercadolibre.com.mx",
    "articulo.mercadolibre.com.ar", "articulo.mercadolibre.com.co",
    "carro.mercadolivre.com.br", "auto.mercadolivre.com.br",
)



def is_readonly_public_pilot(url: str) -> bool:
    """All experimental SV registry sources remain read-only in production."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        return parsed.scheme == "https" and host in SOURCES and host != "encuentra24.com"
    except (ValueError, TypeError):
        return False


def is_listing_url(url: str) -> bool:
    """Conservative route guard for known dealer catalog URLs."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        path = parsed.path.rstrip("/").lower()
        category_routes = {
            "motorasv.com": {"/cars"},
            "tucarro.sv": {"/carros"},
            "disazautos.com": {"/importados"},
            "carroselsalvador.com": {"/anuncios"},
        }
        if host in SOURCES and host != "encuentra24.com":
            return source_for_url(url) is not None
        return path not in category_routes.get(host, set())
    except Exception:
        return False


def is_allowed(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port:
            return False
        host = (parsed.hostname or "").lower()
        return any(host == d or host == "www." + d for d in ALLOWED_DOMAINS)
    except Exception:
        return False
