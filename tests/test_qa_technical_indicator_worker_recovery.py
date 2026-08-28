from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from scripts import qa_technical_indicator_worker_recovery as probe


def _write_stock_data(path: Path) -> str:
    rows: list[dict[str, object]] = []
    for stock_id, base_price in (("0050", 100), ("2330", 900)):
        for day in range(35):
            close = base_price + day
            rows.append(
                {
                    "日期": f"2026-07-{day + 1:02d}",
                    "證券代號": stock_id,
                    "開盤價": close - 1,
                    "最高價": close + 1,
                    "最低價": close - 2,
                    "收盤價": close,
                    "成交股數": 1000 + day,
                }
            )
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_worker_recovery_requires_explicit_confirmation_without_writes(tmp_path: Path) -> None:
    stock_data_file = tmp_path / "stock_data.csv"
    staging_root = tmp_path / "staging"
    protected_root = tmp_path / "protected"
    staging_root.mkdir()
    protected_root.mkdir()
    _write_stock_data(stock_data_file)

    report = probe.measure_worker_recovery(
        stock_data_file=stock_data_file,
        staging_root=staging_root,
        protected_roots=(protected_root,),
        stock_ids=("0050", "2330"),
    )

    assert report["status"] == "confirmation_required"
    assert report["production_write_attempted"] is False
    assert list(staging_root.iterdir()) == []


def test_worker_recovery_measures_real_calculator_crash_and_cancel(tmp_path: Path) -> None:
    stock_data_file = tmp_path / "stock_data.csv"
    staging_root = tmp_path / "staging"
    protected_root = tmp_path / "protected"
    staging_root.mkdir()
    protected_root.mkdir()
    before = _write_stock_data(stock_data_file)

    report = probe.measure_worker_recovery(
        stock_data_file=stock_data_file,
        staging_root=staging_root,
        protected_roots=(protected_root,),
        confirm_probe=True,
        stock_ids=("0050", "2330"),
        min_rows=30,
        max_rows_per_stock=35,
        max_workers=2,
        max_in_flight=2,
        max_retries=1,
    )

    assert report["status"] == "measured"
    assert report["staging_process_pool_enabled"] is True
    assert report["production_worker_enabled"] is False
    assert report["staging_write_attempted"] is True
    assert report["production_write_attempted"] is False
    assert report["sqlite_write_attempted"] is True
    assert report["production_sqlite_write_attempted"] is False
    assert all(report["checks"].values())
    assert report["crash_recovery"]["status"] == "measured"
    assert report["crash_recovery"]["crash_observed"] is True
    assert report["crash_recovery"]["recovered_rows"] > 0
    assert report["cancellation"]["status"] == "measured"
    assert report["cancellation"]["cancelled_ids"]
    assert report["production_single_writer_integration"]["status"] == "staging_measured"
    assert report["production_single_writer_integration"]["scope"] == "isolated_staging"
    assert report["production_single_writer_integration"]["production_write_attempted"] is False
    assert report["cleanup_succeeded"] is True
    assert hashlib.sha256(stock_data_file.read_bytes()).hexdigest() == before
    assert list(staging_root.iterdir()) == []


def test_worker_recovery_rejects_protected_staging_root(tmp_path: Path) -> None:
    stock_data_file = tmp_path / "stock_data.csv"
    protected_root = tmp_path / "protected"
    staging_root = protected_root / "staging"
    protected_root.mkdir()
    staging_root.mkdir()
    _write_stock_data(stock_data_file)

    report = probe.measure_worker_recovery(
        stock_data_file=stock_data_file,
        staging_root=staging_root,
        protected_roots=(protected_root,),
        confirm_probe=True,
    )

    assert report["status"] == "blocked"
    assert report["blocker"] == "staging_root_inside_protected_root"
