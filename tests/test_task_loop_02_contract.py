"""TASK-LOOP-02 市場閉環契約測試。

所有 fixture 都在記憶體中建立；測試不得連線正式資料庫或寫入正式輸出。
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd

from app_module.market_breadth_service import MarketBreadthService
from app_module.relative_strength_liquidity_service import RelativeStrengthLiquidityService
from app_module.regime_service import RegimeService
from app_module.screening_service import ScreeningService
from app_module.sector_rotation_service import SectorRotationService
from decision_module.stock_screener import StockScreener


DECISION_DATE = date(2026, 1, 21)


def test_breadth_dto_freezes_decision_date_and_rejects_future_only() -> None:
    base = pd.DataFrame(
        [
            {"as_of_date": "2026-01-21", "advancing": 7, "declining": 3, "unchanged": 1, "source": "fixture"}
        ]
    )
    service = MarketBreadthService(data=base)
    first = service.build_snapshot_dto(DECISION_DATE)
    appended = pd.concat(
        [base, pd.DataFrame([{"as_of_date": "2026-01-22", "advancing": 1, "declining": 9, "unchanged": 0}])],
        ignore_index=True,
    )
    second = MarketBreadthService(data=appended).build_snapshot_dto(DECISION_DATE)

    assert first.to_dict() == second.to_dict()
    assert first.decision_date == DECISION_DATE
    assert first.effective_date == DECISION_DATE
    assert first.quality == "observed"
    assert first.source_id == "fixture"

    future_only = MarketBreadthService(
        data=pd.DataFrame([{"as_of_date": "2026-01-22", "advancing": 9, "declining": 1}])
    ).build_snapshot_dto(DECISION_DATE)
    assert future_only.quality == "missing"
    assert "market_breadth_missing" in future_only.warnings


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


def test_sector_rotation_future_append_keeps_ranking_and_exposes_bp() -> None:
    first = SectorRotationService(data=_sector_frame()).build_snapshot_dto(DECISION_DATE)
    second = SectorRotationService(data=_sector_frame(include_future=True)).build_snapshot_dto(DECISION_DATE)

    assert first.ranking == second.ranking
    assert first.leading_sector == "電子"
    assert first.effective_date == DECISION_DATE
    assert first.rotation_intensity_bp is not None
    assert first.quality == "observed"


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


def test_relative_strength_future_append_keeps_codes_and_quality() -> None:
    state = {"frame": _relative_frame()}

    class Provider:
        def fetch(self, _as_of: date) -> pd.DataFrame:
            return state["frame"]

    service = RelativeStrengthLiquidityService(Provider(), top_n=2, min_avg_turnover=1)
    first = service.build_snapshot_dto(DECISION_DATE)
    state["frame"] = _relative_frame(include_future=True)
    second = service.build_snapshot_dto(DECISION_DATE)

    assert first.to_dict() == second.to_dict()
    assert first.top_strength_codes == ("1101", "1102")
    assert first.effective_date == DECISION_DATE
    assert first.quality == "observed"


def test_regime_dto_passes_frozen_date_and_does_not_call_match_a_win_rate() -> None:
    calls: list[str | None] = []

    class FakeDetector:
        def detect_regime(self, date: str | None = None):
            calls.append(date)
            return {
                "regime": "Trend",
                "confidence": "0.875",
                "details": {"date": date, "match_score": "0.875"},
            }

        def get_strategy_config(self, regime: str):
            return {"regime": regime}

    service = RegimeService(SimpleNamespace(), regime_detector=FakeDetector())
    result = service.detect_regime_dto(as_of_date=DECISION_DATE)

    assert calls == ["2026-01-21"]
    assert result.effective_date == DECISION_DATE
    assert result.match_score_bp == 8750
    assert result.to_dict()["match_score_bp"] == 8750
    assert "勝率" not in result.to_dict()


def _screening_frame(include_future: bool = False) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = ["20260120", "20260121"]
    if include_future:
        dates.append("20260122")
    prices = {"1101": [10, 11, 30], "1102": [10, 12, 5], "1103": [10, 11, 11]}
    for date_index, current_date in enumerate(dates):
        for code, values in prices.items():
            rows.append(
                {
                    "日期": current_date,
                    "證券代號": code,
                    "證券名稱": f"測試{code}",
                    "收盤價": values[date_index],
                    "開盤價": values[date_index],
                    "最高價": values[date_index],
                    "最低價": values[date_index],
                    "成交股數": 100000,
                    "成交金額": values[date_index] * 100000,
                }
            )
    return pd.DataFrame(rows)


def test_screening_dto_freezes_universe_and_roundtrips_legacy_tuple() -> None:
    state = {"frame": _screening_frame()}

    def provider(_period: str, _lookback: int) -> pd.DataFrame:
        return state["frame"]

    class Mapper:
        def get_stock_industries(self, _code: str):
            return []

        def get_industry_performance(self, _name: str):
            return {}

    mapper = Mapper()
    screener = StockScreener(SimpleNamespace(), mapper, recent_stock_provider=provider)
    service = ScreeningService(SimpleNamespace(), industry_mapper=mapper, stock_screener=screener)
    first = service.get_strong_stocks_dto(decision_date=DECISION_DATE, top_n=3)
    state["frame"] = _screening_frame(include_future=True)
    second = service.get_strong_stocks_dto(decision_date=DECISION_DATE, top_n=3)

    assert first.to_dict() == second.to_dict()
    assert first.quality == "observed"
    assert first.effective_date == DECISION_DATE
    assert first.eligible_universe_size == 3
    legacy_frame, legacy_universe = first.to_legacy()
    assert isinstance(legacy_frame, pd.DataFrame)
    assert legacy_universe == 3
    assert list(legacy_frame["證券代號"]) == list(first.to_dataframe()["證券代號"])


def test_screening_fallback_date_is_degraded_and_has_no_zero_fill() -> None:
    frame = _screening_frame().loc[lambda value: value["日期"] == "20260120"].copy()

    def provider(_period: str, _lookback: int) -> pd.DataFrame:
        return frame

    mapper = SimpleNamespace(get_stock_industries=lambda _code: [], get_industry_performance=lambda _name: {})
    screener = StockScreener(SimpleNamespace(), mapper, recent_stock_provider=provider)
    service = ScreeningService(SimpleNamespace(), industry_mapper=mapper, stock_screener=screener)
    result = service.get_strong_stocks_dto(decision_date=DECISION_DATE)

    assert result.quality == "degraded"
    assert result.effective_date == date(2026, 1, 20)
    assert result.eligible_universe_size == 0
    assert any(item.startswith("screening_as_of_fallback:") for item in result.warnings)
