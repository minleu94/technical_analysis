from decimal import Decimal

from backtest_module.conservative_fill_policy import ConservativeFillPolicy


def test_policy_records_partial_fill_from_known_volume() -> None:
    policy = ConservativeFillPolicy(
        lot_size=100,
        max_participation_rate=Decimal("0.10"),
        enable_limit_up_down=False,
    )

    result = policy.decide(
        side="buy",
        requested_shares=1_000,
        open_price=Decimal("100"),
        known_volume=Decimal("2_500"),
    )

    assert result.status == "partially_filled"
    assert result.filled_shares == 200
    assert result.unfilled_shares == 800
    assert result.participation_cap_shares == 200


def test_policy_rejects_limit_locked_open_without_using_intraday_future_data() -> None:
    policy = ConservativeFillPolicy(lot_size=100, max_participation_rate=None)

    result = policy.decide(
        side="buy",
        requested_shares=100,
        open_price=Decimal("110"),
        prior_close=Decimal("100"),
    )

    assert result.status == "unfilled"
    assert result.reason == "open_at_price_limit"


def test_policy_requires_known_volume_when_participation_cap_is_enabled() -> None:
    policy = ConservativeFillPolicy(
        lot_size=100,
        max_participation_rate=Decimal("0.05"),
    )

    result = policy.decide(
        side="buy",
        requested_shares=100,
        open_price=Decimal("100"),
    )

    assert result.status == "unfilled"
    assert result.reason == "known_volume_missing"

