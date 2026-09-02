"""Carly v38: make cached finalist vision work with Encuentra24 AVIF images.

Encuentra24's image CDN returns image/avif even when clients request JPEG. v37's
server-download bridge therefore mislabeled AVIF bytes as JPEG and the model call
failed closed without persisting vision results. v38 converts unsupported image
formats to JPEG locally before sending them to Anthropic.

Also closes two small state leaks found in the spicy repro:
- understand plural `no pickups` as an exclusion;
- remove stale `require_body=pickup` from the surfaced profile when pickup is excluded.
"""
from __future__ import annotations

import base64
import re
from io import BytesIO
from typing import Any

import httpx
from PIL import Image
try:  # registers AVIF support when the plugin is installed
    import pillow_avif  # type: ignore  # noqa: F401
except Exception:
    pillow_avif = None

from . import main_v37 as v37

app = v37.app
v36 = v37.v36
v31 = v37.v31
v28 = v37.v28
legacy = v37.legacy

_ORIG_APPLY = v37._apply
_ORIG_REFRESH_PROFILE = v37._refresh_profile

try:
    v31.v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = "commercial-v38-avif-vision"
except Exception:
    pass

# v37's constraint parser resolves this regex dynamically from its module.
v37._NO_PICKUP = re.compile(
    r"\b(?:no\s+(?:quiero|quisiera|acepto|busco|necesito)?\s*|sin\s+|nada\s+de\s+)"
    r"(?:una?\s+)?(?:pickups?|pick[- ]?ups?)\b",
    re.I,
)

_SUPPORTED = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def _looks_avif(data: bytes) -> bool:
    head = data[:64]
    return b"ftypavif" in head or b"ftypavis" in head


def _convert_to_jpeg(data: bytes) -> bytes | None:
    try:
        with Image.open(BytesIO(data)) as image:
            rgb = image.convert("RGB")
            out = BytesIO()
            rgb.save(out, format="JPEG", quality=84, optimize=True)
            payload = out.getvalue()
            return payload if payload else None
    except Exception:
        return None


def _download_image(url: str) -> tuple[str, str] | None:
    """Download a finalist photo and normalize AVIF/unsupported formats to JPEG."""
    try:
        with httpx.Client(
            timeout=10.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 CarTradeVision/1.0",
                "Accept": "image/jpeg,image/png,image/webp,image/avif,*/*;q=0.5",
            },
        ) as cli:
            response = cli.get(url)
            response.raise_for_status()
            data = response.content
            if not data or len(data) > 5_000_000:
                return None
            media = (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()

        if media == "image/avif" or _looks_avif(data) or media not in _SUPPORTED:
            converted = _convert_to_jpeg(data)
            if converted is None:
                return None
            data = converted
            media = "image/jpeg"

        return media, base64.b64encode(data).decode("ascii")
    except Exception:
        return None


def _refresh_profile(result: dict, c: dict[str, Any]) -> None:
    _ORIG_REFRESH_PROFILE(result, c)
    profile = dict(result.get("profile") or {})
    avoided = {v28._norm(x) for x in (c.get("avoid_body") or [])}
    if "pickup" in avoided:
        required = profile.get("require_body") or []
        if isinstance(required, str):
            required = [required]
        profile["require_body"] = [x for x in required if v28._norm(x) != "pickup"]
    result["profile"] = profile


def _apply(body: Any, prior_result: Any) -> Any:
    result = _ORIG_APPLY(body, prior_result)
    if not isinstance(result, dict):
        return result
    brain = dict(result.get("recommendation_brain") or {})
    if brain:
        brain["version"] = "v38"
        brain["vision_transport"] = "server_download_avif_to_jpeg_base64"
        brain["plural_pickup_negation"] = True
        brain["profile_constraint_cleanup"] = True
        result["recommendation_brain"] = brain
        result["advisor_mode"] = "recommendation_brain_v38"
    return result


# Patch the dynamically resolved globals in the already-installed route stack.
v37._download_image = _download_image
v37._refresh_profile = _refresh_profile
v31._apply = _apply
