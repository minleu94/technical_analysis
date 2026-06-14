import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope="session")
def sample_market_data() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", "2024-01-10")
    return pd.DataFrame(
        {
            "date": dates,
            "open": np.random.normal(100, 10, len(dates)),
            "high": np.random.normal(105, 10, len(dates)),
            "low": np.random.normal(95, 10, len(dates)),
            "close": np.random.normal(102, 10, len(dates)),
            "volume": np.random.randint(1_000_000, 2_000_000, len(dates)),
        }
    )


@pytest.fixture(scope="session")
def sample_stock_data() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", "2024-01-10")
    rows = []
    for stock_id in ["2330", "2317", "2412"]:
        for date in dates:
            rows.append(
                {
                    "date": date,
                    "stock_id": stock_id,
                    "open": np.random.normal(100, 10),
                    "high": np.random.normal(105, 10),
                    "low": np.random.normal(95, 10),
                    "close": np.random.normal(102, 10),
                    "volume": np.random.randint(1_000_000, 2_000_000),
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture(scope="session")
def sample_index_data() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", "2024-01-10")
    rows = []
    for index_name in ["半導體", "電子", "金融"]:
        for date in dates:
            rows.append(
                {
                    "date": date,
                    "index_name": index_name,
                    "value": np.random.normal(1_000, 100),
                    "change": np.random.normal(0, 10),
                    "change_pct": np.random.normal(0, 1),
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture
def test_config(tmp_path):
    from data_module.config import TWStockConfig

    return TWStockConfig(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        profile="prod",
    )
