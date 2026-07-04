from __future__ import annotations

import json
import subprocess
import sys

from data_module.corporate_action_policy import inspect_corporate_action_policy


def test_policy_forbids_hindsight_adjusted_prices_for_decisions():
    inspection = inspect_corporate_action_policy()
    forbidden = inspection.policy_by_id["full_hindsight_adjusted_price"]

    assert forbidden.allowed_for_decision_features is False
    assert "look_ahead_risk" in forbidden.warnings
    assert forbidden.requires_available_date is True


def test_policy_declares_candidate_table_without_migration():
    inspection = inspect_corporate_action_policy()
    payload = inspection.to_dict()

    assert payload["production_data_writes"] is False
    assert payload["table_candidate"]["table_name"] == "corporate_action_events"
    assert "available_date" in payload["table_candidate"]["required_columns"]
    assert payload["migration_created"] is False


def test_corporate_action_policy_cli_outputs_json():
    completed = subprocess.run(
        [sys.executable, "scripts/inspect_corporate_action_policy.py", "--json-output"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    payload = json.loads(completed.stdout)
    assert payload["schema_version"] == 1
    assert payload["default_decision_price_policy"] == "raw_close_price"
    assert payload["production_data_writes"] is False
