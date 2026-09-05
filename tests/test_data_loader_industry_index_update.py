from __future__ import annotations

from pathlib import Path

import pandas as pd

from data_module.config import TWStockConfig
from data_module.data_loader import DataLoader


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def json(self) -> dict:
        return self.payload


def _industry_response(names: list[str]) -> dict:
    return {
        "stat": "OK",
        "tables": [
            {
                "title": "類股指數",
                "rows": [[name, "100", "+", "1", "1"] for name in names],
            }
        ],
    }


def _make_loader(tmp_path: Path, names: list[str]) -> DataLoader:
    config = TWStockConfig(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
    )
    existing = pd.DataFrame(
        [
            {
                "指數名稱": "電子類指數",
                "收盤指數": 90,
                "漲跌": "+",
                "漲跌點數": 1,
                "漲跌百分比": 1,
                "日期": "2026-05-11",
            },
            {
                "指數名稱": "觀光類指數",
                "收盤指數": 90,
                "漲跌": "+",
                "漲跌點數": 1,
                "漲跌百分比": 1,
                "日期": "2026-05-11",
            },
            {
                "指數名稱": "電子工業類指數",
                "收盤指數": 99,
                "漲跌": "+",
                "漲跌點數": 1,
                "漲跌百分比": 1,
                "日期": "2026-09-02",
            },
            {
                "指數名稱": "觀光餐旅類指數",
                "收盤指數": 99,
                "漲跌": "+",
                "漲跌點數": 1,
                "漲跌百分比": 1,
                "日期": "2026-09-02",
            },
        ]
    )
    existing.to_csv(config.industry_index_file, index=False, encoding="utf-8-sig")
    loader = DataLoader(config)
    loader._make_request = lambda *_args, **_kwargs: _FakeResponse(  # type: ignore[method-assign]
        _industry_response(names)
    )
    return loader


def test_historical_retired_industry_names_do_not_trigger_warning(tmp_path, caplog):
    loader = _make_loader(
        tmp_path,
        ["電子工業類指數", "觀光餐旅類指數"],
    )

    with caplog.at_level("WARNING"):
        assert loader.update_industry_index("2026-09-03", skip_backup=True)

    assert not any("新數據缺少" in record.message for record in caplog.records)


def test_currently_missing_industry_name_still_warns_and_preserves_current_row(tmp_path, caplog):
    loader = _make_loader(tmp_path, ["電子工業類指數"])

    existing_current = pd.read_csv(loader.config.industry_index_file, encoding="utf-8-sig")
    existing_current = pd.concat(
        [
            existing_current,
            pd.DataFrame(
                [
                    {
                        "指數名稱": "觀光餐旅類指數",
                        "收盤指數": 101,
                        "漲跌": "+",
                        "漲跌點數": 1,
                        "漲跌百分比": 1,
                        "日期": "2026-09-03",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    existing_current.to_csv(loader.config.industry_index_file, index=False, encoding="utf-8-sig")

    with caplog.at_level("WARNING"):
        assert loader.update_industry_index("2026-09-03", skip_backup=True)

    assert any("新數據缺少 1 個指數" in record.message for record in caplog.records)
    updated = pd.read_csv(loader.config.industry_index_file, encoding="utf-8-sig")
    preserved = updated[
        (updated["日期"] == "2026-09-03")
        & (updated["指數名稱"] == "觀光餐旅類指數")
    ]
    assert len(preserved) == 1
