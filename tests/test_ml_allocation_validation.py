from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
import json
from pathlib import Path

import pytest

from ml_module.allocation_validation import (
    AllocationFoldEvidence,
    AllocationPromotionEvidence,
    AllocationPromotionEvaluator,
    AllocationWalkForwardPolicy,
    AlphaLaneEvidence,
    BaseOOFPrediction,
    MetaAllocatorOOFGuard,
)
from ml_module.purged_walk_forward import MLTimeWindowRow
from ml_promotion_test_support import build_promotion_test_custody


_HASH = "sha256:" + "d" * 64
_OTHER_HASH = "sha256:" + "e" * 64


def _time_rows(count: int = 200) -> tuple[MLTimeWindowRow, ...]:
    start = date(2024, 1, 1)
    return tuple(
        MLTimeWindowRow(
            row_id=f"row-{index:03d}",
            decision_date=(start + timedelta(days=index)).isoformat(),
            label_end_date=(start + timedelta(days=index + 20)).isoformat(),
        )
        for index in range(count)
    )


def _folds():
    return AllocationWalkForwardPolicy(
        minimum_train_dates=80,
        test_date_count=10,
    ).split(_time_rows())


def _prediction(fold, row, family: str) -> BaseOOFPrediction:
    fit_row_ids = tuple(item.row_id for item in fold.train_rows)
    return BaseOOFPrediction(
        row_id=row.row_id,
        decision_date=row.decision_date,
        fold_id=fold.fold_id,
        model_family=family,
        model_id=f"model:{family}:{fold.fold_id}",
        trained_through_date=fold.train_rows[-1].decision_date,
        fit_row_ids=fit_row_ids,
        preprocessor_fit_row_ids=fit_row_ids,
        expected_excess_return_bp=125,
        downside_probability_bp=1800,
        predicted_mae_bp=250,
        rank_bp=8000,
    )


def test_allocation_split_requires_four_outer_folds_with_60_5_boundary() -> None:
    folds = _folds()

    assert len(folds) >= 4
    assert all(fold.purge_trading_days == 60 for fold in folds)
    assert all(fold.embargo_trading_days == 5 for fold in folds)
    assert all(
        row.label_end_date < fold.test_start
        for fold in folds
        for row in fold.train_rows
    )
    with pytest.raises(ValueError, match="four usable outer folds"):
        AllocationWalkForwardPolicy(
            minimum_train_dates=80,
            test_date_count=10,
        ).split(_time_rows(120))


def test_meta_allocator_bundle_accepts_only_outer_fold_oof_predictions() -> None:
    folds = _folds()[:4]
    predictions = tuple(
        _prediction(fold, fold.test_rows[0], family)
        for fold in folds
        for family in ("price_expert", "fundamental_expert")
    )

    bundle = MetaAllocatorOOFGuard().build(
        predictions=predictions,
        folds=folds,
        required_model_families=("price_expert", "fundamental_expert"),
    )

    assert bundle.oof_only is True
    assert len(bundle.fold_ids) == 4
    assert bundle.model_families == ("fundamental_expert", "price_expert")
    assert bundle.bundle_hash.startswith("sha256:")


