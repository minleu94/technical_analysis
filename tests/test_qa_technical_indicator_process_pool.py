from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from scripts import qa_technical_indicator_process_pool as probe


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
    frame = pd.DataFrame(rows)
    frame.to_csv(path, index=False, encoding="utf-8-sig")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_process_pool_requires_explicit_confirmation_without_writes(tmp_path: Path) -> None:
    stock_data_file = tmp_path / "stock_data.csv"
    staging_root = tmp_path / "staging"
    protected_root = tmp_path / "protected"
    staging_root.mkdir()
    protected_root.mkdir()
    _write_stock_data(stock_data_file)

    report = probe.measure_process_pool(
        stock_data_file=stock_data_file,
        staging_root=staging_root,
        protected_roots=(protected_root,),
        stock_ids=("0050",),
    )

    assert report["status"] == "confirmation_required"
    assert report["staging_write_attempted"] is False
    assert report["production_write_attempted"] is False
    assert list(staging_root.iterdir()) == []


def test_process_pool_rejects_staging_inside_protected_root(tmp_path: Path) -> None:
    stock_data_file = tmp_path / "stock_data.csv"
    protected_root = tmp_path / "protected"
    staging_root = protected_root / "staging"
    protected_root.mkdir()
    staging_root.mkdir()
    _write_stock_data(stock_data_file)

    report = probe.measure_process_pool(
        stock_data_file=stock_data_file,
        staging_root=staging_root,
        protected_roots=(protected_root,),
        confirm_process_pool_probe=True,
        stock_ids=("0050",),
    )

    assert report["status"] == "blocked"
    assert report["blocker"] == "staging_root_inside_protected_root"
    assert list(staging_root.iterdir()) == []


def test_process_pool_measures_real_calculator_with_parent_single_writer(
    tmp_path: Path,
) -> None:
    stock_data_file = tmp_path / "stock_data.csv"
    staging_root = tmp_path / "staging"
    protected_root = tmp_path / "protected"
    staging_root.mkdir()
    protected_root.mkdir()
    before = _write_stock_data(stock_data_file)

    report = probe.measure_process_pool(
        stock_data_file=stock_data_file,
        staging_root=staging_root,
        protected_roots=(protected_root,),
        confirm_process_pool_probe=True,
        stock_ids=("0050", "2330"),
        min_rows=30,
        max_rows_per_stock=35,
        max_workers=2,
        max_in_flight=2,
        max_retries=1,
        transient_fail_stocks=("0050",),
    )

    assert report["status"] == "measured"
    assert report["staging_process_pool_enabled"] is True
    assert report["parallelism_enabled"] is False
    assert report["production_worker_enabled"] is False
    assert report["write_attempted"] is True
    assert report["staging_write_attempted"] is True
    assert report["production_write_attempted"] is False
    assert report["sqlite_write_attempted"] is False
    assert report["production_sqlite_write_attempted"] is False
    assert report["process_pool"]["observed_worker_count"] >= 1
    assert report["process_pool"]["retry_count"] == 1
    assert report["process_pool"]["max_observed_in_flight"] <= 2
    assert all(report["checks"].values())
    assert report["rows"]["aggregate_rows"] == 70
    assert report["cleanup_succeeded"] is True
    assert report["input_unchanged"] is True
    assert hashlib.sha256(stock_data_file.read_bytes()).hexdigest() == before
    assert list(staging_root.iterdir()) == []


def test_process_pool_requires_bounded_stock_selection(tmp_path: Path) -> None:
    stock_data_file = tmp_path / "stock_data.csv"
    staging_root = tmp_path / "staging"
    protected_root = tmp_path / "protected"
    staging_root.mkdir()
    protected_root.mkdir()
    _write_stock_data(stock_data_file)

    report = probe.measure_process_pool(
        stock_data_file=stock_data_file,
        staging_root=staging_root,
        protected_roots=(protected_root,),
        confirm_process_pool_probe=True,
    )

    assert report["status"] == "blocked"
    assert report["blocker"] == "bounded_stock_selection_required"


def test_process_pool_validates_bounds(tmp_path: Path) -> None:
    stock_data_file = tmp_path / "stock_data.csv"
    staging_root = tmp_path / "staging"
    protected_root = tmp_path / "protected"
    staging_root.mkdir()
    protected_root.mkdir()
    _write_stock_data(stock_data_file)

    with pytest.raises(ValueError, match="max_workers"):
        probe.measure_process_pool(
            stock_data_file=stock_data_file,
            staging_root=staging_root,
            protected_roots=(protected_root,),
            stock_ids=("0050",),
            max_workers=9,
        )
