from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from scripts.scheduled.paper_execution_dependency_gate import inspect_dependency


TARGET = "20260908"
OBSERVED = datetime(2026, 9, 8, 13, 0, tzinfo=timezone.utc)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _seed_ready_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    data_root = tmp_path / "data"
    output_root = tmp_path / "output"
    db_path = data_root / "sqlite" / "twstock.db"
    (data_root / "daily_price").mkdir(parents=True)
    (data_root / "daily_price_tpex").mkdir(parents=True)
    (data_root / "daily_price" / f"{TARGET}.csv").write_text(
        "證券代號,開盤價\n2330,100.0\n",
        encoding="utf-8",
    )
    (data_root / "daily_price_tpex" / f"{TARGET}.csv").write_text(
        "日期,證券代號,開盤價\n20260908,2330,100.0\n",
        encoding="utf-8",
    )

    db_path.parent.mkdir(parents=True)
    connection = sqlite3.connect(db_path)
    connection.execute('CREATE TABLE daily_prices ("日期" TEXT, "證券代號" TEXT, "開盤價" REAL)')
    connection.execute(
        'INSERT INTO daily_prices ("日期", "證券代號", "開盤價") VALUES (?, ?, ?)',
        (TARGET, "2330", 100.0),
    )
    connection.commit()
    connection.close()

    quick_path = output_root / "scheduled" / "data_update_quick" / "latest_status.json"
    _write_json(
        quick_path,
        {
            "status": "passed",
            "end_date": "2026-09-08",
            "checked_at": "2026-09-08T20:00:00+08:00",
            "steps": [
                {"name": "update_twse_daily_prices", "status": "passed", "result": {}},
                {"name": "sync_daily_prices_to_sqlite", "status": "passed", "result": {}},
            ],
        },
    )
    freshness_path = output_root / "scheduled" / "data_freshness" / "latest_status.json"
    _write_json(
        freshness_path,
        {
            "status": "passed",
            "checked_at": "2026-09-08T20:05:00+08:00",
            "checks": {
                "daily_prices_latest_date": TARGET,
                "data_update_quick_checked_date": "2026-09-08",
            },
        },
    )
    return data_root, output_root, db_path


def test_dependency_gate_requires_same_date_receipts_source_hash_and_db_rows(tmp_path: Path) -> None:
    data_root, output_root, db_path = _seed_ready_inputs(tmp_path)

    result = inspect_dependency(
        data_root=data_root,
        output_root=output_root,
        db_path=db_path,
        observed_at=OBSERVED,
    )

    assert result["status"] == "ready"
    assert result["ready"] is True
    assert result["target_date"] == "2026-09-08"
    assert str(result["source_hash"]).startswith("sha256:")
    assert result["market_observation"]["mode"] == "ro/query_only"  # type: ignore[index]
    assert result["source_db_written"] is False
    assert result["source_files_written"] is False
    assert result["source_db_readback"]["twse"]["matched_rows"] == 1  # type: ignore[index]
    assert result["source_db_readback"]["tpex"]["matched_rows"] == 1  # type: ignore[index]


def test_dependency_gate_blocks_stale_receipt_and_missing_target_source(tmp_path: Path) -> None:
    data_root, output_root, db_path = _seed_ready_inputs(tmp_path)
    quick_path = output_root / "scheduled" / "data_update_quick" / "latest_status.json"
    payload = json.loads(quick_path.read_text(encoding="utf-8"))
    payload["end_date"] = "2026-09-07"
    quick_path.write_text(json.dumps(payload), encoding="utf-8")
    (data_root / "daily_price_tpex" / f"{TARGET}.csv").unlink()

    result = inspect_dependency(
        data_root=data_root,
        output_root=output_root,
        db_path=db_path,
        observed_at=OBSERVED,
    )

    assert result["status"] == "blocked"
    assert result["ready"] is False
    blockers = result["blockers"]
    assert "quick_update_receipt_data_date_not_target" in blockers  # type: ignore[operator]
    assert any(str(item).startswith("source_file_missing:") for item in blockers)  # type: ignore[union-attr]


def test_dependency_gate_rejects_future_receipt_dates(tmp_path: Path) -> None:
    data_root, output_root, db_path = _seed_ready_inputs(tmp_path)
    quick_path = output_root / "scheduled" / "data_update_quick" / "latest_status.json"
    payload = json.loads(quick_path.read_text(encoding="utf-8"))
    payload["end_date"] = "2026-09-09"
    payload["checked_at"] = "2026-09-09T01:00:00+08:00"
    quick_path.write_text(json.dumps(payload), encoding="utf-8")
    freshness_path = output_root / "scheduled" / "data_freshness" / "latest_status.json"
    freshness = json.loads(freshness_path.read_text(encoding="utf-8"))
    freshness["checks"]["daily_prices_latest_date"] = "20260909"
    freshness["checks"]["data_update_quick_checked_date"] = "2026-09-09"
    freshness_path.write_text(json.dumps(freshness), encoding="utf-8")

    result = inspect_dependency(
        data_root=data_root,
        output_root=output_root,
        db_path=db_path,
        observed_at=OBSERVED,
    )

    assert result["status"] == "blocked"
    assert "quick_update_receipt_data_date_not_target" in result["blockers"]  # type: ignore[operator]
    assert "quick_update_receipt_checked_date_not_target" in result["blockers"]  # type: ignore[operator]
    assert "freshness_receipt_daily_prices_not_target" in result["blockers"]  # type: ignore[operator]
    assert "freshness_receipt_update_date_not_target" in result["blockers"]  # type: ignore[operator]


