"""Build a self-contained Netlify preview from an existing CarTrade HTML file.

Usage: python scripts/build_cartrade_netlify_preview.py --html original.html --out index.html
No deploy or backend modification occurs.
"""
from __future__ import annotations

import argparse
from pathlib import Path

MARKER = 'id="ct-finance-handoff-preview"'


def integrate(html: str, module: str) -> str:
    if MARKER in html:
        raise ValueError("Financing preview already included")
    if "</script>" in module.lower():
        raise ValueError("Unsafe closing script sequence in module")
    closing = html.lower().rfind("</body>")
    if closing == -1:
        raise ValueError("Cannot find document body closing tag")
    addition = (
        '\n<!-- Local-only financing preview. No lender submission. -->\n'
        '<script ' + MARKER + '>\n' + module + '\n</script>\n'
    )
    return html[:closing] + addition + html[closing:]


LEGACY_AUTO_CAPTURE = "var TRACKED = ['req-wa-input', 'fb-wa', 'ss-phone-input'];"
LEAD_GATE_MARKER = 'id="ct-buyer-intent-gate-script"'


def integrate_lead_capture(html: str, module: str) -> str:
    """Remove silent /deals capture and gate confirmation on an actual receipt."""
    if LEAD_GATE_MARKER in html:
        raise ValueError("Buyer intent gate already included")
    if html.count(LEGACY_AUTO_CAPTURE) != 1:
        raise ValueError("Expected exactly one legacy auto-capture registration")
    if "</script>" in module.lower():
        raise ValueError("Unsafe closing script sequence in buyer intent module")
    html = html.replace(LEGACY_AUTO_CAPTURE, "var TRACKED = ['fb-wa', 'ss-phone-input'];")
    html = html.replace("Pedido enviado.", "Solicitud registrada.")
    html = html.replace("Estamos contactando al vendedor de ", "Registramos tu solicitud por ")
    html = html.replace("El vendedor recibe tu invitación por WhatsApp.", "CarTrade recibió tu solicitud y verificará disponibilidad.")
    html = html.replace("Le escribimos al vendedor por WhatsApp. Tú no haces nada.", "Registramos tu interés y te contactaremos cuando haya novedades.")
    html = html.replace("Te avisamos por aquí cuando el vendedor responda.", "Podemos informarte por este medio si nos autorizas.")
    closing = html.lower().rfind("</body>")
    if closing < 0:
        raise ValueError("Cannot find document body closing tag")
    snippet = '\n<!-- Opt-in buyer request; no false confirmation on API failure. -->\n'
    snippet += '<script ' + LEAD_GATE_MARKER + '>\n' + module + '\n</script>\n'
    return html[:closing] + snippet + html[closing:]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--module", default="assets/cartrade_finance_handoff_preview.js", type=Path)
    parser.add_argument("--buyer-module", default="assets/cartrade_buyer_intent_submit.js", type=Path)
    args = parser.parse_args()
    html = args.html.read_text(encoding="utf-8")
    module = args.module.read_text(encoding="utf-8")
    buyer_module = args.buyer_module.read_text(encoding="utf-8")
    args.out.write_text(integrate_lead_capture(integrate(html, module), buyer_module), encoding="utf-8")
    print(f"Created {args.out} ({args.out.stat().st_size} bytes), no deployment performed")


if __name__ == "__main__":
    main()
