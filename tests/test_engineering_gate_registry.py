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
    with pytest.raises(ValueError, match="contiguous"):
        registry.append(_item())


def test_revision_cannot_skip_append_only_sequence(tmp_path: Path) -> None:
    registry = EngineeringGateRegistry(tmp_path / "control.sqlite")
    registry.append(_item())

    with pytest.raises(ValueError, match="expected=2:actual=3"):
        registry.append(_item(3, "in_progress"))


def test_registry_supports_all_required_gate_categories() -> None:
    categories = {
        "human_input",
        "human_approval",
        "waiting_for_time",
        "data_license",
        "evidence_maturity",
        "ml_revalidation",
        "automated_evidence",
        "policy_decision",
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


def test_registry_accepts_explicit_insufficient_evidence_status(tmp_path: Path) -> None:
    item = EngineeringGateItem(
        item_id="evidence:forward-maturity",
        revision=1,
        category="automated_evidence",
        title="Evaluate forward maturity",
        status="insufficient_evidence",
        owner="scheduler",
        earliest_validation_date="2026-07-29",
        progress_bp=0,
        required_artifacts=("maturity.json",),
        validation_commands=("python inspect.py",),
        completion_rules=("minimum matured outcomes",),
        prohibited_actions=("do not fabricate outcomes",),
    )
    registry = EngineeringGateRegistry(tmp_path / "control.sqlite")

    registry.append(item)

    assert registry.latest(item.item_id) == item


def test_append_many_is_atomic_when_any_revision_is_stale(tmp_path: Path) -> None:
    registry = EngineeringGateRegistry(tmp_path / "control.sqlite")
    registry.append(_item())
    second_item = EngineeringGateItem(
        **{
            **_item(2).to_dict(),
            "item_id": "paper:policy",
            "required_artifacts": ("license-review.md",),
            "validation_commands": ("python scripts/verify_p0_source_acceptance.py ...",),
            "completion_rules": ("owner records accepted/limited/rejected/deferred",),
            "prohibited_actions": ("enable production ingestion", "connect ScoringEngine"),
            "completion_evidence": (),
        }
    )

    with pytest.raises(ValueError, match="contiguous"):
        registry.append_many((_item(), second_item))

    assert registry.latest("paper:policy") is None


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
