from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from ml_module.feature_registry import (
    CORE_LONG_HISTORY_FEATURE_REGISTRY,
    FeatureRegistry,
)
from ml_module.historical_contracts import HistoricalFeatureSpec, HistoricalLabelSpec
from ml_module.label_registry import CORE_LONG_HISTORY_LABEL_REGISTRY, LabelRegistry


def test_core_registry_excludes_fundamental_and_broker_feature_families() -> None:
    assert CORE_LONG_HISTORY_FEATURE_REGISTRY.model_family == "core_long_history"
    assert CORE_LONG_HISTORY_FEATURE_REGISTRY.excluded_families == (
        "broker",
        "fundamental",
    )
    assert {
        spec.family for spec in CORE_LONG_HISTORY_FEATURE_REGISTRY.specs
    } <= {"price", "technical", "market", "industry"}


@pytest.mark.parametrize("family", ["fundamental", "broker"])
def test_core_registry_rejects_ineligible_feature_family(family: str) -> None:
    spec = replace(CORE_LONG_HISTORY_FEATURE_REGISTRY.specs[0], family=family)

    with pytest.raises(ValueError, match="excluded feature family"):
        FeatureRegistry.create(
            registry_id="invalid-core",
            model_family="core_long_history",
            specs=(spec,),
            excluded_families=("broker", "fundamental"),
        )


def test_feature_registry_hash_is_deterministic_and_covers_contract_fields() -> None:
    spec = HistoricalFeatureSpec(
        feature_id="return_20d_bp",
        family="price",
        dtype="int",
        unit="bp",
        missing_policy="missing_is_not_zero",
        availability_policy="feature_as_of_before_decision",
    )
    first = FeatureRegistry.create(
        registry_id="core-v1",
        model_family="core_long_history",
        specs=(spec,),
        excluded_families=("broker", "fundamental"),
    )
    second = FeatureRegistry.create(
        registry_id="core-v1",
        model_family="core_long_history",
        specs=(spec,),
        excluded_families=("broker", "fundamental"),
    )

    assert first.registry_hash == second.registry_hash
    assert replace(first, registry_hash="different") != first
    for field_name, changed in (
        ("dtype", replace(spec, dtype="int32")),
        ("unit", replace(spec, unit="ratio_bp")),
        ("missing_policy", replace(spec, missing_policy="reject_row")),
        (
            "availability_policy",
            replace(spec, availability_policy="available_on_decision"),
        ),
    ):
        changed_registry = FeatureRegistry.create(
            registry_id="core-v1",
            model_family="core_long_history",
            specs=(changed,),
            excluded_families=("broker", "fundamental"),
        )
        assert changed_registry.registry_hash != first.registry_hash, field_name


def test_feature_registry_hash_covers_canonical_order() -> None:
    specs = CORE_LONG_HISTORY_FEATURE_REGISTRY.specs[:2]
    forward = FeatureRegistry.create(
        registry_id="ordered",
        model_family="core_long_history",
        specs=specs,
        excluded_families=("broker", "fundamental"),
    )
    reverse = FeatureRegistry.create(
        registry_id="ordered",
        model_family="core_long_history",
        specs=tuple(reversed(specs)),
        excluded_families=("broker", "fundamental"),
    )

    assert forward.registry_hash != reverse.registry_hash


def test_label_registry_hash_covers_horizon_and_availability_contract() -> None:
    spec = HistoricalLabelSpec(
        label_id="relative_return_20d_bp",
        dtype="int",
        unit="bp",
        horizon_trading_days=20,
        missing_policy="pending_is_not_zero",
        availability_policy="available_on_horizon_end",
    )
    first = LabelRegistry.create(registry_id="labels-v1", specs=(spec,))
    same = LabelRegistry.create(registry_id="labels-v1", specs=(spec,))
    later = LabelRegistry.create(
        registry_id="labels-v1",
        specs=(replace(spec, horizon_trading_days=60),),
    )

    assert first.registry_hash == same.registry_hash
    assert first.registry_hash != later.registry_hash
    assert CORE_LONG_HISTORY_LABEL_REGISTRY.specs


def test_registry_contracts_are_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        CORE_LONG_HISTORY_FEATURE_REGISTRY.registry_id = "mutated"  # type: ignore[misc]
