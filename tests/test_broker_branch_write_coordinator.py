from types import SimpleNamespace
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
