"""每日股價來源選擇與日期一致性防線。

``stock_data_whole.csv`` 是歷史整合快照，不能在同一日期已有日期檔時
覆蓋較新的日期檔。這個模組只處理來源選擇與檔案內部日期驗證；它不會
修改任何來源檔案，也不把檔案 mtime 當成來源證據。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
import re
from typing import Any

import pandas as pd


DATE_FILE_SOURCE_VERSION = "daily-price-date-file-selection.v1"
AGGREGATE_SOURCE_VERSION = "daily-price-aggregate-receipt.v1"
AGGREGATE_RECEIPT_SUFFIX = ".source.json"
_DATE_FILE_NAME = re.compile(r"^\d{8}$")


class DailyPriceSourceError(ValueError):
    """每日股價來源無法證明為同一日期、同一品質契約時使用。"""


def configured_daily_price_dirs(config: Any) -> tuple[Path, ...]:
    """回傳去重後的 TWSE/TPEX 日期檔目錄。"""

    directories: list[Path] = []
    for value in (
        getattr(config, "daily_price_dir", None),
        getattr(config, "tpex_daily_price_dir", None),
    ):
        if value is None:
            continue
        path = Path(value)
        if path.exists() and path.is_dir() and path not in directories:
            directories.append(path)
    return tuple(directories)


def discover_daily_price_csvs(
    directories: Iterable[Path],
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """列出日期檔與命名不合約檔；不合約檔會讓上游 fail closed。

    即使某個目錄同時有合法與不合法 CSV，也不能退回 aggregate 快照，
    否則錯誤檔可能被舊快照靜默遮蔽。
    """

    valid: list[Path] = []
    invalid: list[Path] = []
    seen: set[Path] = set()
    for directory in directories:
        for path in sorted(directory.glob("*.csv")):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if _DATE_FILE_NAME.fullmatch(path.stem):
                valid.append(path)
            else:
                invalid.append(path)
    return tuple(valid), tuple(invalid)


def source_date_from_path(path: Path) -> str:
    """取得並驗證日期檔的 YYYYMMDD 檔名。"""

    date_key = path.stem
    if _DATE_FILE_NAME.fullmatch(date_key) is None:
        raise DailyPriceSourceError(
            f"每日股價檔名不是 YYYYMMDD：{path.name}"
        )
    return date_key


def validate_daily_price_frame_date(
    frame: pd.DataFrame,
    *,
    path: Path,
    normalize_date: Any,
) -> pd.DataFrame:
    """驗證 CSV 內宣告日期與檔名一致，並回傳含日期欄的副本。

    官方日期檔可以沒有日期欄，此時日期由已驗證的檔名提供；若檔案
    明確宣告日期，則每一列都必須可正規化且等於檔名日期，不能只檢查
    第一列或把錯日期覆寫成檔名日期。
    """

    date_key = source_date_from_path(path)
    normalized = frame.copy()
    if "日期" not in normalized.columns:
        normalized.insert(0, "日期", date_key)
        return normalized

    declared = normalized["日期"].map(normalize_date)
    if declared.empty or declared.isna().any() or any(
        not str(value).strip() for value in declared
    ):
        raise DailyPriceSourceError(
            f"每日股價檔含空日期：{path.name}"
        )
    declared_values = {str(value).strip() for value in declared}
    if declared_values != {date_key}:
        raise DailyPriceSourceError(
            f"每日股價檔內日期與檔名不一致：{path.name} -> "
            f"{sorted(declared_values)}"
        )
    normalized["日期"] = declared
    return normalized


def aggregate_receipt_path(stock_data_file: Path) -> Path:
    """回傳整合快照的明確來源 receipt 路徑。"""

    return stock_data_file.with_name(
        f"{stock_data_file.name}{AGGREGATE_RECEIPT_SUFFIX}"
    )


def validate_aggregate_receipt_payload(
    payload: Mapping[str, Any],
    *,
    stock_data_file: Path,
    actual_frame: pd.DataFrame,
    file_sha256: str,
) -> None:
    """驗證 aggregate fallback 的內容 receipt，而非只信 manifest flags。"""

    if payload.get("schema_version") != AGGREGATE_SOURCE_VERSION:
        raise DailyPriceSourceError("整合快照 receipt schema 不相容")
    if payload.get("source_version") != AGGREGATE_SOURCE_VERSION:
        raise DailyPriceSourceError("整合快照 receipt source version 不相容")
    if payload.get("quality_status") != "accepted":
        raise DailyPriceSourceError("整合快照 receipt 品質不是 accepted")
    declared_path = payload.get("source_path")
    if not isinstance(declared_path, str) or Path(declared_path).resolve() != stock_data_file.resolve():
        raise DailyPriceSourceError("整合快照 receipt source_path 不一致")
    if payload.get("source_sha256") != file_sha256:
        raise DailyPriceSourceError("整合快照 receipt 未綁定目前整合快照 bytes")
    if "日期" not in actual_frame.columns:
        raise DailyPriceSourceError("整合快照缺少日期欄")
    actual_dates = {
        str(value).strip()
        for value in actual_frame["日期"].dropna().map(str)
        if str(value).strip()
    }
    declared_dates = payload.get("date_keys")
    if not isinstance(declared_dates, list) or {
        str(value).strip() for value in declared_dates
    } != actual_dates:
        raise DailyPriceSourceError("整合快照 receipt date_keys 與內容不一致")
    if payload.get("row_count") != int(len(actual_frame)):
        raise DailyPriceSourceError("整合快照 receipt row_count 與內容不一致")
