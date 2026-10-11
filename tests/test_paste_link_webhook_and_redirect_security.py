"""Regression checks for webhook signature and fetch redirect policy."""
from pathlib import Path


def test_whatsapp_webhook_verifies_meta_signature_before_parsing():
    code = Path("app/main.py").read_text()
    handler = code.split('@app.post("/whatsapp/webhook")', 1)[1].split("\ndef ", 1)[0]
    assert 'META_APP_SECRET' in handler
    assert 'X-Hub-Signature-256' in handler
    assert 'hmac.compare_digest' in handler
    assert handler.index('hmac.compare_digest') < handler.index('json.loads(raw)')
    assert 'status_code=503' in handler


def test_third_party_resolvers_do_not_follow_redirects():
    for name in ("facebook", "encuentra24"):
        source = Path(f"app/resolvers/{name}.py").read_text()
        assert 'follow_redirects=False' in source
        assert '300 <= r.status_code < 400' in source
