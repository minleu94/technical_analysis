from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

from data_module.formal_controlled_handoff import (
    FORMAL_CONTROLLED_HANDOFF_SCHEMA_VERSION,
    _validate_identity_entries,
    build_formal_controlled_handoff_plan,
)
from data_module.prospective_activation_environment import FORMAL_PATH_ENV_NAMES
from data_module.prospective_formal_clock import file_sha256, payload_hash


def test_split_daily_rule_lineage_keeps_fixed_common_identity_gate(
    tmp_path: Path,
) -> None:
    common_clock_id = "clock:prospective:20260909:planned-v1"
    common_clock_hash = "sha256:" + "1" * 64
    common_policy_hash = "sha256:" + "2" * 64
    common_universe_hash = "sha256:" + "3" * 64
    paths = {
        name: tmp_path / f"{index}.json"
        for index, name in enumerate(FORMAL_PATH_ENV_NAMES)
    }
    for path in paths.values():
        path.write_text("source", encoding="utf-8")
    projections = {
        name: {
            "path_hash": payload_hash(
                {"env_name": name, "path": str(path.resolve())}
            ),
            "file_hash": file_sha256(path),
        }
        for name, path in paths.items()
    }
    entries = {
        name: {
            **projections[name],
            "clock_id": common_clock_id,
            "clock_manifest_hash": common_clock_hash,
            "clock_scope": "cumulative_portfolio_state",
            "policy_hash": common_policy_hash,
            "universe_hash": common_universe_hash,
        }
        for name in paths
    }
    clock_projection = {
        "clock_id": common_clock_id,
        "clock_manifest_hash": common_clock_hash,
        "policy_hash": common_policy_hash,
        "universe_hash": common_universe_hash,
        "activation_trading_day": "2026-09-09",
    }
    daily_lineage = {
        "clock_id": "clock:prospective:20260909:daily-rule-v2",
        "clock_manifest_hash": "sha256:" + "4" * 64,
        "activation_trading_day": "2026-09-09",
        "universe_hash": "sha256:" + "5" * 64,
        "source_window_hash": "sha256:" + "6" * 64,
    }

    assert _validate_identity_entries(
        entries,
        path_projection=projections,
        clock_projection=clock_projection,
        identity_payload={"daily_rule_lineage": daily_lineage},
    ) == []

    entries[FORMAL_PATH_ENV_NAMES[1]]["universe_hash"] = "sha256:" + "7" * 64
    blockers = _validate_identity_entries(
        entries,
        path_projection=projections,
        clock_projection=clock_projection,
        identity_payload={"daily_rule_lineage": daily_lineage},
    )
    assert f"{FORMAL_PATH_ENV_NAMES[1]}:identity_universe_hash_mismatch" in blockers

    entries[FORMAL_PATH_ENV_NAMES[1]]["universe_hash"] = common_universe_hash
    daily_lineage["activation_trading_day"] = "2026-09-08"
    blockers = _validate_identity_entries(
        entries,
        path_projection=projections,
        clock_projection=clock_projection,
        identity_payload={"daily_rule_lineage": daily_lineage},
    )
    assert "daily_rule_lineage_activation_precedes_portfolio" in blockers


def test_handoff_plan_attests_process_source_without_auto_discovery(
    tmp_path: Path,
) -> None:
    environment = {
        FORMAL_PATH_ENV_NAMES[0]: str(tmp_path / "old" / "ledger.json"),
        FORMAL_PATH_ENV_NAMES[1]: str(tmp_path / "old" / "rule.json"),
        FORMAL_PATH_ENV_NAMES[2]: str(tmp_path / "old" / "sector.json"),
        "RULE_CHAMPION_CONTROLLED_STORE_ID": "test-store",
        "RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY": "test-secret",
    }
    plan = build_formal_controlled_handoff_plan(
        market_db=tmp_path / "market.db",
        training_as_of="2026-09-08T09:29:59+08:00",
        output_root=tmp_path,
        development_output_root=tmp_path,
        now=datetime(2026, 9, 8, 1, 30, tzinfo=timezone.utc),
        environment=environment,
        platform_name="posix",
    )

    assert plan["schema_version"] == FORMAL_CONTROLLED_HANDOFF_SCHEMA_VERSION
    assert plan["status"] == "blocked"
    proposed = plan["proposed_controlled_configuration"]
    assert isinstance(proposed, dict)
    assert proposed["blockers"] == [
        "proposed_clock_manifest_not_supplied",
        "proposed_identity_manifest_not_supplied",
        "proposed_paths_not_supplied",
    ]
    attestation = plan["runtime_attestation"]
    assert isinstance(attestation, dict)
    formal_paths = attestation["formal_paths"]
    assert isinstance(formal_paths, dict)
    for name in FORMAL_PATH_ENV_NAMES:
        source = formal_paths[name]
        assert source["effective_source"] == "process_environment"
        assert source["process_environment_configured"] is True
        assert source["process_environment_path_matches_effective"] is True
        assert source["windows_registry_configured"] is False
    safety = plan["safety"]
    assert isinstance(safety, dict)
    assert safety["writes_windows_environment"] is False
    assert safety["secret_values_emitted"] is False


