from __future__ import annotations

from qa.full_app_healthcheck.coverage_matrix import (
    CoverageStatus,
    HealthcheckCoverageItem,
    ManualHealthcheckStatus,
)


def build_batch_closeout_baseline() -> tuple[HealthcheckCoverageItem, ...]:
    return (
        HealthcheckCoverageItem(
            healthcheck_id="M-001",
            title="大盤指數規則匹配度顯示",
            status=CoverageStatus.EXISTING_TEST_BRIDGED,
            manual_status=ManualHealthcheckStatus.FIXED_PENDING_VERIFICATION,
            evidence="tests/test_ui_qt_market_regime_view.py",
            source_batch="Batch 6",
            notes="自動測試只能驗證文案與 tooltip；人工狀態仍保持待驗證。",
        ),
        HealthcheckCoverageItem(
            healthcheck_id="M-002",
            title="大盤指數技術細節趨勢規則分說明",
            status=CoverageStatus.EXISTING_TEST_BRIDGED,
            manual_status=ManualHealthcheckStatus.FIXED_PENDING_VERIFICATION,
            evidence="tests/test_ui_qt_market_regime_view.py",
            source_batch="Batch 6",
        ),
        HealthcheckCoverageItem(
            healthcheck_id="MARKET-ISSUE-002",
            title="Regime confidence / subscore 不是勝率的使用者可理解揭露",
            status=CoverageStatus.EXISTING_TEST_BRIDGED,
            manual_status=ManualHealthcheckStatus.FIXED_PENDING_VERIFICATION,
            evidence="tests/test_ui_qt_market_regime_view.py",
            source_batch="Batch 6",
        ),
        HealthcheckCoverageItem(
            healthcheck_id="B-038",
            title="Research Lab 圖表頁既有 run 首次載入",
            status=CoverageStatus.EXISTING_TEST_BRIDGED,
            manual_status=ManualHealthcheckStatus.FIXED_PENDING_VERIFICATION,
            evidence="tests/test_ui_qt_research_workflow.py",
            source_batch="Batch 6",
        ),
        HealthcheckCoverageItem(
            healthcheck_id="B-039",
            title="Research Lab 歷史與比較首次載入",
            status=CoverageStatus.EXISTING_TEST_BRIDGED,
            manual_status=ManualHealthcheckStatus.FIXED_PENDING_VERIFICATION,
            evidence="tests/test_ui_qt_research_workflow.py; tests/test_ui_qt_run_registry_compare.py",
            source_batch="Batch 6",
        ),
        HealthcheckCoverageItem(
            healthcheck_id="B-041",
            title="推薦回放保存 / 升級後導引",
            status=CoverageStatus.EXISTING_TEST_BRIDGED,
            manual_status=ManualHealthcheckStatus.FIXED_PENDING_VERIFICATION,
            evidence="tests/test_ui_qt_research_workflow.py",
            source_batch="Batch 6",
        ),
        HealthcheckCoverageItem(
            healthcheck_id="BACKTEST-ISSUE-021",
            title="歷史、圖表、Registry 比較首次進入自動 refresh",
            status=CoverageStatus.EXISTING_TEST_BRIDGED,
            manual_status=ManualHealthcheckStatus.FIXED_PENDING_VERIFICATION,
            evidence="tests/test_ui_qt_research_workflow.py; tests/test_ui_qt_run_registry_compare.py",
            source_batch="Batch 6",
        ),
        HealthcheckCoverageItem(
            healthcheck_id="BACKTEST-ISSUE-023",
            title="策略版本升級後知道去哪裡看",
            status=CoverageStatus.EXISTING_TEST_BRIDGED,
            manual_status=ManualHealthcheckStatus.FIXED_PENDING_VERIFICATION,
            evidence="tests/test_ui_qt_research_workflow.py",
            source_batch="Batch 6",
        ),
        HealthcheckCoverageItem(
            healthcheck_id="UPDATE-ISSUE-013",
            title="券商分點受控並行",
            status=CoverageStatus.BLOCKED,
            manual_status=ManualHealthcheckStatus.INVESTIGATED_NOT_PARALLELIZED,
            source_batch="Batch 5",
            blocked_reason="受控並行牽涉 MoneyDJ / Selenium / retry / rate limit，不屬第一版非破壞 runner。",
        ),
        HealthcheckCoverageItem(
            healthcheck_id="UPDATE-ISSUE-014",
            title="技術指標多核心計算",
            status=CoverageStatus.BLOCKED,
            manual_status=ManualHealthcheckStatus.INVESTIGATED_NOT_PARALLELIZED,
            source_batch="Batch 5",
            blocked_reason="多核心 compute 與單 writer 寫入需要獨立設計，避免 SQLite / CSV 寫入競爭。",
        ),
    )
