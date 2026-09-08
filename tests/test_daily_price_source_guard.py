from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from app_module.update_service import UpdateService
from data_module.daily_price_source_guard import (
    AGGREGATE_SOURCE_VERSION,
    aggregate_receipt_path,
)


def _config(tmp_path: Path, *, profile: str = "unit") -> SimpleNamespace:
    data_root = tmp_path / "FA_Data"
    meta_dir = data_root / "meta_data"
    daily_dir = data_root / "daily_price"
    tpex_dir = data_root / "daily_price_tpex"
    for directory in (meta_dir, daily_dir, tpex_dir):
        directory.mkdir(parents=True)
    return SimpleNamespace(
        profile=profile,
        data_dir=data_root,
        daily_price_dir=daily_dir,
        tpex_daily_price_dir=tpex_dir,
        meta_data_dir=meta_dir,
        stock_data_file=meta_dir / "stock_data_whole.csv",
        use_sqlite=False,
    )


def _price_rows(code: str, close: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "證券代號": [code],
            "證券名稱": ["測試股票"],
            "開盤價": [close],
            "最高價": [close],
            "最低價": [close],
            "收盤價": [close],
        }
    )


def test_daily_data_prefers_date_file_over_stale_aggregate(tmp_path):
    config = _config(tmp_path)
    pd.DataFrame(
        {"日期": ["20260520"], "證券代號": ["3017"], "收盤價": [726792.0]}
    ).to_csv(config.stock_data_file, index=False, encoding="utf-8-sig")
    _price_rows("3017", 42.0).to_csv(
        config.daily_price_dir / "20260520.csv",
        index=False,
        encoding="utf-8-sig",
    )

    service = UpdateService(config)
    original_loader = service._load_csv_for_sqlite

    def reject_aggregate(path, *args, **kwargs):
        if Path(path).resolve() == config.stock_data_file.resolve():
            raise AssertionError("日期檔存在時不得讀取 stale aggregate")
        return original_loader(path, *args, **kwargs)

    service._load_csv_for_sqlite = reject_aggregate
    loaded = service._load_daily_data_for_sqlite()

    assert loaded[["日期", "證券代號", "收盤價"]].to_dict("records") == [
        {"日期": "20260520", "證券代號": "3017", "收盤價": 42.0}
    ]
    assert service._last_daily_source_selection["source_kind"] == "date_files"
    assert service._last_daily_source_selection["aggregate_is_authoritative"] is True


def test_daily_data_rejects_date_file_mismatch_without_aggregate_fallback(tmp_path):
    config = _config(tmp_path)
    pd.DataFrame(
        {"日期": ["20260520"], "證券代號": ["3017"], "收盤價": [726792.0]}
    ).to_csv(config.stock_data_file, index=False, encoding="utf-8-sig")
    wrong_date = _price_rows("3017", 42.0)
    wrong_date.insert(0, "日期", "20260519")
    wrong_date.to_csv(
        config.daily_price_dir / "20260520.csv",
        index=False,
        encoding="utf-8-sig",
    )

    service = UpdateService(config)
    loaded = service._load_daily_data_for_sqlite()

    assert loaded.empty
    assert service._last_daily_source_selection["reason"] == "daily_price_file_contract_failed"


def test_daily_data_rejects_malformed_date_filename_instead_of_falling_back(tmp_path):
    config = _config(tmp_path)
    pd.DataFrame(
        {"日期": ["20260520"], "證券代號": ["3017"], "收盤價": [726792.0]}
    ).to_csv(config.stock_data_file, index=False, encoding="utf-8-sig")
    _price_rows("3017", 42.0).to_csv(
        config.daily_price_dir / "2026-05-20.csv",
        index=False,
        encoding="utf-8-sig",
    )

    service = UpdateService(config)
    loaded = service._load_daily_data_for_sqlite()

    assert loaded.empty
    assert service._last_daily_source_selection["reason"] == "invalid_daily_price_filename"


