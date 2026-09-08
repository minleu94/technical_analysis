from __future__ import annotations

import sqlite3
import json
from typing import Any
from types import SimpleNamespace
from pathlib import Path

import numpy as np
import pytest

from app_module.ml_allocation_inference_service import _parse_artifact
from ml_module.allocation_out_of_core_training_service import TARGET_FIELDS
from ml_module import allocation_release_loader
import ml_module.allocation_v3_linear_release as v3_release_module
from ml_module.allocation_training_service import (
    CLASSIFICATION_EXPERT_HEADS,
    EXPERT_HEAD_IDS,
    REGRESSION_EXPERT_HEADS,
)
from ml_module.allocation_v3_linear_release import (
    CALIBRATION_FOLD_IDS,
    DEFAULT_BATCH_SIZE,
    FIT_FOLD_ID,
    META_FIT_FOLD_ID,
    V3_PROFILE,
    _ConstantProbabilityModel,
    _ConstantRegressionModel,
    _MarketCloseSeries,
    _load_market_close_pairs,
    _publish_release,
    _artifact_payload,
    _build_neutral_meta_models,
    _fit_base_models,
    _fit_calibrator,
    _default_lock_path,
    _resolve_shared_lock_path,
    _readback_inference_mode,
    _select_projection_refs,
    _v3_feature_layout,
    _validate_v3_rows,
)
from data_module.ml_storage_capacity import directory_size_bytes


def test_release_readback_loader_is_neutral_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert (
        v3_release_module.load_allocation_release
        is allocation_release_loader.load_allocation_release
    )

    monkeypatch.setattr(allocation_release_loader, "_registered_loader", None)
    with pytest.raises(RuntimeError, match="not registered"):
        allocation_release_loader.load_allocation_release(Path("C:/missing-release"))


def test_v3_scope_is_separated_and_bounded() -> None:
    assert FIT_FOLD_ID == "fold-001"
    assert META_FIT_FOLD_ID == "fold-002"
    assert CALIBRATION_FOLD_IDS == ("fold-003", "fold-004")
    assert DEFAULT_BATCH_SIZE <= 65_536
    assert V3_PROFILE == "v3_h5_linear_shadow"


def test_v3_default_lock_resolves_release_v4_shared_lock() -> None:
    manifest = Path(
        "D:\\Min\\Python\\Project\\FA_Data\\output\\release_v4\\"
        "portfolio_ml_direct_numeric_production_v4_v2\\runs\\direct\\manifest.json"
    )
    assert _default_lock_path(manifest) == Path(
        "D:\\Min\\Python\\Project\\FA_Data\\output\\release_v4\\.ml_heavy_chain.lock"
    )


def test_v3_does_not_accept_a_caller_selected_nonshared_lock() -> None:
    # This is checked during preflight, after the immutable parent path is
    # resolved; a C: lock must never be used as a substitute for D: mutex.
    parent = Path(
        "D:/x/release_v4/parent/runs/run/manifest.json"
    )
    with pytest.raises(ValueError, match="shared heavy-chain lock"):
        _resolve_shared_lock_path(parent, Path("C:/wrong/.ml_heavy_chain.lock"))


def test_constant_targets_use_neutral_meta_and_nonconstant_targets_block() -> None:
    targets = np.tile(
        np.asarray([[0, 0, 0, 0, 10_000, 0]], dtype=np.int32),
        (4, 1),
    )
    models, summary = _build_neutral_meta_models(
        targets=targets,
        meta_row_ids=("meta-0", "meta-1", "meta-2", "meta-3"),
    )
    assert summary["training_skipped"] is True
    assert summary["status"] == "degenerate_constant_targets_adapter_neutral"
    assert models["numeric"]["cash_bp"].predict(np.zeros((2, 1))).tolist() == [10_000, 10_000]
    assert models["rebalance"].predict_proba(np.zeros((1, 1)))[0].tolist() == [1.0, 0.0]

    changed = targets.copy()
    changed[0, 0] = 1
    with pytest.raises(ValueError, match="identified Meta target source"):
        _build_neutral_meta_models(
            targets=changed,
            meta_row_ids=("meta-0", "meta-1", "meta-2", "meta-3"),
        )


