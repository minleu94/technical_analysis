"""唯讀檢查 prospective formal simulated portfolio clock manifest。"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.prospective_formal_clock import (  # noqa: E402
    inspect_clock_manifest,
)


def _parse_now(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--now must include timezone")
    return parsed


def _read_calendar_evidence(path: Path | None) -> Mapping[str, object] | None:
    if path is None:
        return None
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("calendar evidence root must be an object")
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="唯讀檢查 prospective formal simulated portfolio clock。"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--now",
        required=True,
        help="帶 timezone 的檢查時間，例如 2026-08-14T09:00:00+08:00",
    )
    parser.add_argument("--calendar-evidence", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        help="可選的 readiness JSON 輸出；不指定時只輸出 stdout，不建立檔案。",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        report = inspect_clock_manifest(
            args.manifest,
            now=_parse_now(args.now),
            calendar_evidence=_read_calendar_evidence(args.calendar_evidence),
        )
        if args.output is not None:
            output = args.output.expanduser().resolve()
            if not output.parent.exists():
                raise ValueError("--output parent directory must already exist")
            output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if report.get("status") == "ready_for_activation" else 1
    except Exception as error:  # pragma: no cover - CLI fail-closed boundary
        print(
            json.dumps(
                {
                    "schema_version": "prospective-formal-clock-readiness.v1",
                    "status": "blocked",
                    "formal_oos_allowed": False,
                    "production_blend_alpha_bp": 0,
                    "broker_order_allowed": False,
                    "read_only": True,
                    "secret_values_emitted": False,
                    "blockers": [f"{type(error).__name__}: {error}"],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
