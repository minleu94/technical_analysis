"""Build V3.0 effectiveness manual review scaffold."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
stderr_reconfigure = getattr(sys.stderr, "reconfigure", None)
if callable(stdout_reconfigure):
    stdout_reconfigure(encoding="utf-8")
if callable(stderr_reconfigure):
    stderr_reconfigure(encoding="utf-8")

from app_module.v3_effectiveness_read_model import (
    V3EffectivenessReadModel,
    sample_v3_effectiveness_rows,
)
from app_module.v3_effectiveness_review_scaffold import V3ReviewScaffoldBuilder


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# V3.0 Effectiveness Review Scaffold",
        "",
        f"- active_milestone: {payload['active_milestone']}",
        f"- manual_validation_status: {payload['manual_validation_status']}",
        f"- production_scheduler_allowed: {str(payload['production_scheduler_allowed']).lower()}",
        f"- auto_trading: {str(payload['auto_trading']).lower()}",
        "",
        "| Review ID | Category | Event | Sufficiency | Confidence | Manual Status |",
        "|---|---|---|---|---|---|",
    ]
    for item in payload["items"]:
        lines.append(
            "| {review_id} | {review_category} | {event_family}/{event_type} | "
            "{sample_sufficiency_label} | {confidence_label} | "
            "{manual_validation_status} |".format(**item)
        )
    lines.extend(
        [
            "",
            "> All items are pending human review. No lifecycle action, no scheduler, no trading.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    if not args.sample:
        raise SystemExit("Only --sample is supported in this read-only slice.")
    report = V3EffectivenessReadModel(
        min_sample_size=args.min_sample_size
    ).build_report(rows=sample_v3_effectiveness_rows())
    return V3ReviewScaffoldBuilder().build(report).to_dict()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output")
    parser.add_argument("--min-sample-size", type=int, default=30)
    args = parser.parse_args()

    payload = build_payload(args)
    if args.format == "json":
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    else:
        text = _render_markdown(payload)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
