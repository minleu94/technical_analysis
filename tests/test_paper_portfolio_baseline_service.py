from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app_module.paper_portfolio_baseline_service import PaperPortfolioBaselineService


def _write_recommendation(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "result_id": "scheduled_rec_20260712_051002",
                "created_at": "2026-07-12T05:10:02",
                "recommendations": [
                    {"證券代號": "1615", "證券名稱": "大山", "收盤價": 46.4, "總分": "66.22", "產業": "電器電纜"},
                    {"證券代號": "2330", "證券名稱": "台積電", "收盤價": 1000, "總分": "65.00", "產業": "半導體"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_builds_research_only_baseline_from_saved_recommendation(tmp_path: Path) -> None:
    source = tmp_path / "recommendation.json"
    _write_recommendation(source)

    payload = PaperPortfolioBaselineService().build(source)

    assert payload["source_result_id"] == "scheduled_rec_20260712_051002"
    assert payload["decision_date"] == "2026-07-12"
    assert payload["research_only"] is True
    assert payload["writes_positions_db"] is False
    assert payload["broker_order_allowed"] is False
    assert payload["policy"]["initial_capital"] == "500000"
    assert payload["policy"]["minimum_cash_bp"] == 2000
    assert [row["stock_code"] for row in payload["allocations"]] == ["1615", "2330"]
    assert payload["allocations"][0]["reference_price"] == "46.40"
    assert payload["allocations"][0]["score_bp"] == 6622
    assert all(row["constrained_weight_bp"] <= 1500 for row in payload["allocations"])
    assert Decimal(payload["residual_cash"]) >= Decimal("100000")


def test_missing_recommendations_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "recommendation.json"
    source.write_text('{"result_id":"empty","recommendations":[]}', encoding="utf-8")

    with pytest.raises(ValueError, match="saved recommendation contains no candidates"):
        PaperPortfolioBaselineService().build(source)


def test_invalid_price_is_preserved_as_rejected_diagnostic(tmp_path: Path) -> None:
    source = tmp_path / "recommendation.json"
    source.write_text(
        json.dumps(
            {
                "result_id": "bad-price",
                "created_at": "2026-07-12T05:10:02",
                "recommendations": [
                    {"證券代號": "2330", "證券名稱": "台積電", "收盤價": None, "總分": "65.00", "產業": "半導體"},
                    {"證券代號": "2317", "證券名稱": "鴻海", "收盤價": "100", "總分": "60.00", "產業": "電子"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = PaperPortfolioBaselineService().build(source)

    rejected = payload["allocations"][0]
    assert rejected["stock_code"] == "2330"
    assert rejected["executable_amount"] == "0.00"
    assert "rejected_invalid_reference_price" in rejected["diagnostics"]
