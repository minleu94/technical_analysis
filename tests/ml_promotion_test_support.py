from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import json
from pathlib import Path
from typing import Mapping

from app_module.portfolio_allocation_dtos import PromotionAuthorizationReference
from ml_module.allocation_validation import (
    AllocationPromotionEvidence,
    AllocationPromotionEvaluator,
    PromotionAuthorizationArtifact,
    PromotionAuthorizationVerification,
    PromotionAuthorizationVerifier,
    file_content_hash,
)


TRUSTED_ISSUER_ID = "automatic-promotion-gate:v1"
TRUSTED_ISSUER_KEY = bytes.fromhex("71" * 32)
TRUSTED_CUSTODY_ID = "baldr-promotion-custody:v1"
REGISTRY_REVISION_ID = "registry-revision:001"


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


@dataclass(frozen=True)
class PromotionTestCustody:
    root: Path
    evidence: AllocationPromotionEvidence
    authorization: PromotionAuthorizationArtifact
    verifier: PromotionAuthorizationVerifier
    evidence_path: Path
    authorization_path: Path
    registry_revision_path: Path
    model_artifact_path: Path
    dataset_manifest_path: Path
    oof_bundle_path: Path
    shadow_evidence_path: Path

    def verify(
        self,
        *,
        decision_at: datetime,
        evaluator: AllocationPromotionEvaluator,
        expected_alpha_bp: int | None = None,
        expected_model_id: str | None = None,
        expected_dataset_id: str | None = None,
        expected_model_hash: str | None = None,
        expected_dataset_identity_hash: str | None = None,
        expected_dataset_manifest_file_hash: str | None = None,
    ) -> PromotionAuthorizationVerification:
        return self.verifier.verify_files(
            decision_at=decision_at,
            evidence_path=self.evidence_path,
            authorization_path=self.authorization_path,
            registry_revision_path=self.registry_revision_path,
            model_artifact_path=self.model_artifact_path,
            dataset_manifest_path=self.dataset_manifest_path,
            oof_bundle_path=self.oof_bundle_path,
            shadow_evidence_path=self.shadow_evidence_path,
            expected_policy_hash=evaluator.policy_hash,
            expected_alpha_bp=expected_alpha_bp,
            expected_model_id=expected_model_id,
            expected_dataset_id=expected_dataset_id,
            expected_model_hash=expected_model_hash,
            expected_dataset_identity_hash=expected_dataset_identity_hash,
            expected_dataset_manifest_file_hash=(
                expected_dataset_manifest_file_hash
            ),
            expected_authorization_artifact_hash=self.authorization.artifact_hash,
        )

    def reference(self) -> PromotionAuthorizationReference:
        return PromotionAuthorizationReference(
            authorization_path=str(self.authorization_path),
            evidence_path=str(self.evidence_path),
            registry_revision_path=str(self.registry_revision_path),
            model_artifact_path=str(self.model_artifact_path),
            dataset_manifest_path=str(self.dataset_manifest_path),
            oof_bundle_path=str(self.oof_bundle_path),
            shadow_evidence_path=str(self.shadow_evidence_path),
            authorization_artifact_hash=self.authorization.artifact_hash,
        )


def build_promotion_test_custody(
    root: Path,
    *,
    evidence: AllocationPromotionEvidence,
    evaluator: AllocationPromotionEvaluator,
    authorized_alpha_bp: int,
    issuer_id: str = TRUSTED_ISSUER_ID,
    signing_key: bytes = TRUSTED_ISSUER_KEY,
    trusted_issuer_keys: Mapping[str, bytes] | None = None,
    issued_at: str = "2026-07-29T08:00:00+08:00",
    decision_valid_from: str = "2026-07-29T08:00:00+08:00",
    decision_valid_until: str = "2026-07-29T09:00:00+08:00",
    frozen_at: str = "2026-07-29T07:00:00+08:00",
) -> PromotionTestCustody:
    root.mkdir(parents=True, exist_ok=True)
    model_path = root / "model.bin"
    dataset_path = root / "dataset_manifest.json"
    oof_path = root / "oof_bundle.json"
    shadow_path = root / "shadow_evidence.json"
    registry_path = root / "registry_revision.json"
    evidence_path = root / "promotion_evidence.json"
    authorization_path = root / "promotion_authorization.json"

    model_path.write_bytes(b"baldr-allocation-model-v1")
    write_json(
        dataset_path,
        {
            "schema_version": "allocation-training-output-manifest-v2",
            "dataset_id": evidence.dataset_id,
            "dataset_identity_hash": evidence.dataset_identity_hash,
            "rows": 100,
        },
    )
    write_json(oof_path, {"bundle_id": "oof-v1", "folds": 4})
    write_json(shadow_path, {"shadow_days": 20, "status": "complete"})
    write_json(
        registry_path,
        {
            "registry_revision_id": REGISTRY_REVISION_ID,
            "status": "append_only",
        },
    )

    bound_evidence = replace(
        evidence,
        model_artifact_hash=file_content_hash(model_path),
        dataset_manifest_file_hash=file_content_hash(dataset_path),
        oof_bundle_hash=file_content_hash(oof_path),
        shadow_evidence_hash=file_content_hash(shadow_path),
    )
    write_json(evidence_path, bound_evidence.canonical_payload())
    authorization = PromotionAuthorizationArtifact.create(
        artifact_id="promotion-auth:v4:001",
        registry_revision_id=REGISTRY_REVISION_ID,
        registry_revision_hash=file_content_hash(registry_path),
        custody_id=TRUSTED_CUSTODY_ID,
        issuer_id=issuer_id,
        issued_at=issued_at,
        decision_valid_from=decision_valid_from,
        decision_valid_until=decision_valid_until,
        freeze_id="freeze:v4:001",
        frozen_at=frozen_at,
        model_id=bound_evidence.model_id,
        dataset_id=bound_evidence.dataset_id,
        authorized_evidence_hash=bound_evidence.evidence_hash,
        evidence_artifact_hash=file_content_hash(evidence_path),
        authorized_policy_hash=evaluator.policy_hash,
        authorized_alpha_bp=authorized_alpha_bp,
        model_artifact_hash=bound_evidence.model_artifact_hash,
        dataset_identity_hash=bound_evidence.dataset_identity_hash,
        dataset_manifest_file_hash=(
            bound_evidence.dataset_manifest_file_hash
        ),
        oof_bundle_hash=bound_evidence.oof_bundle_hash,
        shadow_evidence_hash=bound_evidence.shadow_evidence_hash,
        signing_key=signing_key,
    )
    write_json(authorization_path, authorization.to_dict())
    verifier = PromotionAuthorizationVerifier(
        trusted_issuer_keys=(
            trusted_issuer_keys
            if trusted_issuer_keys is not None
            else {TRUSTED_ISSUER_ID: TRUSTED_ISSUER_KEY}
        ),
        trusted_custody_roots=(root,),
        custody_id=TRUSTED_CUSTODY_ID,
    )
    return PromotionTestCustody(
        root=root,
        evidence=bound_evidence,
        authorization=authorization,
        verifier=verifier,
        evidence_path=evidence_path,
        authorization_path=authorization_path,
        registry_revision_path=registry_path,
        model_artifact_path=model_path,
        dataset_manifest_path=dataset_path,
        oof_bundle_path=oof_path,
        shadow_evidence_path=shadow_path,
    )
