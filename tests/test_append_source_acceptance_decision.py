from __future__ import annotations

import copy
import json

import pytest

from data_module.p0_source_contract_registry import P0_SOURCE_IDS
from data_module.source_acceptance_decision_registry import (
    SourceAcceptanceDecisionRegistry,
    SourceAcceptanceDecisionRevision,
)
from scripts.append_source_acceptance_decision import (
    append_decision,
    inspect_decision_input,
    load_decision,
    main,
)
from scripts.inspect_p0_intake_readiness import build_p0_intake_template


def _complete_intake() -> dict[str, object]:
    payload = copy.deepcopy(build_p0_intake_template())
    dossiers = payload["dossiers"]
    assert isinstance(dossiers, list)
    for dossier in dossiers:
        assert isinstance(dossier, dict)
        dossier.update(
            {
                "source_owner_role": "data_owner",
                "license_owner_role": "legal_compliance",
                "license_status": "approved",
                "license_scope": "internal_research",
                "redistribution_policy": "internal_only",
                "publication_time_policy": "official_publication_timestamp_preserved",
                "available_date_policy": "available_date <= decision_date",
                "revision_policy": "append_only_revision_manifest",
                "pit_coverage_window": "2020-01-01..2026-08-27",
                "coverage_numerator": 100,
                "coverage_denominator": 100,
                "row_conservation_counts": {"raw": 100, "accepted": 100},
                "quarantine_policy": "quarantine_malformed_rows",
                "quality_thresholds": {"minimum_coverage_bp": 9500},
                "evidence_artifact_ids": [
                    "license:review-1",
                    "quality:review-1",
                    "pit:review-1",
                ],
                "reviewer_role": "reviewer",
                "decision_timestamp": "2026-08-27T12:00:00+08:00",
            }
        )
    return payload


def _decision(
    *,
    status: str = "deferred",
    source_id: str = P0_SOURCE_IDS[0],
    revision_id: str = "decision:source:r1",
) -> SourceAcceptanceDecisionRevision:
    applying = status in {"accepted", "limited"}
    return SourceAcceptanceDecisionRevision(
        source_id=source_id,
        decision_revision_id=revision_id,
        parent_revision_id=None,
        status=status,
        allowed_use_cases=("internal_research_shadow",) if applying else (),
        blockers=() if applying else ("owner_review_pending",),
        license_evidence_ids=("license:review-1",) if applying else (),
        quality_evidence_ids=("quality:review-1",) if applying else (),
        pit_evidence_ids=("pit:review-1",) if applying else (),
        owner_role="data_owner",
        reviewer_role="reviewer",
        decided_at="2026-08-27T12:00:00+08:00",
        rollback_reference="decision:disable-next",
    )


def _write_decision(path, revision: SourceAcceptanceDecisionRevision) -> None:
    path.write_text(
        json.dumps(revision.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def test_preview_does_not_initialize_registry(tmp_path) -> None:
    decision_path = tmp_path / "decision.json"
    registry_path = tmp_path / "registry.sqlite"
    _write_decision(decision_path, _decision())

    assert main(["--decision", str(decision_path)]) == 0
    assert not registry_path.exists()


def test_applying_decision_requires_owner_reviewed_intake_and_evidence_binding(tmp_path) -> None:
    limited = _decision(status="limited")
    with pytest.raises(ValueError, match="requires --intake"):
        inspect_decision_input(limited)

    incomplete_path = tmp_path / "incomplete.json"
    incomplete_path.write_text(
        json.dumps(build_p0_intake_template(), ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="not ready_for_owner_review"):
        inspect_decision_input(limited, intake_path=incomplete_path)

    intake = _complete_intake()
    dossier = intake["dossiers"][0]
    assert isinstance(dossier, dict)
    dossier["evidence_artifact_ids"] = ["license:review-1"]
    intake_path = tmp_path / "incomplete-evidence.json"
    intake_path.write_text(json.dumps(intake, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="not bound to intake dossier"):
        inspect_decision_input(limited, intake_path=intake_path)


def test_confirm_append_writes_only_after_explicit_confirmation_and_is_idempotent(tmp_path) -> None:
    decision = _decision(status="limited")
    decision_path = tmp_path / "decision.json"
    intake_path = tmp_path / "intake.json"
    registry_path = tmp_path / "registry.sqlite"
    output_path = tmp_path / "preview.json"
    _write_decision(decision_path, decision)
    intake_path.write_text(json.dumps(_complete_intake(), ensure_ascii=False), encoding="utf-8")

    assert main(
        [
            "--decision",
            str(decision_path),
            "--intake",
            str(intake_path),
            "--registry",
            str(registry_path),
            "--output",
            str(output_path),
        ]
    ) == 0
    preview = json.loads(output_path.read_text(encoding="utf-8"))
    assert preview["status"] == "preview"
    assert preview["registry_append_confirmed"] is False
    assert not registry_path.exists()

    appended = append_decision(decision, registry_path=registry_path, intake_path=intake_path)
    assert appended["status"] == "appended"
    assert appended["registry_append_confirmed"] is True
    assert appended["safety_flags"]["writes_allowed"] is True

    repeated = append_decision(decision, registry_path=registry_path, intake_path=intake_path)
    assert repeated["status"] == "already_present"
    registry = SourceAcceptanceDecisionRegistry(registry_path)
    assert registry.current(P0_SOURCE_IDS[0]).status == "limited"
    assert len(registry.list_revisions(P0_SOURCE_IDS[0])) == 1


def test_cli_confirm_requires_registry_and_invalid_decision_returns_two(tmp_path) -> None:
    decision_path = tmp_path / "accepted.json"
    _write_decision(decision_path, _decision(status="accepted", revision_id="decision:source:r2"))

    assert main(["--decision", str(decision_path), "--confirm-append"]) == 2
    assert main(["--decision", str(decision_path)]) == 2


def test_registry_under_data_root_is_blocked(monkeypatch, tmp_path) -> None:
    production_root = tmp_path / "production"
    monkeypatch.setenv("DATA_ROOT", str(production_root))
    with pytest.raises(ValueError, match="outside the production root"):
        append_decision(_decision(), registry_path=production_root / "registry.sqlite")
    assert not (production_root / "registry.sqlite").exists()


def test_load_decision_rejects_unknown_schema(tmp_path) -> None:
    path = tmp_path / "bad.json"
    payload = _decision().to_dict()
    payload["schema_version"] = "unknown.v1"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported decision schema"):
        load_decision(path)


def test_owner_review_deferred_decision_can_be_previewed_without_intake(tmp_path) -> None:
    path = tmp_path / "owner-review-deferred.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "source-acceptance-owner-review-decision.v1",
                "source_id": P0_SOURCE_IDS[0],
                "decision_revision_id": "decision:source:owner-review-deferred",
                "parent_revision_id": None,
                "status": "deferred",
                "owner_role": "owner",
                "reviewer_role": "reviewer",
                "decision_timestamp": "2026-08-27T12:00:00+08:00",
                "active_blockers": ["source_acceptance_not_authorized"],
                "rollback_reference": "owner-policy:disable",
                "formal_oos_allowed": False,
                "production_blend_alpha_bp": 0,
            }
        ),
        encoding="utf-8",
    )

    revision = load_decision(path)

    assert revision.status == "deferred"
    assert revision.blockers == ("source_acceptance_not_authorized",)
    assert main(["--decision", str(path)]) == 0
