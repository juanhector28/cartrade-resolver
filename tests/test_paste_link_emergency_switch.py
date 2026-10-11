"""Source switch smoke guard: disabled pilot URLs never reach a resolver."""
from pathlib import Path


def test_production_source_switch_precedes_resolution():
    source = Path('app/main.py').read_text()
    handler = source.split('@app.post("/resolve-link")', 1)[1].split('@app.post(', 1)[0]
    assert 'PASTE_LINK_DISABLED_SOURCES' in handler
    assert handler.index('request_host in disabled_sources') < handler.index('platforms.is_allowed(url)')
    assert 'status_code=503' in handler
