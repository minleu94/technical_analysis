from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from qa.full_app_healthcheck.feature_router import FEATURE_ROUTES
from qa.full_app_healthcheck.service_oracle_metadata import get_service_oracle_metadata


@dataclass(frozen=True)
class FlowStep:
    step_id: str
    feature_id: str
    purpose: str
    evidence_sources: tuple[str, ...]
    expected_next_step: str
    manual_gaps: tuple[str, ...]


@dataclass(frozen=True)
class HealthcheckFlow:
    flow_id: str
    display_name: str
    entrypoint: str
    steps: tuple[FlowStep, ...]
    likely_owner: str
    safety_notes: str

    @property
    def ordered_steps(self) -> tuple[str, ...]:
        return tuple(step.purpose for step in self.steps)

    @property
    def ordered_feature_ids(self) -> tuple[str, ...]:
        return tuple(step.feature_id for step in self.steps)

    @property
    def feature_id(self) -> str:
        return self.steps[0].feature_id

    @property
    def evidence_sources(self) -> tuple[str, ...]:
        return tuple(source for step in self.steps for source in step.evidence_sources)

    @property
    def expected_next_step(self) -> str:
        return self.steps[-1].expected_next_step

    @property
    def manual_gaps(self) -> tuple[str, ...]:
        return tuple(gap for step in self.steps for gap in step.manual_gaps)


ClosedLoopFlow = HealthcheckFlow


@dataclass(frozen=True)
class FlowModelReport:
    flows: tuple[HealthcheckFlow, ...]
    summary: str


def _step(
    step_id: str,
    feature_id: str,
    purpose: str,
    expected_next_step: str,
    extra_evidence: tuple[str, ...] = (),
    extra_manual_gaps: tuple[str, ...] = (),
) -> FlowStep:
    route = FEATURE_ROUTES[feature_id]
    evidence_sources = (
        route.direct_bridge_suite_ids
        + route.candidate_test_paths
        + route.service_oracle_test_paths
        + extra_evidence
    )
    return FlowStep(
        step_id=step_id,
        feature_id=feature_id,
        purpose=purpose,
        evidence_sources=evidence_sources,
        expected_next_step=expected_next_step,
        manual_gaps=route.known_gaps + extra_manual_gaps,
    )


