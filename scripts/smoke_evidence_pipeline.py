from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.evidence_capture_service import EvidenceCaptureService
from app_module.evidence_event_importer_dtos import EvidenceCaptureRequest
from app_module.evidence_event_importers import RecommendationEvidenceImporter
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.evidence_event_service import EvidenceEventService
from app_module.forward_performance_service import ForwardPerformanceService
from app_module.recommendation_repository import RecommendationRepository
from data_module.config import TWStockConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an evidence pipeline smoke on an isolated SQLite database.")
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--recommendation-result-id", required=True)
    parser.add_argument("--decision-date", required=True)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--windows", default="5,10,20,60")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true", help="Force dry-run. This is the default without --confirm.")
    parser.add_argument("--confirm", action="store_true", help="Write to the selected DB. Without this flag, no events or outcomes are written.")
    parser.add_argument("--json-output", action="store_true", help="Emit JSON summary. JSON is the default output.")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    return parser


def _parse_windows(value: str) -> tuple[int, ...]:
    windows = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    if not windows:
        raise ValueError("--windows must include at least one integer")
    return windows


def _config_from_args(args: argparse.Namespace) -> TWStockConfig:
    kwargs: dict[str, Any] = {}
    if args.data_root is not None:
        kwargs["data_root"] = args.data_root
    if args.output_root is not None:
        kwargs["output_root"] = args.output_root
    config = TWStockConfig(**kwargs)
    config.db_file = Path(args.db_path)
    config.db_file.parent.mkdir(parents=True, exist_ok=True)
    return config


def _sample_events(repository: EvidenceEventRepository, *, limit: int = 5) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "event_id": event.event_id,
            "event_hash": event.event_hash,
            "event_type": event.event_type.value,
            "symbol": event.symbol,
            "source_id": event.source_id,
        }
        for event in repository.list_events(limit=limit)
    )


def _sample_outcomes(repository: EvidenceEventRepository, *, limit: int = 5) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "outcome_id": outcome.outcome_id,
            "event_id": outcome.event_id,
            "window_days": outcome.window_days,
            "outcome_status": outcome.outcome_status.value,
            "return_basis": outcome.return_basis,
            "forward_return_bp": outcome.forward_return_bp,
            "benchmark_excess_bp": outcome.benchmark_excess_bp,
            "industry_excess_bp": outcome.industry_excess_bp,
        }
        for outcome in repository.list_outcomes()[:limit]
    )


def _quality_counts(repository: EvidenceEventRepository) -> dict[str, int]:
    event_counts = Counter(event.data_quality.value for event in repository.list_events())
    outcome_counts = Counter(outcome.data_quality.value for outcome in repository.list_outcomes())
    combined = event_counts + outcome_counts
    return dict(sorted(combined.items()))


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    config = _config_from_args(args)
    windows = _parse_windows(args.windows)
    dry_run = bool(args.dry_run or not args.confirm)
    repository = EvidenceEventRepository(config)
    capture_service = EvidenceCaptureService(
        EvidenceEventService(repository),
        {
            "recommendation": RecommendationEvidenceImporter(RecommendationRepository(config)),
        },
    )
    capture = capture_service.capture(
        EvidenceCaptureRequest(
            source="recommendation",
            decision_date=args.decision_date,
            start_date=args.start_date,
            end_date=args.end_date,
            result_id=args.recommendation_result_id,
            limit=args.limit,
            dry_run=dry_run,
            confirm=bool(args.confirm),
        )
    )

    outcome_summary = None
    if not dry_run:
        outcome_summary = ForwardPerformanceService(config, repository).calculate(
            windows=windows,
            dry_run=False,
            decision_date=args.decision_date,
            start_date=args.start_date,
            end_date=args.end_date,
            event_type="recommendation_included",
            limit=args.limit,
        )

    outcomes = repository.list_outcomes()
    outcome_status_counts = dict(sorted(Counter(item.outcome_status.value for item in outcomes).items()))
    event_type_counts = (
        capture.event_type_counts
        if dry_run
        else dict(sorted(Counter(event.event_type.value for event in repository.list_events()).items()))
    )
    summary = {
        "dry_run": dry_run,
        "db_path": str(config.db_file),
        "source": "recommendation",
        "recommendation_result_id": args.recommendation_result_id,
        "decision_date": args.decision_date,
        "events_seen": capture.events_seen,
        "events_inserted": capture.events_inserted,
        "events_skipped_duplicate": capture.events_skipped_duplicate,
        "events_failed": capture.events_failed,
        "outcomes_attempted": 0 if outcome_summary is None else outcome_summary.events_ready * len(windows),
        "outcomes_created": 0 if outcome_summary is None else outcome_summary.outcomes_created,
        "outcomes_updated": 0 if outcome_summary is None else outcome_summary.outcomes_updated,
        "outcomes_pending": 0 if outcome_summary is None else outcome_summary.pending_insufficient_future_data,
        "missing_event_price": 0 if outcome_summary is None else outcome_summary.missing_event_price,
        "missing_outcome_price": 0 if outcome_summary is None else outcome_summary.missing_outcome_price,
        "missing_benchmark": 0 if outcome_summary is None else outcome_summary.missing_benchmark,
        "missing_industry_benchmark": 0 if outcome_summary is None else outcome_summary.missing_industry_benchmark,
        "warnings_count": capture.warnings_count + (0 if outcome_summary is None else outcome_summary.warnings_count),
        "event_type_counts": dict(sorted(event_type_counts.items())),
        "outcome_status_counts": outcome_status_counts,
        "quality_counts": capture.quality_counts if dry_run else _quality_counts(repository),
        "sample_events": list(capture.sample_events if dry_run else _sample_events(repository)),
        "sample_outcomes": list(_sample_outcomes(repository)),
        "return_basis": "close_to_close_event_date",
    }
    return summary


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(json.dumps(run_smoke(args), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