def test_dependency_gate_rejects_future_checked_at_even_when_dates_match(tmp_path: Path) -> None:
    data_root, output_root, db_path = _seed_ready_inputs(tmp_path)
    quick_path = output_root / "scheduled" / "data_update_quick" / "latest_status.json"
    payload = json.loads(quick_path.read_text(encoding="utf-8"))
    payload["checked_at"] = "2026-09-08T22:00:00+08:00"
    quick_path.write_text(json.dumps(payload), encoding="utf-8")

    result = inspect_dependency(
        data_root=data_root,
        output_root=output_root,
        db_path=db_path,
        observed_at=OBSERVED,
    )

    assert result["ready"] is False
    assert "quick_update_receipt_checked_at_after_observed" in result["blockers"]  # type: ignore[operator]


def test_dependency_gate_rejects_naive_or_malformed_receipt_timestamps(tmp_path: Path) -> None:
    data_root, output_root, db_path = _seed_ready_inputs(tmp_path)
    quick_path = output_root / "scheduled" / "data_update_quick" / "latest_status.json"
    freshness_path = output_root / "scheduled" / "data_freshness" / "latest_status.json"

    quick_payload = json.loads(quick_path.read_text(encoding="utf-8"))
    quick_payload["checked_at"] = "2026-09-08T20:00:00"
    quick_path.write_text(json.dumps(quick_payload), encoding="utf-8")
    freshness_payload = json.loads(freshness_path.read_text(encoding="utf-8"))
    freshness_payload["checked_at"] = "not-a-timestamp"
    freshness_path.write_text(json.dumps(freshness_payload), encoding="utf-8")

    result = inspect_dependency(
        data_root=data_root,
        output_root=output_root,
        db_path=db_path,
        observed_at=OBSERVED,
    )

    blockers = result["blockers"]
    assert "quick_update_receipt_checked_at_invalid:naive" in blockers  # type: ignore[operator]
    assert "freshness_receipt_checked_at_invalid:malformed" in blockers  # type: ignore[operator]


def test_dependency_gate_rejects_replaced_or_empty_csv_and_stale_db_values(tmp_path: Path) -> None:
    data_root, output_root, db_path = _seed_ready_inputs(tmp_path)
    twse_path = data_root / "daily_price" / f"{TARGET}.csv"
    twse_path.write_text("證券代號,開盤價\n2330,999.0\n", encoding="utf-8")

    replaced = inspect_dependency(
        data_root=data_root,
        output_root=output_root,
        db_path=db_path,
        observed_at=OBSERVED,
    )
    assert any(str(item).startswith("source_db_readback_mismatch:twse:2330") for item in replaced["blockers"])  # type: ignore[union-attr]

    twse_path.write_text("證券代號,開盤價\n", encoding="utf-8")
    empty = inspect_dependency(
        data_root=data_root,
        output_root=output_root,
        db_path=db_path,
        observed_at=OBSERVED,
    )
    assert any(str(item).startswith("source_rows_empty_or_open_missing:") for item in empty["blockers"])  # type: ignore[union-attr]

    twse_path.write_text("證券代號,開盤價\n2330,100.0\n", encoding="utf-8")
    connection = sqlite3.connect(db_path)
    connection.execute('UPDATE daily_prices SET "開盤價"=? WHERE "證券代號"=?', (101.0, "2330"))
    connection.commit()
    connection.close()
    stale_db = inspect_dependency(
        data_root=data_root,
        output_root=output_root,
        db_path=db_path,
        observed_at=OBSERVED,
    )
    assert any(str(item).startswith("source_db_readback_mismatch:twse:2330") for item in stale_db["blockers"])  # type: ignore[union-attr]


def test_dependency_gate_treats_weekend_as_calendar_delegation(tmp_path: Path) -> None:
    result = inspect_dependency(
        data_root=tmp_path / "missing-data",
        output_root=tmp_path / "missing-output",
        db_path=tmp_path / "missing.db",
        observed_at=datetime(2026, 9, 12, 1, 0, tzinfo=timezone.utc),
    )

    assert result["status"] == "not_trading_day"
    assert result["ready"] is True
    assert result["reason"] == "taipei_weekend"
