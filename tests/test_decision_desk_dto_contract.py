from __future__ import annotations

from datetime import date, datetime

from app_module.decision_desk_dtos import DecisionDeskQuality, DecisionDeskSectionStatus, MarketRegimeSummary


def test_decision_desk_quality_values_and_section_serialization_are_stable() -> None:
    section = DecisionDeskSectionStatus(
        as_of_date=date(2026, 7, 10),
        quality=DecisionDeskQuality.ESTIMATED,
        warnings=["source_lag", 7],
    )

    assert {quality.name: quality.value for quality in DecisionDeskQuality} == {
        "OBSERVED": "observed",
        "ESTIMATED": "estimated",
        "DEGRADED": "degraded",
        "MISSING": "missing",
    }
    assert section.warnings == ("source_lag", "7")
    assert section.to_dict() == {
        "as_of_date": "2026-07-10",
        "quality": "estimated",
        "warnings": ["source_lag", "7"],
    }


def test_market_regime_serialization_preserves_field_order_and_datetime_metadata() -> None:
    summary = MarketRegimeSummary(
        as_of_date=date(2026, 7, 10),
        quality=DecisionDeskQuality.OBSERVED,
        warnings=("stable",),
        regime_label="Trend",
        regime_score=84,
        regime_confidence=9100,
        meta={"observed_at": datetime(2026, 7, 10, 9, 30), "source_date": date(2026, 7, 9)},
    )

    payload = summary.to_dict()

    assert list(payload) == [
        "as_of_date",
        "quality",
        "warnings",
        "regime_label",
        "regime_score",
        "regime_confidence",
        "meta",
    ]
    assert payload["quality"] == "observed"
    assert payload["warnings"] == ["stable"]
    assert payload["meta"] == {"observed_at": "2026-07-10T09:30:00", "source_date": "2026-07-09"}
