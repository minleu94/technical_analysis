"""Produce or bind forward position thesis candidate packets.

Both commands are derived, proposal-only operations.  They never modify the
recommendation source, Paper state/ledger, Formal inputs, or the human thesis
registry.  ``produce`` can return zero for an explicitly missing policy while
leaving the packet in ``awaiting_explicit_policy``; a supplied but invalid
policy or source returns a non-zero code.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.forward_position_thesis_candidate_producer import (  # noqa: E402
    ForwardPositionThesisCandidateProducer,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a research-only forward position thesis packet or bind it "
            "to a verified Paper entry lineage."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    produce = subparsers.add_parser(
        "produce", help="record recommendation observations as immutable packets"
    )
    produce.add_argument("--recommendation", required=True, help="recommendation result JSON")
    produce.add_argument("--output-root", required=True, help="repository-isolated output root")
    produce.add_argument("--policy", help="explicit versioned invalidation/horizon policy JSON")
    produce.add_argument("--calendar-cache", help="official calendar cache fallback path")
    produce.add_argument("--decision-at", help="optional timezone-aware decision cutoff")

    bind = subparsers.add_parser(
        "bind", help="bind one packet to a verified Paper health baseline"
    )
    bind.add_argument("--candidate", required=True, help="candidate packet JSON")
    bind.add_argument("--baseline", required=True, help="position-health baseline JSON")
    bind.add_argument(
        "--paper-candidate",
        required=True,
        help="Paper execution candidate that contains the recommendation and fill proof",
    )
    bind.add_argument("--output-root", required=True, help="repository-isolated output root")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "produce":
        result = ForwardPositionThesisCandidateProducer(
            args.output_root,
            calendar_cache_path=args.calendar_cache,
        ).produce(
            args.recommendation,
            policy_path=args.policy,
            decision_at=args.decision_at,
        )
    else:
        result = ForwardPositionThesisCandidateProducer(args.output_root).bind(
            args.candidate,
            args.baseline,
            paper_candidate_path=args.paper_candidate,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    status = str(result.get("status") or "blocked")
    if args.command == "produce":
        return 0 if status in {"passed", "degraded"} else 2
    return 0 if status in {"bound", "awaiting_paper_fill", "rejected_preexisting", "ambiguous"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
