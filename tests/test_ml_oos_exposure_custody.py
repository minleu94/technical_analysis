from __future__ import annotations

import pytest

from ml_module.oos_exposure_custody import (
    AuditEvidenceMetadata,
    OOSExposureCustodyAuditor,
    OOSExposureCustodyRequest,
    SignedCustodyDeclaration,
)


def _metadata(evidence_id: str, access_state: str = "unopened") -> AuditEvidenceMetadata:
    return AuditEvidenceMetadata(
        evidence_id=evidence_id,
        sha256="a" * 64,
        recorded_at="2026-07-13T00:00:00Z",
        access_state=access_state,
    )


def _declaration() -> SignedCustodyDeclaration:
    return SignedCustodyDeclaration(
        declaration_id="declaration-001",
        reviewer_identity="named-reviewer",
        signed_at="2026-07-13T00:00:00Z",
        declares_no_design_influence=True,
    )


def _request(**overrides: object) -> OOSExposureCustodyRequest:
    values: dict[str, object] = {
        "generation_manifest": _metadata("generation-manifest"),
        "access_inventory": _metadata("access-inventory"),
        "signed_declaration": _declaration(),
        "influence_dimensions": (),
    }
    values.update(overrides)
    return OOSExposureCustodyRequest(**values)  # type: ignore[arg-type]


def test_missing_signed_declaration_precedes_influence_classification() -> None:
    report = OOSExposureCustodyAuditor().audit(
        _request(signed_declaration=None, influence_dimensions=("threshold",))
    )

    assert report.status == "indeterminate"
    assert report.blockers == ("signed_declaration_missing",)
    assert report.influence_dimensions == ("threshold",)
    assert report.formal_oos_allowed is False
    assert report.production_blend_alpha_bp == 0


def test_missing_signed_declaration_is_indeterminate() -> None:
    report = OOSExposureCustodyAuditor().audit(_request(signed_declaration=None))

    assert report.status == "indeterminate"
    assert report.blockers == ("signed_declaration_missing",)


def test_missing_machine_evidence_is_indeterminate() -> None:
    report = OOSExposureCustodyAuditor().audit(
        _request(generation_manifest=None, influence_dimensions=("threshold",))
    )

    assert report.status == "indeterminate"
    assert report.blockers == ("generation_manifest_missing",)
    assert report.influence_dimensions == ("threshold",)


def test_exposure_with_named_no_influence_declaration_is_retrospective_only() -> None:
    report = OOSExposureCustodyAuditor().audit(
        _request(access_inventory=_metadata("access-inventory", "exposed"))
    )

    assert report.status == "exposed_no_design_influence_declared"
    assert report.retrospective_only is True
    assert report.formal_oos_allowed is False


def test_complete_unopened_evidence_is_only_a_candidate_for_later_verification() -> None:
    report = OOSExposureCustodyAuditor().audit(_request())

    assert report.status == "custody_verified_unopened"
    assert report.formal_oos_allowed is False
    assert report.production_blend_alpha_bp == 0
    assert report.candidate_for_later_formal_verification is True


def test_external_construction_cannot_unlock_formal_oos_or_production_alpha() -> None:
    report = OOSExposureCustodyAuditor().audit(_request())
    public_values = report.to_dict()

    with pytest.raises(TypeError):
        type(report)(**{**public_values, "formal_oos_allowed": True})
    with pytest.raises(TypeError):
        type(report)(**{**public_values, "production_blend_alpha_bp": 1})


def test_canonical_json_and_hash_are_deterministic_and_contain_no_payload() -> None:
    auditor = OOSExposureCustodyAuditor()
    first = auditor.audit(_request())
    second = auditor.audit(_request())

    assert first.canonical_json() == second.canonical_json()
    assert first.canonical_sha256() == second.canonical_sha256()
    assert "payload" not in first.canonical_json().lower()