FLOWS: dict[str, HealthcheckFlow] = {
    "data_market_loop": HealthcheckFlow(
        flow_id="data_market_loop",
        display_name="資料與市場狀態閉環 (Data & Market Status Loop)",
        entrypoint="UpdateView / 資料更新頁",
        steps=(
            _step(
                "data_freshness",
                "update_view",
                "確認資料更新 workbench、SQLite/CSV 狀態與日資料新鮮度。",
                "交給市場觀察頁確認 regime 與大盤狀態。",
                extra_evidence=("scripts/qa_validate_update_tab.py",),
            ),
            _step(
                "market_context",
                "market_regime",
                "判讀市場 regime、規則匹配與大盤技術背景。",
                "交給主力流向頁檢查籌碼與分點訊號。",
            ),
            _step(
                "smart_money_context",
                "smart_money",
                "檢查 broker flow、分點解碼與主力語意訊號。",
                "回到每日決策桌或候選池，提供資料與市場證據。",
            ),
        ),
        likely_owner="testing_qa",
        safety_notes="Non-destructive model only; do not invoke actual backfill, migration, or long-running data writes.",
    ),
    "research_validation_loop": HealthcheckFlow(
        flow_id="research_validation_loop",
        display_name="研究驗證閉環 (Research & Validation Loop)",
        entrypoint="Research Lab / 策略回測頁",
        steps=(
            _step(
                "research_experiment",
                "research_lab",
                "設定策略、執行回測或 walk-forward 驗證，檢查 look-ahead 與數值治理邊界。",
                "交給跨 run 比較檢查成果是否穩定。",
            ),
            _step(
                "registry_compare",
                "registry_compare",
                "比較多組 research runs、參數與 normalized equity 證據。",
                "若結果可用，進入 recommendation / portfolio handoff；若不可用，回到 Research Lab。",
                extra_manual_gaps=("Recommendation / portfolio handoff route is not a first-class feature route yet.",),
            ),
        ),
        likely_owner="testing_qa",
        safety_notes="Model only; heavy backtest execution remains outside quick mode.",
    ),
    "portfolio_review_loop": HealthcheckFlow(
        flow_id="portfolio_review_loop",
        display_name="持倉檢查閉環 (Portfolio Review Loop)",
        entrypoint="Portfolio / Watchlist candidate gaps",
        steps=(
            _step(
                "portfolio_candidate_gap",
                "smart_money",
                "以 portfolio / watchlist candidate bridge gaps 作為入口，先補齊持倉與候選池風險證據。",
                "交給主力流向頁確認籌碼與分點訊號。",
                extra_evidence=(
                    "tests/test_ui_qt_portfolio_view.py",
                    "tests/test_ui_qt_watchlist_candidate_pool_copy_text.py",
                ),
                extra_manual_gaps=(
                    "Portfolio view is still candidate bridge, not direct healthcheck flow.",
                    "Watchlist candidate pool is still candidate bridge, not direct healthcheck flow.",
                ),
            ),
            _step(
                "smart_money_review",
                "smart_money",
                "檢查持倉個股主力流向與 broker flow 單位、排序、語意狀態。",
                "交給每日決策桌做風控警示判定。",
            ),
            _step(
                "decision_risk_review",
                "decision_desk",
                "彙整持倉、watchlist、risk prompt 與 dashboard warnings。",
                "輸出人工檢查項或交接 Execution / Data Audit。",
            ),
        ),
        likely_owner="testing_qa",
        safety_notes="Portfolio and watchlist UI tests remain candidate evidence until bridge promotion policy approves them.",
    ),
    "daily_decision_loop": HealthcheckFlow(
        flow_id="daily_decision_loop",
        display_name="每日決策閉環 (Daily Decision Loop)",
        entrypoint="Daily Decision Desk / 每日決策頁",
        steps=(
            _step(
                "decision_snapshot",
                "decision_desk",
                "載入每日決策 snapshot、risk prompts、dashboard summary 與 watchlist warnings。",
                "交給市場觀察頁確認 regime 是否支援決策。",
            ),
            _step(
                "market_confirmation",
                "market_regime",
                "確認市場 regime、規則匹配度與大盤背景。",
                "交給資料更新頁確認資料 freshness。",
            ),
            _step(
                "freshness_evidence",
                "update_view",
                "確認資料來源狀態、SQLite/CSV freshness 與更新頁安全提示。",
                "若 freshness 不足，交接 Data Audit；否則回到每日決策桌完成人工決策。",
                extra_evidence=("scripts/qa_validate_update_tab.py",),
            ),
        ),
        likely_owner="testing_qa",
        safety_notes="Read-only diagnostics model; do not execute live trading or data write actions.",
    ),
}


def get_all_flows() -> tuple[HealthcheckFlow, ...]:
    return tuple(FLOWS.values())


def get_flow(flow_id: str) -> HealthcheckFlow | None:
    return FLOWS.get(flow_id)


def generate_flow_model_report() -> FlowModelReport:
    flows = get_all_flows()
    step_count = sum(len(flow.steps) for flow in flows)
    manual_gap_count = sum(len(flow.manual_gaps) for flow in flows)
    return FlowModelReport(
        flows=flows,
        summary=(
            f"{len(flows)} closed-loop flows, {step_count} ordered feature steps, "
            f"{manual_gap_count} manual or UX gaps tracked."
        ),
    )


def render_flow_model_markdown(report: FlowModelReport) -> str:
    lines = [
        "## Full App Healthcheck Closed-loop Flow Model",
        "",
        "> [!IMPORTANT]",
        "> Service oracle tests are evidence only; they are not executable UI flow steps.",
        "",
        f"Summary: {report.summary}",
        "",
    ]
    for flow in report.flows:
        lines.extend(
            [
                f"### `{flow.flow_id}` - {flow.display_name}",
                f"- **Entrypoint**: {flow.entrypoint}",
                f"- **Likely Owner**: `{flow.likely_owner}`",
                f"- **Safety Notes**: {flow.safety_notes}",
                "",
                "| Step | Feature | Purpose | Evidence Sources | Manual / UX Gaps | Next Step |",
                "|---|---|---|---|---|---|",
            ]
        )
        for step in flow.steps:
            evidence = "<br>".join(_format_evidence(source, step.feature_id) for source in step.evidence_sources)
            gaps = "<br>".join(step.manual_gaps) or "none"
            lines.append(
                f"| `{step.step_id}` | `{step.feature_id}` | {step.purpose} | {evidence or 'none'} | "
                f"{gaps} | {step.expected_next_step} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip()


def _format_evidence(source: str, feature_id: str) -> str:
    if source.startswith("tests/"):
        try:
            metadata = get_service_oracle_metadata(source, feature_id)
        except ValueError:
            return f"`{Path(source).name}`"
        return f"`{Path(source).name}` evidence: {metadata.evidence_role}"
    return f"`{source}`"
