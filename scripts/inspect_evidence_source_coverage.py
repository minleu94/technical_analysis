from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.decision_desk_snapshot_repository import DecisionDeskSnapshotRepository
from app_module.decision_desk_snapshot_storage_dtos import section_is_ready
from app_module.recommendation_repository import RecommendationRepository
from data_module.config import TWStockConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect evidence source coverage for read-only planning.")
    parser.add_argument("--db-path")
    parser.add_argument("--result-id")
    parser.add_argument("--decision-date")
    parser.add_argument("--json-output", action="store_true", help="Emit JSON summary. JSON is the default output.")
    parser.add_argument("--data-root")
    parser.add_argument("--output-root")
    return parser


def _config_from_args(args: argparse.Namespace) -> TWStockConfig:
    kwargs: dict[str, Any] = {}
    if args.data_root:
        kwargs["data_root"] = Path(args.data_root)
    if args.output_root:
        kwargs["output_root"] = Path(args.output_root)
    config = TWStockConfig(**kwargs)
    if args.db_path:
        config.db_file = Path(args.db_path)
        config.db_file.parent.mkdir(parents=True, exist_ok=True)
    return config


def _latest_recommendation(repository: RecommendationRepository, result_id: str | None):
    if result_id:
        return repository.load_result(result_id)
    rows = repository.list_results()
    if not rows:
        return None
    latest = sorted(rows, key=lambda item: str(item.get("created_at") or ""), reverse=True)[0]
    return repository.load_result(str(latest.get("result_id") or ""))


def _has_payload(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        return bool(value)
    return bool(list(value))


def _readiness(*, recommendation_ready: bool, snapshot_ready: bool, exclusion_ready: bool) -> str:
    if not recommendation_ready or not snapshot_ready:
        return "not_ready"
    if not exclusion_ready:
        return "dry_run_only"
    return "ready_for_design"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = _config_from_args(args)
    recommendation_repository = RecommendationRepository(config)
    snapshot_repository = DecisionDeskSnapshotRepository(config)

    recommendation = _latest_recommendation(recommendation_repository, args.result_id)
    snapshots = snapshot_repository.list_snapshots()
    latest_snapshot = (
        snapshot_repository.latest_before_or_on(args.decision_date)
        if args.decision_date
        else (snapshots[0] if snapshots else None)
    )

    recommendation_available = recommendation is not None
    why_not_ready = _has_payload(getattr(recommendation, "why_not_payload_json", None)) if recommendation else False
    liquidity_ready = _has_payload(getattr(recommendation, "liquidity_gate_payload_json", None)) if recommendation else False
    exclusion_ready = why_not_ready and liquidity_ready
    snapshot_count = len(snapshots)
    watchlist_ready = latest_snapshot is not None and section_is_ready(latest_snapshot.watchlist_trigger_json)
    portfolio_ready = latest_snapshot is not None and section_is_ready(latest_snapshot.portfolio_alert_json)
    risk_prompt_ready = latest_snapshot is not None and section_is_ready(latest_snapshot.risk_prompt_json)

    blocking_gaps: list[str] = []
    if not recommendation_available:
        blocking_gaps.append("recommendation_persisted_missing")
    if snapshot_count == 0:
        blocking_gaps.append("decision_desk_snapshot_missing")
    if latest_snapshot is not None and not watchlist_ready:
        blocking_gaps.append("watchlist_trigger_snapshot_section_missing")
    if latest_snapshot is not None and not portfolio_ready:
        blocking_gaps.append("portfolio_alert_snapshot_section_missing")
    if latest_snapshot is not None and not risk_prompt_ready:
        blocking_gaps.append("risk_prompt_snapshot_section_missing")
    if not why_not_ready:
        blocking_gaps.append("why_not_exclusion_payload_missing")
    if not liquidity_ready:
        blocking_gaps.append("liquidity_gate_payload_missing")

    summary = {
        "recommendation_persisted_available": recommendation_available,
        "recommendation_exclusion_payload_available": exclusion_ready,
        "decision_desk_snapshots_count": snapshot_count,
        "latest_decision_desk_snapshot_date": latest_snapshot.decision_date if latest_snapshot is not None else None,
        "watchlist_trigger_capture_ready": watchlist_ready,
        "portfolio_alert_capture_ready": portfolio_ready,
        "risk_prompt_capture_ready": risk_prompt_ready,
        "why_not_capture_ready": why_not_ready,
        "liquidity_gate_capture_ready": liquidity_ready,
        "scheduler_readiness": _readiness(
            recommendation_ready=recommendation_available,
            snapshot_ready=snapshot_count > 0 and watchlist_ready and portfolio_ready and risk_prompt_ready,
            exclusion_ready=exclusion_ready,
        ),
        "blocking_gaps": blocking_gaps,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
