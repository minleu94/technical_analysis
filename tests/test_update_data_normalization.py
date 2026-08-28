from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app_module.update_service import UpdateService
from app_module.update_data_normalization import (
    date_key,
    iter_weekday_date_keys,
    normalize_sqlite_dates,
    sqlite_csv_dtype,
    stock_code_key,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        (float("nan"), ""),
        ("20260709", "20260709"),
        ("20260709.0", "20260709"),
        ("2026/7/9", "20260709"),
        ("115/07/09", "20260709"),
        (date(2026, 7, 9), "20260709"),
        ("not-a-date", "notadate"),
    ],
)
def test_date_key_preserves_current_input_output_matrix(value, expected):
    assert date_key(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        (float("nan"), ""),
        (50, "0050"),
        (50.0, "0050"),
        ("0050", "0050"),
        (" 2330.0 ", "2330"),
        ("ABCDE", "ABCDE"),
    ],
)
def test_stock_code_key_preserves_zero_padding_and_dot_zero_behavior(value, expected):
    assert stock_code_key(value) == expected


def test_iter_weekday_date_keys_is_inclusive_and_excludes_weekends():
    assert iter_weekday_date_keys("2026-07-03", "2026-07-06") == ["20260703", "20260706"]


def test_iter_weekday_date_keys_rejects_reverse_ranges():
    with pytest.raises(ValueError, match="start_date must be <= end_date"):
        iter_weekday_date_keys("2026-07-06", "2026-07-03")


def test_sqlite_csv_dtype_contract_remains_exact():
    assert sqlite_csv_dtype() == {
        "日期": str,
        "證券代號": str,
        "股票代號": str,
        "stock_code": str,
        "stock_id": str,
        "date": str,
    }


def test_normalize_sqlite_dates_preserves_columns_order_and_unrelated_values():
    source = pd.DataFrame(
        {
            "日期": ["2026/7/9", "115/07/10", None],
            "證券代號": [50.0, "2330.0", None],
            "證券名稱": ["元大台灣50", "台積電", "缺值"],
            "自訂欄": [1, 2, 3],
        }
    )

    normalized = normalize_sqlite_dates(source)

    assert normalized is not source
    assert list(normalized.columns) == list(source.columns)
    assert normalized["日期"].tolist() == ["20260709", "20260710", ""]
    assert normalized["證券代號"].tolist() == ["0050", "2330", ""]
    assert normalized["證券名稱"].tolist() == source["證券名稱"].tolist()
    assert normalized["自訂欄"].tolist() == [1, 2, 3]
    assert source["日期"].tolist() == ["2026/7/9", "115/07/10", None]


def test_normalize_sqlite_dates_without_date_column_returns_original_frame():
    source = pd.DataFrame({"證券代號": [50], "自訂欄": [1]})

    assert normalize_sqlite_dates(source) is source


def test_normalize_sqlite_dates_maps_code_and_name_aliases_without_date_column():
    source = pd.DataFrame({"stock_code": [50.0], "stock_name": ["元大台灣50"]})

    normalized = normalize_sqlite_dates(source)

    assert normalized.to_dict(orient="records") == [
        {"證券代號": "0050", "證券名稱": "元大台灣50"}
    ]
    assert list(source.columns) == ["stock_code", "stock_name"]


def test_normalize_sqlite_dates_maps_declared_english_aliases():
    source = pd.DataFrame(
        {
            "date": ["2026-07-09"],
            "stock_code": [50.0],
            "stock_name": ["元大台灣50"],
            "value": [1],
        }
    )

    normalized = normalize_sqlite_dates(source)

    assert list(normalized.columns) == ["日期", "證券代號", "證券名稱", "value"]
    assert normalized.to_dict(orient="records") == [
        {
            "日期": "20260709",
            "證券代號": "0050",
            "證券名稱": "元大台灣50",
            "value": 1,
        }
    ]
    assert list(source.columns) == ["date", "stock_code", "stock_name", "value"]


def test_update_service_wrappers_preserve_overridden_private_normalizers():
    service = UpdateService.__new__(UpdateService)
    service._date_key = lambda value: {"start": "20260703", "end": "20260706"}.get(
        value, f"date:{value}"
    )
    service._stock_code_key = lambda value: f"code:{value}"

    assert service._iter_weekday_date_keys("start", "end") == ["20260703", "20260706"]

    source = pd.DataFrame({"日期": ["raw-date"], "證券代號": ["raw-code"]})
    normalized = service._normalize_sqlite_dates(source)

    assert normalized.to_dict(orient="records") == [
        {"日期": "date:raw-date", "證券代號": "code:raw-code"}
    ]