def test_artifact_payload_binds_exact_equal_family_weights() -> None:
    packs = (
        ("data_quality", ("f0",)),
        ("market_sector_cross_section", ("f1",)),
        ("price_liquidity_technical", ("f2",)),
    )
    models = {}
    for pack_id, feature_ids in packs:
        heads: dict[str, Any] = {
            head_id: (
                None
                if head_id == "expected_sector_excess_return_bp"
                else _ConstantRegressionModel(0)
            )
            for head_id in REGRESSION_EXPERT_HEADS
        }
        heads.update(
            {
                head_id: _ConstantProbabilityModel(0)
                for head_id in CLASSIFICATION_EXPERT_HEADS
            }
        )
        fit_rows = {
            head_id: ([] if head_id == "expected_sector_excess_return_bp" else ["r0"])
            for head_id in EXPERT_HEAD_IDS
        }
        models[pack_id] = {
            "models": heads,
            "fit_row_ids": fit_rows,
            "missing": {"expected_sector_excess_return_bp": "sector-unavailable"},
            "feature_ids": feature_ids,
        }
    meta_models = {
        "numeric": {
            field_name: _ConstantRegressionModel(0)
            for field_name in ("target_weight_bp", "delta_weight_bp", "risk_contribution_bp", "risky_budget_bp", "cash_bp")
        },
        "rebalance": _ConstantProbabilityModel(0),
        "fit_row_ids": ["meta-r0"],
    }
    payload = _artifact_payload(
        models=models,
        meta_models=meta_models,
        packs=packs,
        feature_order=("f0", "f1", "f2"),
        dataset_id="v3-test",
        dataset_identity_hash="sha256:" + "a" * 64,
        dataset_manifest_file_hash="sha256:" + "b" * 64,
        feature_registry_hash="sha256:" + "c" * 64,
        source_manifest_hashes=(("source", "sha256:" + "d" * 64),),
        training_as_of="2026-09-04T00:00:00+08:00",
        fit_row_ids=("r0",),
        training_profile=V3_PROFILE,
        target_summary={"all_meta_targets_constant": True},
    )
    assert sum(weight for _, weight in payload["feature_family_weights_bp"]) == 10_000
    assert _parse_artifact(payload).feature_family_weights_bp == (
        ("data_quality", 3333),
        ("market_sector_cross_section", 3333),
        ("price_liquidity_technical", 3334),
    )


def test_v3_sixty_feature_layout_roundtrips_pack_order() -> None:
    ids_by_family = {
        "data_quality": tuple(f"data_quality.f{index:02d}" for index in range(10)),
        "market_sector_cross_section": tuple(
            f"market_sector_cross_section.f{index:02d}" for index in range(11)
        ),
        "price_liquidity_technical": tuple(
            f"price_liquidity_technical.f{index:02d}" for index in range(39)
        ),
    }
    features = tuple(
        SimpleNamespace(feature_id=feature_id, family_id=family_id)
        for family_id, feature_ids in reversed(tuple(ids_by_family.items()))
        for feature_id in reversed(feature_ids)
    )
    order, packs = _v3_feature_layout((SimpleNamespace(features=features),))
    expected = tuple(
        feature_id for family_id in ids_by_family for feature_id in ids_by_family[family_id]
    )
    assert order == expected
    assert tuple(pack_id for pack_id, _ in packs) == tuple(ids_by_family)
    assert tuple(
        feature_id for _pack_id, feature_ids in packs for feature_id in feature_ids
    ) == order


