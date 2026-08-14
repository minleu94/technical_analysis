from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from scripts import run_daily_ml_allocation_orchestration as orchestration


TAIPEI = ZoneInfo("Asia/Taipei")
DECISION_AT = datetime(2026, 7, 31, 8, 30, tzinfo=TAIPEI)


class _Calendar:
    def __init__(
        self,
        states: dict[date, tuple[bool | None, str]],
    ) -> None:
        self._states = states

    def is_official_trading_day(
        self,
        target_date: date,
    ) -> tuple[bool | None, str]:
        return self._states.get(
            target_date,
            (None, "test_calendar_missing"),
        )


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _write_release(
    root: Path,
    *,
    training_as_of: str = "2026-07-30T08:30:00+08:00",
) -> Path:
    root.mkdir(parents=True)
    artifact = root / "allocation_model_v2.joblib"
    artifact_bytes = b"bounded-release-artifact"
    artifact.write_bytes(artifact_bytes)
    manifest = {
        "schema_version": "allocation-training-output-manifest-v2",
        "artifact_file": artifact.name,
        "artifact_hash": _sha256_bytes(artifact_bytes),
        "dataset_id": "all_field_enriched-test-dataset",
        "dataset_identity_hash": f"sha256:{'a' * 64}",
        "dataset_manifest_file_hash": f"sha256:{'b' * 64}",
        "training_as_of": training_as_of,
    }
    (root / "training_manifest_v2.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return root


def _calendar() -> _Calendar:
    return _Calendar(
        {
            date(2026, 7, 31): (True, "official_open"),
            date(2026, 7, 30): (True, "official_open"),
        }
    )


def _raw_publication(tmp_path: Path) -> orchestration.RawPublication:
    publication_directory = tmp_path / "raw" / "runs" / "publication-1"
    dataset_manifest = (
        publication_directory / "all_field_enriched" / "manifest.json"
    )
    return orchestration.RawPublication(
        publication_id="publication-1",
        publication_directory=publication_directory,
        publication_manifest_path=publication_directory / "manifest.json",
        publication_manifest_hash=f"sha256:{'1' * 64}",
        publication_manifest_file_hash=f"sha256:{'c' * 64}",
        dataset_manifest_path=dataset_manifest,
        dataset_manifest_hash=f"sha256:{'2' * 64}",
        dataset_manifest_file_hash=f"sha256:{'d' * 64}",
        row_count=123,
        shard_count=3,
    )


def _post_freeze_result() -> dict[str, object]:
    return {
        "status": "post_freeze_shadow_input_built",
        "selected_symbol_count": 11,
        "selected_row_count": 11,
        "inference_input_compressed_hash": _sha256_bytes(b"input"),
        "audit_hash": f"sha256:{'4' * 64}",
        "production_blend_alpha_bp": 0,
        "broker_order_allowed": False,
    }


def _inference_result() -> dict[str, object]:
    return {
        "status": "inference_completed",
        "proposal_hash": f"sha256:{'5' * 64}",
        "replay_hash": f"sha256:{'6' * 64}",
        "coverage_bp": 10_000,
        "fallback_reason": None,
        "production_blend_alpha_bp": 0,
        "broker_order_allowed": False,
    }


def _promotion_result(output_root: Path) -> dict[str, object]:
    artifact = (
        output_root
        / "scheduled"
        / "ml_allocation_copilot"
        / "artifacts"
        / "20260731_test_promotion.json"
    )
    sidecar = (
        output_root
        / "scheduled"
        / "ml_allocation_copilot"
        / "sidecar"
        / "20260731_test_shadow.json"
    )
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("{}", encoding="utf-8")
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text("{}", encoding="utf-8")
    return {
        "status": "passed_rule_only",
        "selected_alpha_bp": 0,
        "production_blend_alpha_bp": 0,
        "formal_oos_allowed": False,
        "broker_execution": False,
        "failed_reasons": ["promotion_evidence_missing"],
        "status_hash": f"sha256:{'7' * 64}",
        "artifact_path": str(artifact),
        "artifact_hash": f"sha256:{'8' * 64}",
        "sidecar_path": str(sidecar),
        "sidecar_record_hash": f"sha256:{'9' * 64}",
    }


def _shadow_result(output_root: Path) -> dict[str, object]:
    root = (
        output_root
        / "scheduled"
        / "ml_allocation_copilot"
        / "shadow_evidence_collector"
    )
    observation = root / "observations" / "test.json"
    evidence = root / "evidence" / "test.json"
    advice = root / "production_advice" / "test.json"
    for path in (observation, evidence, advice):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    return {
        "status": "shadow_observation_recorded",
        "observation_recorded": True,
        "shadow_day_credit_allowed": True,
        "observation_idempotent": False,
        "observation_revision": 1,
        "observation_hash": f"sha256:{'f' * 64}",
        "observation_path": str(observation),
        "lane_count": 4,
        "lane_alphas_bp": [0, 2000, 3500, 5000],
        "evidence_status": "insufficient_evidence",
        "evidence_hash": f"sha256:{'0' * 64}",
        "evidence_path": str(evidence),
        "matured_observation_count": 0,
        "compatible_promotion_evidence_path": None,
        "production_advice_path": str(advice),
        "production_advice_hash": f"sha256:{'a' * 64}",
        "selected_alpha_bp": 0,
        "formal_oos_allowed": False,
        "production_action_allowed": False,
        "broker_order_allowed": False,
    }


def _run(
    tmp_path: Path,
    release_root: Path,
    *,
    calendar: _Calendar | None = None,
    promotion_reference_pointer_path: Path | None = None,
    promotion_authority_pointer_path: Path | None = None,
) -> dict[str, object]:
    return orchestration.run(
        database_path=tmp_path / "twstock.db",
        output_root=tmp_path / "output",
        release_root=release_root,
        decision_at=DECISION_AT,
        calendar=calendar or _calendar(),
        promotion_reference_pointer_path=promotion_reference_pointer_path,
        promotion_authority_pointer_path=promotion_authority_pointer_path,
    )


def test_automatic_previous_candidates_are_bounded_to_past_trading_days() -> None:
    requested = datetime(2026, 8, 13, 8, 30, tzinfo=TAIPEI)
    now = datetime(2026, 8, 12, 11, 41, tzinfo=TAIPEI)
    calendar = _Calendar(
        {
            date(2026, 8, 12): (True, "official_open"),
            date(2026, 8, 11): (True, "official_open"),
            date(2026, 8, 10): (False, "holiday"),
            date(2026, 8, 9): (False, "weekend"),
            date(2026, 8, 8): (False, "weekend"),
            date(2026, 8, 7): (True, "official_open"),
        }
    )
    candidates = orchestration._automatic_previous_decision_candidates(
        calendar=calendar,
        requested_decision_at=requested,
        now=now,
    )

    assert candidates == (
        datetime(2026, 8, 12, 8, 30, tzinfo=TAIPEI),
        datetime(2026, 8, 11, 8, 30, tzinfo=TAIPEI),
        datetime(2026, 8, 7, 8, 30, tzinfo=TAIPEI),
    )
    assert all(candidate.date() <= now.date() for candidate in candidates)


def test_automatic_previous_candidates_fail_closed_on_unknown_calendar() -> None:
    requested = datetime(2026, 8, 13, 8, 30, tzinfo=TAIPEI)
    now = datetime(2026, 8, 12, 11, 41, tzinfo=TAIPEI)
    calendar = _Calendar(
        {
            date(2026, 8, 12): (None, "calendar_missing"),
        }
    )

    with pytest.raises(
        RuntimeError,
        match="automatic_catch_up_calendar_unknown",
    ):
        orchestration._automatic_previous_decision_candidates(
            calendar=calendar,
            requested_decision_at=requested,
            now=now,
        )


def test_automatic_mode_does_not_search_when_candidate_is_not_future() -> None:
    requested = datetime(2026, 8, 12, 8, 30, tzinfo=TAIPEI)
    now = datetime(2026, 8, 12, 7, 30, tzinfo=TAIPEI)
    calendar = _Calendar(
        {
            date(2026, 8, 11): (True, "official_open"),
        }
    )

    assert orchestration._automatic_previous_decision_candidates(
        calendar=calendar,
        requested_decision_at=requested,
        now=now,
    ) == ()


def test_main_wires_auto_catch_up_selection_into_hash_bound_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = datetime(2026, 8, 12, 8, 30, tzinfo=TAIPEI)
    requested = datetime(2026, 8, 13, 8, 30, tzinfo=TAIPEI)
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        orchestration,
        "OfficialTradingCalendar",
        lambda _database_path: object(),
    )
    monkeypatch.setattr(
        orchestration,
        "_promotion_trust_configuration",
        lambda **_kwargs: ({}, (), None),
    )
    monkeypatch.setattr(
        orchestration,
        "_parse_decision_at",
        lambda _value: requested,
    )
    monkeypatch.setattr(
        orchestration,
        "_automatic_previous_decision_candidates",
        lambda **_kwargs: (selected,),
    )
    monkeypatch.setattr(
        orchestration,
        "_taipei_now",
        lambda: datetime(2026, 8, 12, 11, 41, tzinfo=TAIPEI),
    )

    calls: list[dict[str, Any]] = []

    def fake_run(**kwargs: Any) -> dict[str, object]:
        calls.append(kwargs)
        if len(calls) == 1:
            return {
                "status": "passed_rule_only",
                "orchestration_status": "fail_closed",
                "failed_stage": "post_freeze_input",
                "failed_reasons": [
                    "post_freeze_input:ValueError:expected_price_date not ready"
                ],
                "decision_selection_mode": "automatic_candidate",
            }
        captured.update(kwargs)
        return {
            "status": "passed_rule_only",
            "orchestration_status": "completed",
            "failed_stage": None,
            "failed_reasons": [],
            "decision_selection_mode": "automatic_catch_up",
        }

    monkeypatch.setattr(orchestration, "run", fake_run)

    result = orchestration.main(
        [
            "--database",
            str(tmp_path / "twstock.db"),
            "--output-root",
            str(tmp_path / "output"),
            "--release-root",
            str(tmp_path / "release"),
            "--auto-catch-up",
        ]
    )

    assert result == 0
    assert len(calls) == 2
    assert captured["decision_at"] == selected
    assert captured["requested_decision_at"] == requested
    assert captured["decision_selection_mode"] == "automatic_catch_up"
    assert captured["decision_selection_attempts"]


