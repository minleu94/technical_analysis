from __future__ import annotations

from pathlib import Path

from app_module.decision_quality_repository import DecisionQualityRepository
from app_module.decision_quality_service import DecisionQualityService
from app_module.evidence_event_dtos import EvidenceEvent, EvidenceOutcome
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.journal_service import JournalService
from app_module.live_research_gap_dtos import LiveResearchGapObservation
from app_module.live_research_gap_repository import LiveResearchGapRepository
from app_module.portfolio_service import PortfolioService
from app_module.signal_decay_dtos import SignalDecayObservation
from app_module.signal_decay_repository import SignalDecayRepository
from data_module.config import TWStockConfig


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "decision_quality.db"
    config.use_sqlite = True
    return config


def _seed_trade_without_source(config: TWStockConfig) -> None:
    PortfolioService(config).record_trade(
        stock_code="2330",
        stock_name="TSMC",
        side="buy",
        quantity=1000,
        price=100,
        trade_date="2026-06-10",
        trade_id="trade-1",
    )


def _seed_manual_override(config: TWStockConfig) -> None:
    PortfolioService(config).record_trade(
        stock_code="2317",
        stock_name="Hon Hai",
        side="buy",
        quantity=1000,
        price=100,
        trade_date="2026-06-11",
        source_type="manual_override",
        source_summary={"override": True},
        trade_id="trade-manual",
    )


def _event(event_id: str, *, symbol: str, event_type: str, family: str = "portfolio") -> EvidenceEvent:
    return EvidenceEvent(
        event_id=event_id,
        event_hash=f"hash:{event_id}",
        event_date="2026-06-12",
        decision_date="2026-06-12",
        symbol=symbol,
        event_type=event_type,
        event_family=family,
        source_type=family,
        source_id=f"source:{event_id}",
        data_quality="observed",
        warnings=(),
        as_of_date="2026-06-12",
        available_date="2026-06-12",
    )


def _seed_portfolio_alert(config: TWStockConfig) -> None:
    repo = EvidenceEventRepository(config)
    repo.insert_event(_event("evt-alert", symbol="2330", event_type="portfolio_alert_condition_invalid"))


def _seed_live_gap(config: TWStockConfig) -> None:
    LiveResearchGapRepository(config).save_observation(
        LiveResearchGapObservation(
            gap_id="gap-large",
            gap_hash="hash:gap-large",
            observation_date="2026-06-20",
            position_id="default:2330",
            symbol="2330",
            portfolio_mode="simulated",
            source_type="research_run",
            source_id="run-1",
            gap_vs_forward_evidence_bp=1200,
            data_quality="observed",
        )
    )


def _seed_signal_decay(config: TWStockConfig) -> None:
    SignalDecayRepository(config).save_observation(
        SignalDecayObservation(
            decay_id="decay-1",
            decay_hash="hash:decay-1",
            observation_date="2026-06-21",
            signal_scope_type="event_type",
            signal_scope_id="recommendation_included",
            event_type="recommendation_included",
            event_family="recommendation",
            window_short=30,
            window_long=120,
            sample_size_short=20,
            sample_size_long=80,
            decay_status="decaying",
            suggested_lifecycle_action="demote_candidate",
            confidence="medium",
            evidence_event_count=80,
            quality="observed",
        )
    )


def test_build_review_detects_core_process_items_without_writes(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_trade_without_source(config)
    _seed_manual_override(config)
    _seed_portfolio_alert(config)
    _seed_live_gap(config)
    _seed_signal_decay(config)

    review, items = DecisionQualityService(config).build_review(
        review_type="monthly",
        start_date="2026-06-01",
        end_date="2026-06-30",
        min_sample_size=1,
    )

    item_types = {item.item_type for item in items}
    assert {
        "trade_without_source_trace",
        "manual_override_without_evidence",
        "ignored_portfolio_alert",
        "large_live_research_gap",
        "unreviewed_signal_decay",
    }.issubset(item_types)
    assert review.unlinked_trade_count == 1
    assert review.manual_override_count == 1
    assert review.review_status in {"incomplete", "needs_review"}
    assert all(item.suggested_review_question for item in items)
    assert DecisionQualityRepository(config).list_reviews() == []


def test_save_review_requires_confirm_and_is_idempotent(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_trade_without_source(config)
    service = DecisionQualityService(config)
    review, items = service.build_review(
        review_type="weekly",
        start_date="2026-06-08",
        end_date="2026-06-14",
        min_sample_size=1,
    )

    dry = service.save_review(review, items=items, confirm=False)
    confirmed = service.save_review(review, items=items, confirm=True)
    duplicate = service.save_review(review, items=items, confirm=True)

    assert dry.saved is False
    assert confirmed.saved is True
    assert duplicate.skipped_duplicate is True
    assert len(DecisionQualityRepository(config).list_reviews()) == 1


def test_no_journal_is_warning_not_user_blame(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_trade_without_source(config)

    review, _items = DecisionQualityService(config).build_review(
        review_type="weekly",
        start_date="2026-06-08",
        end_date="2026-06-14",
        min_sample_size=1,
    )

    assert "journal_missing" in review.warnings_json
    assert review.quality == "degraded"
    assert 0 <= review.decision_quality_score_bp <= 10000
    assert 0 <= review.process_adherence_score_bp <= 10000
    assert 0 <= review.evidence_usage_score_bp <= 10000
    assert 0 <= review.risk_discipline_score_bp <= 10000
    assert 0 <= review.review_completeness_score_bp <= 10000


def test_journal_link_suppresses_manual_override_item(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_manual_override(config)
    JournalService(config).add_journal_entry(
        body="已記錄人工調整的研究理由",
        portfolio_id="default",
        stock_code="2317",
        linked_type="trade",
        linked_id="trade-manual",
    )

    _review, items = DecisionQualityService(config).build_review(
        review_type="weekly",
        start_date="2026-06-08",
        end_date="2026-06-14",
        min_sample_size=1,
    )

    assert "manual_override_without_evidence" not in {item.item_type for item in items}
