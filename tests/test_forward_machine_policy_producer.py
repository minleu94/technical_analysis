from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from app_module.forward_machine_policy_producer import (
    DEFAULT_RULES,
    ForwardMachinePolicyProducer,
)


UTC = timezone.utc


class _WeekdayCalendar:
    def is_official_trading_day(self, value, *, allow_online_probe: bool):
        assert allow_online_probe is False
        return (value.weekday() < 5, "fixture_official")


def _calendar(path: Path) -> Path:
    path.write_text(json.dumps({"captured": "fixture"}), encoding="utf-8")
    return path


def test_creates_future_effective_immutable_policy_with_real_clock_and_pin(
    tmp_path: Path,
) -> None:
    calendar_path = _calendar(tmp_path / "calendar.json")
    producer = ForwardMachinePolicyProducer(
        tmp_path / "forward_position_thesis",
        calendar_cache_path=calendar_path,
        calendar=_WeekdayCalendar(),
        now_provider=lambda: datetime(2026, 9, 8, 20, 0, tzinfo=UTC),
    )
    result = producer.create(approval_reference="root-approval-2026-09-08")

    assert result["status"] == "created"
    assert result["effective_from"] == "2026-09-09"
    assert result["available_at"] == "2026-09-08T20:00:00+00:00"
    assert result["policy_bytes_immutable"] is True
    policy_path = Path(result["policy_path"])
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    assert policy["schema_version"] == "forward-position-policy.v1"
    assert policy["candidate_only"] is True
    assert policy["research_only"] is True
    assert policy["auto_action_allowed"] is False
    assert policy["effective_from"] == "2026-09-09"
    assert policy["holding_horizon_trading_days"] == 20
    assert policy["review_cadence_trading_days"] == 5
    assert policy["invalidation_rules"] == list(DEFAULT_RULES)
    snapshot_path = Path(policy["calendar_cache_path"])
    assert snapshot_path != calendar_path.resolve()
    assert snapshot_path.is_file()
    assert snapshot_path.read_bytes() == calendar_path.read_bytes()
    assert policy["calendar_cache_hash"] == "sha256:" + hashlib.sha256(
        calendar_path.read_bytes()
    ).hexdigest()
    assert policy["calendar_source_path"] == str(calendar_path.resolve())
    assert policy["calendar_source_sha256"] == policy["calendar_cache_hash"]
    assert result["policy_file_sha256"] == "sha256:" + hashlib.sha256(
        policy_path.read_bytes()
    ).hexdigest()
    assert Path(result["receipt_path"]).is_file()


def test_same_clock_and_version_is_idempotent_but_changed_bytes_conflict(
    tmp_path: Path,
) -> None:
    calendar_path = _calendar(tmp_path / "calendar.json")
    now = lambda: datetime(2026, 9, 8, 20, 0, tzinfo=UTC)
    producer = ForwardMachinePolicyProducer(
        tmp_path / "forward_position_thesis",
        calendar_cache_path=calendar_path,
        calendar=_WeekdayCalendar(),
        now_provider=now,
    )
    first = producer.create(approval_reference="root-approval-2026-09-08")
    second = producer.create(approval_reference="root-approval-2026-09-08")
    assert second["status"] == "idempotent"
    assert second["policy_file_sha256"] == first["policy_file_sha256"]
    original = Path(first["policy_path"]).read_bytes()

    conflicting = producer.create(
        approval_reference="different-approved-reference",
    )
    assert conflicting["status"] == "blocked"
    assert "policy_version_immutable_conflict" in conflicting["blockers"]
    assert Path(first["policy_path"]).read_bytes() == original


