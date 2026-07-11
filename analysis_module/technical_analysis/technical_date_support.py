from datetime import datetime

import pandas as pd


def safe_convert_technical_dates(series):
    """將日期序列轉換為 YYYY-MM-DD 格式，保留既有解析語意。"""
    s = series.copy()
    s = s.astype(str).str.replace(r"\.0$", "", regex=True)

    def parse_single_date(val):
        if not val or val == "nan" or val == "NaT" or val == "None":
            return None
        val = val.strip()
        if len(val) == 8 and val.isdigit():
            try:
                return datetime.strptime(val, "%Y%m%d").strftime("%Y-%m-%d")
            except:
                pass
        normalized = val.replace("/", "-")
        if len(normalized) >= 10:
            try:
                return datetime.strptime(normalized[:10], "%Y-%m-%d").strftime(
                    "%Y-%m-%d"
                )
            except:
                pass
        try:
            parsed = pd.to_datetime(val, errors="coerce")
            if pd.notna(parsed):
                return parsed.strftime("%Y-%m-%d")
        except:
            pass
        return None

    return s.apply(parse_single_date)
