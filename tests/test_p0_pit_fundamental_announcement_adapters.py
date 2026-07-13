import pytest

from data_module.p0_pit_fundamental_announcement_adapters import (
    PITFinancialAnnouncementAdapter,
    PITRevenueAnnouncementAdapter,
)


def test_monthly_revenue_uses_explicit_announcement_availability() -> None:
    observation = PITRevenueAnnouncementAdapter().adapt(
        source_id="twse.monthly_revenue_announcement",
        row={
            "symbol": "2330",
            "period": "2026-06",
            "announcement_date": "2026-07-10",
            "available_date": "2026-07-10",
            "source_version": "twse-20260710",
            "revenue_cents": 1000000,
        },
        decision_date="2026-07-12",
    )

    assert observation.status == "shadow_ready"
    assert observation.available_date == "2026-07-10"
    assert "period_is_not_available_date" in observation.diagnostics


def test_revenue_available_before_announcement_is_blocked() -> None:
    observation = PITRevenueAnnouncementAdapter().adapt(
        source_id="tpex.monthly_revenue_announcement",
        row={
            "symbol": "1234",
            "period": "2026-06",
            "announcement_date": "2026-07-10",
            "available_date": "2026-07-09",
            "source_version": "tpex-v1",
            "revenue_cents": 1000,
        },
        decision_date="2026-07-12",
    )

    assert observation.status == "blocked"
    assert "available_before_announcement" in observation.diagnostics


def test_quarterly_revision_preserves_revision_available_date() -> None:
    observation = PITFinancialAnnouncementAdapter().adapt(
        row={
            "symbol": "2330",
            "period_end": "2026-03-31",
            "announcement_date": "2026-05-10",
            "available_date": "2026-05-15",
            "revision_number": 1,
            "source_version": "mops-revision-1",
            "statement_items": {"eps_cents": 250},
        },
        decision_date="2026-07-12",
    )

    assert observation.status == "shadow_ready"
    assert observation.available_date == "2026-05-15"
    assert observation.raw_payload["revision_number"] == 1


def test_fundamental_adapter_rejects_unknown_revenue_source() -> None:
    with pytest.raises(ValueError):
        PITRevenueAnnouncementAdapter().adapt(
            source_id="unknown.revenue",
            row={},
            decision_date="2026-07-12",
        )
