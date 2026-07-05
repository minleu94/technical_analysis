import importlib.util
import io
import sys
from pathlib import Path


def test_batch_update_import_does_not_replace_process_streams(monkeypatch):
    stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    stderr = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    script_path = Path("scripts/batch_update_market_and_industry_index.py")
    spec = importlib.util.spec_from_file_location(
        "batch_update_market_and_industry_index_import_test",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    spec.loader.exec_module(module)

    assert sys.stdout is stdout
    assert sys.stderr is stderr
