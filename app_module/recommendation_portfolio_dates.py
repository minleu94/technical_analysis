import pandas as pd


def parse_stock_dates(values) -> pd.Series:
    series = pd.Series(values).copy()
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_datetime(series.astype("Int64").astype(str), errors="coerce", format="%Y%m%d")

    text = series.astype(str).str.strip()
    digit_mask = text.str.fullmatch(r"\d{8}", na=False)
    parsed = pd.to_datetime(series, errors="coerce")
    if digit_mask.any():
        parsed.loc[digit_mask] = pd.to_datetime(text.loc[digit_mask], errors="coerce", format="%Y%m%d")
    return parsed
