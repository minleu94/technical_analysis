from __future__ import annotations

from datetime import date, datetime, time, timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import time as time_module
from zoneinfo import ZoneInfo

import pytest

from scripts import run_daily_ml_allocation_derived_shadow as derived_shadow
from scripts.scheduled import run_ml_allocation_forward_daily as wrapper
from scripts.scheduled import prepare_ml_allocation_forward_config as config_producer


TAIPEI = ZoneInfo("Asia/Taipei")
RUN_DATE = date(2026, 9, 8)
DECISION_AT = datetime(2026, 9, 8, 8, 30, tzinfo=TAIPEI)
DEADLINE_AT = datetime(2026, 9, 8, 8, 35, tzinfo=TAIPEI)


class _CalendarFixture:
    def __init__(self, trading_days: set[date]) -> None:
        self.trading_days = trading_days

    def is_official_trading_day(
        self, target_date: date, allow_online_probe: bool = True
    ) -> tuple[bool, str]:
        del allow_online_probe
        return (
            target_date in self.trading_days,
            "fixture_open" if target_date in self.trading_days else "fixture_closed",
        )


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_config(
    tmp_path: Path,
    *,
    source: dict[str, str],
    run_date: str = "2026-09-08",
) -> Path:
    config_path = tmp_path / "forward_config.json"
    release_root = tmp_path / "release"
    release_root.mkdir(exist_ok=True)
    release_manifest = release_root / "release_manifest.json"
    release_manifest.write_text('{"fixture_release":true}\n', encoding="utf-8")
    payload = {
        "schema_version": "ml-forward-scheduled-config.v1",
        "task_name": "baldr-ml-allocation-forward-daily",
        "decision_timezone": "Asia/Taipei",
        "decision_time": "08:30",
        "scheduled_wake_local": "16:15",
        "run_date": run_date,
        "database": str(tmp_path / "twstock.db"),
        "paper_state_db": str(tmp_path / "paper.sqlite"),
        "output_root": str(tmp_path / "output"),
        "release_root": str(release_root),
        "release_manifest_file_hash": _sha256(release_manifest),
        "natural_forward_deadline_at": "2026-09-08T08:35:00+08:00",
        "source": source,
    }
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    return config_path


def _operational_source(tmp_path: Path) -> dict[str, str]:
    path = tmp_path / "operational.json"
    path.write_text('{"schema_version":"pit-operational.v1"}\n', encoding="utf-8")
    return {
        "kind": "operational_publication",
        "path": str(path),
        "file_hash": _sha256(path),
    }


def _archive_source(tmp_path: Path) -> dict[str, str]:
    root = tmp_path / "pit_candidate_archive"
    root.mkdir()
    manifest = root / "archive_manifest.json"
    manifest.write_text('{"manifest_hash":"sha256:' + "0" * 64 + '"}\n', encoding="utf-8")
    return {
        "kind": "archive",
        "root": str(root),
        "manifest": str(manifest),
        "manifest_file_hash": _sha256(manifest),
    }


def _completed_child_payload(
    *,
    completed_at: datetime = DEADLINE_AT,
    cutoff_date: str | None = "2026-09-07",
    cutoff_reason: str = "fixture_open",
) -> str:
    orchestration: dict[str, object] = {
        "natural_forward_completion_clock": {
            "within_forward_completion_window": True,
            "post_inference_completed_at": completed_at.isoformat(),
            "observation_emitted_at": completed_at.isoformat(),
            "within_forward_emission_window": True,
        },
    }
    if cutoff_date is not None:
        orchestration.update(
            {
                "natural_shadow_maturity_cutoff_date": cutoff_date,
                "natural_shadow_maturity_cutoff_reason": cutoff_reason,
            }
        )
    return json.dumps(
        {
            "status": "completed",
            "daily_orchestration": orchestration,
        }
    )


