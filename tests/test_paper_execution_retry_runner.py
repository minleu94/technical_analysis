from __future__ import annotations

from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from data_module import formal_runtime_config
from data_module import formal_runtime_roll_forward as roll

from scripts.scheduled.paper_execution_retry_runner import run_scheduled


OBSERVED = datetime(2026, 9, 8, 13, 0, tzinfo=timezone.utc)


def _write_cross_day_calendar(path: Path) -> tuple[Path, str]:
    """建立隔離的開市／休市 bundle，供自然 caller 的候選產生測試使用。"""

    body: dict[str, object] = {
        "schema_version": "official-trading-calendar-bundle.v1",
        "candidate_only": True,
        "formal_clock_created": False,
        "range": {
            "start_date": "2026-09-09",
            "end_date": "2026-09-14",
            "day_count": 6,
        },
        "days": [
            {
                "date": day,
                "twse": {"is_trading_day": day not in {"2026-09-11", "2026-09-12", "2026-09-13"}},
                "tpex": {"is_trading_day": day not in {"2026-09-11", "2026-09-12", "2026-09-13"}},
            }
            for day in (
                "2026-09-09",
                "2026-09-10",
                "2026-09-11",
                "2026-09-12",
                "2026-09-13",
                "2026-09-14",
            )
        ],
    }
    bundle_hash = roll._payload_hash(body)
    body["bundle_hash"] = bundle_hash
    path.write_text(
        json.dumps(body, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return path, bundle_hash


def test_existing_paper_caller_rolls_runtime_across_natural_days_and_weekend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一組 pin 由既有 Paper caller 連續產生日期檔，固定 portfolio clock 不重置。"""

    calendar_path, bundle_hash = _write_cross_day_calendar(tmp_path / "calendar.json")
    clock_path = tmp_path / "portfolio-clock.json"
    clock_path.write_bytes(b"isolated immutable cumulative portfolio clock")
    runtime_root = tmp_path / "runtime-config"
    publication_root = tmp_path / "publication"
    market_db = tmp_path / "market.sqlite"
    market_db.write_bytes(b"isolated read-only market source")
    rule_baseline_root = tmp_path / "rule-baseline"
    calendar_cache_root = tmp_path / "calendar-cache"
    rule_baseline_root.mkdir()
    calendar_cache_root.mkdir()

    explicit_config = tmp_path / "initial-pinned-config.json"
    environment_values = {
        roll.CALENDAR_BUNDLE_ENV: str(calendar_path.resolve()),
        roll.PORTFOLIO_CLOCK_ENV: str(clock_path.resolve()),
        roll.ROLL_FORWARD_ROOT_ENV: str(runtime_root.resolve()),
        formal_runtime_config.RUNTIME_CONFIG_ROOT_ENV: str(runtime_root.resolve()),
        formal_runtime_config.FORMAL_RUNTIME_CONFIG_ENV: str(explicit_config.resolve()),
        "FORMAL_DAILY_MARKET_DB": str(market_db.resolve()),
        "FORMAL_DAILY_RULE_BASELINE_ROOT": str(rule_baseline_root.resolve()),
        "FORMAL_DAILY_CALENDAR_CACHE_ROOT": str(calendar_cache_root.resolve()),
        "FORMAL_DAILY_PUBLICATION_ROOT": str(publication_root.resolve()),
        "FORMAL_DAILY_RULE_SOURCE_ROOT": str((publication_root / "rule-source").resolve()),
        "FORMAL_DAILY_PIT_PREOPEN_ARCHIVE_ROOT": str((publication_root / "pit-archive").resolve()),
        "FORMAL_DAILY_PAPER_SNAPSHOT_DB": str((tmp_path / "paper-snapshot.sqlite").resolve()),
        "FORMAL_DAILY_PAPER_TRADE_LEDGER_DB": str((tmp_path / "paper-fill.sqlite").resolve()),
        "FORMAL_DAILY_PAPER_RECEIPT_ROOT": str((publication_root / "paper-receipts").resolve()),
    }
    for name, value in environment_values.items():
        monkeypatch.setenv(name, value)

    # The test calls the production function with a temp candidate root only.
    # The actual production path has no test clock injection; this replacement
    # gives run_from_environment a deterministic process clock without writing
    # any controlled or formal output.
    class FrozenRuntimeDateTime:
        current = OBSERVED

        @classmethod
        def now(cls, tz=None):
            value = cls.current
            if tz is None:
                return value.replace(tzinfo=None)
            return value.astimezone(tz)

    def inspect_calendar(
        _path: Path,
        *,
        activation_date: date,
    ) -> tuple[dict[str, object], list[str]]:
        if activation_date in {
            date(2026, 9, 11),
            date(2026, 9, 12),
            date(2026, 9, 13),
        }:
            return {
                "bundle_hash": bundle_hash,
                "twse_open": False,
                "tpex_open": False,
                "raw_custody": {"verified": True},
            }, [
                "official_calendar_bundle_twse_activation_day_not_open",
                "official_calendar_bundle_tpex_activation_day_not_open",
            ]
        return {
            "bundle_hash": bundle_hash,
            "twse_open": True,
            "tpex_open": True,
            "raw_custody": {"verified": True},
        }, []

    fixed_clock = SimpleNamespace(
        clock_id="clock:prospective:20260909:planned-v1",
        manifest_hash="sha256:" + "1" * 64,
        activation_trading_day=date(2026, 9, 9),
        payload={
            "real_money": False,
            "broker_execution": False,
            "historical_backfill_claimed": False,
        },
    )
    monkeypatch.setattr(roll, "datetime", FrozenRuntimeDateTime)
    monkeypatch.setattr(roll, "load_runtime_environment_binding", lambda: None)
    monkeypatch.setattr(
        formal_runtime_config,
        "load_runtime_environment_binding",
        lambda: None,
    )
    monkeypatch.setattr(roll, "_inspect_calendar_bundle", inspect_calendar)
    monkeypatch.setattr(
        roll,
        "_load_fixed_portfolio_clock",
        lambda _path, *, observed: fixed_clock,
    )
    monkeypatch.setattr(
        roll,
        "_preflight_rule_dependencies",
        lambda **kwargs: {
            "status": "verified",
            "resolver": "test.sqlite.rule_dependency_preflight",
            "target_day": str(kwargs["target_day"]),
        },
    )

    expected_days = (
        (datetime(2026, 9, 8, 13, 0, tzinfo=timezone.utc), "2026-09-09"),
        (datetime(2026, 9, 9, 13, 0, tzinfo=timezone.utc), "2026-09-10"),
        (datetime(2026, 9, 10, 13, 0, tzinfo=timezone.utc), "2026-09-14"),
    )
    produced_paths: list[Path] = []
    produced_configs: list[dict[str, object]] = []

    for observed, expected_day in expected_days:
        FrozenRuntimeDateTime.current = observed
        result = run_scheduled(
            max_attempts=1,
            gate_output_root=tmp_path / "dependency-gate" / expected_day,
            gate_fn=lambda: {"status": "ready", "ready": True, "blockers": []},
            adapter_fn=lambda: {
                "status": "waiting_for_execution_source",
                "blockers": ["paper_execution_waiting_for_delayed_eod_source:isolated"],
            },
            sleep_fn=lambda _: None,
            now_fn=lambda observed=observed: observed,
        )

        assert result["status"] == "waiting_for_execution_source"
        runtime = result["runtime_roll_forward"]
        assert isinstance(runtime, dict)
        assert runtime["status"] == "runtime_config_created"
        assert runtime["exit_code"] == 0
        assert runtime["activation_trading_day"] == expected_day
        path = Path(str(runtime["runtime_config_path"]))
        assert path == (runtime_root / f"{expected_day}.json").resolve()
        produced_paths.append(path)
        config = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(config, dict)
        produced_configs.append(config)

        # Same process pins are unchanged.  A fresh Task Scheduler process will
        # use the root and its current Taipei date to select this exact file.
        assert {
            name: os.environ.get(name)
            for name in environment_values
        } == {
            name: environment_values[name]
            for name in environment_values
        }

    assert [path.name for path in produced_paths] == [
        "2026-09-09.json",
        "2026-09-10.json",
        "2026-09-14.json",
    ]
    fixed_clock_records = [
        config["source_evidence"]["fixed_portfolio_clock"]
        for config in produced_configs
    ]
    assert all(isinstance(record, dict) for record in fixed_clock_records)
    assert {
        (
            record["path"],
            record["file_hash"],
            record["clock_id"],
            record["manifest_hash"],
            record["activation_trading_day"],
            record["reset_on_each_natural_day"],
            record["daily_rule_clock_is_separate"],
        )
        for record in fixed_clock_records
    } == {
        (
            str(clock_path.resolve()),
            fixed_clock_records[0]["file_hash"],
            "clock:prospective:20260909:planned-v1",
            "sha256:" + "1" * 64,
            "2026-09-09",
            False,
            True,
        )
    }
    for config, expected_day in zip(produced_configs, ("2026-09-09", "2026-09-10", "2026-09-14")):
        assert config["activation_trading_day"] == expected_day
        paths = config["publication_paths"]
        assert isinstance(paths, dict)
        assert expected_day in paths["rule_history_manifest"]
        assert expected_day in paths["pit_sidecar"]
        assert expected_day in paths["paper_eod_receipt_root"]
        assert paths["portfolio_clock_manifest"] == str(clock_path.resolve())
        assert expected_day.replace("-", "") in paths["common_identity_manifest"]



def test_retry_runner_triggers_runtime_roll_forward_after_paper_window(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def roll_forward() -> dict[str, object]:
        calls.append("roll-forward")
        return {
            "status": "runtime_config_created",
            "exit_code": 0,
            "activation_trading_day": "2026-09-09",
            "runtime_config_path": str(tmp_path / "runtime" / "2026-09-09.json"),
            "candidate_only": True,
            "formal_oos_allowed": False,
        }

    result = run_scheduled(
        max_attempts=1,
        gate_output_root=tmp_path / "gate",
        gate_fn=lambda: {"status": "ready", "ready": True, "blockers": []},
        adapter_fn=lambda: {
            "status": "machine_verified_candidate",
            "blockers": [],
        },
        sleep_fn=lambda _: None,
        now_fn=lambda: OBSERVED,
        roll_forward_fn=roll_forward,
    )

    assert calls == ["roll-forward"]
    runtime = result["runtime_roll_forward"]
    assert isinstance(runtime, dict)
    assert runtime["status"] == "runtime_config_created"
    assert runtime["candidate_only"] is True
    assert runtime["formal_oos_allowed"] is False


def test_retry_runner_uses_explicit_source_pins_for_runtime_roll_forward(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "FORMAL_DAILY_ROLLING_CALENDAR_BUNDLE",
        str(tmp_path / "calendar.json"),
    )
    monkeypatch.setenv(
        "FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST",
        str(tmp_path / "clock.json"),
    )
    events: list[str] = []

    def fake_roll_forward(*, emit: bool) -> tuple[dict[str, object], int]:
        assert emit is False
        events.append("roll-forward")
        return (
            {
                "status": "runtime_config_reused",
                "activation_trading_day": "2026-09-09",
                "runtime_config_path": str(tmp_path / "runtime" / "2026-09-09.json"),
                "runtime_config_file_hash": "sha256:" + "2" * 64,
                "candidate_only": True,
                "formal_oos_allowed": False,
            },
            0,
        )

    monkeypatch.setattr(
        "data_module.formal_runtime_roll_forward.run_from_environment",
        fake_roll_forward,
    )

    result = run_scheduled(
        max_attempts=1,
        gate_output_root=tmp_path / "gate",
        gate_fn=lambda: {"status": "ready", "ready": True, "blockers": []},
        adapter_fn=lambda: (events.append("paper") or {
            "status": "machine_verified_candidate",
            "blockers": [],
        }),
        sleep_fn=lambda _: None,
        now_fn=lambda: OBSERVED,
    )

    assert events == ["paper", "roll-forward"]
    runtime = result["runtime_roll_forward"]
    assert isinstance(runtime, dict)
    assert runtime["status"] == "runtime_config_reused"
    assert runtime["exit_code"] == 0
    assert runtime["candidate_only"] is True


def test_paper_success_with_roll_forward_failure_is_degraded_and_nonzero(
    tmp_path: Path,
) -> None:
    result = run_scheduled(
        max_attempts=1,
        gate_output_root=tmp_path / "gate",
        gate_fn=lambda: {"status": "ready", "ready": True, "blockers": []},
        adapter_fn=lambda: {
            "status": "machine_verified_candidate",
            "blockers": [],
        },
        sleep_fn=lambda _: None,
        now_fn=lambda: OBSERVED,
        roll_forward_fn=lambda: {
            "status": "blocked",
            "exit_code": 2,
            "blockers": ["runtime_roll_forward_failed:calendar"],
            "candidate_only": True,
            "formal_oos_allowed": False,
        },
    )

    assert result["status"] == "degraded_runtime_roll_forward"
    assert result["exit_code"] == 2
    assert result["paper_execution_status"] == "machine_verified_candidate"
    assert result["blockers"] == [
        "runtime_roll_forward_not_ready:blocked",
        "runtime_roll_forward_failed:calendar",
    ]
    runtime = result["runtime_roll_forward"]
    assert isinstance(runtime, dict)
    assert runtime["exit_code"] == 2


def test_configured_runtime_without_source_pins_is_degraded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("FORMAL_DAILY_RUNTIME_CONFIG", str(tmp_path / "current.json"))
    monkeypatch.delenv("FORMAL_DAILY_RUNTIME_CONFIG_ROOT", raising=False)
    monkeypatch.delenv("FORMAL_DAILY_ROLLING_CALENDAR_BUNDLE", raising=False)
    monkeypatch.delenv("FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST", raising=False)

    result = run_scheduled(
        max_attempts=1,
        gate_output_root=tmp_path / "gate",
        gate_fn=lambda: {"status": "ready", "ready": True, "blockers": []},
        adapter_fn=lambda: {
            "status": "machine_verified_candidate",
            "blockers": [],
        },
        sleep_fn=lambda _: None,
        now_fn=lambda: OBSERVED,
    )

    assert result["status"] == "degraded_runtime_roll_forward"
    assert result["exit_code"] == 2
    assert result["paper_execution_status"] == "machine_verified_candidate"
    runtime = result["runtime_roll_forward"]
    assert isinstance(runtime, dict)
    assert runtime["status"] == "runtime_roll_forward_not_configured"
    assert runtime["exit_code"] == 2
    assert "FORMAL_DAILY_ROLLING_CALENDAR_BUNDLE" in runtime["blockers"][0]


def test_retry_runner_retries_only_transient_gate_and_keeps_unique_receipts(tmp_path: Path) -> None:
    gate_results = iter(
        (
            {"status": "blocked", "ready": False, "blockers": ["source_file_missing:x"]},
            {"status": "blocked", "ready": False, "blockers": ["freshness_status_not_passed:running"]},
            {"status": "ready", "ready": True, "blockers": []},
        )
    )
    adapter_calls: list[int] = []
    sleeps: list[float] = []

    def gate() -> dict[str, object]:
        return next(gate_results)

    def adapter() -> dict[str, object]:
        adapter_calls.append(1)
        return {"status": "machine_verified_candidate", "blockers": []}

    result = run_scheduled(
        max_attempts=3,
        retry_delay_seconds=900,
        gate_output_root=tmp_path / "gate",
        gate_fn=gate,
        adapter_fn=adapter,
        sleep_fn=sleeps.append,
        now_fn=lambda: OBSERVED,
    )

    assert result["status"] == "machine_verified_candidate"
    assert len(adapter_calls) == 1
    assert sleeps == [900, 900]
    receipts = sorted((tmp_path / "gate").glob("dependency_gate_*_attempt*.json"))
    assert len(receipts) == 3
    latest = json.loads((tmp_path / "gate" / "latest.json").read_text(encoding="utf-8"))
    assert latest["latest_path"] == str(receipts[-1].resolve())
    attempts = result["scheduled_retry"]["attempts"]  # type: ignore[index]
    assert len(attempts) == 3  # type: ignore[arg-type]
    assert attempts[0]["retry_reason"] == "dependency_gate_transient"  # type: ignore[index]


def test_retry_runner_stops_immediately_on_terminal_gate_blocker(tmp_path: Path) -> None:
    sleeps: list[float] = []
    adapter_called = False

    def adapter() -> dict[str, object]:
        nonlocal adapter_called
        adapter_called = True
        return {"status": "machine_verified_candidate"}

    result = run_scheduled(
        max_attempts=3,
        retry_delay_seconds=900,
        gate_output_root=tmp_path / "gate",
        gate_fn=lambda: {
            "status": "blocked",
            "ready": False,
            "blockers": ["identity_mismatch:controlled_store"],
        },
        adapter_fn=adapter,
        sleep_fn=sleeps.append,
        now_fn=lambda: OBSERVED,
    )

    assert result["status"] == "blocked"
    assert result["blockers"] == ["identity_mismatch:controlled_store"]
    assert sleeps == []
    assert adapter_called is False
    assert len(list((tmp_path / "gate").glob("dependency_gate_*.json"))) == 1


def test_retry_runner_rejects_mixed_or_unknown_gate_blockers(tmp_path: Path) -> None:
    sleeps: list[float] = []
    adapter_called = False

    def adapter() -> dict[str, object]:
        nonlocal adapter_called
        adapter_called = True
        return {"status": "machine_verified_candidate"}

    result = run_scheduled(
        max_attempts=3,
        retry_delay_seconds=900,
        gate_output_root=tmp_path / "gate",
        gate_fn=lambda: {
            "status": "blocked",
            "ready": False,
            "blockers": ["source_file_missing:x", "unknown_contract_blocker"],
        },
        adapter_fn=adapter,
        sleep_fn=sleeps.append,
        now_fn=lambda: OBSERVED,
    )

    assert result["status"] == "blocked"
    assert sleeps == []
    assert adapter_called is False


def test_retry_runner_does_not_treat_embedded_marker_as_transient(tmp_path: Path) -> None:
    sleeps: list[float] = []
    result = run_scheduled(
        max_attempts=3,
        retry_delay_seconds=900,
        gate_output_root=tmp_path / "gate",
        gate_fn=lambda: {
            "status": "blocked",
            "ready": False,
            "blockers": ["identity_mismatch:source_file_missing:claimed"],
        },
        adapter_fn=lambda: {"status": "machine_verified_candidate"},
        sleep_fn=sleeps.append,
        now_fn=lambda: OBSERVED,
    )

    assert result["status"] == "blocked"
    assert sleeps == []


def test_retry_runner_does_not_retry_malformed_receipt(tmp_path: Path) -> None:
    sleeps: list[float] = []
    result = run_scheduled(
        max_attempts=3,
        retry_delay_seconds=900,
        gate_output_root=tmp_path / "gate",
        gate_fn=lambda: {
            "status": "blocked",
            "ready": False,
            "blockers": [
                "quick_update_receipt_unavailable:malformed:latest_status.json:JSONDecodeError"
            ],
        },
        adapter_fn=lambda: {"status": "machine_verified_candidate"},
        sleep_fn=sleeps.append,
        now_fn=lambda: OBSERVED,
    )

    assert result["status"] == "blocked"
    assert sleeps == []


def test_retry_runner_turns_explicit_official_no_data_into_noop(tmp_path: Path) -> None:
    adapter_called = False

    def adapter() -> dict[str, object]:
        nonlocal adapter_called
        adapter_called = True
        return {"status": "machine_verified_candidate"}

    result = run_scheduled(
        max_attempts=3,
        gate_output_root=tmp_path / "gate",
        gate_fn=lambda: {
            "status": "official_no_data",
            "ready": True,
            "blockers": ["source_file_missing:target"],
        },
        adapter_fn=adapter,
        sleep_fn=lambda _: (_ for _ in ()).throw(AssertionError("no sleep expected")),
        now_fn=lambda: OBSERVED,
    )

    assert result["status"] == "skipped_non_trading_day"
    assert result["official_no_data"] is True
    assert result["adapter_called"] is False
    assert adapter_called is False


def test_retry_runner_turns_weekend_gate_into_noop_before_adapter(
    tmp_path: Path,
) -> None:
    adapter_called = False
    roll_forward_called = False

    def adapter() -> dict[str, object]:
        nonlocal adapter_called
        adapter_called = True
        return {"status": "machine_verified_candidate"}

    def roll_forward() -> dict[str, object]:
        nonlocal roll_forward_called
        roll_forward_called = True
        return {
            "status": "runtime_config_created",
            "exit_code": 0,
            "candidate_only": True,
        }

    result = run_scheduled(
        max_attempts=3,
        gate_output_root=tmp_path / "gate",
        gate_fn=lambda: {
            "status": "not_trading_day",
            "ready": True,
            "reason": "taipei_weekend",
        },
        adapter_fn=adapter,
        roll_forward_fn=roll_forward,
        sleep_fn=lambda _: (_ for _ in ()).throw(AssertionError("no sleep expected")),
        now_fn=lambda: OBSERVED,
    )

    assert result["status"] == "skipped_non_trading_day"
    assert result["non_trading_day"] is True
    assert result["official_no_data"] is False
    assert result["adapter_called"] is False
    assert adapter_called is False
    assert roll_forward_called is True
    assert result["runtime_roll_forward"]["status"] == "runtime_config_created"


def test_retry_runner_retries_transient_adapter_source_blocker(tmp_path: Path) -> None:
    adapter_results = iter(
        (
            {
                "status": "blocked",
                "blockers": ["daily_prices is missing execution-date open rows: 2330"],
            },
            {"status": "no_trade_required_candidate", "blockers": []},
        )
    )
    sleeps: list[float] = []

    result = run_scheduled(
        max_attempts=2,
        retry_delay_seconds=15,
        gate_output_root=tmp_path / "gate",
        gate_fn=lambda: {"status": "ready", "ready": True, "blockers": []},
        adapter_fn=lambda: next(adapter_results),
        sleep_fn=sleeps.append,
        now_fn=lambda: OBSERVED,
    )

    assert result["status"] == "no_trade_required_candidate"
    assert sleeps == [15]
    assert len(list((tmp_path / "gate").glob("dependency_gate_*.json"))) == 2
