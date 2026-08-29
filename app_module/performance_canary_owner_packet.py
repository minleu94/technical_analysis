"""Build a bounded owner packet for technical and broker canary decisions.

Performance evidence is intentionally split across independent probes.  This
module joins only their safe metadata into a handoff packet; it never starts a
worker, opens a production writer, deletes a run, or treats a staging result as
production acceptance.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from typing import Any, Mapping


PERFORMANCE_CANARY_OWNER_PACKET_SCHEMA_VERSION = "performance-canary-owner-review.v1"
_EXPECTED_SCHEMAS = {
    "technical_preview": "technical-indicator-production-canary.v1",
    "worker_recovery": "technical-indicator-worker-recovery.v1",
    "broker_canary": "broker-performance-baseline.v2",
    "direct_storage_preflight": "ml-direct-chain-maintenance-status.v1",
    "retention_direct": "ml-storage-retention-inventory.v1",
    "retention_ooc": "ml-storage-retention-inventory.v1",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _load_artifact(path: str | Path, *, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved = Path(path).expanduser().resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} artifact missing: {resolved}")
    if not _is_inside(resolved, temp_root):
        raise ValueError(f"{label} artifact must remain in OS TEMP")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} artifact is unreadable") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} artifact must be a JSON object")
    expected_schema = _EXPECTED_SCHEMAS[label]
    if payload.get("schema_version") != expected_schema:
        raise ValueError(f"{label} artifact schema is unsupported")
    identity = {
        "label": label,
        "path": str(resolved),
        "sha256": _sha256_file(resolved),
        "schema_version": expected_schema,
        "status": str(payload.get("status") or ""),
    }
    return payload, identity


def _require_bool(payload: Mapping[str, Any], key: str, *, label: str, value: bool) -> None:
    if payload.get(key) is not value:
        raise ValueError(f"{label} artifact must keep {key}={str(value).lower()}")


def _safe_check_map(value: object) -> dict[str, bool]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): item
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, bool)
    }


def _bounded_retention_candidates(payload: Mapping[str, Any], *, limit: int = 5) -> list[dict[str, Any]]:
    candidates = payload.get("retention_candidates")
    if not isinstance(candidates, list):
        return []
    result: list[dict[str, Any]] = []
    for raw in candidates[:limit]:
        if not isinstance(raw, Mapping):
            continue
        result.append(
            {
                "kind": str(raw.get("kind") or ""),
                "path": str(raw.get("path") or ""),
                "run_id": str(raw.get("run_id") or ""),
                "schema_version": str(raw.get("schema_version") or ""),
                "status": str(raw.get("status") or ""),
                "size_bytes": int(raw.get("size_bytes") or 0),
                "file_count": int(raw.get("file_count") or 0),
                "manual_review_required": raw.get("manual_review_required") is True,
                "automatic_delete_allowed": raw.get("automatic_delete_allowed") is True,
                "reversible_action": str(raw.get("reversible_action") or ""),
            }
        )
    return result


def build_performance_canary_owner_packet(
    *,
    technical_preview_path: str | Path,
    worker_recovery_path: str | Path,
    broker_canary_path: str | Path,
    direct_storage_preflight_path: str | Path,
    retention_direct_path: str | Path,
    retention_ooc_path: str | Path,
    owner_role: str = "",
    reviewer_role: str = "",
) -> dict[str, Any]:
    """Build a non-authorizing packet from explicit TEMP performance artifacts."""

    paths = {
        "technical_preview": technical_preview_path,
        "worker_recovery": worker_recovery_path,
        "broker_canary": broker_canary_path,
        "direct_storage_preflight": direct_storage_preflight_path,
        "retention_direct": retention_direct_path,
        "retention_ooc": retention_ooc_path,
    }
    payloads: dict[str, dict[str, Any]] = {}
    identities: list[dict[str, Any]] = []
    for label, path in paths.items():
        payload, identity = _load_artifact(path, label=label)
        payloads[label] = payload
        identities.append(identity)

    technical = payloads["technical_preview"]
    _require_bool(technical, "production_write_attempted", label="technical_preview", value=False)
    _require_bool(technical, "production_sqlite_write_attempted", label="technical_preview", value=False)
    _require_bool(technical, "production_worker_enabled", label="technical_preview", value=False)
    worker = payloads["worker_recovery"]
    _require_bool(worker, "production_write_attempted", label="worker_recovery", value=False)
    _require_bool(worker, "production_sqlite_write_attempted", label="worker_recovery", value=False)
    broker = payloads["broker_canary"]
    _require_bool(broker, "production_write_attempted", label="broker_canary", value=False)
    _require_bool(broker, "production_sqlite_write_attempted", label="broker_canary", value=False)
    _require_bool(broker, "production_fetch_pool_enabled", label="broker_canary", value=False)
    if broker.get("selenium_fallback_serialized") is not True:
        raise ValueError("broker_canary artifact must keep Selenium fallback serialized")

    storage = payloads["direct_storage_preflight"]
    _require_bool(storage, "writes_source_database", label="direct_storage_preflight", value=False)
    _require_bool(storage, "formal_oos_allowed", label="direct_storage_preflight", value=False)
    _require_bool(storage, "broker_order_allowed", label="direct_storage_preflight", value=False)
    storage_preflight = storage.get("storage_preflight")
    if not isinstance(storage_preflight, Mapping):
        raise ValueError("direct_storage_preflight artifact is missing storage_preflight")
    storage_summary = {
        "status": str(storage.get("status") or ""),
        "free_bytes": int(storage_preflight.get("free_bytes") or 0),
        "minimum_free_space_bytes": int(storage_preflight.get("minimum_free_space_bytes") or 0),
        "within_minimum_free_space": storage_preflight.get("within_minimum_free_space") is True,
        "probe_path": str(storage_preflight.get("probe_path") or ""),
        "error": str(storage.get("error") or ""),
    }

    retention_summaries: dict[str, Any] = {}
    for label in ("retention_direct", "retention_ooc"):
        retention = payloads[label]
        safety = retention.get("safety")
        if not isinstance(safety, Mapping):
            raise ValueError(f"{label} artifact is missing safety")
        if safety.get("automatic_delete_allowed") is not False:
            raise ValueError(f"{label} artifact must keep automatic_delete_allowed=false")
        if safety.get("deletion_attempted") is not False or safety.get("move_attempted") is not False:
            raise ValueError(f"{label} artifact reports a destructive action")
        disk = retention.get("disk")
        retention_summaries[label] = {
            "status": str(retention.get("status") or ""),
            "minimum_observed_free_bytes": int(
                (disk.get("minimum_observed_free_bytes") if isinstance(disk, Mapping) else 0) or 0
            ),
            "within_minimum_free_space": (
                disk.get("within_minimum_free_space") is True
                if isinstance(disk, Mapping)
                else False
            ),
            "candidate_count_in_packet": len(_bounded_retention_candidates(retention)),
            "candidates": _bounded_retention_candidates(retention),
            "automatic_delete_allowed": False,
            "deletion_attempted": False,
            "move_attempted": False,
        }

    review_records = [
        {
            "lane": "technical_production_canary",
            "decision": "pending",
            "required_owner_action": "核准一檔股票的 backup／rollback canary，先停用並行 writer。",
            "observations": {
                "status": str(technical.get("status") or ""),
                "stock_id": str(technical.get("stock_id") or ""),
                "expected_latest_date": str(technical.get("expected_latest_date") or ""),
                "workers": int(technical.get("workers") or 0),
                "max_in_flight": int(technical.get("max_in_flight") or 0),
                "rollback_available": technical.get("rollback", {}).get("available") is True
                if isinstance(technical.get("rollback"), Mapping)
                else False,
                "production_write_attempted": False,
            },
            "blockers": [
                "technical_canary_confirmation_required",
                "technical_canary_owner_approval_required",
                "technical_canary_no_concurrent_writer_ack_required",
            ],
        },
        {
            "lane": "technical_single_writer_staging",
            "decision": "observed_staging_only",
            "required_owner_action": "review worker recovery／single-writer staging，再決定是否核准 production canary。",
            "observations": {
                "status": str(worker.get("status") or ""),
                "observed_worker_count": int(worker.get("observed_worker_count") or 0),
                "checks": _safe_check_map(worker.get("checks")),
                "production_write_attempted": False,
                "production_worker_enabled": False,
            },
            "blockers": ["staging_evidence_is_not_production_acceptance"],
        },
        {
            "lane": "direct_ooc_storage",
            "decision": "pending_capacity_owner_review",
            "required_owner_action": "處理容量／保留策略；只能由 owner 確認外部 archive 或擴容，不自動刪除。",
            "observations": storage_summary,
            "blockers": [
                "direct_chain_storage_preflight_blocked"
                if not storage_summary["within_minimum_free_space"]
                else "direct_chain_storage_preflight_observed"
            ],
        },
        {
            "lane": "broker_bounded_fetch",
            "decision": "pending_production_pool_review",
            "required_owner_action": "審核 bounded fetch、rate-limit、Selenium serialized fallback 與 writer 邊界。",
            "observations": {
                "status": str(broker.get("status") or ""),
                "production_fetch_pool_enabled": False,
                "selenium_fallback_invocations": int(broker.get("selenium_fallback_invocations") or 0),
                "selenium_fallback_serialized": True,
                "single_writer_required": broker.get("single_writer_required") is True,
                "checks": _safe_check_map(
                    (broker.get("bounded_fetch_acceptance") or {}).get("checks")
                    if isinstance(broker.get("bounded_fetch_acceptance"), Mapping)
                    else {}
                ),
            },
            "blockers": [
                "broker_production_fetch_pool_disabled",
                "broker_long_term_rate_limit_and_selenium_fallback_not_accepted",
            ],
        },
    ]
    normalized_owner = owner_role.strip()
    normalized_reviewer = reviewer_role.strip()
    return {
        "schema_version": PERFORMANCE_CANARY_OWNER_PACKET_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "packet_status": (
            "ready_for_owner_review"
            if normalized_owner and normalized_reviewer
            else "needs_named_owner_reviewer"
        ),
        "owner_role": normalized_owner,
        "reviewer_role": normalized_reviewer,
        "owner_reviewer_required": True,
        "artifact_identities": identities,
        "technical_production_canary": {
            "status": str(technical.get("status") or ""),
            "production_write_attempted": False,
            "production_worker_enabled": False,
            "single_writer_required": True,
        },
        "technical_single_writer_staging": {
            "status": str(worker.get("status") or ""),
            "production_write_attempted": False,
            "parent_single_writer": (
                (worker.get("checks") or {}).get("parent_single_writer") is True
                if isinstance(worker.get("checks"), Mapping)
                else False
            ),
        },
        "direct_ooc_storage": storage_summary,
        "retention": retention_summaries,
        "broker_bounded_fetch": {
            "status": str(broker.get("status") or ""),
            "production_fetch_pool_enabled": False,
            "selenium_fallback_serialized": True,
            "single_writer_required": broker.get("single_writer_required") is True,
        },
        "review_records": review_records,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
        "production_worker_enabled": False,
        "production_fetch_pool_enabled": False,
        "automatic_delete_allowed": False,
        "candidate_only": True,
        "write_performed": False,
        "destructive_action_performed": False,
        "limitations": [
            "technical／worker 結果若來自 isolated staging，不能當 production backup／rollback 或長期 writer acceptance。",
            "Direct/OOC 容量低於門檻時不啟動 worker；retention inventory 只提供 owner review 候選，不自動刪除或搬移。",
            "broker real HTTP／離線 bounded fetch 只證明當次 parser／限流／fallback contract，不能直接開 production fetch pool。",
            "本 packet 不執行 canary、不改 scheduler／feature flag、不寫 production SQLite、不授予 Formal 或 broker 資格。",
        ],
    }


def validate_output_path(output_path: str | Path, *, input_paths: Mapping[str, str | Path]) -> Path:
    output = Path(output_path).expanduser().resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if not _is_inside(output, temp_root):
        raise ValueError("owner packet output must remain in OS TEMP")
    resolved_inputs = {Path(value).expanduser().resolve() for value in input_paths.values()}
    if output in resolved_inputs:
        raise ValueError("owner packet output must not overwrite an input artifact")
    if not output.parent.exists():
        raise ValueError("owner packet output parent must already exist")
    return output


def render_markdown(packet: Mapping[str, Any]) -> str:
    lines = [
        "# Performance Canary Owner Review Packet (Candidate)",
        "",
        f"- Packet status: `{packet.get('packet_status', '')}`",
        f"- Owner role: `{packet.get('owner_role', '') or 'REQUIRES_NAMED_OWNER'}`",
        f"- Reviewer role: `{packet.get('reviewer_role', '') or 'REQUIRES_NAMED_REVIEWER'}`",
        f"- Technical canary: `{packet.get('technical_production_canary', {}).get('status', '')}`",
        f"- Direct/OOC storage: `{packet.get('direct_ooc_storage', {}).get('status', '')}`",
        f"- Broker bounded fetch: `{packet.get('broker_bounded_fetch', {}).get('status', '')}`",
        "- Production worker／fetch pool enabled: `false`／`false`",
        "- Automatic delete／move allowed: `false`／`false`",
        "- Formal OOS／broker order allowed: `false`／`false`",
        "",
        "## Review lanes",
        "",
        "| Lane | Decision | Required owner action | Blockers |",
        "|---|---|---|---|",
    ]
    for record in packet.get("review_records", []):
        blockers = ", ".join(str(item) for item in record.get("blockers", []))
        lines.append(
            f"| `{record.get('lane', '')}` | `{record.get('decision', '')}` | "
            f"{record.get('required_owner_action', '')} | `{blockers}` |"
        )
    lines.extend(
        [
            "",
            "## Safety boundary",
            "",
            "- Candidate only；本 packet 不執行 technical／broker canary，不啟動 worker，不刪除或搬移任何 run。",
            "- 只有 owner 在獨立 governed path 完成核准後，才可另行執行 production canary；容量與 single-writer guard 未通過時必須停止。",
        ]
    )
    return "\n".join(lines) + "\n"


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


__all__ = [
    "PERFORMANCE_CANARY_OWNER_PACKET_SCHEMA_VERSION",
    "build_performance_canary_owner_packet",
    "render_markdown",
    "validate_output_path",
]