def test_config_requires_one_exact_operational_source_branch(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, source=_operational_source(tmp_path))
    loaded = wrapper.load_schedule_config(config_path, expected_run_date=RUN_DATE)

    assert loaded.source.kind == "operational_publication"
    assert loaded.deadline_at == DEADLINE_AT
    command = wrapper.build_child_command(loaded, decision_at=DECISION_AT)
    assert "--mode" in command
    assert command[command.index("--mode") + 1] == "forward_natural_date"
    assert "--auto-catch-up" not in command
    assert "--pit-machine-operational-publication" in command
    assert "--pit-machine-archive-root" not in command
    # Keep the caller contract executable by the real child parser.  The
    # forward deadline is derived from decision_at by the ML child; the
    # scheduler verifies the same fixed 08:35 boundary around the process.
    parsed = derived_shadow.build_parser().parse_args(command[2:])
    assert parsed.mode == "forward_natural_date"
    assert parsed.decision_at == DECISION_AT.isoformat(timespec="seconds")
    assert parsed.pit_machine_operational_publication is not None


def test_archive_branch_is_mutually_exclusive_with_operational_branch(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, source=_archive_source(tmp_path))
    loaded = wrapper.load_schedule_config(config_path, expected_run_date=RUN_DATE)
    command = wrapper.build_child_command(loaded, decision_at=DECISION_AT)

    assert "--pit-machine-archive-root" in command
    assert "--pit-machine-archive-manifest" in command
    assert "--pit-machine-archive-manifest-file-hash" in command
    assert "--pit-machine-operational-publication" not in command
    parsed = derived_shadow.build_parser().parse_args(command[2:])
    assert parsed.mode == "forward_natural_date"
    assert parsed.decision_at == DECISION_AT.isoformat(timespec="seconds")
    assert parsed.pit_machine_archive_root == Path(
        command[command.index("--pit-machine-archive-root") + 1]
    )


def test_config_rejects_both_source_branches(tmp_path: Path) -> None:
    source = _operational_source(tmp_path)
    source.update(
        {
            "root": str(tmp_path / "pit_candidate_archive"),
            "manifest": str(tmp_path / "archive_manifest.json"),
            "manifest_file_hash": "sha256:" + "0" * 64,
        }
    )
    config_path = _write_config(tmp_path, source=source)

    with pytest.raises(wrapper.ForwardScheduleConfigError, match="unsupported keys"):
        wrapper.load_schedule_config(config_path, expected_run_date=RUN_DATE)


def test_wait_uses_real_taipei_clock_and_never_sleeps_more_than_one_minute() -> None:
    clock_values = iter(
        [
            datetime(2026, 9, 8, 8, 29, 30, tzinfo=TAIPEI),
            DECISION_AT,
        ]
    )
    sleeps: list[float] = []

    reached = wrapper._wait_until_taipei_cutoff(
        now_fn=lambda: next(clock_values),
        sleep_fn=sleeps.append,
    )

    assert reached == DECISION_AT
    assert sleeps == [pytest.approx(30.0)]
    assert all(value <= 60.0 for value in sleeps)


def test_run_once_before_cutoff_is_blocked_without_reading_config_or_child(
    tmp_path: Path,
) -> None:
    called = False

    def child_runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True
        raise AssertionError("child must not run before 08:30")

    payload, code = wrapper.run_once(
        config_path=tmp_path / "missing.json",
        observed=datetime(2026, 9, 8, 8, 29, tzinfo=TAIPEI),
        status_root_override=tmp_path / "status",
        child_runner=child_runner,
    )

    assert code == 2
    assert payload["status"] == "waiting_for_taipei_cutoff"
    assert called is False


def test_run_once_after_0835_fails_closed_without_loading_source(
    tmp_path: Path,
) -> None:
    payload, code = wrapper.run_once(
        config_path=tmp_path / "missing.json",
        observed=datetime(2026, 9, 8, 8, 36, tzinfo=TAIPEI),
        status_root_override=tmp_path / "status",
    )

    assert code == 2
    assert payload["status"] == "blocked_forward_window_expired"
    assert payload["forward_credit_granted"] is False
    assert (tmp_path / "status" / "latest_status.json").is_file()


