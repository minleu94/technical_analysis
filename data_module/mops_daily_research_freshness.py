"""MOPS 每日研究用財報發布 Freshness、Outage、Revision 診斷與 Sanitized Projection 模組。

本模組僅供每日人工執行、唯讀研究用途，產出位於顯式 TEMP／shadow root，嚴禁寫入正式 DB 或 FA_Data。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from data_module.config import TWStockConfig
from data_module.mops_ezsearch_statement_availability import (
    MOPS_EZSEARCH_URL,
    MOPS_MARKETS,
    MOPS_STATEMENT_AVAILABILITY_SOURCE,
    MOPS_STATEMENT_AVAILABILITY_SOURCE_VERSION,
    MOPS_STATEMENT_ITEMS,
    MOPSQueryResult,
    build_statement_availability_artifact,
    query_mops_ezsearch,
)
from development_module.output_guard import validate_development_output_root

DIAGNOSTICS_SCHEMA_VERSION = "mops-daily-research-freshness-diagnostics.v1"
SANITIZED_PROJECTION_SCHEMA_VERSION = "mops-sanitized-research-projection.v1"
MAX_QUERY_WINDOW_DAYS = 31
REQUIRED_DISABLED_APPLY_FLAGS = {
    "apply_to_scoring": False,
    "apply_to_recommendation": False,
    "apply_to_portfolio": False,
    "apply_to_exit": False,
}


@dataclass(frozen=True)
class DiagnosticsRunResult:
    run_id: str
    run_status: str
    artifact_path: Path
    artifact_sha256: str
    sanitized_projection_path: Path
    sanitized_projection_sha256: str
    summary: dict[str, Any]
    exit_code: int


def run_mops_daily_freshness_diagnostics(
    *,
    start_date: date,
    end_date: date,
    output_root: Path,
    session: Any | None = None,
    query_results: Sequence[MOPSQueryResult] | None = None,
    prior_artifact_path: Path | None = None,
    expected_through_date: date | None = None,
    captured_at: str | None = None,
    live_readonly: bool = False,
    timeout_seconds: int = 30,
) -> DiagnosticsRunResult:
    """執行 MOPS daily freshness 診斷與 sanitized projection 產出。"""
    config = TWStockConfig()
    safe_root = validate_development_output_root(
        output_root,
        data_root=Path(config.data_root),
        formal_db=Path(config.db_file),
    )
    _verify_no_symlink_escape(safe_root)

    runs_dir = safe_root / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    captured_time = (
        _parse_iso_timestamp(captured_at)
        if captured_at
        else datetime.now(timezone.utc)
    )
    run_id_prefix = captured_time.strftime("%Y%m%dT%H%M%SZ")

    # 1. 檢查 query window
    if end_date < start_date:
        return _write_failure_run(
            safe_root=safe_root,
            runs_dir=runs_dir,
            run_id=f"mops-daily-research-{run_id_prefix}-invalid-window",
            captured_time=captured_time,
            start_date=start_date,
            end_date=end_date,
            reason="end_date must not be earlier than start_date",
        )

    if (end_date - start_date).days >= MAX_QUERY_WINDOW_DAYS:
        return _write_failure_run(
            safe_root=safe_root,
            runs_dir=runs_dir,
            run_id=f"mops-daily-research-{run_id_prefix}-range-exceeded",
            captured_time=captured_time,
            start_date=start_date,
            end_date=end_date,
            reason=f"query range exceeds maximum allowed limit of {MAX_QUERY_WINDOW_DAYS} days",
        )

    # 2. 抓取 / 取得查詢結果
    actual_results: list[MOPSQueryResult] = []
    outage_reason: str | None = None

    if query_results is not None:
        actual_results = list(query_results)
    elif live_readonly:
        if session is None:
            import requests
            session = requests.Session()
        try:
            for market in MOPS_MARKETS:
                for item in sorted(MOPS_STATEMENT_ITEMS):
                    res = query_mops_ezsearch(
                        session,
                        market=market,
                        announcement_item=item,
                        start_date=start_date,
                        end_date=end_date,
                        timeout_seconds=timeout_seconds,
                    )
                    actual_results.append(res)
        except Exception as exc:
            outage_reason = f"live query failed: {exc}"
    else:
        outage_reason = "neither live_readonly nor query_results supplied for offline run"

    if outage_reason is not None:
        return _write_failure_run(
            safe_root=safe_root,
            runs_dir=runs_dir,
            run_id=f"mops-daily-research-{run_id_prefix}-outage",
            captured_time=captured_time,
            start_date=start_date,
            end_date=end_date,
            reason=outage_reason,
        )

    # 3. 檢查矩陣完整性 (4 markets x 4 items = 16 queries)
    expected_matrix_count = len(MOPS_MARKETS) * len(MOPS_STATEMENT_ITEMS)
    matrix_complete = len(actual_results) == expected_matrix_count and all(
        res.market in MOPS_MARKETS and res.announcement_item in MOPS_STATEMENT_ITEMS
        for res in actual_results
    )

    # 4. 建立基礎 Availability Artifact 並驗證 row conservation
    try:
        availability_artifact = build_statement_availability_artifact(
            actual_results,
            start_date=start_date,
            end_date=end_date,
            captured_at=captured_time.isoformat(),
        )
    except Exception as exc:
        return _write_failure_run(
            safe_root=safe_root,
            runs_dir=runs_dir,
            run_id=f"mops-daily-research-{run_id_prefix}-parse-failure",
            captured_time=captured_time,
            start_date=start_date,
            end_date=end_date,
            reason=f"failed to build statement availability artifact: {exc}",
        )

    manifest_raw_rows = sum(
        m["row_count"] for m in availability_artifact.get("query_manifest", [])
    )
    quality = availability_artifact["quality_summary"]
    event_count = quality["event_count"]
    duplicate_count = quality["duplicate_event_count"]
    invalid_count = quality["invalid_event_count"]
    future_count = quality["future_event_count"]
    projection_count = quality["projection_count"]

    # Row Conservation 檢查: manifest_raw_rows == event_count + duplicate_count + invalid_count + future_count
    if manifest_raw_rows != (event_count + duplicate_count + invalid_count + future_count):
        return _write_failure_run(
            safe_root=safe_root,
            runs_dir=runs_dir,
            run_id=f"mops-daily-research-{run_id_prefix}-conservation-violation",
            captured_time=captured_time,
            start_date=start_date,
            end_date=end_date,
            reason=(
                f"row conservation math mismatch: manifest rows {manifest_raw_rows} != "
                f"events ({event_count}) + duplicates ({duplicate_count}) + invalids ({invalid_count}) + futures ({future_count})"
            ),
        )

    if projection_count > event_count:
        return _write_failure_run(
            safe_root=safe_root,
            runs_dir=runs_dir,
            run_id=f"mops-daily-research-{run_id_prefix}-projection-overflow",
            captured_time=captured_time,
            start_date=start_date,
            end_date=end_date,
            reason=f"projection_count ({projection_count}) exceeds event_count ({event_count})",
        )

    # 5. 判斷 Freshness / Status 語意
    if not matrix_complete:
        run_status = "degraded"
        degraded_reason = f"partial query matrix: {len(actual_results)}/{expected_matrix_count} queries completed"
    elif event_count == 0:
        run_status = "observed_empty"
        degraded_reason = None
    else:
        run_status = "observed"
        degraded_reason = None

    if expected_through_date is not None and end_date < expected_through_date:
        run_status = "stale"
        degraded_reason = f"artifact query end_date ({end_date.isoformat()}) is earlier than expected_through ({expected_through_date.isoformat()})"

    # 6. 比對 Prior Artifact (Comparison)
    comparison_summary = _compare_with_prior(
        current_rows=availability_artifact["rows"],
        current_start_date=start_date,
        current_end_date=end_date,
        prior_artifact_path=prior_artifact_path,
    )

    run_id = f"mops-daily-research-{run_id_prefix}-{sha256(json.dumps(availability_artifact, sort_keys=True).encode()).hexdigest()[:8]}"

    # 7. 組裝 Immutable Run Diagnostic Artifact
    run_artifact = {
        "schema_version": DIAGNOSTICS_SCHEMA_VERSION,
        "run_id": run_id,
        "source_id": MOPS_STATEMENT_AVAILABILITY_SOURCE,
        "source_version": MOPS_STATEMENT_AVAILABILITY_SOURCE_VERSION,
        "source_url": MOPS_EZSEARCH_URL,
        "captured_at": captured_time.isoformat(),
        "query_start_date": start_date.isoformat(),
        "query_end_date": end_date.isoformat(),
        "expected_through_date": expected_through_date.isoformat() if expected_through_date else None,
        "query_matrix_complete": matrix_complete,
        "run_status": run_status,
        "outage_reason": None,
        "degraded_reason": degraded_reason,
        "quality_summary": {
            "manifest_raw_row_count": manifest_raw_rows,
            "event_count": event_count,
            "exact_duplicate_event_count": duplicate_count,
            "invalid_event_count": invalid_count,
            "future_event_count": future_count,
            "projection_count": projection_count,
        },
        "safety_boundary": {
            "research_only": True,
            "read_only_source": True,
            "formal_oos_allowed": False,
            "formal_credit_authorized": False,
            "production_scheduler_allowed": False,
            "production_blend_alpha_bp": 0,
            "fubon_shadow_usable": True,
            "fubon_formal_credit_allowed": False,
        },
        "query_manifest": availability_artifact.get("query_manifest", []),
        "rows": availability_artifact.get("rows", []),
        "availability_projection": availability_artifact.get("availability_projection", []),
        "comparison": comparison_summary,
    }

    # 8. 寫入 Immutable Run Artifact
    artifact_bytes = (
        json.dumps(run_artifact, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    artifact_sha256 = sha256(artifact_bytes).hexdigest()
    run_artifact_file = runs_dir / f"{run_id}.json"
    _safe_write_bytes(run_artifact_file, artifact_bytes)

    # 9. 建立 Sanitized Projection 內容 (Research Console 相容)
    multi_day_ready = (
        comparison_summary["comparison_status"] == "comparable"
        and comparison_summary["prior_artifact_hash"] is not None
    )

    sanitized_projection = {
        "schema_version": SANITIZED_PROJECTION_SCHEMA_VERSION,
        "source": MOPS_STATEMENT_AVAILABILITY_SOURCE,
        "p0_lane": "pit.quarterly_financials",
        "source_decision": "decision:mops.ezsearch.statement_publication:20260727-r1",
        "acceptance": "limited",
        "allowed_use": "research_pit_statement_availability, development_shadow_projection",
        "formal_allowed": False,
        "production_allowed": False,
        "current_run_status": run_status,
        "query_date_window": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
        "market_item_coverage": {
            "markets": list(MOPS_MARKETS),
            "items": sorted(MOPS_STATEMENT_ITEMS),
            "query_matrix_complete": matrix_complete,
        },
        "counts": {
            "manifest_raw_rows": manifest_raw_rows,
            "events": event_count,
            "projections": projection_count,
            "duplicates": duplicate_count,
            "invalids": invalid_count,
            "futures": future_count,
            "new_events": comparison_summary["new_event_count"],
            "revision_candidates": comparison_summary["revision_candidate_count"],
        },
        "outage_reason": None,
        "degraded_reason": degraded_reason,
        "prior_artifact_hash": comparison_summary.get("prior_artifact_hash"),
        "current_artifact_hash": f"sha256:{artifact_sha256}",
        "multi_day_evidence_ready": multi_day_ready,
        "artifact_citation": f"ResearchConsoleProjection.mops_daily_research_freshness.{run_id}",
        "identity": {
            "dataset_id": "mops-daily-research-freshness",
            "generation_id": run_id,
            "research_run_id": run_id,
        },
        "status": {
            "scope": "historical_research_seen_development_data",
            "formal_oos": False,
            "alpha_bp": 0,
            "promotion_eligible": False,
            "apply_flags": REQUIRED_DISABLED_APPLY_FLAGS,
        },
        "lineage": {
            "generated_at": captured_time.isoformat(),
            "dataset_manifest_hash": f"sha256:{artifact_sha256}",
        },
        "frozen_metrics": {},
        "blockers": [],
        "sources": [
            {
                "source_id": "pit.quarterly_financials",
                "label": "MOPS 季報發布 (F26-F29 官方秒級時間軸)",
                "lane": "p0",
                "status": run_status if run_status in {"observed", "degraded", "missing"} else "observed",
                "allowed_use": "research_pit_statement_availability, development_shadow_projection",
                "observed_rows": event_count,
                "revision": comparison_summary.get("prior_run_id") or "v1",
                "owner": "archi",
                "degraded_reason": degraded_reason or outage_reason,
            }
        ],
    }

    # 10. Atomic Write for latest_sanitized_projection.json
    sanitized_bytes = (
        json.dumps(sanitized_projection, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    sanitized_sha256 = sha256(sanitized_bytes).hexdigest()
    latest_projection_file = safe_root / "latest_sanitized_projection.json"
    _atomic_write_bytes(latest_projection_file, sanitized_bytes)

    summary = {
        "run_id": run_id,
        "run_status": run_status,
        "degraded_reason": degraded_reason,
        "outage_reason": outage_reason,
        "artifact_path": str(run_artifact_file),
        "artifact_sha256": artifact_sha256,
        "sanitized_projection_path": str(latest_projection_file),
        "sanitized_projection_sha256": sanitized_sha256,
        "quality_summary": run_artifact["quality_summary"],
        "comparison": comparison_summary,
        "formal_oos_allowed": False,
        "formal_credit_authorized": False,
        "production_blend_alpha_bp": 0,
        "fubon_shadow_usable": True,
        "fubon_formal_credit_allowed": False,
    }

    return DiagnosticsRunResult(
        run_id=run_id,
        run_status=run_status,
        artifact_path=run_artifact_file,
        artifact_sha256=artifact_sha256,
        sanitized_projection_path=latest_projection_file,
        sanitized_projection_sha256=sanitized_sha256,
        summary=summary,
        exit_code=0,
    )


def _compare_with_prior(
    *,
    current_rows: Sequence[Mapping[str, Any]],
    current_start_date: date,
    current_end_date: date,
    prior_artifact_path: Path | None,
) -> dict[str, Any]:
    """比對當前 run 與先前的 immutable artifact。"""
    if prior_artifact_path is None or not prior_artifact_path.is_file():
        return {
            "prior_run_id": None,
            "prior_artifact_hash": None,
            "comparison_status": "baseline_missing",
            "exact_repeated_event_count": 0,
            "new_event_count": len(current_rows),
            "revision_candidate_count": 0,
            "missing_from_repeat_query_count": 0,
            "revision_candidates": [],
            "missing_candidates": [],
        }

    try:
        prior_bytes = prior_artifact_path.read_bytes()
        prior_hash = "sha256:" + sha256(prior_bytes).hexdigest()
        prior = json.loads(prior_bytes)
    except Exception as exc:
        raise ValueError(f"failed to read or parse prior artifact: {exc}") from exc

    if not isinstance(prior, Mapping):
        raise ValueError("prior artifact root must be a JSON object")

    prior_schema = prior.get("schema_version")
    if prior_schema not in {DIAGNOSTICS_SCHEMA_VERSION, "mops-ezsearch-statement-availability.v1"}:
        raise ValueError(f"unsupported prior artifact schema: {prior_schema}")

    prior_run_id = prior.get("run_id") or prior_artifact_path.stem
    prior_rows = prior.get("rows", [])
    if not isinstance(prior_rows, list):
        raise ValueError("prior artifact rows must be a list")

    prior_start = prior.get("query_start_date")
    prior_end = prior.get("query_end_date")
    same_window = (
        prior_start == current_start_date.isoformat()
        and prior_end == current_end_date.isoformat()
    )

    prior_hashes = {str(r.get("event_hash")) for r in prior_rows if isinstance(r, Mapping) and r.get("event_hash")}
    current_hashes = {str(r.get("event_hash")) for r in current_rows if isinstance(r, Mapping) and r.get("event_hash")}

    exact_repeated_count = len(current_hashes & prior_hashes)
    new_event_count = len(current_hashes - prior_hashes)

    # 依 Canonical Key (stock_code, statement_type, period) 尋找 Revision / Correction candidates
    prior_by_key: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for r in prior_rows:
        if isinstance(r, Mapping):
            key = (str(r.get("stock_code")), str(r.get("statement_type")), str(r.get("period")))
            prior_by_key[key] = r

    revision_candidates: list[dict[str, str]] = []
    for r in current_rows:
        if isinstance(r, Mapping):
            key = (str(r.get("stock_code")), str(r.get("statement_type")), str(r.get("period")))
            prior_match = prior_by_key.get(key)
            if prior_match is not None:
                if str(r.get("event_hash")) != str(prior_match.get("event_hash")):
                    revision_candidates.append(
                        {
                            "stock_code": str(r.get("stock_code")),
                            "statement_type": str(r.get("statement_type")),
                            "period": str(r.get("period")),
                            "prior_announcement_at": str(prior_match.get("announcement_at")),
                            "current_announcement_at": str(r.get("announcement_at")),
                            "prior_detail_url": str(prior_match.get("detail_url")),
                            "current_detail_url": str(r.get("detail_url")),
                            "candidate_type": "revision_candidate",
                        }
                    )

    # Missing from repeat query only if identical window
    missing_candidates: list[dict[str, str]] = []
    if same_window:
        current_by_key = {
            (str(r.get("stock_code")), str(r.get("statement_type")), str(r.get("period")))
            for r in current_rows if isinstance(r, Mapping)
        }
        for key, prior_r in prior_by_key.items():
            if key not in current_by_key:
                missing_candidates.append(
                    {
                        "stock_code": key[0],
                        "statement_type": key[1],
                        "period": key[2],
                        "prior_announcement_at": str(prior_r.get("announcement_at")),
                        "candidate_type": "missing_from_repeat_query",
                    }
                )

    return {
        "prior_run_id": prior_run_id,
        "prior_artifact_hash": prior_hash,
        "comparison_status": "comparable" if same_window else "different_window_comparable",
        "exact_repeated_event_count": exact_repeated_count,
        "new_event_count": new_event_count,
        "revision_candidate_count": len(revision_candidates),
        "missing_from_repeat_query_count": len(missing_candidates),
        "revision_candidates": revision_candidates,
        "missing_candidates": missing_candidates,
    }


def _write_failure_run(
    *,
    safe_root: Path,
    runs_dir: Path,
    run_id: str,
    captured_time: datetime,
    start_date: date,
    end_date: date,
    reason: str,
) -> DiagnosticsRunResult:
    """寫入失敗時的 append-only failure diagnostic run artifact。"""
    failure_artifact = {
        "schema_version": DIAGNOSTICS_SCHEMA_VERSION,
        "run_id": run_id,
        "source_id": MOPS_STATEMENT_AVAILABILITY_SOURCE,
        "source_version": MOPS_STATEMENT_AVAILABILITY_SOURCE_VERSION,
        "captured_at": captured_time.isoformat(),
        "query_start_date": start_date.isoformat(),
        "query_end_date": end_date.isoformat(),
        "query_matrix_complete": False,
        "run_status": "capture_failed",
        "outage_reason": reason,
        "degraded_reason": reason,
        "quality_summary": {
            "manifest_raw_row_count": 0,
            "event_count": 0,
            "exact_duplicate_event_count": 0,
            "invalid_event_count": 0,
            "future_event_count": 0,
            "projection_count": 0,
        },
        "safety_boundary": {
            "research_only": True,
            "read_only_source": True,
            "formal_oos_allowed": False,
            "formal_credit_authorized": False,
            "production_scheduler_allowed": False,
            "production_blend_alpha_bp": 0,
            "fubon_shadow_usable": True,
            "fubon_formal_credit_allowed": False,
        },
        "query_manifest": [],
        "rows": [],
        "availability_projection": [],
        "comparison": {
            "prior_run_id": None,
            "prior_artifact_hash": None,
            "comparison_status": "capture_failed",
            "exact_repeated_event_count": 0,
            "new_event_count": 0,
            "revision_candidate_count": 0,
            "missing_from_repeat_query_count": 0,
            "revision_candidates": [],
            "missing_candidates": [],
        },
    }

    artifact_bytes = (
        json.dumps(failure_artifact, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    artifact_sha256 = sha256(artifact_bytes).hexdigest()
    failure_file = runs_dir / f"{run_id}.json"
    _safe_write_bytes(failure_file, artifact_bytes)

    sanitized_failure = {
        "schema_version": SANITIZED_PROJECTION_SCHEMA_VERSION,
        "source": MOPS_STATEMENT_AVAILABILITY_SOURCE,
        "p0_lane": "pit.quarterly_financials",
        "source_decision": "decision:mops.ezsearch.statement_publication:20260727-r1",
        "acceptance": "limited",
        "allowed_use": "research_pit_statement_availability, development_shadow_projection",
        "formal_allowed": False,
        "production_allowed": False,
        "current_run_status": "capture_failed",
        "query_date_window": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
        "counts": {
            "manifest_raw_rows": 0,
            "events": 0,
            "projections": 0,
            "duplicates": 0,
            "invalids": 0,
            "futures": 0,
            "new_events": 0,
            "revision_candidates": 0,
        },
        "outage_reason": reason,
        "degraded_reason": reason,
        "prior_artifact_hash": None,
        "current_artifact_hash": f"sha256:{artifact_sha256}",
        "multi_day_evidence_ready": False,
        "artifact_citation": f"ResearchConsoleProjection.mops_daily_research_freshness.{run_id}",
        "identity": {
            "dataset_id": "mops-daily-research-freshness",
            "generation_id": run_id,
            "research_run_id": run_id,
        },
        "status": {
            "scope": "historical_research_seen_development_data",
            "formal_oos": False,
            "alpha_bp": 0,
            "promotion_eligible": False,
            "apply_flags": REQUIRED_DISABLED_APPLY_FLAGS,
        },
        "lineage": {
            "generated_at": captured_time.isoformat(),
            "dataset_manifest_hash": f"sha256:{artifact_sha256}",
        },
        "frozen_metrics": {},
        "sources": [
            {
                "source_id": "pit.quarterly_financials",
                "label": "MOPS 季報發布 (F26-F29 官方秒級時間軸)",
                "lane": "p0",
                "status": "degraded",
                "allowed_use": "research_pit_statement_availability, development_shadow_projection",
                "observed_rows": 0,
                "revision": "capture_failed",
                "owner": "archi",
                "degraded_reason": reason,
            }
        ],
    }

    sanitized_bytes = (
        json.dumps(sanitized_failure, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    sanitized_sha256 = sha256(sanitized_bytes).hexdigest()
    latest_projection_file = safe_root / "latest_sanitized_projection.json"
    _atomic_write_bytes(latest_projection_file, sanitized_bytes)

    summary = {
        "run_id": run_id,
        "run_status": "capture_failed",
        "artifact_path": str(failure_file),
        "artifact_sha256": artifact_sha256,
        "sanitized_projection_path": str(latest_projection_file),
        "sanitized_projection_sha256": sanitized_sha256,
        "outage_reason": reason,
        "formal_oos_allowed": False,
        "formal_credit_authorized": False,
        "production_blend_alpha_bp": 0,
    }

    return DiagnosticsRunResult(
        run_id=run_id,
        run_status="capture_failed",
        artifact_path=failure_file,
        artifact_sha256=artifact_sha256,
        sanitized_projection_path=latest_projection_file,
        sanitized_projection_sha256=sanitized_sha256,
        summary=summary,
        exit_code=1,
    )


def _safe_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".tmp_{path.name}_{os.getpid()}"
    tmp_path.write_bytes(data)
    os.replace(tmp_path, path)


def _parse_iso_timestamp(text: str) -> datetime:
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must have timezone")
    return parsed


def _verify_no_symlink_escape(root: Path) -> None:
    resolved = root.resolve()
    for parent in (resolved, *resolved.parents):
        if parent.is_symlink():
            raise ValueError(f"symlink path detected: {parent}")
