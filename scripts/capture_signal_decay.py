from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.signal_decay_service import SignalDecayService, is_production_like_db
from data_module.config import TWStockConfig


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture read-only signal decay observations.")
    parser.add_argument("--observation-date", required=True)
    parser.add_argument("--db-path")
    parser.add_argument("--scope", choices=["event_type", "event_family", "strategy_version", "profile", "all"], default="all")
    parser.add_argument("--scope-id")
    parser.add_argument("--short-window-events", type=int, default=30)
    parser.add_argument("--long-window-events", type=int, default=120)
    parser.add_argument("--short-window-days", type=int, default=60)
    parser.add_argument("--long-window-days", type=int, default=240)
    parser.add_argument("--min-sample-size", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--allow-production-db-confirm", action="store_true")
    parser.add_argument("--json-output", action="store_true")
    parser.add_argument("--data-root")
    parser.add_argument("--output-root")
    return parser


def _config(args: argparse.Namespace) -> TWStockConfig:
    kwargs: dict[str, Path] = {}
    if args.data_root:
        kwargs["data_root"] = Path(args.data_root)
    if args.output_root:
        kwargs["output_root"] = Path(args.output_root)
    config = TWStockConfig(**kwargs)
    config.use_sqlite = True
    if args.db_path:
        config.db_file = Path(args.db_path)
    return config


def run_capture(args: argparse.Namespace) -> dict[str, Any]:
    confirm = bool(args.confirm)
    if args.dry_run and args.confirm:
        raise ValueError("--dry-run and --confirm are mutually exclusive")
    if confirm and not args.db_path:
        raise ValueError("confirm requires explicit --db-path")
    config = _config(args)
    if confirm and is_production_like_db(config, args.db_path) and not args.allow_production_db_confirm:
        raise ValueError("production-like DB confirm requires --allow-production-db-confirm")
    service = SignalDecayService(config)
    return service.capture_decay(
        observation_date=args.observation_date,
        scope=args.scope,
        scope_id=args.scope_id,
        short_window_events=args.short_window_events,
        long_window_events=args.long_window_events,
        short_window_days=args.short_window_days,
        long_window_days=args.long_window_days,
        min_sample_size=args.min_sample_size,
        confirm=confirm,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = run_capture(args)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"scopes_evaluated: {payload['scopes_evaluated']}")
        print(f"observations_created: {payload['observations_created']}")
        print(f"dry_run: {payload['dry_run']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

