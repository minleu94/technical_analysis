from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from data_module import formal_runtime_roll_forward as roll
from data_module.formal_runtime_config import (
    FORMAL_RUNTIME_CONFIG_ENV,
    load_formal_runtime_config,
    load_optional_formal_runtime_config,
)
from scripts.scheduled import run_formal_pit_sidecar_postcutoff as sidecar_runner
from scripts.scheduled import run_pit_sector_membership_preopen_capture as pit_runner


CALENDAR_SCHEMA = "official-trading-calendar-bundle.v1"
PORTFOLIO_CLOCK_HASH = "sha256:" + "1" * 64


def _calendar_fixture(path: Path) -> Path:
    body: dict[str, object] = {
        "schema_version": CALENDAR_SCHEMA,
        "candidate_only": True,
        "formal_clock_created": False,
        "days": [
            {
                "date": day,
                "twse": {"is_trading_day": True},
                "tpex": {"is_trading_day": True},
            }
            for day in ("2026-09-09", "2026-09-10", "2026-09-11")
        ],
    }
    body["bundle_hash"] = roll._payload_hash(body)
    path.write_text(
        json.dumps(body, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return path


def _write_identity_bundle(path: Path, start: date, end: date) -> dict[str, object]:
    days: list[dict[str, object]] = []
    current = start
    while current <= end:
        days.append(
            {
                "date": current.isoformat(),
                "twse": {"is_trading_day": current.weekday() < 5},
                "tpex": {"is_trading_day": current.weekday() < 5},
            }
        )
        current += timedelta(days=1)
    body: dict[str, object] = {
        "schema_version": CALENDAR_SCHEMA,
        "range": {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "day_count": len(days),
        },
        "candidate_only": True,
        "formal_clock_created": False,
        "days": days,
    }
    body["bundle_hash"] = roll._payload_hash(body)
    path.write_text(
        json.dumps(body, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return body


def _patch_calendar_inspector(
    monkeypatch: pytest.MonkeyPatch,
    bundle_hash: str,
) -> None:
    def inspect(
        _path: Path,
        *,
        activation_date: date,
    ) -> tuple[dict[str, object], list[str]]:
        return (
            {
                "bundle_hash": bundle_hash,
                "twse_open": activation_date != date(2026, 9, 11),
                "tpex_open": activation_date != date(2026, 9, 11),
                "raw_custody": {"verified": True},
            },
            [],
        )

    monkeypatch.setattr(roll, "_inspect_calendar_bundle", inspect)


def _fake_clock(clock_path: Path) -> SimpleNamespace:
    clock_path.write_text("immutable clock", encoding="utf-8")
    return SimpleNamespace(
        clock_id="clock:prospective:20260909:planned-v1",
        manifest_hash=PORTFOLIO_CLOCK_HASH,
        activation_trading_day=date(2026, 9, 9),
        payload={
            "real_money": False,
            "broker_execution": False,
            "historical_backfill_claimed": False,
        },
    )


def _build_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, object], Path]:
    calendar = _calendar_fixture(tmp_path / "calendar.json")
    calendar_hash = roll._payload_hash(
        {
            "schema_version": CALENDAR_SCHEMA,
            "candidate_only": True,
            "formal_clock_created": False,
            "days": [
                {
                    "date": day,
                    "twse": {"is_trading_day": True},
                    "tpex": {"is_trading_day": True},
                }
                for day in ("2026-09-09", "2026-09-10", "2026-09-11")
            ],
        }
    )
    _patch_calendar_inspector(monkeypatch, calendar_hash)
    clock_path = tmp_path / "portfolio-clock.json"
    clock = _fake_clock(clock_path)
    monkeypatch.setattr(roll, "_load_fixed_portfolio_clock", lambda path, *, observed: clock)
    market_db = tmp_path / "market.sqlite"
    market_db.write_bytes(b"read-only market fixture")
    publication = tmp_path / "publication"
    rule_baseline = tmp_path / "rule-baseline"
    rule_baseline.mkdir()
    # build_rolling_runtime_config must perform the same real Rule dependency
    # resolver preflight as production.  This unit fixture supplies a bounded
    # verified result while the dedicated Rule suite exercises the SQLite
    # resolver against its actual source schema.
    monkeypatch.setattr(
        roll,
        "_preflight_rule_dependencies",
        lambda **_: {
            "status": "verified",
            "resolver": "test.formal_rule_source_producer._find_baseline_bundle",
            "calendar_resolver": "test.formal_rule_source_producer._official_calendar_evidence",
            "target_day": str(_.get("target_day")),
        },
    )
    config_path = tmp_path / "runtime" / "2026-09-09.json"
    config = roll.build_rolling_runtime_config(
        observed=datetime(2026, 9, 8, 14, 0, tzinfo=timezone.utc),
        activation_trading_day=date(2026, 9, 9),
        calendar_bundle=calendar,
        portfolio_clock_manifest=clock_path,
        output_path=config_path,
        publication_root=publication,
        market_db=market_db,
        rule_baseline_root=rule_baseline,
        calendar_cache_root=tmp_path / "calendar-cache",
        rule_source_root=publication / "rule-source",
        pit_archive_root=publication / "pit-archive",
        paper_snapshot_db=tmp_path / "paper-snapshot.sqlite",
        paper_fill_db=tmp_path / "paper-fill.sqlite",
        paper_receipt_root=publication / "paper-receipts",
    )
    return config, config_path


def _bind_config_environment(
    monkeypatch: pytest.MonkeyPatch,
    config: dict[str, object],
) -> None:
    wrappers = config["wrapper_contract"]
    assert isinstance(wrappers, dict)
    for role_contract in wrappers.values():
        assert isinstance(role_contract, dict)
        environment = role_contract["environment"]
        assert isinstance(environment, dict)
        for name, value in environment.items():
            if isinstance(value, str) and not value.startswith("omitted;"):
                monkeypatch.setenv(str(name), value)


def test_next_day_uses_calendar_bundle_and_skips_non_open_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calendar = _calendar_fixture(tmp_path / "calendar.json")
    body = json.loads(calendar.read_text(encoding="utf-8"))
    calendar_hash = str(body["bundle_hash"])
    _patch_calendar_inspector(monkeypatch, calendar_hash)

    selected, evidence = roll.select_next_official_trading_day(
        calendar,
        observed=datetime(2026, 9, 8, 8, 0, tzinfo=timezone.utc),
    )

    assert selected == date(2026, 9, 9)
    assert evidence["selection_rule"].startswith("first official")
    assert evidence["twse_open"] is True
    assert evidence["tpex_open"] is True


def test_next_day_rejects_unknown_calendar_evidence_instead_of_skipping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calendar = _calendar_fixture(tmp_path / "calendar.json")
    body = json.loads(calendar.read_text(encoding="utf-8"))
    bundle_hash = str(body["bundle_hash"])

    def inspect(
        _path: Path,
        *,
        activation_date: date,
    ) -> tuple[dict[str, object], list[str]]:
        if activation_date == date(2026, 9, 9):
            return {"bundle_hash": bundle_hash}, [
                "official_calendar_bundle_raw_evidence_missing"
            ]
        return {
            "bundle_hash": bundle_hash,
            "twse_open": True,
            "tpex_open": True,
        }, []

    monkeypatch.setattr(roll, "_inspect_calendar_bundle", inspect)
    with pytest.raises(
        roll.FormalRuntimeRollForwardError,
        match="official_calendar_candidate_invalid:2026-09-09",
    ):
        roll.select_next_official_trading_day(
            calendar,
            observed=datetime(2026, 9, 8, 8, 0, tzinfo=timezone.utc),
        )


def test_explicit_closed_calendar_day_can_be_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calendar = _calendar_fixture(tmp_path / "calendar.json")
    body = json.loads(calendar.read_text(encoding="utf-8"))
    bundle_hash = str(body["bundle_hash"])

    def inspect(
        _path: Path,
        *,
        activation_date: date,
    ) -> tuple[dict[str, object], list[str]]:
        if activation_date == date(2026, 9, 9):
            return {
                "bundle_hash": bundle_hash,
                "twse_open": False,
                "tpex_open": False,
            }, [
                "official_calendar_bundle_twse_activation_day_not_open",
                "official_calendar_bundle_tpex_activation_day_not_open",
            ]
        return {
            "bundle_hash": bundle_hash,
            "twse_open": True,
            "tpex_open": True,
        }, []

    monkeypatch.setattr(roll, "_inspect_calendar_bundle", inspect)
    selected, _ = roll.select_next_official_trading_day(
        calendar,
        observed=datetime(2026, 9, 8, 8, 0, tzinfo=timezone.utc),
    )
    assert selected == date(2026, 9, 10)


def test_calendar_successor_link_is_exact_and_does_not_scan_latest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Use a temp-shaped repository root so the durable link writer is tested
    # without touching this checkout's output.  Production still requires the
    # publication root to be under ROOT/output.
    monkeypatch.setattr(roll, "ROOT", tmp_path)
    publication = tmp_path / "output" / "formal_daily_publications"
    publication.mkdir(parents=True)
    anchor = publication / "calendar-anchor.json"
    successor = publication / "calendar-successor.json"
    anchor_body = _write_identity_bundle(anchor, date(2026, 9, 1), date(2026, 9, 30))
    successor_body = _write_identity_bundle(successor, date(2026, 10, 1), date(2026, 10, 31))
    identities = {
        str(anchor.resolve()): roll._calendar_bundle_identity(anchor),
        str(successor.resolve()): roll._calendar_bundle_identity(successor),
    }

    def inspect(
        path: Path,
        *,
        activation_date: date,
    ) -> tuple[dict[str, object], list[str]]:
        identity = identities[str(path.resolve())]
        if activation_date.weekday() >= 5:
            return {
                "bundle_hash": identity["bundle_hash"],
                "twse_open": False,
                "tpex_open": False,
            }, [
                "official_calendar_bundle_twse_activation_day_not_open",
                "official_calendar_bundle_tpex_activation_day_not_open",
            ]
        return {
            "bundle_hash": identity["bundle_hash"],
            "twse_open": True,
            "tpex_open": True,
            "raw_custody": {"verified": True},
        }, []

    monkeypatch.setattr(roll, "_inspect_calendar_bundle", inspect)
    source = identities[str(anchor.resolve())]
    next_identity = identities[str(successor.resolve())]
    link_path, link_status, _ = roll._write_calendar_successor_link(
        publication_root=publication,
        source=source,
        successor=next_identity,
        requested_start=date(2026, 10, 1),
        requested_end=date(2026, 10, 31),
        observed=datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc),
        capture_evidence={"status": "fixture_replay"},
    )
    assert link_status == "created"
    assert link_path.is_file()
    assert anchor_body["bundle_hash"] == source["bundle_hash"]
    assert successor_body["bundle_hash"] == next_identity["bundle_hash"]

    monkeypatch.setattr(
        roll,
        "_renew_calendar_successor",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("an exact successor link must avoid a new capture")
        ),
    )
    selected, evidence = roll._resolve_calendar_bundle_for_observed(
        anchor,
        publication_root=publication,
        observed=datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc),
    )
    assert selected == successor.resolve()
    assert evidence["chain"][0]["status"] == "successor_link_reused"  # type: ignore[index]


