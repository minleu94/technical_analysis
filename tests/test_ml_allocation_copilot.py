from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

from ml_module.allocation_validation import (
    ALPHA_LANES,
    AllocationFoldEvidence,
    AllocationPromotionEvidence,
    AllocationPromotionEvaluator,
    AlphaLaneEvidence,
)
from ml_promotion_test_support import (
    TRUSTED_CUSTODY_ID,
    TRUSTED_ISSUER_ID,
    TRUSTED_ISSUER_KEY,
    build_promotion_test_custody,
)
from runtime.promotion_authority_secret_store import (
    PromotionAuthoritySecretStore,
)
from scripts.run_ml_allocation_copilot import (
    _parse_decision_at,
    _promotion_trust_configuration,
    run,
)


HASH_A = "sha256:" + ("a" * 64)
HASH_B = "sha256:" + ("b" * 64)
DECISION_AT = "2026-07-29T08:30:00+08:00"


def test_cli_help_survives_windows_cp1252_console() -> None:
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "cp1252"
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_ml_allocation_copilot.py"
    )

    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        check=False,
        capture_output=True,
        env=environment,
    )

    assert completed.returncode == 0
    assert "Production Co-pilot".encode("utf-8") in completed.stdout


class _OpenCalendar:
    def is_official_trading_day(self, _target_date):
        return True, "test_official_schedule_open"


class _ClosedCalendar:
    def is_official_trading_day(self, _target_date):
        return False, "twse_holiday_schedule_closed"


class _UnknownCalendar:
    def is_official_trading_day(self, _target_date):
        return None, "twse_holiday_schedule_unavailable"


def _lane(alpha_bp: int) -> AlphaLaneEvidence:
    folds = tuple(
        AllocationFoldEvidence(
            fold_id=f"fold-{index}",
            after_cost_excess_vs_rule_bp=10,
        )
        for index in range(1, 5)
    )
    return AlphaLaneEvidence(
        alpha_bp=alpha_bp,
        pit_violation_count=0,
        constraint_violation_count=0,
        replay_hash_pairs=((HASH_A, HASH_A),),
        folds=folds,
        bootstrap_lower_bound_bp=0,
        calibration_ece_bp=100,
        calibrated_brier_bp=900,
        uncalibrated_brier_bp=1000,
        psi_bp=100,
        core_coverage_bp=9600,
        enriched_coverage_bp=9100,
        feasible_fill_coverage_bp=9600,
        mdd_worsening_vs_rule_bp=0,
        cvar_worsening_vs_rule_bp=0,
        weekly_turnover_bp=1000,
        turnover_increment_vs_rule_bp=100,
        shadow_observed_days=20,
    )


def _evidence() -> AllocationPromotionEvidence:
    return AllocationPromotionEvidence(
        experiment_id="release-v4-prod",
        model_id="allocation-model-v1",
        dataset_id="frozen-v4-dataset",
        model_artifact_hash=HASH_A,
        dataset_identity_hash=HASH_B,
        dataset_manifest_file_hash=HASH_A,
        oof_bundle_hash=HASH_A,
        shadow_evidence_hash=HASH_B,
        lanes=tuple(_lane(alpha_bp) for alpha_bp in ALPHA_LANES),
    )


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_consumer_loads_dpapi_authority_trust_without_plaintext_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_root = tmp_path / "output"
    secret_path = (
        output_root
        / "release_v4"
        / "ml_promotion_authority"
        / "authority_secret.dpapi.json"
    )
    secret = PromotionAuthoritySecretStore(secret_path).load_or_create()
    monkeypatch.delenv("BALDR_PROMOTION_TRUSTED_ISSUER_KEYS_JSON", raising=False)
    monkeypatch.delenv("BALDR_PROMOTION_CUSTODY_ROOTS", raising=False)
    monkeypatch.delenv("BALDR_PROMOTION_CUSTODY_ID", raising=False)
    monkeypatch.delenv("BALDR_PROMOTION_AUTHORITY_SECRET_FILE", raising=False)

    keys, roots, custody_id = _promotion_trust_configuration(
        output_root=output_root
    )

    assert keys == {secret.issuer_id: secret.signing_key}
    assert roots == ((output_root / "release_v4").resolve(),)
    assert custody_id == secret.custody_id


