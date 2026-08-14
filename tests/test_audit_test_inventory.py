from pathlib import Path
import scripts.audit_test_inventory as audit_test_inventory
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


def test_read_documented_current_counts_accepts_a_new_machine_refresh_date(
    tmp_path: Path, monkeypatch
) -> None:
    documentation = (
        tmp_path
        / "docs"
        / "06_qa"
        / "TEST_INVENTORY_HEALTHCHECK_CLASSIFICATION_2026_06_23.md"
    )
    documentation.parent.mkdir(parents=True)
    documentation.write_text(
        "\n".join(
            (
                "# Test inventory",
                "",
                "## 2030-01-02 machine refresh",
                "",
                "Current filesystem Python files: `9`",
                "",
                "| 分類 | 數量 |",
                "|---|---:|",
                "| `service-oracle-data-market` | 9 |",
                "",
                "## Historical section",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(audit_test_inventory, "PROJECT_ROOT", tmp_path)

    assert audit_test_inventory._read_documented_current_counts() == {
        "total": 9,
        "service-oracle-data-market": 9,
    }
