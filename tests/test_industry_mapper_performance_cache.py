from types import SimpleNamespace

import pandas as pd

from decision_module.industry_mapper import IndustryMapper


def test_industry_mapper_uses_latest_performance_cache_without_rescanning_frame(tmp_path):
    meta_data_dir = tmp_path / "meta_data"
    meta_data_dir.mkdir()
    companies_file = meta_data_dir / "companies.csv"
    industry_file = tmp_path / "industry_index.csv"

    pd.DataFrame(
        [
            {"stock_id": "2330", "industry_category": "半導體業"},
            {"stock_id": "2454", "industry_category": "半導體業"},
        ]
    ).to_csv(companies_file, index=False, encoding="utf-8-sig")
    pd.DataFrame(
        [
            {"日期": "2026-06-29", "指數名稱": "半導體類指數", "收盤指數": 100, "漲跌百分比": 1.2},
            {"日期": "2026-06-30", "指數名稱": "半導體類指數", "收盤指數": 105, "漲跌百分比": 2.5},
        ]
    ).to_csv(industry_file, index=False, encoding="utf-8-sig")

    config = SimpleNamespace(
        use_sqlite=False,
        meta_data_dir=meta_data_dir,
        industry_index_file=industry_file,
    )
    mapper = IndustryMapper(config)

    mapper.industry_index_df = pd.DataFrame()
    performance = mapper.get_industry_performance("半導體業")

    assert performance is not None
    assert performance["指數名稱"] == "半導體類指數"
    assert performance["收盤指數"] == 105
    assert performance["漲跌百分比"] == 2.5
