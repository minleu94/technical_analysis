"""Frozen causal contracts for the historical ML shadow workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal


FeatureFamily = Literal["price", "technical", "market", "industry", "broker", "fundamental"]
MaturityStatus = Literal["pending", "ready"]
LabelQuality = Literal["clean", "research_only", "degraded"]


@dataclass(frozen=True)
class HistoricalUniversePolicy:
    """Decision-time universe policy that does not use today's survivor list."""

    minimum_history_trading_days: int

    def __post_init__(self) -> None:
        if self.minimum_history_trading_days <= 0:
            raise ValueError("minimum_history_trading_days must be positive")

    def is_eligible(
        self,
        *,
        decision_date: date,
        listing_date: date,
        delisting_date: date | None,
        observed_history_trading_days: int,
    ) -> bool:
        if listing_date > decision_date:
            return False
        if delisting_date is not None and delisting_date < decision_date:
            return False
        return observed_history_trading_days >= self.minimum_history_trading_days


@dataclass(frozen=True)
class HistoricalFeatureSpec:
    feature_id: str
    family: FeatureFamily
    dtype: str
    unit: str
    missing_policy: str
    availability_policy: str

    def __post_init__(self) -> None:
        _require_non_empty(
            self.feature_id,
            self.dtype,
            self.unit,
            self.missing_policy,
            self.availability_policy,
        )


@dataclass(frozen=True)
class HistoricalLabelSpec:
    label_id: str
    dtype: str
    unit: str
    horizon_trading_days: int
    missing_policy: str
    availability_policy: str

    def __post_init__(self) -> None:
        _require_non_empty(
            self.label_id,
            self.dtype,
            self.unit,
            self.missing_policy,
            self.availability_policy,
        )
        if self.horizon_trading_days <= 0:
            raise ValueError("horizon_trading_days must be positive")


@dataclass(frozen=True)
class HistoricalFeatureRow:
    symbol: str
    decision_date: str
    feature_as_of_date: str
    available_date: str
    values: tuple[tuple[str, int | None], ...]

    def __post_init__(self) -> None:
        _require_non_empty(self.symbol)
        decision = _date(self.decision_date)
        if _date(self.feature_as_of_date) >= decision:
            raise ValueError("feature_as_of_date must be before decision_date")
        if _date(self.available_date) > decision:
            raise ValueError("feature available_date must not exceed decision_date")
        if not self.values:
            raise ValueError("feature values are required")
        names = tuple(name for name, _ in self.values)
        if any(not name for name in names) or len(names) != len(set(names)):
            raise ValueError("feature value names must be non-empty and unique")
        if any(isinstance(value, bool) or not isinstance(value, (int, type(None))) for _, value in self.values):
            raise TypeError("persisted feature values must be integer units or explicit missing")


@dataclass(frozen=True)
class HistoricalLabelRow:
    symbol: str
    decision_date: str
    label_id: str
    value: int | None
    horizon_end_date: str
    available_date: str
    maturity_status: MaturityStatus
    quality: LabelQuality

    def __post_init__(self) -> None:
        _require_non_empty(self.symbol, self.label_id)
        decision = _date(self.decision_date)
        horizon_end = _date(self.horizon_end_date)
        available = _date(self.available_date)
        if horizon_end <= decision:
            raise ValueError("label horizon_end_date must be after decision_date")
        if available < horizon_end:
            raise ValueError("label available_date must not precede horizon_end_date")
        if isinstance(self.value, bool) or not isinstance(self.value, (int, type(None))):
            raise TypeError("persisted label value must be integer units or explicit missing")
        if self.maturity_status == "pending" and self.value is not None:
            raise ValueError("pending label value must be missing")
        if self.maturity_status == "ready" and self.value is None:
            raise ValueError("ready label value is required")

    def is_fit_eligible(self, *, training_as_of: str) -> bool:
        return (
            self.maturity_status == "ready"
            and self.value is not None
            and _date(self.available_date) <= _date(training_as_of)
        )


@dataclass(frozen=True)
class HistoricalDatasetRow:
    feature: HistoricalFeatureRow
    labels: tuple[HistoricalLabelRow, ...]

    def __post_init__(self) -> None:
        if not self.labels:
            raise ValueError("dataset row labels are required")
        if any(
            label.symbol != self.feature.symbol
            or label.decision_date != self.feature.decision_date
            for label in self.labels
        ):
            raise ValueError("feature and labels must share the same symbol and decision_date")
        label_ids = tuple(label.label_id for label in self.labels)
        if len(label_ids) != len(set(label_ids)):
            raise ValueError("dataset row label ids must be unique")


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid ISO date: {value}") from exc


def _require_non_empty(*values: str) -> None:
    if any(not value or not value.strip() for value in values):
        raise ValueError("contract text fields must be non-empty")
