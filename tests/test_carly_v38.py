import base64
from io import BytesIO

from PIL import Image
try:
    import pillow_avif  # noqa: F401
except Exception:
    pillow_avif = None

from app import main_v38 as v38


def _body(text):
    return {"messages": [{"role": "user", "content": text}], "country": "sv"}


def test_plural_no_pickups_is_hard_exclusion():
    c = v38.v37._constraints(_body(
        "Hago delivery. No quiero pickups ni carros sospechosos. Automático, máximo US$250 al mes."
    ))
    assert "pickup" in c["avoid_body"]
    assert c["require_body"] is None


def test_profile_clears_stale_pickup_requirement_when_pickup_is_avoided():
    result = {"profile": {"require_body": ["pickup"], "avoid_body": []}}
    c = {"avoid_body": ["pickup"], "prefer_brands": [], "avoid_brands": [],
         "require_transmission": "automatic", "passengers": 5, "total_budget": None,
         "min_year": None}
    v38._refresh_profile(result, c)
    assert result["profile"]["require_body"] == []
    assert "pickup" in result["profile"]["avoid_body"]


def test_avif_download_is_converted_to_real_jpeg(monkeypatch):
    # Generate a tiny valid AVIF in memory using the same decoder/encoder stack CI installs.
    source = BytesIO()
    Image.new("RGB", (8, 8), (120, 80, 40)).save(source, format="AVIF")
    avif_bytes = source.getvalue()
    assert v38._looks_avif(avif_bytes)

    class Response:
        content = avif_bytes
        headers = {"content-type": "image/avif"}
        def raise_for_status(self):
            return None

    class Client:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def get(self, url): return Response()

    monkeypatch.setattr(v38.httpx, "Client", Client)
    result = v38._download_image("https://photos.example/car")
    assert result is not None
    media, encoded = result
    payload = base64.b64decode(encoded)
    assert media == "image/jpeg"
    assert payload[:2] == b"\xff\xd8"


def test_v38_brain_version_wrap(monkeypatch):
    monkeypatch.setattr(v38, "_ORIG_APPLY", lambda body, prior: {
        "recommendation_brain": {"version": "v37"},
        "advisor_mode": "recommendation_brain_v37",
    })
    result = v38._apply({}, {})
    assert result["recommendation_brain"]["version"] == "v38"
    assert result["advisor_mode"] == "recommendation_brain_v38"