def test_meta_allocator_rejects_train_rows_future_fit_and_incomplete_experts() -> None:
    folds = _folds()[:4]
    valid = tuple(
        _prediction(fold, fold.test_rows[0], "price_expert")
        for fold in folds
    )
    train_row_prediction = replace(
        valid[0],
        row_id=folds[0].train_rows[0].row_id,
        decision_date=folds[0].train_rows[0].decision_date,
    )
    with pytest.raises(ValueError, match="non-OOF"):
        MetaAllocatorOOFGuard().build(
            predictions=(train_row_prediction, *valid[1:]),
            folds=folds,
        )

    leaked = replace(valid[0], trained_through_date=folds[0].test_start)
    with pytest.raises(ValueError, match="latest model fit row"):
        MetaAllocatorOOFGuard().build(
            predictions=(leaked, *valid[1:]),
            folds=folds,
        )

    contaminated = replace(
        valid[0],
        fit_row_ids=(*valid[0].fit_row_ids, folds[0].test_rows[0].row_id),
        preprocessor_fit_row_ids=(
            *valid[0].preprocessor_fit_row_ids,
            folds[0].test_rows[0].row_id,
        ),
    )
    with pytest.raises(ValueError, match="outer train fold"):
        MetaAllocatorOOFGuard().build(
            predictions=(contaminated, *valid[1:]),
            folds=folds,
        )

    preprocessing_leak = replace(
        valid[0],
        preprocessor_fit_row_ids=valid[0].preprocessor_fit_row_ids[:-1],
    )
    with pytest.raises(ValueError, match="preprocessor fit rows"):
        MetaAllocatorOOFGuard().build(
            predictions=(preprocessing_leak, *valid[1:]),
            folds=folds,
        )

    incomplete = (
        *valid,
        _prediction(
            folds[0],
            folds[0].test_rows[0],
            "fundamental_expert",
        ),
    )
    with pytest.raises(ValueError, match="every required base family"):
        MetaAllocatorOOFGuard().build(
            predictions=incomplete,
            folds=folds,
        )


def _lane(alpha_bp: int, **overrides: object) -> AlphaLaneEvidence:
    values: dict[str, object] = {
        "alpha_bp": alpha_bp,
        "pit_violation_count": 0,
        "future_prefix_violation_count": 0,
        "constraint_violation_count": 0,
        "replay_hash_pairs": ((_HASH, _HASH),),
        "folds": (
            AllocationFoldEvidence("fold-001", 20),
            AllocationFoldEvidence("fold-002", 10),
            AllocationFoldEvidence("fold-003", 5),
            AllocationFoldEvidence("fold-004", -1),
        ),
        "bootstrap_lower_bound_bp": 0,
        "calibration_ece_bp": 500,
        "calibrated_brier_bp": 1200,
        "uncalibrated_brier_bp": 1200,
        "psi_bp": 2499,
        "core_coverage_bp": 9500,
        "enriched_coverage_bp": 9000,
        "feasible_fill_coverage_bp": 9500,
        "mdd_worsening_vs_rule_bp": 100,
        "cvar_worsening_vs_rule_bp": 100,
        "weekly_turnover_bp": 2000,
        "turnover_increment_vs_rule_bp": 500,
        "shadow_observed_days": 20,
    }
    values.update(overrides)
    return AlphaLaneEvidence(**values)  # type: ignore[arg-type]


def _evidence(
    *,
    lane_2000: AlphaLaneEvidence | None = None,
    lane_3500: AlphaLaneEvidence | None = None,
    lane_5000: AlphaLaneEvidence | None = None,
) -> AllocationPromotionEvidence:
    return AllocationPromotionEvidence(
        experiment_id="experiment:v4-allocation",
        model_id="model:v4-allocation",
        dataset_id="dataset:v4-all-field",
        model_artifact_hash=_HASH,
        dataset_identity_hash=_OTHER_HASH,
        dataset_manifest_file_hash=_HASH,
        oof_bundle_hash=_HASH,
        shadow_evidence_hash=_OTHER_HASH,
        lanes=(
            _lane(0),
            lane_2000 or _lane(2000),
            lane_3500 or _lane(3500),
            lane_5000 or _lane(5000),
        ),
    )


