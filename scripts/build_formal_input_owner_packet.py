"""輸出 Formal／ML 三項 input 的唯讀 owner review packet。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.formal_input_owner_packet import (  # noqa: E402
    build_formal_input_owner_packet,
    render_markdown,
    validate_output_path,
)
from runtime.console_encoding import configure_utf8_console  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    configure_utf8_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory-path", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--owner-role", default="")
    parser.add_argument("--reviewer-role", default="")
    parser.add_argument("--max-candidates-per-input", type=int, default=8)
    parser.add_argument("--json-output", action="store_true")
    args = parser.parse_args(argv)

    try:
        output_json = validate_output_path(args.output_json, inventory_path=args.inventory_path)
        output_markdown = (
            validate_output_path(args.markdown_output, inventory_path=args.inventory_path)
            if args.markdown_output is not None
            else None
        )
        packet = build_formal_input_owner_packet(
            args.inventory_path,
            owner_role=args.owner_role,
            reviewer_role=args.reviewer_role,
            max_candidates_per_input=args.max_candidates_per_input,
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
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        payload: dict[str, Any] = {"status": "rejected", "error": str(exc)}
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
