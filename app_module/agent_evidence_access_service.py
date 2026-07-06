from __future__ import annotations

from dataclasses import asdict, fields
from pathlib import Path
import json
import sqlite3
from typing import Any

from app_module.evidence_event_dtos import (
    EvidenceEvent,
    EvidenceOutcome,
    normalize_data_quality,
    normalize_event_type,
    normalize_outcome_status,
)
from app_module.forward_performance_dashboard_service import ReadOnlyEvidenceEventRepository
from app_module.forward_performance_read_model import (
    ForwardPerformanceFilter,
    ForwardPerformanceReadModel,
)
from app_module.live_research_gap_dtos import LiveResearchGapObservation
from app_module.research_run_dtos import (
    ResearchRunMetadataDTO,
    parse_json_list,
    parse_json_object,
)
from app_module.research_run_repository import ResearchRunRepository


DEFAULT_AGENT_QUERY_LIMIT = 50
MAX_AGENT_QUERY_LIMIT = 500

READ_ONLY_LIMITATIONS = (
    "這是 research evidence，不是買賣建議。",
    "查詢結果只能引用已保存 evidence rows，不代表策略變更、推薦或交易指令。",
    "資料品質、warning、source trace 與樣本限制必須與結論一起呈現。",
)


def build_agent_permission_model() -> dict[str, Any]:
    return {
        "role": "read_only_evidence_agent",
        "access_mode": "read_only",
        "allowed_actions": [
            "query_evidence_events",
            "summarize_forward_evidence",
            "query_research_run_metadata",
            "query_portfolio_review_saved_evidence",
            "draft_evidence_report",
        ],
        "denied_actions": [
            "write_database",
            "create_schema",
            "delete_or_rebuild_data",
            "modify_strategy",
            "modify_recommendation_score",
            "modify_portfolio_lifecycle",
            "modify_scheduler_state",
            "place_order",
            "simulate_broker_order_as_real_order",
            "use_llm_thesis_as_primary_evidence",
        ],
        "db_policy": {
            "sqlite_uri_mode": "mode=ro",
            "pragma_query_only": True,
            "missing_db_behavior": "return_diagnostics_without_create",
        },
        "lifecycle_policy": {
            "read_saved_lifecycle_evidence": True,
            "apply_lifecycle_action": False,
            "promote_demote_or_retire_strategy": False,
        },
    }


def build_ai_report_template() -> dict[str, Any]:
    return {
        "template_id": "v1_9_read_only_evidence_report",
        "required_sections": [
            "question",
            "filters",
            "evidence_rows",
            "quality",
            "warnings",
            "source_trace",
            "limitations",
            "follow_up_questions",
        ],
        "evidence_row_requirements": [
            "每個結論至少引用一筆 evidence row 或明確標示沒有足夠 evidence。",
            "引用 forward outcome 時必須列出 window_days、outcome_status 與 data_quality。",
            "引用 portfolio review 時只能引用已保存 live research gap 或 lifecycle evidence rows。",
        ],
        "limitations": list(READ_ONLY_LIMITATIONS),
        "prohibited_output": [
            "交易指令",
            "未附 evidence row 的策略結論",
            "把 LLM 判斷當成 primary evidence",
        ],
    }


