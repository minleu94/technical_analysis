from __future__ import annotations

from ml_module.feature_registry import CORE_LONG_HISTORY_FEATURE_REGISTRY
from ml_module.historical_contracts import HistoricalFeatureRow, HistoricalLabelRow
from ml_module.historical_dataset_builder import HistoricalDatasetBuilder
from ml_module.label_registry import CORE_LONG_HISTORY_LABEL_REGISTRY


def _feature(symbol: str = "2330") -> HistoricalFeatureRow:
    return HistoricalFeatureRow(
        symbol=symbol, decision_date="2024-01-22", feature_as_of_date="2024-01-19",
        available_date="2024-01-22",
        values=tuple((spec.feature_id, index) for index, spec in enumerate(
            CORE_LONG_HISTORY_FEATURE_REGISTRY.specs, start=1
        )),
    )


def _labels(*, available_date: str = "2024-02-23") -> tuple[HistoricalLabelRow, ...]:
    return tuple(HistoricalLabelRow(
        symbol="2330", decision_date="2024-01-22", label_id=spec.label_id,
        value=index, horizon_end_date="2024-02-22", available_date=available_date,
        maturity_status="ready", quality="clean",
    ) for index, spec in enumerate(CORE_LONG_HISTORY_LABEL_REGISTRY.specs, start=1))


def test_first_build_is_deterministic_shadow_only_and_manifested() -> None:
    builder = HistoricalDatasetBuilder()
    kwargs = dict(
        feature_rows=(_feature(),), labels=_labels(), training_as_of="2024-03-01",
        dataset_id="bounded-first-build", created_at="2026-07-13T12:00:00+00:00",
        source_fingerprints={"formal_sqlite": "sha256:" + "a" * 64},
    )

    first = builder.build(**kwargs)
    second = builder.build(**kwargs)

    assert first == second
    assert len(first.rows) == 1
    assert first.manifest.row_count == 1
    assert first.manifest.content_hash == first.content_hash
    assert first.manifest.broker_eligibility == "excluded_separate_addon"
    assert first.manifest.fundamental_eligibility == "ineligible_pending_pit_repair"
    assert first.manifest.shadow_only is True


def test_build_excludes_labels_not_available_by_training_as_of_without_peeking() -> None:
    result = HistoricalDatasetBuilder().build(
        feature_rows=(_feature(),), labels=_labels(available_date="2024-04-01"),
        training_as_of="2024-03-01", dataset_id="no-peek",
        created_at="2026-07-13T12:00:00+00:00",
        source_fingerprints={"formal_sqlite": "sha256:" + "b" * 64},
    )

    assert not result.rows
    assert result.manifest is None
    assert result.excluded_diagnostics == {"immature_or_unavailable_label": 1}


def test_build_excludes_decision_rows_after_training_as_of() -> None:
    result = HistoricalDatasetBuilder().build(
        feature_rows=(_feature(),), labels=_labels(), training_as_of="2024-01-21",
        dataset_id="future-decision-blocked",
        created_at="2026-07-13T12:00:00+00:00",
        source_fingerprints={"formal_sqlite": "sha256:" + "c" * 64},
    )

    assert result.rows == ()
    assert result.manifest is None
    assert result.excluded_diagnostics == {"future_decision_row": 1}


def test_degraded_corporate_labels_are_manifested_as_research_only_not_clean_oos() -> None:
    degraded = tuple(
        HistoricalLabelRow(
            symbol=label.symbol, decision_date=label.decision_date,
            label_id=label.label_id, value=label.value,
            horizon_end_date=label.horizon_end_date, available_date=label.available_date,
            maturity_status=label.maturity_status, quality="degraded",
        )
        for label in _labels()
    )
    result = HistoricalDatasetBuilder().build(
        feature_rows=(_feature(),), labels=degraded, training_as_of="2024-03-01",
        dataset_id="research-only-degraded",
        created_at="2026-07-13T12:00:00+00:00",
        source_fingerprints={"formal_sqlite": "sha256:" + "d" * 64},
    )

    assert result.manifest is not None
    assert result.manifest.corporate_action_coverage == "research_only_degraded"
    assert result.formal_oos_allowed is False
    assert result.manifest.accepted_diagnostics == {
        "accepted": 1,
        "degraded_corporate_action_rows": 1,
    }
