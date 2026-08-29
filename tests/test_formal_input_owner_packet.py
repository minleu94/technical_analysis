from __future__ import annotations

import json
from pathlib import Path

import pytest

from app_module.formal_input_owner_packet import (
    FORMAL_INPUT_OWNER_PACKET_SCHEMA_VERSION,
    build_formal_input_owner_packet,
    render_markdown,
    validate_output_path,
)
from scripts.build_formal_input_owner_packet import main


def _inventory(path: Path, *, formal_oos_allowed: bool = False) -> None:
    payload = {
        "schema_version": "ml-formal-input-candidate-inventory.v1",
        "candidate_root": str(path.parent / "candidates"),
        "manifest_count": 4,
        "skipped_count": 1,
        "truncated": True,
        "lane_counts": {"research_only": 2, "prospective_only": 2},
        "candidate_input_counts": {
            "causal_non_cash_portfolio_ledger": 2,
            "formal_rule_champion_snapshot_history": 0,
            "pit_sector_membership": 1,
        },
        "formal_ready_input_count": 0,
        "formal_oos_allowed": formal_oos_allowed,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
        "promotion_eligible": False,
        "candidates": [
            {
                "path": "research/causal/manifest.json",
                "manifest_sha256": "sha256:" + "a" * 64,
                "lane": "research_only",
                "reason": "research_artifact_cannot_be_promoted_to_formal",
                "candidate_input": "causal_non_cash_portfolio_ledger",
                "formal_consumer_compatible": False,
                "formal_oos_allowed": False,
                "safe_projection": {"schema_version": "research-causal-baseline-ledger.v1"},
            },
            {
                "path": "prospective/causal/manifest.json",
                "manifest_sha256": "sha256:" + "b" * 64,
                "lane": "prospective_only",
                "reason": "prospective_artifact_is_diagnostic_only",
                "candidate_input": "causal_non_cash_portfolio_ledger",
                "formal_consumer_compatible": False,
                "formal_oos_allowed": False,
                "safe_projection": {"schema_version": "prospective-formal.v1"},
            },
            {
                "path": "prospective/sector/manifest.json",
                "manifest_sha256": "sha256:" + "c" * 64,
                "lane": "prospective_only",
                "reason": "prospective_artifact_is_diagnostic_only",
                "candidate_input": "pit_sector_membership",
                "formal_consumer_compatible": False,
                "formal_oos_allowed": False,
                "safe_projection": {"schema_version": "pit-sector-membership-sidecar-v1"},
            },
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_packet_is_bounded_and_non_authorizing(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    (tmp_path / "candidates").mkdir()
    _inventory(inventory_path)
    before = inventory_path.read_bytes()

    packet = build_formal_input_owner_packet(inventory_path)

    assert packet["schema_version"] == FORMAL_INPUT_OWNER_PACKET_SCHEMA_VERSION
    assert packet["packet_status"] == "needs_named_owner_reviewer"
    assert packet["formal_ready_input_count"] == 0
    assert packet["formal_input_count"] == 3
    assert packet["formal_oos_allowed"] is False
    assert packet["candidate_only"] is True
    assert packet["write_performed"] is False
    records = {item["input"]: item for item in packet["review_records"]}
    assert records["causal_non_cash_portfolio_ledger"]["candidate_count_in_packet"] == 2
    assert records["formal_rule_champion_snapshot_history"]["candidate_count_in_packet"] == 0
    assert records["pit_sector_membership"]["owner_decision"] == "pending"
    assert inventory_path.read_bytes() == before
    assert "Formal OOS allowed: `false`" in render_markdown(packet)


def test_named_roles_and_candidate_limit_only_change_handoff_fields(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    (tmp_path / "candidates").mkdir()
    _inventory(inventory_path)

    packet = build_formal_input_owner_packet(
        inventory_path,
        owner_role="ml_governance_owner",
        reviewer_role="independent_reviewer",
        max_candidates_per_input=1,
    )

    assert packet["packet_status"] == "ready_for_owner_review"
    assert packet["owner_role"] == "ml_governance_owner"
    assert packet["reviewer_role"] == "independent_reviewer"
    causal = next(
        item for item in packet["review_records"] if item["input"] == "causal_non_cash_portfolio_ledger"
    )
    assert causal["candidate_count_observed"] == 2
    assert causal["candidate_count_in_packet"] == 1
    assert causal["selected_candidate_path"] == ""
    assert causal["published_formal_path"] == ""


def test_packet_rejects_unsafe_inventory_and_output_inside_candidate_root(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    candidate_root = tmp_path / "candidates"
    candidate_root.mkdir()
    _inventory(inventory_path, formal_oos_allowed=True)

    with pytest.raises(ValueError, match="formal_oos_allowed"):
        build_formal_input_owner_packet(inventory_path)

    _inventory(inventory_path)
    with pytest.raises(ValueError, match="outside candidate_root"):
        validate_output_path(candidate_root / "packet.json", inventory_path=inventory_path)
    with pytest.raises(ValueError, match="overwrite"):
        validate_output_path(inventory_path, inventory_path=inventory_path)


def test_cli_writes_json_and_markdown_without_selecting_candidates(tmp_path: Path, capsys) -> None:
    inventory_path = tmp_path / "inventory.json"
    candidate_root = tmp_path / "candidates"
    candidate_root.mkdir()
    _inventory(inventory_path)
    output_json = tmp_path / "packet.json"
    output_md = tmp_path / "packet.md"

    assert main(
        [
            "--inventory-path",
            str(inventory_path),
            "--output-json",
            str(output_json),
            "--markdown-output",
            str(output_md),
            "--owner-role",
            "owner",
            "--reviewer-role",
            "reviewer",
            "--json-output",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["packet_status"] == "ready_for_owner_review"
    assert json.loads(output_json.read_text(encoding="utf-8"))["formal_oos_allowed"] is False
    assert "Required input review" in output_md.read_text(encoding="utf-8")
