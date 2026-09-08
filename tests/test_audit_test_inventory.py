from pathlib import Path
import scripts.audit_test_inventory as audit_test_inventory
from scripts.audit_test_inventory import (
    FORMAL_ENTRY_REFERENCES,
    _find_duplicate_current_sections,
    _find_formal_entry_reference_errors,
    _find_markdown_link_errors,
    main,
    run_test_inventory_audit,
)


def test_audit_test_inventory_passes_and_reports_zero_missing() -> None:
    report = run_test_inventory_audit()
    assert report["missing_inventory_paths"] == []
    assert report["stale_inventory_paths"] == []
    assert report["overall_status"] == "passed"
    assert report["documentation_count_drift"] == {}
    assert report["collection_errors"] == []
    assert report["exact_duplicate_test_groups"]
    assert report["markdown_link_errors"] == []
    assert report["duplicate_current_sections"] == []
    assert report["formal_entry_reference_errors"] == []


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


def test_governance_markdown_checks_cover_positive_and_negative_fixtures(tmp_path: Path):
    root = tmp_path
    source = root / "docs" / "index.md"
    target = root / "docs" / "target.md"
    source.parent.mkdir(parents=True)
    target.write_text("# target\n", encoding="utf-8")
    source.write_text(
        "[target](target.md) [external](https://example.com)\n",
        encoding="utf-8",
    )

    assert _find_markdown_link_errors([source], project_root=root) == ([], [])

    source.write_text("[missing](missing.md)\n", encoding="utf-8")
    errors, warnings = _find_markdown_link_errors([source], project_root=root)
    assert errors == ["docs/index.md:missing_local_link:missing.md"]
    assert warnings == []


def test_governance_current_section_and_formal_entry_checks_have_negative_fixtures(
    tmp_path: Path,
):
    source = tmp_path / "governance.md"
    source.write_text(
        "## Current status\n\n## Current status\n",
        encoding="utf-8",
    )
    assert _find_duplicate_current_sections([source], project_root=tmp_path)

    index = tmp_path / "DOCUMENTATION_INDEX.md"
    index.write_text(FORMAL_ENTRY_REFERENCES[0] + "\n", encoding="utf-8")
    missing = _find_formal_entry_reference_errors(index, project_root=tmp_path)
    assert len(missing) == len(FORMAL_ENTRY_REFERENCES) - 1
