"""Decision application services 的 SQLite-first 資料 provider。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd

logger = logging.getLogger(__name__)


class SqliteFirstFrameProvider:
    """以唯讀查詢優先、CSV 候選路徑降級提供資料框。"""

    def __init__(
        self,
        config: Any,
        *,
        table: str,
        csv_paths: Callable[[Any], Iterable[Path]],
        db_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        self.config = config
        self.table = table
        self.csv_paths = csv_paths
        self.db_factory = db_factory

    def __call__(self) -> pd.DataFrame:
        if getattr(self.config, "use_sqlite", False):
            try:
                factory = self.db_factory
                if factory is None:
                    from data_module.db_manager import DBManager

                    factory = DBManager
                frame = factory(self.config).execute_query(
                    f"SELECT * FROM {self.table} ORDER BY 日期 ASC;"
                )
                if not frame.empty:
                    return frame.copy()
            except Exception as exc:  # noqa: BLE001 - fallback 是既有契約
                logger.warning("SQLite 載入 %s 失敗，降級 CSV：%s", self.table, exc)

        for path in self.csv_paths(self.config):
            if path.exists():
                return pd.read_csv(path, encoding="utf-8-sig")
        return pd.DataFrame()


def market_index_frame_provider(config: Any) -> SqliteFirstFrameProvider:
    return SqliteFirstFrameProvider(
        config,
        table="market_indices",
        csv_paths=lambda current: (current.market_index_file,),
    )


def industry_index_frame_provider(config: Any) -> SqliteFirstFrameProvider:
    def candidates(current: Any) -> tuple[Path, ...]:
        return (
            current.industry_index_file,
            current.meta_data_dir / "industry_index.csv",
        )

    return SqliteFirstFrameProvider(
        config,
        table="industry_indices",
        csv_paths=candidates,
    )


def recent_stock_screen_provider(config: Any) -> Callable[[str, int], Any]:
    """建立 StockScreener recent stock frame adapter。"""
    from decision_module.stock_screener_sqlite_reader import load_recent_stock_prices

    return lambda period, volume_lookback: load_recent_stock_prices(
        config, period, volume_lookback
    )


def recent_industry_screen_provider(config: Any) -> Callable[[str], Any]:
    """建立 StockScreener recent industry frame adapter。"""
    from decision_module.stock_screener_sqlite_reader import load_recent_industry_indices

    return lambda period: load_recent_industry_indices(config, period)