def test_prod_aggregate_requires_content_bound_receipt(tmp_path):
    config = _config(tmp_path, profile="prod")
    aggregate = pd.DataFrame(
        {"日期": ["20260520"], "證券代號": ["3017"], "收盤價": [42.0]}
    )
    aggregate.to_csv(config.stock_data_file, index=False, encoding="utf-8-sig")
    file_hash = "sha256:" + hashlib.sha256(config.stock_data_file.read_bytes()).hexdigest()
    aggregate_receipt_path(config.stock_data_file).write_text(
        __import__("json").dumps(
            {
                "schema_version": AGGREGATE_SOURCE_VERSION,
                "source_version": AGGREGATE_SOURCE_VERSION,
                "quality_status": "accepted",
                "source_path": str(config.stock_data_file.resolve()),
                "source_sha256": file_hash,
                "date_keys": ["20260520"],
                "row_count": 1,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    loaded = UpdateService(config)._load_daily_data_for_sqlite()

    assert loaded[["日期", "證券代號", "收盤價"]].to_dict("records") == [
        {"日期": "20260520", "證券代號": "3017", "收盤價": 42.0}
    ]


def test_prod_aggregate_tamper_is_rejected_after_receipt(tmp_path):
    config = _config(tmp_path, profile="prod")
    aggregate = pd.DataFrame(
        {"日期": ["20260520"], "證券代號": ["3017"], "收盤價": [42.0]}
    )
    aggregate.to_csv(config.stock_data_file, index=False, encoding="utf-8-sig")
    file_hash = "sha256:" + hashlib.sha256(config.stock_data_file.read_bytes()).hexdigest()
    aggregate_receipt_path(config.stock_data_file).write_text(
        __import__("json").dumps(
            {
                "schema_version": AGGREGATE_SOURCE_VERSION,
                "source_version": AGGREGATE_SOURCE_VERSION,
                "quality_status": "accepted",
                "source_path": str(config.stock_data_file.resolve()),
                "source_sha256": file_hash,
                "date_keys": ["20260520"],
                "row_count": 1,
            }
        ),
        encoding="utf-8",
    )
    aggregate.assign(收盤價=99.0).to_csv(
        config.stock_data_file, index=False, encoding="utf-8-sig"
    )

    service = UpdateService(config)
    loaded = service._load_daily_data_for_sqlite()

    assert loaded.empty
    assert service._last_daily_source_selection["reason"] == "aggregate_source_contract_failed"


def test_real_daily_writer_rejects_invalid_source_before_writing(tmp_path):
    """真正的 merge writer 入口必須套用檔名／內容日期 guard。"""

    from data_module.daily_price_source_guard import DailyPriceSourceError
    from scripts.merge_daily_data import merge_daily_data

    config = _config(tmp_path)
    _price_rows("3017", 42.0).to_csv(
        config.daily_price_dir / "2026-05-20.csv",
        index=False,
        encoding="utf-8-sig",
    )

    with pytest.raises(DailyPriceSourceError, match="未綁定日期"):
        merge_daily_data(force_all=True, config=config)

    assert not config.stock_data_file.exists()


def test_real_daily_writer_rejects_content_date_mismatch_before_writing(tmp_path):
    """writer 不能以檔名覆蓋 CSV 內的錯誤日期。"""

    from data_module.daily_price_source_guard import DailyPriceSourceError
    from scripts.merge_daily_data import merge_daily_data

    config = _config(tmp_path)
    mismatched = _price_rows("3017", 42.0)
    mismatched.insert(0, "日期", "20260519")
    mismatched.to_csv(
        config.daily_price_dir / "20260520.csv",
        index=False,
        encoding="utf-8-sig",
    )

    with pytest.raises(DailyPriceSourceError, match="內日期與檔名不一致"):
        merge_daily_data(force_all=True, config=config)

    assert not config.stock_data_file.exists()


def test_real_daily_writer_emits_content_bound_receipt(tmp_path):
    """成功 writer 要保存可供 aggregate fallback 驗證的實際內容 receipt。"""

    from scripts.merge_daily_data import merge_daily_data

    config = _config(tmp_path)
    _price_rows("3017", 42.0).to_csv(
        config.daily_price_dir / "20260520.csv",
        index=False,
        encoding="utf-8-sig",
    )

    result = merge_daily_data(force_all=True, config=config)

    assert result["success"] is True
    receipt = aggregate_receipt_path(config.stock_data_file)
    assert Path(result["source_receipt"]) == receipt
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["source_version"] == AGGREGATE_SOURCE_VERSION
    assert payload["quality_status"] == "accepted"
    assert payload["source_sha256"] == (
        "sha256:" + hashlib.sha256(config.stock_data_file.read_bytes()).hexdigest()
    )
    assert payload["date_keys"] == ["20260520"]
    assert payload["row_count"] == 1
