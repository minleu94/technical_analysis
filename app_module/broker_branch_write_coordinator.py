"""Broker branch CSV write boundary。"""

from pathlib import Path
from threading import RLock
from typing import Any

import pandas as pd


class BrokerBranchWriteCoordinator:
    def __init__(self, config: Any) -> None:
        self.config = config
        # Fetching may become bounded/concurrent later, but every CSV mutation
        # must remain serialized behind this process-local writer boundary.
        self._write_lock = RLock()

    def write_daily(self, frame: pd.DataFrame, path: Path) -> None:
        with self._write_lock:
            frame.to_csv(path, index=False, encoding="utf-8-sig")

    def write_merged(self, frame: pd.DataFrame, path: Path) -> None:
        with self._write_lock:
            if path.exists():
                self.config.create_backup(path)
            frame.to_csv(path, index=False, encoding="utf-8-sig")