def test_projection_excludes_unclassified_parent_dq_rows() -> None:
    ids = (
        "data_quality.market_sector_cross_section.quality_blocked_count",
        "data_quality.market_sector_cross_section.stale_count",
        "data_quality.price_liquidity_technical.quality_blocked_count",
        "data_quality.price_liquidity_technical.stale_count",
    )

    class _Store:
        feature_positions = {feature_id: index for index, feature_id in enumerate(ids)}

        def __init__(self) -> None:
            self.values = np.asarray(
                [
                    [0, 0, 0, 0],
                    [0, 1, 0, 0],
                    [0, 0, 1, 0],
                    [0, 0, 0, np.nan],
                ],
                dtype=np.float32,
            )

        def read_feature_batch(
            self,
            refs: np.ndarray,
            positions: tuple[int, ...],
        ) -> np.ndarray:
            return self.values[refs[:, 1]][:, positions]

    selected, report = _select_projection_refs(
        _Store(),  # type: ignore[arg-type]
        np.asarray([[0, 0], [0, 1], [0, 2], [0, 3]], dtype=np.int64),
        batch_size=2,
    )
    assert selected.tolist() == [[0, 0]]
    assert report["total_rows"] == 4
    assert report["eligible_rows"] == 1
    assert report["excluded_rows"] == 3
    assert report["family"]["market_sector_cross_section"][
        "excluded_stale_rows"
    ] == 1
    assert report["family"]["price_liquidity_technical"][
        "excluded_quality_blocked_rows"
    ] == 1
    assert report["family"]["price_liquidity_technical"][
        "excluded_unknown_status_rows"
    ] == 1


def test_non_daily_readback_requires_explicit_research_row_identity() -> None:
    rows = (
        SimpleNamespace(
            row_id="row:post-freeze-shadow:2026-09-07:1101",
            decision_at="2026-09-07T18:00:00+08:00",
        ),
    )
    assert _readback_inference_mode(rows) == "post_freeze_research_shadow"
    with pytest.raises(ValueError, match="post-freeze-shadow row identity"):
        _readback_inference_mode(
            (
                SimpleNamespace(
                    row_id="row:other:2026-09-07:1101",
                    decision_at="2026-09-07T18:00:00+08:00",
                ),
            )
        )


def test_base_head_fit_rows_exclude_missing_label_rows() -> None:
    matrix = np.asarray(
        [[1.0, 2.0, 3.0], [2.0, 3.0, 4.0], [3.0, 4.0, 5.0], [4.0, 5.0, 6.0]],
        dtype=np.float32,
    )
    labels = np.zeros((4, 9), dtype=np.int32)
    labels[:, 2] = (0, 1, 0, 1)
    labels[:, 8] = (1, 0, 1, 0)
    masks = np.zeros((4, 9), dtype=np.uint8)
    masks[0, 0] = 1
    masks[:, 1] = 1
    packs = (
        ("data_quality", ("f0",)),
        ("market_sector_cross_section", ("f1",)),
        ("price_liquidity_technical", ("f2",)),
    )
    result = _fit_base_models(
        matrix,
        labels,
        masks,
        packs=packs,
        feature_order=("f0", "f1", "f2"),
        fit_row_ids=("r0", "r1", "r2", "r3"),
    )
    for pack in result.values():
        assert pack["fit_row_ids"]["expected_excess_return_bp"] == ["r1", "r2", "r3"]
        assert pack["fit_row_ids"]["expected_sector_excess_return_bp"] == []
        assert pack["missing"]["expected_sector_excess_return_bp"]


