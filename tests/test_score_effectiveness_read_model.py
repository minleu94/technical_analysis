from __future__ import annotations

import json
from decimal import Decimal

from app_module.evidence_event_dtos import (
    EvidenceDataQuality,
    EvidenceEvent,
    EvidenceEventType,
    EvidenceOutcome,
    EvidenceOutcomeStatus,
)
from app_module.score_effectiveness_read_model import (
    SCORE_BUCKETS,
    ScoreEffectivenessReadModel,
    total_score_bucket,
)
from scripts.inspect_score_effectiveness import main as inspect_score_effectiveness_main


def _event(event_id: str, score_bp: int | None) -> EvidenceEvent:
    return EvidenceEvent(
        event_id=event_id,
        event_hash=f"hash-{event_id}",
        event_date="2026-01-02",
        decision_date="2026-01-02",
        symbol="2330",
        event_type=EvidenceEventType.RECOMMENDATION_INCLUDED,
        event_family="recommendation",
        source_type="persisted_recommendation",
        score_bp=score_bp,
        data_quality=EvidenceDataQuality.OBSERVED,
        warnings=(),
        as_of_date="2026-01-02",
        available_date="2026-01-02",
    )


def _outcome(
    event_id: str,
    window_days: int,
    status: EvidenceOutcomeStatus,
    *,
    forward_return_bp: int | None = None,
    benchmark_excess_bp: int | None = None,
    industry_excess_bp: int | None = None,
    max_adverse_excursion_bp: int | None = None,
) -> EvidenceOutcome:
    return EvidenceOutcome(
        outcome_id=f"out-{event_id}-{window_days}",
        event_id=event_id,
        window_days=window_days,
        forward_return_bp=forward_return_bp,
        benchmark_excess_bp=benchmark_excess_bp,
        industry_excess_bp=industry_excess_bp,
        max_adverse_excursion_bp=max_adverse_excursion_bp,
        outcome_status=status,
        data_quality=EvidenceDataQuality.OBSERVED,
    )


def test_total_score_bucket_boundaries_use_raw_total_score() -> None:
    assert total_score_bucket(Decimal("0")) == "0-40"
    assert total_score_bucket(Decimal("39.99")) == "0-40"
    assert total_score_bucket(Decimal("40")) == "40-50"
    assert total_score_bucket(Decimal("49.99")) == "40-50"
    assert total_score_bucket(Decimal("50")) == "50-60"
    assert total_score_bucket(Decimal("59.99")) == "50-60"
    assert total_score_bucket(Decimal("60")) == "60-70"
    assert total_score_bucket(Decimal("69.99")) == "60-70"
    assert total_score_bucket(Decimal("70")) == "70-80"
    assert total_score_bucket(Decimal("79.99")) == "70-80"
    assert total_score_bucket(Decimal("80")) == "80-100"
    assert total_score_bucket(Decimal("100")) == "80-100"


def test_report_keeps_empty_buckets_and_read_only_disclosure() -> None:
    report = ScoreEffectivenessReadModel(
        events=(_event("evt-low", 3500), _event("evt-high", 8200)),
        outcomes=(
            _outcome(
                "evt-low",
                5,
                EvidenceOutcomeStatus.READY,
                forward_return_bp=120,
                benchmark_excess_bp=80,
                industry_excess_bp=None,
                max_adverse_excursion_bp=-90,
            ),
            _outcome(
                "evt-high",
                5,
                EvidenceOutcomeStatus.INSUFFICIENT_FUTURE_DATA,
            ),
            _outcome("evt-high", 10, EvidenceOutcomeStatus.MISSING_PRICE),
        ),
    ).build_report()

    payload = report.to_dict()
    assert [bucket["bucket"] for bucket in payload["buckets"]] == list(SCORE_BUCKETS)
    assert payload["access_boundary"]["writes_allowed"] is False
    assert payload["access_boundary"]["production_scheduler_allowed"] is False
    assert payload["access_boundary"]["investment_effectiveness_claim"] is False
    assert "研究證據" in payload["limitations"][0]

    empty = next(bucket for bucket in payload["buckets"] if bucket["bucket"] == "40-50")
    assert empty["sample_count"] == 0
    assert empty["limitations"] == ["此分數區間目前沒有樣本，不能解讀為有效或無效。"]

    low = next(bucket for bucket in payload["buckets"] if bucket["bucket"] == "0-40")
    assert low["sample_count"] == 1
    assert low["ready_outcome_count"] == 1
    assert low["pending_outcome_count"] == 0
    assert low["missing_outcome_count"] == 0
    assert low["forward_return_bp_by_horizon"] == {"5": 120}
    assert low["benchmark_excess_bp_by_horizon"] == {"5": 80}
    assert low["industry_excess_bp_by_horizon"] == {}
    assert low["max_drawdown_bp_by_horizon"] == {"5": -90}
    assert low["win_rate_bp_by_horizon"] == {"5": 10000}
    assert "missing_industry_excess" in low["warnings"]

    high = next(bucket for bucket in payload["buckets"] if bucket["bucket"] == "80-100")
    assert high["sample_count"] == 1
    assert high["ready_outcome_count"] == 0
    assert high["pending_outcome_count"] == 1
    assert high["missing_outcome_count"] == 1


def test_sample_cli_outputs_traditional_chinese_json_and_markdown(tmp_path, capsys) -> None:
    json_path = tmp_path / "score_effectiveness.json"
    assert inspect_score_effectiveness_main(["--sample", "--format", "json", "--output", str(json_path)]) == 0
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["access_boundary"]["writes_allowed"] is False
    assert "研究證據" in payload["limitations"][0]

    markdown_path = tmp_path / "score_effectiveness.md"
    assert inspect_score_effectiveness_main(["--sample", "--format", "markdown", "--output", str(markdown_path)]) == 0
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "分數有效性稽核" in markdown
    assert "不是交易建議" in markdown
    assert "0-40" in markdown
    _ = capsys.readouterr()