def test_missing_evidence_writes_four_unevaluated_lanes_and_alpha_zero(
    tmp_path: Path,
) -> None:
    decision_at = _parse_decision_at(DECISION_AT)

    first = run(
        output_root=tmp_path,
        decision_at=decision_at,
        evidence_path=None,
        authorization_path=None,
        calendar=_OpenCalendar(),
    )
    second = run(
        output_root=tmp_path,
        decision_at=decision_at,
        evidence_path=None,
        authorization_path=None,
        calendar=_OpenCalendar(),
    )

    assert first == second
    assert first["status"] == "passed_rule_only"
    assert first["operation_mode"] == "rule_only"
    assert first["selected_alpha_bp"] == 0
    assert first["formal_oos_allowed"] is False
    assert [row["alpha_bp"] for row in first["alpha_lanes"]] == list(
        ALPHA_LANES
    )
    assert all(row["evaluated"] is False for row in first["alpha_lanes"])
    assert all(row["passed"] is False for row in first["alpha_lanes"])
    assert len(
        list(
            (
                tmp_path
                / "scheduled"
                / "ml_allocation_copilot"
                / "sidecar"
            ).glob("*.json")
        )
    ) == 1
    assert Path(str(first["artifact_path"])).is_file()
    assert Path(str(first["sidecar_path"])).is_file()


