from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, cast

from data_module.ml_file_field_inventory import inspect_ml_file_fields
from scripts.inspect_ml_file_field_inventory import main


def _clock() -> datetime:
    return datetime(2026, 7, 30, 8, 30, tzinfo=UTC)


def _field_by_path_and_name(
    report: dict[str, object],
    *,
    path_fragment: str,
    field_name: str,
) -> dict[str, object]:
    raw_fields = report["fields"]
    assert isinstance(raw_fields, list)
    return next(
        field
        for field in raw_fields
        if isinstance(field, dict)
        and path_fragment in str(field["path_pattern"])
        and field["field_name"] == field_name
    )


def test_inventory_deduplicates_csv_pattern_and_never_reads_data_rows(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    prices = data_root / "daily_price"
    prices.mkdir(parents=True)
    (prices / "20240102.csv").write_text(
        "日期,證券代號,收盤價\n"
        + ("THIS_ROW_MUST_NOT_BE_PARSED," * 100_000),
        encoding="utf-8",
    )
    (prices / "20240103.csv").write_text(
        "日期,證券代號,收盤價\nnot,a,number\n",
        encoding="utf-8",
    )

    result = inspect_ml_file_fields(data_root, clock=_clock)
    report = cast(dict[str, Any], result.to_dict())

    assert report["summary"]["candidate_file_count"] == 2  # type: ignore[index]
    assert report["summary"]["schema_scanned_file_count"] == 2  # type: ignore[index]
    assert report["summary"]["source_schema_count"] == 1  # type: ignore[index]
    source = report["sources"][0]  # type: ignore[index]
    assert source["path_pattern"] == "daily_price/{date}.csv"
    assert source["file_count"] == 2
    close = _field_by_path_and_name(
        report,
        path_fragment="daily_price/",
        field_name="收盤價",
    )
    assert close["canonical_dtype"] == "unknown"
    assert close["dtype_basis"] == "csv_header_only"
    assert close["eligibility_status"] == "unreviewed"
    symbol = _field_by_path_and_name(
        report,
        path_fragment="daily_price/",
        field_name="證券代號",
    )
    assert symbol["eligibility_status"] == "excluded_identifier"
    date_field = _field_by_path_and_name(
        report,
        path_fragment="daily_price/",
        field_name="日期",
    )
    assert date_field["eligibility_status"] == "availability_only"
    assert report["safety"]["csv_data_rows_read"] is False  # type: ignore[index]


def test_inventory_reads_bounded_json_top_row_keys_and_jsonl_types(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    sidecars = data_root / "meta_data"
    sidecars.mkdir(parents=True)
    (sidecars / "source_manifest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-07-30T08:30:00Z",
                "rows": [
                    {
                        "stock_code": "2330",
                        "available_date": "2026-07-29",
                        "value_bp": 125,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (sidecars / "events.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "source_id": "a",
                        "first_seen_at": "2026-07-29T01:00:00Z",
                        "coverage_bp": 9500,
                    }
                ),
                json.dumps(
                    {
                        "source_id": "b",
                        "first_seen_at": "2026-07-30T01:00:00Z",
                        "coverage_bp": None,
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    report = cast(
        dict[str, Any],
        inspect_ml_file_fields(
            data_root,
            max_json_bytes=4096,
            max_jsonl_lines=2,
            clock=_clock,
        ).to_dict(),
    )

    value = _field_by_path_and_name(
        report,
        path_fragment="source_manifest.json",
        field_name="row.value_bp",
    )
    assert value["canonical_dtype"] == "integer"
    available = _field_by_path_and_name(
        report,
        path_fragment="source_manifest.json",
        field_name="row.available_date",
    )
    assert available["eligibility_status"] == "availability_only"
    coverage = _field_by_path_and_name(
        report,
        path_fragment="events.jsonl",
        field_name="row.coverage_bp",
    )
    assert coverage["canonical_dtype"] == "integer"
    first_seen = _field_by_path_and_name(
        report,
        path_fragment="events.jsonl",
        field_name="row.first_seen_at",
    )
    assert first_seen["eligibility_status"] == "availability_only"


def test_inventory_fail_closes_financial_snapshots_and_isolates_legacy_outputs(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    financial = data_root / "financial_data"
    financial.mkdir(parents=True)
    (financial / "2330_balance_sheet.csv").write_text(
        "date,stock_id,type,value\n",
        encoding="utf-8",
    )
    predictions = data_root / "predictions"
    predictions.mkdir()
    (predictions / "prediction_2330_20240103.json").write_text(
        json.dumps({"symbol": "2330", "prediction": 123}),
        encoding="utf-8",
    )
    models = data_root / "models"
    models.mkdir()
    (models / "2330_model.pkl").write_bytes(b"not-a-real-pickle")
    replay = data_root / "output" / "replay"
    replay.mkdir(parents=True)
    (replay / "outcome_rows.json").write_text(
        json.dumps([{"target_weight_bp": 1000}]),
        encoding="utf-8",
    )
    backup = data_root / "backup"
    backup.mkdir()
    (backup / "copy.csv").write_text("secret\n", encoding="utf-8")

    report = cast(
        dict[str, Any],
        inspect_ml_file_fields(data_root, clock=_clock).to_dict(),
    )

    statement_value = _field_by_path_and_name(
        report,
        path_fragment="financial_data/",
        field_name="value",
    )
    assert statement_value["eligibility_status"] == "blocked_no_provenance"
    summary = report["summary"]
    assert summary["candidate_file_count"] == 4
    assert summary["dispositioned_file_count"] == 4
    assert summary["undispositioned_file_count"] == 0
    assert summary["disposition_coverage_bp"] == 10_000
    skipped = report["skipped"]
    assert any(
        row["eligibility_status"] == "excluded_leakage"
        and row["reason_code"] == "legacy_pickle_or_model_binary_excluded"
        for row in skipped
    )
    assert any(
        row["eligibility_status"] == "excluded_leakage"
        and row["reason_code"]
        == "prediction_model_replay_outcome_or_backtest_excluded"
        for row in skipped
    )
    assert any(
        row["object_kind"] == "directory"
        and row["reason_code"] == "excluded_backup_temp_log_or_test_scope"
        for row in skipped
    )
    assert all(
        not str(source["representative_relative_path"]).startswith(str(tmp_path))
        for source in report["sources"]
    )


def test_large_output_detail_is_dispositioned_without_loading_schema(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    details = data_root / "output" / "daily_details"
    details.mkdir(parents=True)
    (details / "metrics.json").write_text(
        json.dumps({"rows": [{"value": "x" * 5000}]}),
        encoding="utf-8",
    )

    report = cast(
        dict[str, Any],
        inspect_ml_file_fields(
            data_root,
            max_output_detail_bytes=100,
            clock=_clock,
        ).to_dict(),
    )

    assert report["summary"]["candidate_file_count"] == 1  # type: ignore[index]
    assert report["summary"]["schema_scanned_file_count"] == 0  # type: ignore[index]
    assert report["summary"]["skipped_file_count"] == 1  # type: ignore[index]
    assert report["skipped"][0]["reason_code"] == (  # type: ignore[index]
        "large_output_detail_isolated_without_schema_scan"
    )
    assert report["skipped"][0]["eligibility_status"] == "research_shadow"  # type: ignore[index]


def test_inventory_self_artifact_is_outside_candidate_denominator(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    release = data_root / "output" / "release_v4"
    release.mkdir(parents=True)
    (release / "ml_file_field_inventory.json").write_text(
        json.dumps({"schema_version": "previous"}),
        encoding="utf-8",
    )
    (data_root / "source.csv").write_text("date,value\n", encoding="utf-8")

    report = cast(
        dict[str, Any],
        inspect_ml_file_fields(data_root, clock=_clock).to_dict(),
    )

    assert report["summary"]["candidate_file_count"] == 1
    assert report["summary"]["disposition_coverage_bp"] == 10_000
    assert any(
        row["reason_code"] == "inventory_self_artifact_outside_discovery_scope"
        and row["file_count"] == 0
        for row in report["skipped"]
    )


def test_cli_writes_release_v4_json(tmp_path: Path, capsys: object) -> None:
    data_root = tmp_path / "data"
    meta = data_root / "meta_data"
    meta.mkdir(parents=True)
    (meta / "availability.csv").write_text(
        "source_id,available_date\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "output" / "release_v4"

    assert (
        main(
            [
                "--data-root",
                str(data_root),
                "--output-dir",
                str(output_dir),
                "--pretty",
            ]
        )
        == 0
    )

    output_path = output_dir / "ml_file_field_inventory.json"
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == "ml-file-field-inventory.v1"
    assert report["summary"]["disposition_coverage_bp"] == 10_000
    assert report["safety"]["sqlite_inspected"] is False
    assert report["inventory_hash"].startswith("sha256:")
