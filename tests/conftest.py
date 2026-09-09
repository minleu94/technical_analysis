import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


pytest_plugins = (
    "tests.fixtures.portfolio_ml_ooc_support",
    "tests.fixtures.ml_allocation_training_support",
)


@pytest.fixture(autouse=True)
def isolate_installed_formal_runtime_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Keep unit fixtures independent from the deployed candidate binding.

    The real Task Scheduler process must read the repository's active binding;
    pytest fixtures intentionally exercise temporary configs and must not
    inherit that production v6 map.  Tests that specifically validate binding
    loading set ``FORMAL_DAILY_RUNTIME_ENVIRONMENT_FILE`` to their own path.
    """

    from data_module import formal_runtime_config

    monkeypatch.setattr(
        formal_runtime_config,
        "DEFAULT_RUNTIME_ENVIRONMENT_FILE",
        tmp_path / "no-installed-runtime-binding.json",
    )
    monkeypatch.delenv("FORMAL_DAILY_RUNTIME_ENVIRONMENT_FILE", raising=False)


@pytest.fixture
def isolated_formal_runtime_subprocess_env(tmp_path: Path) -> dict[str, str]:
    """Give runtime-loading subprocess tests an explicit fail-closed binding.

    A subprocess does not see the module-level monkeypatch above.  Pointing it
    at a unique, missing path under repository ``output`` prevents a test
    process from accidentally loading the active deployed binding while still
    exercising the production path validation rules.
    """

    repository_root = Path(__file__).resolve().parents[1]
    isolated_binding = (
        repository_root
        / "output"
        / "v4_next_formal"
        / f".missing-subprocess-binding-{tmp_path.name[-8:]}.json"
    )
    environment = os.environ.copy()
    for name in (
        "FORMAL_DAILY_RUNTIME_CONFIG",
        "FORMAL_DAILY_RUNTIME_CONFIG_ROOT",
        "FORMAL_DAILY_ROLLING_CALENDAR_BUNDLE",
        "FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST",
    ):
        environment.pop(name, None)
    environment["FORMAL_DAILY_RUNTIME_ENVIRONMENT_FILE"] = str(isolated_binding)
    return environment


@pytest.fixture(scope="session")
def sample_market_data() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", "2024-01-10")
    close = np.arange(100, 110, dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "open": close - 1,
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "volume": np.arange(1_000_000, 1_000_010, dtype=np.int64),
        }
    )


@pytest.fixture(scope="session")
def sample_stock_data() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", "2024-01-10")
    rows = []
    for stock_index, stock_id in enumerate(("2330", "2317", "2412")):
        for day_index, date in enumerate(dates):
            close = float(100 + stock_index * 20 + day_index)
            rows.append(
                {
                    "date": date,
                    "stock_id": stock_id,
                    "open": close - 1,
                    "high": close + 2,
                    "low": close - 2,
                    "close": close,
                    "volume": 1_000_000 + stock_index * 10_000 + day_index,
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture(scope="session")
def sample_index_data() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", "2024-01-10")
    rows = []
    for index_name in ["半導體", "電子", "金融"]:
        for day_index, date in enumerate(dates):
            rows.append(
                {
                    "date": date,
                    "index_name": index_name,
                    "value": 1_000 + day_index,
                    "change": day_index,
                    "change_pct": day_index / 100,
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