def test_increasing_clock_reuses_policy_and_records_new_observation(
    tmp_path: Path,
) -> None:
    calendar_path = _calendar(tmp_path / "calendar.json")
    clocks = iter(
        [
            datetime(2026, 9, 8, 20, 0, tzinfo=UTC),
            datetime(2026, 9, 8, 20, 0, 1, tzinfo=UTC),
        ]
    )
    producer = ForwardMachinePolicyProducer(
        tmp_path / "forward_position_thesis",
        calendar_cache_path=calendar_path,
        calendar=_WeekdayCalendar(),
        now_provider=lambda: next(clocks),
    )
    first = producer.create(approval_reference="root-approval-2026-09-08")
    policy_path = Path(first["policy_path"])
    original_policy_bytes = policy_path.read_bytes()
    second = producer.create(approval_reference="root-approval-2026-09-08")

    assert second["status"] == "idempotent"
    assert second["policy_observation"] == "reused"
    assert second["policy_path"] == first["policy_path"]
    assert second["policy_file_sha256"] == first["policy_file_sha256"]
    assert second["available_at"] == first["available_at"]
    assert second["observed_at"] == "2026-09-08T20:00:01+00:00"
    assert second["recorded_at"] == second["observed_at"]
    assert Path(second["receipt_path"]).is_file()
    assert Path(second["receipt_path"]) != Path(first["receipt_path"])
    assert policy_path.read_bytes() == original_policy_bytes


def test_calendar_renewal_preserves_policy_identity_and_records_new_observation(
    tmp_path: Path,
) -> None:
    calendar_path = _calendar(tmp_path / "calendar.json")
    producer = ForwardMachinePolicyProducer(
        tmp_path / "forward_position_thesis",
        calendar_cache_path=calendar_path,
        calendar=_WeekdayCalendar(),
        now_provider=lambda: datetime(2026, 9, 8, 20, 0, tzinfo=UTC),
    )
    first = producer.create(approval_reference="root-approval-2026-09-08")
    old_policy = Path(first["policy_path"])
    old_policy_bytes = old_policy.read_bytes()
    old_snapshot = Path(json.loads(old_policy.read_text(encoding="utf-8"))["calendar_cache_path"])
    old_snapshot_bytes = old_snapshot.read_bytes()

    calendar_path.write_text(json.dumps({"captured": "renewed"}), encoding="utf-8")
    renewed_observation = producer.create(approval_reference="root-approval-2026-09-08")
    assert renewed_observation["status"] == "idempotent"
    assert renewed_observation["policy_file_sha256"] == first["policy_file_sha256"]
    assert renewed_observation["calendar_cache_sha256"] == first["calendar_cache_sha256"]
    assert renewed_observation["calendar_observed_sha256"] != first["calendar_cache_sha256"]
    assert renewed_observation["calendar_observed_path"] == str(calendar_path.resolve())
    assert old_policy.read_bytes() == old_policy_bytes
    assert old_snapshot.read_bytes() == old_snapshot_bytes


def test_unknown_official_effective_day_fails_closed_without_policy_file(
    tmp_path: Path,
) -> None:
    calendar_path = _calendar(tmp_path / "calendar.json")

    class _UnknownCalendar:
        def is_official_trading_day(self, value, *, allow_online_probe: bool):
            return (None, "unknown")

    producer = ForwardMachinePolicyProducer(
        tmp_path / "forward_position_thesis",
        calendar_cache_path=calendar_path,
        calendar=_UnknownCalendar(),
        now_provider=lambda: datetime(2026, 9, 8, 20, 0, tzinfo=UTC),
    )
    result = producer.create(approval_reference="root-approval-2026-09-08")
    assert result["status"] == "blocked"
    assert "effective_calendar_day_unknown" in result["blockers"][0]
    assert not list((tmp_path / "forward_position_thesis" / "policies").glob("*.json"))


def test_recommendation_cmd_defaults_to_the_approved_policy_artifact() -> None:
    cmd = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "scheduled"
        / "run_recommendation_snapshot.cmd"
    ).read_text(encoding="utf-8")
    assert (
        'set "FORWARD_THESIS_POLICY_PATH=%REPO_ROOT%\\output\\forward_position_thesis\\'
        'policies\\paper-machine-thesis-benchmark-v1_2026-09-08-approved-v1.json"'
    ) in cmd