def test_run_once_passes_frozen_archive_and_requires_child_completion_gate(
    tmp_path: Path,
) -> None:
    config_path = _write_config(tmp_path, source=_archive_source(tmp_path))
    calls: list[list[str]] = []

    def child_runner(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert kwargs["timeout"] > 0
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=_completed_child_payload(
                completed_at=datetime(2026, 9, 8, 8, 34, tzinfo=TAIPEI)
            ),
            stderr="",
        )

    payload, code = wrapper.run_once(
        config_path=config_path,
        observed=DECISION_AT,
        status_root_override=tmp_path / "status",
        child_runner=child_runner,
        now_fn=lambda: DECISION_AT,
        maturity_calendar=_CalendarFixture({date(2026, 9, 7), RUN_DATE}),
    )

    assert code == 0
    assert payload["status"] == "completed_candidate_shadow"
    assert payload["candidate_forward_gate_verified"] is True
    assert payload["forward_credit_granted"] is False
    assert len(calls) == 1
    assert "--pit-machine-archive-manifest-file-hash" in calls[0]
    assert payload["child_completion_clock"]["within_forward_emission_window"] is True
    persisted = json.loads(
        (tmp_path / "status" / "latest_status.json").read_text(encoding="utf-8")
    )
    assert persisted["receipt_path"]


def test_successful_child_missing_maturity_contract_is_blocked(
    tmp_path: Path,
) -> None:
    config_path = _write_config(tmp_path, source=_operational_source(tmp_path))

    def child_runner(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=_completed_child_payload(cutoff_date=None),
            stderr="",
        )

    payload, code = wrapper.run_once(
        config_path=config_path,
        observed=DECISION_AT,
        status_root_override=tmp_path / "status",
        child_runner=child_runner,
        now_fn=lambda: DECISION_AT,
        maturity_calendar=_CalendarFixture({date(2026, 9, 7), RUN_DATE}),
    )

    assert code == 2
    assert payload["status"] == "blocked_post_deadline_maturity"
    assert payload["forward_credit_granted"] is False
    post_deadline = payload["post_deadline_maturity"]
    assert isinstance(post_deadline, dict)
    assert post_deadline["status"] == "blocked"
    assert post_deadline["blocker"] == "child_maturity_cutoff_contract_missing"


def test_child_maturity_cutoff_must_be_official_strict_t_minus_one(
    tmp_path: Path,
) -> None:
    config_path = _write_config(tmp_path, source=_operational_source(tmp_path))

    def child_runner(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=_completed_child_payload(cutoff_date="2026-09-04"),
            stderr="",
        )

    payload, code = wrapper.run_once(
        config_path=config_path,
        observed=DECISION_AT,
        status_root_override=tmp_path / "status",
        child_runner=child_runner,
        now_fn=lambda: DECISION_AT,
        maturity_calendar=_CalendarFixture({date(2026, 9, 7), RUN_DATE}),
    )

    assert code == 2
    assert payload["status"] == "blocked_post_deadline_maturity"
    post_deadline = payload["post_deadline_maturity"]
    assert isinstance(post_deadline, dict)
    assert post_deadline["blocker"] == (
        "child_maturity_cutoff_not_strict_t_minus_one"
    )
    assert post_deadline["expected_cutoff_date"] == "2026-09-07"


