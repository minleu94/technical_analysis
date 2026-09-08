from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from typing import Any, cast
from zoneinfo import ZoneInfo

import joblib
import numpy as np
import pytest

from app_module.allocation_release_adapter import AllocationReleaseAdapter
from app_module.ml_allocation_inference_service import (
    MLAllocationInferenceService,
    _rank_bp,
    _predict_probability_array,
)
from ml_module.allocation_contracts import (
    AllocationWeightContract,
    CausalPortfolioState,
    PITFeatureValue,
    PortfolioMLDatasetRow,
)
from ml_module.allocation_ooc_release_builder import (
    AllocationDerivedOOCReleaseRequest,
    AllocationOOCReleaseRequest,
    build_allocation_derived_ooc_release,
    build_allocation_ooc_release,
    preflight_allocation_derived_ooc_release,
    _rebuild_rank_column,
)
from ml_module.allocation_release_contract import (
    IntegerProbabilityCalibrator,
)
from ml_module.allocation_training_service import (
    CLASSIFICATION_EXPERT_HEADS,
    EXPERT_HEAD_IDS,
    EXPERT_VECTOR_WIDTH,
    REGRESSION_EXPERT_HEADS,
)
from ml_module.allocation_rank_contract import (
    RANK_CONTRACT_V1,
    RANK_CONTRACT_V2,
)
from ml_module.allocation_family_weight_contract import (
    FAMILY_WEIGHT_POLICY_DEGENERATE_EQUAL_V1,
    FAMILY_WEIGHT_STATUS_DEGENERATE_UNIDENTIFIED_EQUAL,
)
from ml_module.allocation_out_of_core_training_service import (
    AllocationOutOfCoreTrainingRequest,
    AllocationOutOfCoreTrainingService,
    _NumericStore,
    _LinearBoundaryModel,
    _quantize_head,
    _quantize_non_negative,
    _quantize_probability,
    _quantize_signed,
)
from data_module.portfolio_ml_out_of_core_store import TARGET_FIELDS
from data_module.ml_storage_capacity import BYTES_PER_GIB, StorageCapacityError


pytest_plugins = ("tests.test_portfolio_ml_out_of_core_pipeline",)

