from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pytest

from app_module.decision_desk_dtos import (
    DecisionDeskQuality,
    MarketBreadthSummary,
    MarketRegimeSummary,
    PortfolioAlertSummary,
    RelativeStrengthLiquiditySummary,
    SectorRotationSummary,
    WatchlistTriggerSummary,
)
from data_module.config import TWStockConfig


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "data" / "sqlite" / "twstock.db"
    config.db_file.parent.mkdir(parents=True, exist_ok=True)
    return config


class _FakeProvider:
    def __init__(self, *_args, **_kwargs) -> None:
        pass


class _FakeRegimeResult:
    regime = "Trend"
    regime_name_cn = "趨勢"
    confidence = 0.75
    details = {"score": 1.2}


class _FakeRegimeService:
    def __init__(self, config: TWStockConfig) -> None:
        self.config = config

    def detect_regime(self, date: str | None = None, as_of_date: str | None = None):
        assert date == "2026-07-03" or as_of_date == "2026-07-03"
        return _FakeRegimeResult()


class _FakeMarketBreadthService:
    def __init__(self, provider: object) -> None:
        self.provider = provider

    def build_snapshot(self, as_of_date: date) -> MarketBreadthSummary:
        return MarketBreadthSummary(
            as_of_date=as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            breadth_ratio_bp=6400,
            advancing=64,
            declining=36,
            unchanged=0,
        )


class _FakeSectorRotationService:
    def __init__(self, provider: object) -> None:
        self.provider = provider

    def build_snapshot(self, as_of_date: date) -> SectorRotationSummary:
        return SectorRotationSummary(
            as_of_date=as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            leading_sector="半導體",
            trailing_sector="航運",
            rotation_intensity_bp=1200,
        )


class _FakeRelativeStrengthLiquidityService:
    def __init__(self, provider: object) -> None:
        self.provider = provider

    def build_snapshot(self, as_of_date: date) -> RelativeStrengthLiquiditySummary:
        return RelativeStrengthLiquiditySummary(
            as_of_date=as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            top_strength_codes=("2330",),
            weak_strength_codes=("2603",),
        )


class _FakeWatchlistService:
    def __init__(self, config: TWStockConfig) -> None:
        self.config = config


class _FakeWatchlistTriggerService:
    def __init__(self, watchlist_provider: object, ranking_provider: object) -> None:
        self.watchlist_provider = watchlist_provider
        self.ranking_provider = ranking_provider

    def build_snapshot(self, as_of_date: date) -> WatchlistTriggerSummary:
        return WatchlistTriggerSummary(
            as_of_date=as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            trigger_count=1,
            triggered_codes=("2330",),
        )


class _FakePortfolioService:
    def __init__(self, config: TWStockConfig) -> None:
        self.config = config


class _FakePortfolioAlertService:
    def __init__(self, portfolio_service: object, condition_monitor: object, chip_summary_provider: object | None = None) -> None:
        self.portfolio_service = portfolio_service
        self.condition_monitor = condition_monitor
        self.chip_summary_provider = chip_summary_provider

    def build_snapshot(self, as_of_date: date) -> PortfolioAlertSummary:
        return PortfolioAlertSummary(
            as_of_date=as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            alert_count=0,
            alert_codes=(),
            alert_level="low",
        )


def test_service_backed_builder_factory_wires_non_ui_decision_desk_services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app_module import decision_desk_builder_factory as factory

    monkeypatch.setattr(factory, "RegimeService", _FakeRegimeService)
    monkeypatch.setattr(factory, "MarketBreadthService", _FakeMarketBreadthService)
    monkeypatch.setattr(factory, "SQLiteDailyPriceMarketBreadthProvider", _FakeProvider)
    monkeypatch.setattr(factory, "SectorRotationService", _FakeSectorRotationService)
    monkeypatch.setattr(factory, "SQLiteIndustryIndexSectorRotationProvider", _FakeProvider)
    monkeypatch.setattr(factory, "RelativeStrengthLiquidityService", _FakeRelativeStrengthLiquidityService)
    monkeypatch.setattr(factory, "SQLiteDailyPriceRelativeStrengthLiquidityProvider", _FakeProvider)
    monkeypatch.setattr(factory, "WatchlistService", _FakeWatchlistService)
    monkeypatch.setattr(factory, "WatchlistTriggerService", _FakeWatchlistTriggerService)
    monkeypatch.setattr(factory, "WatchlistServiceWatchlistProvider", _FakeProvider)
    monkeypatch.setattr(factory, "SQLiteRankingProvider", _FakeProvider)
    monkeypatch.setattr(factory, "PortfolioService", _FakePortfolioService)
    monkeypatch.setattr(factory, "PortfolioAlertService", _FakePortfolioAlertService)
    monkeypatch.setattr(factory, "PortfolioConditionMonitor", _FakeProvider)
    monkeypatch.setattr(factory, "PortfolioChipService", _FakeProvider)
    monkeypatch.setattr(factory, "BrokerFlowService", _FakeProvider)
    monkeypatch.setattr(factory, "SmartMoneySemanticService", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(factory, "SQLiteSmartMoneyPriceProvider", _FakeProvider)

    generated_at = datetime(2026, 7, 3, 9, 0, 0)
    builder = factory.build_service_backed_decision_desk_snapshot_builder(
        _config(tmp_path),
        clock=lambda: generated_at,
    )

    snapshot = builder.build_snapshot(date(2026, 7, 3))

    assert snapshot.generated_at == generated_at
    assert snapshot.market_regime.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.market_breadth.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.sector_rotation.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.relative_strength_liquidity.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.watchlist_triggers.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.portfolio_alerts.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.watchlist_triggers.triggered_codes == ("2330",)


def test_batch_decision_desk_capture_uses_service_backed_factory() -> None:
    checked_paths = (
        Path("app_module/decision_desk_builder_factory.py"),
        Path("app_module/evidence_pipeline_runner.py"),
        Path("scripts/capture_decision_desk_snapshot.py"),
    )
    for path in checked_paths:
        text = path.read_text(encoding="utf-8")
        assert "ui_qt" not in text

    runner_text = Path("app_module/evidence_pipeline_runner.py").read_text(encoding="utf-8")
    capture_text = Path("scripts/capture_decision_desk_snapshot.py").read_text(encoding="utf-8")

    assert "build_service_backed_decision_desk_snapshot_builder" in runner_text
    assert "build_service_backed_decision_desk_snapshot_builder" in capture_text
    assert "DecisionDeskSnapshotBuilder().build_snapshot" not in runner_text
    assert "DecisionDeskSnapshotBuilder(clock=" not in capture_text


def test_decision_desk_section_meta_normalizes_numpy_scalars_for_json() -> None:
    summary = MarketRegimeSummary(
        as_of_date=date(2026, 7, 3),
        quality=DecisionDeskQuality.OBSERVED,
        warnings=(),
        regime_label="趨勢",
        meta={
            "close_above_ma60": np.bool_(True),
            "ma20_slope": np.float64(1.25),
            "sample_size": np.int64(20),
        },
    )

    payload = summary.to_dict()

    assert payload["meta"] == {
        "close_above_ma60": True,
        "ma20_slope": 1.25,
        "sample_size": 20,
    }
    json.dumps(payload, ensure_ascii=False)