def test_promotion_selects_smallest_passing_lane_but_needs_authorization_artifact(
    tmp_path: Path,
) -> None:
    evidence = _evidence()
    evaluator = AllocationPromotionEvaluator()

    preview = evaluator.evaluate(evidence)

    assert preview.eligible_alpha_bp == 2000
    assert preview.formal_oos_allowed is False
    assert preview.production_blend_alpha_bp == 0
    assert preview.blockers == ("promotion_authorization_artifact_required",)

    custody = build_promotion_test_custody(
        tmp_path,
        evidence=evidence,
        evaluator=evaluator,
        authorized_alpha_bp=2000,
    )
    verification = custody.verify(
        decision_at=datetime.fromisoformat("2026-07-29T08:30:00+08:00"),
        evaluator=evaluator,
    )
    assert (
        custody.evidence.dataset_identity_hash
        != custody.evidence.dataset_manifest_file_hash
    )
    assert custody.authorization.dataset_identity_hash == (
        custody.evidence.dataset_identity_hash
    )
    assert custody.authorization.dataset_manifest_file_hash == (
        custody.evidence.dataset_manifest_file_hash
    )
    assert verification.passed is True
    authorized = evaluator.evaluate(
        custody.evidence,
        authorization_verification=verification,
    )
    assert authorized.formal_oos_allowed is True
    assert authorized.production_blend_alpha_bp == 2000
    assert authorized.authorization_artifact_id == "promotion-auth:v4:001"
    assert authorized.blockers == ()


def test_failed_2000_lane_promotes_smallest_later_passing_lane(
    tmp_path: Path,
) -> None:
    evidence = _evidence(
        lane_2000=_lane(2000, bootstrap_lower_bound_bp=-1),
    )
    evaluator = AllocationPromotionEvaluator()
    preview = evaluator.evaluate(evidence)

    assert preview.eligible_alpha_bp == 3500
    lane_2000 = next(row for row in preview.lane_results if row.alpha_bp == 2000)
    assert lane_2000.blockers == ("bootstrap_lower_bound_negative",)

    custody = build_promotion_test_custody(
        tmp_path,
        evidence=evidence,
        evaluator=evaluator,
        authorized_alpha_bp=3500,
    )
    result = evaluator.evaluate(
        custody.evidence,
        authorization_verification=custody.verify(
            decision_at=datetime.fromisoformat("2026-07-29T08:30:00+08:00"),
            evaluator=evaluator,
        ),
    )
    assert result.production_blend_alpha_bp == 3500


@pytest.mark.parametrize(
    ("changes", "expected_blocker"),
    [
        ({"pit_violation_count": 1}, "pit_violation"),
        (
            {"future_prefix_violation_count": 1},
            "future_prefix_violation",
        ),
        ({"constraint_violation_count": 1}, "constraint_violation"),
        (
            {"replay_hash_pairs": ((_HASH, _OTHER_HASH),)},
            "deterministic_replay_hash_mismatch",
        ),
        ({"calibration_ece_bp": 501}, "calibration_ece_exceeded"),
        ({"calibrated_brier_bp": 1201}, "calibrated_brier_worse"),
        ({"psi_bp": 2500}, "psi_threshold_exceeded"),
        ({"core_coverage_bp": 9499}, "core_coverage_insufficient"),
        ({"enriched_coverage_bp": 8999}, "enriched_coverage_insufficient"),
        (
            {"feasible_fill_coverage_bp": 9499},
            "feasible_fill_coverage_insufficient",
        ),
        ({"mdd_worsening_vs_rule_bp": 101}, "mdd_worsening_exceeded"),
        ({"cvar_worsening_vs_rule_bp": 101}, "cvar_worsening_exceeded"),
        ({"weekly_turnover_bp": 2001}, "weekly_turnover_exceeded"),
        ({"turnover_increment_vs_rule_bp": 501}, "turnover_increment_exceeded"),
        ({"shadow_observed_days": 19}, "insufficient_shadow_days"),
    ],
)
def test_every_promotion_threshold_fails_closed(
    changes: dict[str, object], expected_blocker: str
) -> None:
    evidence = _evidence(lane_2000=_lane(2000, **changes))
    result = AllocationPromotionEvaluator().evaluate(evidence)
    lane = next(row for row in result.lane_results if row.alpha_bp == 2000)

    assert lane.passed is False
    assert expected_blocker in lane.blockers


def test_no_lane_passes_falls_back_to_zero() -> None:
    evidence = _evidence(
        lane_2000=_lane(2000, shadow_observed_days=19),
        lane_3500=_lane(3500, shadow_observed_days=19),
        lane_5000=_lane(5000, shadow_observed_days=19),
    )

    result = AllocationPromotionEvaluator().evaluate(evidence)

    assert result.eligible_alpha_bp == 0
    assert result.formal_oos_allowed is False
    assert result.production_blend_alpha_bp == 0
    assert result.blockers == (
        "promotion_evidence_shadow_days_incomplete",
        "no_nonzero_alpha_lane_passed",
    )