def test_calendar_successor_renewal_reuses_durable_link_after_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(roll, "ROOT", tmp_path)
    publication = tmp_path / "output" / "formal_daily_publications"
    publication.mkdir(parents=True)
    anchor = publication / "calendar-anchor.json"
    _write_identity_bundle(anchor, date(2026, 9, 1), date(2026, 9, 30))
    observed = datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc)
    calls: list[list[str]] = []
    bundle_hash_by_path: dict[str, str] = {}

    def inspect(
        path: Path,
        *,
        activation_date: date,
    ) -> tuple[dict[str, object], list[str]]:
        bundle_hash = bundle_hash_by_path.get(str(path.resolve()))
        if bundle_hash is None:
            identity = roll._calendar_bundle_identity(path)
            bundle_hash = str(identity["bundle_hash"])
            bundle_hash_by_path[str(path.resolve())] = bundle_hash
        if activation_date.weekday() >= 5:
            return {
                "bundle_hash": bundle_hash,
                "twse_open": False,
                "tpex_open": False,
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

    def fake_subprocess(command: list[str], **_: object) -> SimpleNamespace:
        calls.append(command)
        if str(roll.CALENDAR_CAPTURE_SCRIPT) in command:
            output = Path(command[command.index("--output") + 1])
            body = _write_identity_bundle(output, date(2026, 10, 1), date(2026, 10, 31))
            body["raw_evidence"] = {"manifest_hash": "sha256:" + "b" * 64}
            body_without_hash = dict(body)
            body_without_hash.pop("bundle_hash", None)
            body["bundle_hash"] = roll._payload_hash(body_without_hash)
            output.write_text(
                json.dumps(body, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            bundle_hash_by_path[str(output.resolve())] = str(body["bundle_hash"])
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"status": "candidate_captured"}),
                stderr="",
            )

        candidate_path = Path(command[command.index("--bundle") + 1])
        candidate = roll._calendar_bundle_identity(candidate_path)
        archive_root = roll._calendar_archive_root(
            publication,
            activation_day=date(2026, 10, 1),
            bundle_hash=candidate["bundle_hash"],
            raw_manifest_hash="sha256:" + "b" * 64,
        )
        archive_root.mkdir(parents=True)
        (archive_root / candidate_path.name).write_bytes(candidate_path.read_bytes())
        (archive_root / "archive_manifest.json").write_bytes(b"{}")
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"status": "candidate_persisted"}),
            stderr="",
        )

    monkeypatch.setattr(roll, "_inspect_calendar_bundle", inspect)
    monkeypatch.setattr(roll.subprocess, "run", fake_subprocess)
    selected, evidence = roll._resolve_calendar_bundle_for_observed(
        anchor,
        publication_root=publication,
        observed=observed,
    )
    assert selected.is_file()
    assert len(calls) == 2
    capture_command = calls[0]
    assert capture_command[ capture_command.index("--start-date") + 1 ] == "2026-10-01"
    assert capture_command[capture_command.index("--end-date") + 1] == "2026-10-31"
    assert "--confirm-network" in capture_command
    assert "--raw-output-dir" in capture_command
    assert evidence["chain"][0]["status"] == "successor_created"  # type: ignore[index]

    def fail_subprocess(*args: object, **kwargs: object) -> SimpleNamespace:
        raise AssertionError("durable successor link should avoid a second capture")

    monkeypatch.setattr(roll.subprocess, "run", fail_subprocess)
    replayed, replay_evidence = roll._resolve_calendar_bundle_for_observed(
        anchor,
        publication_root=publication,
        observed=observed,
    )
    assert replayed == selected
    assert replay_evidence["chain"][0]["status"] == "successor_link_reused"  # type: ignore[index]


