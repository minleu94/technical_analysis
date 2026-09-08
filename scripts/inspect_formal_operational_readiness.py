"""以真實主機 clock 盤點日常 Formal PIT／Rule／Paper evidence。

這個 CLI 只讀取已持久化的 archive、status、receipt 與 readiness report，
並把未登入／電池限制／排程 Query 未提供／漏跑與自然時窗等待列為具體
機器狀態。公開入口沒有 ``--now``；``now`` 只在隔離測試中注入。輸出報告
可寫入 QA 目錄，但不寫來源 SQLite、Formal controlled input、D 原始資料，
不啟動 broker 或訓練。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.formal_operational_readiness import (  # noqa: E402
    audit_formal_operational_readiness,
    write_audit_report,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--publication-root",
        type=Path,
        default=ROOT / "output" / "formal_daily_publications",
        help="持久 PIT／Formal publication root",
    )
    parser.add_argument(
        "--readiness-path",
        type=Path,
        help="唯讀 formal input readiness report；省略時只盤點自然日 evidence",
    )
    parser.add_argument(
        "--scheduler-registration",
        type=Path,
        help="唯讀 inspect_scheduled_task_registration JSON；缺少時明示未觀測",
    )
    parser.add_argument(
        "--paper-receipt-root",
        type=Path,
        help="Paper operational receipt 目錄；不指定時不把未知路徑猜成已完成",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="可選 QA report 路徑；只寫此輸出，不寫來源資料",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    args = _parser().parse_args(argv)
    try:
        report = audit_formal_operational_readiness(
            publication_root=args.publication_root,
            readiness_path=args.readiness_path,
            scheduler_registration_path=args.scheduler_registration,
            paper_receipt_root=args.paper_receipt_root,
        )
    except Exception as error:  # noqa: BLE001 - bounded read-only CLI boundary
        print(
            json.dumps(
                {
                    "schema_version": "formal-operational-readiness.v1",
                    "status": "blocked_audit_error",
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "formal_credit_allowed": False,
                    "formal_oos_allowed": False,
                    "broker_order_allowed": False,
                    "read_only": True,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    if args.output is not None:
        write_audit_report(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    # A blocked/no-credit report is a successful audit operation.  The report,
    # rather than a zero exit code, is the machine decision consumed by QA.
    return 0


def _configure_utf8_stdio() -> None:
    """讓 Windows 非 UTF-8 主控台也能輸出排程的本地化時間欄位。"""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue


if __name__ == "__main__":
    raise SystemExit(main())
