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
    quality_disclosures = _quality_disclosures(payload, totals, final)
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
        "quality_disclosures": quality_disclosures,
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


def _quality_disclosures(payload: dict[str, Any], totals: dict[str, Any], final: dict[str, Any]) -> list[str]:
    outcomes_created = _int(totals.get("outcomes_created"))
    pending_future_data = _int(final.get("pending_insufficient_future_data"))
    missing_benchmark = _int(final.get("missing_benchmark"))
    missing_industry = _int(final.get("missing_industry_benchmark"))
    ready_outcomes = _first_int(
        final,
        (
            "ready",
            "ready_outcomes",
            "outcomes_ready",
            "mature_outcomes",
        ),
    )
    if ready_outcomes is None:
        ready_outcomes = max(0, outcomes_created - pending_future_data)

    benchmark_total = _first_int(
        final,
        (
            "benchmark_total",
            "benchmark_coverage_total",
            "outcomes_with_benchmark_total",
        ),
    )
    if benchmark_total is None:
        benchmark_total = ready_outcomes
    benchmark_covered = _first_int(
        final,
        (
            "benchmark_covered",
            "benchmark_ready",
            "benchmark_coverage_ready",
            "outcomes_with_benchmark",
        ),
    )
    if benchmark_covered is None:
        benchmark_covered = max(0, benchmark_total - missing_benchmark)
    industry_total = _first_int(
        final,
        (
            "industry_benchmark_total",
            "industry_benchmark_coverage_total",
            "outcomes_with_industry_benchmark_total",
        ),
    )
    if industry_total is None:
        industry_total = ready_outcomes
    industry_covered = _first_int(
        final,
        (
            "industry_benchmark_covered",
            "industry_benchmark_ready",
            "industry_benchmark_coverage_ready",
            "outcomes_with_industry_benchmark",
        ),
    )
    if industry_covered is None:
        industry_covered = max(0, industry_total - missing_industry)

    disclosures = [
        str(payload.get("source_label") or "simulated_scheduler"),
        f"outcome_maturity:ready={ready_outcomes},pending_future_data={pending_future_data}",
        f"benchmark_coverage:covered={benchmark_covered},total={benchmark_total},missing={missing_benchmark}",
        f"industry_benchmark_coverage:covered={industry_covered},total={industry_total},missing={missing_industry}",
        "phase0_gate_not_satisfied:weekly_history_and_multi_day_dry_run_require_real_time_accumulation",
    ]
    source_gaps, source_gap_counts, day_count = _source_gap_tokens(payload)
    if not source_gaps:
        disclosures.append("source_gap:none_observed")
    for source_gap in source_gaps:
        disclosures.append(f"source_gap:{source_gap}")
        if day_count > 0:
            disclosures.append(f"source_gap_coverage:{source_gap}={source_gap_counts.get(source_gap, 0)}/{day_count}")
    payload_gap_added = False
    if missing_benchmark > 0:
        disclosures.append("payload_gap:missing_benchmark")
        disclosures.append(f"missing_benchmark:{missing_benchmark}")
        payload_gap_added = True
    if missing_industry > 0:
        disclosures.append("payload_gap:missing_industry_benchmark")
        disclosures.append(f"missing_industry_benchmark:{missing_industry}")
        payload_gap_added = True
    if pending_future_data > 0:
        disclosures.append("payload_gap:pending_future_data")
        disclosures.append(f"pending_future_data:{pending_future_data}")
        payload_gap_added = True
    if not payload_gap_added:
        disclosures.append("payload_gap:none_observed")
    if missing_benchmark == 0 and (missing_industry > 0 or source_gaps or pending_future_data > 0):
        disclosures.append(
            "replay_direction_assessment:"
            "market_benchmark_ready_but_industry_and_source_gaps_block_production_readiness"
        )
    return _dedupe(disclosures)


def _source_gap_tokens(payload: dict[str, Any]) -> tuple[list[str], dict[str, int], int]:
    gaps: list[str] = []
    counts: dict[str, int] = {}
    explicit_gaps = payload.get("source_gaps", ())
    if isinstance(explicit_gaps, str):
        explicit_gaps = (explicit_gaps,)
    for gap in explicit_gaps:
        if gap:
            gap_text = str(gap)
            gaps.append(gap_text)
            counts.setdefault(gap_text, 0)
    day_rows = payload.get("days", ())
    day_count = 0
    if isinstance(day_rows, dict):
        day_rows = day_rows.values()
    for day in day_rows:
        if not isinstance(day, dict):
            continue
        day_count += 1
        diagnostics = day.get("diagnostics", ())
        if isinstance(diagnostics, str):
            diagnostics = (diagnostics,)
        for diagnostic in diagnostics:
            diagnostic_text = str(diagnostic)
            if diagnostic_text.startswith("source_"):
                gaps.append(diagnostic_text)
                counts[diagnostic_text] = counts.get(diagnostic_text, 0) + 1
    return _dedupe(gaps), counts, day_count


def _first_int(mapping: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        if key not in mapping:
            continue
        try:
            return int(mapping.get(key) or 0)
        except (TypeError, ValueError):
            return None
    return None


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