_TAIPEI = ZoneInfo("Asia/Taipei")
_HASH = "sha256:" + ("a" * 64)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _write_rehashed_manifest(path: Path, payload: dict[str, Any]) -> Path:
    body = dict(payload)
    body.pop("manifest_hash", None)
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    body["manifest_hash"] = "sha256:" + hashlib.sha256(encoded).hexdigest()
    path.write_text(
        json.dumps(body, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return path


def _latest_store_refs(store_manifest_path: Path) -> np.ndarray:
    store = _read_json(store_manifest_path)
    year = store["years"][-1]
    year_directory = store_manifest_path.parent / f"year={int(year['year']):04d}"
    with sqlite3.connect(year_directory / "rows.sqlite") as connection:
        records = connection.execute(
            "SELECT local_row_index FROM rows ORDER BY local_row_index DESC LIMIT 2"
        ).fetchall()
    return np.asarray(
        [
            [int(year["year_ordinal"]), int(local_index)]
            for (local_index,) in reversed(records)
        ],
        dtype=np.int64,
    )


def _rows_from_store(store_manifest_path: Path) -> tuple[PortfolioMLDatasetRow, ...]:
    store = _read_json(store_manifest_path)
    year = store["years"][-1]
    year_directory = store_manifest_path.parent / f"year={int(year['year']):04d}"
    with sqlite3.connect(year_directory / "rows.sqlite") as connection:
        records = connection.execute(
            "SELECT local_row_index, row_id FROM rows ORDER BY local_row_index DESC LIMIT 2"
        ).fetchall()
    values = np.memmap(
        year_directory / "features.values.i64",
        dtype="<i8",
        mode="r",
        shape=(int(year["row_count"]), len(store["feature_ids"])),
    )
    masks = np.memmap(
        year_directory / "features.masks.u8",
        dtype="u1",
        mode="r",
        shape=(int(year["row_count"]), len(store["feature_ids"])),
    )
    source_hashes = tuple(tuple(item) for item in store["source_manifest_hashes"])
    decision_at = datetime.combine(
        date(2026, 4, 2), time(8, 30), tzinfo=_TAIPEI
    ).isoformat()
    state = CausalPortfolioState.create(
        as_of_date="2026-04-01",
        weights=AllocationWeightContract(positions_bp=(), cash_bp=10_000),
        weekly_turnover_used_bp=0,
    )
    rows: list[PortfolioMLDatasetRow] = []
    for index, (local_index, source_row_id) in enumerate(reversed(records)):
        features: list[PITFeatureValue] = []
        missing_families: set[str] = set()
        for feature_index, feature_id in enumerate(store["feature_ids"]):
            pack_id = next(
                item["pack_id"]
                for item in store["feature_packs"]
                if feature_id in item["feature_ids"]
            )
            observed = int(masks[int(local_index), feature_index]) == 0
            if not observed:
                missing_families.add(pack_id)
            features.append(
                PITFeatureValue(
                    feature_id=feature_id,
                    family_id=pack_id,
                    source_id=source_hashes[0][0],
                    value_int=(
                        int(values[int(local_index), feature_index])
                        if observed
                        else None
                    ),
                    scale=int(store["feature_scales"][feature_index]),
                    event_at="2026-04-01",
                    available_at="2026-04-01T16:00:00+08:00",
                    revision_id=f"fixture:{source_row_id}:{feature_id}",
                    quality="observed" if observed else "missing",
                    content_hash=_HASH,
                    observed=observed,
                )
            )
        rows.append(
            PortfolioMLDatasetRow(
                row_id=f"release-fixture-{index}",
                decision_at=decision_at,
                symbol=str(source_row_id).split(":")[-1],
                features=tuple(features),
                missing_family_ids=tuple(sorted(missing_families)),
                portfolio_state=state,
                dataset_identity_hash=store["dataset_identity_hash"],
                feature_registry_hash=store["feature_registry_hash"],
                source_manifest_hashes=source_hashes,
                targets=None,
            )
        )
    del values, masks
    return tuple(rows)


def _minimal_training_manifest(bounded_e2e, root: Path) -> Path:
    publication = AllocationOutOfCoreTrainingService().train(
        AllocationOutOfCoreTrainingRequest(
            store_manifest_path=bounded_e2e.store_manifest_path,
            output_root=root,
            algorithms=("ridge_logistic",),
            horizons=(5,),
            batch_size=17,
            workers=1,
            memory_budget_mb=1_024,
            logistic_iterations=2,
            training_profile="minimal_linear_shadow",
            complexity_policy={
                "algorithm_count": 1,
                "horizon_count": 1,
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
            },
        )
    )
    return publication.manifest_path


def _load_ooc_artifact(
    training_manifest_path: Path,
    summary: dict[str, Any],
) -> tuple[dict[str, Any], Path]:
    directory = (
        training_manifest_path.parent
        / str(summary["artifact_path"])
    ).resolve()
    artifact = _read_json(directory / "manifest.json")
    return artifact, directory


def _ooc_rank(
    rows: tuple[PortfolioMLDatasetRow, ...],
    values: dict[str, int],
) -> dict[str, int]:
    ordered = sorted(
        (
            values[row.row_id],
            row.symbol,
            row.row_id,
        )
        for row in rows
    )
    if len(ordered) == 1:
        return {ordered[0][2]: 5_000}
    denominator = len(ordered) - 1
    return {
        row_id: (rank * 10_000) // denominator
        for rank, (_value, _symbol, row_id) in enumerate(ordered)
    }


def _round_ooc_ratio(numerator: int, denominator: int) -> int:
    return int(
        (Decimal(numerator) / Decimal(denominator)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_EVEN,
        )
    )


def _head_int(value: int | None) -> int:
    if value is None:
        raise AssertionError("expected fitted OOC head value")
    return value


def _audit_meta_vector(
    audit: dict[str, Any],
    expert_keys: tuple[str, ...],
) -> tuple[int, ...]:
    values: list[int] = []
    base_outputs = audit["base_expert_outputs"]
    for expert_id in expert_keys:
        output = base_outputs[expert_id]
        values.extend(
            [
                int(output["expected_excess_return_bp"]),
                int(output["expected_sector_excess_return_bp"] or 0),
                int(output["predicted_mae_bp"]),
                int(output["predicted_mfe_bp"]),
                int(output["predicted_realized_volatility_bp"]),
                int(output["predicted_max_drawdown_bp"]),
                int(output["predicted_tail_loss_bp"]),
                int(output["uncalibrated_downside_probability_bp"]),
                int(output["fill_feasibility_probability_bp"]),
                int(output["rank_bp"]),
            ]
        )
        missing = set(output["missing_head_ids"])
        values.extend(int(head_id in missing) for head_id in EXPERT_HEAD_IDS)
    return tuple(values)


def _independent_ooc_outputs(
    *,
    training_manifest_path: Path,
    store_manifest_path: Path,
    rows: tuple[PortfolioMLDatasetRow, ...],
    calibrator: IntegerProbabilityCalibrator,
) -> tuple[
    dict[str, dict[str, dict[str, object]]],
    dict[str, dict[str, object]],
    dict[str, dict[str, dict[str, int]]],
    dict[str, tuple[int, ...]],
]:
    """以 frozen numeric batch 獨立重播 base head 與原始 meta pipeline。"""

    training = _read_json(training_manifest_path)
    store = _NumericStore(store_manifest_path)
    refs = _latest_store_refs(store_manifest_path)
    assert refs.shape == (len(rows), 2)
    packs = tuple(store.feature_packs)
    horizon = int(training["horizons"][0])
    expert_keys = tuple(
        f"{pack['pack_id']}|h{horizon}|ridge_logistic"
        for pack in packs
    )
    final_summaries = {
        str(summary["expert_id"]): summary
        for summary in training["final_base_experts"]
    }
    expected_base: dict[str, dict[str, dict[str, object]]] = {
        row.row_id: {} for row in rows
    }
    vectors: dict[str, tuple[int, ...]] = {}

    for pack in packs:
        pack_id = str(pack["pack_id"])
        expert_id = f"{pack_id}|h{horizon}|ridge_logistic"
        artifact, directory = _load_ooc_artifact(
            training_manifest_path,
            final_summaries[expert_id],
        )
        records = {
            str(record["head_id"]): record
            for record in artifact["head_models"]
        }
        positions = store.feature_positions_for_pack(pack)
        # 這是 OOC ``_LinearBoundaryModel.predict_numeric`` 實際消費的
        # persisted float32 batch；expected head value 不經 daily service 計算。
        matrix = np.asarray(
            store.read_feature_batch(refs, positions),
            dtype=np.float32,
        )
        head_values: dict[str, list[int | None]] = {}
        missing_head_ids = tuple(
            sorted(
                str(head_id)
                for head_id, record in records.items()
                if record["status"] == "missing"
            )
        )
        for head_id in EXPERT_HEAD_IDS:
            record = records[head_id]
            if record["status"] == "missing":
                head_values[head_id] = [
                    None if head_id == "expected_sector_excess_return_bp" else 0
                    for _row in rows
                ]
                continue
            model = joblib.load(directory / str(record["path"]))
            raw_values = np.asarray(
                model.predict_numeric(matrix),
                dtype=np.float64,
            )
            head_values[head_id] = [
                int(value)
                for value in _quantize_head(
                    head_id=head_id,
                    values=raw_values,
                )
            ]

        active_indexes = [
            index
            for index, row in enumerate(rows)
            if any(
                feature.observed
                for feature in row.features
                if feature.family_id == pack_id
            )
        ]
        rank_values = {
            rows[index].row_id: _head_int(
                head_values["expected_excess_return_bp"][index]
            )
            for index in active_indexes
        }
        rank_by_row_id = _ooc_rank(
            tuple(rows[index] for index in active_indexes),
            rank_values,
        )
        for index, row in enumerate(rows):
            if index not in active_indexes:
                expected_base[row.row_id][expert_id] = {
                    "expected_excess_return_bp": 0,
                    "expected_sector_excess_return_bp": None,
                    "downside_probability_bp": 5_000,
                    "uncalibrated_downside_probability_bp": 5_000,
                    "predicted_mae_bp": 10_000,
                    "predicted_mfe_bp": 0,
                    "predicted_realized_volatility_bp": 10_000,
                    "predicted_max_drawdown_bp": 10_000,
                    "predicted_tail_loss_bp": 10_000,
                    "fill_feasibility_probability_bp": 5_000,
                    "rank_bp": 5_000,
                    "missing_head_ids": list(EXPERT_HEAD_IDS),
                    "neutral_fallback": True,
                }
                continue
            raw_downside = _head_int(
                head_values["downside_probability_bp"][index]
            )
            expected_base[row.row_id][expert_id] = {
                "expected_excess_return_bp": _head_int(
                    head_values["expected_excess_return_bp"][index]
                ),
                "expected_sector_excess_return_bp": (
                    None
                    if head_values["expected_sector_excess_return_bp"][index]
                    is None
                    else _head_int(
                        head_values["expected_sector_excess_return_bp"][index]
                    )
                ),
                "downside_probability_bp": calibrator.calibrate_bp(raw_downside),
                "uncalibrated_downside_probability_bp": raw_downside,
                "predicted_mae_bp": _head_int(
                    head_values["predicted_mae_bp"][index]
                ),
                "predicted_mfe_bp": _head_int(
                    head_values["predicted_mfe_bp"][index]
                ),
                "predicted_realized_volatility_bp": _head_int(
                    head_values["predicted_realized_volatility_bp"][index]
                ),
                "predicted_max_drawdown_bp": _head_int(
                    head_values["predicted_max_drawdown_bp"][index]
                ),
                "predicted_tail_loss_bp": _head_int(
                    head_values["predicted_tail_loss_bp"][index]
                ),
                "fill_feasibility_probability_bp": _head_int(
                    head_values["fill_feasibility_probability_bp"][index]
                ),
                "rank_bp": rank_by_row_id[row.row_id],
                "missing_head_ids": list(missing_head_ids),
                "neutral_fallback": False,
            }

    family_weights = {
        str(item["family_id"]): int(item["weight_bp"])
        for item in _load_ooc_artifact(
            training_manifest_path,
            training["final_meta"],
        )[0]["feature_family_weights_bp"]
    }
    for row in rows:
        vector_values: list[int] = []
        for expert_id in expert_keys:
            output = expected_base[row.row_id][expert_id]
            vector_values.extend(
                [
                    cast(int, output["expected_excess_return_bp"]),
                    cast(int, output["expected_sector_excess_return_bp"] or 0),
                    cast(int, output["predicted_mae_bp"]),
                    cast(int, output["predicted_mfe_bp"]),
                    cast(int, output["predicted_realized_volatility_bp"]),
                    cast(int, output["predicted_max_drawdown_bp"]),
                    cast(int, output["predicted_tail_loss_bp"]),
                    cast(int, output["uncalibrated_downside_probability_bp"]),
                    cast(int, output["fill_feasibility_probability_bp"]),
                    cast(int, output["rank_bp"]),
                ]
            )
            missing = set(cast(list[str], output["missing_head_ids"]))
            vector_values.extend(
                int(head_id in missing) for head_id in EXPERT_HEAD_IDS
            )
        assert len(vector_values) == len(expert_keys) * EXPERT_VECTOR_WIDTH
        vectors[row.row_id] = tuple(vector_values)

    meta_artifact, meta_directory = _load_ooc_artifact(
        training_manifest_path,
        training["final_meta"],
    )
    meta_records = {
        str(record["head_id"]): record
        for record in meta_artifact["head_models"]
    }
    meta_models = {
        field_name: joblib.load(meta_directory / str(meta_records[field_name]["path"]))
        for field_name in TARGET_FIELDS
    }
    active_rows = tuple(
        row
        for row in rows
        if any(
            output["neutral_fallback"] is False
            for output in expected_base[row.row_id].values()
        )
    )
    meta_matrix = np.asarray(
        [vectors[row.row_id] for row in active_rows],
        dtype=np.float32,
    )
    expected_meta: dict[str, dict[str, object]] = {
        row.row_id: {
            "target_weight_bp": 0,
            "delta_weight_bp": 0,
            "risk_contribution_bp": 0,
            "risky_budget_bp": 0,
            "cash_bp": 10_000,
            "rebalance_probability_bp": 0,
            "rebalance_worthwhile": False,
        }
        for row in rows
        if row not in active_rows
    }
    for index, row in enumerate(active_rows):
        values: dict[str, int] = {}
        for field_name in TARGET_FIELDS[:5]:
            raw = np.asarray(
                meta_models[field_name].predict_numeric(meta_matrix[index : index + 1]),
                dtype=np.float64,
            )
            if field_name == "delta_weight_bp":
                values[field_name] = int(_quantize_signed(raw)[0])
            else:
                values[field_name] = int(_quantize_non_negative(raw)[0])
        rebalance_raw = np.asarray(
            meta_models["rebalance_worthwhile"].predict_numeric(
                meta_matrix[index : index + 1]
            ),
            dtype=np.float64,
        )
        rebalance_bp = int(_quantize_probability(rebalance_raw)[0])
        expected_meta[row.row_id] = {
            **values,
            "rebalance_probability_bp": rebalance_bp,
            "rebalance_worthwhile": rebalance_bp >= 5_000,
        }

    expected_horizon: dict[str, dict[str, dict[str, int]]] = {}
    for row in rows:
        eligible = [
            (
                family_weights[expert_id.split("|", 1)[0]],
                expected_base[row.row_id][expert_id],
            )
            for expert_id in expert_keys
            if expected_base[row.row_id][expert_id]["neutral_fallback"] is False
        ]
        if not eligible:
            calibrated = uncalibrated = 5_000
        else:
            denominator = sum(weight for weight, _output in eligible)
            calibrated = _round_ooc_ratio(
                sum(
                    weight * cast(int, output["downside_probability_bp"])
                    for weight, output in eligible
                ),
                denominator,
            )
            uncalibrated = _round_ooc_ratio(
                sum(
                    weight
                    * cast(
                        int,
                        output["uncalibrated_downside_probability_bp"],
                    )
                    for weight, output in eligible
                ),
                denominator,
            )
        expected_horizon[row.row_id] = {
            str(horizon): {
                "calibrated_downside_probability_bp": calibrated,
                "uncalibrated_downside_probability_bp": uncalibrated,
            }
        }
    return expected_base, expected_meta, expected_horizon, vectors


def test_minimal_ooc_release_attaches_calibrator_and_matches_direct_consumer(
    bounded_e2e,
    tmp_path: Path,
) -> None:
    training_manifest = _minimal_training_manifest(bounded_e2e, tmp_path / "minimal")
    release = build_allocation_ooc_release(
        AllocationOOCReleaseRequest(
            training_manifest_path=training_manifest,
            output_root=tmp_path / "release",
            model_id="fixture-linear-release",
            policy_id="fixture-policy",
            batch_size=17,
        )
    )
    loaded = AllocationReleaseAdapter().load(
        release.release_root,
        expected_release_identity_hash=release.release_identity_hash,
    )
    rows = _rows_from_store(bounded_e2e.store_manifest_path)
    artifact_payload = joblib.load(BytesIO(release.model_artifact_path.read_bytes()))
    assert artifact_payload["meta_probability_input"] == "raw_oof"
    assert artifact_payload["training_profile"] == "minimal_linear_shadow"
    assert artifact_payload["complexity_policy"] == {
        "algorithm_count": 1,
        "horizon_count": 1,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
    }
    policy_hash = loaded.manifest.missing_policy.policy_hash
    result = loaded.infer(
        rows=rows,
        universe_id="fixture-universe",
        policy_hash=policy_hash,
    )
    calibrator = IntegerProbabilityCalibrator.from_dict(
        _read_json(release.release_root / "calibrator.json")
    )
    assert calibrator.fit_fold_ids == release.calibration_fit_fold_ids
    assert calibrator.oof_diagnostic_only is False
    assert calibrator.diagnostic_only is False
    assert release.calibration_fit_row_count > 0
    assert all(
            output["downside_probability_bp"]
        == calibrator.calibrate_bp(
            output["uncalibrated_downside_probability_bp"]
        )
        for audit in result.audit_payload()["row_audits"]
        for output in audit["base_expert_outputs"].values()
    )

    # 這個 service 只用 release artifact 的 raw numeric head，刻意不掛
    # calibrator；若 meta 仍得到相同輸出，即證明 calibrated bp 沒有被送進
    # 以 raw OOF vector fit 的 final meta。
    raw_result = MLAllocationInferenceService.from_artifact_path(
        release.model_artifact_path,
        expected_artifact_hash=release.model_artifact_hash,
        expected_dataset_id=loaded.dataset_id,
    ).infer(
        rows=rows,
        model_id=loaded.model_id,
        universe_id="fixture-universe",
        policy_id=loaded.manifest.missing_policy.policy_id,
        policy_hash=policy_hash,
    )
    result_audits = {
        str(audit["row_id"]): audit
        for audit in result.audit_payload()["row_audits"]
    }
    raw_audits = {
        str(audit["row_id"]): audit
        for audit in raw_result.audit_payload()["row_audits"]
    }
    assert all(
        result_audits[row_id]["meta_output"]
        == raw_audits[row_id]["meta_output"]
        for row_id in result_audits
    )

    (
        expected_base,
        expected_meta,
        expected_horizon,
        expected_vectors,
    ) = _independent_ooc_outputs(
        training_manifest_path=training_manifest,
        store_manifest_path=bounded_e2e.store_manifest_path,
        rows=rows,
        calibrator=calibrator,
    )
    assert all(
        len(vector) == EXPERT_VECTOR_WIDTH * len(expected_base[row_id])
        for row_id, vector in expected_vectors.items()
    )
    for row_id in expected_base:
        expert_keys = tuple(expected_base[row_id])
        assert _audit_meta_vector(result_audits[row_id], expert_keys) == expected_vectors[row_id]
        assert result_audits[row_id]["base_expert_outputs"] == expected_base[row_id]
        assert (
            result_audits[row_id]["meta_output"]
            == expected_meta[row_id]
        )
        assert (
            result_audits[row_id]["downside_probability_by_horizon_bp"]
            == expected_horizon[row_id]
        )

    independent_ooc_audits = [
        {
            "row_id": row_id,
            "base_expert_outputs": expected_base[row_id],
            "downside_probability_by_horizon_bp": expected_horizon[row_id],
            "meta_output": expected_meta[row_id],
        }
        for row_id in sorted(expected_base)
    ]
    parity = loaded.validate_frozen_rows(
        rows=rows,
        ooc_outputs={"row_audits": independent_ooc_audits},
        universe_id="fixture-universe",
        policy_hash=policy_hash,
    )
    assert parity.matched
    assert parity.row_count == len(rows)


def test_minimal_ooc_release_rejects_unbound_profile(
    bounded_e2e,
    tmp_path: Path,
) -> None:
    training_manifest_path = _minimal_training_manifest(
        bounded_e2e,
        tmp_path / "minimal",
    )
    training = _read_json(training_manifest_path)
    training["training_profile"] = "full_shadow"
    body = dict(training)
    body.pop("manifest_hash", None)
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    training["manifest_hash"] = "sha256:" + hashlib.sha256(encoded).hexdigest()
    poisoned = training_manifest_path.parent / "poisoned-manifest.json"
    poisoned.write_text(json.dumps(training), encoding="utf-8")
    with pytest.raises(ValueError, match="minimal_linear_shadow profile"):
        build_allocation_ooc_release(
            AllocationOOCReleaseRequest(
                training_manifest_path=poisoned,
                output_root=tmp_path / "release",
            )
        )


def test_derived_h5_release_retrains_causal_meta_and_replays_withheld_fold(
    bounded_e2e,
    tmp_path: Path,
) -> None:
    request = AllocationDerivedOOCReleaseRequest(
        parent_training_manifest_path=bounded_e2e.ridge_manifest_path,
        output_root=tmp_path / "derived-release",
        model_id="fixture-derived-h5-release",
        policy_id="fixture-derived-policy",
        batch_size=31,
        memory_budget_mb=1_024,
        safety_reserve_bytes=1,
        acquire_heavy_lock=False,
    )
    preflight = preflight_allocation_derived_ooc_release(request)
    assert preflight["status"] == "preflight_passed"
    assert preflight["selected_fold_ids"][-1] == preflight["heldout_fold_id"]
    source_preflight = preflight["capacity_preflight"][
        "source_drive_preflight"
    ]
    assert source_preflight["within_budget"] is True
    assert preflight["capacity_preflight"]["all_probe_within_budget"] is True

    publication = build_allocation_derived_ooc_release(request)
    parent = _read_json(bounded_e2e.ridge_manifest_path)
    derived = _read_json(publication.derived_manifest_path)
    lineage = derived["selection_lineage"]
    assert derived["parent_training_manifest_hash"] == parent["manifest_hash"]
    assert derived["training_profile"] == "derived_linear_shadow"
    assert derived["algorithms"] == ["ridge_logistic"]
    assert derived["horizons"] == [5]
    assert lineage["parent_training_manifest_hash"] == parent["manifest_hash"]
    assert lineage["parent_final_meta_reused"] is False
    assert lineage["meta_fit_fold_ids"] == lineage["selected_fold_ids"][:-1]
    assert lineage["calibration_fit_fold_ids"] == lineage["selected_fold_ids"][:-1]
    assert lineage["heldout_fold_id"] == lineage["selected_fold_ids"][-1]
    assert lineage["meta_probability_input"] == "raw_oof"
    assert derived["final_meta_training_row_count"] == derived[
        "meta_artifacts"
    ]["final"]["train_row_count"]
    assert publication.meta_fit_row_count > 1
    assert publication.calibration_fit_row_count > 1
    assert publication.calibration_fit_fold_ids
    assert publication.heldout_fold_id not in publication.calibration_fit_fold_ids

    heldout = _read_json(publication.heldout_evaluation_path)
    assert heldout["heldout_fold_id"] == publication.heldout_fold_id
    assert heldout["base_oof_replay_matched"] is True
    assert heldout["meta_oof_replay_matched"] is True
    assert heldout["final_base_not_used"] is True
    assert heldout["final_meta_not_used"] is True
    assert heldout["target_fold_label_reads"] == 0
    assert heldout["target_fold_excluded_from_meta_fit"] is True
    assert heldout["target_fold_excluded_from_calibration"] is True

    model_payload = joblib.load(BytesIO(publication.model_artifact_path.read_bytes()))
    assert model_payload["training_profile"] == "derived_linear_shadow"
    assert model_payload["meta_probability_input"] == "raw_oof"
    assert model_payload["complexity_policy"] == {
        "algorithm_count": 1,
        "horizon_count": 1,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
    }
    loaded = AllocationReleaseAdapter().load(
        publication.release_root,
        expected_release_identity_hash=publication.release_identity_hash,
    )
    calibrator = IntegerProbabilityCalibrator.from_dict(
        _read_json(publication.release_root / "calibrator.json")
    )
    assert calibrator.oof_diagnostic_only is False
    assert calibrator.diagnostic_only is False
    assert calibrator.fit_fold_ids == publication.calibration_fit_fold_ids
    rows = _rows_from_store(bounded_e2e.store_manifest_path)
    policy_hash = loaded.manifest.missing_policy.policy_hash
    calibrated_result = loaded.infer(
        rows=rows,
        universe_id="fixture-derived-universe",
        policy_hash=policy_hash,
    )
    raw_result = MLAllocationInferenceService.from_artifact_path(
        publication.model_artifact_path,
        expected_artifact_hash=publication.model_artifact_hash,
        expected_dataset_id=loaded.dataset_id,
    ).infer(
        rows=rows,
        model_id=loaded.model_id,
        universe_id="fixture-derived-universe",
        policy_id=loaded.manifest.missing_policy.policy_id,
        policy_hash=policy_hash,
    )
    calibrated_audits = {
        str(item["row_id"]): item
        for item in calibrated_result.audit_payload()["row_audits"]
    }
    raw_audits = {
        str(item["row_id"]): item
        for item in raw_result.audit_payload()["row_audits"]
    }
    assert calibrated_audits.keys() == raw_audits.keys()
    assert all(
        calibrated_audits[row_id]["meta_output"]
        == raw_audits[row_id]["meta_output"]
        for row_id in calibrated_audits
    )
    assert all(
        output["downside_probability_bp"]
        == calibrator.calibrate_bp(
            output["uncalibrated_downside_probability_bp"]
        )
        for audit in calibrated_audits.values()
        for output in audit["base_expert_outputs"].values()
    )


def test_derived_v2_rank_contract_fits_replays_and_preserves_parent(
    bounded_e2e,
    tmp_path: Path,
) -> None:
    """V2 rank 必須在 derived fit、heldout replay、daily consumer 一致。"""

    parent_bytes = bounded_e2e.ridge_manifest_path.read_bytes()
    request = AllocationDerivedOOCReleaseRequest(
        parent_training_manifest_path=bounded_e2e.ridge_manifest_path,
        output_root=tmp_path / "derived-v2-release",
        model_id="fixture-derived-v2-rank-release",
        policy_id="fixture-derived-v2-policy",
        batch_size=31,
        memory_budget_mb=1_024,
        safety_reserve_bytes=1,
        acquire_heavy_lock=False,
        rank_contract=RANK_CONTRACT_V2,
        family_weight_policy=FAMILY_WEIGHT_POLICY_DEGENERATE_EQUAL_V1,
    )
    preflight = preflight_allocation_derived_ooc_release(request)
    assert preflight["parent_rank_contract"] == RANK_CONTRACT_V1
    assert preflight["rank_contract"] == RANK_CONTRACT_V2
    assert (
        preflight["family_weight_policy"]
        == FAMILY_WEIGHT_POLICY_DEGENERATE_EQUAL_V1
    )

    publication = build_allocation_derived_ooc_release(request)
    parent = _read_json(bounded_e2e.ridge_manifest_path)
    derived = _read_json(publication.derived_manifest_path)
    assert bounded_e2e.ridge_manifest_path.read_bytes() == parent_bytes
    assert parent["manifest_hash"] == bounded_e2e.ridge_manifest_hash
    assert derived["parent_training_manifest_hash"] == parent["manifest_hash"]
    assert derived["rank_contract"] == RANK_CONTRACT_V2
    assert (
        derived["family_weight_policy"]
        == FAMILY_WEIGHT_POLICY_DEGENERATE_EQUAL_V1
    )
    assert (
        derived["feature_family_weights_status"]
        == FAMILY_WEIGHT_STATUS_DEGENERATE_UNIDENTIFIED_EQUAL
    )
    assert all(
        bool(summary["constant"])
        for summary in derived["target_summary"].values()
    )
    assert sum(
        int(item["weight_bp"])
        for item in derived["meta_artifacts"]["final"][
            "feature_family_weights_bp"
        ]
    ) == 10_000
    assert derived["selection_lineage"]["parent_rank_contract"] == RANK_CONTRACT_V1
    assert derived["selection_lineage"]["rank_contract"] == RANK_CONTRACT_V2
    assert derived["selection_lineage"]["parent_final_meta_reused"] is False

    heldout = _read_json(publication.heldout_evaluation_path)
    assert heldout["rank_contract"] == RANK_CONTRACT_V2
    assert heldout["base_oof_rank_rebuilt_from_parent_heads"] is True
    assert heldout["meta_oof_replay_matched"] is True
    assert heldout["final_base_not_used"] is True
    assert heldout["final_meta_not_used"] is True
    assert heldout["target_fold_label_reads"] == 0

    model_payload = joblib.load(BytesIO(publication.model_artifact_path.read_bytes()))
    assert model_payload["rank_contract"] == RANK_CONTRACT_V2
    assert (
        model_payload["family_weight_policy"]
        == FAMILY_WEIGHT_POLICY_DEGENERATE_EQUAL_V1
    )
    assert (
        model_payload["feature_family_weights_status"]
        == FAMILY_WEIGHT_STATUS_DEGENERATE_UNIDENTIFIED_EQUAL
    )
    loaded = AllocationReleaseAdapter().load(
        publication.release_root,
        expected_release_identity_hash=publication.release_identity_hash,
    )
    rows = _rows_from_store(bounded_e2e.store_manifest_path)
    policy_hash = loaded.manifest.missing_policy.policy_hash
    consumer_result = MLAllocationInferenceService.from_artifact_path(
        publication.model_artifact_path,
        expected_artifact_hash=publication.model_artifact_hash,
        expected_dataset_id=loaded.dataset_id,
    ).infer(
        rows=rows,
        model_id=loaded.model_id,
        universe_id="fixture-derived-v2-universe",
        policy_id=loaded.manifest.missing_policy.policy_id,
        policy_hash=policy_hash,
    )
    consumer_audits = {
        str(item["row_id"]): item
        for item in consumer_result.audit_payload()["row_audits"]
    }
    for expert_id in consumer_audits[rows[0].row_id]["base_expert_outputs"]:
        predictions = tuple(
            int(
                consumer_audits[row.row_id]["base_expert_outputs"][expert_id][
                    "expected_excess_return_bp"
                ]
            )
            for row in rows
        )
        expected_ranks = _rank_bp(
            rows=rows,
            predicted_values=predictions,
            rank_contract=RANK_CONTRACT_V2,
        )
        assert {
            row_id: int(
                consumer_audits[row_id]["base_expert_outputs"][expert_id][
                    "rank_bp"
                ]
            )
            for row_id in expected_ranks
        } == expected_ranks

    # 以兩個 decision date 的 frozen row/ref 形狀驗證 derived rank 重建：
    # 同值只按 value 分組，symbol 順序不再製造虛假差異。
    class _TwoDateStore:
        def iter_decision_dates(self, _refs):
            yield (0, "2026-01-05", "row:AAA")
            yield (1, "2026-01-05", "row:BBB")
            yield (2, "2026-01-06", "row:CCC")
            yield (3, "2026-01-06", "row:DDD")

    oof = np.zeros((4, EXPERT_VECTOR_WIDTH), dtype=np.int32)
    oof[:, 0] = np.asarray((100, 100, 200, 300), dtype=np.int32)
    rebuilt = _rebuild_rank_column(
        store=cast(Any, _TwoDateStore()),
        test_refs=np.asarray(
            ((0, 0), (0, 1), (0, 2), (0, 3)),
            dtype=np.int64,
        ),
        oof=oof,
        rank_contract=RANK_CONTRACT_V2,
    )
    assert tuple(int(value) for value in rebuilt) == (5_000, 5_000, 0, 10_000)

    consumer_rows = tuple(
        SimpleNamespace(
            row_id=f"row:{symbol}",
            symbol=symbol,
            decision_at=f"{decision_date}T08:30:00+08:00",
        )
        for decision_date, symbol in (
            ("2026-01-05", "AAA"),
            ("2026-01-05", "BBB"),
            ("2026-01-06", "CCC"),
            ("2026-01-06", "DDD"),
        )
    )
    assert _rank_bp(
        rows=cast(Any, consumer_rows),
        predicted_values=(100, 100, 200, 300),
        rank_contract=RANK_CONTRACT_V2,
    ) == {
        "row:AAA": 5_000,
        "row:BBB": 5_000,
        "row:CCC": 0,
        "row:DDD": 10_000,
    }
    with pytest.raises(ValueError, match="unsupported"):
        AllocationDerivedOOCReleaseRequest(
            parent_training_manifest_path=bounded_e2e.ridge_manifest_path,
            output_root=tmp_path / "unknown-rank",
            rank_contract="allocation-rank-v9:unknown",
        )


def test_derived_release_rejects_empty_algorithm_and_partial_selected_oof(
    bounded_e2e,
    tmp_path: Path,
) -> None:
    parent_path = bounded_e2e.ridge_manifest_path
    parent = _read_json(parent_path)
    empty_algorithm = dict(parent)
    empty_algorithm["algorithms"] = []
    poisoned_empty = _write_rehashed_manifest(
        parent_path.parent / "poisoned-empty-algorithm.json",
        empty_algorithm,
    )
    with pytest.raises(ValueError, match="ridge_logistic"):
        preflight_allocation_derived_ooc_release(
            AllocationDerivedOOCReleaseRequest(
                parent_training_manifest_path=poisoned_empty,
                output_root=tmp_path / "empty-algorithm",
                safety_reserve_bytes=1,
            )
        )

    selected_fold_ids = {
        str(item["fold_id"])
        for item in _read_json(bounded_e2e.store_manifest_path)["folds"][:4]
    }
    partial = dict(parent)
    base_experts = list(parent["base_experts"])
    removed = False
    kept: list[dict[str, Any]] = []
    for summary in base_experts:
        if not removed and str(summary["fold_id"]) in selected_fold_ids:
            removed = True
            continue
        kept.append(summary)
    assert removed
    partial["base_experts"] = kept
    poisoned_partial = _write_rehashed_manifest(
        parent_path.parent / "poisoned-partial-oof.json",
        partial,
    )
    with pytest.raises(ValueError, match="coverage is incomplete"):
        preflight_allocation_derived_ooc_release(
            AllocationDerivedOOCReleaseRequest(
                parent_training_manifest_path=poisoned_partial,
                output_root=tmp_path / "partial-oof",
                safety_reserve_bytes=1,
            )
        )


def test_derived_release_capacity_preflight_fails_closed_before_write(
    bounded_e2e,
    tmp_path: Path,
) -> None:
    with pytest.raises(StorageCapacityError, match="capacity preflight"):
        preflight_allocation_derived_ooc_release(
            AllocationDerivedOOCReleaseRequest(
                parent_training_manifest_path=bounded_e2e.ridge_manifest_path,
                output_root=tmp_path / "capacity-blocked",
                persistent_new_bytes_budget=1,
                temporary_peak_bytes_budget=1,
                safety_reserve_bytes=1,
            )
        )
    assert not (tmp_path / "capacity-blocked").exists()


def test_numeric_probability_fallback_requires_classifier_contract() -> None:
    model = _LinearBoundaryModel(
        head_id="downside_probability_bp",
        medians=np.zeros(1, dtype=np.float64),
        means=np.zeros(2, dtype=np.float64),
        standard_deviations=np.ones(2, dtype=np.float64),
        coefficients=np.zeros(2, dtype=np.float64),
        intercept=0.0,
        classifier=False,
    )
    with pytest.raises(ValueError, match="not a classifier"):
        _predict_probability_array(
            model,
            np.zeros((1, 1), dtype=np.float64),
            field_name="negative.classifier",
        )
