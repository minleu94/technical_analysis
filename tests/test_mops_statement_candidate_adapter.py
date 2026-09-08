from datetime import date
from decimal import Decimal
import hashlib
import json
import sqlite3

import pytest

from data_module.mops_statement_candidate_adapter import (
    load_mops_statement_candidate,
    materialize_mops_statement_candidates,
)
from data_module.fundamental_sqlite_provider import FundamentalSQLiteProvider
from scripts.materialize_mops_statement_candidates import main as materialize_cli


def _row(
    *,
    statement_type: str,
    item_name: str,
    value: int,
    value_unit: str,
    value_scale: int,
    period_start: str | None,
    period_basis: str,
    item_code: str | None = None,
) -> dict[str, object]:
    resolved_code = item_code or {
        "基本每股盈餘": "9750",
        "營業收入合計": "4000",
        "現金及約當現金": "1100",
        "繼續營業單位稅前淨利（淨損）": "A00010",
    }.get(item_name, "1100")
    official_item_name = {
        "基本每股盈餘": "基本每股盈餘合計",
    }.get(item_name, item_name)
    return {
        "stock_code": "2330",
        "market": "sii",
        "statement_type": statement_type,
        "statement_scope": "consolidated",
        "period": "2026-Q2",
        "period_start": period_start,
        "period_end": "2026-06-30",
        "period_basis": period_basis,
        "item_name": item_name,
        "item_code": resolved_code,
        "item_code_source": "mops.t164sb01.xbrl.row_code",
        "official_item_name": official_item_name,
        "xbrl_concept": "ifrs-full:TestConcept",
        "item_indent": 2,
        "official_indent_depth": 2,
        "value": value,
        "value_unit": value_unit,
        "value_scale": value_scale,
        "raw_value": "27.25" if value_unit == "TWD_per_share" else "1,270,380,250",
        "announcement_event_timestamp": "2026-08-14T13:59:44+08:00",
        "numeric_available_at": "2026-09-07T08:58:27.223577+00:00",
        "numeric_available_date": "2026-09-08",
        "available_date": "2026-09-08",
        "content_hash": "a" * 64,
        "numeric_source_row_sha256": "sha256:" + "b" * 64,
        "availability_event_sha256": "sha256:" + "c" * 64,
        "item_code_lineage_sha256": "sha256:" + "d" * 64,
    }


