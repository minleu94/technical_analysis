from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd

from app_module.decision_data_providers import SqliteFirstFrameProvider


def test_sqlite_first_provider_returns_query_snapshot_without_csv_access(tmp_path) -> None:
    expected = pd.DataFrame({"日期": [20260710], "收盤指數": [100]})
    db = MagicMock()
    db.execute_query.return_value = expected
    provider = SqliteFirstFrameProvider(
        SimpleNamespace(use_sqlite=True),
        table="market_indices",
        csv_paths=lambda _: (tmp_path / "must-not-exist.csv",),
        db_factory=MagicMock(return_value=db),
    )

    actual = provider()

    pd.testing.assert_frame_equal(actual, expected)
    assert actual is not expected
    db.execute_query.assert_called_once_with(
        "SELECT * FROM market_indices ORDER BY 日期 ASC;"
    )


def test_sqlite_first_provider_falls_back_to_first_existing_csv(tmp_path) -> None:
    fallback = tmp_path / "market.csv"
    pd.DataFrame({"日期": ["2026-07-10"], "收盤價": [100]}).to_csv(
        fallback, index=False, encoding="utf-8-sig"
    )
    db_factory = MagicMock(side_effect=RuntimeError("offline"))
    provider = SqliteFirstFrameProvider(
        SimpleNamespace(use_sqlite=True),
        table="market_indices",
        csv_paths=lambda _: (tmp_path / "missing.csv", fallback),
        db_factory=db_factory,
    )

    actual = provider()

    assert actual.to_dict("records") == [{"日期": "2026-07-10", "收盤價": 100}]