def test_success_runs_raw_input_inference_then_promotion_and_hashes_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_root = _write_release(tmp_path / "release")
    reference_pointer_path = tmp_path / "reference" / "latest_reference.json"
    frozen_reference = orchestration.FrozenPromotionReference(
        pointer_path=reference_pointer_path.resolve(),
        pointer_file_hash=f"sha256:{'1' * 64}",
        reference_path=(
            tmp_path / "reference" / "runs" / "reference.json"
        ).resolve(),
        reference_hash=f"sha256:{'2' * 64}",
        reference_file_hash=f"sha256:{'3' * 64}",
    )
    calls: list[str] = []
    captured: dict[str, Any] = {}

    def fake_raw(**kwargs: Any) -> orchestration.RawPublication:
        calls.append("raw")
        captured["raw"] = kwargs
        return _raw_publication(tmp_path)

    def fake_input(**kwargs: Any) -> dict[str, object]:
        calls.append("input")
        captured["input"] = kwargs
        Path(kwargs["input_output"]).parent.mkdir(parents=True, exist_ok=True)
        Path(kwargs["input_output"]).write_bytes(b"input")
        Path(kwargs["audit_output"]).write_text("{}", encoding="utf-8")
        return _post_freeze_result()

    def fake_inference(**kwargs: Any) -> dict[str, object]:
        calls.append("inference")
        captured["inference"] = kwargs
        Path(kwargs["proposal_output"]).write_text("{}", encoding="utf-8")
        Path(kwargs["audit_output"]).write_text("{}", encoding="utf-8")
        return _inference_result()

    def fake_promotion(**kwargs: Any) -> dict[str, object]:
        calls.append("promotion")
        captured["promotion"] = kwargs
        return _promotion_result(tmp_path / "output")

    def fake_shadow(**kwargs: Any) -> dict[str, object]:
        calls.append("shadow")
        captured["shadow"] = kwargs
        return _shadow_result(tmp_path / "output")

    monkeypatch.setattr(orchestration, "_build_raw_publication", fake_raw)
    monkeypatch.setattr(orchestration, "_build_post_freeze_input", fake_input)
    monkeypatch.setattr(
        orchestration,
        "_calculate_inference_universe_hash",
        lambda _path: f"sha256:{'e' * 64}",
    )
    monkeypatch.setattr(
        orchestration,
        "_load_promotion_reference_pointer",
        lambda **_kwargs: frozen_reference,
    )
    monkeypatch.setattr(
        orchestration,
        "_load_inference_rows",
        lambda _path: (),
    )
    monkeypatch.setattr(orchestration, "_run_inference", fake_inference)
    monkeypatch.setattr(
        orchestration,
        "_run_shadow_evidence_collector",
        fake_shadow,
    )
    monkeypatch.setattr(
        orchestration,
        "_run_promotion_evaluator",
        fake_promotion,
    )

    result = _run(
        tmp_path,
        release_root,
        promotion_reference_pointer_path=reference_pointer_path,
    )

    assert calls == ["raw", "input", "inference", "shadow", "promotion"]
    assert captured["raw"]["symbols"] == orchestration.DEFAULT_SYMBOLS
    assert captured["raw"]["strict_t_minus_one"] == date(2026, 7, 30)
    assert captured["raw"]["raw_lookback_days"] == 730
    assert captured["input"]["strict_t_minus_one"] == date(2026, 7, 30)
    assert captured["inference"]["policy_hash"] == orchestration.POLICY_HASH
    assert captured["inference"]["expected_universe_hash"] == (
        f"sha256:{'e' * 64}"
    )
    assert captured["shadow"]["strict_t_minus_one"] == date(2026, 7, 30)
    assert captured["shadow"]["proposal_hash"] == f"sha256:{'5' * 64}"
    assert captured["shadow"]["promotion_reference"] == frozen_reference
    assert captured["shadow"]["model_artifact_path"] == (
        release_root / "allocation_model_v2.joblib"
    ).resolve()
    assert captured["shadow"]["post_freeze_input_hash"] == _sha256_bytes(
        b"input"
    )
    assert captured["promotion"]["evidence_path"] is None
    assert (
        captured["promotion"]["model_artifact_path"]
        == (release_root / "allocation_model_v2.joblib").resolve()
    )
    assert result["status"] == "passed_rule_only"
    assert result["orchestration_status"] == "completed"
    assert result["ml_pipeline_status"] == "completed"
    assert result["post_freeze_input_status"] == "completed"
    assert result["inference_status"] == "completed"
    assert result["promotion_status"] == "completed"
    assert str(result["orchestration_run_hash"]).startswith("sha256:")
    assert result["release_dataset_identity_hash"] == f"sha256:{'a' * 64}"
    assert result["release_dataset_manifest_file_hash"] == f"sha256:{'b' * 64}"
    assert result["promotion_reference_hash"] == f"sha256:{'2' * 64}"
    assert result["promotion_reference_file_hash"] == f"sha256:{'3' * 64}"
    assert result["selected_alpha_bp"] == 0
    assert result["production_blend_alpha_bp"] == 0
    assert result["formal_oos_allowed"] is False
    assert result["broker_order_allowed"] is False
    assert result["broker_execution"] is False
    assert result["shadow_observation_recorded"] is True
    assert result["shadow_day_credit_allowed"] is True
    assert result["shadow_evidence_status"] == "insufficient_evidence"
    assert result["shadow_lane_count"] == 4
    assert result["matured_shadow_observation_count"] == 0
    assert result["proposal_hash"] == f"sha256:{'5' * 64}"
    assert str(result["proposal_file_hash"]).startswith("sha256:")
    assert result["replay_hash"] == f"sha256:{'6' * 64}"
    assert result["inference_universe_hash"] == f"sha256:{'e' * 64}"
    assert str(result["post_freeze_audit_file_hash"]).startswith("sha256:")
    assert str(result["inference_audit_file_hash"]).startswith("sha256:")
    assert result["promotion_status_hash"] == f"sha256:{'7' * 64}"
    assert str(result["promotion_artifact_file_hash"]).startswith("sha256:")
    assert result["decision_selection_mode"] == "requested"
    assert result["requested_decision_at"] == DECISION_AT.isoformat(
        timespec="seconds"
    )
    assert result["decision_selection_attempts"] == []
    assert str(result["promotion_sidecar_file_hash"]).startswith("sha256:")

    status_path = (
        tmp_path
        / "output"
        / "scheduled"
        / "ml_allocation_copilot"
        / "latest_status.json"
    )
    stored = json.loads(status_path.read_text(encoding="utf-8"))
    status_hash = stored.pop("status_hash")
    assert status_hash == orchestration._payload_hash(stored)
    assert stored == {key: value for key, value in result.items() if key != "status_hash"}


