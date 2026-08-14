from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts import audit_existing_ooc_calibration as audit


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def test_build_report_preserves_shadow_only_and_hash_binds_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_root = tmp_path / "release"
    training_run = release_root / "training" / "runs" / "run-1"
    training_manifest_path = training_run / "manifest.json"
    store_manifest_path = release_root / "store" / "manifest.json"
    _write_json(store_manifest_path, {"status": "complete"})
    store_file_hash = audit._file_sha256(store_manifest_path)
    training_manifest = {
        "run_id": "allocation-ooc-test",
        "run_identity": {"schema_version": "test"},
        "store_manifest_path": "../../../store/manifest.json",
        "store_manifest_hash": "sha256:" + "a" * 64,
        "store_manifest_file_hash": store_file_hash,
        "base_expert_count": 1,
        "base_experts": [{"artifact_path": "artifacts/base"}],
        "manifest_hash": "sha256:" + "b" * 64,
    }
    _write_json(training_manifest_path, training_manifest)

    class FakeStore:
        manifest: dict[str, Any] = {
            "manifest_hash": training_manifest["store_manifest_hash"],
            "row_count": 123,
        }
        feature_ids = ("feature",)
        folds = ({"fold_id": "fold-1"},)

    monkeypatch.setattr(
        audit,
        "_validate_training_manifest",
        lambda **_: None,
    )
    monkeypatch.setattr(audit, "_NumericStore", lambda _: FakeStore())
    monkeypatch.setattr(
        audit,
        "_read_and_validate_artifact",
        lambda _: {
            "store_manifest_hash": training_manifest["store_manifest_hash"],
        },
    )
    monkeypatch.setattr(
        audit,
        "_calibration_summary",
        lambda **_: {
            "status": "measured_cross_fitted_oof",
            "cross_fitted_calibration": True,
            "production_eligible": False,
            "promotion_pass": False,
            "horizons": [{"quality_pass": True}],
        },
    )

    report = audit.build_calibration_audit_report(
        training_manifest_path=training_manifest_path,
        batch_size=128,
    )

    assert report["status"] == "complete_shadow_diagnostic"
    assert report["read_only"] is True
    assert report["formal_oos_allowed"] is False
    assert report["production_eligible"] is False
    assert report["quality_pass"] is True
    assert report["promotion_pass"] is False
    assert report["custody"]["store_manifest_file_hash"] == store_file_hash
    declared_hash = report["audit_hash"]
    body = dict(report)
    del body["audit_hash"]
    assert declared_hash == audit._payload_hash(body)


def test_build_report_rejects_store_outside_release_custody(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_root = tmp_path / "release"
    training_run = release_root / "training" / "runs" / "run-1"
    training_manifest_path = training_run / "manifest.json"
    outside_store = tmp_path / "outside" / "manifest.json"
    _write_json(outside_store, {})
    _write_json(
        training_manifest_path,
        {
            "run_id": "allocation-ooc-test",
            "run_identity": {},
            "store_manifest_path": "../../../../outside/manifest.json",
            "base_expert_count": 0,
            "base_experts": [],
            "manifest_hash": "sha256:" + "b" * 64,
        },
    )
    monkeypatch.setattr(
        audit,
        "_validate_training_manifest",
        lambda **_: None,
    )

    with pytest.raises(ValueError, match="escapes the release custody root"):
        audit.build_calibration_audit_report(
            training_manifest_path=training_manifest_path,
        )
