from __future__ import annotations

from dataclasses import replace

import pytest

from ml_module.feature_registry import CORE_LONG_HISTORY_FEATURE_REGISTRY
from ml_module.historical_contracts import HistoricalFeatureRow
from ml_module.historical_feature_builder import HistoricalFeatureBuilder


def _values(*, reverse: bool = False) -> tuple[tuple[str, int | None], ...]:
    values = tuple(
        (spec.feature_id, index * 10)
        for index, spec in enumerate(CORE_LONG_HISTORY_FEATURE_REGISTRY.specs, start=1)
    )
    return tuple(reversed(values)) if reverse else values


def _row(**overrides: object) -> HistoricalFeatureRow:
    values: dict[str, object] = {
        "symbol": "2330",
        "decision_date": "2024-06-03",
        "feature_as_of_date": "2024-05-31",
        "available_date": "2024-06-03",
        "values": _values(),
    }
    values.update(overrides)
    return HistoricalFeatureRow(**values)  # type: ignore[arg-type]


def test_load_contract_freezes_registry_order_dtype_unit_and_schema_hash() -> None:
    contract = HistoricalFeatureBuilder().load_contract

    assert contract.registry_hash == CORE_LONG_HISTORY_FEATURE_REGISTRY.registry_hash
    assert contract.canonical_schema == CORE_LONG_HISTORY_FEATURE_REGISTRY.canonical_schema
    assert contract.canonical_ids == CORE_LONG_HISTORY_FEATURE_REGISTRY.canonical_ids
    assert contract.canonical_dtypes == CORE_LONG_HISTORY_FEATURE_REGISTRY.canonical_dtypes
    assert contract.schema_hash.startswith("sha256:")
    assert contract.contract_hash.startswith("sha256:")
    assert contract.decision_timing == "decision_t_uses_previous_trading_day"
    assert contract.missing_policy == "missing_is_not_zero"


def test_training_and_inference_loads_have_identical_canonical_vector_and_hash() -> None:
    builder = HistoricalFeatureBuilder()

    training = builder.load(_row(values=_values()))
    inference = builder.load(_row(values=_values(reverse=True)))

    assert training == inference
    assert training.feature_ids == CORE_LONG_HISTORY_FEATURE_REGISTRY.canonical_ids
    assert training.values == tuple(value for _, value in _values())


def test_missing_value_and_observed_zero_remain_distinct() -> None:
    values = list(_values())
    values[0] = (values[0][0], None)
    values[1] = (values[1][0], 0)

    vector = HistoricalFeatureBuilder().load(_row(values=tuple(values)))

    assert vector.values[0] is None
    assert vector.values[1] == 0
    assert vector.missing_feature_ids == (values[0][0],)


def test_load_rejects_missing_extra_or_wrong_registry_schema() -> None:
    builder = HistoricalFeatureBuilder()

    with pytest.raises(ValueError, match="feature id set mismatch"):
        builder.load(_row(values=_values()[:-1]))
    with pytest.raises(ValueError, match="feature id set mismatch"):
        builder.load(_row(values=(*_values(), ("future_feature", 1))))
    with pytest.raises(ValueError, match="feature schema mismatch"):
        builder.load_contract.validate(
            expected_registry_hash=CORE_LONG_HISTORY_FEATURE_REGISTRY.registry_hash,
            expected_canonical_schema=tuple(
                reversed(CORE_LONG_HISTORY_FEATURE_REGISTRY.canonical_schema)
            ),
            expected_schema_hash=builder.load_contract.schema_hash,
        )


def test_appending_future_rows_does_not_change_existing_vectors() -> None:
    builder = HistoricalFeatureBuilder()
    first = _row()
    future = replace(
        first,
        decision_date="2024-06-04",
        feature_as_of_date="2024-06-03",
        available_date="2024-06-04",
    )

    prefix = builder.load_many((first,))
    extended = builder.load_many((first, future))

    assert extended[: len(prefix)] == prefix
