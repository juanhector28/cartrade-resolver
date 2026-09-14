from __future__ import annotations

import subprocess
import sys
import textwrap


def test_v59_imports_against_real_stack_and_patches_active_retrieval():
    code = textwrap.dedent(
        r'''
        from app import main_v51
        from app import carly_v59_demo_truth as v59
        assert v59._unknown_make_token("Busco un Bugatti Chiron 2025") == "Bugatti"
        assert v59._unknown_make_token("Busco un Toyota SUV") is None
        assert v59.v52._price_range("SUV confiable entre USD 15,000 y 25,000") == (15000.0, 25000.0)
        body = {"country":"gt","messages":[{"role":"user","content":"Busco un SUV confiable entre USD 15,000 y 25,000 para trabajo diario"}]}
        c = v59._constraints_with_floor(body)
        assert c.get("price_min") == 15000.0, c
        assert c.get("total_budget") == 25000.0, c
        assert getattr(v59.v50.v46._ORIG_QUERY_ROWS, "__name__", "") == "_rows_with_range_v46"
        rows = [{"price_usd":12000},{"price_usd":16000},{"price_usd":25000},{"price_usd":26000},{"price_usd":None}]
        kept = v59._filter_price_range(rows, c)
        assert [r["price_usd"] for r in kept] == [16000,25000], kept
        '''
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
