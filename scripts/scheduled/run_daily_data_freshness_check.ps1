param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$DataRoot = $env:DATA_ROOT,
    [string]$OutputRoot = $env:OUTPUT_ROOT,
    [string]$DbPath = "",
    [int]$StaleDays = 7
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($DataRoot)) {
    $DataRoot = "D:\Min\Python\Project\FA_Data"
}
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $DataRoot "output"
}
if ([string]::IsNullOrWhiteSpace($DbPath)) {
    $DbPath = Join-Path $DataRoot "sqlite\twstock.db"
}

$RunRoot = Join-Path $OutputRoot "scheduled\data_freshness"
$LogRoot = Join-Path $RunRoot "logs"
New-Item -ItemType Directory -Force -Path $RunRoot, $LogRoot | Out-Null

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$StatusPath = Join-Path $RunRoot "latest_status.json"
$LogPath = Join-Path $LogRoot "data_freshness_$Timestamp.log"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

$env:BALDR_DATA_ROOT = $DataRoot
$env:BALDR_DB_PATH = $DbPath
$env:BALDR_STATUS_PATH = $StatusPath
$env:BALDR_LOG_PATH = $LogPath
$env:BALDR_STALE_DAYS = [string]$StaleDays

$FreshnessProbe = @'
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path


def _parse_date(value: object) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def _latest_date(conn: sqlite3.Connection, table: str) -> str | None:
    if not _table_exists(conn, table):
        return None
    row = conn.execute(f'SELECT MAX("日期") FROM "{table}"').fetchone()
    return str(row[0]) if row and row[0] is not None else None


data_root = Path(os.environ["BALDR_DATA_ROOT"])
db_path = Path(os.environ["BALDR_DB_PATH"])
status_path = Path(os.environ["BALDR_STATUS_PATH"])
log_path = Path(os.environ["BALDR_LOG_PATH"])
stale_days = int(os.environ.get("BALDR_STALE_DAYS", "7"))
now = datetime.now().isoformat(timespec="seconds")
checks: dict[str, object] = {
    "data_root_exists": data_root.exists(),
    "db_path": str(db_path),
    "db_exists": db_path.exists(),
}
warnings: list[str] = []
errors: list[str] = []

if not data_root.exists():
    errors.append("data_root_missing")
if not db_path.exists():
    errors.append("sqlite_db_missing")

if db_path.exists():
    try:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            for table in ("daily_prices", "technical_indicators"):
                latest = _latest_date(conn, table)
                checks[f"{table}_latest_date"] = latest
                parsed = _parse_date(latest)
                if parsed is None:
                    warnings.append(f"{table}_latest_date_missing")
                    continue
                age_days = (date.today() - parsed).days
                checks[f"{table}_age_days"] = age_days
                if age_days > stale_days:
                    warnings.append(f"{table}_stale")
    except Exception as exc:  # noqa: BLE001
        errors.append("sqlite_read_failed")
        checks["sqlite_error"] = str(exc)

status = "failed" if errors else "degraded" if warnings else "passed"
payload = {
    "task": "baldr-data-freshness-check-daily",
    "status": status,
    "read_only": True,
    "checked_at": now,
    "data_root": str(data_root),
    "output_root": str(status_path.parents[2]),
    "checks": checks,
    "warnings": warnings,
    "errors": errors,
    "stale_days": stale_days,
}
status_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
log_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
raise SystemExit(1 if errors else 0)
'@

$FreshnessProbe | & $Python -

exit $LASTEXITCODE
