"""Consent-gated link-first buyer interest, independent of third-party extraction."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()
_ALLOWED_COUNTRIES = {"el-salvador-es": "sv", "guatemala-es": "gt", "panama-es": "pa",
                      "costa-rica-es": "cr", "honduras-es": "hn", "nicaragua-es": "ni"}
_PHONE = re.compile(r"^\\+?[0-9][0-9 ()-]{6,22}$")
_EMAIL = re.compile(r"^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$")
_rate_window: dict[str, list[float]] = {}


class LinkInterest(BaseModel):
    listing_url: str = Field(min_length=12, max_length=2048)
    buyer_contact: str = Field(min_length=5, max_length=254)
    contact_channel: str
    consent_to_contact: bool
    website: str = Field(default="", max_length=200)  # honeypot


def _validated_url(value: str) -> tuple[str, str, str]:
    try:
        u = urlsplit(value.strip())
        host = (u.hostname or "").lower().removeprefix("www.")
        if u.scheme != "https" or not host or u.username or u.password or u.port or u.fragment:
            raise ValueError()
        if host == "localhost" or host.endswith(".local") or re.fullmatch(r"\\d+(?:\\.\\d+){3}", host):
            raise ValueError()
        if not (host == "encuentra24.com" or host.endswith(".encuentra24.com")
                or (host.count(".") >= 1 and re.fullmatch(r"[a-z0-9.-]+", host))):
            raise ValueError()
        country = next((code for slug, code in _ALLOWED_COUNTRIES.items() if u.path.lower().startswith("/" + slug + "/")), "unknown")
        source = "encuentra24" if host == "encuentra24.com" or host.endswith(".encuentra24.com") else host
        return value.strip(), country, source
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail="Enlace no válido; usa una URL HTTPS pública.")


def _contact(value: str, channel: str) -> str:
    value = value.strip()
    if channel == "email" and _EMAIL.fullmatch(value):
        return value
    if channel == "whatsapp" and _PHONE.fullmatch(value) and 8 <= len(re.sub(r"\\D", "", value)) <= 15:
        return value
    raise HTTPException(status_code=422, detail="Ingresa un WhatsApp o correo válido.")


@router.post("/link-interest", status_code=201)
async def link_interest(body: LinkInterest, request: Request):
    if not body.consent_to_contact:
        raise HTTPException(status_code=422, detail="Es necesario autorizar el contacto.")
    if body.website:
        raise HTTPException(status_code=422, detail="Solicitud no válida.")
    url, country, source = _validated_url(body.listing_url)
    contact = _contact(body.buyer_contact, body.contact_channel)
    # Lightweight per-process guard; keep the DB write private and never expose buyer information.
    import time
    now = time.monotonic()
    ip = request.client.host if request.client else "unknown"
    entries = [t for t in _rate_window.get(ip, []) if now - t < 3600]
    if len(entries) >= 6:
        raise HTTPException(status_code=429, detail="Demasiadas solicitudes. Intenta más tarde.")
    entries.append(now)
    _rate_window[ip] = entries
    from .main import supabase
    if supabase is None:
        raise HTTPException(status_code=503, detail="Servicio de solicitudes temporalmente no disponible.")
    request_id = str(uuid.uuid4())
    try:
        supabase.table("buyer_intents").insert({
            "request_id": request_id,
            "buyer_contact": contact,
            "contact_channel": body.contact_channel,
            "listing_url": url,
            "car_name": "Vehículo pendiente de verificar",
            "price_usd": None,
            "country": country,
            "source": source,
            "consent_to_contact": True,
            "consent_recorded_at": datetime.now(timezone.utc).isoformat(),
            "status": "received"
        }).execute()
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo guardar la solicitud. Inténtalo de nuevo.")
    return {"received": True, "request_id": request_id, "message": "Recibimos tu enlace. Te contactaremos por el medio elegido."}
