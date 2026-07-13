from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from ml_module.dataset_manifest import MLDatasetField, MLDatasetManifestV2
from ml_module.feature_registry import CORE_LONG_HISTORY_FEATURE_REGISTRY
from ml_module.label_registry import CORE_LONG_HISTORY_LABEL_REGISTRY


def _sha(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _features() -> tuple[MLDatasetField, ...]:
    return tuple(
        MLDatasetField(spec.feature_id, spec.dtype, f"core.{spec.family}", True)
        for spec in CORE_LONG_HISTORY_FEATURE_REGISTRY.specs
    )


def _labels() -> tuple[MLDatasetField, ...]:
    return tuple(
        MLDatasetField(spec.label_id, spec.dtype, "historical_label", True)
        for spec in CORE_LONG_HISTORY_LABEL_REGISTRY.specs
    )


def _manifest(**overrides: object) -> MLDatasetManifestV2:
    values: dict[str, object] = {
        "dataset_id": "core-2015-2024-v1",
        "created_at": "2026-07-13T12:00:00+00:00",
        "decision_date_start": "2015-01-05",
        "decision_date_end": "2024-12-31",
        "row_count": 1000,
        "features": _features(),
        "labels": _labels(),
        "feature_registry_hash": CORE_LONG_HISTORY_FEATURE_REGISTRY.registry_hash,
        "label_registry_hash": CORE_LONG_HISTORY_LABEL_REGISTRY.registry_hash,
        "universe_policy_id": "historical-listed-with-60d-history-v1",
        "decision_timing": "decision_t_uses_previous_trading_day",
        "split_policy": "expanding_purged_walk_forward_trading_calendar",
        "source_fingerprints": {"daily_prices": _sha("prices"), "market": _sha("market")},
        "accepted_diagnostics": {"accepted": 1000},
        "excluded_diagnostics": {"immature_label": 25},
        "corporate_action_coverage": "research_only_unknown",
        "broker_eligibility": "excluded_separate_addon",
        "fundamental_eligibility": "ineligible_pending_pit_repair",
        "content_hash": _sha("dataset"),
    }
    values.update(overrides)
    return MLDatasetManifestV2.create(**values)  # type: ignore[arg-type]


def test_v2_manifest_is_deterministic_and_records_canonical_feature_contract() -> None:
    first = _manifest()
    second = _manifest(
        source_fingerprints={"market": _sha("market"), "daily_prices": _sha("prices")}
    )

    assert first == second
    assert first.schema_version == "ml-dataset-manifest.v2"
    assert first.feature_canonical_order == CORE_LONG_HISTORY_FEATURE_REGISTRY.canonical_ids
    assert first.feature_dtypes == CORE_LONG_HISTORY_FEATURE_REGISTRY.canonical_dtypes
    assert first.fundamental_eligibility == "ineligible_pending_pit_repair"
    assert first.shadow_only is True
    assert first.production_eligible is False


def test_v2_manifest_hash_changes_when_feature_order_or_dtype_changes() -> None:
    first = _manifest()
    reordered = _manifest(features=tuple(reversed(_features())))
    changed_dtype = list(_features())
    changed_dtype[0] = replace(changed_dtype[0], dtype="int32")

    assert reordered.manifest_hash != first.manifest_hash
    assert _manifest(features=tuple(changed_dtype)).manifest_hash != first.manifest_hash


def test_v2_manifest_validates_feature_registry_hash_order_and_dtype() -> None:
    manifest = _manifest()
    manifest.assert_feature_contract(
        registry_hash=CORE_LONG_HISTORY_FEATURE_REGISTRY.registry_hash,
        canonical_ids=CORE_LONG_HISTORY_FEATURE_REGISTRY.canonical_ids,
        canonical_dtypes=CORE_LONG_HISTORY_FEATURE_REGISTRY.canonical_dtypes,
    )

    with pytest.raises(ValueError, match="feature registry hash mismatch"):
        manifest.assert_feature_contract(
            registry_hash=_sha("wrong"),
            canonical_ids=CORE_LONG_HISTORY_FEATURE_REGISTRY.canonical_ids,
            canonical_dtypes=CORE_LONG_HISTORY_FEATURE_REGISTRY.canonical_dtypes,
        )
    with pytest.raises(ValueError, match="feature canonical order mismatch"):
        manifest.assert_feature_contract(
            registry_hash=CORE_LONG_HISTORY_FEATURE_REGISTRY.registry_hash,
            canonical_ids=tuple(reversed(CORE_LONG_HISTORY_FEATURE_REGISTRY.canonical_ids)),
            canonical_dtypes=CORE_LONG_HISTORY_FEATURE_REGISTRY.canonical_dtypes,
        )


def test_v2_manifest_round_trip_rejects_tampered_payload() -> None:
    manifest = _manifest()
    assert MLDatasetManifestV2.from_dict(manifest.to_dict()) == manifest

    tampered = manifest.to_dict()
    tampered["row_count"] = 1001
    with pytest.raises(ValueError, match="manifest hash mismatch"):
        MLDatasetManifestV2.from_dict(tampered)

    unsafe_flags = manifest.to_dict()
    unsafe_flags["production_eligible"] = True
    with pytest.raises(ValueError, match="shadow flags"):
        MLDatasetManifestV2.from_dict(unsafe_flags)


def test_v2_manifest_nested_mappings_are_immutable() -> None:
    manifest = _manifest()

    with pytest.raises(TypeError):
        manifest.source_fingerprints["future"] = _sha("future")  # type: ignore[index]


def test_v2_manifest_requires_full_hashes_and_explicit_exclusion_gates() -> None:
    with pytest.raises(ValueError, match="feature_registry_hash"):
        _manifest(feature_registry_hash="sha256:short")
    with pytest.raises(ValueError, match="fundamental_eligibility"):
        _manifest(fundamental_eligibility="")