def test_real_child_process_can_finish_then_run_slow_maturity_after_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The child timeout bounds inference; maturity runs in the parent phase."""

    config_path = _write_config(tmp_path, source=_operational_source(tmp_path))
    child_script = tmp_path / "child.py"
    child_script.write_text(
        "import json\n"
        "print(" + repr(_completed_child_payload(
            completed_at=datetime(2026, 9, 8, 8, 34, tzinfo=TAIPEI)
        )) + ")\n",
        encoding="utf-8",
    )
    calls: list[dict[str, object]] = []

    def slow_maturity(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        time_module.sleep(1.1)
        return {
            "mode": "maturity_only",
            "status": "completed",
            "observation_count": 0,
            "matured_observation_count": 0,
            "natural_day_credit_granted": False,
        }

    import scripts.run_daily_ml_allocation_orchestration as orchestration

    monkeypatch.setattr(
        orchestration,
        "run_shadow_maturity_refresh",
        slow_maturity,
    )
    payload, code = wrapper.run_once(
        config_path=config_path,
        observed=DECISION_AT,
        derived_script=child_script,
        status_root_override=tmp_path / "status",
        now_fn=lambda: DEADLINE_AT - timedelta(seconds=1),
        maturity_calendar=_CalendarFixture({date(2026, 9, 7), RUN_DATE}),
    )

    assert code == 0
    assert payload["status"] == "completed_candidate_shadow"
    assert payload["forward_credit_granted"] is False
    assert len(calls) == 1
    assert calls[0]["cutoff_date"] == date(2026, 9, 7)
    post_deadline = payload["post_deadline_maturity"]
    assert isinstance(post_deadline, dict)
    assert post_deadline["post_deadline"] is True
    assert post_deadline["strict_t_minus_one_verified"] is True


def test_timeout_child_still_runs_maturity_with_official_cutoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_config(tmp_path, source=_operational_source(tmp_path))
    calls: list[dict[str, object]] = []

    def child_runner(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output="")

    def maturity(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {"status": "pending_source_missing", "natural_day_credit_granted": False}

    import scripts.run_daily_ml_allocation_orchestration as orchestration

    monkeypatch.setattr(
        orchestration,
        "run_shadow_maturity_refresh",
        maturity,
    )
    payload, code = wrapper.run_once(
        config_path=config_path,
        observed=DECISION_AT,
        status_root_override=tmp_path / "status",
        child_runner=child_runner,
        now_fn=lambda: DECISION_AT,
        maturity_calendar=_CalendarFixture({date(2026, 9, 7), RUN_DATE}),
    )

    assert code == 2
    assert payload["status"] == "blocked_child_timeout"
    assert payload["post_deadline_maturity_degraded"] is False
    assert len(calls) == 1
    assert calls[0]["cutoff_date"] == date(2026, 9, 7)


def test_run_once_rejects_child_without_completion_gate(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, source=_operational_source(tmp_path))

    def child_runner(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {"status": "completed", "daily_orchestration": {}}
            ),
            stderr="",
        )

    payload, code = wrapper.run_once(
        config_path=config_path,
        observed=DECISION_AT,
        status_root_override=tmp_path / "status",
        child_runner=child_runner,
        now_fn=lambda: DECISION_AT,
    )

    assert code == 2
    assert payload["status"] == "blocked_child_completion_gate"
    assert payload["forward_credit_granted"] is False


def test_run_once_rechecks_pinned_release_manifest_before_child(
    tmp_path: Path,
) -> None:
    config_path = _write_config(tmp_path, source=_operational_source(tmp_path))
    release_manifest = tmp_path / "release" / "release_manifest.json"
    release_manifest.write_text('{"fixture_release":"replaced"}\n', encoding="utf-8")
    called = False

    def child_runner(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del command, kwargs
        nonlocal called
        called = True
        raise AssertionError("child must not run after release replacement")

    payload, code = wrapper.run_once(
        config_path=config_path,
        observed=DECISION_AT,
        status_root_override=tmp_path / "status",
        child_runner=child_runner,
        now_fn=lambda: DECISION_AT,
    )

    assert code == 2
    assert payload["status"] == "blocked_source_contract"
    assert "release manifest file hash changed" in str(payload["blockers"])
    assert called is False


@pytest.mark.parametrize("outer_status", ["blocked_capacity", "failed_read_only"])
def test_outer_derived_failure_cannot_be_hidden_by_inner_completed_clock(
    outer_status: str,
) -> None:
    allowed, reason = wrapper._child_completion_is_allowed(
        {
            "status": outer_status,
            "daily_orchestration": {
                "status": "completed",
                "natural_forward_completion_clock": {
                    "within_forward_completion_window": True,
                    "post_inference_completed_at": DEADLINE_AT.isoformat(),
                },
            },
        },
        deadline_at=DEADLINE_AT,
    )
    assert allowed is False
    assert reason == "child_status_not_completed"


def test_cmd_is_prepared_but_does_not_register_a_task() -> None:
    text = Path(
        "scripts/scheduled/run_ml_allocation_forward_daily.cmd"
    ).read_text(encoding="utf-8")

    assert "run_ml_allocation_forward_daily.py" in text
    assert "schtasks" not in text.lower()
    assert "registered 17-task set" in text
    assert "register_baldr_scheduled_tasks" not in text
    assert "v4_ml_daily_derived_shadow_real_v2" in text
    assert "v4_ml_derived_h5_20260907_real_v2" in text
    assert "BALDR_ML_RELEASE_MANIFEST_FILE_HASH" in text


def test_forward_defaults_keep_the_verified_repo_v2_custody(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "ML_FORWARD_OUTPUT_ROOT",
        "BALDR_ML_RELEASE_ROOT",
        "BALDR_ML_RELEASE_MANIFEST_FILE_HASH",
    ):
        monkeypatch.delenv(name, raising=False)

    assert config_producer.default_output_root().name == (
        "v4_ml_daily_derived_shadow_real_v2"
    )
    assert config_producer.default_release_root().name == (
        "v4_ml_derived_h5_20260907_real_v2"
    )
    assert config_producer.default_release_manifest_file_hash() == (
        config_producer.DEFAULT_RELEASE_MANIFEST_FILE_HASH
    )


def test_daily_config_producer_selects_verified_archive_and_is_create_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_root = tmp_path / "pit_candidate_archive"
    manifest_path = archive_root / "2026-09-07" / "archive-a" / "archive_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps({"effective_from": "2026-09-07"}),
        encoding="utf-8",
    )
    fake_result = {
        "status": "machine_verified_archive_candidate",
        "archive_id": "archive-a",
        "archive_manifest_hash": "sha256:" + "1" * 64,
        "archive_manifest_file_hash": _sha256(manifest_path),
        "captured_at": "2026-09-07T18:00:00+08:00",
        "available_at": "2026-09-07T18:00:00+08:00",
        "archived_at": "2026-09-07T18:01:00+08:00",
        "effective_from": "2026-09-07",
        "capture_id": "capture-a",
        "row_count": 1984,
        "source_ids": ["official:tpex:t187ap03_O", "official:twse:t187ap03_L"],
        "current_code_hash_match": True,
        "code_hash_compatibility": "current",
        "legacy_code_hash_compatibility_verified": False,
        "source_custody_verified": True,
        "rows_rebuilt_from_raw": True,
        "candidate_only": True,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "production_action_allowed": False,
    }

    def fake_consumer(**kwargs: object) -> dict[str, object]:
        assert kwargs["manifest_path"] == manifest_path.resolve()
        return fake_result

    import ml_module.pit_archive_consumer as archive_consumer

    monkeypatch.setattr(
        archive_consumer,
        "consume_pit_candidate_archive",
        fake_consumer,
    )
    now = datetime(2026, 9, 8, 8, 30, tzinfo=TAIPEI)
    result = config_producer.prepare_daily_config(
        config_root=tmp_path / "scheduler",
        archive_root=archive_root,
        decision_at=now,
        now=now,
        database=tmp_path / "twstock.db",
        paper_state_db=tmp_path / "paper.sqlite",
        output_root=tmp_path / "output",
        release_root=tmp_path / "release",
        calendar=_CalendarFixture({date(2026, 9, 7), RUN_DATE}),
    )

    config_path = Path(str(result["config_path"]))
    assert result["status"] == "created"
    assert config_path == tmp_path / "scheduler" / "configs" / "2026-09-08.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["run_date"] == "2026-09-08"
    assert config["source"]["kind"] == "archive"
    assert config["source"]["manifest"] == str(manifest_path.resolve())
    assert config["natural_forward_deadline_at"] == "2026-09-08T08:35:00+08:00"
    assert config["release_manifest_file_hash"] == (
        config_producer.DEFAULT_RELEASE_MANIFEST_FILE_HASH
    )
    assert result["create_only"] is True
    assert result["forward_credit_granted"] is False

    reused = config_producer.prepare_daily_config(
        config_root=tmp_path / "scheduler",
        archive_root=archive_root,
        decision_at=now,
        now=now,
        database=tmp_path / "twstock.db",
        paper_state_db=tmp_path / "paper.sqlite",
        output_root=tmp_path / "output",
        release_root=tmp_path / "release",
        calendar=_CalendarFixture({date(2026, 9, 7), RUN_DATE}),
    )
    assert reused["status"] == "reused_existing"


def test_daily_config_producer_rejects_future_or_unverified_only_archives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_root = tmp_path / "pit_candidate_archive"
    manifest_path = archive_root / "2026-09-09" / "future" / "archive_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps({"effective_from": "2026-09-09"}),
        encoding="utf-8",
    )

    import ml_module.pit_archive_consumer as archive_consumer

    def reject(**kwargs: object) -> dict[str, object]:
        raise ValueError("archive is future dated")

    monkeypatch.setattr(archive_consumer, "consume_pit_candidate_archive", reject)
    now = datetime(2026, 9, 8, 8, 30, tzinfo=TAIPEI)
    with pytest.raises(
        config_producer.ForwardConfigProducerError,
        match="no verified PIT archive",
    ):
        config_producer.prepare_daily_config(
            config_root=tmp_path / "scheduler",
            archive_root=archive_root,
            decision_at=now,
            now=now,
            database=tmp_path / "twstock.db",
            paper_state_db=tmp_path / "paper.sqlite",
            output_root=tmp_path / "output",
            release_root=tmp_path / "release",
            calendar=_CalendarFixture({date(2026, 9, 7), RUN_DATE}),
        )


def test_daily_config_producer_uses_one_session_freshness_window_and_hash_freeze(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_root = tmp_path / "pit_candidate_archive"
    manifest_path = archive_root / "2026-09-06" / "stale" / "archive_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps({"effective_from": "2026-09-06"}),
        encoding="utf-8",
    )
    import ml_module.pit_archive_consumer as archive_consumer

    monkeypatch.setattr(
        archive_consumer,
        "consume_pit_candidate_archive",
        lambda **kwargs: {
            "status": "machine_verified_archive_candidate",
            "archive_manifest_file_hash": "sha256:" + "f" * 64,
            "captured_at": "2026-09-06T18:00:00+08:00",
        },
    )
    now = datetime(2026, 9, 8, 8, 30, tzinfo=TAIPEI)
    with pytest.raises(
        config_producer.ForwardConfigProducerError,
        match="no verified PIT archive",
    ):
        config_producer.prepare_daily_config(
            config_root=tmp_path / "scheduler",
            archive_root=archive_root,
            decision_at=now,
            now=now,
            database=tmp_path / "twstock.db",
            paper_state_db=tmp_path / "paper.sqlite",
            output_root=tmp_path / "output",
            release_root=tmp_path / "release",
            calendar=_CalendarFixture({date(2026, 9, 7), RUN_DATE}),
        )

    # The producer must also reject a consumer that reports a hash different
    # from the bytes it actually verified; it may not freeze a replacement.
    current_manifest = (
        archive_root / "2026-09-07" / "hash-mismatch" / "archive_manifest.json"
    )
    current_manifest.parent.mkdir(parents=True)
    current_manifest.write_text(
        json.dumps({"effective_from": "2026-09-07"}),
        encoding="utf-8",
    )
    with pytest.raises(
        config_producer.ForwardConfigProducerError,
        match="no verified PIT archive",
    ):
        config_producer.prepare_daily_config(
            config_root=tmp_path / "scheduler-mismatch",
            archive_root=archive_root,
            decision_at=now,
            now=now,
            database=tmp_path / "twstock.db",
            paper_state_db=tmp_path / "paper.sqlite",
            output_root=tmp_path / "output",
            release_root=tmp_path / "release",
            calendar=_CalendarFixture({date(2026, 9, 7), RUN_DATE}),
        )


def test_daily_config_producer_resolves_cross_weekend_previous_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_root = tmp_path / "pit_candidate_archive"
    manifest_path = archive_root / "2026-09-11" / "friday" / "archive_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps({"effective_from": "2026-09-11"}),
        encoding="utf-8",
    )
    import ml_module.pit_archive_consumer as archive_consumer

    monkeypatch.setattr(
        archive_consumer,
        "consume_pit_candidate_archive",
        lambda **kwargs: {
            "status": "machine_verified_archive_candidate",
            "archive_manifest_file_hash": _sha256(manifest_path),
            "archive_id": "friday",
            "captured_at": "2026-09-11T18:00:00+08:00",
            "effective_from": "2026-09-11",
            "current_code_hash_match": True,
            "code_hash_compatibility": "current",
            "legacy_code_hash_compatibility_verified": False,
            "candidate_only": True,
            "formal_oos_allowed": False,
        },
    )
    monday = datetime(2026, 9, 14, 8, 30, tzinfo=TAIPEI)
    result = config_producer.prepare_daily_config(
        config_root=tmp_path / "scheduler",
        archive_root=archive_root,
        decision_at=monday,
        now=monday,
        database=tmp_path / "twstock.db",
        paper_state_db=tmp_path / "paper.sqlite",
        output_root=tmp_path / "output",
        release_root=tmp_path / "release",
        calendar=_CalendarFixture({date(2026, 9, 11), date(2026, 9, 14)}),
    )
    assert result["status"] == "created"
    assert result["calendar"]["previous_session"] == "2026-09-11"


def test_daily_config_producer_skips_non_trading_and_fails_unknown_calendar(
    tmp_path: Path,
) -> None:
    sunday = datetime(2026, 9, 13, 8, 30, tzinfo=TAIPEI)
    skipped = config_producer.prepare_daily_config(
        config_root=tmp_path / "weekend",
        archive_root=tmp_path / "pit_candidate_archive",
        decision_at=sunday,
        now=sunday,
        database=tmp_path / "twstock.db",
        paper_state_db=tmp_path / "paper.sqlite",
        output_root=tmp_path / "output",
        release_root=tmp_path / "release",
        calendar=_CalendarFixture(set()),
    )
    assert skipped["status"] == "skipped_non_trading_day"
    assert not (tmp_path / "weekend" / "configs").exists()

    class UnknownCalendar:
        def is_official_trading_day(
            self, target_date: date, allow_online_probe: bool = True
        ) -> tuple[None, str]:
            del target_date, allow_online_probe
            return None, "unknown"

    with pytest.raises(
        config_producer.ForwardConfigProducerError,
        match="official calendar is unknown",
    ):
        config_producer.prepare_daily_config(
            config_root=tmp_path / "unknown",
            archive_root=tmp_path / "pit_candidate_archive",
            decision_at=datetime(2026, 9, 8, 8, 30, tzinfo=TAIPEI),
            now=datetime(2026, 9, 8, 8, 30, tzinfo=TAIPEI),
            database=tmp_path / "twstock.db",
            paper_state_db=tmp_path / "paper.sqlite",
            output_root=tmp_path / "output",
            release_root=tmp_path / "release",
            calendar=UnknownCalendar(),
        )


def test_forward_calendar_uses_verified_cache_without_network() -> None:
    from data_module.official_trading_calendar import OfficialTradingCalendar

    cache = Path(
        "output/paper_execution_eod_replay/calendar_cache/"
        "twse_holiday_schedule_2026_20260907_capture1.json"
    )
    closure = cache.parent / "twse_temporary_closure_20260710_af23f921a3376a5a.json"
    calendar = OfficialTradingCalendar(
        db_path=Path("this-database-does-not-exist.sqlite"),
        calendar_cache_path=cache,
        temporary_closure_path=closure,
    )
    assert calendar.is_official_trading_day(
        date(2026, 9, 9), allow_online_probe=False
    ) == (True, "twse_holiday_schedule_cache_open")
    assert calendar.is_official_trading_day(
        date(2026, 9, 8), allow_online_probe=False
    ) == (True, "twse_holiday_schedule_cache_open")
    assert calendar.is_official_trading_day(
        date(2026, 9, 7), allow_online_probe=False
    ) == (True, "twse_holiday_schedule_cache_open")
    assert calendar.is_official_trading_day(
        date(2026, 9, 6), allow_online_probe=False
    ) == (False, "weekend_closed")
