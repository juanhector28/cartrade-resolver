"""URL → Platform detection."""
from __future__ import annotations
from urllib.parse import urlparse
from .safe_urls import is_public_url
from .resolvers.base import Platform


def detect(url: str) -> Platform:
    """Detect platform from URL. Returns 'unknown' if no match."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return "unknown"

    if host == "encuentra24.com" or host.endswith(".encuentra24.com"):
        return "encuentra24"
    if host == "olx.com" or host.startswith("olx.") or host.startswith("www.olx."):
        return "olx"
    if host in ("facebook.com", "fb.com") or host.endswith((".facebook.com", ".fb.com")):
        return "facebook"
    if host.startswith(("mercadolibre.", "mercadolivre.")) or ".mercadolibre." in host or ".mercadolivre." in host:
        return "mercadolibre"
    return "unknown"


# Whitelist of domains we will resolve. Anything else returns 400 from main.
ALLOWED_DOMAINS = (
    "encuentra24.com",
    # Established regional vehicle portals; generic OG fallback is used.
    "crautos.com", "crautos.com.cr", "encuentra24.com.pa",
    "movilauto.com", "autogogt.com", "agautoventas.com",
    "olx.com.sv", "olx.com.br", "olx.com.mx", "olx.com.ar", "olx.com.pe", "olx.com",
    "facebook.com", "fb.com", "m.facebook.com",
    "mercadolibre.com.sv", "mercadolibre.com.mx", "mercadolibre.com.ar",
    "mercadolibre.com.co", "mercadolibre.com.pe", "mercadolivre.com.br",
    "articulo.mercadolibre.com.sv", "articulo.mercadolibre.com.mx",
    "articulo.mercadolibre.com.ar", "articulo.mercadolibre.com.co",
    "carro.mercadolivre.com.br", "auto.mercadolivre.com.br",
)


def is_allowed(url: str) -> bool:
    """Accept public HTTP(S) listing URLs; the fetcher also validates redirects."""
    return is_public_url(url)