def test_signed_authority_for_different_model_cannot_drive_inference_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_root = _write_release(tmp_path / "release")
    mismatched_model = tmp_path / "release_v4" / "other-model.json"
    mismatched_model.parent.mkdir(parents=True)
    mismatched_model.write_text("{}", encoding="utf-8")
    authority_inputs = {
        field_name: mismatched_model
        for field_name in (
            "evidence_path",
            "authorization_path",
            "registry_revision_path",
            "model_artifact_path",
            "dataset_manifest_path",
            "oof_bundle_path",
            "shadow_evidence_path",
        )
    }
    captured: dict[str, object] = {}

    def fake_input(**kwargs: Any) -> dict[str, object]:
        Path(kwargs["input_output"]).parent.mkdir(parents=True, exist_ok=True)
        Path(kwargs["input_output"]).write_bytes(b"input")
        Path(kwargs["audit_output"]).write_text("{}", encoding="utf-8")
        return _post_freeze_result()

    def fake_inference(**kwargs: Any) -> dict[str, object]:
        Path(kwargs["proposal_output"]).write_text("{}", encoding="utf-8")
        Path(kwargs["audit_output"]).write_text("{}", encoding="utf-8")
        return _inference_result()

    def fake_promotion(**kwargs: Any) -> dict[str, object]:
        captured.update(kwargs)
        return _promotion_result(tmp_path / "output")

    monkeypatch.setattr(
        orchestration,
        "_build_raw_publication",
        lambda **_kwargs: _raw_publication(tmp_path),
    )
    monkeypatch.setattr(
        orchestration,
        "_build_post_freeze_input",
        fake_input,
    )
    monkeypatch.setattr(
        orchestration,
        "_calculate_inference_universe_hash",
        lambda _path: f"sha256:{'e' * 64}",
    )
    monkeypatch.setattr(orchestration, "_load_inference_rows", lambda _path: ())
    monkeypatch.setattr(orchestration, "_run_inference", fake_inference)
    monkeypatch.setattr(
        orchestration,
        "_run_shadow_evidence_collector",
        lambda **_kwargs: _shadow_result(tmp_path / "output"),
    )
    monkeypatch.setattr(
        orchestration,
        "_load_promotion_authority_pointer",
        lambda **_kwargs: authority_inputs,
    )
    monkeypatch.setattr(
        orchestration,
        "_run_promotion_evaluator",
        fake_promotion,
    )

    result = _run(
        tmp_path,
        release_root,
        promotion_authority_pointer_path=tmp_path / "authority.json",
    )

    assert captured["authorization_path"] is None
    assert captured["evidence_path"] is None
    assert captured["model_artifact_path"] == (
        release_root / "allocation_model_v2.joblib"
    ).resolve()
    assert result["promotion_authority_pointer_used"] is False
    assert result["promotion_authority_pointer_rejection"] == (
        "inference_release_custody_mismatch:ValueError"
    )
    assert result["production_blend_alpha_bp"] == 0
    assert result["formal_oos_allowed"] is False


