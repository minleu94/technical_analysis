from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.inspect_formal_input_candidates import inspect_candidates


def test_candidate_inventory_separates_research_and_prospective_manifests(
    tmp_path: Path,
) -> None:
    root = tmp_path / "candidates"
    research = root / "release_v4" / "research" / "manifest.json"
    prospective = root / "formal_prospective" / "clock-20260828" / "clock" / "manifest.json"
    formal = root / "owner_deposit" / "manifest.json"
    for path in (research, prospective, formal):
        path.parent.mkdir(parents=True, exist_ok=True)
    research.write_text(
        json.dumps(
            {
                "schema_version": "portfolio-ml-training-shards.v2",
                "research_only": True,
                "formal_oos_allowed": False,
                "causal_ledger": {
                    "schema_version": "research-causal-baseline-ledger.v1",
                    "non_cash_state_day_count": 12,
                },
            }
        ),
        encoding="utf-8",
    )
    prospective.write_text(
        json.dumps(
            {
                "schema_version": "prospective-formal-simulated-portfolio-clock.v1",
                "mode": "prospective_formal_simulation",
            }
        ),
        encoding="utf-8",
    )
    formal.write_text(
        json.dumps(
            {
                "schema_version": "causal-portfolio-ledger.v1",
                "formal_consumer_compatible": True,
                "formal_oos_allowed": False,
            }
        ),
        encoding="utf-8",
    )

    report = inspect_candidates(candidate_root=root)

    assert report["read_only"] is True
    assert report["formal_ready_input_count"] == 0
    assert report["expected_schema_observed"]["causal_non_cash_portfolio_ledger"] == 1
    by_path = {item["path"]: item for item in report["candidates"]}
    assert by_path["release_v4/research/manifest.json"]["lane"] == "research_only"
    assert by_path["release_v4/research/manifest.json"]["reason"] == (
        "research_causal_ledger_not_formal_source"
    )
    assert by_path["formal_prospective/clock-20260828/clock/manifest.json"]["lane"] == (
        "prospective_only"
    )
    assert by_path["owner_deposit/manifest.json"]["lane"] == "formal_schema_candidate"
    assert '"formal_ready": true' not in json.dumps(report, ensure_ascii=False)


def test_candidate_inventory_is_bounded_and_reports_invalid_manifests(
    tmp_path: Path,
) -> None:
    root = tmp_path / "candidates"
    root.mkdir()
    for index in range(3):
        path = root / f"nested-{index}" / "manifest.json"
        path.parent.mkdir()
        path.write_text("{}", encoding="utf-8")
    invalid = root / "invalid" / "manifest.json"
    invalid.parent.mkdir()
    invalid.write_text("not-json", encoding="utf-8")

    report = inspect_candidates(candidate_root=root, max_manifests=2)

    assert report["manifest_count"] + report["skipped_count"] <= 2
    assert report["truncated"] is True
    assert report["skipped_count"] <= 2

    full_report = inspect_candidates(candidate_root=root)
    assert full_report["manifest_count"] == 3
    assert full_report["skipped_count"] == 1
    assert full_report["skipped"][0]["reason"] == "manifest_unreadable_or_invalid"


def test_candidate_inventory_refuses_report_inside_candidate_root(tmp_path: Path) -> None:
    root = tmp_path / "candidates"
    root.mkdir()
    output = root / "inventory.json"

    from scripts.inspect_formal_input_candidates import _write_report

    with pytest.raises(ValueError, match="outside candidate_root"):
        _write_report(output, {"status": "ok"}, root=root)
    assert not output.exists()
