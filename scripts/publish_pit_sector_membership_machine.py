"""以受控 machine identity 發布並讀回 current-day PIT sector candidate。"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.pit_sector_machine_publisher import (  # noqa: E402
    MACHINE_PIT_OPERATIONAL_CONSUMER_VERSION,
    MachinePITSourceError,
    consume_machine_pit_operational_candidate,
    publish_machine_pit_operational_candidate,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--decision-at",
        type=_parse_decision_at,
        required=True,
        help="明確含時區的 consumer decision_at；不得用日期代替 timestamp",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt_path = args.receipt_path.expanduser().resolve()
        output_path = args.output.expanduser().resolve()
        _require_temp_path(receipt_path, field_name="receipt")
        _require_temp_path(output_path, field_name="output")
        published = publish_machine_pit_operational_candidate(
            receipt_path,
            output_path=output_path,
            decision_at=args.decision_at,
        )
        consumed = consume_machine_pit_operational_candidate(
            output_path,
            decision_at=args.decision_at,
        )
        summary: dict[str, Any] = {
            "status": consumed["status"],
            "consumer_version": MACHINE_PIT_OPERATIONAL_CONSUMER_VERSION,
            "publisher_id": consumed["publisher_id"],
            "operational_publication_path": str(output_path),
            "operational_file_hash": published["operational_file_hash"],
            "publisher_code_sha256": consumed["publisher_code_sha256"],
            "attestation_signature": consumed["attestation_signature"],
            "decision_at": consumed["consumer_decision_at"],
            "available_at": consumed["available_at"],
            "effective_from": consumed["effective_from"],
            "capture_id": consumed["capture_id"],
            "row_count": consumed["row_count"],
            "source_ids": consumed["source_ids"],
            "source_custody_verified": consumed["source_custody_verified"],
            "rows_rebuilt_from_raw": consumed["rows_rebuilt_from_raw"],
            "formal_consumer_compatible": False,
            "candidate_only": True,
            "formal_oos_allowed": False,
            "production_action_allowed": False,
        }
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, TypeError, ValueError, MachinePITSourceError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(error).__name__,
                    "reason": str(error),
                    "formal_oos_allowed": False,
                    "production_action_allowed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2


def _parse_decision_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "decision-at 必須是含時區的 ISO 8601 時間"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("decision-at 必須包含時區")
    return parsed


def _require_temp_path(path: Path, *, field_name: str) -> None:
    try:
        path.relative_to(Path(tempfile.gettempdir()).resolve())
    except ValueError as error:
        raise ValueError(f"{field_name} must be under operating-system TEMP") from error


if __name__ == "__main__":
    raise SystemExit(main())
