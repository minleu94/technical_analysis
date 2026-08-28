"""彙總目前程式各 readiness lane 的唯讀狀態。

這個 CLI 是「盤點入口」，不是新的 gate。它只讀取既有的 P0、Evidence、Paper、
Formal/ML、Runtime、Data Update history 與 performance artifact，將各 lane 的
阻塞原因與下一步放在同一份可機器讀取的報告中。沒有指定的外部 artifact 會明確
標成未觀察或等待外部輸入，不會掃描資料目錄、猜測替代路徑、回放歷史或建立
SQLite／目錄。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_module.paper_portfolio_readiness_service import PaperPortfolioReadinessService
from app_module.pre_v2_readiness_service import PreV2ReadinessService
from app_module.runtime_services.environment_readiness_service import (
    EnvironmentReadinessService,
)
from app_module.update_status_history import (
    MAX_STATUS_HISTORY_BYTES,
    read_update_status_history,
)
from data_module.source_acceptance_decision_registry import (
    parse_source_acceptance_decisions,
)
from scripts.inspect_ml_formal_input_readiness import build_readiness_report
from app_module.p0_source_control_center import P0SourceControlCenterService


READINESS_SCHEMA_VERSION = "program-readiness.v1"
DEFAULT_DATA_ROOT = "D:/Min/Python/Project/FA_Data"


@dataclass(frozen=True)
class ReadOnlyConfig:
    """只提供既有 read model 需要的路徑，避免建立 TWStockConfig 的副作用。"""

    data_root: Path
    output_root: Path
    db_file: Path
    research_run_db_file: Path


def inspect_program_readiness(
    *,
    data_root: str | Path,
    output_root: str | Path,
    p0_audit_path: str | Path | None = None,
    p0_decision_path: str | Path | None = None,
    evidence_db_path: str | Path | None = None,
    research_db_path: str | Path | None = None,
    approved_weekly_history_path: str | Path | None = None,
    weekly_collection_sidecar_path: str | Path | None = None,
    multi_day_record_path: str | Path | None = None,
    min_weekly_records: int = 3,
    min_dry_run_days: int = 3,
    training_as_of: str | None = None,
    technical_performance_path: str | Path | None = None,
    technical_batch_performance_path: str | Path | None = None,
    technical_write_performance_path: str | Path | None = None,
    technical_worker_acceptance_path: str | Path | None = None,
    broker_performance_path: str | Path | None = None,
    runtime_write_probe_path: str | Path | None = None,
    update_history_path: str | Path | None = None,
    update_status_path: str | Path | None = None,
    scheduled_task_status_path: str | Path | None = None,
) -> dict[str, Any]:
    """以既有服務建立整體唯讀 readiness report。"""

    resolved_data_root = _safe_resolve(Path(data_root))
    resolved_output_root = _safe_resolve(Path(output_root))
    resolved_evidence_db = _safe_resolve(
        Path(evidence_db_path)
        if evidence_db_path is not None
        else resolved_data_root / "sqlite" / "twstock.db"
    )
    resolved_research_db = _safe_resolve(
        Path(research_db_path)
        if research_db_path is not None
        else resolved_output_root / "research_runs" / "research_runs.db"
    )
    config = ReadOnlyConfig(
        data_root=resolved_data_root,
        output_root=resolved_output_root,
        db_file=resolved_evidence_db,
        research_run_db_file=resolved_research_db,
    )

    workstreams = {
        "p0": _inspect_p0_lane(
            _optional_path(p0_audit_path),
            _optional_path(p0_decision_path),
        ),
        "evidence": _inspect_evidence_lane(
            config,
            approved_weekly_history_path=_optional_path(approved_weekly_history_path),
            weekly_collection_sidecar_path=_optional_path(weekly_collection_sidecar_path),
            multi_day_record_path=_optional_path(multi_day_record_path),
            min_weekly_records=min_weekly_records,
            min_dry_run_days=min_dry_run_days,
        ),
        "paper": _inspect_paper_lane(resolved_output_root),
        "formal_ml": _inspect_formal_ml_lane(
            resolved_output_root,
            training_as_of=training_as_of,
        ),
        "runtime": _inspect_runtime_lane(
            resolved_data_root,
            resolved_output_root,
            _optional_path(runtime_write_probe_path),
        ),
        "update_history": _inspect_update_history_lane(
            _safe_resolve(
                Path(update_history_path)
                if update_history_path is not None
                else resolved_output_root
                / "scheduled"
                / "data_update_quick"
                / "history.jsonl"
            ),
            _safe_resolve(
                Path(update_status_path)
                if update_status_path is not None
                else resolved_output_root
                / "scheduled"
                / "data_update_quick"
                / "latest_status.json"
            ),
            _optional_path(scheduled_task_status_path),
        ),
        "performance": _inspect_performance_lane(
            _optional_path(technical_performance_path),
            _optional_path(technical_batch_performance_path),
            _optional_path(technical_write_performance_path),
            _optional_path(technical_worker_acceptance_path),
            _optional_path(broker_performance_path),
        ),
    }
    report: dict[str, Any] = {
        "schema_version": READINESS_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "status": _overall_status(workstreams),
        "workstreams": workstreams,
        "execution_order": _execution_order(workstreams),
        "boundary": {
            "read_only": True,
            "writes_allowed": False,
            "formal_oos_allowed": False,
            "production_scheduler_allowed": False,
            "broker_order_allowed": False,
            "historical_replay_backfill_allowed": False,
        },
        "inputs": {
            "data_root": str(resolved_data_root),
            "output_root": str(resolved_output_root),
            "evidence_db_path": str(resolved_evidence_db),
            "research_db_path": str(resolved_research_db),
            "training_as_of": training_as_of,
        },
        "safety": {
            "side_effect_free": True,
            "directories_created": False,
            "sqlite_connections": "query_only_or_existing_service_read_only",
            "network_requests": False,
            "secret_values_emitted": False,
        },
    }
    return report


def _inspect_p0_lane(
    audit_path: Path | None,
    decision_path: Path | None,
) -> dict[str, Any]:
    try:
        audit = _read_json_mapping(audit_path) if audit_path is not None else None
        decisions = (
            parse_source_acceptance_decisions(_read_json_value(decision_path))
            if decision_path is not None
            else ()
        )
        projection = P0SourceControlCenterService().build(
            candidate_audit=audit,
            decisions=decisions,
        ).to_dict()
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        return _lane(
            "action_required",
            blockers=("p0_projection_invalid",),
            next_actions=("修正明確指定的 P0 audit／decision JSON，再重新執行盤點。",),
            details={"error_type": type(error).__name__, "error": str(error)},
        )

    source_count = _as_int(projection.get("p0_source_count"), default=0)
    accepted = _as_int(projection.get("accepted_count"), default=0)
    limited = _as_int(projection.get("limited_count"), default=0)
    blockers = _string_list(projection.get("global_blockers"))
    actions: Sequence[str]
    if audit_path is None:
        status = "waiting_for_external_input"
        blockers.append("p0_live_audit_not_supplied")
        actions = (
            "提供最新的 P0 live audit JSON，保留每個來源的 publication／coverage／license lineage。",
            "再由具名 owner/reviewer 逐來源決定 license、use-case 與 downstream eligibility。",
        )
    elif accepted + limited < source_count:
        status = "action_required"
        blockers.append("p0_source_acceptance_pending")
        actions = (
            "由具名 owner/reviewer 審核尚未決定的來源；官方無資料、fallback rejected 與 network error 仍要保留原診斷。",
        )
    elif _as_int(projection.get("downstream_eligible_count"), default=0) < source_count:
        status = "partial"
        blockers.append("p0_downstream_eligibility_not_granted")
        actions = (
            "確認每筆 decision 的 license scope、PIT／publication evidence 與 downstream eligibility，再由治理流程升級。",
        )
    else:
        status = "ready"
        actions = ("保留 live audit 與 owner packet hash，等待下一個自然排程週期持續觀察。",)
    return _lane(
        status,
        blockers=tuple(blockers),
        next_actions=actions,
        external_input_required=status in {"waiting_for_external_input", "action_required"},
        details={
            "audit_path": str(audit_path) if audit_path is not None else None,
            "decision_path": str(decision_path) if decision_path is not None else None,
            "source_count": source_count,
            "accepted_count": accepted,
            "limited_count": limited,
            "projection": projection,
        },
    )


def _inspect_evidence_lane(
    config: ReadOnlyConfig,
    *,
    approved_weekly_history_path: Path | None,
    weekly_collection_sidecar_path: Path | None,
    multi_day_record_path: Path | None,
    min_weekly_records: int,
    min_dry_run_days: int,
) -> dict[str, Any]:
    try:
        report = PreV2ReadinessService(
            config,
            evidence_db_path=config.db_file,
            research_db_path=config.research_run_db_file,
            approved_weekly_history_projection_path=approved_weekly_history_path,
            weekly_collection_sidecar_path=weekly_collection_sidecar_path,
        ).inspect(
            multi_day_record_path=multi_day_record_path,
            min_weekly_records=min_weekly_records,
            min_dry_run_days=min_dry_run_days,
        )
        payload = report.to_dict()
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        return _lane(
            "action_required",
            blockers=("evidence_readiness_inspection_failed",),
            next_actions=("檢查 Evidence／Research DB 與明確 projection 路徑，再重跑唯讀盤點。",),
            details={"error_type": type(error).__name__, "error": str(error)},
        )

    blockers: list[str] = []
    actions: list[str] = []
    for item in payload.get("items", []):
        if not isinstance(item, Mapping):
            continue
        blockers.extend(_string_list(item.get("blocking_reasons")))
        actions.extend(_string_list(item.get("next_actions")))
    if payload.get("formal_credit_authorized") is not True:
        blockers.append("formal_credit_not_authorized")
    overall = str(payload.get("overall_status") or "unknown")
    if overall == "action_required":
        status = "action_required"
    elif overall == "waiting_for_time":
        status = "waiting_for_external_input"
    else:
        # Pre-V2 ready 只表示可討論，並不授予 Formal credit。
        status = "partial"
    if not actions:
        actions.append("持續累積自然 weekly／multi-day evidence；人工核准前不計 Formal credit。")
    return _lane(
        status,
        blockers=tuple(blockers),
        next_actions=tuple(actions),
        external_input_required=status != "partial" or payload.get("formal_credit_authorized") is not True,
        details={"readiness": payload},
    )


def _inspect_paper_lane(output_root: Path) -> dict[str, Any]:
    try:
        result = PaperPortfolioReadinessService(output_root=output_root).inspect()
        payload = result.to_dict()
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        return _lane(
            "action_required",
            blockers=("paper_readiness_inspection_failed",),
            next_actions=("檢查 Paper output 的明確路徑與 schema，再重跑唯讀盤點。",),
            details={"error_type": type(error).__name__, "error": str(error)},
        )

    blockers = _string_list(payload.get("blockers"))
    actions: list[str] = []
    if str(payload.get("cost_ledger_status")) != "ready":
        actions.append("以受控的真實或人工覆核 fills CSV 補齊 Decimal cost、fill status、turnover 與 execution gap，再 atomic append Paper Ledger。")
    if _as_int(payload.get("benchmark_observation_count"), default=0) < 2:
        actions.append("持續建立與 Paper universe／現金政策對齊的 Equal Weight benchmark observations。")
    if not actions:
        actions.append("保留 Paper／benchmark／cost ledger hash，等待下一個自然週期。")
    raw_status = str(payload.get("status") or "not_configured")
    status = "ready" if raw_status == "ready" and payload.get("weekly_report_status") == "ready" else (
        "partial" if raw_status in {"ready", "partial", "degraded"} else "action_required"
    )
    if payload.get("weekly_report_status") != "ready":
        blockers.append("paper_weekly_report_not_computable")
    return _lane(
        status,
        blockers=tuple(blockers),
        next_actions=tuple(actions),
        external_input_required=status == "action_required" or status == "partial",
        details={"readiness": payload},
    )


def _inspect_formal_ml_lane(
    output_root: Path,
    *,
    training_as_of: str | None,
) -> dict[str, Any]:
    if not training_as_of:
        return _lane(
            "waiting_for_external_input",
            blockers=("training_as_of_required",),
            next_actions=("明確指定 training_as_of，再檢查三項 owner-controlled formal input；不得由 inspector 猜日期。",),
            details={"output_root": str(output_root), "readiness": None},
        )
    try:
        payload = build_readiness_report(
            output_root=output_root,
            training_as_of=training_as_of,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        return _lane(
            "action_required",
            blockers=("formal_ml_readiness_inspection_failed",),
            next_actions=("確認 output root 與 training_as_of，再重跑 formal input readiness。",),
            details={"error_type": type(error).__name__, "error": str(error)},
        )

    blockers = [
        f"formal_input_not_ready:{item.get('input')}"
        for item in payload.get("inputs", [])
        if isinstance(item, Mapping) and item.get("state") != "ready"
    ]
    if payload.get("formal_oos_allowed") is not True:
        blockers.append("formal_oos_disabled")
    ready_count = _as_int(payload.get("ready_input_count"), default=0)
    input_count = _as_int(payload.get("input_count"), default=3)
    status = "partial" if ready_count == input_count else "action_required"
    next_action = str(payload.get("next_action") or "publish all three owner-controlled formal inputs; no partial retrain is permitted")
    return _lane(
        status,
        blockers=tuple(blockers),
        next_actions=(next_action,),
        external_input_required=status != "ready",
        details={"readiness": payload},
    )


def _inspect_runtime_lane(
    data_root: Path,
    output_root: Path,
    write_probe_path: Path | None = None,
) -> dict[str, Any]:
    try:
        snapshot = EnvironmentReadinessService(data_root, output_root).get_snapshot()
        payload = {
            "overall_state": snapshot.overall_state,
            "observed_at": snapshot.observed_at.isoformat(timespec="seconds"),
            "data_root": snapshot.data_root,
            "output_root": snapshot.output_root,
            "log_root": snapshot.log_root,
            "research_registry": snapshot.research_registry,
            "side_effect_free": snapshot.side_effect_free,
            "write_probe": snapshot.write_probe,
            "diagnostics": list(snapshot.diagnostics),
            "paths": [
                {
                    "key": item.key,
                    "label": item.label,
                    "path": item.path,
                    "kind": item.kind,
                    "exists": item.exists,
                    "parent_exists": item.parent_exists,
                    "readable": item.readable,
                    "writable": item.writable,
                    "requires_write": item.requires_write,
                    "status": item.status,
                    "diagnostic": item.diagnostic,
                }
                for item in snapshot.paths
            ],
        }
    except (OSError, TypeError, ValueError) as error:
        return _lane(
            "action_required",
            blockers=("runtime_readiness_inspection_failed",),
            next_actions=("檢查 DATA_ROOT／OUTPUT_ROOT 的可見性，再重跑 Runtime readiness。",),
            details={"error_type": type(error).__name__, "error": str(error)},
        )
    raw_status = str(payload.get("overall_state") or "unknown")
    status = "ready" if raw_status == "ready" else "action_required"
    blockers = _string_list(payload.get("diagnostics"))
    details: dict[str, Any] = {"readiness": payload}
    staging_probe: Mapping[str, Any] | None = None
    if write_probe_path is not None:
        try:
            staging_probe = _read_json_mapping(write_probe_path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            blockers.append(f"runtime_write_probe_invalid:{type(error).__name__}")
        if staging_probe is None:
            blockers.append("runtime_write_probe_not_supplied_or_missing")
        else:
            details["staging_write_probe"] = dict(staging_probe)
            probe_passed = (
                staging_probe.get("status") == "passed"
                and staging_probe.get("file_write_succeeded") is True
                and staging_probe.get("sqlite_write_succeeded") is True
                and staging_probe.get("registry_transaction_succeeded") is True
                and staging_probe.get("cleanup_succeeded") is True
            )
            if not probe_passed:
                blockers.append("runtime_staging_write_probe_failed")
            elif status != "ready":
                status = "partial"
    if staging_probe is not None and staging_probe.get("status") == "passed":
        actions = (
            "Runtime staging 的實際 Registry transaction／rollback 已通過；正式 config.log／Registry ACL 仍依目前 host 權限顯示，需由 owner 在正式環境確認。",
        )
    else:
        actions = (
            "Runtime host 已可觀察；若要證明實際寫入，另在非正式 staging 目錄明確執行 write probe，不能把 os.access hint 當成正式 Registry transaction。",
        )
    return _lane(status, blockers=tuple(blockers), next_actions=actions, details=details)


def _inspect_update_history_lane(
    history_path: Path,
    latest_status_path: Path,
    scheduled_task_status_path: Path | None = None,
) -> dict[str, Any]:
    history = read_update_status_history(history_path)
    diagnostics = _string_list(history.get("diagnostics"))
    records = [item for item in history.get("records", []) if isinstance(item, Mapping)]
    latest = history.get("latest") if isinstance(history.get("latest"), Mapping) else None
    latest_status = _read_optional_json_mapping(latest_status_path)
    scheduled_status = (
        _read_optional_json_mapping(scheduled_task_status_path)
        if scheduled_task_status_path is not None
        else None
    )
    if scheduled_task_status_path is not None and scheduled_status is None:
        diagnostics.append("scheduled_task_status_missing_or_invalid")
    elif scheduled_status is not None:
        available_count = _as_int(scheduled_status.get("available_count"), default=-1)
        task_count = _as_int(scheduled_status.get("task_count"), default=-1)
        if scheduled_status.get("all_available") is not True:
            diagnostics.append(
                "scheduled_tasks_missing_or_unavailable:"
                f"{max(available_count, 0)}/{max(task_count, 0)}"
            )
    if latest_status is not None and latest is not None:
        latest_status_run = str(latest_status.get("run_id") or "").strip()
        latest_history_run = str(latest.get("run_id") or "").strip()
        if latest_status_run and latest_history_run and latest_status_run != latest_history_run:
            diagnostics.append("latest_status_run_not_equal_to_history_latest_run")
    elif latest_status is not None and latest is None:
        diagnostics.append("latest_status_present_history_has_no_record")
    elif latest_status is None and latest is not None:
        diagnostics.append("history_present_latest_status_missing")

    size_bytes = 0
    try:
        if history_path.is_file():
            size_bytes = history_path.stat().st_size
    except OSError as error:
        diagnostics.append(f"history_size_unavailable:{type(error).__name__}")
    terminal_count = sum(
        1 for record in records if str(record.get("status") or "").lower() != "running"
    )
    unique_run_count = len({str(record.get("run_id")) for record in records if record.get("run_id")})
    details = {
        "history_path": str(history_path),
        "latest_status_path": str(latest_status_path),
        "history": history,
        "latest_status": latest_status,
        "size_bytes": size_bytes,
        "max_bytes": MAX_STATUS_HISTORY_BYTES,
        "retention_status": (
            "over_limit"
            if size_bytes > MAX_STATUS_HISTORY_BYTES
            else "near_limit"
            if size_bytes * 100 >= MAX_STATUS_HISTORY_BYTES * 80
            else "within_limit"
        ),
        "terminal_record_count": terminal_count,
        "unique_run_count": unique_run_count,
        "scheduled_task_status_path": (
            str(scheduled_task_status_path) if scheduled_task_status_path is not None else None
        ),
        "scheduled_task_status": scheduled_status,
    }
    history_status = str(history.get("status") or "unknown")
    blockers: list[str] = list(diagnostics)
    scheduler_missing = any(
        item.startswith("scheduled_tasks_missing_or_unavailable:")
        for item in diagnostics
    )
    if scheduler_missing:
        # 排程未註冊是可立即處理的 host 狀態，不應被誤標成單純等待
        # 下一次自然週期；即使 history 尚未建立，下一步也是先註冊 task。
        status = "action_required"
    elif history_status in {"invalid", "missing"}:
        status = "action_required" if history_status == "invalid" else "waiting_for_external_input"
    elif history_status in {"not_configured", "empty"}:
        status = "waiting_for_external_input"
        blockers.append("update_history_not_observed")
    elif diagnostics:
        status = "action_required"
    elif terminal_count == 0:
        status = "waiting_for_external_input"
        blockers.append("update_history_has_no_terminal_attempt")
    else:
        status = "ready"
    if status == "action_required":
        if scheduler_missing:
            actions = (
                "由 owner 在正確 Windows 帳號下受控重新註冊 13 個 baldr task，再觀察下一次真實 running／terminal history；不可用舊 latest status 回填。",
            )
        else:
            actions = ("修正 history JSONL／latest status 的 schema 或 run identity；禁止用舊 latest status 回填 history。",)
    elif status == "waiting_for_external_input":
        actions = ("等待下一次真實 Data Update 排程自然產生 running 與 terminal history，再觀察 retention 與 UI live refresh。",)
    else:
        actions = ("以真實排程持續觀察成功、官方無資料、fallback、schema mismatch、network failure 與資料落後等狀態的顯示與 bounded retention。",)
    return _lane(
        status,
        blockers=tuple(blockers),
        next_actions=actions,
        external_input_required=status != "ready",
        details=details,
    )


def _inspect_performance_lane(
    technical_path: Path | None,
    technical_batch_path: Path | None,
    technical_write_path: Path | None,
    technical_worker_path: Path | None,
    broker_path: Path | None,
) -> dict[str, Any]:
    artifacts: dict[str, Any] = {}
    blockers: list[str] = []
    if (
        technical_path is None
        and technical_batch_path is None
        and technical_write_path is None
        and technical_worker_path is None
    ):
        blockers.append("technical_performance_baseline_not_supplied")
    if broker_path is None:
        blockers.append("broker_performance_baseline_not_supplied")
    for label, path in (
        ("technical", technical_path),
        ("technical_batch", technical_batch_path),
        ("technical_write", technical_write_path),
        ("technical_worker", technical_worker_path),
        ("broker", broker_path),
    ):
        if path is None:
            artifacts[label] = None
            continue
        try:
            artifacts[label] = _read_json_mapping(path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            blockers.append(f"{label}_performance_baseline_invalid")
            artifacts[label] = {"path": str(path), "error_type": type(error).__name__, "error": str(error)}
    if not any(isinstance(value, Mapping) for value in artifacts.values()):
        return _lane(
            "waiting_for_external_input",
            blockers=tuple(blockers),
            next_actions=("先提供 read-only latency baseline，再做 full-batch CPU／CSV write／SQLite contention measurement；在此之前不要啟用 worker。",),
            details={
                "technical_path": str(technical_path) if technical_path else None,
                "technical_batch_path": str(technical_batch_path) if technical_batch_path else None,
                "technical_write_path": str(technical_write_path) if technical_write_path else None,
                "technical_worker_path": str(technical_worker_path) if technical_worker_path else None,
                "broker_path": str(broker_path) if broker_path else None,
                "artifacts": artifacts,
            },
        )
    for label, payload in artifacts.items():
        if not isinstance(payload, Mapping):
            continue
        production_write_attempted = payload.get("production_write_attempted") is True
        unscoped_write_attempted = (
            payload.get("write_attempted") is True
            and payload.get("staging_write_attempted") is not True
        )
        if production_write_attempted or unscoped_write_attempted:
            blockers.append(f"{label}_performance_probe_wrote_data")
        if payload.get("production_sqlite_write_attempted") is True:
            blockers.append(f"{label}_performance_probe_wrote_production_sqlite")
        if label == "technical_write":
            if payload.get("staging_write_attempted") is not True:
                blockers.append("technical_write_staging_write_not_confirmed")
            if payload.get("cleanup_succeeded") is False:
                blockers.append("technical_write_staging_cleanup_failed")
        if label == "technical_worker":
            checks = payload.get("checks")
            checks_passed = isinstance(checks, Mapping) and bool(checks) and all(
                value is True for value in checks.values()
            )
            worker_contract = (
                payload.get("synthetic_parallelism_enabled") is True
                or payload.get("staging_process_pool_enabled") is True
            )
            if (
                payload.get("status") != "measured"
                or payload.get("production_worker_enabled") is not False
                or not worker_contract
                or not checks_passed
            ):
                blockers.append("technical_bounded_worker_acceptance_invalid")
        if payload.get("parallelism_enabled") is True:
            blockers.append(f"{label}_parallelism_claim_requires_single_writer_review")
    technical_worker_payload = artifacts.get("technical_worker")
    if not (
        isinstance(technical_worker_payload, Mapping)
        and technical_worker_payload.get("status") == "measured"
    ):
        blockers.append("technical_bounded_worker_acceptance_not_completed")
    elif technical_worker_payload.get("staging_process_pool_enabled") is not True:
        blockers.append("technical_real_process_pool_not_completed")
    else:
        for recovery_key, blocker in (
            ("crash_recovery", "technical_worker_crash_recovery_not_completed"),
            ("cancellation", "technical_worker_cancel_acceptance_not_completed"),
        ):
            recovery_payload = technical_worker_payload.get(recovery_key)
            if not (
                isinstance(recovery_payload, Mapping)
                and recovery_payload.get("status") == "measured"
            ):
                blockers.append(blocker)
        integration_payload = technical_worker_payload.get(
            "production_single_writer_integration"
        )
        if not (
            isinstance(integration_payload, Mapping)
            and integration_payload.get("status") == "staging_measured"
        ):
            blockers.append("technical_production_single_writer_integration_not_completed")
        else:
            # The product code is now wired behind an explicit feature flag,
            # but this artifact only exercised an isolated staging root. Keep
            # the remaining gate precise: production backup/rollback and the
            # owner-approved canary have not happened yet.
            blockers.append("technical_production_single_writer_canary_not_completed")
    # No broker worker artifact is accepted as a proxy for technical worker proof.
    broker_payload = artifacts.get("broker")
    broker_contract_raw: object = (
        broker_payload.get("bounded_fetch_acceptance")
        if isinstance(broker_payload, Mapping)
        else None
    )
    if not isinstance(broker_payload, Mapping) or not isinstance(broker_contract_raw, Mapping):
        blockers.append("broker_bounded_fetch_acceptance_not_completed")
    else:
        broker_contract = broker_contract_raw
        if broker_contract.get("status") != "measured":
            blockers.append("broker_bounded_fetch_acceptance_not_completed")
        broker_checks = broker_contract.get("checks")
        broker_checks_passed = isinstance(broker_checks, Mapping) and bool(broker_checks) and all(
            value is True for value in broker_checks.values()
        )
        if (
            broker_contract.get("status") != "measured"
            or broker_payload.get("staging_fetch_pool_enabled") is not True
            or broker_payload.get("production_fetch_pool_enabled") is not False
            or broker_payload.get("production_write_attempted") is not False
            or not broker_checks_passed
        ):
            blockers.append("broker_bounded_fetch_acceptance_invalid")
        if broker_payload.get("network_enabled") is not True:
            blockers.append("broker_real_http_canary_not_completed")
    return _lane(
        "partial",
        blockers=tuple(blockers),
        next_actions=("已具備 technical full-batch、real staging bounded worker、worker recovery／取消與 feature-flag wiring；接著由 owner 核准 backup／rollback 後做單次 production canary，再允許 broker canary。",),
        external_input_required=True,
        details={
            "technical_path": str(technical_path) if technical_path else None,
            "technical_batch_path": str(technical_batch_path) if technical_batch_path else None,
            "technical_write_path": str(technical_write_path) if technical_write_path else None,
            "technical_worker_path": str(technical_worker_path) if technical_worker_path else None,
            "broker_path": str(broker_path) if broker_path else None,
            "artifacts": artifacts,
            "parallelism_enabled": False,
            "single_writer_required": True,
        },
    )


def _execution_order(workstreams: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    ordered = (
        (1, "p0", "先累積 live P0 audit／fallback lineage，再完成具名 owner decision。"),
        (2, "evidence", "持續累積真實週期，並由 owner/reviewer 審核 weekly history；projection 不授予 Formal credit。"),
        (3, "paper", "補真實 fills／partial-fill／reject／override／Decimal cost／execution gap，再計算成本後 weekly。"),
        (4, "formal_ml", "由 owner 發布當前三項 formal inputs；禁止用 prospective 或歷史 shadow artifact 冒充。"),
        (5, "runtime", "先確認 staging transaction 與正式 config／Registry ACL；staging 證據不能取代正式環境權限。"),
        (6, "performance", "已量測 full batch、isolated writer contention、real staging worker recovery／取消與 feature-flag wiring；接著由 owner 核准 backup／rollback 後做單次 production canary，再驗收 broker canary。"),
        (7, "update_history", "等真實排程產生 history，執行 live refresh、retention 與狀態投影 QA。"),
    )
    result: list[dict[str, Any]] = []
    for order, key, fallback in ordered:
        lane = workstreams.get(key, {})
        actions = _string_list(lane.get("next_actions"))
        result.append(
            {
                "order": order,
                "lane": key,
                "status": lane.get("status", "unknown"),
                "action": actions[0] if actions else fallback,
                "blockers": _string_list(lane.get("blockers")),
            }
        )
    return result


def _overall_status(workstreams: Mapping[str, Mapping[str, Any]]) -> str:
    statuses = {str(item.get("status")) for item in workstreams.values()}
    if "action_required" in statuses:
        return "action_required"
    if statuses and statuses == {"ready"}:
        return "ready"
    return "partial"


def _lane(
    status: str,
    *,
    blockers: Sequence[str] = (),
    next_actions: Sequence[str] = (),
    details: Mapping[str, Any] | None = None,
    external_input_required: bool = False,
) -> dict[str, Any]:
    return {
        "status": status,
        "blockers": list(dict.fromkeys(str(item) for item in blockers if str(item))),
        "next_actions": list(dict.fromkeys(str(item) for item in next_actions if str(item))),
        "external_input_required": external_input_required,
        "details": dict(details or {}),
    }


def _read_json_value(path: Path | None) -> Any:
    if path is None:
        raise ValueError("JSON path is required")
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json_mapping(path: Path | None) -> Mapping[str, Any]:
    payload = _read_json_value(path)
    if not isinstance(payload, Mapping):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return payload


def _read_optional_json_mapping(path: Path) -> Mapping[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return _read_json_mapping(path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _optional_path(value: str | Path | None) -> Path | None:
    return _safe_resolve(Path(value)) if value is not None else None


def _safe_resolve(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return path


def _as_int(value: Any, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if str(item)]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--p0-audit-json", type=Path)
    parser.add_argument("--p0-decision-json", type=Path)
    parser.add_argument("--evidence-db-path", type=Path)
    parser.add_argument("--research-db-path", type=Path)
    parser.add_argument("--approved-weekly-history-projection", type=Path)
    parser.add_argument(
        "--weekly-collection-sidecar",
        type=Path,
        help="明確指定 V2.2 pending weekly collection sidecar；只讀，不授予 Gate credit",
    )
    parser.add_argument("--multi-day-record-path", type=Path)
    parser.add_argument("--min-weekly-records", type=int, default=3)
    parser.add_argument("--min-dry-run-days", type=int, default=3)
    parser.add_argument("--training-as-of")
    parser.add_argument("--technical-performance-baseline", type=Path)
    parser.add_argument("--technical-batch-performance-baseline", type=Path)
    parser.add_argument("--technical-write-performance-baseline", type=Path)
    parser.add_argument("--technical-worker-acceptance-baseline", type=Path)
    parser.add_argument("--broker-performance-baseline", type=Path)
    parser.add_argument("--runtime-write-probe", type=Path)
    parser.add_argument("--update-history-path", type=Path)
    parser.add_argument("--update-status-path", type=Path)
    parser.add_argument(
        "--scheduled-task-status",
        type=Path,
        help="唯讀 schtasks 註冊摘要 JSON；缺少時不會掃描或修改 task",
    )
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", type=Path, help="可選的報告輸出路徑；不指定則只輸出 stdout。")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    args = build_parser().parse_args(argv)
    data_root = args.data_root or Path(os.environ.get("DATA_ROOT", DEFAULT_DATA_ROOT))
    output_root = args.output_root or Path(
        os.environ.get("OUTPUT_ROOT", str(data_root / "output"))
    )
    report = inspect_program_readiness(
        data_root=data_root,
        output_root=output_root,
        p0_audit_path=args.p0_audit_json,
        p0_decision_path=args.p0_decision_json,
        evidence_db_path=args.evidence_db_path,
        research_db_path=args.research_db_path,
        approved_weekly_history_path=args.approved_weekly_history_projection,
        weekly_collection_sidecar_path=args.weekly_collection_sidecar,
        multi_day_record_path=args.multi_day_record_path,
        min_weekly_records=args.min_weekly_records,
        min_dry_run_days=args.min_dry_run_days,
        training_as_of=args.training_as_of,
        technical_performance_path=args.technical_performance_baseline,
        technical_batch_performance_path=args.technical_batch_performance_baseline,
        technical_write_performance_path=args.technical_write_performance_baseline,
        technical_worker_acceptance_path=args.technical_worker_acceptance_baseline,
        broker_performance_path=args.broker_performance_baseline,
        runtime_write_probe_path=args.runtime_write_probe,
        update_history_path=args.update_history_path,
        update_status_path=args.update_status_path,
        scheduled_task_status_path=args.scheduled_task_status,
    )
    rendered = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.format == "json"
        else render_markdown(report)
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if report["status"] in {"ready", "partial"} else 2


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Program Readiness",
        "",
        f"- status: `{report.get('status', 'unknown')}`",
        f"- generated_at: `{report.get('generated_at', 'unknown')}`",
        "",
        "| 工作流 | 狀態 | 外部輸入 | 主要 blockers | 下一步 |",
        "|---|---|---:|---|---|",
    ]
    workstreams = report.get("workstreams", {})
    if isinstance(workstreams, Mapping):
        for key, lane in workstreams.items():
            if not isinstance(lane, Mapping):
                continue
            blockers = "；".join(_string_list(lane.get("blockers"))) or "無"
            actions = "；".join(_string_list(lane.get("next_actions"))) or "無"
            lines.append(
                f"| `{key}` | `{lane.get('status', 'unknown')}` | "
                f"`{str(lane.get('external_input_required', False)).lower()}` | "
                f"{blockers} | {actions} |"
            )
    lines.extend(["", "## 依序推進", ""])
    for item in report.get("execution_order", []):
        if not isinstance(item, Mapping):
            continue
        lines.append(
            f"{item.get('order')}. `{item.get('lane')}`／`{item.get('status')}`：{item.get('action')}"
        )
    lines.extend(
        [
            "",
            "## 安全邊界",
            "",
            "- 此報告只讀取明確輸入；不建立目錄、不寫正式 SQLite、不發網路請求、不啟用 scheduler／broker。",
            "- `partial` 或 `action_required` 不代表可以用 replay、prospective、snapshot 或手動交易資料偽造缺件。",
        ]
    )
    return "\n".join(lines) + "\n"


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue


if __name__ == "__main__":
    raise SystemExit(main())
