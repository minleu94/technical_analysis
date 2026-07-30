from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
import sqlite3

from ml_module.allocation_validation import (
    AllocationPromotionEvaluator,
    PromotionAuthorizationVerifier,
)
from ml_promotion_test_support import (
    build_promotion_test_custody,
)
from runtime.promotion_authority_secret_store import (
    PromotionAuthoritySecretStore,
)
from scripts.run_ml_promotion_authority import (
    POINTER_SCHEMA_VERSION,
    _payload_hash,
    run,
)
from tests.test_ml_allocation_copilot import _evidence


class _OpenCalendar:
    def is_official_trading_day(
        self,
        _target_date: date,
        allow_online_probe: bool = True,
    ):
        del allow_online_probe
        return True, "test_official_open"


def _write_pointer(path: Path, body: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {**body, "pointer_hash": _payload_hash(body)},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _registry(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE engineering_gate_revisions (
                item_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                category TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (item_id, revision)
            )"""
        )
        payload = {
            "item_id": "ml:revalidation",
            "revision": 1,
            "category": "ml_revalidation",
            "title": "test",
            "status": "in_progress",
            "owner": "machine",
            "earliest_validation_date": "2026-07-29",
            "progress_bp": 9000,
            "required_artifacts": ["evidence"],
            "validation_commands": ["test"],
            "completion_rules": ["policy"],
            "prohibited_actions": ["no broker"],
            "notes": "",
            "completion_evidence": [],
        }
        connection.execute(
            "INSERT INTO engineering_gate_revisions VALUES (?, ?, ?, ?, ?)",
            (
                "ml:revalidation",
                1,
                "ml_revalidation",
                "in_progress",
                json.dumps(payload),
            ),
        )


def test_missing_compatible_pointer_initializes_dpapi_and_skips(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"

    result = run(
        output_root=output_root,
        evidence_pointer_path=tmp_path / "missing.json",
        registry_database_path=tmp_path / "missing.sqlite",
        now=datetime.fromisoformat("2026-07-28T20:00:00+08:00"),
        calendar=_OpenCalendar(),
    )

    assert result["status"] == "skipped_evidence_unavailable"
    assert result["authorization_created"] is False
    assert result["formal_oos_allowed"] is False
    assert (
        output_root
        / "release_v4"
        / "ml_promotion_authority"
        / "authority_secret.dpapi.json"
    ).is_file()


def test_complete_bundle_is_signed_for_future_decision_and_verifies(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    release_root = output_root / "release_v4"
    custody = build_promotion_test_custody(
        release_root / "source",
        evidence=_evidence(),
        evaluator=AllocationPromotionEvaluator(),
        authorized_alpha_bp=2000,
    )
    pointer_path = (
        release_root
        / "ml_allocation_promotion_evidence"
        / "latest_pointer.json"
    )
    body: dict[str, object] = {
        "schema_version": POINTER_SCHEMA_VERSION,
        "status": "published",
        "publication_id": "promotion-evidence:test",
        "generated_at": "2026-07-28T19:30:00+08:00",
        "decision_at": "2026-07-29T08:30:00+08:00",
        "authority_required": True,
        "authorization_artifact_created": False,
        "evidence_hash": custody.evidence.evidence_hash,
        "evidence_file_hash": (
            "sha256:"
            + __import__("hashlib").sha256(
                custody.evidence_path.read_bytes()
            ).hexdigest()
        ),
        "promotion_evidence_path": str(custody.evidence_path),
        "model_artifact_path": str(custody.model_artifact_path),
        "dataset_manifest_path": str(custody.dataset_manifest_path),
        "oof_bundle_path": str(custody.oof_bundle_path),
        "shadow_evidence_path": str(custody.shadow_evidence_path),
        "replay_bundle_path": str(custody.oof_bundle_path),
        "promotion_reference_path": str(custody.shadow_evidence_path),
    }
    _write_pointer(pointer_path, body)
    registry_path = release_root / "engineering_gate_registry.sqlite"
    _registry(registry_path)
    now = datetime.fromisoformat("2026-07-28T20:00:00+08:00")

    result = run(
        output_root=output_root,
        evidence_pointer_path=pointer_path,
        registry_database_path=registry_path,
        now=now,
        calendar=_OpenCalendar(),
    )

    assert result["status"] == "authorized"
    assert result["authorized_alpha_bp"] == 2000
    assert result["formal_oos_allowed"] is False
    authority_pointer_path = Path(
        str(result["authorization_pointer_path"])
    )
    authority_pointer = json.loads(
        authority_pointer_path.read_text(encoding="utf-8")
    )
    secret = PromotionAuthoritySecretStore(
        release_root
        / "ml_promotion_authority"
        / "authority_secret.dpapi.json"
    ).load()
    verifier = PromotionAuthorizationVerifier(
        trusted_issuer_keys={secret.issuer_id: secret.signing_key},
        trusted_custody_roots=(release_root,),
        custody_id=secret.custody_id,
    )
    verification = verifier.verify_files(
        decision_at=datetime.fromisoformat(
            "2026-07-29T08:30:00+08:00"
        ),
        evidence_path=Path(authority_pointer["evidence_path"]),
        authorization_path=Path(
            authority_pointer["authorization_path"]
        ),
        registry_revision_path=Path(
            authority_pointer["registry_revision_path"]
        ),
        model_artifact_path=Path(
            authority_pointer["model_artifact_path"]
        ),
        dataset_manifest_path=Path(
            authority_pointer["dataset_manifest_path"]
        ),
        oof_bundle_path=Path(authority_pointer["oof_bundle_path"]),
        shadow_evidence_path=Path(
            authority_pointer["shadow_evidence_path"]
        ),
        expected_policy_hash=AllocationPromotionEvaluator().policy_hash,
    )
    assert verification.passed is True


def test_pointer_tamper_skips_without_authorization(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    pointer = (
        output_root
        / "release_v4"
        / "ml_allocation_promotion_evidence"
        / "latest_pointer.json"
    )
    _write_pointer(
        pointer,
        {
            "schema_version": POINTER_SCHEMA_VERSION,
            "authority_required": True,
            "authorization_artifact_created": False,
            "publication_id": "test",
            "generated_at": "2026-07-28T19:00:00+08:00",
            "promotion_evidence_path": "missing",
        },
    )
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    payload["publication_id"] = "tampered"
    pointer.write_text(json.dumps(payload), encoding="utf-8")

    result = run(
        output_root=output_root,
        evidence_pointer_path=pointer,
        registry_database_path=tmp_path / "missing.sqlite",
        now=datetime.fromisoformat("2026-07-28T20:00:00+08:00"),
        calendar=_OpenCalendar(),
    )

    assert result["status"] == "skipped_invalid_or_incomplete_custody"
    assert result["authorization_created"] is False

