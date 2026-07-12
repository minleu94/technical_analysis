"""Decision market-frame 的 canonical schema normalization。"""

import pandas as pd


def normalize_market_dates(values: pd.Series) -> pd.Series:
    """同時接受 YYYYMMDD 與 ISO 日期，不以未來資料補值。"""
    text = values.astype(str).str.strip()
    compact = text.str.replace("-", "", regex=False).str.replace("/", "", regex=False)
    compact_dates = pd.to_datetime(compact, format="%Y%m%d", errors="coerce")
    flexible_dates = pd.to_datetime(text, errors="coerce")
    return compact_dates.fillna(flexible_dates)


def normalize_market_index_frame(source: pd.DataFrame) -> pd.DataFrame:
    """統一 SQLite／CSV／injected market index frame 欄位。"""
    frame = source.copy()
    if "日期" in frame.columns:
        frame["日期"] = normalize_market_dates(frame["日期"])
    if "收盤價" not in frame.columns and "收盤指數" in frame.columns:
        frame = frame.rename(columns={"收盤指數": "收盤價"})
    return frame.loc[:, ~frame.columns.duplicated()]
