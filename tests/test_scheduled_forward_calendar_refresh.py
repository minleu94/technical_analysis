from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from data_module.official_trading_calendar_cache import (
    build_twse_calendar_cache,
    write_twse_calendar_cache,
)
from scripts.scheduled import run_official_calendar_cache_refresh_daily as refresh


TAIPEI = refresh.TAIPEI


def _official_payload(year: int = 2026) -> list[dict[str, str]]:
    roc_year = year - 1911
    return [
        {
            "Name": "中華民國開國紀念日",
            "Date": f"{roc_year:03d}0101",
            "Weekday": "四",
            "Description": "依規定放假1日。",
        },
        {
            "Name": "國曆新年開始交易日",
            "Date": f"{roc_year:03d}0102",
            "Weekday": "五",
            "Description": "國曆新年開始交易。",
        },
    ]


def _write_cache(
    path: Path,
    captured_at: datetime,
    *,
    year: int = 2026,
    max_age: timedelta = timedelta(days=7),
) -> None:
    raw = json.dumps(
        _official_payload(year), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    cache = build_twse_calendar_cache(
        calendar_year=year,
        raw_response=raw,
        requested_at=captured_at - timedelta(seconds=1),
        captured_at=captured_at,
        response_status=200,
        response_headers={"Content-Type": "application/json"},
        max_age=max_age,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    write_twse_calendar_cache(path, cache, allowed_root=path.parents[2])


def test_valid_cache_is_kept_when_it_covers_next_taipei_cutoff(
    tmp_path: Path,
) -> None:
    observed = datetime(2026, 9, 14, 7, 15, tzinfo=TAIPEI)
    cache_path = tmp_path / "calendar" / "twse_holiday_schedule_2026_existing.json"
    _write_cache(cache_path, observed - timedelta(hours=1))
    status_root = tmp_path / "status"

    def fail_capture(*args: object, **kwargs: object) -> SimpleNamespace:
        raise AssertionError("a cache valid through the cutoff needs no capture")

    payload, code = refresh.run_once(
        observed=observed,
        cache_root=cache_path.parent,
        status_root=status_root,
        allowed_root=tmp_path,
        capture_runner=fail_capture,
        now_provider=lambda: observed,
    )

    assert code == 0
    assert payload["status"] == "cache_valid_for_forward_horizon"
    inspection = payload["inspection"]
    assert isinstance(inspection, dict)
    assert inspection["refresh_required"] is False
    assert payload["forward_child_started"] is False
    assert (status_root / "latest_status.json").is_file()


def test_expiring_cache_triggers_capture_and_verifies_new_immutable_file(
    tmp_path: Path,
) -> None:
    observed = datetime(2026, 9, 14, 7, 15, tzinfo=TAIPEI)
    cache_root = tmp_path / "calendar"
    old_path = cache_root / "twse_holiday_schedule_2026_old.json"
    # The cache is still valid at the launch time, but its seven-day expiry is
    # before the next 08:30 decision cutoff.  This is the preemptive case.
    _write_cache(old_path, observed - timedelta(days=6, hours=23))
    capture_time = observed + timedelta(seconds=2)
    clock_values = iter((capture_time,))
    calls: list[list[str]] = []

    def fake_capture(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(command)
        output = Path(command[command.index("--output") + 1])
        _write_cache(output, capture_time)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "official_calendar_cache_captured",
                    "path": str(output),
                    "captured_at_utc": capture_time.astimezone(timezone.utc).isoformat(),
                    "expires_at_utc": (capture_time + timedelta(days=7))
                    .astimezone(timezone.utc)
                    .isoformat(),
                    "content_sha256": "sha256:" + "1" * 64,
                }
            ),
            stderr="",
        )

    payload, code = refresh.run_once(
        observed=observed,
        cache_root=cache_root,
        status_root=tmp_path / "status",
        allowed_root=tmp_path,
        capture_runner=fake_capture,
        now_provider=lambda: next(clock_values),
    )

    assert code == 0
    assert payload["status"] == "refreshed"
    assert len(calls) == 1
    assert old_path.exists()
    new_files = list(cache_root.glob("twse_holiday_schedule_2026_*.json"))
    assert len(new_files) == 2
    verification = payload["refresh_verification"]
    assert isinstance(verification, dict)
    assert verification["source_hash"].startswith("sha256:")


