from __future__ import annotations

import json
import subprocess
import sys

from data_module.data_source_capability_registry import (
    build_default_data_source_capability_registry,
    inspect_data_source_capabilities,
)


def test_registry_contains_v1_5_p0_sources():
    registry = build_default_data_source_capability_registry()

    assert registry.require("corporate_action.ex_dividend_timeline").status == "planned"
    assert registry.require("microstructure.disposition_stock").available_date_policy
    assert registry.require("recommendation.exclusion.why_not_payload").status == "partial"
    assert registry.require("decision_desk.snapshot.watchlist_trigger").status == "ready"


def test_registry_serializes_fields_and_warnings():
    inspection = inspect_data_source_capabilities()
    payload = inspection.to_dict()

    source_ids = {item["source_id"] for item in payload["sources"]}
    assert "microstructure.limit_lock" in source_ids
    ex_dividend = next(
        item for item in payload["sources"] if item["source_id"] == "corporate_action.ex_dividend_timeline"
    )
    assert ex_dividend["fields"][0]["field_name"] == "event_date"
    assert "source_not_ingested" in ex_dividend["warnings"]
    assert payload["status_counts"]["planned"] >= 1
    assert payload["production_data_writes"] is False


def test_inspect_data_source_capabilities_cli_outputs_json():
    completed = subprocess.run(
        [sys.executable, "scripts/inspect_data_source_capabilities.py"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    payload = json.loads(completed.stdout)
    assert payload["schema_version"] == 1
    assert payload["production_data_writes"] is False
    assert any(item["source_id"] == "twse.daily_prices.raw" for item in payload["sources"])
