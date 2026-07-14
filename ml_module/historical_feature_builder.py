"""Shared canonical feature loading boundary for training and inference."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
import hashlib
import json
from collections import defaultdict
from typing import Mapping

from data_module.ml_historical_snapshot_provider import (
    HistoricalIndexObservation,
    HistoricalPriceObservation,
    HistoricalRawSnapshot,
    HistoricalTechnicalObservation,
)
from ml_module.feature_registry import (
    CORE_LONG_HISTORY_FEATURE_REGISTRY,
    FeatureRegistry,
)
from ml_module.historical_contracts import HistoricalFeatureRow


FeatureSchema = tuple[tuple[str, str, str], ...]


@dataclass(frozen=True)
class HistoricalFeatureBuilderLoadContract:
    registry_id: str
    registry_hash: str
    canonical_schema: FeatureSchema
    schema_hash: str
    decision_timing: str
    missing_policy: str
    contract_hash: str
    shadow_only: bool = True
    production_action_allowed: bool = False

    @classmethod
    def from_registry(
        cls, registry: FeatureRegistry
    ) -> "HistoricalFeatureBuilderLoadContract":
        schema_hash = _hash_payload(
            {
                "registry_hash": registry.registry_hash,
                "canonical_schema": [list(item) for item in registry.canonical_schema],
            }
        )
        payload = {
            "registry_id": registry.registry_id,
            "registry_hash": registry.registry_hash,
            "canonical_schema": [list(item) for item in registry.canonical_schema],
            "schema_hash": schema_hash,
            "decision_timing": "decision_t_uses_previous_trading_day",
            "missing_policy": "missing_is_not_zero",
            "shadow_only": True,
            "production_action_allowed": False,
        }
        return cls(
            registry_id=registry.registry_id,
            registry_hash=registry.registry_hash,
            canonical_schema=registry.canonical_schema,
            schema_hash=schema_hash,
            decision_timing="decision_t_uses_previous_trading_day",
            missing_policy="missing_is_not_zero",
            contract_hash=_hash_payload(payload),
        )

    @property
    def canonical_ids(self) -> tuple[str, ...]:
        return tuple(item[0] for item in self.canonical_schema)

    @property
    def canonical_dtypes(self) -> tuple[str, ...]:
        return tuple(item[1] for item in self.canonical_schema)

    @property
    def canonical_units(self) -> tuple[str, ...]:
        return tuple(item[2] for item in self.canonical_schema)

    def validate(
        self,
        *,
        expected_registry_hash: str,
        expected_canonical_schema: FeatureSchema,
        expected_schema_hash: str,
    ) -> None:
        if not self.shadow_only or self.production_action_allowed:
            raise ValueError("feature builder contract must remain shadow-only")
        if expected_registry_hash != self.registry_hash:
            raise ValueError("feature registry hash mismatch")
        if expected_canonical_schema != self.canonical_schema:
            raise ValueError("feature schema mismatch")
        if expected_schema_hash != self.schema_hash:
            raise ValueError("feature schema hash mismatch")


@dataclass(frozen=True)
class HistoricalFeatureVector:
    symbol: str
    decision_date: str
    feature_as_of_date: str
    available_date: str
    registry_hash: str
    schema_hash: str
    feature_ids: tuple[str, ...]
    feature_dtypes: tuple[str, ...]
    feature_units: tuple[str, ...]
    values: tuple[int | None, ...]
    missing_feature_ids: tuple[str, ...]
    snapshot_hash: str
    shadow_only: bool = True


class HistoricalFeatureBuilder:
    """Canonicalizes causal feature rows without fitting or imputing values."""

    def __init__(
        self, registry: FeatureRegistry = CORE_LONG_HISTORY_FEATURE_REGISTRY
    ) -> None:
        self._registry = registry
        self.load_contract = HistoricalFeatureBuilderLoadContract.from_registry(registry)

    def load(self, row: HistoricalFeatureRow) -> HistoricalFeatureVector:
        by_id = dict(row.values)
        expected_ids = self.load_contract.canonical_ids
        if set(by_id) != set(expected_ids):
            missing = tuple(sorted(set(expected_ids) - set(by_id)))
            extra = tuple(sorted(set(by_id) - set(expected_ids)))
            raise ValueError(
                f"feature id set mismatch: missing={missing}, extra={extra}"
            )
        values = tuple(by_id[feature_id] for feature_id in expected_ids)
        missing_ids = tuple(
            feature_id
            for feature_id, value in zip(expected_ids, values)
            if value is None
        )
        payload = {
            "symbol": row.symbol,
            "decision_date": row.decision_date,
            "feature_as_of_date": row.feature_as_of_date,
            "available_date": row.available_date,
            "registry_hash": self.load_contract.registry_hash,
            "schema_hash": self.load_contract.schema_hash,
            "feature_ids": list(expected_ids),
            "values": list(values),
        }
        return HistoricalFeatureVector(
            symbol=row.symbol,
            decision_date=row.decision_date,
            feature_as_of_date=row.feature_as_of_date,
            available_date=row.available_date,
            registry_hash=self.load_contract.registry_hash,
            schema_hash=self.load_contract.schema_hash,
            feature_ids=expected_ids,
            feature_dtypes=self.load_contract.canonical_dtypes,
            feature_units=self.load_contract.canonical_units,
            values=values,
            missing_feature_ids=missing_ids,
            snapshot_hash=_hash_payload(payload),
        )

    def load_many(
        self, rows: tuple[HistoricalFeatureRow, ...]
    ) -> tuple[HistoricalFeatureVector, ...]:
        return tuple(self.load(row) for row in rows)

    def compute(
        self,
        snapshot: HistoricalRawSnapshot,
        *,
        industry_index_name_by_symbol: Mapping[str, str],
    ) -> tuple[HistoricalFeatureRow, ...]:
        """Compute prefix-invariant integer features using only snapshot T-1 rows."""
        cutoff = snapshot.feature_as_of_date
        price_by_symbol: dict[str, list[HistoricalPriceObservation]] = defaultdict(list)
        for price_observation in snapshot.prices:
            if price_observation.trading_date <= cutoff:
                price_by_symbol[price_observation.symbol].append(price_observation)
        technical_by_symbol: dict[str, list[HistoricalTechnicalObservation]] = defaultdict(list)
        for technical_observation in snapshot.technicals:
            if technical_observation.trading_date <= cutoff:
                technical_by_symbol[technical_observation.symbol].append(technical_observation)
        market = _index_closes(snapshot.market, cutoff=cutoff, index_name="market")
        industry_names = {row.index_name for row in snapshot.industries}
        industries = {
            name: _index_closes(snapshot.industries, cutoff=cutoff, index_name=name)
            for name in industry_names
        }
        market_5 = _return_bp(market, 5)
        market_20 = _return_bp(market, 20)
        market_60 = _return_bp(market, 60)
        rows: list[HistoricalFeatureRow] = []
        for symbol in sorted(price_by_symbol):
            observations = sorted(price_by_symbol[symbol], key=lambda row: row.trading_date)
            closes = [row.close_price for row in observations]
            volumes = [row.volume for row in observations]
            latest = observations[-1]
            latest_close = latest.close_price
            technicals = sorted(technical_by_symbol[symbol], key=lambda row: row.trading_date)
            technical = technicals[-1] if technicals else None
            stock_20 = _return_bp(closes, 20)
            industry_name = industry_index_name_by_symbol.get(symbol)
            industry_20 = _return_bp(
                industries.get(industry_name, []) if industry_name is not None else [], 20
            )
            values = {
                "stock_return_1d_bp": _return_bp(closes, 1),
                "stock_return_5d_bp": _return_bp(closes, 5),
                "stock_return_20d_bp": stock_20,
                "stock_return_60d_bp": _return_bp(closes, 60),
                "trailing_volatility_20d_bp": _volatility_bp(closes, 20),
                "high_low_range_20d_bp": _range_bp(observations, 20),
                "close_to_ma_5d_bp": _close_to_average_bp(closes, 5),
                "close_to_ma_20d_bp": _close_to_average_bp(closes, 20),
                "close_to_ma_60d_bp": _close_to_average_bp(closes, 60),
                "rsi_normalized_bp": _rsi_bp(technical.rsi if technical else None),
                "adx_normalized_bp": _scaled_bp(technical.adx if technical else None),
                "macd_normalized_bp": _ratio_bp(
                    technical.macd if technical else None, latest_close
                ),
                "volume_ratio_5d_bp": _recent_ratio_bp(volumes, 5),
                "volume_ratio_20d_bp": _recent_ratio_bp(volumes, 20),
                "turnover_amount_minor": latest.turnover_amount_minor,
                "market_return_5d_bp": market_5,
                "market_return_20d_bp": market_20,
                "market_return_60d_bp": market_60,
                "stock_minus_market_20d_bp": _difference(stock_20, market_20),
                "industry_relative_return_20d_bp": _difference(stock_20, industry_20),
            }
            rows.append(HistoricalFeatureRow(
                symbol=symbol,
                decision_date=snapshot.decision_date,
                feature_as_of_date=cutoff,
                available_date=snapshot.decision_date,
                values=tuple((feature_id, values[feature_id]) for feature_id in self.load_contract.canonical_ids),
            ))
        return tuple(rows)


def _hash_payload(payload: object) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


_BASIS_POINTS = Decimal(10_000)


def _quantized_integer(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def _return_bp(values: list[Decimal | None], periods: int) -> int | None:
    if len(values) <= periods:
        return None
    start, end = values[-periods - 1], values[-1]
    if start is None or start == 0 or end is None:
        return None
    return _quantized_integer((end / start - 1) * _BASIS_POINTS)


def _ratio_bp(numerator: Decimal | None, denominator: Decimal | None) -> int | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return _quantized_integer(numerator / denominator * _BASIS_POINTS)


def _difference(left: int | None, right: int | None) -> int | None:
    return None if left is None or right is None else left - right


def _close_to_average_bp(values: list[Decimal | None], periods: int) -> int | None:
    if len(values) < periods:
        return None
    window = values[-periods:]
    if any(value is None for value in window):
        return None
    complete = [value for value in window if value is not None]
    average = sum(complete, Decimal(0)) / Decimal(periods)
    return _ratio_bp(complete[-1] - average, average)


def _recent_ratio_bp(values: list[int | None], periods: int) -> int | None:
    if len(values) < periods:
        return None
    window = values[-periods:]
    if any(value is None for value in window):
        return None
    complete = [value for value in window if value is not None]
    average = Decimal(sum(complete)) / Decimal(periods)
    return _ratio_bp(Decimal(complete[-1]), average)


def _range_bp(observations: list[HistoricalPriceObservation], periods: int) -> int | None:
    if len(observations) < periods:
        return None
    highs = [row.high_price for row in observations[-periods:] if row.high_price is not None]
    lows = [row.low_price for row in observations[-periods:] if row.low_price is not None]
    if len(highs) != periods or len(lows) != periods or min(lows) == 0:
        return None
    return _quantized_integer((max(highs) / min(lows) - 1) * _BASIS_POINTS)


def _volatility_bp(values: list[Decimal | None], periods: int) -> int | None:
    if len(values) <= periods:
        return None
    window = values[-periods - 1:]
    if any(value is None for value in window):
        return None
    complete = [value for value in window if value is not None]
    if any(previous == 0 for previous in complete[:-1]):
        return None
    returns = [current / previous - 1 for previous, current in zip(complete, complete[1:])]
    mean = sum(returns, Decimal(0)) / Decimal(len(returns))
    variance = sum(((value - mean) ** 2 for value in returns), Decimal(0)) / Decimal(len(returns))
    with localcontext() as context:
        context.prec = 34
        return _quantized_integer(variance.sqrt() * _BASIS_POINTS)


def _rsi_bp(value: Decimal | None) -> int | None:
    if value is None:
        return None
    return _quantized_integer((value - Decimal(50)) * Decimal(200))


def _scaled_bp(value: Decimal | None) -> int | None:
    return None if value is None else _quantized_integer(value * Decimal(100))


def _index_closes(
    rows: tuple[HistoricalIndexObservation, ...], *, cutoff: str, index_name: str
) -> list[Decimal | None]:
    selected = sorted(
        (row for row in rows if row.index_name == index_name and row.trading_date <= cutoff),
        key=lambda row: row.trading_date,
    )
    return [row.close_value for row in selected]
