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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--module", default="assets/cartrade_finance_handoff_preview.js", type=Path)
    args = parser.parse_args()
    html = args.html.read_text(encoding="utf-8")
    module = args.module.read_text(encoding="utf-8")
    args.out.write_text(integrate(html, module), encoding="utf-8")
    print(f"Created {args.out} ({args.out.stat().st_size} bytes), no deployment performed")


if __name__ == "__main__":
    main()
