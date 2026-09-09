"""把已驗證的 TEMP PIT machine capture 持久化到 repository archive。

這個入口只接受呼叫端明確指定的三份 TEMP publication／receipt／operational
bytes，先用當下 code 與受控 HMAC 完整重驗，再以既有 archive writer 將相同
bytes create-only 複製到 repository publication root。它支援 D-1 capture 在
D 08:30 前可被 timestamp-gated consumer 使用；``effective_from`` 永遠保留
實際 capture 的台北自然日。它不寫 D 原始資料、SQLite、controlled path 或
broker，也不重新抓官方來源。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.formal_daily_input_producer import (  # noqa: E402
    _archive_pit_candidate,
)
from data_module.pit_sector_machine_publisher import (  # noqa: E402
    validate_machine_pit_operational_candidate,
)
from data_module.pit_sector_membership_machine import (  # noqa: E402
    validate_machine_pit_receipt,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publication-path", type=Path, required=True)
    parser.add_argument("--receipt-path", type=Path, required=True)
    parser.add_argument("--operational-path", type=Path, required=True)
    parser.add_argument("--publication-root", type=Path, required=True)
    parser.add_argument("--decision-at", required=True)
    return parser


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("--decision-at must be an aware ISO timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--decision-at must include timezone")
    return parsed.astimezone(timezone.utc)


def _temp_path(path: Path, field_name: str) -> Path:
    import tempfile

    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(Path(tempfile.gettempdir()).resolve())
    except ValueError as error:
        raise ValueError(f"{field_name} must be under OS TEMP") from error
    return resolved


def main(argv: Sequence[str] | None = None) -> int:
    from runtime.console_encoding import configure_utf8_console

    configure_utf8_console()
    args = _parser().parse_args(argv)
    try:
        publication_path = _temp_path(args.publication_path, "publication")
        receipt_path = _temp_path(args.receipt_path, "receipt")
        operational_path = _temp_path(args.operational_path, "operational")
        decision_at = _parse_datetime(args.decision_at)
        publication_root = args.publication_root.expanduser().resolve()
        receipt = validate_machine_pit_receipt(receipt_path, now=decision_at)
        operational = validate_machine_pit_operational_candidate(
            operational_path,
            decision_at=decision_at,
            now=decision_at,
        )
        if Path(str(receipt.get("publication_path"))).resolve() != publication_path:
            raise ValueError("receipt publication_path does not match explicit input")
        if Path(str(operational.get("receipt_path"))).resolve() != receipt_path:
            raise ValueError("operational receipt_path does not match explicit input")
        result: dict[str, object] = {
            "status": "machine_verified_candidate",
            "producer": receipt.get("producer", "data_module.pit_sector_membership_machine"),
            "producer_version": receipt.get("producer_version", "official-company-basic-first-seen.v1"),
            "producer_code_sha256": receipt.get(
                "consumer_code_sha256", operational.get("publisher_code_sha256")
            ),
            "consumer": receipt.get("consumer", "data_module.pit_sector_membership_machine"),
            "consumer_verified": True,
            "publication_path": str(publication_path),
            "publication_file_hash": receipt.get("publication_file_hash"),
            "publication_content_hash": receipt.get("publication_content_hash"),
            "publication_content_sha256": receipt.get("publication_content_hash"),
            "receipt_path": str(receipt_path),
            "receipt_file_hash": receipt.get("receipt_file_hash"),
            "operational_path": str(operational_path),
            "operational_file_hash": operational.get("operational_file_hash"),
            "publication_content_hash_semantics": "publication.content_sha256",
            "receipt_content_hash": receipt.get("content_sha256"),
            "decision_at": operational.get("decision_at"),
            "effective_from": operational.get("effective_from"),
            "available_at": operational.get("available_at"),
            "capture_id": operational.get("capture_id"),
            "row_count": operational.get("row_count"),
            "source_ids": operational.get("source_ids"),
            "formal_consumer_compatible": False,
            "candidate_only": True,
            "historical_backfill_claimed": False,
            "formal_oos_allowed": False,
            "promotion_eligible": False,
            "broker_order_allowed": False,
        }
        archive = _archive_pit_candidate(
            publication_root=publication_root,
            pit_result=result,
            archive_cutoff=None,
        )
    except (OSError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(error).__name__,
                    "reason": str(error),
                    "formal_oos_allowed": False,
                    "production_action_allowed": False,
                    "writes_source_database": False,
                    "writes_formal_controlled_paths": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2

    print(
        json.dumps(
            {
                "status": "durable_candidate_archived",
                "archive": archive,
                "effective_from": result.get("effective_from"),
                "available_at": result.get("available_at"),
                "decision_at": result.get("decision_at"),
                "candidate_only": True,
                "formal_consumer_compatible": False,
                "formal_oos_allowed": False,
                "writes_source_database": False,
                "writes_formal_controlled_paths": False,
                "secret_values_emitted": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
