"""Immutable feature registry for historical ML shadow datasets."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json

from ml_module.historical_contracts import HistoricalFeatureSpec


_CORE_FAMILIES = frozenset({"price", "technical", "market", "industry"})


@dataclass(frozen=True)
class FeatureRegistry:
    registry_id: str
    model_family: str
    specs: tuple[HistoricalFeatureSpec, ...]
    excluded_families: tuple[str, ...]
    registry_hash: str

    @classmethod
    def create(
        cls,
        *,
        registry_id: str,
        model_family: str,
        specs: tuple[HistoricalFeatureSpec, ...],
        excluded_families: tuple[str, ...],
    ) -> "FeatureRegistry":
        if not registry_id or not model_family or not specs:
            raise ValueError("registry_id, model_family, and specs are required")
        feature_ids = tuple(spec.feature_id for spec in specs)
        if len(feature_ids) != len(set(feature_ids)):
            raise ValueError("feature ids must be unique")
        if model_family == "core_long_history":
            excluded = set(excluded_families)
            if not {"fundamental", "broker"}.issubset(excluded):
                raise ValueError("core registry must exclude fundamental and broker families")
            invalid = tuple(spec.family for spec in specs if spec.family not in _CORE_FAMILIES)
            if invalid:
                raise ValueError(f"excluded feature family in core registry: {invalid[0]}")
        payload = {
            "registry_id": registry_id,
            "model_family": model_family,
            "specs": [asdict(spec) for spec in specs],
            "excluded_families": list(excluded_families),
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return cls(
            registry_id=registry_id,
            model_family=model_family,
            specs=specs,
            excluded_families=excluded_families,
            registry_hash=f"sha256:{digest}",
        )


def _feature(feature_id: str, family: str, *, unit: str = "bp") -> HistoricalFeatureSpec:
    return HistoricalFeatureSpec(
        feature_id=feature_id,
        family=family,  # type: ignore[arg-type]
        dtype="int",
        unit=unit,
        missing_policy="missing_is_not_zero",
        availability_policy="feature_as_of_before_decision",
    )


CORE_LONG_HISTORY_FEATURE_REGISTRY = FeatureRegistry.create(
    registry_id="core-long-history-features-v1",
    model_family="core_long_history",
    specs=(
        _feature("stock_return_1d_bp", "price"),
        _feature("stock_return_5d_bp", "price"),
        _feature("stock_return_20d_bp", "price"),
        _feature("stock_return_60d_bp", "price"),
        _feature("trailing_volatility_20d_bp", "price"),
        _feature("high_low_range_20d_bp", "price"),
        _feature("close_to_ma_5d_bp", "technical"),
        _feature("close_to_ma_20d_bp", "technical"),
        _feature("close_to_ma_60d_bp", "technical"),
        _feature("rsi_normalized_bp", "technical"),
        _feature("adx_normalized_bp", "technical"),
        _feature("macd_normalized_bp", "technical"),
        _feature("volume_ratio_5d_bp", "technical"),
        _feature("volume_ratio_20d_bp", "technical"),
        _feature("turnover_amount_minor", "price", unit="minor_currency_unit"),
        _feature("market_return_5d_bp", "market"),
        _feature("market_return_20d_bp", "market"),
        _feature("market_return_60d_bp", "market"),
        _feature("stock_minus_market_20d_bp", "market"),
        _feature("industry_relative_return_20d_bp", "industry"),
    ),
    excluded_families=("broker", "fundamental"),
)
