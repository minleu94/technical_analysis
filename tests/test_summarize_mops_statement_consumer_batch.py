from datetime import date
import json
from pathlib import Path

import pytest

from data_module.mops_statement_candidate_adapter import materialize_mops_statement_candidates
from scripts import build_mops_statement_batch as batch
from scripts import summarize_mops_statement_consumer_batch as summary


def _candidate_row() -> dict[str, object]:
    return {
        "stock_code": "2330",
        "market": "sii",
        "statement_type": "income_statement",
        "statement_scope": "consolidated",
        "period": "2026-Q2",
        "period_start": "2026-04-01",
        "period_end": "2026-06-30",
        "period_basis": "quarter_single",
        "item_name": "基本每股盈餘",
        "item_code": "9750",
        "item_code_source": "mops.t164sb01.xbrl.row_code",
        "official_item_name": "基本每股盈餘合計",
        "xbrl_concept": "ifrs-full:EarningsPerShareBasic",
        "item_indent": 2,
        "official_indent_depth": 2,
        "value": 2725,
        "value_unit": "TWD_per_share",
        "value_scale": 100,
        "raw_value": "27.25",
        "announcement_event_timestamp": "2026-08-14T13:59:44+08:00",
        "numeric_available_at": "2026-09-07T08:58:27.223577+00:00",
        "numeric_available_date": "2026-09-08",
        "available_date": "2026-09-08",
        "content_hash": "a" * 64,
        "numeric_source_row_sha256": "sha256:" + "b" * 64,
        "availability_event_sha256": "sha256:" + "c" * 64,
        "item_code_lineage_sha256": "sha256:" + "d" * 64,
    }


