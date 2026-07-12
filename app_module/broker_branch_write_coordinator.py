"""Broker branch CSV write boundary。"""

from pathlib import Path
from typing import Any

import pandas as pd


class BrokerBranchWriteCoordinator:
    def __init__(self, config: Any) -> None:
        self.config = config

    @staticmethod
    def write_daily(frame: pd.DataFrame, path: Path) -> None:
        frame.to_csv(path, index=False, encoding="utf-8-sig")

    def write_merged(self, frame: pd.DataFrame, path: Path) -> None:
        if path.exists():
            self.config.create_backup(path)
        frame.to_csv(path, index=False, encoding="utf-8-sig")
