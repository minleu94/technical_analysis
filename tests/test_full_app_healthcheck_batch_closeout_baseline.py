from qa.full_app_healthcheck.batch_closeout_baseline import (
    build_batch_closeout_baseline,
)
from qa.full_app_healthcheck.coverage_matrix import (
    CoverageStatus,
    ManualHealthcheckStatus,
)


def test_batch_closeout_baseline_keeps_batch6_items_and_manual_status():
    items = build_batch_closeout_baseline()
    by_id = {item.healthcheck_id: item for item in items}

    assert by_id["M-001"].manual_status is ManualHealthcheckStatus.FIXED_PENDING_VERIFICATION
    assert by_id["M-001"].status is CoverageStatus.EXISTING_TEST_BRIDGED
    assert by_id["M-001"].source_batch == "Batch 6"

    assert by_id["B-039"].status is CoverageStatus.EXISTING_TEST_BRIDGED
    assert by_id["B-041"].status is CoverageStatus.EXISTING_TEST_BRIDGED
    assert by_id["BACKTEST-ISSUE-021"].source_batch == "Batch 6"


def test_batch_closeout_baseline_blocks_deferred_high_risk_or_design_items():
    items = build_batch_closeout_baseline()
    by_id = {item.healthcheck_id: item for item in items}

    assert by_id["UPDATE-ISSUE-013"].status is CoverageStatus.BLOCKED
    assert by_id["UPDATE-ISSUE-014"].status is CoverageStatus.BLOCKED
    assert "受控並行" in by_id["UPDATE-ISSUE-013"].blocked_reason
    assert "多核心" in by_id["UPDATE-ISSUE-014"].blocked_reason
