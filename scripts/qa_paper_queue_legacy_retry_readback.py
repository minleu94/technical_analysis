"""唯讀驗證 legacy Paper queue receipt 的同日 retry 與跨日封鎖。

此 QA 入口只接受 caller 明確提供的 recommendation、行情、日曆與 receipt
root。它把 receipt bytes 複製到指定 output 下的隔離 readback root，讓
``resolve_pending_recommendation`` 可以完整執行而不改寫正式 receipt。來源
recommendation／market／原 receipt 只以 read-only 方式讀取；輸出 JSON 綁定
讀回 hash，沒有 Formal credit、歷史補造或 broker side effect。
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import uuid
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.official_trading_calendar import OfficialTradingCalendar  # noqa: E402
from data_module.paper_daily_execution_producer import (  # noqa: E402
    _load_queue_receipts,
    resolve_pending_recommendation,
)


TAIPEI = ZoneInfo("Asia/Taipei")
SCHEMA_VERSION = "paper-queue-legacy-retry-readback.v1"


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _hash_file(path: Path) -> str:
    return _hash_bytes(path.read_bytes())


def _write_hashed_json(path: Path, body: Mapping[str, object]) -> None:
    payload = dict(body)
    payload["content_sha256"] = _hash_bytes(
        _canonical(payload).encode("utf-8")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write((_canonical(payload) + "\n").encode("utf-8"))
        stream.flush()
        import os

        os.fsync(stream.fileno())


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--observed must include timezone")
    return parsed.astimezone(timezone.utc)


def _copy_receipts(source: Path, output: Path) -> tuple[dict[str, str], dict[str, str]]:
    source_files = {
        path.name: _hash_file(path)
        for path in sorted(source.glob("*.json"))
        if path.is_file()
    }
    output.mkdir(parents=True, exist_ok=False)
    copied: dict[str, str] = {}
    for name in sorted(source_files):
        source_path = source / name
        target = output / name
        shutil.copyfile(source_path, target)
        copied[name] = _hash_file(target)
    return source_files, copied


def _projection(rows: tuple[object, ...], issues: tuple[str, ...]) -> dict[str, object]:
    normalized: list[dict[str, object]] = []
    for row in rows:
        normalized.append(
            {
                "state": getattr(row, "state", None),
                "execution_date": (
                    None
                    if getattr(row, "execution_date", None) is None
                    else getattr(row, "execution_date").isoformat()
                ),
                "source_result_id": getattr(row, "source_result_id", None),
                "source_file_hash": getattr(row, "source_file_hash", None),
                "recorded_at": (
                    None
                    if getattr(row, "recorded_at", None) is None
                    else getattr(row, "recorded_at").isoformat()
                ),
            }
        )
    return {
        "valid_count": len(normalized),
        "pending_count": sum(
            item["state"] == "pending_execution" for item in normalized
        ),
        "rows": normalized,
        "issues": list(issues),
    }


def build_report(
    *,
    recommendation_root: Path,
    market_db: Path,
    receipt_root: Path,
    calendar_cache: Path,
    observed: datetime,
    output_root: Path,
) -> dict[str, object]:
    recommendation_root = recommendation_root.expanduser().resolve()
    market_db = market_db.expanduser().resolve()
    receipt_root = receipt_root.expanduser().resolve()
    calendar_cache = calendar_cache.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    if not recommendation_root.is_dir():
        raise FileNotFoundError(recommendation_root)
    if not market_db.is_file():
        raise FileNotFoundError(market_db)
    if not receipt_root.is_dir():
        raise FileNotFoundError(receipt_root)
    if not calendar_cache.exists():
        raise FileNotFoundError(calendar_cache)
    output_root.mkdir(parents=True, exist_ok=True)
    readback_root = output_root / f"legacy_receipt_readback_{uuid.uuid4().hex}"
    source_hashes_before, copied_hashes = _copy_receipts(
        receipt_root,
        readback_root / "receipts",
    )
    before_rows, before_issues = _load_queue_receipts(readback_root / "receipts")
    calendar = OfficialTradingCalendar(
        db_path=market_db,
        calendar_cache_path=calendar_cache,
    )
    selected, reason = resolve_pending_recommendation(
        recommendation_root,
        observed=observed,
        market_db=market_db,
        calendar=calendar,
        receipt_root=readback_root / "receipts",
    )
    after_rows, after_issues = _load_queue_receipts(readback_root / "receipts")
    source_hashes_after = {
        path.name: _hash_file(path)
        for path in sorted(receipt_root.glob("*.json"))
        if path.is_file()
    }
    next_day_selected, next_day_reason = resolve_pending_recommendation(
        recommendation_root,
        observed=observed.astimezone(TAIPEI).replace(tzinfo=TAIPEI)
        .astimezone(timezone.utc)
        + timedelta(days=1),
        market_db=market_db,
        calendar=calendar,
        receipt_root=readback_root / "receipts",
    )
    expected_source = "scheduled_rec_20260907_051003.json"
    calendar_failure_issues = [
        issue
        for issue in before_issues
        if "execution_date_missing" in issue
    ]
    body: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "observed_at": observed.astimezone(timezone.utc).isoformat(),
        "decision_timezone": "Asia/Taipei",
        "read_only": True,
        "formal_credit": False,
        "broker_order_allowed": False,
        "historical_backfill_claimed": False,
        "inputs": {
            "recommendation_root": str(recommendation_root),
            "market_db": str(market_db),
            "receipt_root": str(receipt_root),
            "calendar_cache": str(calendar_cache),
        },
        "legacy_receipt_readback": _projection(before_rows, before_issues),
        "resolver": {
            "selected_path": None if selected is None else str(selected),
            "selected_name": None if selected is None else selected.name,
            "reason": reason,
            "expected_source_name": expected_source,
            "expected_source_selected": (
                selected is not None and selected.name == expected_source
            ),
            "calendar_failure_issues": calendar_failure_issues,
            "calendar_failure_issues_do_not_block_pending": (
                selected is not None and bool(calendar_failure_issues)
            ),
        },
        "cross_day_guard": {
            "selected_path": (
                None if next_day_selected is None else str(next_day_selected)
            ),
            "reason": next_day_reason,
            "pending_session_missed_explicit": next_day_reason.startswith(
                "pending_execution_session_missed:"
            ),
            "late_replay_policy": "no_historical_backfill_pending_session_missed",
        },
        "receipt_copy": {
            "root": str(readback_root / "receipts"),
            "source_file_count": len(source_hashes_before),
            "copied_file_count": len(copied_hashes),
            "copy_hashes_match": all(
                source_hashes_before.get(name) == copied_hashes.get(name)
                for name in source_hashes_before
            ),
            "source_receipts_unchanged": source_hashes_before == source_hashes_after,
            "after_readback": _projection(after_rows, after_issues),
        },
    }
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recommendation-root", type=Path, required=True)
    parser.add_argument("--market-db", type=Path, required=True)
    parser.add_argument("--receipt-root", type=Path, required=True)
    parser.add_argument("--calendar-cache", type=Path, required=True)
    parser.add_argument("--observed", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = build_report(
            recommendation_root=args.recommendation_root,
            market_db=args.market_db,
            receipt_root=args.receipt_root,
            calendar_cache=args.calendar_cache,
            observed=_parse_datetime(args.observed),
            output_root=args.output.parent,
        )
        _write_hashed_json(args.output.expanduser().resolve(), report)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"blocked: {type(error).__name__}:{error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": "verified" if report["resolver"]["expected_source_selected"] else "blocked",
                "output": str(args.output.expanduser().resolve()),
                "selected": report["resolver"]["selected_name"],
                "reason": report["resolver"]["reason"],
                "cross_day_reason": report["cross_day_guard"]["reason"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["resolver"]["expected_source_selected"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
