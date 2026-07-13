"""Immutable matured-label registry for historical ML shadow datasets."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json

from ml_module.historical_contracts import HistoricalLabelSpec


@dataclass(frozen=True)
class LabelRegistry:
    registry_id: str
    specs: tuple[HistoricalLabelSpec, ...]
    registry_hash: str

    @classmethod
    def create(
        cls,
        *,
        registry_id: str,
        specs: tuple[HistoricalLabelSpec, ...],
    ) -> "LabelRegistry":
        if not registry_id or not specs:
            raise ValueError("registry_id and specs are required")
        label_ids = tuple(spec.label_id for spec in specs)
        if len(label_ids) != len(set(label_ids)):
            raise ValueError("label ids must be unique")
        payload = {
            "registry_id": registry_id,
            "specs": [asdict(spec) for spec in specs],
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return cls(
            registry_id=registry_id,
            specs=specs,
            registry_hash=f"sha256:{digest}",
        )


def _label(label_id: str, unit: str) -> HistoricalLabelSpec:
    return HistoricalLabelSpec(
        label_id=label_id,
        dtype="int",
        unit=unit,
        horizon_trading_days=20,
        missing_policy="pending_is_not_zero",
        availability_policy="available_on_horizon_end",
    )


CORE_LONG_HISTORY_LABEL_REGISTRY = LabelRegistry.create(
    registry_id="core-long-history-labels-v1",
    specs=(
        _label("relative_return_20d_bp", "bp"),
        _label("maximum_adverse_excursion_20d_bp", "bp"),
        _label("downside_20d_flag", "boolean_int"),
        _label("cross_sectional_top_quintile_20d_flag", "boolean_int"),
    ),
)