def _make_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    child_dir = tmp_path / "child-2330"
    child_dir.mkdir()
    candidate = child_dir / "statement-pit-candidate.json"
    candidate.write_text(
        json.dumps(
            {
                "schema_version": "mops-statement-pit-candidate.v1",
                "source_id": "mops.statement.publication",
                "source_version": "mops-test-source.v1",
                "report_basis": "consolidated",
                "research_only": True,
                "formal_oos_allowed": False,
                "rows": [_candidate_row()],
                "pit_coverage_summary": {
                    "stock_code": "2330",
                    "market_request": "sii",
                    "period": "2026-Q2",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    child_manifest = child_dir / "run-manifest.json"
    child_manifest.write_text(
        json.dumps(
            {
                "schema_version": "mops-statement-pit-run-manifest.v1",
                "run_id": child_dir.name,
                "files": {"candidate": batch._file_sha256_reference(candidate)},
                "research_only": True,
                "formal_oos_allowed": False,
            }
        ),
        encoding="utf-8",
    )
    batch_manifest = tmp_path / "batch-manifest.json"
    batch_manifest.write_text(
        json.dumps(
            {
                "schema_version": "mops-statement-pit-batch-manifest.v2",
                "request_count": 1,
                "status": "completed",
                "succeeded_count": 1,
                "failed_count": 0,
                "pending_count": 0,
                "research_only": True,
                "formal_oos_allowed": False,
                "child_runs": [
                    {
                        "stock_code": "2330",
                        "market": "sii",
                        "period": "2026-Q2",
                        "run_id": child_dir.name,
                        "candidate": str(candidate),
                        "manifest": str(child_manifest),
                        "status": "succeeded",
                        "candidate_sha256": batch._file_sha256_reference(candidate),
                        "manifest_sha256": batch._file_sha256_reference(child_manifest),
                        "report_basis": "consolidated",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "consumer.db"
    first = materialize_mops_statement_candidates(
        [candidate],
        db_path,
        decision_dates=[date(2026, 9, 7), date(2026, 9, 8)],
    )
    retry = materialize_mops_statement_candidates(
        [candidate],
        db_path,
        decision_dates=[date(2026, 9, 7), date(2026, 9, 8)],
    )
    first_path = tmp_path / "materialization-first.json"
    retry_path = tmp_path / "materialization-retry.json"
    first_path.write_text(json.dumps(first), encoding="utf-8")
    retry_path.write_text(json.dumps(retry), encoding="utf-8")
    return batch_manifest, child_manifest, first_path, retry_path, candidate


def _summary_args(
    tmp_path: Path,
    fixture: tuple[Path, Path, Path, Path, Path],
    output_name: str,
) -> list[str]:
    batch_manifest, child_manifest, first, retry, _ = fixture
    return [
        "--period",
        "2026-Q2",
        "--batch-manifest",
        str(batch_manifest),
        "--child-manifest",
        str(child_manifest),
        "--materialization-first",
        str(first),
        "--materialization-retry",
        str(retry),
        "--output",
        str(tmp_path / output_name),
    ]


def test_summary_binds_child_hashes_db_cutoff_and_idempotent_retry(tmp_path) -> None:
    fixture = _make_fixture(tmp_path)
    assert summary.main(_summary_args(tmp_path, fixture, "summary.json")) == 0
    payload = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert payload["coverage"] == {
        "completed_company_count": 1,
        "candidate_row_count": 1,
        "materialized_main_count": 1,
        "materialized_sidecar_count": 1,
        "eligible_company_count": None,
        "remaining_selectable_company_count": None,
        "scope_statement": "completed children are a bounded research slice; remaining universe is not restored",
    }
    assert payload["consumer"]["cutoff"]["hidden_visible_row_counts"] == {
        "2026-09-07": 0,
        "2026-09-08": 1,
    }
    assert payload["consumer"]["first_materialization"]["inserted_row_count"] == 1
    assert payload["consumer"]["retry_materialization"]["idempotent_existing_row_count"] == 1
    assert payload["consumer"]["database"]["quick_check"] == "ok"
    assert payload["consumer"]["eps_rows"][0]["value"] == "27.25"


def test_summary_rejects_retry_that_claims_an_insert(tmp_path) -> None:
    fixture = _make_fixture(tmp_path)
    retry_path = fixture[3]
    retry = json.loads(retry_path.read_text(encoding="utf-8"))
    retry["inserted_row_count"] = 1
    retry_path.write_text(json.dumps(retry), encoding="utf-8")
    with pytest.raises(ValueError, match="retry materialization receipt"):
        summary.main(_summary_args(tmp_path, fixture, "summary-rejected.json"))


def test_summary_refuses_to_overwrite_a_candidate_input(tmp_path) -> None:
    fixture = _make_fixture(tmp_path)
    args = _summary_args(tmp_path, fixture, "summary-rejected.json")
    args[-1] = str(fixture[4])
    with pytest.raises(ValueError, match="must not overlap"):
        summary.main(args)


def test_summary_applies_immutable_supersession_before_deduplication(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)
    old_batch, old_child, _, _, old_candidate = fixture
    new_root = tmp_path / "replacement"
    new_root.mkdir()
    new_child = new_root / "child-2330-replacement"
    new_child.mkdir()
    new_candidate = new_child / "statement-pit-candidate.json"
    payload = json.loads(old_candidate.read_text(encoding="utf-8"))
    payload["source_version"] = "mops-test-source-v2"
    new_candidate.write_text(json.dumps(payload), encoding="utf-8")
    new_manifest = new_child / "run-manifest.json"
    new_manifest.write_text(
        json.dumps(
            {
                "schema_version": "mops-statement-pit-run-manifest.v1",
                "run_id": new_child.name,
                "files": {"candidate": batch._file_sha256_reference(new_candidate)},
                "research_only": True,
                "formal_oos_allowed": False,
            }
        ),
        encoding="utf-8",
    )
    correction = tmp_path / "supersession.json"
    correction.write_text(
        json.dumps(
            {
                "schema_version": "mops-statement-artifact-correction.v1",
                "research_only": True,
                "formal_oos_allowed": False,
                "status": "accepted_replacement",
                "target": {
                    "stock_code": "2330",
                    "registry_market": "twse",
                    "batch_market": "sii",
                    "period": "2026-Q2",
                    "report_basis": "consolidated",
                },
                "superseded": {
                    "candidate_path": str(old_candidate),
                    "candidate_sha256": batch._file_sha256_reference(old_candidate),
                    "manifest_path": str(old_child),
                    "manifest_sha256": batch._file_sha256_reference(old_child),
                },
                "replacement": {
                    "candidate_path": str(new_candidate),
                    "candidate_sha256": batch._file_sha256_reference(new_candidate),
                    "manifest_path": str(new_manifest),
                    "manifest_sha256": batch._file_sha256_reference(new_manifest),
                },
                "reason": "strict replacement fixture",
            }
        ),
        encoding="utf-8",
    )

    old_details = summary._validate_child_manifest(
        old_child,
        expected_period="2026-Q2",
    )
    corrected, corrections = summary._apply_supersession_records(
        [old_details],
        [correction],
        expected_period="2026-Q2",
    )
    assert len(corrected) == 1
    assert corrected[0]["candidate_path"] == str(new_candidate.resolve())
    assert corrected[0]["candidate_sha256"] == batch._file_sha256_reference(new_candidate)
    assert corrections[0]["supersedes_candidate_sha256"] == batch._file_sha256_reference(old_candidate)
