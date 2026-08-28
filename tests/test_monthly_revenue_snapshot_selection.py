from __future__ import annotations

from data_module.monthly_revenue_snapshot_selection import (
    inspect_monthly_revenue_snapshot,
    select_latest_monthly_revenue_snapshot,
)


def test_select_latest_snapshot_uses_period_not_file_size(tmp_path) -> None:
    snapshot_dir = tmp_path / "monthly_revenue_mops_snapshots"
    snapshot_dir.mkdir()
    old = snapshot_dir / "mops_monthly_revenue_snapshot_2014-04_2026-05_2026-06-16.csv"
    new = snapshot_dir / "mops_monthly_revenue_snapshot_2026-07_2026-07_2026-08-28.csv"
    old.write_text("x\n" * 500, encoding="utf-8")
    new.write_text("x\n", encoding="utf-8")

    assert select_latest_monthly_revenue_snapshot(snapshot_dir) == new.resolve()


def test_snapshot_selection_ignores_backup_and_exposes_filename_metadata(tmp_path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    backup = snapshot_dir / (
        "mops_monthly_revenue_snapshot_2026-07_2026-07_2026-08-28"
        ".before_apply.csv"
    )
    backup.write_text("x\n", encoding="utf-8")
    path = snapshot_dir / "mops_monthly_revenue_snapshot_2026-06_2026-06_2026-07-14.csv"
    path.write_text("x\n", encoding="utf-8")

    info = inspect_monthly_revenue_snapshot(path)
    assert info.start_period == "2026-06"
    assert info.end_period == "2026-06"
    assert info.fetch_date == "2026-07-14"
    assert select_latest_monthly_revenue_snapshot(snapshot_dir) == path.resolve()

