from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from data_module.formal_runtime_config import FormalRuntimeConfigError
from scripts.scheduled import run_formal_input_producer_daily as runner


def _predecessor_fixture(tmp_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    bundle = (tmp_path / "rule-source" / "clock-20260909-machine-v2-test").resolve()
    metadata = bundle / "metadata"
    clock = bundle / "clock" / "manifest.json"
    symbols = metadata / "universe_symbols.json"
    owner = metadata / "owner_acceptance.json"
    for path, content in (
        (clock, "clock"),
        (symbols, "symbols"),
        (owner, "owner"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    status_path = tmp_path / "scheduler" / "rule_source_latest_status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status = {
        "status": "rule_source_bundle_reused",
        "exit_code": 0,
        "taipei_date": "2026-09-09",
        "bundle_root": str(bundle),
        "clock_manifest": str(clock),
        "universe_symbols": str(symbols),
        "owner_acceptance": str(owner),
        "source_window_hash": "sha256:" + "1" * 64,
        "consumer_validation": {"status": "machine_revalidation_verified"},
    }
    status_path.write_text(json.dumps(status), encoding="utf-8")
    dependency = {
        "task": "baldr-pit-sector-membership-preopen-capture-daily",
        "source_root": str(bundle.parent.parent),
        "required_status_path": str(status_path),
        "required_exit_code": 0,
        "accepted_statuses": ["rule_source_bundle_created", "rule_source_bundle_reused"],
    }
    projection = {"role_contract": {"rule_source_predecessor": dependency}}
    return projection, status


def test_rule_predecessor_returns_status_bound_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection, status = _predecessor_fixture(tmp_path)
    status_path = Path(
        str(projection["role_contract"]["rule_source_predecessor"]["required_status_path"])
    )
    expected_status_hash = "sha256:" + hashlib.sha256(status_path.read_bytes()).hexdigest()
    monkeypatch.setattr(
        runner,
        "file_sha256",
        lambda _path: pytest.fail("predecessor must hash the parsed status bytes"),
    )
    market_db = tmp_path / "market.sqlite"
    market_db.write_bytes(b"market fixture")
    monkeypatch.setenv("FORMAL_DAILY_MARKET_DB", str(market_db))
    monkeypatch.setattr(
        runner,
        "_validate_exact_rule_source_bundle",
        lambda _bundle_path, *, market_db, observed: {
            "status": "machine_revalidation_verified",
            "source_window_hash": status["source_window_hash"],
        },
    )
    monkeypatch.setenv(
        "FORMAL_DAILY_RULE_SOURCE_ROOT",
        str(tmp_path / "rule-source"),
    )

    result = runner._validate_rule_source_predecessor(
        projection,
        observed=datetime(2026, 9, 9, 1, 0, tzinfo=timezone.utc),
    )

    assert result is not None
    assert result["status"] == status["status"]
    source_paths = result["source_paths"]
    assert isinstance(source_paths, dict)
    assert source_paths["FORMAL_DAILY_CLOCK_MANIFEST"].endswith(
        "clock\\manifest.json"
    )
    assert result["consumer_validation_status"] == "machine_revalidation_verified"
    assert result["status_file_hash"] == expected_status_hash


def test_rule_predecessor_rejects_path_outside_reported_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection, _ = _predecessor_fixture(tmp_path)
    dependency = projection["role_contract"]["rule_source_predecessor"]
    status_path = Path(str(dependency["required_status_path"]))
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    outside = tmp_path / "outside-owner.json"
    outside.write_text("outside", encoding="utf-8")
    payload["owner_acceptance"] = str(outside)
    status_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("FORMAL_DAILY_RULE_SOURCE_ROOT", str(tmp_path / "rule-source"))

    with pytest.raises(
        FormalRuntimeConfigError,
        match="rule_source_predecessor_owner_acceptance_outside_bundle",
    ):
        runner._validate_rule_source_predecessor(
            projection,
            observed=datetime(2026, 9, 9, 1, 0, tzinfo=timezone.utc),
        )


def test_rule_predecessor_rejects_status_source_hash_transcription_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection, _status = _predecessor_fixture(tmp_path)
    market_db = tmp_path / "market.sqlite"
    market_db.write_bytes(b"market fixture")
    monkeypatch.setenv("FORMAL_DAILY_MARKET_DB", str(market_db))
    monkeypatch.setenv("FORMAL_DAILY_RULE_SOURCE_ROOT", str(tmp_path / "rule-source"))
    monkeypatch.setattr(
        runner,
        "_validate_exact_rule_source_bundle",
        lambda _bundle_path, *, market_db, observed: {
            "status": "machine_revalidation_verified",
            "source_window_hash": "sha256:" + "2" * 64,
        },
    )

    with pytest.raises(
        FormalRuntimeConfigError,
        match="rule_source_predecessor_source_window_hash_mismatch",
    ):
        runner._validate_rule_source_predecessor(
            projection,
            observed=datetime(2026, 9, 9, 1, 0, tzinfo=timezone.utc),
        )


def test_formal_runner_consumes_exact_predecessor_paths_without_latest_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection, status_payload = _predecessor_fixture(tmp_path)
    current_day = datetime.now(timezone.utc).astimezone(
        ZoneInfo("Asia/Taipei")
    ).date().isoformat()
    status_path = Path(
        str(projection["role_contract"]["rule_source_predecessor"]["required_status_path"])
    )
    status_payload["taipei_date"] = current_day
    status_path.write_text(json.dumps(status_payload), encoding="utf-8")
    projection["activation_status"] = "active"
    projection["activation_trading_day"] = current_day
    monkeypatch.setattr(
        runner,
        "load_optional_formal_runtime_config",
        lambda *, role, observed: projection,
    )
    market_db = tmp_path / "market.sqlite"
    market_db.write_bytes(b"market fixture")
    monkeypatch.setenv("FORMAL_DAILY_MARKET_DB", str(market_db))
    monkeypatch.setattr(
        runner,
        "_validate_exact_rule_source_bundle",
        lambda _bundle_path, *, market_db, observed: {
            "status": "machine_revalidation_verified",
            "source_window_hash": status_payload["source_window_hash"],
        },
    )
    # This test isolates status/path handoff and stubs the bundle consumer;
    # provide the corresponding valid clock projection for the lineage step
    # instead of leaving the fixture's child file as arbitrary text.
    monkeypatch.setattr(
        runner,
        "load_clock_manifest_for_capture",
        lambda _path, *, now: SimpleNamespace(
            clock_id="clock:test:daily-lineage",
            manifest_hash="sha256:" + "3" * 64,
            activation_trading_day=date.fromisoformat(current_day),
            payload={
                "universe_hash": "sha256:" + "4" * 64,
                "policy_hash": "sha256:" + "5" * 64,
            },
        ),
    )
    monkeypatch.setattr(
        runner,
        "_resolve_required_source_paths",
        lambda **_: pytest.fail("latest source resolver must not run"),
    )
    captured: list[object] = []

    def fake_run(paths: object) -> dict[str, object]:
        captured.append(paths)
        return {
            "status": "candidate_only",
            "formal_ready_input_count": 0,
            "formal_consumer_compatible_count": 0,
            "machine_candidate_input_count": 0,
            "inputs": {},
            "blockers": ["test_only"],
        }

    monkeypatch.setattr(runner, "run_daily_formal_input_producer", fake_run)
    monkeypatch.setenv(
        "FORMAL_DAILY_RULE_SOURCE_ROOT",
        str(tmp_path / "rule-source"),
    )
    clock_path = tmp_path / "portfolio-clock.json"
    clock_path.write_text("portfolio", encoding="utf-8")
    monkeypatch.setenv("FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST", str(clock_path))

    publication_root = tmp_path / "publication"
    status, exit_code = runner.run_from_environment(
        publication_root=publication_root,
        status_root=publication_root / "scheduler",
    )

    assert exit_code == 2
    assert len(captured) == 1
    paths = captured[0]
    assert getattr(paths, "clock_manifest").name == "manifest.json"
    assert str(getattr(paths, "clock_manifest")).startswith(
        str((tmp_path / "rule-source").resolve())
    )
    configuration = status["scheduled_source_configuration"]
    assert isinstance(configuration, dict)
    resolution = configuration["rule_source_resolution"]
    assert isinstance(resolution, dict)
    assert resolution["mode"] == "predecessor_exact_status_paths"
    assert status["scheduled_source_configuration"]["rule_source_predecessor"][
        "source_paths"
    ]