def test_not_strictly_post_freeze_fails_before_raw_or_promotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_root = _write_release(
        tmp_path / "release",
        training_as_of="2026-07-31T08:30:00+08:00",
    )
    calls: list[str] = []

    def should_not_run(**_kwargs: Any) -> None:
        calls.append("unexpected")
        raise AssertionError("downstream stage must not run")

    monkeypatch.setattr(
        orchestration,
        "_build_raw_publication",
        should_not_run,
    )
    monkeypatch.setattr(
        orchestration,
        "_run_promotion_evaluator",
        should_not_run,
    )

    result = _run(tmp_path, release_root)

    assert calls == []
    assert result["status"] == "passed_rule_only"
    assert result["failed_stage"] == "release_preflight"
    assert result["selected_alpha_bp"] == 0
    assert result["formal_oos_allowed"] is False
    assert result["broker_order_allowed"] is False
    assert result["shadow_observation_recorded"] is False
    assert result["shadow_day_credit_allowed"] is False
    assert "strictly after" in str(result["failed_reasons"])


def test_promotion_reference_pointer_is_hash_and_release_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_root = _write_release(tmp_path / "release")
    release = orchestration._load_frozen_release(release_root)
    publication_root = tmp_path / "reference"
    reference_path = publication_root / "runs" / "v1" / "reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text("{}", encoding="utf-8")
    reference_hash = f"sha256:{'c' * 64}"
    reference_file_hash = _sha256_bytes(reference_path.read_bytes())
    pointer_path = publication_root / "latest_reference.json"
    pointer_path.write_text(
        json.dumps(
            {
                "schema_version": (
                    orchestration.PROMOTION_REFERENCE_POINTER_SCHEMA_VERSION
                ),
                "reference_path": str(reference_path.resolve()),
                "reference_hash": reference_hash,
                "reference_file_hash": reference_file_hash,
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def fake_load(path: Path, **kwargs: object) -> dict[str, object]:
        captured["path"] = path
        captured.update(kwargs)
        return {"reference_hash": reference_hash}

    monkeypatch.setattr(
        orchestration,
        "load_promotion_reference",
        fake_load,
    )

    result = orchestration._load_promotion_reference_pointer(
        pointer_path=pointer_path,
        release=release,
        policy_hash=orchestration.POLICY_HASH,
    )

    assert result.reference_path == reference_path.resolve()
    assert result.reference_hash == reference_hash
    assert result.reference_file_hash == reference_file_hash
    assert captured["expected_model_artifact_hash"] == release.artifact_hash
    assert captured["expected_dataset_identity_hash"] == (
        release.dataset_identity_hash
    )
    assert captured["expected_promotion_policy_hash"] == (
        orchestration.POLICY_HASH
    )


def _write_authority_pointer(
    root: Path,
    *,
    decision_at: datetime = DECISION_AT,
) -> tuple[Path, dict[str, Path]]:
    root.mkdir(parents=True)
    paths = {
        "evidence_path": root / "evidence.json",
        "authorization_path": root / "authorization.json",
        "registry_revision_path": root / "registry_revision.json",
        "model_artifact_path": root / "model.joblib",
        "dataset_manifest_path": root / "dataset_manifest.json",
        "oof_bundle_path": root / "oof_bundle.json",
        "shadow_evidence_path": root / "shadow_evidence.json",
    }
    for path in paths.values():
        path.write_text("{}", encoding="utf-8")
    body: dict[str, object] = {
        "schema_version": (
            orchestration.PROMOTION_AUTHORITY_POINTER_SCHEMA_VERSION
        ),
        "custody_root": str(root.resolve()),
        "decision_at": decision_at.isoformat(timespec="seconds"),
        "decision_valid_from": (
            decision_at.replace(minute=0)
        ).isoformat(timespec="seconds"),
        "decision_valid_until": (
            decision_at.replace(hour=9, minute=0)
        ).isoformat(timespec="seconds"),
        "authorization_file_hash": orchestration._file_hash(
            paths["authorization_path"]
        ),
        **{
            field_name: str(path.resolve())
            for field_name, path in paths.items()
        },
    }
    pointer = {**body, "pointer_hash": orchestration._payload_hash(body)}
    pointer_path = root / "latest_authorization_pointer.json"
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    return pointer_path, paths


def test_promotion_authority_pointer_is_decision_and_custody_bound(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "release_v4"
    pointer_path, paths = _write_authority_pointer(release_root)

    result = orchestration._load_promotion_authority_pointer(
        pointer_path=pointer_path,
        decision_at=DECISION_AT,
        release_root=release_root,
    )

    assert result == {
        field_name: path.resolve()
        for field_name, path in paths.items()
    }


def test_invalid_promotion_authority_pointer_fails_closed_to_none(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "release_v4"
    pointer_path, _paths = _write_authority_pointer(release_root)
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["decision_at"] = "2026-08-01T08:30:00+08:00"
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")

    assert (
        orchestration._load_promotion_authority_pointer(
            pointer_path=pointer_path,
            decision_at=DECISION_AT,
            release_root=release_root,
        )
        is None
    )

    pointer_path.write_text("{not-json", encoding="utf-8")
    assert (
        orchestration._load_promotion_authority_pointer(
            pointer_path=pointer_path,
            decision_at=DECISION_AT,
            release_root=release_root,
        )
        is None
    )


def test_parser_output_root_drives_all_default_release_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "custom-output"
    monkeypatch.setenv("OUTPUT_ROOT", str(output_root))
    monkeypatch.delenv("BALDR_ML_RELEASE_ROOT", raising=False)

    args = orchestration.build_parser().parse_args([])

    assert args.output_root == output_root
    assert args.release_root == (
        output_root / "release_v4" / "ml_allocation_bounded_v4_operational"
    )
    assert args.paper_state_db == (
        output_root / "paper_portfolio" / "paper_portfolio.sqlite"
    )
    assert args.promotion_reference_pointer == (
        output_root
        / "release_v4"
        / "ml_promotion_reference_v4"
        / "latest_reference.json"
    )
    assert args.promotion_authorization_pointer == (
        output_root
        / "release_v4"
        / "ml_promotion_authority"
        / "latest_authorization_pointer.json"
    )


def test_release_missing_dataset_file_custody_hash_fails_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_root = _write_release(tmp_path / "release")
    manifest_path = release_root / "training_manifest_v2.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("dataset_manifest_file_hash")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    downstream_calls: list[str] = []

    def should_not_run(**_kwargs: Any) -> None:
        downstream_calls.append("unexpected")
        raise AssertionError("downstream stage must not run")

    monkeypatch.setattr(
        orchestration,
        "_build_raw_publication",
        should_not_run,
    )

    result = _run(tmp_path, release_root)

    assert downstream_calls == []
    assert result["status"] == "passed_rule_only"
    assert result["failed_stage"] == "release_preflight"
    assert "dataset_manifest_file_hash" in str(result["failed_reasons"])
    assert result["production_blend_alpha_bp"] == 0
    assert result["broker_order_allowed"] is False


def test_missing_strict_t_minus_one_raw_fails_closed_without_shadow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_root = _write_release(tmp_path / "release")
    promotion_calls: list[str] = []

    def insufficient_raw(**_kwargs: Any) -> orchestration.RawPublication:
        raise ValueError("strict T-1 raw rows are missing")

    def should_not_promote(**_kwargs: Any) -> dict[str, object]:
        promotion_calls.append("promotion")
        return _promotion_result(tmp_path / "output")

    monkeypatch.setattr(
        orchestration,
        "_build_raw_publication",
        insufficient_raw,
    )
    monkeypatch.setattr(
        orchestration,
        "_run_promotion_evaluator",
        should_not_promote,
    )

    result = _run(tmp_path, release_root)

    assert promotion_calls == []
    assert result["status"] == "passed_rule_only"
    assert result["failed_stage"] == "raw_pit_publication"
    assert result["production_blend_alpha_bp"] == 0
    assert result["formal_oos_allowed"] is False
    assert result["broker_execution"] is False
    assert result["shadow_observation_recorded"] is False
    sidecar_root = (
        tmp_path
        / "output"
        / "scheduled"
        / "ml_allocation_copilot"
        / "sidecar"
    )
    assert not sidecar_root.exists()


def test_inference_failure_never_invokes_promotion_or_records_shadow_day(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_root = _write_release(tmp_path / "release")
    promotion_calls: list[str] = []

    def fake_input(**kwargs: Any) -> dict[str, object]:
        Path(kwargs["input_output"]).parent.mkdir(parents=True, exist_ok=True)
        Path(kwargs["input_output"]).write_bytes(b"input")
        Path(kwargs["audit_output"]).write_text("{}", encoding="utf-8")
        return _post_freeze_result()

    def failed_inference(**_kwargs: Any) -> dict[str, object]:
        raise RuntimeError("controlled inference failure")

    def should_not_promote(**_kwargs: Any) -> dict[str, object]:
        promotion_calls.append("promotion")
        return _promotion_result(tmp_path / "output")

    monkeypatch.setattr(
        orchestration,
        "_build_raw_publication",
        lambda **_kwargs: _raw_publication(tmp_path),
    )
    monkeypatch.setattr(
        orchestration,
        "_build_post_freeze_input",
        fake_input,
    )
    monkeypatch.setattr(
        orchestration,
        "_calculate_inference_universe_hash",
        lambda _path: f"sha256:{'e' * 64}",
    )
    monkeypatch.setattr(
        orchestration,
        "_run_inference",
        failed_inference,
    )
    monkeypatch.setattr(
        orchestration,
        "_run_promotion_evaluator",
        should_not_promote,
    )

    result = _run(tmp_path, release_root)

    assert promotion_calls == []
    assert result["status"] == "passed_rule_only"
    assert result["failed_stage"] == "inference"
    assert result["inference_status"] == "failed"
    assert result["promotion_status"] == "not_run"
    assert result["production_blend_alpha_bp"] == 0
    assert result["formal_oos_allowed"] is False
    assert result["broker_order_allowed"] is False
    assert result["broker_execution"] is False
    assert result["shadow_observation_recorded"] is False
    assert result["shadow_day_credit_allowed"] is False
    sidecar_root = (
        tmp_path
        / "output"
        / "scheduled"
        / "ml_allocation_copilot"
        / "sidecar"
    )
    assert not sidecar_root.exists()


def test_shadow_collector_failure_rolls_back_to_rule_and_skips_promotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_root = _write_release(tmp_path / "release")
    promotion_calls: list[str] = []

    def fake_input(**kwargs: Any) -> dict[str, object]:
        Path(kwargs["input_output"]).parent.mkdir(parents=True, exist_ok=True)
        Path(kwargs["input_output"]).write_bytes(b"input")
        Path(kwargs["audit_output"]).write_text("{}", encoding="utf-8")
        return _post_freeze_result()

    def fake_inference(**kwargs: Any) -> dict[str, object]:
        Path(kwargs["proposal_output"]).write_text("{}", encoding="utf-8")
        Path(kwargs["audit_output"]).write_text("{}", encoding="utf-8")
        return _inference_result()

    def failed_shadow(**_kwargs: Any) -> dict[str, object]:
        raise RuntimeError("controlled shadow sidecar failure")

    def should_not_promote(**_kwargs: Any) -> dict[str, object]:
        promotion_calls.append("promotion")
        return _promotion_result(tmp_path / "output")

    monkeypatch.setattr(
        orchestration,
        "_build_raw_publication",
        lambda **_kwargs: _raw_publication(tmp_path),
    )
    monkeypatch.setattr(
        orchestration,
        "_build_post_freeze_input",
        fake_input,
    )
    monkeypatch.setattr(
        orchestration,
        "_calculate_inference_universe_hash",
        lambda _path: f"sha256:{'e' * 64}",
    )
    monkeypatch.setattr(orchestration, "_run_inference", fake_inference)
    monkeypatch.setattr(
        orchestration,
        "_run_shadow_evidence_collector",
        failed_shadow,
    )
    monkeypatch.setattr(
        orchestration,
        "_run_promotion_evaluator",
        should_not_promote,
    )

    result = _run(tmp_path, release_root)

    assert promotion_calls == []
    assert result["status"] == "passed_rule_only"
    assert result["failed_stage"] == "shadow_evidence"
    assert result["shadow_evidence_status"] == "failed"
    assert result["shadow_observation_recorded"] is False
    assert result["shadow_day_credit_allowed"] is False
    assert result["production_blend_alpha_bp"] == 0
    assert result["formal_oos_allowed"] is False
    assert result["broker_order_allowed"] is False
