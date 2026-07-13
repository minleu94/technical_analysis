from decimal import Decimal

import pytest

from app_module.paper_portfolio_daily_runner import PaperPriceObservation, PaperPortfolioDailyRunner
from app_module.paper_portfolio_snapshot_repository import (
    PaperPortfolioPositionSnapshot,
    PaperPortfolioSnapshot,
)


def _prior() -> PaperPortfolioSnapshot:
    return PaperPortfolioSnapshot(
        snapshot_id="paper-20260710",
        portfolio_id="paper-main",
        decision_date="2026-07-10",
        source_result_id="rec-1",
        cash=Decimal("200000.00"),
        total_value=Decimal("500000.00"),
        positions=(
            PaperPortfolioPositionSnapshot("2330", 300, Decimal("1000"), Decimal("300000"), 6000),
        ),
    )


def test_daily_runner_marks_positions_and_recomputes_integer_weights() -> None:
    result = PaperPortfolioDailyRunner().run(
        prior=_prior(),
        decision_date="2026-07-11",
        prices=(PaperPriceObservation("2330", "2026-07-11", "2026-07-11", Decimal("1010")),),
    )

    assert result.snapshot.total_value == Decimal("503000.00")
    assert result.snapshot.positions[0].market_value == Decimal("303000.00")
    assert result.snapshot.positions[0].weight_bp == 6023
    assert result.source_mode == "causal_mark_to_market"
    assert result.broker_order_allowed is False


def test_future_available_price_is_never_used() -> None:
    with pytest.raises(ValueError, match="missing causal price"):
        PaperPortfolioDailyRunner().run(
            prior=_prior(),
            decision_date="2026-07-11",
            prices=(PaperPriceObservation("2330", "2026-07-11", "2026-07-12", Decimal("1010")),),
        )


def test_latest_visible_price_on_or_before_decision_date_is_used() -> None:
    result = PaperPortfolioDailyRunner().run(
        prior=_prior(),
        decision_date="2026-07-12",
        prices=(
            PaperPriceObservation("2330", "2026-07-10", "2026-07-10", Decimal("1000")),
            PaperPriceObservation("2330", "2026-07-11", "2026-07-11", Decimal("1010")),
            PaperPriceObservation("2330", "2026-07-13", "2026-07-13", Decimal("9999")),
        ),
    )

    assert result.snapshot.positions[0].mark_price == Decimal("1010")
    assert "previous_visible_trading_day:2330" in result.diagnostics


def test_runner_rejects_non_forward_snapshot_date() -> None:
    with pytest.raises(ValueError, match="after prior snapshot"):
        PaperPortfolioDailyRunner().run(prior=_prior(), decision_date="2026-07-10", prices=())
