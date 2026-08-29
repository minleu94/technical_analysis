"""Build a read-only owner/reviewer input from the weekly collection sidecar.

The sidecar is an automatic collection store.  This module deliberately emits a
separate candidate packet rather than mutating the sidecar or producing an
``approved-weekly-history-projection.v1``.  A human must still fill the review
fields and publish any approved projection through the existing governed path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping


SCHEMA_VERSION = "evidence-weekly-approval-input.v1"
PENDING_STATUS = "pending_human_review"
FAILED_STATUS = "collection_failed"
APPROVAL_STATUS = "pending_owner_reviewer"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _read_only_connection(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(str(path))
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _non_empty(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"weekly collection row missing {field}")
    return text


def _payload(value: object, collection_id: str) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"weekly collection payload invalid: {collection_id}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"weekly collection payload must be an object: {collection_id}")
    return parsed


def _record_from_row(
    row: sqlite3.Row,
    *,
    owner_role: str,
    reviewer_role: str,
) -> dict[str, Any]:
    collection_id = _non_empty(row["collection_id"], "collection_id")
    period_start = _non_empty(row["period_start"], "period_start")
    period_end = _non_empty(row["period_end"], "period_end")
    source_path = _non_empty(row["source_path"], "source_path")
    source_hash = _non_empty(row["source_hash"], "source_hash")
    if not source_hash.startswith("sha256:"):
        raise ValueError(f"weekly collection source hash is not immutable: {collection_id}")
    status = _non_empty(row["status"], "status")
    if status not in {PENDING_STATUS, FAILED_STATUS}:
        raise ValueError(f"unsupported weekly collection status: {status}")
    payload = _payload(row["payload_json"], collection_id)
    error_type = str(row["error_type"] or "")
    error_message = str(row["error_message"] or "")
    if status == PENDING_STATUS and (error_type or error_message):
        raise ValueError(f"pending weekly collection contains an error: {collection_id}")

    payload_last_trading_date = str(payload.get("last_trading_date") or "").strip()
    return {
        "collection_id": collection_id,
        "period_start": period_start,
        "period_end": period_end,
        "source_path": source_path,
        "source_hash": source_hash,
        "collection_status": status,
        "created_at": str(row["created_at"] or "").strip(),
        "last_trading_date": payload_last_trading_date,
        "collection_payload": payload,
        "error": {
            "type": error_type,
            "message": error_message,
        },
        "review": {
            "approval_status": APPROVAL_STATUS,
            "owner_role": owner_role,
            "reviewer_role": reviewer_role,
            "review_decision": "",
            "reviewed_at": "",
            "review_note": "",
        },
        "formal_credit_authorized": False,
        "production_scheduler_allowed": False,
        "downstream_eligibility": "none",
    }


def build_weekly_approval_input(
    sidecar_path: str | Path,
    *,
    owner_role: str = "",
    reviewer_role: str = "",
    include_failed: bool = False,
) -> dict[str, Any]:
    """Read pending sidecar rows and return a non-approving review packet."""

    resolved_sidecar = Path(sidecar_path).expanduser().resolve()
    normalized_owner = owner_role.strip()
    normalized_reviewer = reviewer_role.strip()
    statuses = (PENDING_STATUS, FAILED_STATUS) if include_failed else (PENDING_STATUS,)
    placeholders = ", ".join("?" for _ in statuses)
    try:
        with _read_only_connection(resolved_sidecar) as connection:
            if not _table_exists(connection, "evidence_weekly_collections"):
                raise ValueError("weekly collection sidecar table missing")
            rows = connection.execute(
                f"""
                SELECT collection_id, period_start, period_end, source_path,
                       source_hash, status, payload_json, error_type,
                       error_message, created_at
                FROM evidence_weekly_collections
                WHERE status IN ({placeholders})
                ORDER BY period_start, period_end, collection_id
                """,
                statuses,
            ).fetchall()
    except sqlite3.Error as exc:
        raise ValueError(f"weekly collection sidecar unavailable: {exc}") from exc

    records = [
        _record_from_row(
            row,
            owner_role=normalized_owner,
            reviewer_role=normalized_reviewer,
        )
        for row in rows
    ]
    pending_count = sum(
        1 for record in records if record["collection_status"] == PENDING_STATUS
    )
    failed_count = sum(
        1 for record in records if record["collection_status"] == FAILED_STATUS
    )
    source_paths = sorted({record["source_path"] for record in records})
    source_hashes = sorted({record["source_hash"] for record in records})
    packet_status = (
        "ready_for_human_review"
        if normalized_owner and normalized_reviewer
        else "needs_named_owner_reviewer"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "packet_status": packet_status,
        "sidecar_path": str(resolved_sidecar),
        "sidecar_sha256": _sha256_file(resolved_sidecar),
        "source_paths": source_paths,
        "source_hashes": source_hashes,
        "record_count": len(records),
        "pending_human_review_count": pending_count,
        "collection_failed_count": failed_count,
        "owner_reviewer_required": True,
        "owner_role": normalized_owner,
        "reviewer_role": normalized_reviewer,
        "formal_credit_authorized": False,
        "production_scheduler_allowed": False,
        "downstream_eligibility": "none",
        "candidate_only": True,
        "write_performed": False,
        "approved_projection_emitted": False,
        "records": records,
        "limitations": [
            "自動 sidecar collection 只代表 pending_human_review，不是人工核准。",
            "本 packet 不會寫 sidecar、正式 Evidence DB、Registry 或 approved weekly projection。",
            "必須由具名 owner／reviewer 填寫 review_decision、reviewed_at 與 review_note；此 packet 本身不授予 Formal credit。",
            "collection payload 的 source hash 只綁定收集時讀到的來源快照，不替代 quality、coverage、PIT 或 license acceptance。",
        ],
    }


def render_markdown(packet: Mapping[str, Any]) -> str:
    records = packet.get("records", [])
    lines = [
        "# Evidence Weekly Approval Input (Candidate)",
        "",
        f"- Packet status: `{packet.get('packet_status', '')}`",
        f"- Generated at: `{packet.get('generated_at', '')}`",
        f"- Sidecar: `{packet.get('sidecar_path', '')}`",
        f"- Sidecar SHA-256: `{packet.get('sidecar_sha256', '')}`",
        f"- Pending human review: `{packet.get('pending_human_review_count', 0)}`",
        f"- Collection failed: `{packet.get('collection_failed_count', 0)}`",
        f"- Owner role: `{packet.get('owner_role', '') or 'REQUIRES_NAMED_OWNER'}`",
        f"- Reviewer role: `{packet.get('reviewer_role', '') or 'REQUIRES_NAMED_REVIEWER'}`",
        "- Formal credit authorized: `false`",
        "- Production scheduler allowed: `false`",
        "- Downstream eligibility: `none`",
        "- Write performed: `false`",
        "",
        "## Review records",
        "",
        "| Period | Collection ID | Source hash | Last trading date | Approval status | Decision |",
        "|---|---|---|---|---|---|",
    ]
    for record in records:
        review = record.get("review", {})
        lines.append(
            "| {start}..{end} | `{collection}` | `{source_hash}` | `{last_trading}` | "
            "`{approval}` | `{decision}` |".format(
                start=record.get("period_start", ""),
                end=record.get("period_end", ""),
                collection=record.get("collection_id", ""),
                source_hash=record.get("source_hash", ""),
                last_trading=record.get("last_trading_date", "") or "unknown",
                approval=review.get("approval_status", APPROVAL_STATUS),
                decision=review.get("review_decision", "") or "pending",
            )
        )
    lines.extend(
        [
            "",
            "## Required human input",
            "",
            "- 逐期確認 source freshness、quality、warnings、blocking gaps 與 follow-up。",
            "- 填寫具名 owner／reviewer、review decision（reviewed／dismissed／follow_up）、reviewed_at 與 note。",
            "- 只有人工核准流程另外產生相容的 approved-weekly-history projection 後，UI 才能揭露核准期數；本 packet 不會自動轉換。",
        ]
    )
    return "\n".join(lines) + "\n"


def validate_output_path(output_path: str | Path, *, sidecar_path: str | Path) -> Path:
    """Reject destructive or misleading output targets before writing a packet."""

    output = Path(output_path).expanduser().resolve()
    sidecar = Path(sidecar_path).expanduser().resolve()
    if output == sidecar:
        raise ValueError("approval packet output must not overwrite the source sidecar")
    if output.name.lower() == "twstock.db":
        raise ValueError("approval packet output must not overwrite a source database")
    if not output.parent.exists():
        raise ValueError("approval packet output parent must already exist")
    return output

