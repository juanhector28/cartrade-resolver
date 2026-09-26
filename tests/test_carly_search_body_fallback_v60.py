from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_v60_patch_removes_sql_body_filter_and_adds_model_fallback(tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    src = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    (app_dir / "main.py").write_text(src, encoding="utf-8")

    patch = (ROOT / "resolver_patch_carly_v60_body_fallback.py").read_text(encoding="utf-8")
    patch = patch.replace('Path("/app/app/main.py")', 'Path("app/main.py")')
    patch_path = tmp_path / "patch.py"
    patch_path.write_text(patch, encoding="utf-8")

    subprocess.run([sys.executable, str(patch_path)], cwd=tmp_path, check=True)
    out = (app_dir / "main.py").read_text(encoding="utf-8")

    assert 'q = q.in_("body_type", it.body_types)' not in out
    assert 'classify_body_type(car.get("model"), None)' in out
    assert "CARLY_SEARCH_BODY_FALLBACK_V60" in out
