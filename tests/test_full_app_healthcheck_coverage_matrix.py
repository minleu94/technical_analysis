from qa.full_app_healthcheck.coverage_matrix import (
    CoverageStatus,
    HealthcheckCoverageItem,
    ManualHealthcheckStatus,
    detect_coverage_gaps,
)


def test_detect_coverage_gaps_keeps_manual_and_missing_visible():
    items = (
        HealthcheckCoverageItem(
            healthcheck_id="UPDATE-001",
            title="數據更新頁可載入",
            status=CoverageStatus.AUTOMATED,
            manual_status=ManualHealthcheckStatus.FIXED_PENDING_VERIFICATION,
            evidence="manifest:LOOP-1",
        ),
        HealthcheckCoverageItem(
            healthcheck_id="UPDATE-009",
            title="快速更新實際寫入",
            status=CoverageStatus.MANUAL_ONLY,
            manual_status=ManualHealthcheckStatus.NEEDS_CONFIRMATION,
            evidence="非破壞模式不執行正式寫入",
        ),
        HealthcheckCoverageItem(
            healthcheck_id="PORTFOLIO-004",
            title="持倉刪除流程",
            status=CoverageStatus.NOT_YET_AUTOMATED,
            manual_status=ManualHealthcheckStatus.NEEDS_CONFIRMATION,
            evidence="尚未建立高風險取消測項",
        ),
    )

    gaps = detect_coverage_gaps(items)

    assert [gap.healthcheck_id for gap in gaps] == ["UPDATE-009", "PORTFOLIO-004"]
    assert gaps[0].status is CoverageStatus.MANUAL_ONLY


def test_coverage_item_preserves_manual_status_separately_from_automation_status():
    item = HealthcheckCoverageItem(
        healthcheck_id="M-001",
        title="大盤指數規則匹配度顯示",
        status=CoverageStatus.EXISTING_TEST_BRIDGED,
        manual_status=ManualHealthcheckStatus.FIXED_PENDING_VERIFICATION,
        evidence="tests/test_ui_qt_market_regime_view.py",
        source_batch="Batch 6",
    )

    assert item.status is CoverageStatus.EXISTING_TEST_BRIDGED
    assert item.manual_status is ManualHealthcheckStatus.FIXED_PENDING_VERIFICATION
    assert item.source_batch == "Batch 6"