def test_expired_cache_and_capture_failure_fail_closed_without_deleting_old_file(
    tmp_path: Path,
) -> None:
    observed = datetime(2026, 9, 14, 7, 15, tzinfo=TAIPEI)
    cache_root = tmp_path / "calendar"
    old_path = cache_root / "twse_holiday_schedule_2026_old.json"
    _write_cache(old_path, observed - timedelta(days=8))

    def failed_capture(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            returncode=2,
            stdout=json.dumps({"status": "blocked", "reason": "network"}),
            stderr="network unavailable",
        )

    payload, code = refresh.run_once(
        observed=observed,
        cache_root=cache_root,
        status_root=tmp_path / "status",
        allowed_root=tmp_path,
        capture_runner=failed_capture,
        now_provider=lambda: observed,
    )

    assert code == 2
    assert payload["status"] == "blocked_refresh"
    assert payload["forward_child_started"] is False
    assert old_path.exists()
    assert len(list(cache_root.glob("twse_holiday_schedule_2026_*.json"))) == 1


def test_capture_that_expires_before_forward_horizon_is_rejected(
    tmp_path: Path,
) -> None:
    observed = datetime(2026, 9, 14, 7, 15, tzinfo=TAIPEI)
    cache_root = tmp_path / "calendar"
    # Force a refresh by leaving no valid current cache.
    _write_cache(
        cache_root / "twse_holiday_schedule_2026_old.json",
        observed - timedelta(days=8),
    )
    capture_time = observed + timedelta(seconds=2)

    def short_lived_capture(command: list[str], **kwargs: object) -> SimpleNamespace:
        output = Path(command[command.index("--output") + 1])
        _write_cache(output, capture_time, max_age=timedelta(minutes=30))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "official_calendar_cache_captured",
                    "path": str(output),
                    "captured_at_utc": capture_time.astimezone(timezone.utc).isoformat(),
                    "expires_at_utc": (capture_time + timedelta(minutes=30))
                    .astimezone(timezone.utc)
                    .isoformat(),
                }
            ),
            stderr="",
        )

    payload, code = refresh.run_once(
        observed=observed,
        cache_root=cache_root,
        status_root=tmp_path / "status",
        allowed_root=tmp_path,
        capture_runner=short_lived_capture,
        now_provider=lambda: capture_time,
    )

    assert code == 2
    assert payload["status"] == "blocked_refresh"
    assert "expires before forward horizon" in str(payload["blockers"])


def test_preflight_is_read_only_and_rejects_output_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_root = tmp_path / "calendar"
    status_root = tmp_path / "status"
    capture_script = tmp_path / "capture.py"
    capture_script.write_text("# test capture\n", encoding="utf-8")
    monkeypatch.setattr(refresh, "CAPTURE_SCRIPT", capture_script)
    payload, code = refresh.preflight(
        cache_root=cache_root,
        status_root=status_root,
        allowed_root=tmp_path,
    )
    assert code == 0
    assert payload["status"] == "ready"
    assert payload["network_attempts"] == 0
    assert not (status_root / "latest_status.json").exists()

    escaped_payload, escaped_code = refresh.preflight(
        cache_root=tmp_path.parent / "outside",
        status_root=status_root,
        allowed_root=tmp_path,
    )
    assert escaped_code == 2
    assert escaped_payload["status"] == "blocked"


def test_next_cutoff_handles_both_pacific_dst_offsets_without_fixed_date() -> None:
    # These are the two Taiwan local launch times produced by a 16:15 Pacific
    # task.  Both must protect that same day's 08:30 boundary.
    pdt_launch = datetime(2026, 9, 8, 7, 15, tzinfo=TAIPEI)
    pst_launch = datetime(2026, 12, 8, 8, 15, tzinfo=TAIPEI)
    assert refresh.next_forward_cutoff(pdt_launch).date().isoformat() == "2026-09-08"
    assert refresh.next_forward_cutoff(pst_launch).date().isoformat() == "2026-12-08"


def test_new_year_horizon_requires_predecessor_calendar_cache(tmp_path: Path) -> None:
    observed = datetime(2027, 1, 1, 7, 15, tzinfo=TAIPEI)
    cache_root = tmp_path / "calendar"
    _write_cache(
        cache_root / "twse_holiday_schedule_2026_previous.json",
        observed - timedelta(hours=2),
        year=2026,
    )
    _write_cache(
        cache_root / "twse_holiday_schedule_2027_current.json",
        observed - timedelta(hours=1),
        year=2027,
    )

    def fail_capture(*args: object, **kwargs: object) -> SimpleNamespace:
        raise AssertionError("both annual caches cover the New Year cutoff")

    payload, code = refresh.run_once(
        observed=observed,
        cache_root=cache_root,
        status_root=tmp_path / "status",
        allowed_root=tmp_path,
        capture_runner=fail_capture,
        now_provider=lambda: observed,
    )

    assert code == 0
    assert payload["calendar_years"] == [2026, 2027]
    inspections = payload["inspections"]
    assert isinstance(inspections, dict)
    assert set(inspections) == {"2026", "2027"}
    assert payload["status"] == "cache_valid_for_forward_horizon"
