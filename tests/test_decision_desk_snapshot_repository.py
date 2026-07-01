from __future__ import annotations

from datetime import date, datetime

from app_module.decision_desk_dtos import (
    DecisionDeskQuality,
    DecisionDeskRiskPrompt,
    DecisionDeskRiskPromptSummary,
    MarketBreadthSummary,
    MarketRegimeSummary,
    PortfolioAlertAttribution,
    PortfolioAlertSummary,
    RelativeStrengthLiquiditySummary,
    SectorRotationSummary,
    WatchlistTriggerSummary,
)
from app_module.decision_desk_snapshot_repository import DecisionDeskSnapshotRepository
from app_module.decision_desk_snapshot_storage_dtos import build_stored_decision_desk_snapshot
from data_module.config import TWStockConfig


def _config(tmp_path):
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "evidence.db"
    config.db_file.parent.mkdir(parents=True, exist_ok=True)
    return config


def _snapshot(as_of: date = date(2026, 6, 30), *, warning: str = "fixture") -> object:
    from app_module.decision_desk_dtos import DecisionDeskSnapshot

    return DecisionDeskSnapshot(
        as_of_date=as_of,
        generated_at=datetime(2026, 6, 30, 15, 0, 0),
        schema_version=1,
        overall_quality=DecisionDeskQuality.DEGRADED,
        market_regime=MarketRegimeSummary(as_of, DecisionDeskQuality.MISSING, ("regime_missing",)),
        market_breadth=MarketBreadthSummary(as_of, DecisionDeskQuality.MISSING, ("breadth_missing",)),
        sector_rotation=SectorRotationSummary(as_of, DecisionDeskQuality.MISSING, ("rotation_missing",)),
        relative_strength_liquidity=RelativeStrengthLiquiditySummary(
            as_of,
            DecisionDeskQuality.OBSERVED,
            (),
            top_strength_codes=("2330",),
            weak_strength_codes=("2317",),
            low_liquidity_codes=("1234",),
        ),
        watchlist_triggers=WatchlistTriggerSummary(
            as_of,
            DecisionDeskQuality.OBSERVED,
            ("watchlist_trigger_risk_alert:2317",),
            trigger_count=2,
            triggered_codes=("2330", "2317"),
            top_signal="new=2330;down=2317",
        ),
        portfolio_alerts=PortfolioAlertSummary(
            as_of,
            DecisionDeskQuality.DEGRADED,
            ("portfolio_degraded",),
            alert_count=1,
            alert_codes=("2317",),
            alert_level="warning",
            attributions=(
                PortfolioAlertAttribution(
                    stock_code="2317",
                    source_label="fixture",
                    condition_status="warning",
                    chip_risk_level="neutral",
                    severity=2,
                    reasons=("condition_warning",),
                    data_quality_flags=("fixture_flag",),
                ),
            ),
        ),
        risk_prompts=DecisionDeskRiskPromptSummary(
            as_of,
            DecisionDeskQuality.OBSERVED,
            (),
            prompts=(
                DecisionDeskRiskPrompt(
                    category="liquidity",
                    severity="warning",
                    source="fixture",
                    code="1234",
                    title="Liquidity evidence",
                    reason="Persisted snapshot payload",
                    action_hint="Review source data",
                ),
            ),
        ),
        warnings=(warning,),
    )


def test_repository_saves_lists_and_reads_snapshot(tmp_path):
    repository = DecisionDeskSnapshotRepository(_config(tmp_path))
    stored = repository.save_snapshot(build_stored_decision_desk_snapshot(_snapshot()))

    assert repository.get_snapshot(stored.snapshot_id) == stored
    assert repository.find_by_decision_date(date(2026, 6, 30))[0].snapshot_id == stored.snapshot_id
    assert repository.latest_before_or_on(date(2026, 7, 1)).snapshot_id == stored.snapshot_id
    assert repository.list_snapshots()[0].snapshot_hash == stored.snapshot_hash
    restored = stored.to_decision_desk_snapshot()
    assert restored.watchlist_triggers.triggered_codes == ("2330", "2317")
    assert restored.risk_prompts.prompts[0].category == "liquidity"


def test_same_snapshot_is_idempotent_and_hash_is_deterministic(tmp_path):
    repository = DecisionDeskSnapshotRepository(_config(tmp_path))
    first = build_stored_decision_desk_snapshot(_snapshot())
    second = build_stored_decision_desk_snapshot(_snapshot())

    assert first.snapshot_hash == second.snapshot_hash
    saved_first = repository.save_snapshot(first)
    saved_second = repository.save_snapshot(second)

    assert saved_first.snapshot_id == saved_second.snapshot_id
    assert len(repository.list_snapshots()) == 1


def test_different_hash_keeps_new_version_and_supersedes_prior_active(tmp_path):
    repository = DecisionDeskSnapshotRepository(_config(tmp_path))
    first = repository.save_snapshot(build_stored_decision_desk_snapshot(_snapshot(warning="first")))
    second = repository.save_snapshot(build_stored_decision_desk_snapshot(_snapshot(warning="second")))

    rows = repository.find_by_decision_date("2026-06-30")
    assert len(rows) == 2
    assert {row.snapshot_status for row in rows} == {"superseded", "active"}
    assert repository.get_snapshot(first.snapshot_id).snapshot_status == "superseded"
    assert repository.get_snapshot(second.snapshot_id).snapshot_status == "active"


def test_missing_sections_are_persisted_as_degraded_payload_not_neutral(tmp_path):
    snapshot = _snapshot()
    stored = build_stored_decision_desk_snapshot(snapshot)
    assert stored.market_regime_json["quality"] == "missing"
    assert "regime_missing" in stored.market_regime_json["warnings"]

    repository = DecisionDeskSnapshotRepository(_config(tmp_path))
    saved = repository.save_snapshot(stored)

    restored = saved.to_decision_desk_snapshot()
    assert restored.market_regime.quality == DecisionDeskQuality.MISSING
    assert "regime_missing" in restored.market_regime.warnings
