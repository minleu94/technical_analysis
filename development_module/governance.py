"""Read-only preflight for the owner-authorized Terra development decision."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
from pathlib import Path


@dataclass(frozen=True)
class DevelopmentDataUsageDecision:
    """The only accepted governance state before a Terra source read."""

    new_holdout_start: str
    decision_record_sha256: str


def load_development_data_usage_decision(
    decision_path: str | Path,
    *,
    output_root: str | Path,
) -> DevelopmentDataUsageDecision:
    """Validate the append-only owner decision and an unconsumed replacement holdout."""
    root = Path(output_root).expanduser().resolve()
    path = Path(decision_path).expanduser().resolve()
    expected = root / "governance" / "DevelopmentDataUsageDecision.jsonl"
    if path != expected:
        raise ValueError("usage decision must be the explicit output-root governance artifact")
    raw = path.read_bytes()
    records = _records(raw, path)
    decision = records[0]
    if decision.get("decision") != "seen_oos":
        raise ValueError("usage decision must be seen_oos")
    authorization = decision.get("owner_provided_authorization")
    if not isinstance(authorization, str) or not authorization.strip():
        raise ValueError("owner-provided authorization is required")
    if decision.get("year_2025_usage") != "development_only":
        raise ValueError("2025 usage must remain development_only")
    if decision.get("formal_oos_allowed") is not False:
        raise ValueError("formal_oos_allowed must remain false")
    if decision.get("production_blend_alpha_bp") != 0:
        raise ValueError("production_blend_alpha_bp must remain zero")
    effective_timestamp = decision.get("effective_timestamp_utc")
    if not isinstance(effective_timestamp, str) or not effective_timestamp.strip():
        raise ValueError("effective timestamp is required")
    try:
        datetime.fromisoformat(effective_timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("effective timestamp must be ISO-8601") from exc
    recorded_root = Path(str(decision.get("development_output_root", ""))).expanduser().resolve()
    if recorded_root != root:
        raise ValueError("usage decision output root mismatch")
    holdout = str(decision.get("new_holdout_start", ""))
    date.fromisoformat(holdout)
    registry = root / "governance" / "HoldoutConsumptionRegistry.jsonl"
    if registry.exists() and _holdout_consumed(registry, holdout):
        raise ValueError("new holdout has already been consumed")
    return DevelopmentDataUsageDecision(
        new_holdout_start=holdout,
        decision_record_sha256="sha256:" + hashlib.sha256(raw).hexdigest(),
    )


def _records(raw: bytes, path: Path) -> list[dict[str, object]]:
    try:
        records = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid append-only usage decision: {path}") from exc
    if not records or any(not isinstance(record, dict) for record in records):
        raise ValueError("usage decision requires at least one JSON object record")
    return records


def _holdout_consumed(registry: Path, holdout_start: str) -> bool:
    for record in _records(registry.read_bytes(), registry):
        observed = record.get("trading_session", record.get("holdout_start"))
        if observed == holdout_start:
            return True
    return False
