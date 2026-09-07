"""TASK-LOOP-02 市場閉環隔離驗收入口。

此腳本只使用記憶體 DataFrame 與 TemporaryDirectory，明確禁止正式資料、網路、
SQLite 寫入及外部來源。exit code 只有在所有強制案例通過時才為 0。
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app_module.market_breadth_service import MarketBreadthService  # noqa: E402
from app_module.relative_strength_liquidity_service import RelativeStrengthLiquidityService  # noqa: E402
from app_module.regime_service import RegimeService  # noqa: E402
from app_module.screening_service import ScreeningService  # noqa: E402
from app_module.sector_rotation_service import SectorRotationService  # noqa: E402
from decision_module.stock_screener import StockScreener  # noqa: E402


DECISION_DATE = date(2026, 1, 21)


class _RelativeProvider:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame

    def fetch(self, _as_of_date: date) -> pd.DataFrame:
        return self.frame


class _ScreeningMapper:
    def get_stock_industries(self, _stock_code: str):
        return []

    def get_industry_performance(self, _industry_name: str):
        return {}


def _sector_frame(include_future: bool = False) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = [date(2026, 1, 1) + timedelta(days=index) for index in range(21)]
    if include_future:
        dates.append(date(2026, 1, 22))
    for current_date in dates:
        offset = (current_date - date(2026, 1, 1)).days
        rows.extend(
            [
                {"日期": current_date, "指數名稱": "電子", "收盤指數": 100 + offset * 2},
                {"日期": current_date, "指數名稱": "金融", "收盤指數": 100 + offset},
            ]
        )
    return pd.DataFrame(rows)


def _relative_frame(include_future: bool = False) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = [date(2025, 12, 31) + timedelta(days=index) for index in range(22)]
    if include_future:
        dates.append(date(2026, 1, 23))
    for index, current_date in enumerate(dates):
        rows.extend(
            [
                {"日期": current_date, "證券代號": "1101", "收盤價": 100 + index, "成交股數": 300000},
                {"日期": current_date, "證券代號": "1102", "收盤價": 100 + index // 2, "成交股數": 300000},
            ]
        )
    return pd.DataFrame(rows)


def _stock_frame(include_future: bool = False) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = ["20260120", "20260121"]
    if include_future:
        dates.append("20260122")
    prices = {"1101": [10, 11, 30], "1102": [10, 12, 5], "1103": [10, 11, 11]}
    for date_index, current_date in enumerate(dates):
        for code, values in prices.items():
            price = values[date_index]
            rows.append(
                {
                    "日期": current_date,
                    "證券代號": code,
                    "證券名稱": f"測試{code}",
                    "收盤價": price,
                    "開盤價": price,
                    "最高價": price,
                    "最低價": price,
                    "成交股數": 100000,
                    "成交金額": price * 100000,
                }
            )
    return pd.DataFrame(rows)


def _check_dto_and_future_append() -> None:
    breadth_base = pd.DataFrame(
        [{"as_of_date": "2026-01-21", "advancing": 7, "declining": 3, "unchanged": 1, "source": "qa"}]
    )
    breadth_one = MarketBreadthService(data=breadth_base).build_snapshot_dto(DECISION_DATE)
    breadth_two = MarketBreadthService(
        data=pd.concat(
            [breadth_base, pd.DataFrame([{"as_of_date": "2026-01-22", "advancing": 1, "declining": 9}])],
            ignore_index=True,
        )
    ).build_snapshot_dto(DECISION_DATE)
    assert breadth_one.to_dict() == breadth_two.to_dict()
    assert breadth_one.quality == "observed"
    assert breadth_one.source_id == "qa"

    sector_one = SectorRotationService(data=_sector_frame()).build_snapshot_dto(DECISION_DATE)
    sector_two = SectorRotationService(data=_sector_frame(True)).build_snapshot_dto(DECISION_DATE)
    assert sector_one.to_dict() == sector_two.to_dict()
    assert sector_one.leading_sector == "電子"
    assert sector_one.rotation_intensity_bp is not None

    relative_provider = _RelativeProvider(_relative_frame())
    relative_one = RelativeStrengthLiquidityService(
        relative_provider, top_n=2, min_avg_turnover=1
    ).build_snapshot_dto(DECISION_DATE)
    relative_provider.frame = _relative_frame(True)
    relative_two = RelativeStrengthLiquidityService(
        relative_provider, top_n=2, min_avg_turnover=1
    ).build_snapshot_dto(DECISION_DATE)
    assert relative_one.to_dict() == relative_two.to_dict()
    assert relative_one.top_strength_codes == ("1101", "1102")

    state = {"frame": _stock_frame()}

    def stock_provider(_period: str, _lookback: int) -> pd.DataFrame:
        return state["frame"]

    mapper = _ScreeningMapper()
    screener = StockScreener(SimpleNamespace(), mapper, recent_stock_provider=stock_provider)
    screening = ScreeningService(SimpleNamespace(), industry_mapper=mapper, stock_screener=screener)
    screening_one = screening.get_strong_stocks_dto(decision_date=DECISION_DATE, top_n=3)
    state["frame"] = _stock_frame(True)
    screening_two = screening.get_strong_stocks_dto(decision_date=DECISION_DATE, top_n=3)
    assert screening_one.to_dict() == screening_two.to_dict()
    assert screening_one.eligible_universe_size == 3
    legacy_frame, legacy_universe = screening_one.to_legacy()
    assert isinstance(legacy_frame, pd.DataFrame)
    assert legacy_universe == 3


def _check_failure_modes() -> None:
    future_only = MarketBreadthService(
        data=pd.DataFrame([{"as_of_date": "2026-01-22", "advancing": 1, "declining": 1}])
    ).build_snapshot_dto(DECISION_DATE)
    assert future_only.quality == "missing"
    assert future_only.advancing is None

    prior_stock_frame = _stock_frame().loc[lambda frame: frame["日期"] == "20260120"].copy()

    def prior_provider(_period: str, _lookback: int) -> pd.DataFrame:
        return prior_stock_frame

    mapper = _ScreeningMapper()
    screener = StockScreener(SimpleNamespace(), mapper, recent_stock_provider=prior_provider)
    screening = ScreeningService(SimpleNamespace(), industry_mapper=mapper, stock_screener=screener)
    fallback = screening.get_strong_stocks_dto(decision_date=DECISION_DATE)
    assert fallback.quality == "degraded"
    assert fallback.effective_date == date(2026, 1, 20)
    assert fallback.eligible_universe_size == 0
    assert any(item.startswith("screening_as_of_fallback:") for item in fallback.warnings)


def _check_regime_boundary() -> None:
    class Detector:
        def detect_regime(self, date: str | None = None):
            return {"regime": "Trend", "confidence": "0.875", "details": {"date": date}}

        def get_strategy_config(self, regime: str):
            return {"regime": regime}

    result = RegimeService(SimpleNamespace(), regime_detector=Detector()).detect_regime_dto(
        as_of_date=DECISION_DATE
    )
    assert result.effective_date == DECISION_DATE
    assert result.match_score_bp == 8750
    assert "勝率" not in result.to_dict()


def _check_ui_boundary() -> None:
    view_paths = (
        "ui_qt/views/market_regime_view.py",
        "ui_qt/views/strong_stocks_view.py",
        "ui_qt/views/weak_stocks_view.py",
        "ui_qt/views/strong_industries_view.py",
        "ui_qt/views/weak_industries_view.py",
    )
    forbidden = ("import sqlite3", "DBManager", "read_csv", "read_sql")
    for relative_path in view_paths:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert not any(token in text for token in forbidden), relative_path


def main() -> int:
    checks = (
        ("dto_future_append", _check_dto_and_future_append),
        ("missing_and_fallback", _check_failure_modes),
        ("regime_boundary", _check_regime_boundary),
        ("ui_storage_boundary", _check_ui_boundary),
    )
    failures: list[str] = []
    with TemporaryDirectory(prefix="task_loop_02_market_") as isolated_root:
        isolated_path = Path(isolated_root)
        (isolated_path / "fixture_manifest.txt").write_text(
            "TASK-LOOP-02 isolated fixture; formal data and network are forbidden.\n",
            encoding="utf-8",
        )
        for name, check in checks:
            try:
                check()
                print(f"PASS {name}")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{name}: {type(exc).__name__}: {exc}")
                print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    if failures:
        print("TASK-LOOP-02 QA FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("TASK-LOOP-02 QA PASSED: isolated fixtures only; no formal data touched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

