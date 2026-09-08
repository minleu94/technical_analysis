"""輸出 Formal／ML 三項 input 的唯讀 owner review packet。"""

from __future__ import annotations

import argparse
from datetime import datetime
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
    parser.add_argument(
        "--pit-machine-receipt",
        type=Path,
        help="明確指定的 current natural-day PIT machine receipt（只讀 TEMP）",
    )
    parser.add_argument(
        "--pit-machine-publication",
        type=Path,
        help="明確指定的受控 machine operational publication（只讀 TEMP）",
    )
    parser.add_argument(
        "--pit-machine-decision-at",
        type=_parse_decision_at,
        help="machine PIT consumer decision_at（含時區 ISO 8601；省略時使用現在時間）",
    )
    parser.add_argument(
        "--formal-ledger-path",
        type=Path,
        help="明確指定的正式 causal non-cash ledger manifest；只讀 consumer 驗證",
    )
    parser.add_argument(
        "--formal-rule-history-path",
        type=Path,
        help="明確指定的正式 Rule Champion history manifest；只讀 consumer 驗證",
    )
    parser.add_argument(
        "--formal-sector-path",
        type=Path,
        help="明確指定的正式 PIT sector sidecar；只讀 assembler 驗證",
    )
    parser.add_argument(
        "--formal-training-as-of",
        help="三項正式 consumer 共用的含時區 ISO 8601 cutoff",
    )
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
            pit_machine_receipt_path=args.pit_machine_receipt,
            pit_machine_publication_path=args.pit_machine_publication,
            pit_machine_decision_at=args.pit_machine_decision_at,
            formal_ledger_path=args.formal_ledger_path,
            formal_rule_history_path=args.formal_rule_history_path,
            formal_sector_path=args.formal_sector_path,
            formal_training_as_of=args.formal_training_as_of,
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


def _parse_decision_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "pit-machine-decision-at 必須是含時區的 ISO 8601 時間"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError(
            "pit-machine-decision-at 必須包含時區"
        )
    return parsed
if __name__ == "__main__":
    raise SystemExit(main())
