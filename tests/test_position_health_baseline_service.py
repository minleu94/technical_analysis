from __future__ import annotations

import json
from pathlib import Path

from app_module.position_health_baseline_service import PositionHealthBaselineService


def test_missing_thesis_fields_fail_closed_to_watch(tmp_path: Path) -> None:
    source = tmp_path / "paper.json"
    source.write_text(
        json.dumps(
            {
                "decision_date": "2026-07-12",
                "source_result_id": "scheduled_rec_20260712_051002",
                "research_only": True,
                "allocations": [
                    {
                        "stock_code": "1615",
                        "stock_name": "大山",
                        "executable_shares": 1000,
                        "constrained_weight_bp": 1500,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = PositionHealthBaselineService().build(source)

    assert payload["research_only"] is True
    assert payload["writes_positions_db"] is False
    assert payload["auto_action_allowed"] is False
    assert payload["positions"][0]["state"] == "WATCH"
    assert payload["positions"][0]["entry_thesis"] is None
    assert payload["positions"][0]["invalidation"] is None
    assert set(payload["positions"][0]["required_human_fields"]) == {
        "entry_thesis",
        "invalidation",
        "holding_horizon",
        "review_date",
    }
    assert "missing_entry_thesis" in payload["positions"][0]["reasons"]


def test_zero_share_allocation_is_not_treated_as_active_position(tmp_path: Path) -> None:
    source = tmp_path / "paper.json"
    source.write_text(
        json.dumps(
            {
                "decision_date": "2026-07-12",
                "research_only": True,
                "allocations": [
                    {"stock_code": "2330", "stock_name": "台積電", "executable_shares": 0, "constrained_weight_bp": 1500}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = PositionHealthBaselineService().build(source)

    assert payload["positions"] == []
    assert payload["diagnostics"] == ["no_active_paper_positions"]
