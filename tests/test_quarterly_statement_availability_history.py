import json
import importlib
from datetime import date
from pathlib import Path


def _history_module():
    try:
        return importlib.import_module("data_module.quarterly_statement_availability_history")
    except ModuleNotFoundError:
        return None


def _evidence(**overrides: str) -> dict[str, str]:
    row = {
        "stock_code": "2330",
        "statement_type": "income_statement",
        "statement_scope": "consolidated",
        "period": "2024-Q1",
        "period_end": "2024-03-31",
        "announcement_date": "2024-05-10",
        "available_date": "2024-05-10",
        "source_id": "mops.statement.publication",
        "source_version": "mops-v1",
        "source_hash": "a" * 64,
        "content_hash": "b" * 64,
        "evidence_tier": "official",
        "revision": "1",
    }
    row.update(overrides)
    return row


def test_period_end_or_deadline_does_not_become_availability() -> None:
    history = _history_module()
    assert history is not None, "quarterly statement history contract is missing"
    result = history.build_quarterly_statement_availability_history(
        statement_keys={("2330", "income_statement", "consolidated", "2024-Q1", date(2024, 3, 31))},
        evidence_rows=(
            _evidence(
                announcement_date="",
                available_date="",
                filing_deadline="2024-05-15",
            ),
        ),
        feature_cutoff=date(2024, 6, 1),
    )

    assert result.records == ()
    assert result.unmatched_reasons == {
        ("2330", "income_statement", "consolidated", "2024-Q1"): "missing_publication_or_first_observed"
    }
    assert result.coverage.unmatched == 1


def test_statement_scope_and_revision_chain_do_not_cross_match() -> None:
    history = _history_module()
    assert history is not None, "quarterly statement history contract is missing"
    result = history.build_quarterly_statement_availability_history(
        statement_keys={
            ("2330", "income_statement", "consolidated", "2024-Q1", date(2024, 3, 31)),
            ("2330", "income_statement", "individual", "2024-Q1", date(2024, 3, 31)),
        },
        evidence_rows=(
            _evidence(),
            _evidence(
                source_version="mops-v2",
                available_date="2024-05-20",
                content_hash="c" * 64,
                revision="2",
                parent_revision="1",
            ),
        ),
        feature_cutoff=date(2024, 5, 15),
    )

    assert [record.revision for record in result.records] == [1, 2]
    assert result.coverage.total == 3
    assert result.coverage.revision == 1
    assert result.coverage.future_blocked == 1
    assert result.unmatched_reasons[
        ("2330", "income_statement", "individual", "2024-Q1")
    ] == "no_matching_statement_evidence"


def test_writer_uses_only_explicit_staging_root(tmp_path: Path) -> None:
    history = _history_module()
    assert history is not None, "quarterly statement history contract is missing"
    result = history.build_quarterly_statement_availability_history(
        statement_keys={("2330", "income_statement", "consolidated", "2024-Q1", date(2024, 3, 31))},
        evidence_rows=(_evidence(),),
        feature_cutoff=date(2024, 6, 1),
    )

    outputs = history.write_quarterly_statement_availability_history(
        result,
        output_root=tmp_path,
    )

    assert set(outputs) == {"mapping", "coverage", "manifest"}
    assert all(path.parent == tmp_path.resolve() for path in outputs.values())
    assert all(path.exists() for path in outputs.values())


def test_cli_requires_and_writes_explicit_staging_root(tmp_path: Path) -> None:
    cli = importlib.import_module("scripts.build_quarterly_statement_availability_history")
    keys_path = tmp_path / "keys.json"
    evidence_path = tmp_path / "evidence.json"
    output_root = tmp_path / "staging"
    keys_path.write_text(
        json.dumps(
            [
                {
                    "stock_code": "2330",
                    "statement_type": "income_statement",
                    "statement_scope": "consolidated",
                    "period": "2024-Q1",
                    "period_end": "2024-03-31",
                }
            ]
        ),
        encoding="utf-8",
    )
    evidence_path.write_text(json.dumps([_evidence()]), encoding="utf-8")

    exit_code = cli.main(
        [
            "--statement-keys-json",
            str(keys_path),
            "--evidence-json",
            str(evidence_path),
            "--feature-cutoff",
            "2024-06-01",
            "--output-root",
            str(output_root),
        ]
    )

    assert exit_code == 0
    assert sorted(path.name for path in output_root.iterdir()) == [
        "quarterly_statement_availability_coverage.json",
        "quarterly_statement_availability_manifest.json",
        "quarterly_statement_availability_mapping.csv",
    ]
