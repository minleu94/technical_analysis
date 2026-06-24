from __future__ import annotations

from qa.full_app_healthcheck.manifest import (
    HealthcheckManifest,
    HealthcheckMode,
    HealthcheckStep,
    RiskLevel,
)


def build_default_manifest() -> HealthcheckManifest:
    return HealthcheckManifest(
        id="full-app-release-healthcheck-v1",
        title="Release 前非破壞式 Full App Healthcheck",
        modes=(
            HealthcheckMode.QUICK,
            HealthcheckMode.FULL,
        ),
        steps=(
            HealthcheckStep(
                id="EXISTING-QUICK-UI",
                title="呼叫既有快速 UI contract 測試：UpdateView + Daily Decision Desk",
                mode=HealthcheckMode.QUICK,
                workspace="既有測試",
                action="run_existing_suites_for_mode",
                risk=RiskLevel.UI_ONLY,
                expected="重用既有快速 UI 測試，不重寫同等測試邏輯。",
            ),
            HealthcheckStep(
                id="EXISTING-FULL-UI",
                title="呼叫既有完整 UI / QA 測試：Research workflow、Market Regime、Registry Compare、Smart Money、Update QA",
                mode=HealthcheckMode.FULL,
                workspace="既有測試",
                action="run_existing_suites_for_mode",
                risk=RiskLevel.READ_ONLY,
                expected="重用 Batch 1-6 後既有完整 UI 與 QA scripts，避免重複測試檔案。",
            ),
        ),
    )