def test_complete_proposed_bundle_can_replace_stale_current_configuration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    old_paths = {
        FORMAL_PATH_ENV_NAMES[0]: str(tmp_path / "old-ledger.json"),
        FORMAL_PATH_ENV_NAMES[1]: str(tmp_path / "old-rule.json"),
        FORMAL_PATH_ENV_NAMES[2]: str(tmp_path / "old-sector.json"),
    }
    proposed_paths = {
        name: tmp_path / f"proposed-{index}.json"
        for index, name in enumerate(FORMAL_PATH_ENV_NAMES)
    }
    for path in proposed_paths.values():
        path.write_text("{}", encoding="utf-8")
    clock_path = tmp_path / "clock.json"
    clock_path.write_text("clock", encoding="utf-8")
    clock_id = "clock:prospective:20260908:test"
    clock_hash = "sha256:" + "1" * 64
    identity_entries = {
        name: {
            "path_hash": payload_hash(
                {"env_name": name, "path": str(path.resolve())}
            ),
            "file_hash": file_sha256(path),
            "clock_id": clock_id,
            "clock_manifest_hash": clock_hash,
        }
        for name, path in proposed_paths.items()
    }
    identity_path = tmp_path / "identity.json"
    identity_path.write_text(
        json.dumps({"entries": identity_entries}),
        encoding="utf-8",
    )

    def fake_readback(paths, *, training_as_of):
        del training_as_of
        is_proposed = all(
            path == proposed_paths[name]
            for name, path in (
                (FORMAL_PATH_ENV_NAMES[0], paths.formal_ledger_path),
                (FORMAL_PATH_ENV_NAMES[1], paths.formal_rule_history_path),
                (FORMAL_PATH_ENV_NAMES[2], paths.formal_sector_path),
            )
        )
        if not is_proposed:
            return (
                {
                    name: {
                        "input": name,
                        "formal_ready": False,
                        "formal_consumer_compatible": False,
                        "candidate_only": True,
                    }
                    for name in (
                        "causal_non_cash_portfolio_ledger",
                        "formal_rule_champion_snapshot_history",
                        "pit_sector_membership",
                    )
                },
                ["stale_current_path_missing"],
            )
        return (
            {
                name: {
                    "input": name,
                    "formal_ready": True,
                    "formal_consumer_compatible": True,
                    "candidate_only": False,
                }
                for name in (
                    "causal_non_cash_portfolio_ledger",
                    "formal_rule_champion_snapshot_history",
                    "pit_sector_membership",
                )
            },
            [],
        )

    monkeypatch.setattr(
        "data_module.formal_controlled_handoff._readback_explicit_formal_sources",
        fake_readback,
    )
    monkeypatch.setattr(
        "data_module.formal_controlled_handoff.load_clock_manifest_for_capture",
        lambda path, *, now: SimpleNamespace(
            clock_id=clock_id,
            manifest_hash=clock_hash,
            activation_trading_day=datetime(2026, 9, 8).date(),
        ),
    )
    plan = build_formal_controlled_handoff_plan(
        market_db=tmp_path / "market.db",
        training_as_of="2026-09-08T09:29:59+08:00",
        output_root=tmp_path,
        development_output_root=tmp_path,
        now=datetime(2026, 9, 8, 1, 30, tzinfo=timezone.utc),
        environment={
            **old_paths,
            "RULE_CHAMPION_CONTROLLED_STORE_ID": "test-store",
            "RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY": "test-secret",
        },
        platform_name="posix",
        proposed_paths=proposed_paths,
        proposed_clock_manifest=clock_path,
        proposed_identity_manifest=identity_path,
    )

    assert plan["status"] == "ready_for_root_review"
    current = plan["current_controlled_configuration"]
    assert current["formal_ready_count"] == 0
    proposed = plan["proposed_controlled_configuration"]
    assert proposed["blockers"] == []


