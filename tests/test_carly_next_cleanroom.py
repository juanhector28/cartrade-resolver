from pathlib import Path

def test_no_versioned_main_imports():
    root = Path(__file__).parents[1] / "app" / "carly_next"
    for path in root.glob("*.py"):
        assert "main_v" not in path.read_text()