class _CalibrationStore:
    def read_label_batch(
        self,
        refs: np.ndarray,
        horizon: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        assert horizon == 5
        labels = np.zeros((len(refs), 9), dtype=np.int32)
        labels[:, 2] = np.arange(len(refs), dtype=np.int32) % 2
        masks = np.zeros((len(refs), 9), dtype=np.uint8)
        return labels, masks


def test_calibrator_uses_two_withheld_folds_and_records_row_vs_observation_counts() -> None:
    packs = (
        ("data_quality", ("f0",)),
        ("market_sector_cross_section", ("f1",)),
        ("price_liquidity_technical", ("f2",)),
    )
    models = {
        pack_id: {
            "models": {
                "downside_probability_bp": _ConstantProbabilityModel(0),
            }
        }
        for pack_id, _ in packs
    }
    refs = {
        fold_id: np.asarray([0, 1, 2, 3], dtype=np.int64)
        for fold_id in CALIBRATION_FOLD_IDS
    }
    matrices = {
        fold_id: np.zeros((4, 3), dtype=np.float32)
        for fold_id in CALIBRATION_FOLD_IDS
    }
    mapping, evidence = _fit_calibrator(
        models=models,
        calibration_matrices=matrices,
        calibration_ref_sets=refs,  # type: ignore[arg-type]
        store=_CalibrationStore(),  # type: ignore[arg-type]
        calibration_metadata={
            "fold-003": (
                ["2015-08-07T08:30:00+08:00"] * 4,
                ["1101", "1102", "1103", "1104"],
                ["c3:1101", "c3:1102", "c3:1103", "c3:1104"],
            ),
            "fold-004": (
                ["2015-11-16T08:30:00+08:00"] * 4,
                ["1101", "1102", "1103", "1104"],
                ["c4:1101", "c4:1102", "c4:1103", "c4:1104"],
            ),
        },
        fit_metadata=(
            ["2014-01-03T08:30:00+08:00"] * 4,
            ["1101", "1102", "1103", "1104"],
            ["fit:1101", "fit:1102", "fit:1103", "fit:1104"],
        ),
        packs=packs,
        feature_order=("f0", "f1", "f2"),
    )
    assert len(mapping) == 10_001
    assert evidence["target_fold_self_excluded"] is True
    assert evidence["fit_row_count_by_fold"] == {"fold-003": 4, "fold-004": 4}
    assert evidence["fit_observation_count_by_fold"] == {"fold-003": 12, "fold-004": 12}
    assert evidence["positive_row_count"] == 12
    assert evidence["negative_row_count"] == 12


def test_calibrator_rejects_row_identity_overlap_before_fit() -> None:
    packs = (
        ("data_quality", ("f0",)),
        ("market_sector_cross_section", ("f1",)),
        ("price_liquidity_technical", ("f2",)),
    )
    models = {
        pack_id: {
            "models": {"downside_probability_bp": _ConstantProbabilityModel(0)}
        }
        for pack_id, _ in packs
    }
    refs = {
        fold_id: np.asarray([0, 1], dtype=np.int64)
        for fold_id in CALIBRATION_FOLD_IDS
    }
    matrices = {
        fold_id: np.zeros((2, 3), dtype=np.float32)
        for fold_id in CALIBRATION_FOLD_IDS
    }
    metadata = {
        "fold-003": (
            ["2015-08-07T08:30:00+08:00"] * 2,
            ["1101", "1102"],
            ["fit:1101", "c3:1102"],
        ),
        "fold-004": (
            ["2015-11-16T08:30:00+08:00"] * 2,
            ["1101", "1102"],
            ["c4:1101", "c4:1102"],
        ),
    }
    with pytest.raises(ValueError, match="overlap base fit rows"):
        _fit_calibrator(
            models=models,
            calibration_matrices=matrices,
            calibration_ref_sets=refs,  # type: ignore[arg-type]
            store=_CalibrationStore(),  # type: ignore[arg-type]
            calibration_metadata=metadata,
            fit_metadata=(
                ["2014-01-03T08:30:00+08:00"] * 2,
                ["1101", "1102"],
                ["fit:1101", "fit:1102"],
            ),
            packs=packs,
            feature_order=("f0", "f1", "f2"),
        )


def _market_fixture(path: Path, rows: list[tuple[str, float]]) -> Path:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE market_indices (日期 TEXT, 指數名稱 TEXT, "
        "收盤指數 REAL, 收盤價 REAL)"
    )
    connection.executemany(
        "INSERT INTO market_indices VALUES (?, 'TAIEX', ?, NULL)", rows
    )
    connection.commit()
    connection.close()
    return path


def test_market_projection_excludes_same_day_close_before_decision(
    tmp_path: Path,
) -> None:
    path = _market_fixture(
        tmp_path / "market.sqlite",
        [("20260902", 90.0), ("20260903", 100.0), ("20260904", 999.0)],
    )
    market = _load_market_close_pairs(path)
    before = market.pair_for_decision("2026-09-04T08:30:00+08:00")
    after = market.pair_for_decision("2026-09-04T15:00:00+08:00")
    assert before is not None
    assert after is not None
    assert before[0].event_date == "2026-09-03"
    assert before[1].event_date == "2026-09-02"
    assert before[0].close - before[1].close == 10
    assert after[0].event_date == "2026-09-04"
    assert after[0].close == 999


def test_market_projection_rejects_missing_official_intermediate_session(
    tmp_path: Path,
) -> None:
    path = _market_fixture(
        tmp_path / "market.sqlite",
        [("20260901", 90.0), ("20260903", 100.0)],
    )
    market = _load_market_close_pairs(path)
    assert market.pair_for_decision("2026-09-07T08:30:00+08:00") is None
    assert market.pair_reason(
        "2026-09-07T08:30:00+08:00"
    ) == "official_trading_day_continuity_unproven"


def test_market_projection_rejects_missing_latest_session_before_decision(
    tmp_path: Path,
) -> None:
    path = _market_fixture(
        tmp_path / "market.sqlite",
        [("20260901", 90.0), ("20260902", 100.0)],
    )
    market = _load_market_close_pairs(path)
    assert market.pair_for_decision("2026-09-07T08:30:00+08:00") is None
    assert market.pair_reason(
        "2026-09-07T08:30:00+08:00"
    ) == "official_trading_day_gap_before_decision"


def test_publish_pointer_failure_preserves_pointer_and_retry_repairs_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeRelease:
        release_id = "v3-test-release"
        release_identity_hash = "sha256:" + "a" * 64
        artifact_hash = "sha256:" + "b" * 64

        @staticmethod
        def to_dict() -> dict[str, str]:
            return {"release_identity_hash": _FakeRelease.release_identity_hash}

    def _fake_loader(_path: Path) -> SimpleNamespace:
        return SimpleNamespace(
            manifest=SimpleNamespace(
                release_identity_hash=_FakeRelease.release_identity_hash
            )
        )

    monkeypatch.setattr(
        "ml_module.allocation_v3_linear_release.load_allocation_release",
        _fake_loader,
    )
    output_root = tmp_path / "output"
    pointer = output_root / "latest_manifest.json"
    output_root.mkdir()
    pointer.write_bytes(b"old-pointer")
    release_root = output_root / "runs" / _FakeRelease.release_id
    with pytest.raises(RuntimeError, match="injected publish failure"):
        _publish_release(
            release_root=release_root,
            output_root=output_root,
            release=_FakeRelease(),  # type: ignore[arg-type]
            artifact_bytes=b"artifact",
            preprocessor_bytes=b"{}",
            calibrator_bytes=b"{}",
            training_bytes=b"{}",
            baseline_bytes=directory_size_bytes(output_root),
            failure_inject_stage="pointer",
        )
    assert pointer.read_bytes() == b"old-pointer"
    assert release_root.is_dir()
    artifact_before_retry = (release_root / "model.joblib").read_bytes()

    repaired = _publish_release(
        release_root=release_root,
        output_root=output_root,
        release=_FakeRelease(),  # type: ignore[arg-type]
        artifact_bytes=b"artifact",
        preprocessor_bytes=b"{}",
        calibrator_bytes=b"{}",
        training_bytes=b"{}",
        baseline_bytes=directory_size_bytes(output_root),
    )
    assert repaired["status"] == "existing_release_reused"
    assert repaired["latest_pointer_repaired"] is True
    assert (release_root / "model.joblib").read_bytes() == artifact_before_retry
    latest = json.loads(pointer.read_text(encoding="utf-8"))
    assert latest["release_id"] == _FakeRelease.release_id


def test_v3_input_rejects_missing_or_legacy_feature_contract() -> None:
    features = []
    for index in range(60):
        family = (
            "data_quality"
            if index < 10
            else "market_sector_cross_section"
            if index < 21
            else "price_liquidity_technical"
        )
        features.append(
            SimpleNamespace(
                feature_id=f"f{index}",
                family_id=family,
            )
        )
    row = SimpleNamespace(
        row_id="row-0",
        symbol="0000",
        decision_at="2026-09-07T18:00:00+08:00",
        features=tuple(features),
        dataset_identity_hash="sha256:" + "b" * 64,
        feature_registry_hash="sha256:" + "a" * 64,
        source_manifest_hashes=(("source", "sha256:" + "c" * 64),),
        targets=None,
    )
    # The validator requires the concrete frozen derived IDs, so a generic
    # 60-column payload is rejected rather than silently treated as v3.
    with pytest.raises(ValueError, match="derived market changes"):
        _validate_v3_rows(
            (row,),
            {"feature_contract_hash": "sha256:" + "a" * 64},
        )
