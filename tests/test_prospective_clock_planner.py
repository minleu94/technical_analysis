from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys

import pytest

from data_module.prospective_clock_planner import (
    OFFICIAL_CALENDAR_BUNDLE_SCHEMA_VERSION,
    ProspectiveClockPlanningError,
    plan_next_prospective_clock,
)


def _bundle() -> dict[str, object]:
    return {
        "schema_version": OFFICIAL_CALENDAR_BUNDLE_SCHEMA_VERSION,
        "days": [
            {
                "date": "2026-08-29",
                "twse": {
                    "is_trading_day": False,
                    "source": "TWSE holidaySchedule",
                    "source_hash": "sha256:" + "1" * 64,
                },
                "tpex": {
                    "is_trading_day": False,
                    "source": "TPEX mktCalendar",
                    "source_hash": "sha256:" + "2" * 64,
                },
            },
            {
                "date": "2026-08-31",
                "twse": {
                    "is_trading_day": True,
                    "source": "TWSE holidaySchedule",
                    "source_hash": "sha256:" + "3" * 64,
                },
                "tpex": {
                    "is_trading_day": False,
                    "source": "TPEX mktCalendar",
                    "source_hash": "sha256:" + "4" * 64,
                },
            },
            {
                "date": "2026-09-01",
                "twse": {
                    "is_trading_day": True,
                    "source": "TWSE holidaySchedule",
                    "source_hash": "sha256:" + "5" * 64,
                },
                "tpex": {
                    "is_trading_day": True,
                    "source": "TPEX mktCalendar",
                    "source_hash": "sha256:" + "6" * 64,
                },
            },
        ],
    }


def test_selects_first_unconsumed_common_future_day() -> None:
    report = plan_next_prospective_clock(
        now=datetime.fromisoformat("2026-08-28T15:00:00+08:00"),
        owner_decision_timestamp=datetime.fromisoformat(
            "2026-08-28T10:00:00+08:00"
        ),
        calendar_evidence=_bundle(),
    )

    assert report["status"] == "candidate_ready"
    assert report["activation_trading_day"] == "2026-09-01"
    assert report["clock_id"] == "clock:prospective:20260901:planned-v1"
    assert report["calendar_day_count"] == 3
    assert report["safety"] == {
        "read_only": True,
        "formal_clock_created": False,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "historical_backfill_claimed": False,
        "same_day_preopen_override_selected": False,
        "secret_values_emitted": False,
    }
    assert str(report["plan_hash"]).startswith("sha256:")


def test_existing_clock_date_is_not_reused() -> None:
    report = plan_next_prospective_clock(
        now=datetime.fromisoformat("2026-08-28T15:00:00+08:00"),
        owner_decision_timestamp=datetime.fromisoformat(
            "2026-08-28T10:00:00+08:00"
        ),
        calendar_evidence=_bundle(),
        existing_clock_ids=("clock:prospective:20260901:v1",),
    )

    assert report["status"] == "blocked"
    assert "no_unconsumed_common_trading_day" in str(report["blockers"])


def test_missing_common_day_is_blocked_without_guessing() -> None:
    bundle = _bundle()
    days = bundle["days"]
    assert isinstance(days, list)
    days[-1]["tpex"]["is_trading_day"] = False  # type: ignore[index]
    report = plan_next_prospective_clock(
        now=datetime.fromisoformat("2026-08-28T15:00:00+08:00"),
        owner_decision_timestamp=datetime.fromisoformat(
            "2026-08-28T10:00:00+08:00"
        ),
        calendar_evidence=bundle,
    )

    assert report["status"] == "blocked"
    assert report["safety"]["formal_clock_created"] is False  # type: ignore[index]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("now", datetime(2026, 8, 28, 15, 0), "now must include timezone"),
        (
            "owner_decision_timestamp",
            datetime.fromisoformat("2026-08-29T10:00:00+08:00"),
            "cannot be in the future",
        ),
        ("minimum_preparation_days", 0, "positive integer"),
    ],
)
def test_rejects_unsafe_planning_inputs(
    field: str,
    value: object,
    message: str,
) -> None:
    kwargs: dict[str, object] = {
        "now": datetime.fromisoformat("2026-08-28T15:00:00+08:00"),
        "owner_decision_timestamp": datetime.fromisoformat(
            "2026-08-28T10:00:00+08:00"
        ),
        "calendar_evidence": _bundle(),
    }
    kwargs[field] = value
    with pytest.raises(ProspectiveClockPlanningError, match=message):
        plan_next_prospective_clock(**kwargs)  # type: ignore[arg-type]


def test_rejects_invalid_calendar_hash() -> None:
    bundle = _bundle()
    days = bundle["days"]
    assert isinstance(days, list)
    days[0]["twse"]["source_hash"] = "bad"  # type: ignore[index]
    with pytest.raises(ProspectiveClockPlanningError, match="source_hash"):
        plan_next_prospective_clock(
            now=datetime.fromisoformat("2026-08-28T15:00:00+08:00"),
            owner_decision_timestamp=datetime.fromisoformat(
                "2026-08-28T10:00:00+08:00"
            ),
            calendar_evidence=bundle,
        )


def test_cli_output_is_create_only(tmp_path: Path) -> None:
    # The CLI must write a proposal once and reject a second write rather than
    # silently replacing a reviewed planning artifact.
    calendar_path = tmp_path / "calendar.json"
    calendar_path.write_text(json.dumps(_bundle()), encoding="utf-8")
    output = tmp_path / "plan.json"
    script = Path(__file__).resolve().parents[1] / "scripts" / "plan_prospective_formal_clock.py"
    command = [
        sys.executable,
        str(script),
        "--now",
        "2026-08-28T15:00:00+08:00",
        "--owner-decision-timestamp",
        "2026-08-28T10:00:00+08:00",
        "--calendar-evidence",
        str(calendar_path),
        "--output",
        str(output),
    ]
    first = subprocess.run(command, capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "candidate_ready"

    second = subprocess.run(command, capture_output=True, text=True, check=False)
    assert second.returncode == 2
    assert "already exists" in second.stderr
