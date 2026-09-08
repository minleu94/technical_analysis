from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

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
    assert packet["packet_status"] == "needs_input_evidence"
    assert packet["formal_ready_input_count"] == 0
    assert packet["owner_reviewer_required"] is False
    assert packet["human_review_required"] is False
    assert packet["evidence_required"] is True
    assert packet["formal_input_count"] == 3
    assert packet["formal_oos_allowed"] is False
    assert packet["candidate_only"] is True
    assert packet["write_performed"] is False
    records = {item["input"]: item for item in packet["review_records"]}
    assert records["causal_non_cash_portfolio_ledger"]["candidate_count_in_packet"] == 2
    assert records["formal_rule_champion_snapshot_history"]["candidate_count_in_packet"] == 0
    assert records["pit_sector_membership"]["owner_decision"] == "needs_input_evidence"
    assert records["pit_sector_membership"]["evidence_state"] == "missing"
    assert records["pit_sector_membership"]["machine_review_required"] is False
    assert inventory_path.read_bytes() == before
    assert "Formal OOS allowed: `false`" in render_markdown(packet)


def test_named_roles_are_metadata_and_cannot_change_evidence_state(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    (tmp_path / "candidates").mkdir()
    _inventory(inventory_path)

    packet = build_formal_input_owner_packet(
        inventory_path,
        owner_role="ml_governance_owner",
        reviewer_role="independent_reviewer",
        max_candidates_per_input=1,
    )

    assert packet["packet_status"] == "needs_input_evidence"
    assert packet["owner_role"] == "ml_governance_owner"
    assert packet["reviewer_role"] == "independent_reviewer"
    assert packet["owner_reviewer_required"] is False
    causal = next(
        item for item in packet["review_records"] if item["input"] == "causal_non_cash_portfolio_ledger"
    )
    assert causal["candidate_count_observed"] == 2
    assert causal["candidate_count_in_packet"] == 1
    assert causal["selected_candidate_path"] == ""
    assert causal["published_formal_path"] == ""


def test_formal_consumer_routing_can_machine_verify_without_named_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Routing keeps the state machine evidence-driven; real E2E follows below."""

    import app_module.formal_input_owner_packet as packet_module

    inventory_path = tmp_path / "inventory.json"
    (tmp_path / "candidates").mkdir()
    _inventory(inventory_path)
    ledger_path = tmp_path / "ledger" / "manifest.json"
    rule_path = tmp_path / "rule" / "manifest.json"
    sector_path = tmp_path / "sector" / "sidecar.json"
    for path in (ledger_path, rule_path, sector_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")

    monkeypatch.setattr(
        packet_module,
        "load_formal_portfolio_state_ledger",
        lambda _path: SimpleNamespace(
            decision_dates=("2026-07-31",),
            ledger_manifest_hash="sha256:" + "a" * 64,
            transition_chain_hash="sha256:" + "b" * 64,
            non_cash_state_day_count=1,
        ),
    )
    monkeypatch.setattr(
        packet_module,
        "load_verified_rule_champion_snapshot_history",
        lambda _path, *, training_as_of: SimpleNamespace(
            manifest_file_hash="sha256:" + "c" * 64,
            manifest_hash="sha256:" + "d" * 64,
            registered_store_id="controlled-store",
            decision_dates=("2026-07-31",),
            snapshots=(object(),),
        ),
    )
    monkeypatch.setattr(
        packet_module,
        "discover_valid_sector_membership",
        lambda **_: sector_path,
    )

    without_names = build_formal_input_owner_packet(
        inventory_path,
        formal_ledger_path=ledger_path,
        formal_rule_history_path=rule_path,
        formal_sector_path=sector_path,
        formal_training_as_of="2026-08-01T13:00:00+00:00",
    )
    with_names = build_formal_input_owner_packet(
        inventory_path,
        owner_role="owner",
        reviewer_role="reviewer",
        formal_ledger_path=ledger_path,
        formal_rule_history_path=rule_path,
        formal_sector_path=sector_path,
        formal_training_as_of="2026-08-01T13:00:00+00:00",
    )

    assert without_names["packet_status"] == "machine_verified"
    assert without_names["formal_ready_input_count"] == 3
    assert without_names["formal_consumer_compatible_count"] == 3
    assert without_names["owner_reviewer_required"] is False
    assert without_names["human_review_required"] is False
    assert without_names["evidence_required"] is False
    assert with_names["packet_status"] == without_names["packet_status"]
    for key in (
        "formal_ready_input_count",
        "machine_verified_input_count",
        "formal_consumer_compatible_count",
        "missing_input_count",
        "unknown_input_count",
        "invalid_input_count",
        "evidence_required",
    ):
        assert with_names[key] == without_names[key]
    assert all(
        record["owner_decision"] == "machine_verified"
        and record["formal_ready"] is True
        and record["machine_review_required"] is False
        for record in without_names["review_records"]
    )
    assert [
        (record["evidence_state"], record["owner_decision"])
        for record in without_names["review_records"]
    ] == [
        (record["evidence_state"], record["owner_decision"])
        for record in with_names["review_records"]
    ]
    assert [
        record["formal_consumer_evidence"]
        for record in without_names["review_records"]
    ] == [
        record["formal_consumer_evidence"]
        for record in with_names["review_records"]
    ]


def test_three_real_formal_artifacts_reach_machine_verified_3_of_3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the packet against the repository's actual three loaders."""

    from tests.test_continue_ml_direct_ooc_after_store import _write_sector_sidecar
    from tests.test_formal_portfolio_ledger import _build_ledger
    from tests.test_rule_champion_snapshot_service import (
        _TEST_KEY,
        _TEST_STORE_ID,
        _artifact,
        _build,
        _history_payload,
        _repository,
    )

    inventory_path = tmp_path / "inventory.json"
    (tmp_path / "candidates").mkdir()
    _inventory(inventory_path)
    ledger_path = _build_ledger(tmp_path / "ledger")

    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY", _TEST_KEY)
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_ID", _TEST_STORE_ID)

    artifact = _artifact()
    snapshot = _build(
        _repository(artifact),
        str(artifact["decision_snapshot_id"]),
    )
    rule_path = tmp_path / "rule" / "manifest.json"
    rule_path.parent.mkdir(parents=True)
    rule_path.write_text(
        json.dumps(_history_payload(snapshot), ensure_ascii=False),
        encoding="utf-8",
    )

    sector_path = tmp_path / "sector" / "sidecars" / "pit_sector_membership.json"
    _write_sector_sidecar(sector_path)

    packet = build_formal_input_owner_packet(
        inventory_path,
        formal_ledger_path=ledger_path,
        formal_rule_history_path=rule_path,
        formal_sector_path=sector_path,
        formal_training_as_of="2026-07-14T00:00:00+08:00",
    )

    assert packet["packet_status"] == "machine_verified"
    assert packet["formal_ready_input_count"] == 3
    assert packet["machine_verified_input_count"] == 3
    assert packet["owner_reviewer_required"] is False
    assert packet["evidence_required"] is False
    assert all(
        record["formal_consumer_evidence"]["state"] == "ready"
        and record["formal_consumer_evidence"]["formal_consumer_compatible"] is True
        for record in packet["review_records"]
    )

    before_rule_snapshot = build_formal_input_owner_packet(
        inventory_path,
        formal_ledger_path=ledger_path,
        formal_rule_history_path=rule_path,
        formal_sector_path=sector_path,
        # The signed snapshot is 09:00 Asia/Taipei; 08:59:59 must remain
        # invalid even though it is the same Taiwan calendar date.
        formal_training_as_of="2026-07-13T08:59:59+08:00",
    )
    rule_record = next(
        item
        for item in before_rule_snapshot["review_records"]
        if item["input"] == "formal_rule_champion_snapshot_history"
    )
    assert before_rule_snapshot["formal_ready_input_count"] == 2
    assert rule_record["evidence_state"] == "invalid"
    assert rule_record["owner_decision"] == "input_evidence_invalid"


def test_consumer_failure_is_invalid_evidence_even_with_role_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app_module.formal_input_owner_packet as packet_module

    inventory_path = tmp_path / "inventory.json"
    (tmp_path / "candidates").mkdir()
    _inventory(inventory_path)
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text("tampered", encoding="utf-8")

    def reject_hash(_path: Path) -> object:
        raise ValueError("formal portfolio ledger manifest hash mismatch")

    monkeypatch.setattr(packet_module, "load_formal_portfolio_state_ledger", reject_hash)
    packet = build_formal_input_owner_packet(
        inventory_path,
        owner_role="owner",
        reviewer_role="reviewer",
        formal_ledger_path=ledger_path,
        formal_training_as_of="2026-08-01T13:00:00+00:00",
    )
    ledger = next(
        item
        for item in packet["review_records"]
        if item["input"] == "causal_non_cash_portfolio_ledger"
    )
    assert packet["packet_status"] == "input_evidence_invalid"
    assert ledger["evidence_state"] == "invalid"
    assert ledger["owner_decision"] == "input_evidence_invalid"
    assert ledger["formal_ready"] is False
    assert packet["owner_reviewer_required"] is False


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
    assert payload["packet_status"] == "needs_input_evidence"
    assert json.loads(output_json.read_text(encoding="utf-8"))["formal_oos_allowed"] is False
    assert "Required input review" in output_md.read_text(encoding="utf-8")
