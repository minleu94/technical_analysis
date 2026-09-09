"""Keep the official TWSE annual calendar cache valid for the next forward cutoff.

The registered ML forward task starts before the Asia/Taipei 08:30 decision
boundary.  The Paper EOD task refreshes the same cache when it is already
expired, but a seven-day cache can still be valid at Paper's 06:00 Pacific
start and expire before the later forward invocation.  This small scheduled
boundary checks the next real Taipei cutoff and invokes the existing bounded
capture CLI only when the currently verified cache would expire before it.

The command never accepts a caller-supplied date or timestamp.  All dates and
capture timestamps come from the machine clock or the official response.  A
new capture receives a unique immutable filename; existing cache files are
never replaced or removed.  A failed/expired refresh is observable and exits
non-zero so the forward wrapper can stop before its producer or child runs.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.official_trading_calendar_cache import (  # noqa: E402
    OfficialCalendarCacheError,
    load_verified_twse_calendar_cache,
)


TAIPEI = ZoneInfo("Asia/Taipei")
TAIPEI_DECISION_TIME = time(8, 30)
TASK_NAME = "baldr-ml-allocation-forward-daily"
SCHEMA_VERSION = "official-calendar-refresh-status.v1"
CAPTURE_SCRIPT = ROOT / "scripts" / "capture_official_trading_calendar_cache.py"
DEFAULT_CACHE_ROOT = ROOT / "output" / "paper_execution_eod_replay" / "calendar_cache"
DEFAULT_STATUS_ROOT = ROOT / "output" / "v4_ml_forward_scheduler" / "calendar_cache_refresh"
MAX_CACHE_CANDIDATES = 64
CAPTURE_TIMEOUT_SECONDS = 30
SHA256_RE = "sha256:"


class CalendarRefreshError(ValueError):
    """The pre-forward calendar refresh contract cannot be satisfied."""


def _path(value: Path | str) -> Path:
    return Path(value).expanduser().resolve()


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    if not isinstance(value, str) or not value.strip():
        return None
    return _path(value.strip())


def default_cache_root() -> Path:
    return _env_path("ML_FORWARD_CALENDAR_CACHE_ROOT") or DEFAULT_CACHE_ROOT


def default_status_root() -> Path:
    return _env_path("ML_FORWARD_CALENDAR_REFRESH_STATUS_ROOT") or DEFAULT_STATUS_ROOT


def _require_aware(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CalendarRefreshError(f"{field_name} must contain a timezone")
    return value


def _parse_aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise CalendarRefreshError(f"{field_name} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise CalendarRefreshError(f"{field_name} must be an ISO timestamp") from error
    return _require_aware(parsed, field_name=field_name)


def next_forward_cutoff(observed: datetime) -> datetime:
    """Return the next real Taipei 08:30 boundary after ``observed``.

    The forward task is normally launched at Taipei 07:15/08:15.  Keeping the
    calculation based on the actual local clock also handles manual recovery,
    DST changes on the Pacific host, and year boundaries without a fixed date.
    """

    local = _require_aware(observed, field_name="observed").astimezone(TAIPEI)
    target_date = local.date()
    if local.timetz().replace(tzinfo=None) >= TAIPEI_DECISION_TIME:
        target_date += timedelta(days=1)
    return datetime.combine(target_date, TAIPEI_DECISION_TIME, tzinfo=TAIPEI)


def calendar_years_needed(horizon: datetime) -> tuple[int, ...]:
    """Return annual cache years needed by the producer's 31-day lookback.

    The producer may resolve the previous official session across New Year's
    Day.  Keeping the horizon year and its predecessor prevents a January
    cutoff from depending on a cache that was never refreshed for the prior
    calendar year.
    """

    local_date = _require_aware(horizon, field_name="horizon").astimezone(TAIPEI).date()
    years = {local_date.year}
    # The producer searches back at most 31 calendar days for the previous
    # official session.  Only the first 31 days of a year can therefore cross
    # into the predecessor year.
    if local_date <= date(local_date.year, 1, 31):
        years.add(local_date.year - 1)
    return tuple(sorted(years))


def _ensure_under(path: Path, allowed_root: Path, *, label: str) -> Path:
    resolved = _path(path)
    root = _path(allowed_root)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise CalendarRefreshError(f"{label} must be under repository output") from error
    if resolved == root:
        raise CalendarRefreshError(f"{label} must be a child of repository output")
    return resolved


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return SHA256_RE + digest.hexdigest()


def _cache_candidates(cache_root: Path, calendar_year: int) -> list[Path]:
    """Return a bounded set of annual cache candidates, newest first."""

    pattern = f"twse_holiday_schedule_{calendar_year}_*.json"
    candidates: list[tuple[int, str, Path]] = []
    for candidate in cache_root.glob(pattern):
        try:
            resolved = candidate.resolve()
            resolved.relative_to(cache_root)
            if not resolved.is_file():
                continue
            stat = resolved.stat()
        except OSError:
            continue
        candidates.append((int(stat.st_mtime_ns), str(resolved), resolved))
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in candidates[:MAX_CACHE_CANDIDATES]]


def inspect_cache(
    *,
    cache_root: Path,
    calendar_year: int,
    observed: datetime,
    horizon: datetime,
) -> dict[str, object]:
    """Verify annual cache files and decide whether the horizon needs refresh."""

    resolved_root = _path(cache_root)
    candidates = _cache_candidates(resolved_root, calendar_year)
    invalid: list[dict[str, str]] = []
    valid: list[dict[str, object]] = []
    for candidate in candidates:
        try:
            verified = load_verified_twse_calendar_cache(
                candidate,
                calendar_year=calendar_year,
                observed_at=observed,
            )
        except (OSError, ValueError, OfficialCalendarCacheError) as error:
            invalid.append(
                {
                    "path": str(candidate),
                    "reason": f"{type(error).__name__}:{str(error)[:240]}",
                }
            )
            continue
        evidence = dict(verified.evidence)
        captured_value = evidence.get("captured_at")
        expires_value = evidence.get("expires_at")
        try:
            captured = _parse_aware(captured_value, field_name="cache.captured_at")
            expires = _parse_aware(expires_value, field_name="cache.expires_at")
        except CalendarRefreshError:
            invalid.append(
                {
                    "path": str(candidate),
                    "reason": "verified cache evidence has invalid timestamps",
                }
            )
            continue
        valid.append(
            {
                "path": str(candidate),
                "file_sha256": _file_hash(candidate),
                "content_sha256": evidence.get("cache_content_sha256"),
                "source_hash": evidence.get("source_hash"),
                "captured_at": captured.astimezone(timezone.utc).isoformat(),
                "expires_at": expires.astimezone(timezone.utc).isoformat(),
                "expires_before_horizon": expires.astimezone(timezone.utc)
                <= horizon.astimezone(timezone.utc),
            }
        )
    valid.sort(key=lambda item: str(item.get("captured_at", "")), reverse=True)
    selected = valid[0] if valid else None
    return {
        "candidate_count": len(candidates),
        "valid_count": len(valid),
        "invalid_count": len(invalid),
        "invalid_candidates": invalid[:12],
        "selected": selected,
        "horizon": horizon.astimezone(timezone.utc).isoformat(),
        "horizon_timezone": "Asia/Taipei",
        "refresh_required": selected is None
        or bool(selected.get("expires_before_horizon")),
    }


def _new_capture_path(cache_root: Path, calendar_year: int, observed: datetime) -> Path:
    stamp = observed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return cache_root / (
        f"twse_holiday_schedule_{calendar_year}_{stamp}_{uuid.uuid4().hex[:12]}.json"
    )


def _last_json_line(value: str) -> Mapping[str, object] | None:
    for line in reversed(value.splitlines()):
        text = line.strip()
        if not text:
            continue
        try:
            parsed: object = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, Mapping):
            return parsed
    return None


def _run_capture(
    *,
    cache_root: Path,
    calendar_year: int,
    observed: datetime,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    cache_root.mkdir(parents=True, exist_ok=True)
    output = _new_capture_path(cache_root, calendar_year, observed)
    command = [
        sys.executable,
        str(CAPTURE_SCRIPT),
        "--year",
        str(calendar_year),
        "--output",
        str(output),
        "--confirm-network",
    ]
    try:
        completed = runner(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CAPTURE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        return {
            "status": "refresh_blocked",
            "refresh_attempted": True,
            "network_attempts": 1,
            "reason": "official_calendar_capture_timeout",
            "capture_path": str(output),
            "capture_stdout_tail": str(error.stdout or "")[-1_000:],
            "capture_stderr_tail": str(error.stderr or "")[-1_000:],
        }
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    child_payload = _last_json_line(stdout)
    result: dict[str, object] = {
        "refresh_attempted": True,
        "network_attempts": 1,
        "capture_path": str(output),
        "capture_returncode": int(completed.returncode),
        "capture_stdout_sha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
        "capture_stderr_tail": stderr[-1_000:],
    }
    if completed.returncode != 0:
        result.update(
            {
                "status": "refresh_blocked",
                "reason": "official_calendar_capture_nonzero",
                "capture_payload": child_payload,
            }
        )
        return result
    if not isinstance(child_payload, Mapping) or child_payload.get(
        "status"
    ) != "official_calendar_cache_captured":
        result.update(
            {
                "status": "refresh_blocked",
                "reason": "official_calendar_capture_contract_invalid",
                "capture_payload": child_payload,
            }
        )
        return result
    declared_path = child_payload.get("path")
    if not isinstance(declared_path, str) or _path(declared_path) != output:
        result.update(
            {
                "status": "refresh_blocked",
                "reason": "official_calendar_capture_path_mismatch",
                "capture_payload": child_payload,
            }
        )
        return result
    try:
        result.update(
            {
                "status": "refreshed",
                "cache_file_sha256": _file_hash(output),
                "cache_content_sha256": child_payload.get("content_sha256"),
                "captured_at": child_payload.get("captured_at_utc"),
                "expires_at": child_payload.get("expires_at_utc"),
                "source_hash": child_payload.get("source_sha256"),
            }
        )
    except OSError as error:
        result.update(
            {
                "status": "refresh_blocked",
                "reason": f"official_calendar_capture_output_missing:{type(error).__name__}",
            }
        )
    return result


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    fd, temporary_name = tempfile.mkstemp(
        prefix=".calendar-refresh-",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_receipt(status_root: Path, payload: Mapping[str, object]) -> dict[str, str]:
    resolved = _path(status_root)
    receipt_root = resolved / "receipts"
    receipt_root.mkdir(parents=True, exist_ok=True)
    observed = str(payload.get("observed_at", ""))
    stamp = observed.replace(":", "").replace("+", "p").replace("-", "")
    receipt = receipt_root / f"{stamp}_{uuid.uuid4().hex[:12]}.json"
    _atomic_write_json(receipt, payload)
    latest = resolved / "latest_status.json"
    _atomic_write_json(latest, payload)
    return {"receipt_path": str(receipt), "latest_status_path": str(latest)}


def _base_payload(
    *,
    observed: datetime,
    horizon: datetime,
    calendar_years: Sequence[int],
    cache_root: Path,
    status: str,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "task": TASK_NAME,
        "producer": "scripts.scheduled.run_official_calendar_cache_refresh_daily",
        "observed_at": observed.astimezone(timezone.utc).isoformat(),
        "calendar_year": int(calendar_years[-1]),
        "calendar_years": [int(year) for year in calendar_years],
        "next_forward_cutoff": horizon.astimezone(timezone.utc).isoformat(),
        "next_forward_cutoff_timezone": "Asia/Taipei",
        "cache_root": str(cache_root),
        "status": status,
        "candidate_only": True,
        "read_only": True,
        "writes_market_database": False,
        "writes_source_database": False,
        "paper_ledger_written": False,
        "formal_clock_created": False,
        "forward_child_started": False,
        "forward_credit_granted": False,
        "production_action_allowed": False,
        "broker_order_allowed": False,
    }


def run_once(
    *,
    observed: datetime | None = None,
    cache_root: Path | None = None,
    status_root: Path | None = None,
    now_provider: Callable[[], datetime] | None = None,
    capture_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    allowed_root: Path | None = None,
) -> tuple[dict[str, object], int]:
    """Run one natural-clock refresh decision and persist its receipt."""

    clock = now_provider or (lambda: datetime.now(timezone.utc))
    current = _require_aware(observed or clock(), field_name="observed")
    current = current.astimezone(timezone.utc)
    allowed = _path(allowed_root or ROOT / "output")
    resolved_cache_root = _ensure_under(
        cache_root or default_cache_root(), allowed, label="cache_root"
    )
    resolved_status_root = _ensure_under(
        status_root or default_status_root(), allowed, label="status_root"
    )
    horizon = next_forward_cutoff(current)
    calendar_years = calendar_years_needed(horizon)
    payload = _base_payload(
        observed=current,
        horizon=horizon,
        calendar_years=calendar_years,
        cache_root=resolved_cache_root,
        status="inspecting",
    )
    try:
        inspections: dict[str, object] = {}
        refresh_years: list[int] = []
        for calendar_year in calendar_years:
            inspection = inspect_cache(
                cache_root=resolved_cache_root,
                calendar_year=calendar_year,
                observed=current,
                horizon=horizon,
            )
            inspections[str(calendar_year)] = inspection
            if inspection.get("refresh_required") is True:
                refresh_years.append(calendar_year)
        payload["inspections"] = inspections
        if len(calendar_years) == 1:
            payload["inspection"] = inspections[str(calendar_years[0])]
        if not refresh_years:
            payload["status"] = "cache_valid_for_forward_horizon"
            paths = _write_receipt(resolved_status_root, payload)
            payload.update(paths)
            return payload, 0
        refreshes: dict[str, object] = {}
        for calendar_year in refresh_years:
            refresh = _run_capture(
                cache_root=resolved_cache_root,
                calendar_year=calendar_year,
                observed=current,
                runner=capture_runner,
            )
            refreshes[str(calendar_year)] = refresh
            if refresh.get("status") != "refreshed":
                payload["refreshes"] = refreshes
                payload["status"] = "blocked_refresh"
                payload["blockers"] = [
                    f"calendar_year_{calendar_year}:"
                    f"{refresh.get('reason') or 'official_calendar_refresh_failed'}"
                ]
                paths = _write_receipt(resolved_status_root, payload)
                payload.update(paths)
                return payload, 2
            # Verify exact newly written bytes and require its response-derived
            # expiry to cover the same forward horizon that triggered capture.
            verification_time = _require_aware(
                clock(), field_name="verification_time"
            )
            verified = load_verified_twse_calendar_cache(
                _path(str(refresh["capture_path"])),
                calendar_year=calendar_year,
                observed_at=verification_time,
            )
            expires = _parse_aware(
                verified.evidence.get("expires_at"),
                field_name=f"cache.{calendar_year}.expires_at",
            )
            if expires.astimezone(timezone.utc) <= horizon.astimezone(timezone.utc):
                raise CalendarRefreshError(
                    f"captured cache {calendar_year} expires before forward horizon"
                )
            refresh["verified"] = dict(verified.evidence)
        payload["refreshes"] = refreshes
        if len(refresh_years) == 1:
            single_refresh = refreshes[str(refresh_years[0])]
            payload["refresh"] = single_refresh
            if isinstance(single_refresh, Mapping):
                payload["refresh_verification"] = single_refresh.get("verified")
        payload["status"] = "refreshed"
        payload["blockers"] = []
        paths = _write_receipt(resolved_status_root, payload)
        payload.update(paths)
        return payload, 0
    except (OSError, ValueError, OfficialCalendarCacheError) as error:
        payload["status"] = "blocked_refresh"
        payload["blockers"] = [f"calendar_refresh:{type(error).__name__}:{error}"]
        paths = _write_receipt(resolved_status_root, payload)
        payload.update(paths)
        return payload, 2


def preflight(
    *,
    cache_root: Path | None = None,
    status_root: Path | None = None,
    allowed_root: Path | None = None,
) -> tuple[dict[str, object], int]:
    """Check paths only; this mode performs no network request or write."""

    allowed = _path(allowed_root or ROOT / "output")
    checks: list[dict[str, object]] = []
    blockers: list[str] = []
    # The capture script is code under ``ROOT/scripts``; only writable output
    # paths are constrained to ``ROOT/output``.
    capture_exists = CAPTURE_SCRIPT.is_file()
    checks.append(
        {
            "name": "capture_script",
            "path": str(CAPTURE_SCRIPT.resolve()),
            "kind": "file",
            "exists": capture_exists,
        }
    )
    if not capture_exists:
        blockers.append("missing:capture_script")
    for name, candidate, kind in (
        ("cache_root", cache_root or default_cache_root(), "directory"),
        ("status_root", status_root or default_status_root(), "directory"),
    ):
        try:
            resolved = _ensure_under(candidate, allowed, label=name)
            exists = resolved.is_file() if kind == "file" else resolved.is_dir()
            checks.append(
                {"name": name, "path": str(resolved), "kind": kind, "exists": exists}
            )
            if kind == "file" and not exists:
                blockers.append(f"missing:{name}")
        except CalendarRefreshError as error:
            checks.append({"name": name, "path": str(candidate), "kind": kind, "exists": False})
            blockers.append(f"invalid:{name}:{error}")
    payload: dict[str, object] = {
        "schema_version": "official-calendar-refresh-preflight.v1",
        "task": TASK_NAME,
        "status": "ready" if not blockers else "blocked",
        "checks": checks,
        "blockers": blockers,
        "network_attempts": 0,
        "writes": False,
        "forward_child_started": False,
        "broker_order_allowed": False,
    }
    return payload, 0 if not blockers else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="只檢查路徑，不發網路、不建立 receipt、不執行 capture。",
    )
    parser.add_argument("--cache-root", type=Path, default=None)
    parser.add_argument("--status-root", type=Path, default=None)
    return parser


def _configure_stdio() -> None:
    """Keep Traditional Chinese help/receipts readable on Windows consoles."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: Sequence[str] | None = None) -> int:
    _configure_stdio()
    args = build_parser().parse_args(argv)
    if args.preflight:
        payload, code = preflight(
            cache_root=args.cache_root,
            status_root=args.status_root,
        )
    else:
        payload, code = run_once(
            cache_root=args.cache_root,
            status_root=args.status_root,
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
