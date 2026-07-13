from pathlib import Path

import pytest

from app_module.engineering_gate_registry import EngineeringGateItem, EngineeringGateRegistry


def _item(revision: int = 1, status: str = "open") -> EngineeringGateItem:
    return EngineeringGateItem(
        item_id="p0:institutional-license",
        revision=revision,
        category="data_license",
        title="Review institutional-flow source terms",
        status=status,
        owner="data-owner",
        earliest_validation_date="2026-07-15",
        progress_bp=0 if status == "open" else 5000,
        required_artifacts=("license-review.md",),
        validation_commands=("python scripts/verify_p0_source_acceptance.py ...",),
        completion_rules=("owner records accepted/limited/rejected/deferred",),
        prohibited_actions=("enable production ingestion", "connect ScoringEngine"),
        notes="Awaiting owner review",
    )


def test_registry_appends_revisions_and_returns_latest(tmp_path: Path) -> None:
    registry = EngineeringGateRegistry(tmp_path / "control.sqlite")
    registry.append(_item())
    registry.append(_item(2, "in_progress"))

    assert registry.latest("p0:institutional-license") == _item(2, "in_progress")
    assert registry.history("p0:institutional-license") == (_item(), _item(2, "in_progress"))


def test_duplicate_revision_cannot_overwrite(tmp_path: Path) -> None:
    registry = EngineeringGateRegistry(tmp_path / "control.sqlite")
    registry.append(_item())
    with pytest.raises(ValueError, match="already exists"):
        registry.append(_item())


def test_registry_supports_all_required_gate_categories() -> None:
    categories = {
        "human_input",
        "human_approval",
        "waiting_for_time",
        "data_license",
        "evidence_maturity",
        "ml_revalidation",
    }
    for index, category in enumerate(sorted(categories), start=1):
        item = EngineeringGateItem(
            item_id=f"item-{index}",
            revision=1,
            category=category,
            title=category,
            status="open",
            owner="owner",
            earliest_validation_date="2026-07-15",
            progress_bp=0,
            required_artifacts=("artifact",),
            validation_commands=("command",),
            completion_rules=("rule",),
            prohibited_actions=("prohibited",),
        )
        assert item.category == category


def test_complete_gate_requires_full_progress_and_completion_evidence() -> None:
    with pytest.raises(ValueError, match="complete gate"):
        EngineeringGateItem(
            item_id="bad",
            revision=1,
            category="human_approval",
            title="bad",
            status="complete",
            owner="owner",
            earliest_validation_date="2026-07-15",
            progress_bp=5000,
            required_artifacts=("artifact",),
            validation_commands=("command",),
            completion_rules=("rule",),
            prohibited_actions=("prohibited",),
        )
