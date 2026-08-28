from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import time
from unittest.mock import MagicMock

import pandas as pd

from app_module.broker_branch_write_coordinator import BrokerBranchWriteCoordinator


def test_write_coordinator_writes_daily_without_backup_and_merged_with_backup(tmp_path) -> None:
    backup = MagicMock()
    coordinator = BrokerBranchWriteCoordinator(SimpleNamespace(create_backup=backup))
    frame = pd.DataFrame({"date": ["2026-07-10"], "net_lots": [10]})
    daily = tmp_path / "daily.csv"
    merged = tmp_path / "merged.csv"
    merged.write_text("old", encoding="utf-8")

    coordinator.write_daily(frame, daily)
    coordinator.write_merged(frame, merged)

    backup.assert_called_once_with(merged)
    assert pd.read_csv(daily)["net_lots"].tolist() == [10]
    assert pd.read_csv(merged)["net_lots"].tolist() == [10]


def test_write_coordinator_serializes_concurrent_csv_mutations(tmp_path, monkeypatch) -> None:
    coordinator = BrokerBranchWriteCoordinator(SimpleNamespace(create_backup=MagicMock()))
    original_to_csv = pd.DataFrame.to_csv
    active_writers = 0
    max_active_writers = 0

    def slow_to_csv(self, *args, **kwargs):
        nonlocal active_writers, max_active_writers
        active_writers += 1
        max_active_writers = max(max_active_writers, active_writers)
        try:
            time.sleep(0.02)
            return original_to_csv(self, *args, **kwargs)
        finally:
            active_writers -= 1

    monkeypatch.setattr(pd.DataFrame, "to_csv", slow_to_csv)
    frame = pd.DataFrame({"date": ["2026-07-10"], "net_lots": [10]})
    paths = (tmp_path / "one.csv", tmp_path / "two.csv")

    with ThreadPoolExecutor(max_workers=2) as executor:
        tuple(
            executor.map(
                lambda path: coordinator.write_daily(frame, path),
                paths,
            )
        )

    assert max_active_writers == 1
    assert all(path.exists() for path in paths)
