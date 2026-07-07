from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_module.decision_desk_dtos import (
    DecisionDeskActionSummary,
    DecisionDeskQuality,
    DecisionDeskRiskPrompt,
    DecisionDeskRiskPromptSummary,
    DecisionDeskSnapshot,
    MarketBreadthSummary,
    MarketRegimeSummary,
    PortfolioAlertSummary,
    RelativeStrengthLiquiditySummary,
    SectorRotationSummary,
    WatchlistTriggerSummary,
)
from app_module.pre_v2_readiness_service import (
    PreV2ReadinessItem,
    PreV2ReadinessReport,
    STATUS_READY,
    STATUS_WAITING_FOR_TIME,
)
from app_module.workbench_dtos import WorkbenchDashboardDTO
from app_module.workbench_read_only_composer import WorkbenchReadOnlyComposer
from app_module.workbench_replay_summary import load_historical_replay_summary
from app_module.workbench_source_service import WorkbenchSourceService
from data_module.config import TWStockConfig


def main(argv: list[str] | None = None) -> int:
    stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(stdout_reconfigure):
        stdout_reconfigure(encoding="utf-8")
    stderr_reconfigure = getattr(sys.stderr, "reconfigure", None)
    if callable(stderr_reconfigure):
        stderr_reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Inspect V2.0 Workbench Phase 1 read-only prototype.")
    parser.add_argument("--sample", action="store_true", help="Use built-in sample payloads.")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", type=Path, help="Optional artifact output path.")
    parser.add_argument("--replay-summary-json", type=Path, help="Optional historical replay JSON summary path.")
    parser.add_argument("--db-path", type=Path, help="Evidence SQLite DB path. Missing DB is reported, not created.")
    parser.add_argument("--research-db-path", type=Path, help="Research Run SQLite DB path. Missing DB is reported, not created.")
    parser.add_argument("--decision-date", help="Decision date for read-only source lookup.")
    parser.add_argument("--multi-day-record-path", type=Path, help="Markdown multi-day dry-run record path.")
    parser.add_argument("--min-weekly-records", type=int, default=3)
    parser.add_argument("--min-dry-run-days", type=int, default=3)
    parser.add_argument("--agent-report-limit", type=int, default=5)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args(argv)

    if args.sample:
        replay_summary = (
            load_historical_replay_summary(args.replay_summary_json) if args.replay_summary_json is not None else None
        )
        source_mode = "sample_plus_historical_replay" if replay_summary is not None else "sample_only"
        dashboard = WorkbenchReadOnlyComposer().compose(
            decision_snapshot=_sample_decision_snapshot(),
            readiness_report=_sample_readiness_report(),
            agent_report_sample=_sample_agent_report(),
            historical_replay_summary=replay_summary,
            source_mode=source_mode,
        )
    else:
        if args.db_path is None:
            parser.error("--db-path is required unless --sample is used.")
        config = _config_from_args(args)
        dashboard = WorkbenchSourceService(
            config,
            evidence_db_path=args.db_path,
            research_db_path=args.research_db_path,
        ).inspect(
            decision_date=args.decision_date,
            multi_day_record_path=args.multi_day_record_path,
            min_weekly_records=args.min_weekly_records,
            min_dry_run_days=args.min_dry_run_days,
            agent_report_limit=args.agent_report_limit,
            replay_summary_json=args.replay_summary_json,
        )
    rendered = (
        json.dumps(dashboard.to_dict(), ensure_ascii=False, indent=2)
        if args.format == "json"
        else render_workbench_markdown(dashboard)
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


def _config_from_args(args: argparse.Namespace) -> TWStockConfig:
    kwargs: dict[str, Any] = {}
    if args.data_root is not None:
        kwargs["data_root"] = args.data_root
    if args.output_root is not None:
        kwargs["output_root"] = args.output_root
    config = TWStockConfig(**kwargs)
    if args.db_path is not None:
        config.db_file = args.db_path
    if args.research_db_path is not None:
        config.research_run_db_file = args.research_db_path
    return config


def render_workbench_markdown(dashboard: WorkbenchDashboardDTO) -> str:
    payload = dashboard.to_dict()
    lines = [
        "# V2.0 Unified Decision Workbench Prototype",
        "",
        f"- source_mode: `{payload['source_mode']}`",
        f"- generated_at: `{payload['generated_at']}`",
        f"- production_scheduler_allowed: `{str(payload['access_boundary']['production_scheduler_allowed']).lower()}`",
        f"- writes_allowed: `{str(payload['access_boundary']['writes_allowed']).lower()}`",
        "",
        "此 prototype 僅供 Phase 1 read-only design spike 使用，不是交易建議。",
    ]
    lines.extend(["", "## Status Strip", ""])
    for item in payload["status_strip"]:
        lines.append(f"- {item['label']}: `{item['status']}` - {item['value']}")
    lines.extend(["", "## 今日待判讀", ""])
    for item in payload["review_items"]:
        lines.append(f"- [{item['severity']}] {item['title']} ({item['source']}): {item['summary']}")
    lines.extend(["", "## Evidence Mode", ""])
    for item in payload["evidence_summary"]:
        lines.append(f"- {item['label']}: `{item['status']}` - {item['summary']}")
        if item.get("diagnostics"):
            lines.append(f"  - diagnostics: {', '.join(str(diagnostic) for diagnostic in item['diagnostics'])}")
    lines.extend(["", "## Daily Checklist", ""])
    for item in payload["daily_checklist"]:
        lines.append(f"- {item['label']}: `{item['status']}` - {item['summary']}")
    if payload["warnings"]:
        lines.extend(["", "## Limitations", ""])
        lines.extend(f"- {warning}" for warning in payload["warnings"])
    return "\n".join(lines)


def _sample_decision_snapshot() -> DecisionDeskSnapshot:
    sample_date = date(2026, 7, 6)
    return DecisionDeskSnapshot(
        as_of_date=sample_date,
        generated_at=datetime(2026, 7, 6, 12, 0, 0),
        schema_version=1,
        overall_quality=DecisionDeskQuality.OBSERVED,
        market_regime=MarketRegimeSummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            regime_label="risk-on",
            regime_confidence=8200,
        ),
        market_breadth=MarketBreadthSummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            breadth_ratio_bp=6200,
            advancing=120,
            declining=80,
            unchanged=10,
        ),
        sector_rotation=SectorRotationSummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            leading_sector="半導體",
            trailing_sector="金融",
            rotation_intensity_bp=150,
        ),
        relative_strength_liquidity=RelativeStrengthLiquiditySummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=("low_liquidity:9999",),
            top_strength_codes=("2330", "2454"),
            weak_strength_codes=("1101",),
            low_liquidity_codes=("9999",),
        ),
        watchlist_triggers=WatchlistTriggerSummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            trigger_count=1,
            triggered_codes=("2603",),
            top_signal="momentum_breakout",
        ),
        portfolio_alerts=PortfolioAlertSummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            alert_count=1,
            alert_codes=("2330",),
            alert_level="high",
        ),
        risk_prompts=DecisionDeskRiskPromptSummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            prompts=(
                DecisionDeskRiskPrompt(
                    category="portfolio",
                    severity="warning",
                    source="portfolio_alert",
                    code="2330",
                    title="Thesis invalidation review",
                    reason="持倉警示需要人工覆盤。",
                    action_hint="檢查 journal 與風險來源。",
                ),
            ),
        ),
        action_summary=DecisionDeskActionSummary(
            action_level="研究模式",
            headline="今日主結論：Phase 1 read-only prototype。",
            research_mode_note="研究模式：以下為市場與 evidence 輔助判讀，不是交易建議。",
            reasons=("市場廣度偏強。",),
        ),
    )