def test_proposed_consumer_failure_keeps_handoff_blocked(
    tmp_path: Path,
    monkeypatch,
) -> None:
    old_paths = {
        FORMAL_PATH_ENV_NAMES[0]: str(tmp_path / "old-ledger.json"),
        FORMAL_PATH_ENV_NAMES[1]: str(tmp_path / "old-rule.json"),
        FORMAL_PATH_ENV_NAMES[2]: str(tmp_path / "old-sector.json"),
    }
    proposed_paths = {
        name: tmp_path / f"proposed-{index}.json"
        for index, name in enumerate(FORMAL_PATH_ENV_NAMES)
    }
    for path in proposed_paths.values():
        path.write_text("{}", encoding="utf-8")
    clock_path = tmp_path / "clock.json"
    clock_path.write_text("clock", encoding="utf-8")
    clock_id = "clock:prospective:20260908:test"
    clock_hash = "sha256:" + "2" * 64
    identity_entries = {
        name: {
            "path_hash": payload_hash(
                {"env_name": name, "path": str(path.resolve())}
            ),
            "file_hash": file_sha256(path),
            "clock_id": clock_id,
            "clock_manifest_hash": clock_hash,
        }
        for name, path in proposed_paths.items()
    }
    identity_path = tmp_path / "identity.json"
    identity_path.write_text(
        json.dumps({"entries": identity_entries}),
        encoding="utf-8",
    )

    def fake_readback(paths, *, training_as_of):
        del training_as_of
        proposed = paths.formal_ledger_path == proposed_paths[FORMAL_PATH_ENV_NAMES[0]]
        if proposed:
            return (
                {
                    "causal_non_cash_portfolio_ledger": {
                        "formal_ready": True,
                        "formal_consumer_compatible": True,
                    },
                    "formal_rule_champion_snapshot_history": {
                        "formal_ready": False,
                        "formal_consumer_compatible": False,
                    },
                    "pit_sector_membership": {
                        "formal_ready": True,
                        "formal_consumer_compatible": True,
                    },
                },
                ["formal_rule_history_consumer_rejected:receipt_missing"],
            )
        return {}, ["stale_current_path_missing"]

    monkeypatch.setattr(
        "data_module.formal_controlled_handoff._readback_explicit_formal_sources",
        fake_readback,
    )
    monkeypatch.setattr(
        "data_module.formal_controlled_handoff.load_clock_manifest_for_capture",
        lambda path, *, now: SimpleNamespace(
            clock_id=clock_id,
            manifest_hash=clock_hash,
            activation_trading_day=datetime(2026, 9, 8).date(),
        ),
    )
    plan = build_formal_controlled_handoff_plan(
        market_db=tmp_path / "market.db",
        training_as_of="2026-09-08T09:29:59+08:00",
        output_root=tmp_path,
        development_output_root=tmp_path,
        now=datetime(2026, 9, 8, 1, 30, tzinfo=timezone.utc),
        environment={
            **old_paths,
            "RULE_CHAMPION_CONTROLLED_STORE_ID": "test-store",
            "RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY": "test-secret",
        },
        platform_name="posix",
        proposed_paths=proposed_paths,
        proposed_clock_manifest=clock_path,
        proposed_identity_manifest=identity_path,
    )

    assert plan["status"] == "blocked"
    proposed = plan["proposed_controlled_configuration"]
    assert "formal_rule_history_consumer_rejected:receipt_missing" in proposed[
        "blockers"
    ]
    assert "formal_rule_champion_snapshot_history:proposed_consumer_not_formal_ready" in proposed[
        "blockers"
    ]
