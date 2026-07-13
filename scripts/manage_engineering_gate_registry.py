"""Append and inspect Gate 2-7 engineering control-center revisions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.engineering_gate_registry import EngineeringGateItem, EngineeringGateRegistry


TUPLE_FIELDS = (
    "required_artifacts",
    "validation_commands",
    "completion_rules",
    "prohibited_actions",
    "completion_evidence",
)


def _item(payload: dict[str, Any]) -> EngineeringGateItem:
    normalized = dict(payload)
    for name in TUPLE_FIELDS:
        normalized[name] = tuple(normalized.get(name, ()))
    return EngineeringGateItem(**normalized)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    append_parser = subparsers.add_parser("append")
    append_parser.add_argument("--input", type=Path, required=True)
    subparsers.add_parser("list-latest")
    history_parser = subparsers.add_parser("history")
    history_parser.add_argument("--item-id", required=True)
    args = parser.parse_args(argv)
    registry = EngineeringGateRegistry(args.db)
    try:
        if args.command == "append":
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            item = _item(payload)
            registry.append(item)
            output: Any = item.to_dict()
        elif args.command == "history":
            output = [item.to_dict() for item in registry.history(args.item_id)]
        else:
            output = [item.to_dict() for item in registry.list_latest()]
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
