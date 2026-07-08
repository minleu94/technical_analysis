from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app_module.source_candidate_readiness import (
    ACCESS_BOUNDARY,
    SourceCandidateReadinessService,
    SourceCandidateRow,
    build_sample_source_candidate_report,
)
from scripts.inspect_source_candidate_readiness import main as inspect_source_candidate_readiness_main


def _item(payload: dict, source_id: str) -> dict:
    return next(item for item in payload["items"] if item["source_id"] == source_id)


def test_missing_sources_degrade_without_creating_db_or_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "not_ingested.sqlite"

    report = SourceCandidateReadinessService.from_sqlite(db_path, decision_date="2026-07-08").build_report()
    payload = report.to_dict()

    assert db_path.exists() is False
    assert payload["access_boundary"] == ACCESS_BOUNDARY
    assert payload["access_boundary"]["writes_allowed"] is False
    assert payload["access_boundary"]["production_scheduler_allowed"] is False
    assert payload["access_boundary"]["scoring_engine_write_allowed"] is False
    assert payload["access_boundary"]["investment_effectiveness_claim"] is False
    assert {item["source_id"] for item in payload["items"]} == {
        "institutional_flows",
        "credit_transactions",
        "tdcc_shareholding",
    }
    for item in payload["items"]:
        assert item["decision_ready"] is False
        assert item["status"] == "degraded"
        assert "source_not_ingested" in item["diagnostics"]
        assert "missing_db" in item["diagnostics"]


def test_table_exists_but_missing_available_date_is_not_decision_ready(tmp_path: Path) -> None:
    db_path = tmp_path / "sources.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE institutional_flows (
                stock_code TEXT,
                decision_date TEXT,
                foreign_investor_buy INTEGER,
                foreign_investor_sell INTEGER,
                foreign_investor_net INTEGER,
                investment_trust_buy INTEGER,
                investment_trust_sell INTEGER,
                investment_trust_net INTEGER,
                dealer_buy INTEGER,
                dealer_sell INTEGER,
                dealer_net INTEGER,
                source_version TEXT,
                quality TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO institutional_flows VALUES (
                '2330', '2026-07-08',
                1000, 700, 300,
                200, 100, 100,
                80, 60, 20,
                'sample-v1', 'observed'
            )
            """
        )

    payload = SourceCandidateReadinessService.from_sqlite(db_path, decision_date="2026-07-08").build_report().to_dict()
    institutional = _item(payload, "institutional_flows")

    assert institutional["decision_ready"] is False
    assert institutional["status"] == "degraded"
    assert "missing_available_date" in institutional["diagnostics"]


def test_future_available_date_is_blocked() -> None:
    row = SourceCandidateRow(
        source_id="credit_transactions",
        symbol="2330",
        decision_date="2026-07-08",
        available_date="2026-07-09",
        source_version="sample-v1",
        quality="observed",
        payload={
            "margin_purchase": 100,
            "margin_balance": 2500,
            "short_sale": 20,
            "short_balance": 400,
        },
    )

    payload = SourceCandidateReadinessService(rows=(row,), decision_date="2026-07-08").build_report().to_dict()
    credit = _item(payload, "credit_transactions")

    assert credit["decision_ready"] is False
    assert credit["blocked_row_count"] == 1
    assert "future_data_blocked" in credit["diagnostics"]


def test_all_three_sources_can_emit_readiness_items_with_optional_credit_diagnostics() -> None:
    payload = build_sample_source_candidate_report(decision_date="2026-07-08").to_dict()

    institutional = _item(payload, "institutional_flows")
    credit = _item(payload, "credit_transactions")
    tdcc = _item(payload, "tdcc_shareholding")

    assert institutional["decision_ready"] is True
    assert "foreign_investor_buy" in institutional["coverage"]["required_fields_present"]
    assert credit["decision_ready"] is True
    assert "missing_optional_source:financing" in credit["diagnostics"]
    assert "missing_optional_source:securities_lending" in credit["diagnostics"]
    assert tdcc["decision_ready"] is True
    assert "large_holder_ratio_bp" in tdcc["coverage"]["candidate_fields_present"]


def test_cli_sample_outputs_json_and_markdown(tmp_path: Path, capsys) -> None:
    json_path = tmp_path / "source_candidate.json"
    markdown_path = tmp_path / "source_candidate.md"

    assert inspect_source_candidate_readiness_main(["--sample", "--format", "json", "--output", str(json_path)]) == 0
    assert inspect_source_candidate_readiness_main(["--sample", "--format", "markdown", "--output", str(markdown_path)]) == 0

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert payload["source_mode"] == "sample_only"
    assert payload["access_boundary"]["writes_allowed"] is False
    assert "institutional_flows" in markdown
    assert "candidate-only" in markdown
    assert "writes_allowed=false" in markdown
    _ = capsys.readouterr()
