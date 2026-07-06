from __future__ import annotations

from typing import Any

from app_module.agent_evidence_access_service import (
    AgentEvidenceAccessService,
    build_agent_permission_model as build_permission_model_payload,
    build_ai_report_template as build_report_template_payload,
)
from data_module.config import TWStockConfig


def create_service() -> AgentEvidenceAccessService:
    return AgentEvidenceAccessService(TWStockConfig())


def create_evidence_access_mcp_server():
    from fastmcp import FastMCP

    mcp = FastMCP("twstock-evidence-access")
    service = create_service()

    @mcp.tool()
    def get_agent_permission_model() -> dict[str, Any]:
        """取得 V1.9 Agent evidence access 的唯讀權限模型。"""
        return build_permission_model_payload()

    @mcp.tool()
    def get_ai_report_template() -> dict[str, Any]:
        """取得 evidence-only AI report template 與必備引用欄位。"""
        return build_report_template_payload()

    @mcp.tool()
    def query_evidence_events(
        symbol: str | None = None,
        event_type: str | None = None,
        decision_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 50,
        include_outcomes: bool = True,
        window_days: int | None = None,
    ) -> dict[str, Any]:
        """唯讀查詢 evidence_events 與選定 forward outcomes。"""
        return service.query_evidence_events(
            symbol=symbol,
            event_type=event_type,
            decision_date=decision_date,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            include_outcomes=include_outcomes,
            window_days=window_days,
        )

    @mcp.tool()
    def summarize_forward_evidence(
        group_by: str = "event_type",
        window_days: int = 5,
        min_sample_size: int = 1,
        symbol: str | None = None,
        event_type: str | None = None,
        event_family: str | None = None,
        source_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        regime: str | None = None,
        sector: str | None = None,
        profile_id: str | None = None,
        strategy_version_id: str | None = None,
    ) -> dict[str, Any]:
        """唯讀彙總 forward evidence，不重跑回測或重算訊號。"""
        return service.summarize_forward_evidence(
            group_by=group_by,
            window_days=window_days,
            min_sample_size=min_sample_size,
            symbol=symbol,
            event_type=event_type,
            event_family=event_family,
            source_type=source_type,
            start_date=start_date,
            end_date=end_date,
            regime=regime,
            sector=sector,
            profile_id=profile_id,
            strategy_version_id=strategy_version_id,
        )

    @mcp.tool()
    def query_research_runs(
        run_id: str | None = None,
        run_type: str | None = None,
        strategy_id: str | None = None,
        include_archived: bool = False,
        limit: int = 50,
    ) -> dict[str, Any]:
        """唯讀查詢 Research Run Registry metadata。"""
        return service.query_research_runs(
            run_id=run_id,
            run_type=run_type,
            strategy_id=strategy_id,
            include_archived=include_archived,
            limit=limit,
        )

    @mcp.tool()
    def query_portfolio_review_evidence(
        symbol: str | None = None,
        run_id: str | None = None,
        strategy_version_id: str | None = None,
        observation_date: str | None = None,
        source_type: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """唯讀查詢 Portfolio Review 相關已保存 evidence rows。"""
        return service.query_portfolio_review_evidence(
            symbol=symbol,
            run_id=run_id,
            strategy_version_id=strategy_version_id,
            observation_date=observation_date,
            source_type=source_type,
            limit=limit,
        )

    return mcp


if __name__ == "__main__":
    create_evidence_access_mcp_server().run(show_banner=False)
