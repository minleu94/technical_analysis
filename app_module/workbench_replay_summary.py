from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_historical_replay_summary(path: str | Path) -> dict[str, Any]:
    summary_path = Path(path)
    if summary_path.suffix.lower() != ".json":
        raise ValueError("Historical replay input must be a JSON summary, not a replay DB or other artifact.")
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Historical replay JSON summary must contain an object payload.")

    final = _dict(payload.get("final_outcome_summary"))
    totals = _dict(payload.get("totals"))
    warnings = _warnings(payload, final)
    return {
        "replay_run_id": payload.get("replay_run_id"),
        "replay_mode": str(payload.get("replay_mode") or "historical_replay"),
        "source_label": str(payload.get("source_label") or "simulated_scheduler"),
        "start_date": payload.get("start_date"),
        "end_date": payload.get("end_date"),
        "totals": totals,
        "final_outcome_summary": final,
        "does_not_satisfy_phase0_gate": True,
        "production_scheduler_allowed": False,
        "warnings": warnings,
        "limitations": list(payload.get("limitations", ())),
    }


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _warnings(payload: dict[str, Any], final: dict[str, Any]) -> list[str]:
    warnings = ["simulated_scheduler", "not_production_readiness"]
    if _int(final.get("missing_benchmark")) > 0:
        warnings.append("missing_benchmark")
    if _int(final.get("missing_industry_benchmark")) > 0:
        warnings.append("missing_industry_benchmark")
    if _int(final.get("pending_insufficient_future_data")) > 0:
        warnings.append("pending_insufficient_future_data")
    for day in payload.get("days", ()):
        if not isinstance(day, dict):
            continue
        diagnostics = day.get("diagnostics", ())
        if isinstance(diagnostics, str):
            diagnostics = (diagnostics,)
        if "source_missing_screening_matrix" in diagnostics:
            warnings.append("source_missing_screening_matrix")
            break
    return _dedupe(warnings)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
