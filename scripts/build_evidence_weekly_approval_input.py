from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.evidence_weekly_approval_input import (
    build_weekly_approval_input,
    render_markdown,
    validate_output_path,
)
from runtime.console_encoding import configure_utf8_console


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export pending weekly sidecar rows into a non-approving owner/reviewer input packet."
    )
    parser.add_argument("--sidecar-path", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--owner-role", default="")
    parser.add_argument("--reviewer-role", default="")
    parser.add_argument("--include-failed", action="store_true")
    parser.add_argument("--json-output", action="store_true")
    return parser.parse_args()


def main() -> int:
    configure_utf8_console()
    args = parse_args()
    output_json = validate_output_path(args.output_json, sidecar_path=args.sidecar_path)
    output_markdown = (
        validate_output_path(args.markdown_output, sidecar_path=args.sidecar_path)
        if args.markdown_output is not None
        else None
    )
    packet = build_weekly_approval_input(
        args.sidecar_path,
        owner_role=args.owner_role,
        reviewer_role=args.reviewer_role,
        include_failed=bool(args.include_failed),
    )
    serialized = json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    output_json.write_text(serialized, encoding="utf-8")
    if output_markdown is not None:
        output_markdown.write_text(render_markdown(packet), encoding="utf-8")
    if args.json_output:
        print(serialized, end="")
    else:
        print(render_markdown(packet), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

