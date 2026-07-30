"""配置型 ML 的 OOF 防線與自動 promotion 證據評估。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import secrets
from typing import Literal, Mapping, Sequence

from ml_module.purged_walk_forward import (
    MLTimeWindowRow,
    PurgedWalkForwardFold,
    PurgedWalkForwardSplitter,
)


ALPHA_LANES = (0, 2000, 3500, 5000)


@dataclass(frozen=True)
class AllocationWalkForwardPolicy:
    minimum_train_dates: int
    test_date_count: int
    purge_trading_days: int = 60
    embargo_trading_days: int = 5
    minimum_outer_folds: int = 4

    def __post_init__(self) -> None:
        for field_name in (
            "minimum_train_dates",
            "test_date_count",
            "purge_trading_days",
            "embargo_trading_days",
            "minimum_outer_folds",
        ):
            value = _require_integer(field_name, getattr(self, field_name))
            if value <= 0:
                raise ValueError(f"{field_name} must be positive")
        if self.minimum_outer_folds < 4:
            raise ValueError("minimum_outer_folds must be at least four")
        if self.purge_trading_days < 60:
            raise ValueError("purge_trading_days must be at least 60")
        if self.embargo_trading_days < 5:
            raise ValueError("embargo_trading_days must be at least 5")

    def split(
        self, rows: Sequence[MLTimeWindowRow]
    ) -> tuple[PurgedWalkForwardFold, ...]:
        folds = PurgedWalkForwardSplitter(
            minimum_train_dates=self.minimum_train_dates,
            test_date_count=self.test_date_count,
            purge_trading_days=self.purge_trading_days,
            embargo_trading_days=self.embargo_trading_days,
        ).split(rows)
        if len(folds) < self.minimum_outer_folds:
            raise ValueError(
                "allocation validation requires at least four usable outer folds"
            )
        return folds


@dataclass(frozen=True)
class BaseOOFPrediction:
    """只有 outer-fold test row 才能建立的 base expert prediction。"""

    row_id: str
    decision_date: str
    fold_id: str
    model_family: str
    model_id: str
    trained_through_date: str
    fit_row_ids: tuple[str, ...]
    preprocessor_fit_row_ids: tuple[str, ...]
    expected_excess_return_bp: int
    downside_probability_bp: int
    predicted_mae_bp: int
    rank_bp: int

    def __post_init__(self) -> None:
        _require_text(
            row_id=self.row_id,
            decision_date=self.decision_date,
            fold_id=self.fold_id,
            model_family=self.model_family,
            model_id=self.model_id,
            trained_through_date=self.trained_through_date,
        )
        _parse_date(self.decision_date, field_name="decision_date")
        _parse_date(self.trained_through_date, field_name="trained_through_date")
        if (
            not self.fit_row_ids
            or len(self.fit_row_ids) != len(set(self.fit_row_ids))
            or any(not row_id.strip() for row_id in self.fit_row_ids)
        ):
            raise ValueError("fit_row_ids must be non-empty and unique")
        if (
            not self.preprocessor_fit_row_ids
            or len(self.preprocessor_fit_row_ids)
            != len(set(self.preprocessor_fit_row_ids))
            or any(not row_id.strip() for row_id in self.preprocessor_fit_row_ids)
        ):
            raise ValueError("preprocessor_fit_row_ids must be non-empty and unique")
        _require_integer(
            "expected_excess_return_bp", self.expected_excess_return_bp
        )
        for field_name in (
            "downside_probability_bp",
            "predicted_mae_bp",
            "rank_bp",
        ):
            value = _require_integer(field_name, getattr(self, field_name))
            if not 0 <= value <= 10_000:
                raise ValueError(f"{field_name} must be within 0..10000")


@dataclass(frozen=True)
class MetaAllocatorOOFBundle:
    """Meta allocator 唯一可接受的 base prediction bundle。"""

    predictions: tuple[BaseOOFPrediction, ...]
    fold_ids: tuple[str, ...]
    model_families: tuple[str, ...]
    row_ids: tuple[str, ...]
    bundle_hash: str
    oof_only: Literal[True] = field(default=True, init=False)


class MetaAllocatorOOFGuard:
    def __init__(self, *, minimum_outer_folds: int = 4) -> None:
        if minimum_outer_folds < 4:
            raise ValueError("minimum_outer_folds must be at least four")
        self._minimum_outer_folds = minimum_outer_folds

    def build(
        self,
        *,
        predictions: Sequence[BaseOOFPrediction],
        folds: Sequence[PurgedWalkForwardFold],
        required_model_families: tuple[str, ...] | None = None,
    ) -> MetaAllocatorOOFBundle:
        if len(folds) < self._minimum_outer_folds:
            raise ValueError("meta allocator requires at least four outer folds")
        fold_by_id = {fold.fold_id: fold for fold in folds}
        if len(fold_by_id) != len(folds):
            raise ValueError("outer fold ids must be unique")
        if any(
            fold.purge_trading_days < 60 or fold.embargo_trading_days < 5
            for fold in folds
        ):
            raise ValueError("meta allocator folds must enforce purge=60 and embargo=5")

        test_membership: dict[str, tuple[str, MLTimeWindowRow]] = {}
        for fold in folds:
            train_ids = {row.row_id for row in fold.train_rows}
            test_ids = {row.row_id for row in fold.test_rows}
            if train_ids & test_ids:
                raise ValueError("outer fold train and test rows must be disjoint")
            if any(
                row.decision_date >= fold.test_start
                or row.label_end_date >= fold.test_start
                for row in fold.train_rows
            ):
                raise ValueError("outer fold train rows violate the causal purge boundary")
            for row in fold.test_rows:
                if row.row_id in test_membership:
                    raise ValueError("a row may appear in only one outer test fold")
                test_membership[row.row_id] = (fold.fold_id, row)
        if not predictions:
            raise ValueError("base OOF predictions are required")

        keys: set[tuple[str, str]] = set()
        families_by_row: dict[str, set[str]] = {}
        observed_fold_ids: set[str] = set()
        fit_audits: dict[
            tuple[str, str],
            tuple[str, str, tuple[str, ...], tuple[str, ...]],
        ] = {}
        for prediction in predictions:
            key = (prediction.row_id, prediction.model_family)
            if key in keys:
                raise ValueError("base OOF row/model-family predictions must be unique")
            keys.add(key)
            membership = test_membership.get(prediction.row_id)
            if membership is None:
                raise ValueError("meta input contains a non-OOF row")
            expected_fold_id, source_row = membership
            if prediction.fold_id != expected_fold_id:
                raise ValueError("prediction fold_id does not own its outer test row")
            fold = fold_by_id[prediction.fold_id]
            if prediction.decision_date != source_row.decision_date:
                raise ValueError("prediction decision_date does not match its test row")
            train_by_id = {row.row_id: row for row in fold.train_rows}
            fit_id_set = set(prediction.fit_row_ids)
            if not fit_id_set.issubset(train_by_id):
                raise ValueError("base model fit rows must belong to the outer train fold")
            canonical_fit_ids = tuple(
                row.row_id
                for row in fold.train_rows
                if row.row_id in fit_id_set
            )
            if prediction.fit_row_ids != canonical_fit_ids:
                raise ValueError("base model fit rows must use canonical fold order")
            if prediction.preprocessor_fit_row_ids != prediction.fit_row_ids:
                raise ValueError(
                    "preprocessor fit rows must equal the outer-fold model fit rows"
                )
            max_fit_date = max(
                train_by_id[row_id].decision_date
                for row_id in prediction.fit_row_ids
            )
            if prediction.trained_through_date != max_fit_date:
                raise ValueError(
                    "trained_through_date must equal the latest model fit row"
                )
            if _parse_date(
                prediction.trained_through_date,
                field_name="trained_through_date",
            ) >= _parse_date(fold.test_start, field_name="test_start"):
                raise ValueError("base prediction was trained through its test period")
            audit_key = (prediction.fold_id, prediction.model_family)
            audit_value = (
                prediction.model_id,
                prediction.trained_through_date,
                prediction.fit_row_ids,
                prediction.preprocessor_fit_row_ids,
            )
            previous_audit = fit_audits.setdefault(audit_key, audit_value)
            if previous_audit != audit_value:
                raise ValueError(
                    "base predictions in one fold/family must share one fit audit"
                )
            families_by_row.setdefault(prediction.row_id, set()).add(
                prediction.model_family
            )
            observed_fold_ids.add(prediction.fold_id)

        expected_families = (
            set(required_model_families)
            if required_model_families is not None
            else set().union(*families_by_row.values())
        )
        if (
            required_model_families is not None
            and len(required_model_families) != len(expected_families)
        ):
            raise ValueError("required_model_families must be unique")
        if not expected_families or any(not family.strip() for family in expected_families):
            raise ValueError("model families must be non-empty")
        for row_id, families in families_by_row.items():
            if families != expected_families:
                raise ValueError(
                    f"meta row {row_id} does not contain every required base family"
                )
        if len(observed_fold_ids) < self._minimum_outer_folds:
            raise ValueError("OOF bundle must cover at least four outer folds")

        canonical = tuple(
            sorted(
                predictions,
                key=lambda row: (
                    row.decision_date,
                    row.row_id,
                    row.model_family,
                    row.model_id,
                ),
            )
        )
        payload = [
            {
                "row_id": row.row_id,
                "decision_date": row.decision_date,
                "fold_id": row.fold_id,
                "model_family": row.model_family,
                "model_id": row.model_id,
                "trained_through_date": row.trained_through_date,
                "fit_row_ids": list(row.fit_row_ids),
                "preprocessor_fit_row_ids": list(
                    row.preprocessor_fit_row_ids
                ),
                "expected_excess_return_bp": row.expected_excess_return_bp,
                "downside_probability_bp": row.downside_probability_bp,
                "predicted_mae_bp": row.predicted_mae_bp,
                "rank_bp": row.rank_bp,
            }
            for row in canonical
        ]
        return MetaAllocatorOOFBundle(
            predictions=canonical,
            fold_ids=tuple(sorted(observed_fold_ids)),
            model_families=tuple(sorted(expected_families)),
            row_ids=tuple(sorted(families_by_row)),
            bundle_hash=_payload_hash(payload),
        )


@dataclass(frozen=True)
class AllocationFoldEvidence:
    fold_id: str
    after_cost_excess_vs_rule_bp: int

    def __post_init__(self) -> None:
        _require_text(fold_id=self.fold_id)
        _require_integer(
            "after_cost_excess_vs_rule_bp", self.after_cost_excess_vs_rule_bp
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "fold_id": self.fold_id,
            "after_cost_excess_vs_rule_bp": self.after_cost_excess_vs_rule_bp,
        }


@dataclass(frozen=True)
class AlphaLaneEvidence:
    alpha_bp: int
    pit_violation_count: int
    constraint_violation_count: int
    replay_hash_pairs: tuple[tuple[str, str], ...]
    folds: tuple[AllocationFoldEvidence, ...]
    bootstrap_lower_bound_bp: int
    calibration_ece_bp: int
    calibrated_brier_bp: int
    uncalibrated_brier_bp: int
    psi_bp: int
    core_coverage_bp: int
    enriched_coverage_bp: int
    feasible_fill_coverage_bp: int
    mdd_worsening_vs_rule_bp: int
    cvar_worsening_vs_rule_bp: int
    weekly_turnover_bp: int
    turnover_increment_vs_rule_bp: int
    shadow_observed_days: int
    future_prefix_violation_count: int = 0

    def __post_init__(self) -> None:
        _require_integer("alpha_bp", self.alpha_bp)
        for field_name in (
            "pit_violation_count",
            "future_prefix_violation_count",
            "constraint_violation_count",
            "psi_bp",
            "weekly_turnover_bp",
            "turnover_increment_vs_rule_bp",
            "shadow_observed_days",
        ):
            value = _require_integer(field_name, getattr(self, field_name))
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        _require_integer("bootstrap_lower_bound_bp", self.bootstrap_lower_bound_bp)
        _require_integer(
            "mdd_worsening_vs_rule_bp", self.mdd_worsening_vs_rule_bp
        )
        _require_integer(
            "cvar_worsening_vs_rule_bp", self.cvar_worsening_vs_rule_bp
        )
        for field_name in (
            "calibration_ece_bp",
            "calibrated_brier_bp",
            "uncalibrated_brier_bp",
            "core_coverage_bp",
            "enriched_coverage_bp",
            "feasible_fill_coverage_bp",
        ):
            value = _require_integer(field_name, getattr(self, field_name))
            if not 0 <= value <= 10_000:
                raise ValueError(f"{field_name} must be within 0..10000")
        if not self.replay_hash_pairs:
            raise ValueError("replay_hash_pairs are required")
        for expected_hash, actual_hash in self.replay_hash_pairs:
            _require_sha256(expected_hash, field_name="expected_replay_hash")
            _require_sha256(actual_hash, field_name="actual_replay_hash")
        fold_ids = tuple(row.fold_id for row in self.folds)
        if len(fold_ids) != len(set(fold_ids)):
            raise ValueError("promotion fold ids must be unique")

    def to_dict(self) -> dict[str, object]:
        return {
            "alpha_bp": self.alpha_bp,
            "pit_violation_count": self.pit_violation_count,
            "future_prefix_violation_count": self.future_prefix_violation_count,
            "constraint_violation_count": self.constraint_violation_count,
            "replay_hash_pairs": [
                list(pair) for pair in sorted(self.replay_hash_pairs)
            ],
            "folds": [
                row.to_dict() for row in sorted(self.folds, key=lambda item: item.fold_id)
            ],
            "bootstrap_lower_bound_bp": self.bootstrap_lower_bound_bp,
            "calibration_ece_bp": self.calibration_ece_bp,
            "calibrated_brier_bp": self.calibrated_brier_bp,
            "uncalibrated_brier_bp": self.uncalibrated_brier_bp,
            "psi_bp": self.psi_bp,
            "core_coverage_bp": self.core_coverage_bp,
            "enriched_coverage_bp": self.enriched_coverage_bp,
            "feasible_fill_coverage_bp": self.feasible_fill_coverage_bp,
            "mdd_worsening_vs_rule_bp": self.mdd_worsening_vs_rule_bp,
            "cvar_worsening_vs_rule_bp": self.cvar_worsening_vs_rule_bp,
            "weekly_turnover_bp": self.weekly_turnover_bp,
            "turnover_increment_vs_rule_bp": self.turnover_increment_vs_rule_bp,
            "shadow_observed_days": self.shadow_observed_days,
        }


@dataclass(frozen=True)
class AllocationPromotionEvidence:
    experiment_id: str
    model_id: str
    dataset_id: str
    model_artifact_hash: str
    dataset_identity_hash: str
    dataset_manifest_file_hash: str
    oof_bundle_hash: str
    shadow_evidence_hash: str
    lanes: tuple[AlphaLaneEvidence, ...]

    def __post_init__(self) -> None:
        _require_text(
            experiment_id=self.experiment_id,
            model_id=self.model_id,
            dataset_id=self.dataset_id,
        )
        for field_name in (
            "model_artifact_hash",
            "dataset_identity_hash",
            "dataset_manifest_file_hash",
            "oof_bundle_hash",
            "shadow_evidence_hash",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        lane_ids = tuple(lane.alpha_bp for lane in self.lanes)
        if tuple(sorted(lane_ids)) != ALPHA_LANES or len(lane_ids) != len(set(lane_ids)):
            raise ValueError("promotion evidence requires alpha lanes 0/2000/3500/5000")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "experiment_id": self.experiment_id,
            "model_id": self.model_id,
            "dataset_id": self.dataset_id,
            "model_artifact_hash": self.model_artifact_hash,
            "dataset_identity_hash": self.dataset_identity_hash,
            "dataset_manifest_file_hash": self.dataset_manifest_file_hash,
            "oof_bundle_hash": self.oof_bundle_hash,
            "shadow_evidence_hash": self.shadow_evidence_hash,
            "lanes": [
                lane.to_dict()
                for lane in sorted(self.lanes, key=lambda row: row.alpha_bp)
            ],
        }

    @property
    def evidence_hash(self) -> str:
        return _payload_hash(self.canonical_payload())


@dataclass(frozen=True)
class AllocationPromotionPolicy:
    candidate_alpha_lanes: tuple[int, ...] = (2000, 3500, 5000)
    minimum_outer_folds: int = 4
    minimum_winning_folds: int = 3
    maximum_calibration_ece_bp: int = 500
    maximum_psi_bp_exclusive: int = 2500
    minimum_core_coverage_bp: int = 9500
    minimum_enriched_coverage_bp: int = 9000
    minimum_feasible_fill_coverage_bp: int = 9500
    maximum_risk_worsening_bp: int = 100
    maximum_weekly_turnover_bp: int = 2000
    maximum_turnover_increment_bp: int = 500
    minimum_shadow_observed_days: int = 20

    def __post_init__(self) -> None:
        if self.candidate_alpha_lanes != (2000, 3500, 5000):
            raise ValueError("candidate alpha lanes must be 2000/3500/5000")
        for field_name in (
            "minimum_outer_folds",
            "minimum_winning_folds",
            "maximum_calibration_ece_bp",
            "maximum_psi_bp_exclusive",
            "minimum_core_coverage_bp",
            "minimum_enriched_coverage_bp",
            "minimum_feasible_fill_coverage_bp",
            "maximum_risk_worsening_bp",
            "maximum_weekly_turnover_bp",
            "maximum_turnover_increment_bp",
            "minimum_shadow_observed_days",
        ):
            value = _require_integer(field_name, getattr(self, field_name))
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        if self.minimum_outer_folds < 4 or self.minimum_winning_folds < 3:
            raise ValueError("promotion requires at least four folds and three wins")

    @property
    def policy_hash(self) -> str:
        return _payload_hash(
            {
                "candidate_alpha_lanes": list(self.candidate_alpha_lanes),
                "minimum_outer_folds": self.minimum_outer_folds,
                "minimum_winning_folds": self.minimum_winning_folds,
                "maximum_calibration_ece_bp": self.maximum_calibration_ece_bp,
                "maximum_psi_bp_exclusive": self.maximum_psi_bp_exclusive,
                "minimum_core_coverage_bp": self.minimum_core_coverage_bp,
                "minimum_enriched_coverage_bp": self.minimum_enriched_coverage_bp,
                "minimum_feasible_fill_coverage_bp": (
                    self.minimum_feasible_fill_coverage_bp
                ),
                "maximum_risk_worsening_bp": self.maximum_risk_worsening_bp,
                "maximum_weekly_turnover_bp": self.maximum_weekly_turnover_bp,
                "maximum_turnover_increment_bp": (
                    self.maximum_turnover_increment_bp
                ),
                "minimum_shadow_observed_days": self.minimum_shadow_observed_days,
            }
        )


@dataclass(frozen=True)
class PromotionAuthorizationArtifact:
    """由可信 Promotion Authority 簽發的單一決策窗授權。

    ``artifact_hash`` 只提供內容完整性；真正的信任邊界是
    ``authority_signature``。Consumer 必須以部署時注入的 issuer key 重新驗證，
    不能把這個 dataclass 本身視為授權能力。
    """

    artifact_id: str
    registry_revision_id: str
    registry_revision_hash: str
    custody_id: str
    issuer_id: str
    issued_at: str
    decision_valid_from: str
    decision_valid_until: str
    freeze_id: str
    frozen_at: str
    model_id: str
    dataset_id: str
    authorized_evidence_hash: str
    evidence_artifact_hash: str
    authorized_policy_hash: str
    authorized_alpha_bp: int
    model_artifact_hash: str
    dataset_identity_hash: str
    dataset_manifest_file_hash: str
    oof_bundle_hash: str
    shadow_evidence_hash: str
    artifact_hash: str
    authority_signature: str
    status: Literal["authorized"] = "authorized"

    def __post_init__(self) -> None:
        _require_text(
            artifact_id=self.artifact_id,
            registry_revision_id=self.registry_revision_id,
            custody_id=self.custody_id,
            issuer_id=self.issuer_id,
            issued_at=self.issued_at,
            decision_valid_from=self.decision_valid_from,
            decision_valid_until=self.decision_valid_until,
            freeze_id=self.freeze_id,
            frozen_at=self.frozen_at,
            model_id=self.model_id,
            dataset_id=self.dataset_id,
        )
        for field_name in (
            "issued_at",
            "decision_valid_from",
            "decision_valid_until",
            "frozen_at",
        ):
            _parse_aware_datetime(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "registry_revision_hash",
            "authorized_evidence_hash",
            "evidence_artifact_hash",
            "authorized_policy_hash",
            "model_artifact_hash",
            "dataset_identity_hash",
            "dataset_manifest_file_hash",
            "oof_bundle_hash",
            "shadow_evidence_hash",
            "artifact_hash",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        if self.authorized_alpha_bp not in (2000, 3500, 5000):
            raise ValueError("authorized_alpha_bp must be a non-zero candidate lane")
        if self.status != "authorized":
            raise ValueError("promotion authorization status must be authorized")
        _require_hmac_sha256(
            self.authority_signature,
            field_name="authority_signature",
        )
        expected = _payload_hash(self._payload_without_hash_and_signature())
        if self.artifact_hash != expected:
            raise ValueError("promotion authorization artifact hash mismatch")

    @classmethod
    def create(
        cls,
        *,
        artifact_id: str,
        registry_revision_id: str,
        registry_revision_hash: str,
        custody_id: str,
        issuer_id: str,
        issued_at: str,
        decision_valid_from: str,
        decision_valid_until: str,
        freeze_id: str,
        frozen_at: str,
        model_id: str,
        dataset_id: str,
        authorized_evidence_hash: str,
        evidence_artifact_hash: str,
        authorized_policy_hash: str,
        authorized_alpha_bp: int,
        model_artifact_hash: str,
        dataset_identity_hash: str,
        dataset_manifest_file_hash: str,
        oof_bundle_hash: str,
        shadow_evidence_hash: str,
        signing_key: bytes,
    ) -> "PromotionAuthorizationArtifact":
        _require_signing_key(signing_key)
        payload: dict[str, object] = {
            "artifact_id": artifact_id,
            "registry_revision_id": registry_revision_id,
            "registry_revision_hash": registry_revision_hash,
            "custody_id": custody_id,
            "issuer_id": issuer_id,
            "issued_at": issued_at,
            "decision_valid_from": decision_valid_from,
            "decision_valid_until": decision_valid_until,
            "freeze_id": freeze_id,
            "frozen_at": frozen_at,
            "model_id": model_id,
            "dataset_id": dataset_id,
            "authorized_evidence_hash": authorized_evidence_hash,
            "evidence_artifact_hash": evidence_artifact_hash,
            "authorized_policy_hash": authorized_policy_hash,
            "authorized_alpha_bp": authorized_alpha_bp,
            "model_artifact_hash": model_artifact_hash,
            "dataset_identity_hash": dataset_identity_hash,
            "dataset_manifest_file_hash": dataset_manifest_file_hash,
            "oof_bundle_hash": oof_bundle_hash,
            "shadow_evidence_hash": shadow_evidence_hash,
            "status": "authorized",
        }
        artifact_hash = _payload_hash(payload)
        signed_payload = {**payload, "artifact_hash": artifact_hash}
        return cls(
            artifact_id=artifact_id,
            registry_revision_id=registry_revision_id,
            registry_revision_hash=registry_revision_hash,
            custody_id=custody_id,
            issuer_id=issuer_id,
            issued_at=issued_at,
            decision_valid_from=decision_valid_from,
            decision_valid_until=decision_valid_until,
            freeze_id=freeze_id,
            frozen_at=frozen_at,
            model_id=model_id,
            dataset_id=dataset_id,
            authorized_evidence_hash=authorized_evidence_hash,
            evidence_artifact_hash=evidence_artifact_hash,
            authorized_policy_hash=authorized_policy_hash,
            authorized_alpha_bp=authorized_alpha_bp,
            model_artifact_hash=model_artifact_hash,
            dataset_identity_hash=dataset_identity_hash,
            dataset_manifest_file_hash=dataset_manifest_file_hash,
            oof_bundle_hash=oof_bundle_hash,
            shadow_evidence_hash=shadow_evidence_hash,
            artifact_hash=artifact_hash,
            authority_signature=_hmac_signature(signing_key, signed_payload),
        )

    def _payload_without_hash_and_signature(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "registry_revision_id": self.registry_revision_id,
            "registry_revision_hash": self.registry_revision_hash,
            "custody_id": self.custody_id,
            "issuer_id": self.issuer_id,
            "issued_at": self.issued_at,
            "decision_valid_from": self.decision_valid_from,
            "decision_valid_until": self.decision_valid_until,
            "freeze_id": self.freeze_id,
            "frozen_at": self.frozen_at,
            "model_id": self.model_id,
            "dataset_id": self.dataset_id,
            "authorized_evidence_hash": self.authorized_evidence_hash,
            "evidence_artifact_hash": self.evidence_artifact_hash,
            "authorized_policy_hash": self.authorized_policy_hash,
            "authorized_alpha_bp": self.authorized_alpha_bp,
            "model_artifact_hash": self.model_artifact_hash,
            "dataset_identity_hash": self.dataset_identity_hash,
            "dataset_manifest_file_hash": self.dataset_manifest_file_hash,
            "oof_bundle_hash": self.oof_bundle_hash,
            "shadow_evidence_hash": self.shadow_evidence_hash,
            "status": self.status,
        }

    def signing_payload(self) -> dict[str, object]:
        return {
            **self._payload_without_hash_and_signature(),
            "artifact_hash": self.artifact_hash,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.signing_payload(),
            "authority_signature": self.authority_signature,
        }


_VERIFIED_PROMOTION_CAPABILITY = object()
_VERIFIED_PROMOTION_PROCESS_KEY = secrets.token_bytes(32)


@dataclass(frozen=True)
class PromotionAuthorizationVerification:
    """Consumer 重新驗證後的結果；raw authorization 永遠不等於此能力。"""

    decision_at: str
    passed: bool
    blockers: tuple[str, ...]
    authorization: PromotionAuthorizationArtifact | None = None
    evidence: AllocationPromotionEvidence | None = None
    custody_hash: str | None = None
    verification_proof: str | None = field(default=None, repr=False)
    _capability: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _parse_aware_datetime(self.decision_at, field_name="decision_at")
        if self.passed:
            if (
                self.blockers
                or self.authorization is None
                or self.evidence is None
                or self.custody_hash is None
                or self.verification_proof is None
                or self._capability is not _VERIFIED_PROMOTION_CAPABILITY
            ):
                raise ValueError(
                    "passed promotion verification requires complete custody evidence"
                )
            _require_sha256(self.custody_hash, field_name="custody_hash")
            _require_hmac_sha256(
                self.verification_proof,
                field_name="verification_proof",
            )
            expected_proof = _promotion_verification_proof(
                decision_at=self.decision_at,
                authorization=self.authorization,
                evidence=self.evidence,
                custody_hash=self.custody_hash,
            )
            if not hmac.compare_digest(self.verification_proof, expected_proof):
                raise ValueError("promotion verification proof mismatch")
        elif not self.blockers:
            raise ValueError("failed promotion verification requires blockers")

    @property
    def authorized_alpha_bp(self) -> int:
        if not self.passed or self.authorization is None:
            return 0
        return self.authorization.authorized_alpha_bp


class PromotionAuthorizationVerifier:
    """以部署時信任根驗證 issuer、時效、custody 與所有實體 artifact。"""

    def __init__(
        self,
        *,
        trusted_issuer_keys: Mapping[str, bytes],
        trusted_custody_roots: Sequence[Path],
        custody_id: str,
        maximum_validity: timedelta = timedelta(days=1),
    ) -> None:
        if not trusted_issuer_keys:
            raise ValueError("trusted_issuer_keys must not be empty")
        normalized_keys: dict[str, bytes] = {}
        for issuer_id, key in trusted_issuer_keys.items():
            _require_text(issuer_id=issuer_id)
            _require_signing_key(key)
            normalized_keys[issuer_id] = bytes(key)
        if not trusted_custody_roots:
            raise ValueError("trusted_custody_roots must not be empty")
        roots: list[Path] = []
        for raw_root in trusted_custody_roots:
            root = Path(raw_root).resolve(strict=True)
            if not root.is_dir():
                raise ValueError("trusted custody roots must be directories")
            roots.append(root)
        _require_text(custody_id=custody_id)
        if maximum_validity <= timedelta(0):
            raise ValueError("maximum_validity must be positive")
        self._trusted_issuer_keys = dict(normalized_keys)
        self._trusted_custody_roots = tuple(dict.fromkeys(roots))
        self._custody_id = custody_id
        self._maximum_validity = maximum_validity

    def verify_files(
        self,
        *,
        decision_at: datetime,
        evidence_path: Path,
        authorization_path: Path,
        registry_revision_path: Path,
        model_artifact_path: Path,
        dataset_manifest_path: Path,
        oof_bundle_path: Path,
        shadow_evidence_path: Path,
        expected_policy_hash: str,
        expected_alpha_bp: int | None = None,
        expected_model_id: str | None = None,
        expected_dataset_id: str | None = None,
        expected_model_hash: str | None = None,
        expected_dataset_identity_hash: str | None = None,
        expected_dataset_manifest_file_hash: str | None = None,
        expected_authorization_artifact_hash: str | None = None,
    ) -> PromotionAuthorizationVerification:
        decision = _require_aware_datetime_object(
            decision_at,
            field_name="decision_at",
        )
        decision_text = decision.isoformat(timespec="seconds")
        try:
            paths = {
                "evidence": Path(evidence_path).resolve(strict=True),
                "authorization": Path(authorization_path).resolve(strict=True),
                "registry_revision": Path(registry_revision_path).resolve(strict=True),
                "model_artifact": Path(model_artifact_path).resolve(strict=True),
                "dataset_manifest": Path(dataset_manifest_path).resolve(strict=True),
                "oof_bundle": Path(oof_bundle_path).resolve(strict=True),
                "shadow_evidence": Path(shadow_evidence_path).resolve(strict=True),
            }
        except (OSError, RuntimeError) as exc:
            return self._failed(
                decision_text,
                f"promotion_custody_file_invalid:{type(exc).__name__}",
            )
        if any(not path.is_file() for path in paths.values()):
            return self._failed(decision_text, "promotion_custody_file_missing")
        if len(set(paths.values())) != len(paths):
            return self._failed(decision_text, "promotion_custody_paths_not_unique")
        if any(not self._is_trusted_path(path) for path in paths.values()):
            return self._failed(decision_text, "promotion_custody_path_untrusted")

        try:
            evidence = load_allocation_promotion_evidence(paths["evidence"])
            authorization = load_promotion_authorization_artifact(
                paths["authorization"]
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return self._failed(
                decision_text,
                f"promotion_authorization_invalid:{type(exc).__name__}",
            )

        blockers: list[str] = []
        issuer_key = self._trusted_issuer_keys.get(authorization.issuer_id)
        if issuer_key is None:
            blockers.append("promotion_authorization_issuer_untrusted")
        elif not hmac.compare_digest(
            authorization.authority_signature,
            _hmac_signature(issuer_key, authorization.signing_payload()),
        ):
            blockers.append("promotion_authorization_signature_invalid")

        issued_at = _parse_aware_datetime(
            authorization.issued_at,
            field_name="issued_at",
        )
        valid_from = _parse_aware_datetime(
            authorization.decision_valid_from,
            field_name="decision_valid_from",
        )
        valid_until = _parse_aware_datetime(
            authorization.decision_valid_until,
            field_name="decision_valid_until",
        )
        frozen_at = _parse_aware_datetime(
            authorization.frozen_at,
            field_name="frozen_at",
        )
        decision_utc = decision.astimezone(timezone.utc)
        issued_utc = issued_at.astimezone(timezone.utc)
        valid_from_utc = valid_from.astimezone(timezone.utc)
        valid_until_utc = valid_until.astimezone(timezone.utc)
        frozen_utc = frozen_at.astimezone(timezone.utc)
        if issued_utc > decision_utc:
            blockers.append("promotion_authorization_issued_in_future")
        if valid_until_utc < valid_from_utc:
            blockers.append("promotion_authorization_validity_invalid")
        elif valid_until_utc - valid_from_utc > self._maximum_validity:
            blockers.append("promotion_authorization_validity_too_long")
        if not valid_from_utc <= decision_utc <= valid_until_utc:
            blockers.append("promotion_authorization_outside_decision_window")
        if frozen_utc > issued_utc or frozen_utc > decision_utc:
            blockers.append("promotion_authorization_freeze_invalid")
        if authorization.custody_id != self._custody_id:
            blockers.append("promotion_authorization_custody_mismatch")

        content_hashes = {
            name: file_content_hash(path)
            for name, path in paths.items()
            if name != "authorization"
        }
        expected_content_hashes = {
            "evidence": authorization.evidence_artifact_hash,
            "registry_revision": authorization.registry_revision_hash,
            "model_artifact": authorization.model_artifact_hash,
            "dataset_manifest": authorization.dataset_manifest_file_hash,
            "oof_bundle": authorization.oof_bundle_hash,
            "shadow_evidence": authorization.shadow_evidence_hash,
        }
        for artifact_name, expected_hash in expected_content_hashes.items():
            if content_hashes[artifact_name] != expected_hash:
                blocker_name = (
                    "promotion_custody_dataset_manifest_file_hash_mismatch"
                    if artifact_name == "dataset_manifest"
                    else f"promotion_custody_{artifact_name}_hash_mismatch"
                )
                blockers.append(
                    blocker_name
                )

        if not _registry_revision_is_present(
            paths["registry_revision"],
            authorization.registry_revision_id,
        ):
            blockers.append("promotion_registry_revision_missing")
        if authorization.authorized_evidence_hash != evidence.evidence_hash:
            blockers.append("promotion_authorization_evidence_mismatch")
        if authorization.authorized_policy_hash != expected_policy_hash:
            blockers.append("promotion_authorization_policy_mismatch")
        if authorization.model_id != evidence.model_id:
            blockers.append("promotion_authorization_model_id_mismatch")
        if authorization.dataset_id != evidence.dataset_id:
            blockers.append("promotion_authorization_dataset_id_mismatch")
        if authorization.model_artifact_hash != evidence.model_artifact_hash:
            blockers.append("promotion_authorization_model_hash_mismatch")
        if authorization.dataset_identity_hash != evidence.dataset_identity_hash:
            blockers.append(
                "promotion_authorization_dataset_identity_hash_mismatch"
            )
        if (
            authorization.dataset_manifest_file_hash
            != evidence.dataset_manifest_file_hash
        ):
            blockers.append(
                "promotion_authorization_dataset_manifest_file_hash_mismatch"
            )
        try:
            manifest_identity_hash = _dataset_manifest_identity_hash(
                paths["dataset_manifest"]
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            blockers.append("promotion_dataset_manifest_identity_invalid")
        else:
            if manifest_identity_hash != authorization.dataset_identity_hash:
                blockers.append(
                    "promotion_dataset_manifest_identity_hash_mismatch"
                )
        if authorization.oof_bundle_hash != evidence.oof_bundle_hash:
            blockers.append("promotion_authorization_oof_hash_mismatch")
        if authorization.shadow_evidence_hash != evidence.shadow_evidence_hash:
            blockers.append("promotion_authorization_shadow_hash_mismatch")
        if (
            expected_alpha_bp is not None
            and authorization.authorized_alpha_bp != expected_alpha_bp
        ):
            blockers.append("promotion_authorization_alpha_mismatch")
        if expected_model_id is not None and authorization.model_id != expected_model_id:
            blockers.append("promotion_consumer_model_id_mismatch")
        if (
            expected_dataset_id is not None
            and authorization.dataset_id != expected_dataset_id
        ):
            blockers.append("promotion_consumer_dataset_id_mismatch")
        if (
            expected_model_hash is not None
            and authorization.model_artifact_hash != expected_model_hash
        ):
            blockers.append("promotion_consumer_model_hash_mismatch")
        if (
            expected_dataset_identity_hash is not None
            and authorization.dataset_identity_hash
            != expected_dataset_identity_hash
        ):
            blockers.append(
                "promotion_consumer_dataset_identity_hash_mismatch"
            )
        if (
            expected_dataset_manifest_file_hash is not None
            and authorization.dataset_manifest_file_hash
            != expected_dataset_manifest_file_hash
        ):
            blockers.append(
                "promotion_consumer_dataset_manifest_file_hash_mismatch"
            )
        if expected_authorization_artifact_hash is not None:
            if authorization.artifact_hash != expected_authorization_artifact_hash:
                blockers.append("promotion_consumer_authorization_hash_mismatch")

        custody_hash = _payload_hash(
            {
                "custody_id": self._custody_id,
                "registry_revision_id": authorization.registry_revision_id,
                "authorization_artifact_hash": authorization.artifact_hash,
                "content_hashes": dict(sorted(content_hashes.items())),
            }
        )
        unique_blockers = tuple(dict.fromkeys(blockers))
        if unique_blockers:
            return PromotionAuthorizationVerification(
                decision_at=decision_text,
                passed=False,
                blockers=unique_blockers,
                authorization=authorization,
                evidence=evidence,
                custody_hash=custody_hash,
            )
        verification_proof = _promotion_verification_proof(
            decision_at=decision_text,
            authorization=authorization,
            evidence=evidence,
            custody_hash=custody_hash,
        )
        return PromotionAuthorizationVerification(
            decision_at=decision_text,
            passed=True,
            blockers=(),
            authorization=authorization,
            evidence=evidence,
            custody_hash=custody_hash,
            verification_proof=verification_proof,
            _capability=_VERIFIED_PROMOTION_CAPABILITY,
        )

    def _is_trusted_path(self, path: Path) -> bool:
        return any(path.is_relative_to(root) for root in self._trusted_custody_roots)

    @staticmethod
    def _failed(
        decision_at: str,
        blocker: str,
    ) -> PromotionAuthorizationVerification:
        return PromotionAuthorizationVerification(
            decision_at=decision_at,
            passed=False,
            blockers=(blocker,),
        )


def file_content_hash(path: Path) -> str:
    """回傳實體檔案 bytes 的 SHA-256；不得以 JSON 自述 hash 取代。"""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def load_allocation_promotion_evidence(path: Path) -> AllocationPromotionEvidence:
    payload = _load_json_mapping(path, label="promotion_evidence")
    source = payload.get("promotion_evidence", payload)
    body = _as_mapping(source, label="promotion_evidence")
    lanes: list[AlphaLaneEvidence] = []
    for lane_index, raw_lane in enumerate(
        _as_sequence(body.get("lanes"), label="promotion_evidence.lanes")
    ):
        lane = _as_mapping(raw_lane, label=f"lanes[{lane_index}]")
        folds = tuple(
            AllocationFoldEvidence(
                fold_id=_as_text(
                    _as_mapping(row, label="fold").get("fold_id"),
                    label="fold_id",
                ),
                after_cost_excess_vs_rule_bp=_as_integer(
                    _as_mapping(row, label="fold").get(
                        "after_cost_excess_vs_rule_bp"
                    ),
                    label="after_cost_excess_vs_rule_bp",
                ),
            )
            for row in _as_sequence(lane.get("folds"), label="folds")
        )
        replay_hash_pairs: list[tuple[str, str]] = []
        for raw_pair in _as_sequence(
            lane.get("replay_hash_pairs"),
            label="replay_hash_pairs",
        ):
            pair = _as_sequence(raw_pair, label="replay_hash_pair")
            if len(pair) != 2:
                raise ValueError("replay_hash_pair must contain exactly two hashes")
            replay_hash_pairs.append(
                (
                    _as_text(pair[0], label="expected_replay_hash"),
                    _as_text(pair[1], label="actual_replay_hash"),
                )
            )
        lanes.append(
            AlphaLaneEvidence(
                alpha_bp=_as_integer(lane.get("alpha_bp"), label="alpha_bp"),
                pit_violation_count=_as_integer(
                    lane.get("pit_violation_count"),
                    label="pit_violation_count",
                ),
                future_prefix_violation_count=_as_integer(
                    lane.get("future_prefix_violation_count"),
                    label="future_prefix_violation_count",
                ),
                constraint_violation_count=_as_integer(
                    lane.get("constraint_violation_count"),
                    label="constraint_violation_count",
                ),
                replay_hash_pairs=tuple(replay_hash_pairs),
                folds=folds,
                bootstrap_lower_bound_bp=_as_integer(
                    lane.get("bootstrap_lower_bound_bp"),
                    label="bootstrap_lower_bound_bp",
                ),
                calibration_ece_bp=_as_integer(
                    lane.get("calibration_ece_bp"),
                    label="calibration_ece_bp",
                ),
                calibrated_brier_bp=_as_integer(
                    lane.get("calibrated_brier_bp"),
                    label="calibrated_brier_bp",
                ),
                uncalibrated_brier_bp=_as_integer(
                    lane.get("uncalibrated_brier_bp"),
                    label="uncalibrated_brier_bp",
                ),
                psi_bp=_as_integer(lane.get("psi_bp"), label="psi_bp"),
                core_coverage_bp=_as_integer(
                    lane.get("core_coverage_bp"),
                    label="core_coverage_bp",
                ),
                enriched_coverage_bp=_as_integer(
                    lane.get("enriched_coverage_bp"),
                    label="enriched_coverage_bp",
                ),
                feasible_fill_coverage_bp=_as_integer(
                    lane.get("feasible_fill_coverage_bp"),
                    label="feasible_fill_coverage_bp",
                ),
                mdd_worsening_vs_rule_bp=_as_integer(
                    lane.get("mdd_worsening_vs_rule_bp"),
                    label="mdd_worsening_vs_rule_bp",
                ),
                cvar_worsening_vs_rule_bp=_as_integer(
                    lane.get("cvar_worsening_vs_rule_bp"),
                    label="cvar_worsening_vs_rule_bp",
                ),
                weekly_turnover_bp=_as_integer(
                    lane.get("weekly_turnover_bp"),
                    label="weekly_turnover_bp",
                ),
                turnover_increment_vs_rule_bp=_as_integer(
                    lane.get("turnover_increment_vs_rule_bp"),
                    label="turnover_increment_vs_rule_bp",
                ),
                shadow_observed_days=_as_integer(
                    lane.get("shadow_observed_days"),
                    label="shadow_observed_days",
                ),
            )
        )
    return AllocationPromotionEvidence(
        experiment_id=_as_text(body.get("experiment_id"), label="experiment_id"),
        model_id=_as_text(body.get("model_id"), label="model_id"),
        dataset_id=_as_text(body.get("dataset_id"), label="dataset_id"),
        model_artifact_hash=_as_text(
            body.get("model_artifact_hash"),
            label="model_artifact_hash",
        ),
        dataset_identity_hash=_as_text(
            body.get("dataset_identity_hash"),
            label="dataset_identity_hash",
        ),
        dataset_manifest_file_hash=_as_text(
            body.get("dataset_manifest_file_hash"),
            label="dataset_manifest_file_hash",
        ),
        oof_bundle_hash=_as_text(
            body.get("oof_bundle_hash"),
            label="oof_bundle_hash",
        ),
        shadow_evidence_hash=_as_text(
            body.get("shadow_evidence_hash"),
            label="shadow_evidence_hash",
        ),
        lanes=tuple(lanes),
    )


def load_promotion_authorization_artifact(
    path: Path,
) -> PromotionAuthorizationArtifact:
    payload = _load_json_mapping(path, label="promotion_authorization")
    source = payload.get("authorization", payload)
    body = _as_mapping(source, label="authorization")
    if body.get("status", "authorized") != "authorized":
        raise ValueError("authorization.status must be authorized")
    return PromotionAuthorizationArtifact(
        artifact_id=_as_text(body.get("artifact_id"), label="artifact_id"),
        registry_revision_id=_as_text(
            body.get("registry_revision_id"),
            label="registry_revision_id",
        ),
        registry_revision_hash=_as_text(
            body.get("registry_revision_hash"),
            label="registry_revision_hash",
        ),
        custody_id=_as_text(body.get("custody_id"), label="custody_id"),
        issuer_id=_as_text(body.get("issuer_id"), label="issuer_id"),
        issued_at=_as_text(body.get("issued_at"), label="issued_at"),
        decision_valid_from=_as_text(
            body.get("decision_valid_from"),
            label="decision_valid_from",
        ),
        decision_valid_until=_as_text(
            body.get("decision_valid_until"),
            label="decision_valid_until",
        ),
        freeze_id=_as_text(body.get("freeze_id"), label="freeze_id"),
        frozen_at=_as_text(body.get("frozen_at"), label="frozen_at"),
        model_id=_as_text(body.get("model_id"), label="model_id"),
        dataset_id=_as_text(body.get("dataset_id"), label="dataset_id"),
        authorized_evidence_hash=_as_text(
            body.get("authorized_evidence_hash"),
            label="authorized_evidence_hash",
        ),
        evidence_artifact_hash=_as_text(
            body.get("evidence_artifact_hash"),
            label="evidence_artifact_hash",
        ),
        authorized_policy_hash=_as_text(
            body.get("authorized_policy_hash"),
            label="authorized_policy_hash",
        ),
        authorized_alpha_bp=_as_integer(
            body.get("authorized_alpha_bp"),
            label="authorized_alpha_bp",
        ),
        model_artifact_hash=_as_text(
            body.get("model_artifact_hash"),
            label="model_artifact_hash",
        ),
        dataset_identity_hash=_as_text(
            body.get("dataset_identity_hash"),
            label="dataset_identity_hash",
        ),
        dataset_manifest_file_hash=_as_text(
            body.get("dataset_manifest_file_hash"),
            label="dataset_manifest_file_hash",
        ),
        oof_bundle_hash=_as_text(
            body.get("oof_bundle_hash"),
            label="oof_bundle_hash",
        ),
        shadow_evidence_hash=_as_text(
            body.get("shadow_evidence_hash"),
            label="shadow_evidence_hash",
        ),
        artifact_hash=_as_text(body.get("artifact_hash"), label="artifact_hash"),
        authority_signature=_as_text(
            body.get("authority_signature"),
            label="authority_signature",
        ),
        status="authorized",
    )


@dataclass(frozen=True)
class AlphaLanePromotionResult:
    alpha_bp: int
    passed: bool
    winning_fold_count: int
    blockers: tuple[str, ...]
    evidence: AlphaLaneEvidence

    def to_dict(self) -> dict[str, object]:
        return {
            "alpha_bp": self.alpha_bp,
            "promotion_candidate": self.alpha_bp != 0,
            "passed": self.passed,
            "winning_fold_count": self.winning_fold_count,
            "failed_reasons": list(self.blockers),
            "threshold_evidence": self.evidence.to_dict(),
        }


@dataclass(frozen=True)
class AllocationPromotionEvaluation:
    evidence_hash: str
    policy_hash: str
    lane_results: tuple[AlphaLanePromotionResult, ...]
    eligible_alpha_bp: int
    formal_oos_allowed: bool
    production_blend_alpha_bp: int
    authorization_artifact_id: str | None
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_sha256(self.evidence_hash, field_name="evidence_hash")
        _require_sha256(self.policy_hash, field_name="policy_hash")
        if tuple(row.alpha_bp for row in self.lane_results) != ALPHA_LANES:
            raise ValueError("promotion evaluation must contain all four alpha lanes")
        if self.formal_oos_allowed:
            if (
                self.production_blend_alpha_bp not in (2000, 3500, 5000)
                or self.production_blend_alpha_bp != self.eligible_alpha_bp
                or not self.authorization_artifact_id
                or self.blockers
            ):
                raise ValueError("formal promotion requires an authorized eligible alpha")
        elif self.production_blend_alpha_bp != 0:
            raise ValueError("failed promotion must atomically use alpha zero")

    @property
    def selected_alpha_bp(self) -> int:
        return self.production_blend_alpha_bp

    def to_dict(self) -> dict[str, object]:
        """供 orchestration script 原樣序列化的 promotion artifact。"""
        return {
            "schema_version": "ml-allocation-promotion.v1",
            "evidence_hash": self.evidence_hash,
            "policy_hash": self.policy_hash,
            "alpha_lanes": [row.to_dict() for row in self.lane_results],
            "eligible_alpha_bp": self.eligible_alpha_bp,
            "selected_alpha_bp": self.selected_alpha_bp,
            "formal_oos_allowed": self.formal_oos_allowed,
            "production_blend_alpha_bp": self.production_blend_alpha_bp,
            "authorization_artifact_id": self.authorization_artifact_id,
            "failed_reasons": list(self.blockers),
        }


class AllocationPromotionEvaluator:
    def __init__(self, policy: AllocationPromotionPolicy | None = None) -> None:
        self._policy = policy or AllocationPromotionPolicy()

    @property
    def policy_hash(self) -> str:
        return self._policy.policy_hash

    def evaluate(
        self,
        evidence: AllocationPromotionEvidence,
        *,
        authorization: PromotionAuthorizationArtifact | None = None,
        authorization_verification: PromotionAuthorizationVerification | None = None,
    ) -> AllocationPromotionEvaluation:
        lane_results: list[AlphaLanePromotionResult] = []
        result_by_alpha: dict[int, AlphaLanePromotionResult] = {}
        for lane in sorted(evidence.lanes, key=lambda row: row.alpha_bp):
            if lane.alpha_bp == 0:
                result = AlphaLanePromotionResult(0, True, 0, (), lane)
            else:
                lane_blockers = self._lane_blockers(lane)
                result = AlphaLanePromotionResult(
                    alpha_bp=lane.alpha_bp,
                    passed=not lane_blockers,
                    winning_fold_count=sum(
                        row.after_cost_excess_vs_rule_bp > 0
                        for row in lane.folds
                    ),
                    blockers=tuple(lane_blockers),
                    evidence=lane,
                )
            lane_results.append(result)
            result_by_alpha[result.alpha_bp] = result

        candidate_lanes = tuple(
            lane for lane in evidence.lanes if lane.alpha_bp != 0
        )
        blockers: list[str] = []
        if any(
            len(lane.folds) < self._policy.minimum_outer_folds
            for lane in candidate_lanes
        ):
            blockers.append("promotion_evidence_outer_folds_incomplete")
        if any(
            lane.shadow_observed_days
            < self._policy.minimum_shadow_observed_days
            for lane in candidate_lanes
        ):
            blockers.append("promotion_evidence_shadow_days_incomplete")
        eligible_alpha = 0
        if not blockers:
            eligible_alpha = next(
                (
                    alpha
                    for alpha in self._policy.candidate_alpha_lanes
                    if result_by_alpha[alpha].passed
                ),
                0,
            )
        authorization_id: str | None = None
        if eligible_alpha == 0:
            blockers.append("no_nonzero_alpha_lane_passed")
        elif authorization_verification is None:
            blockers.append(
                "promotion_authorization_unverified"
                if authorization is not None
                else "promotion_authorization_artifact_required"
            )
        elif not authorization_verification.passed:
            blockers.extend(authorization_verification.blockers)
        else:
            verified_evidence = authorization_verification.evidence
            authorization = authorization_verification.authorization
            if authorization is None or verified_evidence is None:
                blockers.append("promotion_authorization_verification_incomplete")
                authorization = None
            elif verified_evidence.evidence_hash != evidence.evidence_hash:
                blockers.append("promotion_authorization_evidence_mismatch")
        if eligible_alpha > 0 and authorization is not None and not (
            authorization_verification is None
            or not authorization_verification.passed
        ):
            authorization_id = authorization.artifact_id
            if authorization.authorized_evidence_hash != evidence.evidence_hash:
                blockers.append("promotion_authorization_evidence_mismatch")
            if authorization.authorized_policy_hash != self._policy.policy_hash:
                blockers.append("promotion_authorization_policy_mismatch")
            if authorization.authorized_alpha_bp != eligible_alpha:
                blockers.append("promotion_authorization_alpha_mismatch")

        promoted = eligible_alpha > 0 and not blockers
        return AllocationPromotionEvaluation(
            evidence_hash=evidence.evidence_hash,
            policy_hash=self._policy.policy_hash,
            lane_results=tuple(lane_results),
            eligible_alpha_bp=eligible_alpha,
            formal_oos_allowed=promoted,
            production_blend_alpha_bp=eligible_alpha if promoted else 0,
            authorization_artifact_id=authorization_id if promoted else None,
            blockers=tuple(blockers),
        )

    def _lane_blockers(self, lane: AlphaLaneEvidence) -> list[str]:
        blockers: list[str] = []
        if lane.pit_violation_count != 0:
            blockers.append("pit_violation")
        if lane.future_prefix_violation_count != 0:
            blockers.append("future_prefix_violation")
        if lane.constraint_violation_count != 0:
            blockers.append("constraint_violation")
        if any(expected != actual for expected, actual in lane.replay_hash_pairs):
            blockers.append("deterministic_replay_hash_mismatch")
        if len(lane.folds) < self._policy.minimum_outer_folds:
            blockers.append("insufficient_oos_folds")
        winning_folds = sum(
            row.after_cost_excess_vs_rule_bp > 0 for row in lane.folds
        )
        if winning_folds < self._policy.minimum_winning_folds:
            blockers.append("insufficient_winning_folds")
        if lane.bootstrap_lower_bound_bp < 0:
            blockers.append("bootstrap_lower_bound_negative")
        if lane.calibration_ece_bp > self._policy.maximum_calibration_ece_bp:
            blockers.append("calibration_ece_exceeded")
        if lane.calibrated_brier_bp > lane.uncalibrated_brier_bp:
            blockers.append("calibrated_brier_worse")
        if lane.psi_bp >= self._policy.maximum_psi_bp_exclusive:
            blockers.append("psi_threshold_exceeded")
        if lane.core_coverage_bp < self._policy.minimum_core_coverage_bp:
            blockers.append("core_coverage_insufficient")
        if lane.enriched_coverage_bp < self._policy.minimum_enriched_coverage_bp:
            blockers.append("enriched_coverage_insufficient")
        if (
            lane.feasible_fill_coverage_bp
            < self._policy.minimum_feasible_fill_coverage_bp
        ):
            blockers.append("feasible_fill_coverage_insufficient")
        if (
            lane.mdd_worsening_vs_rule_bp
            > self._policy.maximum_risk_worsening_bp
        ):
            blockers.append("mdd_worsening_exceeded")
        if (
            lane.cvar_worsening_vs_rule_bp
            > self._policy.maximum_risk_worsening_bp
        ):
            blockers.append("cvar_worsening_exceeded")
        if lane.weekly_turnover_bp > self._policy.maximum_weekly_turnover_bp:
            blockers.append("weekly_turnover_exceeded")
        if (
            lane.turnover_increment_vs_rule_bp
            > self._policy.maximum_turnover_increment_bp
        ):
            blockers.append("turnover_increment_exceeded")
        if lane.shadow_observed_days < self._policy.minimum_shadow_observed_days:
            blockers.append("insufficient_shadow_days")
        return blockers


def _payload_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _require_text(**values: str) -> None:
    for field_name, value in values.items():
        if not value or not value.strip():
            raise ValueError(f"{field_name} is required")


def _require_integer(field_name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    return value


def _require_sha256(value: str, *, field_name: str) -> None:
    digest = value[7:] if value.startswith("sha256:") else ""
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"{field_name} must be a sha256: digest")


def _parse_date(value: str, *, field_name: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc


def _parse_aware_datetime(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return parsed


def _require_aware_datetime_object(
    value: datetime,
    *,
    field_name: str,
) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{field_name} must be an aware datetime")
    return value


def _require_signing_key(value: bytes) -> None:
    if not isinstance(value, bytes) or len(value) < 32:
        raise ValueError("promotion authority signing key must be at least 32 bytes")


def _require_hmac_sha256(value: str, *, field_name: str) -> None:
    digest = value[12:] if value.startswith("hmac-sha256:") else ""
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError(f"{field_name} must be a hmac-sha256: digest")


def _hmac_signature(key: bytes, payload: object) -> str:
    _require_signing_key(key)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hmac.new(key, encoded, hashlib.sha256).hexdigest()
    return f"hmac-sha256:{digest}"


def _promotion_verification_proof(
    *,
    decision_at: str,
    authorization: PromotionAuthorizationArtifact,
    evidence: AllocationPromotionEvidence,
    custody_hash: str,
) -> str:
    return _hmac_signature(
        _VERIFIED_PROMOTION_PROCESS_KEY,
        {
            "decision_at": decision_at,
            "authorization_artifact_hash": authorization.artifact_hash,
            "authorized_alpha_bp": authorization.authorized_alpha_bp,
            "evidence_hash": evidence.evidence_hash,
            "custody_hash": custody_hash,
        },
    )


def _registry_revision_is_present(path: Path, revision_id: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return revision_id in text
    if not isinstance(payload, dict):
        return False
    candidates: list[object] = [
        payload.get("registry_revision_id"),
        payload.get("revision_id"),
        payload.get("artifact_id"),
    ]
    nested = payload.get("revision")
    if isinstance(nested, dict):
        candidates.extend(
            [
                nested.get("registry_revision_id"),
                nested.get("revision_id"),
                nested.get("artifact_id"),
            ]
        )
    return revision_id in candidates


def _dataset_manifest_identity_hash(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("dataset manifest must contain an object")
    identity_hash = _as_text(
        payload.get("dataset_identity_hash"),
        label="dataset_identity_hash",
    )
    _require_sha256(identity_hash, field_name="dataset_identity_hash")
    return identity_hash


def _load_json_mapping(path: Path, *, label: str) -> Mapping[str, object]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be a JSON object")
    return value


def _as_mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return value


def _as_sequence(value: object, *, label: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, list):
        raise TypeError(f"{label} must be an array")
    return value


def _as_integer(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    return value


def _as_text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{label} must be a non-empty string")
    return value
