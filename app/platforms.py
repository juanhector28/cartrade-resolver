"""URL → Platform detection."""
from __future__ import annotations
from urllib.parse import urlparse
from .resolvers.base import Platform


def detect(url: str) -> Platform:
    """Detect platform from URL. Returns 'unknown' if no match."""
    try:
        host = urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return "unknown"

    if "encuentra24.com" in host:
        return "encuentra24"
    if "olx." in host:
        return "olx"
    if "facebook.com" in host or "fb.com" in host or "m.facebook.com" in host:
        return "facebook"
    if "mercadolibre." in host or "mercadolivre." in host:
        return "mercadolibre"
    return "unknown"


# Whitelist of domains we will resolve. Anything else returns 400 from main.
ALLOWED_DOMAINS = (
    "encuentra24.com",
    "olx.com.sv", "olx.com.br", "olx.com.mx", "olx.com.ar", "olx.com.pe", "olx.com",
    "facebook.com", "fb.com", "m.facebook.com",
    "mercadolibre.com.sv", "mercadolibre.com.mx", "mercadolibre.com.ar",
    "mercadolibre.com.co", "mercadolibre.com.pe", "mercadolivre.com.br",
    "articulo.mercadolibre.com.sv", "articulo.mercadolibre.com.mx",
    "articulo.mercadolibre.com.ar", "articulo.mercadolibre.com.co",
    "carro.mercadolivre.com.br", "auto.mercadolivre.com.br",
)


def is_allowed(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
        return any(host == d or host.endswith("." + d) or host == "www." + d
                   for d in ALLOWED_DOMAINS)
    except Exception:
        return False
