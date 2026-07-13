from pathlib import Path

from app_module.gate_2_to_7_closeout_verifier import (
    CloseoutRequirement,
    Gate2To7CloseoutVerifier,
)


def test_verifier_distinguishes_engineering_complete_from_external_pending(tmp_path: Path) -> None:
    artifact = tmp_path / "module.py"
    artifact.write_text("pass\n", encoding="utf-8")
    verifier = Gate2To7CloseoutVerifier(
        tmp_path,
        requirements=(CloseoutRequirement("slice", "module.py", "feat: slice"),),
    )

    report = verifier.verify(
        commit_subjects=("feat: slice",),
        external_gate_statuses=("open", "waiting"),
    )

    assert report.engineering_package_status == "complete"
    assert report.external_validation_status == "pending"
    assert report.formal_product_closeout is False


def test_missing_artifact_or_commit_blocks_engineering_completion(tmp_path: Path) -> None:
    verifier = Gate2To7CloseoutVerifier(
        tmp_path,
        requirements=(CloseoutRequirement("slice", "missing.py", "feat: missing"),),
    )

    report = verifier.verify(commit_subjects=(), external_gate_statuses=())

    assert report.engineering_package_status == "incomplete"
    assert "missing_artifact:slice:missing.py" in report.blockers
    assert "missing_commit:slice:feat: missing" in report.blockers


def test_default_requirements_cover_all_engineering_packages() -> None:
    from app_module.gate_2_to_7_closeout_verifier import DEFAULT_REQUIREMENTS

    package_ids = {item.package_id for item in DEFAULT_REQUIREMENTS}
    assert {"evidence_v3", "p0_sources", "paper_portfolio", "position_health", "ml_shadow", "control_center"} <= package_ids


def test_rejected_external_gate_remains_explicit() -> None:
    verifier = Gate2To7CloseoutVerifier(Path("."), requirements=())
    report = verifier.verify(commit_subjects=(), external_gate_statuses=("rejected",))

    assert report.engineering_package_status == "complete"
    assert report.external_validation_status == "rejected_or_blocked"
    assert report.formal_product_closeout is False
