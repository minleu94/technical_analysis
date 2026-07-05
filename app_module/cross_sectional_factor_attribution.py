"""Read-only attribution summary for V1.6 factor snapshots."""

from __future__ import annotations

from collections import Counter
from typing import Any

from app_module.cross_sectional_factor_repository import CrossSectionalFactorRepository


def build_cross_sectional_factor_attribution_summary(
    repository: CrossSectionalFactorRepository,
    *,
    snapshot_id: str,
) -> dict[str, Any]:
    snapshot = repository.get_snapshot(snapshot_id)
    if snapshot is None:
        raise ValueError(f"snapshot not found: {snapshot_id}")
    rows = repository.list_rows(snapshot_id)

    factor_counts = Counter(row.factor_name for row in rows)
    quality_counts = Counter(row.quality.value for row in rows)
    rank_bucket_counts = Counter(_rank_bucket(row.quantile_bp) for row in rows)
    sector_counts = Counter(row.sector or "missing" for row in rows)
    concept_basket_counts = Counter(row.concept_basket or "missing" for row in rows)
    diagnostic_counts = Counter(item.code for item in snapshot.diagnostics)

    return {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_hash": snapshot.snapshot_hash,
        "decision_date": snapshot.decision_date.isoformat(),
        "factor_set_version": snapshot.factor_set_version,
        "universe_id": snapshot.universe_id,
        "source_version": snapshot.source_version,
        "row_count": len(rows),
        "factor_counts": _sorted_counter(factor_counts),
        "quality_counts": _sorted_counter(quality_counts),
        "rank_bucket_counts": _sorted_counter(rank_bucket_counts),
        "sector_counts": _sorted_counter(sector_counts),
        "concept_basket_counts": _sorted_counter(concept_basket_counts),
        "diagnostic_counts": _sorted_counter(diagnostic_counts),
        "metadata": dict(snapshot.metadata),
    }


def render_cross_sectional_factor_summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        f"# Cross-sectional Factor Snapshot {summary['snapshot_id']}",
        "",
        f"- decision_date: {summary['decision_date']}",
        f"- factor_set_version: {summary['factor_set_version']}",
        f"- universe_id: {summary['universe_id']}",
        f"- row_count: {summary['row_count']}",
        "",
    ]
    for title, key in (
        ("Factor Counts", "factor_counts"),
        ("Quality Counts", "quality_counts"),
        ("Rank Bucket Counts", "rank_bucket_counts"),
        ("Sector Counts", "sector_counts"),
        ("Concept Basket Counts", "concept_basket_counts"),
        ("Diagnostic Counts", "diagnostic_counts"),
    ):
        lines.append(f"## {title}")
        counts = summary.get(key, {})
        if not counts:
            lines.append("- none")
        else:
            lines.extend(f"- {name}: {count}" for name, count in counts.items())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _rank_bucket(value: int | None) -> str:
    if value is None:
        return "missing"
    parsed = int(value)
    if parsed <= 2000:
        return "0-2000"
    if parsed <= 4000:
        return "2001-4000"
    if parsed <= 6000:
        return "4001-6000"
    if parsed <= 8000:
        return "6001-8000"
    return "8001-10000"


def _sorted_counter(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: item[0]))
