from __future__ import annotations

import pytest

from qa.full_app_healthcheck.service_oracle_metadata import (
    generate_service_oracle_report,
    get_service_oracle_metadata,
    render_service_oracle_metadata_markdown,
    ServiceOracleMetadata,
    ServiceOracleReport,
)
from qa.full_app_healthcheck.feature_router import FEATURE_ROUTES


def test_service_oracle_report_generation():
    """驗證 report 順利產生，且對齊 FEATURE_ROUTES 宣告的 service oracle 測試。"""
    report = generate_service_oracle_report()
    expected_paths = {
        path
        for route in FEATURE_ROUTES.values()
        for path in route.service_oracle_test_paths
    }
    assert isinstance(report, ServiceOracleReport)
    assert {item.path for item in report.items} == expected_paths
    assert len(report.items) == len(expected_paths)
    assert str(len(expected_paths)) in report.summary

    # 驗證每個項目的基本屬性與 allowed_as_bridge_step 必須為 False
    for item in report.items:
        assert isinstance(item, ServiceOracleMetadata)
        assert item.allowed_as_bridge_step is False
        assert item.path.startswith("tests/")
        assert item.feature_id in FEATURE_ROUTES
        assert item.oracle_category in (
            "data/market",
            "research/backtest",
            "recommendation",
            "portfolio/decision/runtime",
        )
        assert item.evidence_role != ""
        assert item.likely_owner in ("data_audit", "execution", "testing_qa")
        assert item.risk_notes != ""
        assert item.recommended_usage != ""


def test_service_oracle_specific_mappings():
    """驗證需求中明確指定的特定 mapping 關係"""
    report = generate_service_oracle_report()
    items_by_path = {item.path: item for item in report.items}

    # tests/test_update_service_status.py -> update_view
    assert "tests/test_update_service_status.py" in items_by_path
    update_meta = items_by_path["tests/test_update_service_status.py"]
    assert update_meta.feature_id == "update_view"
    assert update_meta.oracle_category == "data/market"
    assert update_meta.likely_owner == "data_audit"

    # tests/test_decision_desk_service.py -> decision_desk
    assert "tests/test_decision_desk_service.py" in items_by_path
    decision_meta = items_by_path["tests/test_decision_desk_service.py"]
    assert decision_meta.feature_id == "decision_desk"
    assert decision_meta.oracle_category == "portfolio/decision/runtime"
    assert decision_meta.likely_owner == "execution"

    # tests/test_walkforward_service.py -> market_regime
    assert "tests/test_walkforward_service.py" in items_by_path
    walkforward_meta = items_by_path["tests/test_walkforward_service.py"]
    assert walkforward_meta.feature_id == "market_regime"
    assert walkforward_meta.oracle_category == "research/backtest"
    assert walkforward_meta.likely_owner == "execution"


def test_service_oracle_unmapped_path_raises_error():
    """驗證呼叫未對映的路徑會拋出 ValueError"""
    with pytest.raises(ValueError, match="not mapped to any feature"):
        get_service_oracle_metadata("tests/does_not_exist_test_file.py")


def test_service_oracle_markdown_renderer():
    """驗證 Markdown 產生器包含明確標明 service oracle 不是 UI flow step 的警告文字"""
    report = generate_service_oracle_report()
    md = render_service_oracle_metadata_markdown(report)

    assert "Service oracle 測試是證據（Evidence），不是 UI flow step" in md
    assert "allowed_as_bridge_step 必須為 False" in md
    assert "Total 14 service oracle tests mapped to features." in md

    # 確保表格中有表格欄位名稱與對應的路徑
    assert "Service Oracle Test" in md
    assert "tests/test_update_service_status.py" in md
    assert "tests/test_walkforward_service.py" in md