class AgentEvidenceAccessService:
    """Read-only evidence query service for V1.9 Agent / MCP access."""

    def __init__(
        self,
        config: Any,
        *,
        evidence_db_path: str | Path | None = None,
        research_db_path: str | Path | None = None,
    ) -> None:
        self.config = config
        self.evidence_db_path = Path(evidence_db_path) if evidence_db_path is not None else Path(config.db_file)
        self.research_db_path = (
            Path(research_db_path) if research_db_path is not None else Path(config.research_run_db_file)
        )

    def query_evidence_events(
        self,
        *,
        symbol: str | None = None,
        event_type: str | None = None,
        decision_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int | None = DEFAULT_AGENT_QUERY_LIMIT,
        include_outcomes: bool = True,
        window_days: int | None = None,
    ) -> dict[str, Any]:
        safe_limit = _safe_limit(limit)
        filters = {
            "symbol": symbol,
            "event_type": event_type,
            "decision_date": decision_date,
            "start_date": start_date,
            "end_date": end_date,
            "limit": safe_limit,
            "include_outcomes": include_outcomes,
            "window_days": window_days,
        }
        repository = ReadOnlyEvidenceEventRepository(self.config, db_path=self.evidence_db_path)
        diagnostics: list[str] = []
        try:
            events = repository.list_events(
                symbol=_blank_to_none(symbol),
                event_type=_blank_to_none(event_type),
                decision_date=_blank_to_none(decision_date),
                start_date=_blank_to_none(start_date),
                end_date=_blank_to_none(end_date),
                limit=safe_limit,
            )
            outcomes_by_event = self._load_outcomes_by_event(
                repository,
                events,
                include_outcomes=include_outcomes,
                window_days=window_days,
            )
        except (FileNotFoundError, sqlite3.Error, ValueError) as exc:
            events = []
            outcomes_by_event = {}
            diagnostics.append(f"evidence_store_unavailable:{exc}")

        rows = [
            _event_to_dict(
                event,
                outcomes=outcomes_by_event.get(event.event_id, ()),
            )
            for event in events
        ]
        return {
            "access_boundary": _access_boundary(),
            "filters": filters,
            "events_count": len(rows),
            "outcomes_count": sum(len(row["outcomes"]) for row in rows),
            "events": rows,
            "limitations": list(READ_ONLY_LIMITATIONS),
            "diagnostics": diagnostics,
        }

    def summarize_forward_evidence(
        self,
        *,
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
        filters = ForwardPerformanceFilter(
            start_date=_blank_to_none(start_date),
            end_date=_blank_to_none(end_date),
            event_type=_blank_to_none(event_type),
            event_family=_blank_to_none(event_family),
            source_type=_blank_to_none(source_type),
            symbol=_blank_to_none(symbol),
            regime=_blank_to_none(regime),
            sector=_blank_to_none(sector),
            profile_id=_blank_to_none(profile_id),
            strategy_version_id=_blank_to_none(strategy_version_id),
            window_days=int(window_days),
        )
        repository = ReadOnlyEvidenceEventRepository(self.config, db_path=self.evidence_db_path)
        read_model = ForwardPerformanceReadModel(repository)
        diagnostics: list[str] = []
        try:
            summaries = read_model.summarize(
                group_by=group_by,
                filters=filters,
                min_sample_size=int(min_sample_size),
            )
        except (FileNotFoundError, sqlite3.Error, ValueError) as exc:
            summaries = []
            diagnostics.append(f"forward_evidence_unavailable:{exc}")

        return {
            "access_boundary": _access_boundary(),
            "filters": {
                "group_by": group_by,
                "window_days": int(window_days),
                "min_sample_size": int(min_sample_size),
                "symbol": symbol,
                "event_type": event_type,
                "event_family": event_family,
                "source_type": source_type,
                "start_date": start_date,
                "end_date": end_date,
                "regime": regime,
                "sector": sector,
                "profile_id": profile_id,
                "strategy_version_id": strategy_version_id,
            },
            "rows_count": len(summaries),
            "rows": [summary.to_dict() for summary in summaries],
            "limitations": list(READ_ONLY_LIMITATIONS),
            "diagnostics": diagnostics,
        }

    def query_research_runs(
        self,
        *,
        run_id: str | None = None,
        run_type: str | None = None,
        strategy_id: str | None = None,
        include_archived: bool = False,
        limit: int | None = DEFAULT_AGENT_QUERY_LIMIT,
    ) -> dict[str, Any]:
        safe_limit = _safe_limit(limit)
        diagnostics: list[str] = []
        rows: list[dict[str, Any]] = []
        filters = {
            "run_id": run_id,
            "run_type": run_type,
            "strategy_id": strategy_id,
            "include_archived": include_archived,
            "limit": safe_limit,
        }

        try:
            with _connect_read_only(self.research_db_path) as conn:
                if not _table_exists(conn, "research_runs"):
                    diagnostics.append("research_runs_table_missing")
                else:
                    rows = self._query_research_run_rows(
                        conn,
                        run_id=_blank_to_none(run_id),
                        run_type=_blank_to_none(run_type),
                        strategy_id=_blank_to_none(strategy_id),
                        include_archived=include_archived,
                        limit=safe_limit,
                    )
        except FileNotFoundError as exc:
            diagnostics.append(f"research_db_missing:{exc}")
        except (sqlite3.Error, ValueError) as exc:
            diagnostics.append(f"research_runs_unavailable:{exc}")

        return {
            "access_boundary": _access_boundary(),
            "filters": filters,
            "runs_count": len(rows),
            "runs": rows,
            "limitations": list(READ_ONLY_LIMITATIONS),
            "diagnostics": diagnostics,
        }

    def query_portfolio_review_evidence(
        self,
        *,
        symbol: str | None = None,
        run_id: str | None = None,
        strategy_version_id: str | None = None,
        observation_date: str | None = None,
        source_type: str | None = None,
        limit: int | None = DEFAULT_AGENT_QUERY_LIMIT,
    ) -> dict[str, Any]:
        safe_limit = _safe_limit(limit)
        diagnostics: list[str] = []
        live_gap_rows = self._query_live_gap_rows(
            symbol=_blank_to_none(symbol),
            run_id=_blank_to_none(run_id),
            strategy_version_id=_blank_to_none(strategy_version_id),
            observation_date=_blank_to_none(observation_date),
            source_type=_blank_to_none(source_type),
            limit=safe_limit,
            diagnostics=diagnostics,
        )
        lifecycle_rows = self._query_lifecycle_rows(
            run_id=_blank_to_none(run_id),
            strategy_version_id=_blank_to_none(strategy_version_id),
            limit=safe_limit,
            diagnostics=diagnostics,
        )

        return {
            "access_boundary": _access_boundary(),
            "portfolio_review_scope": "saved_evidence_only",
            "filters": {
                "symbol": symbol,
                "run_id": run_id,
                "strategy_version_id": strategy_version_id,
                "observation_date": observation_date,
                "source_type": source_type,
                "limit": safe_limit,
            },
            "live_research_gap_observations_count": len(live_gap_rows),
            "live_research_gap_observations": live_gap_rows,
            "strategy_lifecycle_evidence_count": len(lifecycle_rows),
            "strategy_lifecycle_evidence": lifecycle_rows,
            "limitations": [
                *READ_ONLY_LIMITATIONS,
                "Portfolio Review snapshot 目前不作為 V1.9 查詢的持久化物件；本查詢只讀已保存 gap / lifecycle evidence。",
            ],
            "diagnostics": diagnostics,
        }

    def _load_outcomes_by_event(
        self,
        repository: ReadOnlyEvidenceEventRepository,
        events: list[EvidenceEvent],
        *,
        include_outcomes: bool,
        window_days: int | None,
    ) -> dict[str, tuple[EvidenceOutcome, ...]]:
        if not include_outcomes:
            return {}
        outcomes_by_event: dict[str, tuple[EvidenceOutcome, ...]] = {}
        for event in events:
            outcomes = repository.list_outcomes(event_id=event.event_id, window_days=window_days)
            outcomes_by_event[event.event_id] = tuple(outcomes)
        return outcomes_by_event

    def _query_research_run_rows(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str | None,
        run_type: str | None,
        strategy_id: str | None,
        include_archived: bool,
        limit: int,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if run_id:
            where.append("run_id = ?")
            params.append(run_id)
        if run_type:
            where.append("run_type = ?")
            params.append(run_type)
        if strategy_id:
            where.append("strategy_id = ?")
            params.append(strategy_id)
        if not include_archived:
            where.append("is_archived = 0")
        sql = "SELECT * FROM research_runs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC, run_id ASC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, tuple(params)).fetchall()
        return [_research_run_row_to_dict(dict(row)) for row in rows]

    def _query_live_gap_rows(
        self,
        *,
        symbol: str | None,
        run_id: str | None,
        strategy_version_id: str | None,
        observation_date: str | None,
        source_type: str | None,
        limit: int,
        diagnostics: list[str],
    ) -> list[dict[str, Any]]:
        try:
            with _connect_read_only(self.evidence_db_path) as conn:
                if not _table_exists(conn, "live_research_gap_observations"):
                    diagnostics.append("live_research_gap_observations_table_missing")
                    return []
                where: list[str] = []
                params: list[Any] = []
                if symbol:
                    where.append("symbol = ?")
                    params.append(symbol)
                if run_id:
                    where.append("research_run_id = ?")
                    params.append(run_id)
                if strategy_version_id:
                    where.append("strategy_version_id = ?")
                    params.append(strategy_version_id)
                if observation_date:
                    where.append("observation_date = ?")
                    params.append(observation_date)
                if source_type:
                    where.append("source_type = ?")
                    params.append(source_type)
                sql = "SELECT * FROM live_research_gap_observations"
                if where:
                    sql += " WHERE " + " AND ".join(where)
                sql += " ORDER BY observation_date ASC, gap_id ASC LIMIT ?"
                params.append(limit)
                rows = conn.execute(sql, tuple(params)).fetchall()
                return [_live_gap_row_to_dict(dict(row)) for row in rows]
        except FileNotFoundError as exc:
            diagnostics.append(f"evidence_db_missing:{exc}")
            return []
        except (sqlite3.Error, ValueError) as exc:
            diagnostics.append(f"live_research_gap_unavailable:{exc}")
            return []

    def _query_lifecycle_rows(
        self,
        *,
        run_id: str | None,
        strategy_version_id: str | None,
        limit: int,
        diagnostics: list[str],
    ) -> list[dict[str, Any]]:
        try:
            with _connect_read_only(self.research_db_path) as conn:
                if not _table_exists(conn, "strategy_lifecycle_evidence"):
                    diagnostics.append("strategy_lifecycle_evidence_table_missing")
                    return []
                where: list[str] = []
                params: list[Any] = []
                if run_id:
                    where.append("run_id = ?")
                    params.append(run_id)
                if strategy_version_id:
                    where.append("version_id = ?")
                    params.append(strategy_version_id)
                sql = "SELECT * FROM strategy_lifecycle_evidence"
                if where:
                    sql += " WHERE " + " AND ".join(where)
                sql += " ORDER BY evidence_id ASC LIMIT ?"
                params.append(limit)
                rows = conn.execute(sql, tuple(params)).fetchall()
                return [_lifecycle_row_to_dict(dict(row)) for row in rows]
        except FileNotFoundError as exc:
            diagnostics.append(f"research_db_missing:{exc}")
            return []
        except (sqlite3.Error, ValueError) as exc:
            diagnostics.append(f"strategy_lifecycle_evidence_unavailable:{exc}")
            return []


def create_agent_evidence_access_service(config: Any) -> AgentEvidenceAccessService:
    return AgentEvidenceAccessService(config)


def _connect_read_only(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(str(path))
    uri_path = path.resolve().as_posix()
    conn = sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _safe_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_AGENT_QUERY_LIMIT
    parsed = max(1, int(limit))
    return min(parsed, MAX_AGENT_QUERY_LIMIT)


def _blank_to_none(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _access_boundary() -> dict[str, Any]:
    return {
        "mode": "read_only",
        "scope": "evidence_only",
        "writes_allowed": False,
        "strategy_changes_allowed": False,
        "orders_allowed": False,
    }


def _event_to_dict(event: EvidenceEvent, *, outcomes: tuple[EvidenceOutcome, ...]) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "event_hash": event.event_hash,
        "event_date": event.event_date,
        "decision_date": event.decision_date,
        "symbol": event.symbol,
        "event_type": normalize_event_type(event.event_type).value,
        "event_family": event.event_family,
        "score_bp": event.score_bp,
        "score_percentile_bp": event.score_percentile_bp,
        "regime": event.regime,
        "sector": event.sector,
        "liquidity_state": event.liquidity_state,
        "data_quality": normalize_data_quality(event.data_quality).value,
        "warnings": list(event.warnings),
        "reason_codes": list(event.reason_codes),
        "why_not_codes": list(event.why_not_codes),
        "risk_codes": list(event.risk_codes),
        "source_trace": {
            "source_type": event.source_type,
            "source_id": event.source_id,
            "source_snapshot_id": event.source_snapshot_id,
            "strategy_version_id": event.strategy_version_id,
            "profile_id": event.profile_id,
            "run_id": event.run_id,
            "as_of_date": event.as_of_date,
            "available_date": event.available_date,
            "source_version": event.source_version,
            "benchmark_id": event.benchmark_id,
            "industry_benchmark_id": event.industry_benchmark_id,
        },
        "metadata": dict(event.metadata),
        "outcomes": [_outcome_to_dict(outcome) for outcome in outcomes],
        "created_at": event.created_at,
    }


def _outcome_to_dict(outcome: EvidenceOutcome) -> dict[str, Any]:
    return {
        "outcome_id": outcome.outcome_id,
        "event_id": outcome.event_id,
        "window_days": outcome.window_days,
        "window_type": outcome.window_type,
        "return_basis": outcome.return_basis,
        "event_price_date": outcome.event_price_date,
        "event_close": outcome.event_close,
        "outcome_price_date": outcome.outcome_price_date,
        "outcome_close": outcome.outcome_close,
        "forward_return_bp": outcome.forward_return_bp,
        "benchmark_return_bp": outcome.benchmark_return_bp,
        "benchmark_excess_bp": outcome.benchmark_excess_bp,
        "industry_return_bp": outcome.industry_return_bp,
        "industry_excess_bp": outcome.industry_excess_bp,
        "max_adverse_excursion_bp": outcome.max_adverse_excursion_bp,
        "max_favorable_excursion_bp": outcome.max_favorable_excursion_bp,
        "tradable_flag": outcome.tradable_flag,
        "limit_up_down_flag": outcome.limit_up_down_flag,
        "suspended_flag": outcome.suspended_flag,
        "liquidity_cost_bp": outcome.liquidity_cost_bp,
        "outcome_status": normalize_outcome_status(outcome.outcome_status).value,
        "data_quality": normalize_data_quality(outcome.data_quality).value,
        "warnings": list(outcome.warnings),
        "calculated_at": outcome.calculated_at,
        "data_as_of_date": outcome.data_as_of_date,
        "metadata": dict(outcome.metadata),
    }


def _research_run_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    reverse_json_map = {value: key for key, value in ResearchRunRepository.JSON_FIELD_MAP.items()}
    dto_field_names = {field_info.name for field_info in fields(ResearchRunMetadataDTO)}
    kwargs: dict[str, Any] = {}
    for column, value in row.items():
        if column in reverse_json_map:
            dto_name = reverse_json_map[column]
            kwargs[dto_name] = parse_json_list(value) if dto_name == "universe" else parse_json_object(value)
        elif column in dto_field_names:
            kwargs[column] = bool(value) if column == "is_archived" else value
    metadata = ResearchRunMetadataDTO(**kwargs)
    payload = asdict(metadata)
    payload["source_trace"] = {
        "run_id": metadata.run_id,
        "payload_hash": metadata.payload_hash,
        "data_fingerprint": metadata.data_fingerprint,
        "fingerprint_algorithm": metadata.fingerprint_algorithm,
        "equity_path": metadata.equity_path,
        "equity_parquet_hash": metadata.equity_parquet_hash,
        "trades_path": metadata.trades_path,
        "trades_parquet_hash": metadata.trades_parquet_hash,
        "created_at": metadata.created_at,
    }
    return payload


def _live_gap_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    observation = LiveResearchGapObservation(
        gap_id=str(row["gap_id"]),
        gap_hash=str(row["gap_hash"]),
        observation_date=str(row["observation_date"]),
        position_id=str(row["position_id"]),
        symbol=str(row["symbol"]),
        portfolio_mode=str(row["portfolio_mode"]),
        source_type=str(row["source_type"]),
        source_id=str(row["source_id"]),
        research_run_id=str(row["research_run_id"]),
        strategy_version_id=str(row["strategy_version_id"]),
        recommendation_result_id=str(row["recommendation_result_id"]),
        evidence_event_id=str(row["evidence_event_id"]),
        evidence_outcome_id=str(row["evidence_outcome_id"]),
        entry_date=str(row["entry_date"]),
        entry_price=str(row["entry_price"]),
        current_price_date=str(row["current_price_date"]),
        current_price=str(row["current_price"]),
        holding_days=row["holding_days"],
        portfolio_return_bp=row["portfolio_return_bp"],
        research_expected_return_bp=row["research_expected_return_bp"],
        forward_evidence_return_bp=row["forward_evidence_return_bp"],
        benchmark_excess_bp=row["benchmark_excess_bp"],
        industry_excess_bp=row["industry_excess_bp"],
        gap_vs_research_bp=row["gap_vs_research_bp"],
        gap_vs_forward_evidence_bp=row["gap_vs_forward_evidence_bp"],
        gap_vs_benchmark_bp=row["gap_vs_benchmark_bp"],
        condition_status=str(row["condition_status"]),
        chip_risk_level=str(row["chip_risk_level"]),
        regime_at_entry=str(row["regime_at_entry"]),
        regime_current=str(row["regime_current"]),
        data_quality=str(row["data_quality"]),
        warnings_json=json.loads(row["warnings_json"] or "[]"),
        attribution_json=json.loads(row["attribution_json"] or "[]"),
        metadata_json=json.loads(row["metadata_json"] or "{}"),
        created_at=str(row["created_at"]),
    )
    payload = observation.to_dict()
    payload["source_trace"] = {
        "source_type": observation.source_type,
        "source_id": observation.source_id,
        "research_run_id": observation.research_run_id,
        "strategy_version_id": observation.strategy_version_id,
        "recommendation_result_id": observation.recommendation_result_id,
        "evidence_event_id": observation.evidence_event_id,
        "evidence_outcome_id": observation.evidence_outcome_id,
    }
    return payload


def _lifecycle_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence_id": int(row["evidence_id"]),
        "run_id": str(row["run_id"]),
        "strategy_id": str(row["strategy_id"]),
        "version_id": str(row["version_id"]),
        "action": str(row["action"]),
        "status": str(row["status"]),
        "reason": str(row["reason"]),
        "decision_snapshot": json.loads(row["decision_snapshot_json"] or "{}"),
        "created_at": str(row["created_at"]),
        "source_trace": {
            "run_id": str(row["run_id"]),
            "strategy_id": str(row["strategy_id"]),
            "version_id": str(row["version_id"]),
            "evidence_id": int(row["evidence_id"]),
        },
    }