def test_calendar_successor_real_capture_persist_validator_survives_temp_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run the renewal chain with the real parser, persist CLI and validator.

    Only the bounded HTTP boundary is replaced with official-shaped raw
    fixtures.  The capture command still builds its raw-response custody,
    the persist command runs in a real subprocess, and the production
    validator/link reader consume the durable files after the temporary
    candidate tree has been removed.
    """

    from scripts.capture_official_calendar_bundle import main as capture_main

    monkeypatch.setattr(roll, "ROOT", tmp_path)
    publication = tmp_path / "output" / "formal_daily_publications"
    publication.mkdir(parents=True)
    anchor = publication / "calendar-anchor.json"
    _write_identity_bundle(anchor, date(2026, 9, 1), date(2026, 9, 30))

    twse_fixture = tmp_path / "twse-2026.json"
    twse_fixture.write_text(
        json.dumps(
            [
                {
                    "Name": "國慶日",
                    "Date": "1151009",
                    "Description": "依規定放假一日。",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    tpex_data: dict[str, dict[str, object]] = {}
    current = date(2026, 10, 1)
    while current <= date(2026, 10, 31):
        tpex_data[current.strftime("%Y%m%d")] = {
            "holiday": current == date(2026, 10, 9),
            "holidayList": ["國慶日"] if current == date(2026, 10, 9) else [],
        }
        current += timedelta(days=1)
    tpex_fixture = tmp_path / "tpex-202610.json"
    tpex_fixture.write_text(
        json.dumps(
            {
                "status": "success",
                "calendar": {
                    "status": "success",
                    "data": tpex_data,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    import subprocess as subprocess_module

    real_run = subprocess_module.run
    calls: list[list[str]] = []
    capture_temp_paths: list[Path] = []

    def capture_fixture_then_run(
        command: list[str],
        **kwargs: object,
    ) -> SimpleNamespace | object:
        command_text = [str(item) for item in command]
        calls.append(command)
        if str(roll.CALENDAR_CAPTURE_SCRIPT) not in command_text:
            return real_run(command, **kwargs)

        output = Path(command[command.index("--output") + 1])
        raw_output = Path(command[command.index("--raw-output-dir") + 1])
        capture_temp_paths.extend((output, raw_output))
        capture_stdout = io.StringIO()
        capture_stderr = io.StringIO()
        with redirect_stdout(capture_stdout), redirect_stderr(capture_stderr):
            return_code = capture_main(
                [
                    "--start-date",
                    command[command.index("--start-date") + 1],
                    "--end-date",
                    command[command.index("--end-date") + 1],
                    "--twse-fixture",
                    str(twse_fixture),
                    "--tpex-fixture",
                    str(tpex_fixture),
                    "--output",
                    str(output),
                    "--raw-output-dir",
                    str(raw_output),
                ]
            )
        return SimpleNamespace(
            returncode=return_code,
            stdout=capture_stdout.getvalue(),
            stderr=capture_stderr.getvalue(),
        )

    monkeypatch.setattr(roll.subprocess, "run", capture_fixture_then_run)
    selected, evidence = roll._resolve_calendar_bundle_for_observed(
        anchor,
        publication_root=publication,
        observed=datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc),
    )

    assert selected.is_file()
    assert len(calls) == 2
    assert evidence["chain"][0]["status"] == "successor_created"  # type: ignore[index]
    assert evidence["chain"][0]["persistence_status"] == "created"  # type: ignore[index]
    successor_summary = evidence["chain"][0]["successor_bundle"]  # type: ignore[index]
    assert isinstance(successor_summary, dict)
    assert successor_summary["range_start"] == "2026-10-01"
    assert successor_summary["range_end"] == "2026-10-31"
    assert all(not path.exists() for path in capture_temp_paths)

    durable_projection, durable_blockers = roll._inspect_calendar_bundle(
        selected,
        activation_date=date(2026, 10, 1),
    )
    assert durable_blockers == []
    assert durable_projection["raw_custody"]["verified"] is True  # type: ignore[index]
    assert durable_projection["raw_custody"]["inline_source_count"] == 2  # type: ignore[index]

    def fail_if_replayed(*args: object, **kwargs: object) -> object:
        raise AssertionError("durable successor replay must not capture or persist")

    monkeypatch.setattr(roll.subprocess, "run", fail_if_replayed)
    replayed, replay_evidence = roll._resolve_calendar_bundle_for_observed(
        anchor,
        publication_root=publication,
        observed=datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc),
    )
    assert replayed == selected
    assert replay_evidence["chain"][0]["status"] == "successor_link_reused"  # type: ignore[index]

    durable_payload = json.loads(selected.read_text(encoding="utf-8"))
    assert isinstance(durable_payload, dict)
    durable_payload["capture_mode"] = "tampered_fixture"
    selected.write_text(
        json.dumps(durable_payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    with pytest.raises(
        roll.FormalRuntimeRollForwardError,
        match="official_calendar_bundle_hash_invalid",
    ):
        roll._resolve_calendar_bundle_for_observed(
            anchor,
            publication_root=publication,
            observed=datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc),
        )


def test_runtime_candidate_binds_fixed_clock_and_all_wrapper_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, config_path = _build_fixture(tmp_path, monkeypatch)
    assert config["activation_trading_day"] == "2026-09-09"
    evidence = config["source_evidence"]
    assert isinstance(evidence, dict)
    fixed_clock = evidence["fixed_portfolio_clock"]
    assert isinstance(fixed_clock, dict)
    assert fixed_clock["reset_on_each_natural_day"] is False
    assert fixed_clock["daily_rule_clock_is_separate"] is True
    assert not config_path.exists()

    written, file_hash = roll.write_immutable_rolling_runtime_config(
        config_path,
        config,
    )
    assert written == "created"
    assert file_hash.startswith("sha256:")
    _bind_config_environment(monkeypatch, config)
    observed = datetime(2026, 9, 8, 14, 0, tzinfo=timezone.utc)
    wrappers = config["wrapper_contract"]
    assert isinstance(wrappers, dict)
    projections = {
        role: load_formal_runtime_config(
            config_path,
            role=role,
            observed=observed,
        )
        for role in wrappers
    }
    assert set(projections) == {
        "rule_source_wrapper",
        "pit_preopen_wrapper",
        "pit_sidecar_wrapper",
        "formal_input_wrapper",
        "paper_eod_wrapper",
    }
    assert all(
        projection["activation_status"] == "waiting_for_activation"
        for projection in projections.values()
    )
    # 同日盤前 recovery 必須消費已 pin 的設定，不得呼叫 roll-forward
    # 而無聲跳到下一日期。
    recovery = load_formal_runtime_config(
        config_path,
        role="formal_input_wrapper",
        observed=datetime(2026, 9, 9, 0, 0, tzinfo=timezone.utc),
    )
    assert recovery["activation_status"] == "active"


def test_runtime_config_root_auto_binds_exact_natural_day(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, config_path = _build_fixture(tmp_path, monkeypatch)
    roll.write_immutable_rolling_runtime_config(config_path, config)
    _bind_config_environment(monkeypatch, config)
    monkeypatch.delenv(FORMAL_RUNTIME_CONFIG_ENV, raising=False)

    projection = load_optional_formal_runtime_config(
        role="formal_input_wrapper",
        observed=datetime(2026, 9, 9, 0, 0, tzinfo=timezone.utc),
    )

    assert projection is not None
    assert projection["path"] == str(config_path.resolve())
    assert os.environ[FORMAL_RUNTIME_CONFIG_ENV] == str(config_path.resolve())


def test_runtime_config_root_rolls_two_days_without_rebinding_other_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config9, config9_path = _build_fixture(tmp_path, monkeypatch)
    roll.write_immutable_rolling_runtime_config(config9_path, config9)
    calendar_path = tmp_path / "calendar.json"
    clock_path = tmp_path / "portfolio-clock.json"
    config10_path = tmp_path / "runtime" / "2026-09-10.json"
    config10 = roll.build_rolling_runtime_config(
        observed=datetime(2026, 9, 9, 14, 0, tzinfo=timezone.utc),
        activation_trading_day=date(2026, 9, 10),
        calendar_bundle=calendar_path,
        portfolio_clock_manifest=clock_path,
        output_path=config10_path,
        publication_root=tmp_path / "publication",
        market_db=tmp_path / "market.sqlite",
        rule_baseline_root=tmp_path / "rule-baseline",
        calendar_cache_root=tmp_path / "calendar-cache",
        rule_source_root=tmp_path / "publication" / "rule-source",
        pit_archive_root=tmp_path / "publication" / "pit-archive",
        paper_snapshot_db=tmp_path / "paper-snapshot.sqlite",
        paper_fill_db=tmp_path / "paper-fill.sqlite",
        paper_receipt_root=tmp_path / "publication" / "paper-receipts",
    )
    roll.write_immutable_rolling_runtime_config(config10_path, config10)

    # Bind once from the first config.  The next natural day must select the
    # exact date file from the pinned root while preserving every other path.
    _bind_config_environment(monkeypatch, config9)
    fixed_environment = {
        name: os.environ.get(name)
        for name in (
            roll.CALENDAR_BUNDLE_ENV,
            roll.PORTFOLIO_CLOCK_ENV,
            roll.ROLL_FORWARD_ROOT_ENV,
            "FORMAL_DAILY_MARKET_DB",
            "FORMAL_DAILY_PUBLICATION_ROOT",
            "FORMAL_DAILY_RULE_SOURCE_ROOT",
        )
    }
    for observed, expected_path in (
        (datetime(2026, 9, 9, 0, 0, tzinfo=timezone.utc), config9_path),
        (datetime(2026, 9, 10, 0, 0, tzinfo=timezone.utc), config10_path),
    ):
        projections = {
            role: load_optional_formal_runtime_config(
                role=role,
                observed=observed,
            )
            for role in sorted(config9["wrapper_contract"])
        }
        assert all(item is not None for item in projections.values())
        assert all(
            item["activation_status"] == "active"
            for item in projections.values()
            if item is not None
        )
        assert os.environ[FORMAL_RUNTIME_CONFIG_ENV] == str(expected_path.resolve())
        assert {
            name: os.environ.get(name)
            for name in fixed_environment
        } == fixed_environment


def test_runtime_candidate_retry_is_byte_idempotent_and_mutation_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, config_path = _build_fixture(tmp_path, monkeypatch)
    first_status, _ = roll.write_immutable_rolling_runtime_config(
        config_path,
        config,
    )
    second_status, _ = roll.write_immutable_rolling_runtime_config(
        config_path,
        config,
    )
    assert first_status == "created"
    assert second_status == "reused"

    changed = dict(config)
    changed["generated_at"] = "2026-09-08T14:01:00+00:00"
    changed_body = dict(changed)
    changed_body.pop("config_hash", None)
    changed["config_hash"] = roll._payload_hash(changed_body)
    with pytest.raises(
        roll.FormalRuntimeRollForwardError,
        match="runtime_config_existing_bytes_mismatch",
    ):
        roll.write_immutable_rolling_runtime_config(config_path, changed)


def test_runtime_roll_forward_requires_pinned_sources_and_rejects_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(roll.ROLL_FORWARD_ROOT_ENV, str(tmp_path / "roll-forward"))
    monkeypatch.delenv(roll.CALENDAR_BUNDLE_ENV, raising=False)
    monkeypatch.delenv(roll.PORTFOLIO_CLOCK_ENV, raising=False)
    status, exit_code = roll.run_from_environment()
    assert exit_code == 2
    assert status["status"] == "blocked"
    assert f"{roll.CALENDAR_BUNDLE_ENV}_missing" in status["blockers"][0]
    with pytest.raises(
        roll.FormalRuntimeRollForwardError,
        match="does not accept date",
    ):
        roll.main(["--date", "2026-09-09"])


def test_pit_preopen_consumes_same_runtime_binding_before_source_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pit_runner,
        "load_optional_formal_runtime_config",
        lambda *, role, observed: {
            "role": role,
            "activation_status": "waiting_for_activation",
            "activation_trading_day": "2026-09-09",
        },
    )
    payload, exit_code = pit_runner.run_capture(
        publication_root=tmp_path / "publication",
        status_root=tmp_path / "status",
        now=datetime(2026, 9, 8, 14, 0, tzinfo=timezone.utc),
    )
    assert exit_code == 2
    assert payload["status"] == "waiting_for_runtime_config"
    assert payload["formal_runtime_config"]["activation_trading_day"] == "2026-09-09"


def test_pit_sidecar_rejects_invalid_shared_runtime_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sidecar_runner,
        "load_optional_formal_runtime_config",
        lambda *, role, observed: (_ for _ in ()).throw(
            sidecar_runner.FormalRuntimeConfigError("formal_input_wrapper_environment_mismatch")
        ),
    )
    payload, exit_code = sidecar_runner.run_sidecar(
        publication_root=tmp_path / "publication",
        status_root=tmp_path / "status",
        now=datetime(2026, 9, 9, 1, 0, tzinfo=timezone.utc),
    )
    assert exit_code == 2
    assert payload["status"] == "blocked"
    assert payload["blockers"] == [
        "runtime_config_invalid:formal_input_wrapper_environment_mismatch"
    ]
