"""以實際 decision_at 派送 PIT machine candidate 到 assembler 的記憶體 spool。

這個 bounded daily dispatch 只讀取已由受控 machine publisher 簽章的
operational publication，讓既有 ``_load/_spool_sector_memberships`` 驗證
相同 rows 與 custody。spool 使用 in-memory SQLite，輸出只寫 TEMP status；
不建立正式 training publication、不寫 D 原始資料，也不授予 Formal OOS。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module import portfolio_ml_dataset_assembler as dataset_assembler  # noqa: E402
from data_module.pit_sector_machine_publisher import (  # noqa: E402
    MachinePITSourceError,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operational-publication", type=Path, required=True)
    parser.add_argument("--decision-at", type=_parse_decision_at, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--confirm-readonly",
        action="store_true",
        help="確認只在 in-memory SQLite 進行 daily candidate dispatch",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if not args.confirm_readonly:
            raise ValueError("daily PIT dispatch requires --confirm-readonly")
        operational_path = args.operational_publication.expanduser().resolve()
        output_path = args.output.expanduser().resolve()
        _require_temp_path(operational_path, field_name="operational publication")
        _require_temp_path(output_path, field_name="dispatch output")
        if output_path == operational_path:
            raise ValueError("dispatch output must not overwrite operational publication")
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        try:
            dataset_assembler._initialize_spool(connection)
            manifest_hash, row_count = dataset_assembler._spool_sector_memberships(
                connection,
                None,
                training_as_of=args.decision_at,
                machine_operational_path=operational_path,
                machine_now=datetime.now(timezone.utc),
            )
            persisted_count = int(
                connection.execute("SELECT COUNT(*) FROM sector_memberships").fetchone()[0]
            )
        finally:
            connection.close()
        payload: dict[str, Any] = {
            "schema_version": "pit-sector-membership-machine-daily-dispatch.v1",
            "status": "machine_verified",
            "dispatcher": "scripts.scheduled.run_pit_sector_membership_machine_dispatch",
            "operational_publication_path": str(operational_path),
            "operational_publication_file_hash": dataset_assembler._file_sha256(
                operational_path
            ),
            "decision_at": args.decision_at.isoformat(),
            "sector_manifest_hash": manifest_hash,
            "row_count": row_count,
            "rows_spooled_to_memory": persisted_count,
            "source_custody_verified": True,
            "rows_rebuilt_from_raw": True,
            "formal_consumer_compatible": False,
            "candidate_only": True,
            "formal_oos_allowed": False,
            "production_action_allowed": False,
            "decision_reason": (
                "operational machine publication was revalidated at explicit decision_at "
                "and consumed through assembler sector spool in memory"
            ),
        }
        _create_json(output_path, payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, TypeError, ValueError, sqlite3.Error, MachinePITSourceError) as error:
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


def _create_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(
                (
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                ).encode("utf-8")
            )
            stream.flush()
    except FileExistsError as error:
        raise ValueError(f"dispatch output already exists: {path}") from error


if __name__ == "__main__":
    raise SystemExit(main())