def _sample_readiness_report() -> PreV2ReadinessReport:
    return PreV2ReadinessReport(
        generated_at="2026-07-06T12:00:00Z",
        overall_status=STATUS_WAITING_FOR_TIME,
        production_scheduler_allowed=False,
        items=(
            PreV2ReadinessItem(
                item_id="weekly_history",
                label="多週 weekly evidence operations history",
                status=STATUS_WAITING_FOR_TIME,
                required_count=3,
                observed_count=1,
                blocking_reasons=("insufficient_weekly_history_records",),
                next_actions=("繼續累積跨週樣本。",),
            ),
            PreV2ReadinessItem(
                item_id="multi_day_dry_run",
                label="Multi-day dry-run record",
                status=STATUS_WAITING_FOR_TIME,
                required_count=3,
                observed_count=1,
                blocking_reasons=("insufficient_dry_run_days",),
                next_actions=("繼續填寫 3-5 個交易日 dry-run 紀錄。",),
            ),
            PreV2ReadinessItem(
                item_id="source_gaps",
                label="Source gaps 收斂狀態",
                status=STATUS_READY,
                evidence={"blocking_gaps": [], "warnings": []},
            ),
        ),
        limitations=(
            "waiting_for_time 代表仍需真實多週或多日觀察，不能用單次 smoke 取代。",
            "ready 只代表可進入 V2.0 design discussion，不代表投資有效性。",
        ),
    )


def _sample_agent_report() -> dict[str, Any]:
    return {
        "quality": {"evidence_row_count": 5},
        "warnings": ("agent_sample_warning",),
        "limitations": ("AI report 只能整理 evidence rows，不是交易建議。",),
        "source_trace": {"service": "AgentEvidenceAccessService", "mode": "read_only"},
    }


if __name__ == "__main__":
    raise SystemExit(main())
