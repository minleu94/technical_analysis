"""每日建立 Decision Desk 快照並保存 Evidence Event。

本 orchestrator 只依序呼叫既有的兩個 capture CLI。兩個 CLI 都具備內容
hash 與唯一鍵保護，因此中途失敗後可安全重跑；本檔不修改 Rule、Advice、
Portfolio 狀態，也不觸發任何券商執行。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, time, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.official_trading_calendar import OfficialTradingCalendar


TASK_NAME = "baldr-decision-evidence-capture-daily"
TAIPEI = ZoneInfo("Asia/Taipei")
DECISION_TIME = time(hour=8, minute=30)
SCHEMA_VERSION = "decision-evidence-capture.v1"
DEFAULT_SUBPROCESS_TIMEOUT_SECONDS = 120
REQUIRED_SNAPSHOT_SECTIONS = frozenset(
    {
        "market_regime",
        "market_breadth",
        "sector_rotation",
        "relative_strength_liquidity",
        "watchlist_trigger",
        "portfolio_alert",
        "risk_prompt",
    }
)


@dataclass(frozen=True)
class CliRunResult:
    returncode: int
    payload: Mapping[str, Any] | None
    stderr: str
    timed_out: bool = False
    timeout_seconds: int | None = None


def next_unreached_taipei_decision_at(now: datetime | None = None) -> datetime:
    """回傳尚未到達的下一個台北 08:30 日曆決策時間。

    回傳值仍須交由 :class:`OfficialTradingCalendar` 驗證；休市或未知日期
    不得建立 Decision Desk 或 Evidence 紀錄。
    """

    current = now or datetime.now(TAIPEI)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now 必須包含時區")
    current_taipei = current.astimezone(TAIPEI)
    candidate = datetime.combine(
        current_taipei.date(),
        DECISION_TIME,
        tzinfo=TAIPEI,
    )
    if current_taipei >= candidate:
        candidate += timedelta(days=1)
    return candidate


def latest_reached_taipei_decision_at(now: datetime | None = None) -> datetime:
    """回傳最近一個已到達的台北 08:30 日曆決策時間。

    Windows 排程在台灣 08:30 前執行時，若選下一個尚未到達的 cutoff，
    capture CLI 會收到 future decision date。排程入口因此只選已到達的
    cutoff；回放／明確 ``decision_at`` 仍可保留原有語意並由下游驗證。
    """

    current = now or datetime.now(TAIPEI)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now 必須包含時區")
    current_taipei = current.astimezone(TAIPEI)
    candidate = datetime.combine(
        current_taipei.date(),
        DECISION_TIME,
        tzinfo=TAIPEI,
    )
    if candidate > current_taipei:
        candidate -= timedelta(days=1)
    return candidate


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    text = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _run_json_cli(
    command: Sequence[str],
    *,
    timeout_seconds: int = DEFAULT_SUBPROCESS_TIMEOUT_SECONDS,
) -> CliRunResult:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds 必須大於 0")
    environment = os.environ.copy()
    environment.setdefault("PYTHONUTF8", "1")
    try:
        completed = subprocess.run(
            list(command),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=environment,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stderr = exc.stderr
        if isinstance(stderr, bytes):
            stderr_text = stderr.decode("utf-8", errors="replace")
        else:
            stderr_text = str(stderr or "")
        return CliRunResult(
            returncode=124,
            payload=None,
            stderr=stderr_text.strip(),
            timed_out=True,
            timeout_seconds=timeout_seconds,
        )
    payload: Mapping[str, Any] | None = None
    try:
        decoded = json.loads(completed.stdout)
        if isinstance(decoded, dict):
            payload = decoded
    except (json.JSONDecodeError, TypeError):
        payload = None
    return CliRunResult(
        returncode=completed.returncode,
        payload=payload,
        stderr=completed.stderr.strip(),
    )


def _non_negative_int(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TypeError(f"{label} 必須是非負整數")
    return value


def _snapshot_step(result: CliRunResult) -> tuple[dict[str, Any], list[str]]:
    payload = result.payload
    failures: list[str] = []
    if result.timed_out:
        failures.append("snapshot_cli_timeout")
    elif result.returncode != 0:
        failures.append(f"snapshot_cli_exit:{result.returncode}")
    if payload is None:
        failures.append("snapshot_json_invalid")
        return (
            {
                "status": "timeout" if result.timed_out else "failed",
                "saved": False,
                "duplicate": False,
                "stderr": result.stderr,
                "timeout_seconds": result.timeout_seconds,
            },
            failures,
        )

    saved = payload.get("saved") is True
    duplicate = payload.get("skipped_duplicate") is True
    if payload.get("dry_run") is not False:
        failures.append("snapshot_confirm_not_effective")
    if not saved and not duplicate:
        failures.append("snapshot_not_saved_or_duplicate")
    raw_sections_seen = payload.get("sections_seen")
    raw_sections_missing = payload.get("sections_missing")
    if not isinstance(raw_sections_seen, list) or not all(
        isinstance(section, str) for section in raw_sections_seen
    ):
        failures.append("snapshot_sections_seen_invalid")
        sections_seen: list[str] = []
    else:
        sections_seen = list(raw_sections_seen)
    if not isinstance(raw_sections_missing, list) or not all(
        isinstance(section, str) for section in raw_sections_missing
    ):
        failures.append("snapshot_sections_missing_invalid")
        sections_missing: list[str] = []
    else:
        sections_missing = list(raw_sections_missing)
    missing_required = sorted(REQUIRED_SNAPSHOT_SECTIONS - set(sections_seen))
    if missing_required:
        failures.append(
            "snapshot_required_sections_missing:" + ",".join(missing_required)
        )
    if sections_missing:
        failures.append(
            "snapshot_sections_reported_missing:" + ",".join(
                sorted(set(sections_missing))
            )
        )
    step = {
        "status": "passed" if not failures else "failed",
        "saved": saved,
        "duplicate": duplicate,
        "snapshot_id": payload.get("snapshot_id"),
        "snapshot_hash": payload.get("snapshot_hash"),
        "quality": payload.get("quality"),
        "sections_seen": sections_seen,
        "sections_missing": sections_missing,
        "required_sections": sorted(REQUIRED_SNAPSHOT_SECTIONS),
        "warnings_count": payload.get("warnings_count"),
    }
    if result.stderr and failures:
        step["stderr"] = result.stderr
    return step, failures


def _evidence_step(result: CliRunResult) -> tuple[dict[str, Any], list[str]]:
    payload = result.payload
    failures: list[str] = []
    if result.timed_out:
        failures.append("evidence_cli_timeout")
    elif result.returncode != 0:
        failures.append(f"evidence_cli_exit:{result.returncode}")
    if payload is None:
        failures.append("evidence_json_invalid")
        return (
            {
                "status": "timeout" if result.timed_out else "failed",
                "events_seen": 0,
                "events_inserted": 0,
                "duplicates": 0,
                "failures": 1,
                "stderr": result.stderr,
                "timeout_seconds": result.timeout_seconds,
            },
            failures,
        )

    try:
        seen = _non_negative_int(
            payload.get("events_seen"),
            label="events_seen",
        )
        inserted = _non_negative_int(
            payload.get("events_inserted"),
            label="events_inserted",
        )
        duplicates = _non_negative_int(
            payload.get("events_skipped_duplicate"),
            label="events_skipped_duplicate",
        )
        event_failures = _non_negative_int(
            payload.get("events_failed"),
            label="events_failed",
        )
    except TypeError as exc:
        failures.append(f"evidence_counts_invalid:{exc}")
        seen = 0
        inserted = 0
        duplicates = 0
        event_failures = 1

    if payload.get("dry_run") is not False:
        failures.append("evidence_confirm_not_effective")
    if seen == 0:
        failures.append("evidence_events_empty")
    if inserted == 0 and duplicates == 0:
        failures.append("evidence_no_insert_or_duplicate")
    if event_failures:
        failures.append(f"evidence_events_failed:{event_failures}")
    diagnostics = payload.get("diagnostics")
    error_diagnostics = []
    if isinstance(diagnostics, list):
        error_diagnostics = [
            item
            for item in diagnostics
            if isinstance(item, dict) and item.get("severity") == "error"
        ]
    if error_diagnostics:
        failures.append(f"evidence_error_diagnostics:{len(error_diagnostics)}")

    step = {
        "status": "passed" if not failures else "failed",
        "events_seen": seen,
        "events_inserted": inserted,
        "duplicates": duplicates,
        "failures": event_failures + len(error_diagnostics),
        "warnings_count": payload.get("warnings_count"),
        "diagnostics_by_code": dict(payload.get("diagnostics_by_code") or {}),
        "event_type_counts": dict(payload.get("event_type_counts") or {}),
        "quality_counts": dict(payload.get("quality_counts") or {}),
    }
    if result.stderr and failures:
        step["stderr"] = result.stderr
    return step, failures


def _base_payload(
    *,
    decision_at: datetime,
    checked_at: datetime,
    status_path: Path,
    db_path: Path | None,
    decision_date_basis: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "task": TASK_NAME,
        "status": "running",
        "checked_at": checked_at.isoformat(timespec="seconds"),
        "decision_at": decision_at.isoformat(timespec="seconds"),
        "decision_date": decision_at.date().isoformat(),
        "decision_timezone": "Asia/Taipei",
        "decision_time": "08:30:00",
        "decision_date_basis": decision_date_basis,
        "trading_calendar_validated": False,
        "trading_calendar_is_open": None,
        "trading_calendar_reason": None,
        "maturity_date_inferred": False,
        "status_path": str(status_path.resolve()),
        "db_path": str(db_path.resolve()) if db_path is not None else None,
        "confirm_capture": True,
        "safety_boundary": {
            "writes_decision_desk_snapshot": True,
            "writes_evidence_events": True,
            "changes_rule_state": False,
            "changes_advice_state": False,
            "changes_portfolio_state": False,
            "broker_execution": False,
        },
    }


def run(
    *,
    data_root: Path,
    output_root: Path,
    db_path: Path | None = None,
    now: datetime | None = None,
    decision_at: datetime | None = None,
    python_executable: str | None = None,
    subprocess_timeout_seconds: int = DEFAULT_SUBPROCESS_TIMEOUT_SECONDS,
    calendar: OfficialTradingCalendar | None = None,
) -> dict[str, Any]:
    checked_raw = now or datetime.now(TAIPEI)
    if checked_raw.tzinfo is None or checked_raw.utcoffset() is None:
        raise ValueError("now 必須包含時區")
    checked_at = checked_raw.astimezone(TAIPEI)
    if decision_at is None:
        resolved_decision_at = latest_reached_taipei_decision_at(checked_at)
        decision_date_basis = "latest_reached_calendar_decision_at"
    else:
        if decision_at.tzinfo is None or decision_at.utcoffset() is None:
            raise ValueError("decision_at 必須包含時區")
        resolved_decision_at = decision_at.astimezone(TAIPEI)
        if resolved_decision_at.timetz().replace(tzinfo=None) != DECISION_TIME:
            raise ValueError("decision_at 必須對應 Asia/Taipei 08:30")
        decision_date_basis = "explicit_decision_at"
    status_path = (
        output_root
        / "scheduled"
        / "decision_evidence_capture"
        / "latest_status.json"
    )
    payload = _base_payload(
        decision_at=resolved_decision_at,
        checked_at=checked_at,
        status_path=status_path,
        db_path=db_path,
        decision_date_basis=decision_date_basis,
    )
    _atomic_write_json(status_path, payload)

    calendar_service = calendar or OfficialTradingCalendar(db_path=db_path)
    try:
        is_trading_day, calendar_reason = (
            calendar_service.is_official_trading_day(
                resolved_decision_at.date()
            )
        )
    except Exception as exc:  # noqa: BLE001 - 必須持久化 fail-closed 狀態
        is_trading_day = None
        calendar_reason = f"calendar_exception:{type(exc).__name__}"
    payload["trading_calendar_validated"] = is_trading_day is not None
    payload["trading_calendar_is_open"] = is_trading_day
    payload["trading_calendar_reason"] = calendar_reason
    if is_trading_day is not True:
        safety_boundary = dict(payload["safety_boundary"])
        safety_boundary["writes_decision_desk_snapshot"] = False
        safety_boundary["writes_evidence_events"] = False
        payload.update(
            {
                "status": (
                    "skipped_non_trading_day"
                    if is_trading_day is False
                    else "degraded_calendar_unknown"
                ),
                "failure_reasons": [
                    (
                        f"non_trading_day:{calendar_reason}"
                        if is_trading_day is False
                        else f"trading_calendar_unknown:{calendar_reason}"
                    )
                ],
                "snapshot": {
                    "status": "not_run",
                    "saved": False,
                    "duplicate": False,
                    "reason": "official_market_not_open",
                },
                "evidence": {
                    "status": "not_run",
                    "events_seen": 0,
                    "events_inserted": 0,
                    "duplicates": 0,
                    "failures": 0,
                    "reason": "official_market_not_open",
                },
                "snapshot_saved": False,
                "snapshot_duplicate": False,
                "events_inserted": 0,
                "events_duplicates": 0,
                "events_failures": 0,
                "safety_boundary": safety_boundary,
            }
        )
        _atomic_write_json(status_path, payload)
        return payload

    interpreter = python_executable or sys.executable
    common_args = [
        "--decision-date",
        resolved_decision_at.date().isoformat(),
        "--data-root",
        str(data_root),
        "--output-root",
        str(output_root),
        "--json-output",
    ]
    if db_path is not None:
        common_args.extend(("--db-path", str(db_path)))

    failures: list[str] = []
    try:
        snapshot_result = _run_json_cli(
            [
                interpreter,
                str(
                    REPO_ROOT
                    / "scripts"
                    / "capture_decision_desk_snapshot.py"
                ),
                *common_args,
                "--confirm",
            ],
            timeout_seconds=subprocess_timeout_seconds,
        )
        snapshot, snapshot_failures = _snapshot_step(snapshot_result)
    except Exception as exc:  # noqa: BLE001
        snapshot = {
            "status": "failed",
            "saved": False,
            "duplicate": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        snapshot_failures = [
            f"snapshot_step_exception:{type(exc).__name__}"
        ]
    failures.extend(snapshot_failures)
    payload["snapshot"] = snapshot

    if failures:
        payload["evidence"] = {
            "status": "not_run",
            "events_inserted": 0,
            "duplicates": 0,
            "failures": 0,
            "reason": "snapshot_step_failed",
        }
    else:
        try:
            evidence_result = _run_json_cli(
                [
                    interpreter,
                    str(
                        REPO_ROOT
                        / "scripts"
                        / "capture_evidence_events.py"
                    ),
                    "--source",
                    "all",
                    *common_args,
                    "--confirm",
                ],
                timeout_seconds=subprocess_timeout_seconds,
            )
            evidence, evidence_failures = _evidence_step(evidence_result)
        except Exception as exc:  # noqa: BLE001
            evidence = {
                "status": "failed",
                "events_inserted": 0,
                "duplicates": 0,
                "failures": 1,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            evidence_failures = [
                f"evidence_step_exception:{type(exc).__name__}"
            ]
        payload["evidence"] = evidence
        failures.extend(evidence_failures)

    evidence_payload = payload["evidence"]
    payload.update(
        {
            "status": (
                "degraded"
                if any("timeout" in reason for reason in failures)
                else ("failed" if failures else "passed")
            ),
            "failure_reasons": failures,
            "snapshot_saved": snapshot["saved"],
            "snapshot_duplicate": snapshot["duplicate"],
            "events_inserted": evidence_payload["events_inserted"],
            "events_duplicates": evidence_payload["duplicates"],
            "events_failures": evidence_payload["failures"],
            "subprocess_timeout_seconds": subprocess_timeout_seconds,
        }
    )
    _atomic_write_json(status_path, payload)
    return payload


def _parse_now(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--now 必須是含時區 ISO timestamp")
    return parsed


def _parse_decision_at(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--decision-at 必須是含時區 ISO timestamp")
    local = parsed.astimezone(TAIPEI)
    if local.timetz().replace(tzinfo=None) != DECISION_TIME:
        raise ValueError("--decision-at 必須對應 Asia/Taipei 08:30")
    return local


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "保存下一個尚未到達之台北 08:30 Decision Desk 快照與 Evidence Event。"
        )
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(
            os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data")
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(
            os.environ.get(
                "OUTPUT_ROOT",
                "D:/Min/Python/Project/FA_Data/output",
            )
        ),
    )
    parser.add_argument("--db-path", type=Path)
    parser.add_argument(
        "--now",
        help="測試／重播用的含時區 ISO timestamp；省略時讀取台北現在時間。",
    )
    parser.add_argument(
        "--decision-at",
        help="明確指定含時區的決策時間；必須對應台北 08:30 並通過官方交易日驗證。",
    )
    parser.add_argument(
        "--subprocess-timeout-seconds",
        type=int,
        default=DEFAULT_SUBPROCESS_TIMEOUT_SECONDS,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = run(
            data_root=args.data_root,
            output_root=args.output_root,
            db_path=args.db_path,
            now=_parse_now(args.now),
            decision_at=_parse_decision_at(args.decision_at),
            subprocess_timeout_seconds=args.subprocess_timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps(
                {
                    "task": TASK_NAME,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                # Windows Task Scheduler/redirected cmd may expose cp1252.
                # Console JSON must remain ASCII-safe so a successful capture
                # is not turned into a process failure while printing Chinese.
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            payload,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if payload["status"] in {"passed", "skipped_non_trading_day"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
