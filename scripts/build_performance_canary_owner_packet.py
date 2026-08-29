"""輸出 technical／broker canary 的唯讀 owner review packet。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.performance_canary_owner_packet import (  # noqa: E402
    build_performance_canary_owner_packet,
    render_markdown,
    validate_output_path,
)
from runtime.console_encoding import configure_utf8_console  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    configure_utf8_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--technical-preview", type=Path, required=True)
    parser.add_argument("--worker-recovery", type=Path, required=True)
    parser.add_argument("--broker-canary", type=Path, required=True)
    parser.add_argument("--direct-storage-preflight", type=Path, required=True)
    parser.add_argument("--retention-direct", type=Path, required=True)
    parser.add_argument("--retention-ooc", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--owner-role", default="")
    parser.add_argument("--reviewer-role", default="")
    parser.add_argument("--json-output", action="store_true")
    args = parser.parse_args(argv)
    input_paths = {
        "technical_preview": args.technical_preview,
        "worker_recovery": args.worker_recovery,
        "broker_canary": args.broker_canary,
        "direct_storage_preflight": args.direct_storage_preflight,
        "retention_direct": args.retention_direct,
        "retention_ooc": args.retention_ooc,
    }
    try:
        output_json = validate_output_path(args.output_json, input_paths=input_paths)
        output_markdown = (
            validate_output_path(args.markdown_output, input_paths=input_paths)
            if args.markdown_output is not None
            else None
        )
        packet = build_performance_canary_owner_packet(
            technical_preview_path=args.technical_preview,
            worker_recovery_path=args.worker_recovery,
            broker_canary_path=args.broker_canary,
            direct_storage_preflight_path=args.direct_storage_preflight,
            retention_direct_path=args.retention_direct,
            retention_ooc_path=args.retention_ooc,
            owner_role=args.owner_role,
            reviewer_role=args.reviewer_role,
        )
        serialized = json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        output_json.write_text(serialized, encoding="utf-8")
        if output_markdown is not None:
            output_markdown.write_text(render_markdown(packet), encoding="utf-8")
        print(serialized if args.json_output else render_markdown(packet), end="")
        return 0
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "rejected", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
