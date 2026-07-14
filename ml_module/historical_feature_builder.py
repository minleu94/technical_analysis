"""Shared canonical feature loading boundary for training and inference."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

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


def _hash_payload(payload: object) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"
