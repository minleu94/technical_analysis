"""唯讀檢查 baldr Windows Task Scheduler 註冊狀態。

此工具只呼叫 ``schtasks /Query``，不會建立、修改或刪除 task。輸出只保留
可供 readiness 判讀的摘要，不保存命令列原文或可能含有帳號資訊的完整 LIST。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "scheduled-task-registration.v1"
DEFAULT_EXECUTABLE = "schtasks.exe"
DEFAULT_TIMEOUT_SECONDS = 15

EXPECTED_TASKS: tuple[dict[str, str], ...] = (
    {"name": "baldr-data-update-quick-daily", "schedule": "DAILY 04:20", "required": "true"},
    {"name": "baldr-official-market-events-daily", "schedule": "DAILY 04:50", "required": "true"},
    {"name": "baldr-data-freshness-check-daily", "schedule": "DAILY 05:00", "required": "true"},
    {"name": "baldr-ml-raw-pit-refresh-daily", "schedule": "DAILY 05:05", "required": "true"},
    {"name": "baldr-recommendation-snapshot-daily", "schedule": "DAILY 05:10", "required": "true"},
    {"name": "baldr-evidence-pipeline-dry-run-daily", "schedule": "DAILY 05:15", "required": "true"},
    {"name": "baldr-ml-promotion-evidence-daily", "schedule": "DAILY 05:17", "required": "true"},
    {"name": "baldr-ml-promotion-authority-daily", "schedule": "DAILY 05:18", "required": "true"},
    {"name": "baldr-ml-allocation-copilot-daily", "schedule": "DAILY 05:20", "required": "true"},
    {"name": "baldr-decision-evidence-capture-daily", "schedule": "DAILY 05:25", "required": "true"},
    {"name": "baldr-paper-portfolio-daily", "schedule": "DAILY 05:28", "required": "true"},
    {"name": "baldr-ml-direct-chain-maintainer", "schedule": "DAILY 05:30", "required": "true"},
    {"name": "baldr-v2-2-weekly-collection", "schedule": "WEEKLY SUN 18:00", "required": "true"},
)

_SAFE_SUMMARY_KEYS = (
    "status",
    "task_to_run",
    "next_run_time",
    "last_run_time",
    "last_result",
)


def inspect_scheduled_task_registration(
    *,
    executable: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    runner=None,
) -> dict[str, Any]:
    """Query every expected task and return a redacted, deterministic summary."""

    if timeout_seconds < 1 or timeout_seconds > 120:
        raise ValueError("timeout_seconds must be between 1 and 120")
    command = executable or os.environ.get("BALDR_SCHTASKS_EXE", DEFAULT_EXECUTABLE)
    run = runner or subprocess.run
    task_results: list[dict[str, Any]] = []
    for spec in EXPECTED_TASKS:
        name = spec["name"]
        query = [command, "/Query", "/TN", name, "/V", "/FO", "LIST"]
        try:
            completed = run(
                query,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
        except FileNotFoundError as error:
            task_results.append(
                _task_result(spec, status="unavailable", error=f"{type(error).__name__}:{error}")
            )
            continue
        except subprocess.TimeoutExpired as error:
            task_results.append(
                _task_result(spec, status="timeout", error=f"{type(error).__name__}:{error}")
            )
            continue
        except OSError as error:
            task_results.append(
                _task_result(spec, status="unavailable", error=f"{type(error).__name__}:{error}")
            )
            continue

        stdout = str(getattr(completed, "stdout", "") or "")
        stderr = str(getattr(completed, "stderr", "") or "")
        returncode = int(getattr(completed, "returncode", 1))
        summary = _parse_list_summary(stdout)
        status = "available" if returncode == 0 else "missing_or_unavailable"
        task_results.append(
            _task_result(
                spec,
                status=status,
                returncode=returncode,
                command_output_sha256=_sha256_text(stdout + "\n" + stderr),
                summary=summary,
                error=None if returncode == 0 else _compact_error(stderr or stdout),
            )
        )

    available_count = sum(item["status"] == "available" for item in task_results)
    missing_count = len(task_results) - available_count
    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "executable": command,
        "query_only": True,
        "side_effect_free": True,
        "task_count": len(task_results),
        "available_count": available_count,
        "missing_or_unavailable_count": missing_count,
        "all_available": missing_count == 0,
        "tasks": task_results,
    }


def _task_result(
    spec: Mapping[str, str],
    *,
    status: str,
    returncode: int | None = None,
    command_output_sha256: str | None = None,
    summary: Mapping[str, str] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": spec["name"],
        "schedule": spec["schedule"],
        "required": spec["required"] == "true",
        "status": status,
    }
    if returncode is not None:
        payload["returncode"] = returncode
    if command_output_sha256:
        payload["command_output_sha256"] = command_output_sha256
    if summary:
        payload["summary"] = dict(summary)
    if error:
        payload["error"] = error[:500]
    return payload


def _parse_list_summary(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in output.splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        normalized_key = key.strip().lower().replace(" ", "_")
        if normalized_key not in _SAFE_SUMMARY_KEYS:
            continue
        text = value.strip()
        if text:
            values[normalized_key] = text[:240]
    return values


def _compact_error(value: str) -> str | None:
    text = " ".join(value.split())
    return text[:500] if text else None


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", default=None, help="schtasks executable; defaults to BALDR_SCHTASKS_EXE")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--output", type=Path, help="optional JSON output path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    args = build_parser().parse_args(argv)
    report = inspect_scheduled_task_registration(
        executable=args.executable,
        timeout_seconds=args.timeout_seconds,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if report["all_available"] else 1


def _configure_utf8_stdio() -> None:
    """讓 Windows CP1252 主控台也能安全輸出繁中說明與診斷。"""

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
