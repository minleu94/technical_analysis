"""Conservative, integer-share execution decisions for research replay.

The policy is intentionally small and deterministic.  It separates an order's
requested quantity from the quantity that can be filled at the next executable
price, records price-limit and participation failures, and never fabricates a
fill when the known volume input is missing.  Money and rates stay in Decimal;
quantities stay integer shares.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from financial_module.units import to_decimal


@dataclass(frozen=True)
class FillDecision:
    """Result of applying conservative market constraints to one order."""

    side: str
    requested_shares: int
    filled_shares: int
    unfilled_shares: int
    status: str
    reason: str | None = None
    participation_cap_shares: int | None = None

    def __post_init__(self) -> None:
        if self.side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        for field_name in ("requested_shares", "filled_shares", "unfilled_shares"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.filled_shares + self.unfilled_shares != self.requested_shares:
            raise ValueError("fill quantities must conserve the request")
        if self.status not in {"filled", "partially_filled", "unfilled"}:
            raise ValueError("unsupported fill status")
        if self.status == "filled" and self.unfilled_shares != 0:
            raise ValueError("filled decision cannot have unfilled shares")
        if self.status == "partially_filled" and not (0 < self.filled_shares < self.requested_shares):
            raise ValueError("partially_filled requires both filled and unfilled shares")
        if self.status == "unfilled" and self.filled_shares != 0:
            raise ValueError("unfilled decision cannot have filled shares")

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "requested_shares": self.requested_shares,
            "filled_shares": self.filled_shares,
            "unfilled_shares": self.unfilled_shares,
            "status": self.status,
            "reason": self.reason,
            "participation_cap_shares": self.participation_cap_shares,
        }


class ConservativeFillPolicy:
    """Apply price-limit, lot-size and known-volume constraints."""

    def __init__(
        self,
        *,
        lot_size: int = 1000,
        max_participation_rate: Any | None = None,
        enable_limit_up_down: bool = True,
        limit_up_down_pct: Any = Decimal("0.10"),
        apply_volume_to_sell: bool = True,
    ) -> None:
        if isinstance(lot_size, bool) or not isinstance(lot_size, int) or lot_size < 1:
            raise ValueError("lot_size must be a positive integer")
        rate = None if max_participation_rate is None else to_decimal(max_participation_rate)
        limit = to_decimal(limit_up_down_pct)
        if rate is not None and (not rate.is_finite() or rate <= 0 or rate > 1):
            raise ValueError("max_participation_rate must be within (0, 1]")
        if not limit.is_finite() or limit <= 0 or limit >= 1:
            raise ValueError("limit_up_down_pct must be within (0, 1)")
        self.lot_size = lot_size
        self.max_participation_rate = rate
        self.enable_limit_up_down = bool(enable_limit_up_down)
        self.limit_up_down_pct = limit
        self.apply_volume_to_sell = bool(apply_volume_to_sell)

    def decide(
        self,
        *,
        side: str,
        requested_shares: int,
        open_price: Any,
        prior_close: Any | None = None,
        known_volume: Any | None = None,
    ) -> FillDecision:
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if isinstance(requested_shares, bool) or not isinstance(requested_shares, int) or requested_shares < 0:
            raise ValueError("requested_shares must be a non-negative integer")
        if requested_shares == 0:
            return FillDecision(side, 0, 0, 0, "unfilled", "zero_requested_shares")
        price = to_decimal(open_price)
        if not price.is_finite() or price <= 0:
            return FillDecision(side, requested_shares, 0, requested_shares, "unfilled", "missing_open_or_invalid_price")

        previous = None if prior_close is None else to_decimal(prior_close)
        if (
            self.enable_limit_up_down
            and previous is not None
            and previous.is_finite()
            and previous > 0
        ):
            upper = previous * (Decimal("1") + self.limit_up_down_pct)
            lower = previous * (Decimal("1") - self.limit_up_down_pct)
            if side == "buy" and price >= upper:
                return FillDecision(side, requested_shares, 0, requested_shares, "unfilled", "open_at_price_limit")
            if side == "sell" and price <= lower:
                return FillDecision(side, requested_shares, 0, requested_shares, "unfilled", "open_at_price_limit")

        cap: int | None = None
        applies_to_volume = self.max_participation_rate is not None and (side == "buy" or self.apply_volume_to_sell)
        if applies_to_volume:
            assert self.max_participation_rate is not None
            if known_volume is None:
                return FillDecision(side, requested_shares, 0, requested_shares, "unfilled", "known_volume_missing")
            volume = to_decimal(known_volume)
            if not volume.is_finite() or volume < 0:
                return FillDecision(side, requested_shares, 0, requested_shares, "unfilled", "known_volume_invalid")
            cap = (int(volume * self.max_participation_rate) // self.lot_size) * self.lot_size
            if cap <= 0:
                return FillDecision(side, requested_shares, 0, requested_shares, "unfilled", "participation_capacity_zero", cap)

        fill = requested_shares if cap is None else min(requested_shares, cap)
        # The policy never emits odd-lot fills for a lot-sized request.
        fill = (fill // self.lot_size) * self.lot_size
        if fill <= 0:
            return FillDecision(side, requested_shares, 0, requested_shares, "unfilled", "lot_size_limited", cap)
        remaining = requested_shares - fill
        status = "filled" if remaining == 0 else "partially_filled"
        return FillDecision(side, requested_shares, fill, remaining, status, None, cap)
