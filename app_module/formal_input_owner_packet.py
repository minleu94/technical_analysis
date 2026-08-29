"""Build a fail-closed owner packet from the Formal candidate inventory.

The candidate inventory deliberately does not discover or wire Formal inputs.
This module turns that bounded, safe projection into an actionable handoff:
each of the three expected input contracts gets a named review slot and a
short list of candidate manifests.  It never reads candidate data rows,
renames a manifest, writes a controlled path, or grants Formal/OOS credit.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping


FORMAL_INPUT_OWNER_PACKET_SCHEMA_VERSION = "formal-input-owner-review.v1"
INVENTORY_SCHEMA_VERSION = "ml-formal-input-candidate-inventory.v1"
EXPECTED_INPUTS: tuple[tuple[str, str, str], ...] = (
    (
        "causal_non_cash_portfolio_ledger",
        "causal-portfolio-ledger.v1",
        "由 owner 發布 append-only non-cash state ledger，逐日綁定 T-1、row hash、chain hash 與 custody。",
    ),
    (
        "formal_rule_champion_snapshot_history",
        "rule-champion-snapshot-history.v1",
        "由 owner 發布正式 Rule Champion snapshot history，綁定決策日、版本、hash 與可重建輸入。",
    ),
    (
        "pit_sector_membership",
        "pit-sector-membership-sidecar-v1",
        "由 owner 提供歷史 PIT sector membership sidecar，逐日綁定來源 publication、as-of 與 coverage。",
    ),
)
_EXPECTED_INPUT_NAMES = frozenset(item[0] for item in EXPECTED_INPUTS)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _load_inventory(path: Path) -> tuple[dict[str, Any], str]:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"formal candidate inventory is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("formal candidate inventory must be a JSON object")
    if payload.get("schema_version") != INVENTORY_SCHEMA_VERSION:
        raise ValueError("formal candidate inventory schema is unsupported")
    if payload.get("formal_oos_allowed") is not False:
        raise ValueError("formal candidate inventory must remain formal_oos_allowed=false")
    if payload.get("broker_order_allowed") is not False:
        raise ValueError("formal candidate inventory must remain broker_order_allowed=false")
    if payload.get("promotion_eligible") is not False:
        raise ValueError("formal candidate inventory must remain promotion_eligible=false")
    if payload.get("formal_ready_input_count", 0) not in (0, None):
        raise ValueError("formal candidate inventory must report formal_ready_input_count=0")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("formal candidate inventory candidates must be a list")
    candidate_root = str(payload.get("candidate_root") or "").strip()
    if not candidate_root:
        raise ValueError("formal candidate inventory candidate_root is required")
    return payload, _sha256_file(path)


def _candidate_projection(item: Mapping[str, object]) -> dict[str, object]:
    path = str(item.get("path") or "").strip()
    manifest_hash = str(item.get("manifest_sha256") or "").strip()
    lane = str(item.get("lane") or "").strip()
    reason = str(item.get("reason") or "").strip()
    if not path or not manifest_hash.startswith("sha256:") or not lane or not reason:
        raise ValueError("formal candidate inventory row is missing safe identity fields")
    raw_safe_projection = item.get("safe_projection")
    safe_projection: dict[str, object] = {}
    if isinstance(raw_safe_projection, Mapping):
        safe_projection = {str(key): value for key, value in raw_safe_projection.items()}
    return {
        "path": path,
        "manifest_sha256": manifest_hash,
        "lane": lane,
        "reason": reason,
        "formal_consumer_compatible": (
            item.get("formal_consumer_compatible")
            if isinstance(item.get("formal_consumer_compatible"), bool)
            else None
        ),
        "formal_oos_allowed": (
            item.get("formal_oos_allowed")
            if isinstance(item.get("formal_oos_allowed"), bool)
            else None
        ),
        "safe_projection": safe_projection,
    }


def build_formal_input_owner_packet(
    inventory_path: str | Path,
    *,
    owner_role: str = "",
    reviewer_role: str = "",
    max_candidates_per_input: int = 8,
) -> dict[str, Any]:
    """Build a non-authorizing owner/reviewer packet from a candidate report."""

    resolved_inventory = Path(inventory_path).expanduser().resolve()
    if (
        isinstance(max_candidates_per_input, bool)
        or not isinstance(max_candidates_per_input, int)
        or not 1 <= max_candidates_per_input <= 32
    ):
        raise ValueError("max_candidates_per_input must be between 1 and 32")
    inventory, inventory_hash = _load_inventory(resolved_inventory)
    candidate_rows: dict[str, list[dict[str, object]]] = {
        input_name: [] for input_name in _EXPECTED_INPUT_NAMES
    }
    for raw_item in inventory["candidates"]:
        if not isinstance(raw_item, Mapping):
            raise ValueError("formal candidate inventory row must be an object")
        input_name = raw_item.get("candidate_input")
        if not isinstance(input_name, str) or input_name not in _EXPECTED_INPUT_NAMES:
            continue
        projected = _candidate_projection(raw_item)
        bucket = candidate_rows[str(input_name)]
        if len(bucket) < max_candidates_per_input:
            bucket.append(projected)

    normalized_owner = owner_role.strip()
    normalized_reviewer = reviewer_role.strip()
    review_records: list[dict[str, Any]] = []
    for input_name, expected_schema, requirement in EXPECTED_INPUTS:
        candidates = candidate_rows[input_name]
        review_records.append(
            {
                "input": input_name,
                "expected_schema": expected_schema,
                "requirement": requirement,
                "candidate_count_in_packet": len(candidates),
                "candidate_count_observed": int(
                    (inventory.get("candidate_input_counts") or {}).get(input_name, 0)
                ),
                "candidates": candidates,
                "owner_decision": "pending",
                "selected_candidate_path": "",
                "published_formal_path": "",
                "custody_id": "",
                "reviewed_at": "",
                "review_note": "",
            }
        )

    packet_status = (
        "ready_for_owner_review"
        if normalized_owner and normalized_reviewer
        else "needs_named_owner_reviewer"
    )
    return {
        "schema_version": FORMAL_INPUT_OWNER_PACKET_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "packet_status": packet_status,
        "inventory_path": str(resolved_inventory),
        "inventory_sha256": inventory_hash,
        "candidate_root": str(Path(str(inventory["candidate_root"])).expanduser().resolve()),
        "inventory_manifest_count": inventory.get("manifest_count", 0),
        "inventory_skipped_count": inventory.get("skipped_count", 0),
        "inventory_truncated": inventory.get("truncated", False),
        "inventory_lane_counts": inventory.get("lane_counts", {}),
        "owner_role": normalized_owner,
        "reviewer_role": normalized_reviewer,
        "owner_reviewer_required": True,
        "formal_ready_input_count": 0,
        "formal_input_count": len(review_records),
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
        "promotion_eligible": False,
        "candidate_only": True,
        "write_performed": False,
        "publication_emitted": False,
        "review_records": review_records,
        "limitations": [
            "候選 inventory 只保留 bounded manifest metadata，不代表 underlying data rows 已通過 loader、PIT、cutoff 或 custody。",
            "research／prospective artifact 不得改名、複製或直接接到正式 BALDR_ML_FORMAL_* path。",
            "必須由 owner-controlled publisher 產生三份 expected schema manifest，再由正式 readiness inspector 重新驗證 hash、cutoff、chain 與來源。",
            "本 packet 不會選擇 candidate、不會填入 published_formal_path、不會授予 Formal OOS、promotion 或 broker 資格。",
        ],
    }


def validate_output_path(output_path: str | Path, *, inventory_path: str | Path) -> Path:
    """Reject overwriting inventory or writing a packet into the candidate tree."""

    output = Path(output_path).expanduser().resolve()
    inventory = Path(inventory_path).expanduser().resolve()
    if output == inventory:
        raise ValueError("owner packet output must not overwrite the inventory")
    if output.parent == inventory.parent and output.name.lower() == "inventory.json":
        raise ValueError("owner packet output must not replace inventory.json")
    if not output.parent.exists():
        raise ValueError("owner packet output parent must already exist")
    try:
        candidate_root_value = json.loads(inventory.read_text(encoding="utf-8")).get("candidate_root")
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
        candidate_root_value = None
    if isinstance(candidate_root_value, str) and candidate_root_value.strip():
        candidate_root = Path(candidate_root_value).expanduser().resolve()
        if output == candidate_root or output.is_relative_to(candidate_root):
            raise ValueError("owner packet output must be outside candidate_root")
    return output


def render_markdown(packet: Mapping[str, Any]) -> str:
    lines = [
        "# Formal Input Owner Review Packet (Candidate)",
        "",
        f"- Packet status: `{packet.get('packet_status', '')}`",
        f"- Inventory: `{packet.get('inventory_path', '')}`",
        f"- Inventory SHA-256: `{packet.get('inventory_sha256', '')}`",
        f"- Candidate root: `{packet.get('candidate_root', '')}`",
        f"- Manifest count / skipped / truncated: `{packet.get('inventory_manifest_count', 0)}` / `{packet.get('inventory_skipped_count', 0)}` / `{str(bool(packet.get('inventory_truncated'))).lower()}`",
        f"- Owner role: `{packet.get('owner_role', '') or 'REQUIRES_NAMED_OWNER'}`",
        f"- Reviewer role: `{packet.get('reviewer_role', '') or 'REQUIRES_NAMED_REVIEWER'}`",
        "- Formal ready inputs: `0/3`",
        "- Formal OOS allowed: `false`",
        "- Candidate only: `true`",
        "- Write performed: `false`",
        "",
        "## Required input review",
        "",
        "| Input | Expected schema | Observed candidates | Packet candidates | Owner decision |",
        "|---|---|---:|---:|---|",
    ]
    for record in packet.get("review_records", []):
        lines.append(
            f"| `{record.get('input', '')}` | `{record.get('expected_schema', '')}` | "
            f"{record.get('candidate_count_observed', 0)} | {record.get('candidate_count_in_packet', 0)} | "
            f"`{record.get('owner_decision', 'pending')}` |"
        )
        lines.extend(
            [
                "",
                f"### {record.get('input', '')}",
                "",
                f"Requirement: {record.get('requirement', '')}",
            ]
        )
        candidates = record.get("candidates", [])
        if not candidates:
            lines.append("- No candidate manifest observed for this input.")
        else:
            for candidate in candidates:
                lines.append(
                    f"- `{candidate.get('path', '')}` — `{candidate.get('lane', '')}` — "
                    f"`{candidate.get('reason', '')}` — `{candidate.get('manifest_sha256', '')}`"
                )
        lines.append("- Selected candidate / published formal path / custody id: `pending owner input`")
    lines.extend(
        [
            "",
            "## Required human input",
            "",
            "- 由具名 owner／reviewer 確認來源、PIT、cutoff、hash、custody 與 loader validation。",
            "- 只有 owner-controlled publisher 另產生正式 manifest 後，才可重新執行 formal input readiness。",
            "- 不得把 research／prospective candidate 改名或複製成正式 input；本 packet 不會自動寫入任何路徑。",
        ]
    )
    return "\n".join(lines) + "\n"


__all__ = [
    "EXPECTED_INPUTS",
    "FORMAL_INPUT_OWNER_PACKET_SCHEMA_VERSION",
    "build_formal_input_owner_packet",
    "render_markdown",
    "validate_output_path",
]
