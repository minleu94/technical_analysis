"""Run one derived, proposal-only position health transition evaluation."""

from __future__ import annotations

import argparse
from datetime import timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.position_health_transition_evaluator import (  # noqa: E402
    DEFAULT_POLICY_HASH,
    evaluate_baseline_file,
)
from scripts.scheduled.scheduled_clock import scheduled_now  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate a Paper health baseline into research-only transition proposals. "
            "Missing thesis/condition sources remain degraded."
        )
    )
    parser.add_argument("--baseline", required=True, help="derived position-health baseline JSON")
    parser.add_argument("--output-dir", required=True, help="isolated transition output directory")
    parser.add_argument("--decision-date", help="optional YYYY-MM-DD; defaults to baseline date")
    parser.add_argument("--observed-at", help="timezone-aware ISO timestamp; defaults to scheduled clock")
    parser.add_argument(
        "--transition-db",
        help="optional isolated append-only proposal repository SQLite path",
    )
    parser.add_argument("--policy-hash", default=DEFAULT_POLICY_HASH)
    parser.add_argument("--thesis-registry", help="derived append-only human thesis registry JSON")
    parser.add_argument(
        "--forward-binding",
        help="optional verified forward candidate-to-Paper-entry binding JSON",
    )
    parser.add_argument("--condition-source", help="hash-bound PIT condition source JSON")
    parser.add_argument("--metrics-source", help="hash-bound Decimal metric source JSON")
    parser.add_argument(
        "--policy-source",
        help=(
            "verified Formal machine Rule source status JSON; contributes the "
            "frozen policy identity only and never supplies a position thesis"
        ),
    )
    parser.add_argument("--calendar-cache", help="verified offline official calendar cache directory")
    parser.add_argument("--temporary-closure-cache", help="verified official temporary-closure cache directory")
    parser.add_argument("--calendar-db", help="optional read-only market DB fallback path")
    parser.add_argument("--calendar-start-date", help="optional YYYY-MM-DD calendar range start")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = scheduled_now()
    observed_at = args.observed_at or now.astimezone(timezone.utc).isoformat()
    output_dir = Path(args.output_dir).expanduser().resolve()
    transition_db = (
        Path(args.transition_db).expanduser().resolve()
        if args.transition_db
        else output_dir / "position_health_transitions.sqlite"
    )
    result = evaluate_baseline_file(
        baseline_path=args.baseline,
        output_dir=output_dir,
        observed_at=observed_at,
        decision_date=args.decision_date,
        transition_repository_path=transition_db,
        policy_hash=args.policy_hash,
        thesis_registry_path=args.thesis_registry,
        forward_binding_path=args.forward_binding,
        condition_source_path=args.condition_source,
        metrics_source_path=args.metrics_source,
        policy_source_path=args.policy_source,
        calendar_cache_path=args.calendar_cache,
        temporary_closure_path=args.temporary_closure_cache,
        calendar_db_path=args.calendar_db,
        calendar_start_date=args.calendar_start_date,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 2 if result.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