def test_passing_evidence_without_authorization_stays_alpha_zero(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "evidence.json"
    evidence = _evidence()
    _write_json(evidence_path, evidence.canonical_payload())

    result = run(
        output_root=tmp_path / "output",
        decision_at=_parse_decision_at(DECISION_AT),
        evidence_path=evidence_path,
        authorization_path=None,
        calendar=_OpenCalendar(),
    )

    assert result["selected_alpha_bp"] == 0
    assert result["formal_oos_allowed"] is False
    assert result["operation_mode"] == "rule_only"
    assert all(row["evaluated"] is True for row in result["alpha_lanes"])
    assert "promotion_authorization_artifact_required" in result[
        "failed_reasons"
    ]


def test_matching_evidence_and_authorization_select_smallest_passing_lane(
    tmp_path: Path,
) -> None:
    evaluator = AllocationPromotionEvaluator()
    custody = build_promotion_test_custody(
        tmp_path / "custody",
        evidence=_evidence(),
        evaluator=evaluator,
        authorized_alpha_bp=2000,
    )

    result = run(
        output_root=tmp_path / "output",
        decision_at=_parse_decision_at(DECISION_AT),
        evidence_path=custody.evidence_path,
        authorization_path=custody.authorization_path,
        calendar=_OpenCalendar(),
        registry_revision_path=custody.registry_revision_path,
        model_artifact_path=custody.model_artifact_path,
        dataset_manifest_path=custody.dataset_manifest_path,
        oof_bundle_path=custody.oof_bundle_path,
        shadow_evidence_path=custody.shadow_evidence_path,
        trusted_issuer_keys={TRUSTED_ISSUER_ID: TRUSTED_ISSUER_KEY},
        trusted_custody_roots=(custody.root,),
        trusted_custody_id=TRUSTED_CUSTODY_ID,
    )

    assert result["selected_alpha_bp"] == 2000
    assert result["formal_oos_allowed"] is True
    assert result["operation_mode"] == "ml_blend_authorized"
    assert result["failed_reasons"] == []


def test_scheduler_reverifies_self_signed_and_future_authorization(
    tmp_path: Path,
) -> None:
    evaluator = AllocationPromotionEvaluator()
    cases = (
        (
            "untrusted-issuer",
            {
                "issuer_id": "attacker",
                "signing_key": bytes.fromhex("24" * 32),
            },
            "promotion_authorization_issuer_untrusted",
        ),
        (
            "self-signed",
            {
                "signing_key": bytes.fromhex("42" * 32),
            },
            "promotion_authorization_signature_invalid",
        ),
        (
            "future",
            {
                "issued_at": "2099-01-01T08:00:00+08:00",
            },
            "promotion_authorization_issued_in_future",
        ),
    )
    for case_name, overrides, expected_blocker in cases:
        custody = build_promotion_test_custody(
            tmp_path / case_name,
            evidence=_evidence(),
            evaluator=evaluator,
            authorized_alpha_bp=2000,
            **overrides,  # type: ignore[arg-type]
        )
        result = run(
            output_root=tmp_path / f"output-{case_name}",
            decision_at=_parse_decision_at(DECISION_AT),
            evidence_path=custody.evidence_path,
            authorization_path=custody.authorization_path,
            calendar=_OpenCalendar(),
            registry_revision_path=custody.registry_revision_path,
            model_artifact_path=custody.model_artifact_path,
            dataset_manifest_path=custody.dataset_manifest_path,
            oof_bundle_path=custody.oof_bundle_path,
            shadow_evidence_path=custody.shadow_evidence_path,
            trusted_issuer_keys={TRUSTED_ISSUER_ID: TRUSTED_ISSUER_KEY},
            trusted_custody_roots=(custody.root,),
            trusted_custody_id=TRUSTED_CUSTODY_ID,
        )

        assert result["selected_alpha_bp"] == 0
        assert result["formal_oos_allowed"] is False
        assert expected_blocker in result["failed_reasons"]


def test_invalid_evidence_is_recorded_without_nonzero_alpha(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "invalid.json"
    evidence_path.write_text('{"lanes": "invalid"}\n', encoding="utf-8")

    result = run(
        output_root=tmp_path / "output",
        decision_at=_parse_decision_at(DECISION_AT),
        evidence_path=evidence_path,
        authorization_path=None,
        calendar=_OpenCalendar(),
    )

    assert result["status"] == "passed_rule_only"
    assert result["selected_alpha_bp"] == 0
    assert result["formal_oos_allowed"] is False
    assert result["failed_reasons"] == [
        "promotion_evidence_invalid:TypeError"
    ]


def test_decision_timestamp_must_be_taipei_0830() -> None:
    assert (
        _parse_decision_at("2026-07-29T00:30:00Z").isoformat(
            timespec="seconds"
        )
        == DECISION_AT
    )

    try:
        _parse_decision_at("2026-07-29T09:00:00+08:00")
    except ValueError as exc:
        assert "08:30" in str(exc)
    else:
        raise AssertionError("non-08:30 decision_at must fail")


def test_default_decision_timestamp_is_the_next_future_taipei_cutoff() -> None:
    before_cutoff = datetime.fromisoformat("2026-07-29T07:00:00+08:00")
    after_cutoff = datetime.fromisoformat("2026-07-29T20:00:00+08:00")

    assert _parse_decision_at(None, now=before_cutoff).isoformat() == (
        "2026-07-29T08:30:00+08:00"
    )
    assert _parse_decision_at(None, now=after_cutoff).isoformat() == (
        "2026-07-30T08:30:00+08:00"
    )


def test_closed_day_writes_status_only_without_shadow_observation(
    tmp_path: Path,
) -> None:
    result = run(
        output_root=tmp_path,
        decision_at=_parse_decision_at(DECISION_AT),
        evidence_path=None,
        authorization_path=None,
        calendar=_ClosedCalendar(),
    )

    run_root = tmp_path / "scheduled" / "ml_allocation_copilot"
    assert result["status"] == "skipped_non_trading_day"
    assert result["trading_calendar_validated"] is True
    assert result["artifact_path"] is None
    assert result["sidecar_path"] is None
    assert not (run_root / "artifacts").exists()
    assert not (run_root / "sidecar").exists()


def test_unknown_calendar_fails_closed_without_shadow_observation(
    tmp_path: Path,
) -> None:
    result = run(
        output_root=tmp_path,
        decision_at=_parse_decision_at(DECISION_AT),
        evidence_path=None,
        authorization_path=None,
        calendar=_UnknownCalendar(),
    )

    assert result["status"] == "degraded_calendar_unknown"
    assert result["trading_calendar_validated"] is False
    assert result["operation_mode"] == "not_run"
    assert result["production_blend_alpha_bp"] == 0
    assert result["sidecar_path"] is None
