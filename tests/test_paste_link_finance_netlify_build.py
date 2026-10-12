"""Netlify preview build must be additive and reject duplicate insertion."""
from pathlib import Path
import pytest
from scripts.build_cartrade_netlify_preview import integrate, integrate_lead_capture, MARKER, LEAD_GATE_MARKER


def test_finance_preview_integration_preserves_original_html():
    original = '<html><body><h1>CarTrade</h1><script>const s = "</body>";</script></body></html>'
    module = '(function(){window.CT_FINANCE_PREVIEW_INSTALLED = true;})();'
    integrated = integrate(original, module)
    assert integrated.count(MARKER) == 1
    assert integrated.startswith(original[:original.lower().rfind('</body>')])
    assert integrated.endswith('</body></html>')
    assert module in integrated


def test_finance_preview_double_injection_fails_closed():
    html = '<html><body></body></html>'
    result = integrate(html, 'console.log("preview")')
    with pytest.raises(ValueError):
        integrate(result, 'console.log("duplicate")')


def test_finance_module_static_safe_contract():
    module = Path('assets/cartrade_finance_handoff_preview.js').read_text()
    assert 'ct-finance-consent' in module
    assert 'CT_FINANCE_CONTEXT' in module
    assert 'financing_status' in module
    assert 'not_started' in module
    assert 'Ninguna solicitud bancaria ha sido enviada' in module
    assert 'CT_FINANCE_RESOLVED' in module
    assert 'innerHTML' not in module
    assert '</script>' not in module.lower()


def test_buyer_gate_requires_explicit_receipt_and_removes_silent_capture():
    original = '<html><body><script>var TRACKED = [\'req-wa-input\', \'fb-wa\', \'ss-phone-input\'];</script></body></html>'
    output = integrate_lead_capture(original, '(function(){window.CT_BUYER_INTENT_GATE_INSTALLED=true})()')
    assert LEAD_GATE_MARKER in output
    assert "'req-wa-input', 'fb-wa'" not in output
    assert "var TRACKED = ['fb-wa', 'ss-phone-input'];" in output
    assert output.index('<script id="ct-buyer-intent-gate-script">') < output.index('</body>')
    assert output.endswith('</body></html>')


def test_buyer_gate_fails_without_known_legacy_capture():
    with pytest.raises(ValueError):
        integrate_lead_capture('<html><body></body></html>', 'console.log("gate")')
