"""Build the self-contained CarTrade link-first Netlify preview.

Usage: python scripts/build_link_first_netlify.py --out /tmp/cartrade-link-first
Output is a static preview ONLY, with demo mode hardcoded and no real API key.
Drag-and-drop the generated directory or its ZIP into a NEW Netlify preview
site. Do not overwrite cartrade.live with this proof of concept.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "previews" / "link-first" / "index.html"
SCRIPT = ROOT / "assets" / "cartrade_link_first_request.js"

README = """# CarTrade | Pega el enlace
Netlify-only preview: no live lead intake, no banking calls, no scraper dependency.

## Run locally
Serve this folder over localhost, for example:
python -m http.server 8000
Then open http://localhost:8000/ .

## Netlify
Drag the folder contents (index.html and cartrade_link_first_request.js)
into a NEW Netlify preview site. Do not replace production cartrade.live.

## Functional behavior
The buyer pastes a PUBLIC HTTPS link, enters WhatsApp and explicitly consents.
The preview displays "Vista previa completada"; it DOES NOT transmit contact
data, persist requests, or claim to have contacted a seller.

To activate real requests later: independently review privacy/retention,
deploy the feature-gated API with per-IP challenge protections, bind the
verified API endpoint, remove the DEMO flag, and test consent + receipt on
a restricted environment before a separate explicit release approval.
"""


def build(out: Path):
    html = HTML.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")
    assert "<script>window.CT_LINK_FIRST_DEMO = true" in html, "Preview must be demo-only"
    assert "window.CT_LINK_FIRST_DEMO === true" in script, "Frontend demo must never call the API"
    assert "id=\"heroInput\"" in html and "id=\"lp9\"" in html
    assert "ct-link-first-start" in script and "/buyer-intents" in script
    if "</script>" in script.lower():
        raise ValueError("Unexpected JS script terminator")
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / SCRIPT.name).write_text(script, encoding="utf-8")
    (out / "README.txt").write_text(README, encoding="utf-8")
    print(f"Built demo-only Netlify preview: {out}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    build(args.out)


if __name__ == "__main__":
    main()