def _write_candidate(tmp_path, rows: list[dict[str, object]]):
    path = tmp_path / "statement-pit-candidate.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "mops-statement-pit-candidate.v1",
                "source_id": "mops.statement.publication",
                "source_version": "mops-t164-consolidated-statements-with-t57sb01-publication.v1",
                "research_only": True,
                "formal_oos_allowed": False,
                "rows": rows,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _write_batch_manifest(
    tmp_path,
    *,
    period: str = "2026-Q2",
    source_version: str = "mops-t164-consolidated-statements-with-t57sb01-publication.v1",
    child_manifest_run_id: str = "fixture-child",
    include_failed: bool = False,
):
    child_dir = tmp_path / "child"
    child_dir.mkdir()
    candidate = _write_candidate(
        child_dir,
        [
            _row(
                statement_type="income_statement",
                item_name="基本每股盈餘",
                value=2725,
                value_unit="TWD_per_share",
                value_scale=100,
                period_start="2026-04-01",
                period_basis="quarter_single",
            )
        ],
    )
    candidate_payload = json.loads(candidate.read_text(encoding="utf-8"))
    candidate_payload["source_version"] = source_version
    candidate_payload["pit_coverage_summary"] = {
        "stock_code": "2330",
        "market_request": "sii",
        "period": period,
    }
    candidate_payload["rows"][0]["period"] = period
    candidate.write_text(
        json.dumps(candidate_payload, ensure_ascii=False),
        encoding="utf-8",
    )
    candidate_hash = "sha256:" + hashlib.sha256(candidate.read_bytes()).hexdigest()
    child_manifest = child_dir / "run-manifest.json"
    child_manifest.write_text(
        json.dumps(
            {
                "schema_version": "mops-statement-pit-run-manifest.v2",
                "run_id": child_manifest_run_id,
                "research_only": True,
                "formal_oos_allowed": False,
                "files": {"candidate": candidate_hash},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manifest_hash = "sha256:" + hashlib.sha256(child_manifest.read_bytes()).hexdigest()
    batch_manifest = tmp_path / "batch-manifest.json"
    child_runs = [
        {
            "stock_code": "2330",
            "market": "sii",
            "period": period,
            "run_id": "fixture-child",
            "candidate": str(candidate),
            "manifest": str(child_manifest),
            "status": "succeeded",
            "candidate_sha256": candidate_hash,
            "manifest_sha256": manifest_hash,
            "report_basis": "consolidated",
        }
    ]
    if include_failed:
        child_runs.append(
            {
                "stock_code": "6488",
                "market": "sii",
                "period": period,
                "run_id": "fixture-failed",
                "status": "failed",
                "attempts": [
                    {
                        "attempt": 1,
                        "status": "failed",
                        "error_type": "ValueError",
                        "error": "fixture failure",
                        "failure_source": "fixture.source",
                    }
                ],
            }
        )
    batch_manifest.write_text(
        json.dumps(
            {
                "schema_version": "mops-statement-pit-batch-manifest.v2",
                "research_only": True,
                "formal_oos_allowed": False,
                "request_count": len(child_runs),
                "status": "partial" if include_failed else "completed",
                "succeeded_count": 1,
                "failed_count": 1 if include_failed else 0,
                "pending_count": 0,
                "child_runs": child_runs,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return batch_manifest, candidate, child_manifest


def test_adapter_converts_eps_and_preserves_period_semantics(tmp_path) -> None:
    path = _write_candidate(
        tmp_path,
        [
            _row(
                statement_type="income_statement",
                item_name="基本每股盈餘",
                value=2725,
                value_unit="TWD_per_share",
                value_scale=100,
                period_start="2026-04-01",
                period_basis="quarter_single",
            ),
            _row(
                statement_type="balance_sheet",
                item_name="現金及約當現金",
                value=3_134_218_213_000,
                value_unit="TWD",
                value_scale=1000,
                period_start=None,
                period_basis="period_end_snapshot",
            ),
            _row(
                statement_type="cash_flows_statement",
                item_name="繼續營業單位稅前淨利（淨損）",
                value=1_550_229_773_000,
                value_unit="TWD",
                value_scale=1000,
                period_start="2026-01-01",
                period_basis="year_to_date",
            ),
        ],
    )

    rows = load_mops_statement_candidate(path)
    eps = next(row for row in rows if row.item_name == "基本每股盈餘")
    amount = next(row for row in rows if row.item_name == "現金及約當現金")
    cash = next(row for row in rows if row.statement_type == "cash_flows_statement")
    assert eps.value == Decimal("27.25")
    assert eps.raw_integer_value == 2725
    assert eps.value_unit == "TWD_per_share"
    assert eps.value_scale == 100
    assert eps.period_start == date(2026, 4, 1)
    assert eps.period_basis == "quarter_single"
    assert amount.value == Decimal("3134218213000")
    assert amount.value_unit == "TWD"
    assert cash.period_start == date(2026, 1, 1)
    assert cash.period_basis == "year_to_date"


def test_adapter_materializes_individual_basis_and_provider_preserves_scope(tmp_path) -> None:
    path = _write_candidate(
        tmp_path,
        [
            _row(
                statement_type="income_statement",
                item_name="基本每股盈餘",
                value=2725,
                value_unit="TWD_per_share",
                value_scale=100,
                period_start="2026-04-01",
                period_basis="quarter_single",
            )
        ],
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["report_basis"] = "individual"
    payload["statement_scope"] = "individual"
    payload["source_version"] = "mops-t164-individual-test.v1"
    payload["rows"][0]["report_basis"] = "individual"
    payload["rows"][0]["statement_scope"] = "individual"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    rows = load_mops_statement_candidate(path)
    assert rows[0].report_basis == "individual"
    report = materialize_mops_statement_candidates(
        [path],
        tmp_path / "individual.db",
        decision_dates=[date(2026, 9, 8)],
    )
    assert report["inserted_row_count"] == 1
    provider = FundamentalSQLiteProvider(tmp_path / "individual.db")
    loaded = provider.load_statement_items(
        stock_code="2330",
        decision_date=date(2026, 9, 8),
    )
    assert len(loaded) == 1
    assert loaded[0].value == Decimal("27.25")
    assert loaded[0].report_basis == "individual"


def test_adapter_date_only_cutoff_hides_capture_until_next_day(tmp_path) -> None:
    path = _write_candidate(
        tmp_path,
        [
            _row(
                statement_type="income_statement",
                item_name="營業收入合計",
                value=1_270_380_250_000,
                value_unit="TWD",
                value_scale=1000,
                period_start="2026-04-01",
                period_basis="quarter_single",
            )
        ],
    )

    assert load_mops_statement_candidate(path, decision_date=date(2026, 9, 7)) == ()
    visible = load_mops_statement_candidate(path, decision_date=date(2026, 9, 8))
    assert len(visible) == 1
    assert visible[0].numeric_available_at.isoformat() == "2026-09-07T08:58:27.223577+00:00"


def test_adapter_rejects_unit_scale_mismatch(tmp_path) -> None:
    path = _write_candidate(
        tmp_path,
        [
            _row(
                statement_type="income_statement",
                item_name="基本每股盈餘",
                value=27250,
                value_unit="TWD_per_share",
                value_scale=1000,
                period_start="2026-04-01",
                period_basis="quarter_single",
            )
        ],
    )

    with pytest.raises(ValueError, match="unit/scale mismatch"):
        load_mops_statement_candidate(path)


def test_adapter_rejects_saved_listing_without_verified_evidence(tmp_path) -> None:
    path = _write_candidate(
        tmp_path,
        [
            _row(
                statement_type="income_statement",
                item_name="營業收入合計",
                value=1_270_380_250_000,
                value_unit="TWD",
                value_scale=1000,
                period_start="2026-04-01",
                period_basis="quarter_single",
            )
        ],
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["lineage"] = {
        "availability_source": {
            "capture_mode": "previously_saved_official_response",
            "evidence_status": "unverified_saved_response",
        }
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="without verified evidence"):
        load_mops_statement_candidate(path)


def test_adapter_preserves_two_decimal_eps_scale(tmp_path) -> None:
    path = _write_candidate(
        tmp_path,
        [
            _row(
                statement_type="income_statement",
                item_name="基本每股盈餘",
                value=790,
                value_unit="TWD_per_share",
                value_scale=100,
                period_start="2026-04-01",
                period_basis="quarter_single",
            )
        ],
    )
    eps = load_mops_statement_candidate(path)[0]
    assert eps.value == Decimal("7.90")
    assert str(eps.value) == "7.90"


def test_adapter_rejects_same_day_date_only_availability(tmp_path) -> None:
    path = _write_candidate(
        tmp_path,
        [
            {
                **_row(
                    statement_type="income_statement",
                    item_name="營業收入合計",
                    value=1_270_380_250_000,
                    value_unit="TWD",
                    value_scale=1000,
                    period_start="2026-04-01",
                    period_basis="quarter_single",
                ),
                "numeric_available_date": "2026-09-07",
                "available_date": "2026-09-07",
            }
        ],
    )

    with pytest.raises(ValueError, match="next Taipei calendar date"):
        load_mops_statement_candidate(path)


def test_isolated_materialization_is_idempotent_and_provider_cutoff_safe(tmp_path) -> None:
    candidate = _write_candidate(
        tmp_path,
        [
            _row(
                statement_type="balance_sheet",
                item_name="現金及約當現金",
                value=3_134_218_213_000,
                value_unit="TWD",
                value_scale=1000,
                period_start=None,
                period_basis="period_end_snapshot",
                item_code="1100",
            ),
            _row(
                statement_type="income_statement",
                item_name="基本每股盈餘",
                value=2725,
                value_unit="TWD_per_share",
                value_scale=100,
                period_start="2026-04-01",
                period_basis="quarter_single",
                item_code="9750",
            ),
            _row(
                statement_type="cash_flows_statement",
                item_name="繼續營業單位稅前淨利（淨損）",
                value=1_550_229_773_000,
                value_unit="TWD",
                value_scale=1000,
                period_start="2026-01-01",
                period_basis="year_to_date",
                item_code="A00010",
            ),
        ],
    )
    db_path = tmp_path / "isolated.db"

    first = materialize_mops_statement_candidates(
        [candidate],
        db_path,
        decision_dates=[date(2026, 9, 7), date(2026, 9, 8)],
    )
    second = materialize_mops_statement_candidates(
        [candidate],
        db_path,
        decision_dates=[date(2026, 9, 7), date(2026, 9, 8)],
    )

    assert first["inserted_row_count"] == 3
    assert first["materialized_row_count"] == 3
    assert first["sidecar_row_count"] == 3
    assert first["provider_visible_rows_by_decision_date"] == {
        "2026-09-07": 0,
        "2026-09-08": 3,
    }
    assert second["inserted_row_count"] == 0
    assert second["idempotent_existing_row_count"] == 3
    assert second["materialized_row_count"] == 3
    assert (tmp_path / "isolated.db.research-only.json").is_file()

    from data_module.fundamental_sqlite_provider import FundamentalSQLiteProvider

    provider = FundamentalSQLiteProvider(db_path)
    records = provider.load_statement_items(
        stock_code="2330",
        decision_date=date(2026, 9, 8),
    )
    assert {record.item_code for record in records} == {"1100", "9750", "A00010"}
    assert next(record for record in records if record.item_code == "9750").value == Decimal("27.25")


def test_materializer_rejects_existing_unmarked_database(tmp_path) -> None:
    candidate = _write_candidate(
        tmp_path,
        [
            _row(
                statement_type="income_statement",
                item_name="基本每股盈餘",
                value=2725,
                value_unit="TWD_per_share",
                value_scale=100,
                period_start="2026-04-01",
                period_basis="quarter_single",
            )
        ],
    )
    db_path = tmp_path / "preexisting-unmarked.db"
    connection = sqlite3.connect(db_path)
    connection.close()

    with pytest.raises(ValueError, match="isolation marker"):
        materialize_mops_statement_candidates(
            [candidate],
            db_path,
            decision_dates=[date(2026, 9, 8)],
        )


def test_materializer_rejects_formal_data_root_and_symlink_alias(tmp_path, monkeypatch) -> None:
    formal_root = tmp_path / "formal-data"
    monkeypatch.setenv("DATA_ROOT", str(formal_root))
    monkeypatch.setenv("PROFILE", "prod")
    candidate = _write_candidate(
        tmp_path,
        [
            _row(
                statement_type="income_statement",
                item_name="基本每股盈餘",
                value=2725,
                value_unit="TWD_per_share",
                value_scale=100,
                period_start="2026-04-01",
                period_basis="quarter_single",
            )
        ],
    )
    formal_db = formal_root / "sqlite" / "twstock.db"
    with pytest.raises(ValueError, match="DATA_ROOT"):
        materialize_mops_statement_candidates(
            [candidate],
            formal_db,
            decision_dates=[date(2026, 9, 8)],
        )

    alias = tmp_path / "formal-alias.db"
    try:
        alias.symlink_to(formal_db)
    except (OSError, NotImplementedError):
        pytest.skip("此 Windows 環境不允許建立 symlink")
    with pytest.raises(ValueError, match="symlink|DATA_ROOT"):
        materialize_mops_statement_candidates(
            [candidate],
            alias,
            decision_dates=[date(2026, 9, 8)],
        )


def test_materializer_cli_writes_research_evidence(tmp_path) -> None:
    candidate = _write_candidate(
        tmp_path,
        [
            _row(
                statement_type="income_statement",
                item_name="基本每股盈餘",
                value=2725,
                value_unit="TWD_per_share",
                value_scale=100,
                period_start="2026-04-01",
                period_basis="quarter_single",
            )
        ],
    )
    db_path = tmp_path / "cli-isolated.db"
    evidence = tmp_path / "cli-evidence.json"
    assert materialize_cli(
        [
            "--candidate",
            str(candidate),
            "--db-path",
            str(db_path),
            "--decision-date",
            "2026-09-08",
            "--evidence-output",
            str(evidence),
        ]
    ) == 0
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["inserted_row_count"] == 1
    assert payload["provider_sample_values_by_stock"]["2330"][0]["value"] == "27.25"


def test_materializer_cli_collects_and_validates_succeeded_batch_children(tmp_path) -> None:
    batch_manifest, candidate, _child_manifest = _write_batch_manifest(
        tmp_path,
        include_failed=True,
    )
    db_path = tmp_path / "batch-cli-isolated.db"
    evidence = tmp_path / "batch-cli-evidence.json"

    assert materialize_cli(
        [
            "--batch-manifest",
            str(batch_manifest),
            "--period",
            "2026-Q2",
            "--db-path",
            str(db_path),
            "--decision-date",
            "2026-09-08",
            "--evidence-output",
            str(evidence),
        ]
    ) == 0
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["candidate_paths"] == [str(candidate.resolve())]
    assert payload["inserted_row_count"] == 1
    assert payload["provider_visible_rows_by_decision_date"]["2026-09-08"] == 1
    assert payload["batch_succeeded_child_count"] == 1
    assert payload["batch_incomplete_child_count"] == 1
    assert payload["batch_sources"][0]["batch_manifest_sha256"].startswith("sha256:")
    assert payload["batch_sources"][0]["observed_counts"] == {
        "succeeded": 1,
        "failed": 1,
        "integrity_error": 0,
        "pending": 0,
        "running": 0,
    }
    assert payload["batch_succeeded_scope"][0]["run_id"] == "fixture-child"
    assert payload["batch_incomplete_scope"][0]["run_id"] == "fixture-failed"
    assert payload["batch_incomplete_scope"][0]["error"] == "fixture failure"


def test_materializer_cli_rejects_child_manifest_run_id_mismatch_before_database_creation(
    tmp_path,
) -> None:
    batch_manifest, candidate, _child_manifest = _write_batch_manifest(
        tmp_path,
        child_manifest_run_id="different-child",
    )
    db_path = tmp_path / "run-id-mismatch-isolated.db"
    evidence = tmp_path / "run-id-mismatch-evidence.json"

    with pytest.raises(ValueError, match="run_id does not match child manifest"):
        materialize_cli(
            [
                "--batch-manifest",
                str(batch_manifest),
                "--period",
                "2026-Q2",
                "--db-path",
                str(db_path),
                "--decision-date",
                "2026-09-08",
                "--evidence-output",
                str(evidence),
            ]
        )
    assert not db_path.exists()
    assert not evidence.exists()
    assert candidate.is_file()


def test_materializer_cli_rejects_unknown_legacy_report_basis(tmp_path) -> None:
    batch_manifest, candidate, _child_manifest = _write_batch_manifest(
        tmp_path,
        source_version="mops-test-source-without-report-basis.v1",
    )
    payload = json.loads(batch_manifest.read_text(encoding="utf-8"))
    payload["child_runs"][0].pop("report_basis")
    batch_manifest.write_text(json.dumps(payload), encoding="utf-8")
    db_path = tmp_path / "unknown-basis-isolated.db"
    evidence = tmp_path / "unknown-basis-evidence.json"

    with pytest.raises(ValueError, match="report_basis is unknown"):
        materialize_cli(
            [
                "--batch-manifest",
                str(batch_manifest),
                "--period",
                "2026-Q2",
                "--db-path",
                str(db_path),
                "--decision-date",
                "2026-09-08",
                "--evidence-output",
                str(evidence),
            ]
        )
    assert not db_path.exists()
    assert not evidence.exists()
    assert candidate.is_file()


def test_materializer_cli_rejects_changed_batch_child_hash_before_database_creation(
    tmp_path,
) -> None:
    batch_manifest, candidate, _child_manifest = _write_batch_manifest(tmp_path)
    payload = json.loads(batch_manifest.read_text(encoding="utf-8"))
    payload["child_runs"][0]["candidate_sha256"] = "sha256:" + "0" * 64
    batch_manifest.write_text(json.dumps(payload), encoding="utf-8")
    db_path = tmp_path / "changed-batch-isolated.db"
    evidence = tmp_path / "changed-batch-evidence.json"

    with pytest.raises(ValueError, match="candidate_sha256 changed"):
        materialize_cli(
            [
                "--batch-manifest",
                str(batch_manifest),
                "--period",
                "2026-Q2",
                "--db-path",
                str(db_path),
                "--decision-date",
                "2026-09-08",
                "--evidence-output",
                str(evidence),
            ]
        )
    assert not db_path.exists()
    assert not evidence.exists()
    assert candidate.is_file()


def test_materializer_cli_rejects_evidence_database_overlap_before_materialize(tmp_path) -> None:
    candidate = _write_candidate(
        tmp_path,
        [
            _row(
                statement_type="income_statement",
                item_name="基本每股盈餘",
                value=2725,
                value_unit="TWD_per_share",
                value_scale=100,
                period_start="2026-04-01",
                period_basis="quarter_single",
            )
        ],
    )
    candidate_before = candidate.read_bytes()
    db_path = tmp_path / "overlap-isolated.db"
    with pytest.raises(ValueError, match="overlap"):
        materialize_cli(
            [
                "--candidate",
                str(candidate),
                "--db-path",
                str(db_path),
                "--decision-date",
                "2026-09-08",
                "--evidence-output",
                str(db_path),
            ]
        )
    assert not db_path.exists()
    assert candidate.read_bytes() == candidate_before


def test_materializer_cli_collects_legacy_direct_child_manifest(tmp_path) -> None:
    _batch_manifest, candidate, child_manifest = _write_batch_manifest(
        tmp_path,
        child_manifest_run_id="child",
    )
    db_path = tmp_path / "direct-child-isolated.db"
    evidence = tmp_path / "direct-child-evidence.json"

    assert materialize_cli(
        [
            "--child-manifest",
            str(child_manifest),
            "--period",
            "2026-Q2",
            "--db-path",
            str(db_path),
            "--decision-date",
            "2026-09-08",
            "--evidence-output",
            str(evidence),
        ]
    ) == 0
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["candidate_paths"] == [str(candidate.resolve())]
    assert payload["batch_succeeded_child_count"] == 1
    assert payload["direct_child_manifest_count"] == 1
    assert payload["supersession_replacement_count"] == 0
    assert payload["inserted_row_count"] == 1


def test_materializer_cli_direct_child_infers_only_known_legacy_basis(tmp_path) -> None:
    _batch_manifest, _candidate, child_manifest = _write_batch_manifest(
        tmp_path,
        child_manifest_run_id="child",
        source_version="mops-t164-consolidated-statements-with-t57sb01-xbrl-row-codes.v2",
    )
    db_path = tmp_path / "legacy-basis-isolated.db"
    evidence = tmp_path / "legacy-basis-evidence.json"

    assert materialize_cli(
        [
            "--child-manifest",
            str(child_manifest),
            "--period",
            "2026-Q2",
            "--db-path",
            str(db_path),
            "--decision-date",
            "2026-09-08",
            "--evidence-output",
            str(evidence),
        ]
    ) == 0
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["child_manifest_sources"][0]["report_basis"] == "consolidated"


def test_materializer_cli_rejects_unknown_direct_child_basis_before_database_creation(
    tmp_path,
) -> None:
    _batch_manifest, candidate, child_manifest = _write_batch_manifest(
        tmp_path,
        child_manifest_run_id="child",
        source_version="mops-test-source-without-report-basis.v1",
    )
    db_path = tmp_path / "unknown-direct-basis-isolated.db"
    evidence = tmp_path / "unknown-direct-basis-evidence.json"

    with pytest.raises(ValueError, match="report_basis is unknown"):
        materialize_cli(
            [
                "--child-manifest",
                str(child_manifest),
                "--period",
                "2026-Q2",
                "--db-path",
                str(db_path),
                "--decision-date",
                "2026-09-08",
                "--evidence-output",
                str(evidence),
            ]
        )
    assert not db_path.exists()
    assert not evidence.exists()
    assert candidate.is_file()


def _write_supersession_fixture(tmp_path):
    def _child(name: str, *, value: int, content_hash: str):
        child_dir = tmp_path / name
        child_dir.mkdir()
        row = _row(
            statement_type="income_statement",
            item_name="基本每股盈餘",
            value=value,
            value_unit="TWD_per_share",
            value_scale=100,
            period_start="2026-04-01",
            period_basis="quarter_single",
        )
        row["content_hash"] = content_hash
        row["raw_value"] = f"{value / 100:.2f}"
        candidate = _write_candidate(child_dir, [row])
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        payload.update(
            {
                "source_version": "mops-t164-consolidated-statements-with-t57sb01-xbrl-row-codes.v2",
                "report_basis": "consolidated",
                "pit_coverage_summary": {
                    "stock_code": "2330",
                    "market_request": "sii",
                    "period": "2026-Q2",
                },
            }
        )
        payload["rows"][0]["period"] = "2026-Q2"
        candidate.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        candidate_hash = "sha256:" + hashlib.sha256(candidate.read_bytes()).hexdigest()
        manifest = child_dir / "run-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": "mops-statement-pit-run-manifest.v1",
                    "run_id": child_dir.name,
                    "research_only": True,
                    "formal_oos_allowed": False,
                    "files": {"candidate": candidate_hash},
                }
            ),
            encoding="utf-8",
        )
        manifest_hash = "sha256:" + hashlib.sha256(manifest.read_bytes()).hexdigest()
        return candidate, manifest, candidate_hash, manifest_hash

    old = _child("old-child", value=2725, content_hash="a" * 64)
    new = _child("new-child", value=2800, content_hash="e" * 64)
    record = tmp_path / "supersession.json"
    record.write_text(
        json.dumps(
            {
                "schema_version": "mops-statement-artifact-correction.v1",
                "research_only": True,
                "formal_oos_allowed": False,
                "status": "accepted_replacement",
                "target": {
                    "stock_code": "2330",
                    "registry_market": "twse",
                    "period": "2026-Q2",
                },
                "superseded": {
                    "candidate_path": str(old[0]),
                    "manifest_path": str(old[1]),
                    "candidate_sha256": old[2],
                    "manifest_sha256": old[3],
                },
                "replacement": {
                    "candidate_path": str(new[0]),
                    "manifest_path": str(new[1]),
                    "candidate_sha256": new[2],
                    "manifest_sha256": new[3],
                },
                "reason": "fixture replacement has independently verified content lineage",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return old, new, record


def test_materializer_cli_collects_only_supersession_replacement(tmp_path) -> None:
    old, new, record = _write_supersession_fixture(tmp_path)
    db_path = tmp_path / "supersession-isolated.db"
    evidence = tmp_path / "supersession-evidence.json"

    assert materialize_cli(
        [
            "--supersession-record",
            str(record),
            "--period",
            "2026-Q2",
            "--db-path",
            str(db_path),
            "--decision-date",
            "2026-09-08",
            "--evidence-output",
            str(evidence),
        ]
    ) == 0
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["candidate_paths"] == [str(new[0].resolve())]
    assert str(old[0].resolve()) not in payload["candidate_paths"]
    assert payload["supersession_replacement_count"] == 1
    assert payload["batch_succeeded_child_count"] == 1
    assert payload["supersession_records"][0]["superseded_candidate_sha256"] == old[2]
    assert payload["supersession_records"][0]["replacement_candidate_sha256"] == new[2]
    assert payload["provider_sample_values_by_stock"]["2330"][0]["value"] == "28.00"
