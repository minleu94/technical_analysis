from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd

from decision_module.industry_mapper import IndustryMapper


def test_industry_mapper_uses_injected_industry_index_provider(tmp_path) -> None:
    provider = MagicMock(
        return_value=pd.DataFrame(
            {
                "日期": ["20260710"],
                "指數名稱": ["半導體類指數"],
                "收盤指數": [100],
            }
        )
    )
    config = SimpleNamespace(
        meta_data_dir=tmp_path,
        industry_index_file=tmp_path / "missing.csv",
        use_sqlite=True,
    )

    mapper = IndustryMapper(config, industry_index_provider=provider)

    provider.assert_called_once_with()
    assert mapper.industry_index_df is not None
    assert str(mapper.industry_index_df["日期"].dtype).startswith("datetime64")


def test_industry_mapper_preserves_iso_dates_from_provider_csv_fallback(tmp_path) -> None:
    provider = MagicMock(
        return_value=pd.DataFrame(
            {
                "日期": ["2026-07-10"],
                "指數名稱": ["半導體類指數"],
                "收盤指數": [100],
            }
        )
    )
    config = SimpleNamespace(
        meta_data_dir=tmp_path,
        industry_index_file=tmp_path / "missing.csv",
        use_sqlite=True,
    )

    mapper = IndustryMapper(config, industry_index_provider=provider)

    assert mapper.industry_index_df is not None
    assert mapper.industry_index_df["日期"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-07-10"
    ]