def test_incomplete_fold_or_shadow_evidence_atomically_forces_alpha_zero() -> None:
    short_folds = _lane(2000).folds[:3]
    insufficient_folds = _evidence(
        lane_2000=_lane(2000, folds=short_folds),
    )
    fold_result = AllocationPromotionEvaluator().evaluate(insufficient_folds)
    assert fold_result.eligible_alpha_bp == 0
    assert fold_result.selected_alpha_bp == 0
    assert "promotion_evidence_outer_folds_incomplete" in fold_result.blockers

    insufficient_shadow = _evidence(
        lane_2000=_lane(2000, shadow_observed_days=19),
    )
    shadow_result = AllocationPromotionEvaluator().evaluate(insufficient_shadow)
    assert shadow_result.eligible_alpha_bp == 0
    assert shadow_result.selected_alpha_bp == 0
    assert "promotion_evidence_shadow_days_incomplete" in shadow_result.blockers


def test_promotion_evaluation_is_json_ready_with_four_lane_evidence() -> None:
    evidence = _evidence()
    evaluator = AllocationPromotionEvaluator()
    result = evaluator.evaluate(evidence)

    payload = result.to_dict()
    encoded = json.dumps(payload, sort_keys=True)

    assert '"schema_version": "ml-allocation-promotion.v1"' in encoded
    assert len(payload["alpha_lanes"]) == 4  # type: ignore[arg-type]
    assert payload["selected_alpha_bp"] == 0
    assert payload["formal_oos_allowed"] is False
    lane_2000 = next(
        row
        for row in payload["alpha_lanes"]  # type: ignore[union-attr]
        if row["alpha_bp"] == 2000
    )
    assert lane_2000["threshold_evidence"]["shadow_observed_days"] == 20
    assert lane_2000["failed_reasons"] == []

    failed = evaluator.evaluate(
        _evidence(lane_2000=_lane(2000, calibration_ece_bp=501))
    ).to_dict()
    failed_lane = next(
        row
        for row in failed["alpha_lanes"]  # type: ignore[union-attr]
        if row["alpha_bp"] == 2000
    )
    assert failed_lane["failed_reasons"] == ["calibration_ece_exceeded"]


def test_authorization_must_bind_exact_evidence_policy_and_selected_alpha(
    tmp_path: Path,
) -> None:
    evidence = _evidence()
    evaluator = AllocationPromotionEvaluator()
    custody = build_promotion_test_custody(
        tmp_path / "evidence-mismatch",
        evidence=evidence,
        evaluator=evaluator,
        authorized_alpha_bp=2000,
    )
    verification = custody.verify(
        decision_at=datetime.fromisoformat("2026-07-29T08:30:00+08:00"),
        evaluator=evaluator,
    )
    wrong_evidence = evaluator.evaluate(
        _evidence(lane_2000=_lane(2000, bootstrap_lower_bound_bp=1)),
        authorization_verification=verification,
    )
    assert wrong_evidence.production_blend_alpha_bp == 0
    assert "promotion_authorization_evidence_mismatch" in wrong_evidence.blockers
    with pytest.raises(ValueError, match="verification proof mismatch"):
        replace(
            verification,
            evidence=_evidence(
                lane_2000=_lane(2000, bootstrap_lower_bound_bp=2)
            ),
        )

    wrong_alpha_custody = build_promotion_test_custody(
        tmp_path / "alpha-mismatch",
        evidence=evidence,
        evaluator=evaluator,
        authorized_alpha_bp=3500,
    )
    wrong_alpha = evaluator.evaluate(
        wrong_alpha_custody.evidence,
        authorization_verification=wrong_alpha_custody.verify(
            decision_at=datetime.fromisoformat("2026-07-29T08:30:00+08:00"),
            evaluator=evaluator,
        ),
    )
    assert wrong_alpha.production_blend_alpha_bp == 0
    assert "promotion_authorization_alpha_mismatch" in wrong_alpha.blockers

    raw_artifact = evaluator.evaluate(
        custody.evidence,
        authorization=custody.authorization,
    )
    assert raw_artifact.production_blend_alpha_bp == 0
    assert "promotion_authorization_unverified" in raw_artifact.blockers

    preview = evaluator.evaluate(evidence)
    with pytest.raises(ValueError, match="atomically"):
        replace(preview, production_blend_alpha_bp=2000)


