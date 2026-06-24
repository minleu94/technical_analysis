from __future__ import annotations

from qa.full_app_healthcheck.coverage_burndown import (
    generate_coverage_burndown_report,
    render_coverage_burndown_markdown,
    CoverageBurndownReport,
)
from qa.full_app_healthcheck.feature_router import FeatureRoute


def test_coverage_burndown_report_default():
    """驗證預設報告的生成與基本欄位"""
    report = generate_coverage_burndown_report()
    assert isinstance(report, CoverageBurndownReport)
    assert report.total_features == 6
    assert report.ui_covered_count == 6
    assert report.oracle_only_count == 0
    assert report.gap_count == 0
    assert report.burndown_percentage == 100.0
    assert len(report.features) == 6
    assert report.known_gap_count > 0
    assert "known feature gaps" in report.summary

    # FEATURE_ROUTES 只對映高層功能用到的 service oracle。
    # 推薦系統等 service-oracle 測試仍應以 unmapped gaps 呈現。
    assert len(report.unmapped_service_oracles) > 0
    assert "tests/test_recommendation_dto_roundtrip.py" in report.unmapped_service_oracles


def test_coverage_burndown_with_mocked_routes():
    """驗證當有不同覆蓋度狀態 feature 時的分類與計算邏輯"""
    mock_routes = {
        "feat_a": FeatureRoute(
            feature_id="feat_a",
            display_name="Feature A (UI Covered)",
            direct_bridge_suite_ids=("suite-1",),
            candidate_test_paths=(),
            service_oracle_test_paths=(),
            quick_supported=True,
            full_supported=True,
            data_audit_policy="never",
            data_audit_triggers=(),
            known_gaps=(),
            safety_notes="safe",
        ),
        "feat_b": FeatureRoute(
            feature_id="feat_b",
            display_name="Feature B (Oracle Only)",
            direct_bridge_suite_ids=(),
            candidate_test_paths=(),
            service_oracle_test_paths=("tests/test_update_service_status.py",),
            quick_supported=False,
            full_supported=True,
            data_audit_policy="never",
            data_audit_triggers=(),
            known_gaps=(),
            safety_notes="safe",
        ),
        "feat_c": FeatureRoute(
            feature_id="feat_c",
            display_name="Feature C (Gap)",
            direct_bridge_suite_ids=(),
            candidate_test_paths=(),
            service_oracle_test_paths=(),
            quick_supported=False,
            full_supported=False,
            data_audit_policy="never",
            data_audit_triggers=(),
            known_gaps=(),
            safety_notes="safe",
        ),
    }

    report = generate_coverage_burndown_report(feature_routes=mock_routes)

    assert report.total_features == 3
    assert report.ui_covered_count == 1
    assert report.oracle_only_count == 1
    assert report.gap_count == 1

    # UI covered 算 1.0, Oracle only 算 0.5, Gap 算 0.0
    # 進度應為 ((1 + 0.5 * 1) / 3) * 100 = 50.0%
    assert report.burndown_percentage == 50.0

    features_by_id = {f.feature_id: f for f in report.features}
    assert features_by_id["feat_a"].status == "fully-ui-covered"
    assert features_by_id["feat_b"].status == "oracle-only"
    assert features_by_id["feat_c"].status == "gap"
    assert features_by_id["feat_b"].service_oracle_evidence_roles == (
        "data update and cache status evidence",
    )


def test_coverage_burndown_markdown_renderer():
    """驗證 Markdown 渲染格式與必備內容"""
    report = generate_coverage_burndown_report()
    md = render_coverage_burndown_markdown(report)

    assert "Full App Healthcheck Coverage Burn-down Report" in md
    assert "Progress Summary" in md
    assert "Burndown Progress" in md
    assert "Known Manual / UX Gaps" in md
    assert "Feature Coverage Details" in md
    assert "Service Oracle Evidence" in md
    assert "Coverage Gaps & Unmapped Components" in md
    assert "Future Candidate Work Items" in md

    # 確保特有的 feature 被包含在 Markdown 中
    assert "update_view" in md
    assert "decision_desk" in md
    assert "TWSE/TPEX real API fetch progress bar indication" in md
    assert "decision desk dashboard service validation" in md
