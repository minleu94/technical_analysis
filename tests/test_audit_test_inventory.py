from pathlib import Path
from scripts.audit_test_inventory import run_test_inventory_audit, main


def test_audit_test_inventory_passes_and_reports_zero_missing() -> None:
    report = run_test_inventory_audit()
    assert report["missing_inventory_paths"] == []
    assert report["stale_inventory_paths"] == []
    assert report["overall_status"] == "passed"
    assert report["documentation_count_drift"] == {}
    assert report["collection_errors"] == []
    assert report["exact_duplicate_test_groups"]


def test_audit_test_inventory_cli(tmp_path: Path) -> None:
    outfile = tmp_path / "audit.json"
    code = main(["--output-json", str(outfile), "--skip-pytest-collection"])
    assert code == 0
    assert outfile.exists()