def test_evidence_requires_all_four_alpha_lanes() -> None:
    with pytest.raises(ValueError, match="alpha lanes"):
        replace(
            _evidence(),
            lanes=(_lane(0), _lane(2000), _lane(3500)),
        )


@pytest.mark.parametrize(
    ("case_name", "custody_kwargs", "expected_blocker"),
    [
        (
            "untrusted-issuer",
            {
                "issuer_id": "attacker",
                "signing_key": bytes.fromhex("12" * 32),
            },
            "promotion_authorization_issuer_untrusted",
        ),
        (
            "self-signed-trusted-name",
            {"signing_key": bytes.fromhex("34" * 32)},
            "promotion_authorization_signature_invalid",
        ),
        (
            "future-issued",
            {"issued_at": "2099-01-01T08:00:00+08:00"},
            "promotion_authorization_issued_in_future",
        ),
        (
            "expired",
            {
                "decision_valid_from": "2026-07-28T08:00:00+08:00",
                "decision_valid_until": "2026-07-28T09:00:00+08:00",
            },
            "promotion_authorization_outside_decision_window",
        ),
        (
            "future-freeze",
            {"frozen_at": "2026-07-29T08:15:00+08:00"},
            "promotion_authorization_freeze_invalid",
        ),
    ],
)
def test_promotion_authority_time_issuer_and_signature_fail_closed(
    tmp_path: Path,
    case_name: str,
    custody_kwargs: dict[str, object],
    expected_blocker: str,
) -> None:
    evaluator = AllocationPromotionEvaluator()
    custody = build_promotion_test_custody(
        tmp_path / case_name,
        evidence=_evidence(),
        evaluator=evaluator,
        authorized_alpha_bp=2000,
        **custody_kwargs,  # type: ignore[arg-type]
    )

    verification = custody.verify(
        decision_at=datetime.fromisoformat("2026-07-29T08:30:00+08:00"),
        evaluator=evaluator,
    )
    result = evaluator.evaluate(
        custody.evidence,
        authorization_verification=verification,
    )

    assert verification.passed is False
    assert expected_blocker in verification.blockers
    assert result.production_blend_alpha_bp == 0
    assert result.formal_oos_allowed is False


@pytest.mark.parametrize(
    ("artifact_name", "expected_blocker"),
    [
        ("model_artifact_path", "promotion_custody_model_artifact_hash_mismatch"),
        (
            "dataset_manifest_path",
            "promotion_custody_dataset_manifest_file_hash_mismatch",
        ),
        ("evidence_path", "promotion_custody_evidence_hash_mismatch"),
        (
            "registry_revision_path",
            "promotion_custody_registry_revision_hash_mismatch",
        ),
    ],
)
def test_promotion_custody_rehashes_physical_artifacts(
    tmp_path: Path,
    artifact_name: str,
    expected_blocker: str,
) -> None:
    evaluator = AllocationPromotionEvaluator()
    custody = build_promotion_test_custody(
        tmp_path,
        evidence=_evidence(),
        evaluator=evaluator,
        authorized_alpha_bp=2000,
    )
    path = getattr(custody, artifact_name)
    if artifact_name == "evidence_path":
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    else:
        path.write_bytes(path.read_bytes() + b"\ntampered")

    verification = custody.verify(
        decision_at=datetime.fromisoformat("2026-07-29T08:30:00+08:00"),
        evaluator=evaluator,
    )

    assert verification.passed is False
    assert expected_blocker in verification.blockers
