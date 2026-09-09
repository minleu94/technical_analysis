from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from data_module.formal_runtime_config import (
    FORMAL_RUNTIME_CONFIG_ENV,
    RUNTIME_CONFIG_ROOT_ENV,
    RUNTIME_ENVIRONMENT_FILE_ENV,
    FormalRuntimeConfigError,
    build_runtime_environment_binding,
    load_runtime_environment_binding,
    _payload_hash,
    read_runtime_environment_values,
    load_formal_runtime_config,
)


def _write_binding_candidate(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    output = (tmp_path / "output").resolve()
    runtime_root = output / "runtime"
    config_path = (runtime_root / "2026-09-09.json").resolve()
    values = {
        FORMAL_RUNTIME_CONFIG_ENV: str(config_path),
        RUNTIME_CONFIG_ROOT_ENV: str(runtime_root),
        "FORMAL_DAILY_ROLLING_CALENDAR_BUNDLE": str(output / "calendar.json"),
        "FORMAL_DAILY_RUNTIME_ROLL_FORWARD_ROOT": str(output / "roll-forward"),
        "FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST": str(output / "clock.json"),
    }
    body: dict[str, object] = {
        "schema_version": "formal-paper-9-9-candidate-runtime-config.v1",
        "status": "candidate_ready_for_root_review",
        "wrapper_contract": {
            "formal_input_wrapper": {
                "environment": values,
                "required_environment": list(values),
            }
        },
    }
    body["config_hash"] = _payload_hash(body)
    runtime_root.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return config_path, values


def _write_config(tmp_path: Path) -> tuple[Path, Path]:
    config_path = (tmp_path / "runtime-config.json").resolve()
    portfolio_clock = (tmp_path / "portfolio-clock.json").resolve()
    portfolio_clock.write_text("fixed-clock", encoding="utf-8")
    environment = {
        FORMAL_RUNTIME_CONFIG_ENV: str(config_path),
        "FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST": str(portfolio_clock),
    }
    body: dict[str, object] = {
        "schema_version": "formal-paper-9-9-candidate-runtime-config.v1",
        "status": "candidate_ready_for_root_review",
        "generated_at": "2026-09-08T10:00:00+00:00",
        "activation_trading_day": "2026-09-09",
        "runtime_attestation": {
            "observed_clock_is_runtime_only": True,
            "secret_values_emitted": False,
        },
        "safety": {
            "read_only_sources": True,
            "candidate_only": True,
            "writes_market_database": False,
            "writes_formal_controlled_paths": False,
            "writes_scheduler": False,
            "broker_execution": False,
            "historical_backfill_claimed": False,
        },
        "runtime_config_binding": {
            "environment_variable": FORMAL_RUNTIME_CONFIG_ENV,
            "path": str(config_path),
        },
        "wrapper_contract": {
            "formal_input_wrapper": {
                "entrypoint": "scripts/scheduled/run_formal_input_producer_daily.cmd",
                "environment": environment,
                "required_environment": list(environment),
            }
        },
        "rolling_contract": {
            "schema_version": "formal-paper-runtime-roll-forward.v1",
            "natural_date_timezone": "Asia/Taipei",
            "same_candidate_reuse_prohibited": True,
            "requires_date_scoped_config": True,
            "date_scoped_fields": ["activation_trading_day", "publication_paths"],
            "path_patterns": {
                "runtime_config": "runtime/<YYYY-MM-DD>.json",
                "pit_archive_manifest": "pit/<YYYY-MM-DD>/archive_manifest.json",
                "rule_source_bundle_manifest": "rule/<YYYYMMDD>/clock/manifest.json",
                "rule_history_manifest": "rule_history/<YYYY-MM-DD>/manifest.json",
                "portfolio_clock_manifest": "fixed/portfolio-clock/manifest.json",
                "formal_pit_sidecar": "pit_formal/<YYYY-MM-DD>/sidecar.json",
                "paper_eod_receipt_root": "paper/receipts/<YYYY-MM-DD>/",
                "causal_ledger_manifest": "ledger/<YYYY-MM-DD>/manifest.json",
            },
            "consumer_sequence": ["rule", "paper", "formal"],
        },
        "publication_paths": {},
    }
    body["config_hash"] = _payload_hash(body)
    config_path.write_text(
        json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return config_path, portfolio_clock


def _bind_environment(
    monkeypatch: pytest.MonkeyPatch,
    config_path: Path,
    portfolio_clock: Path,
) -> None:
    monkeypatch.setenv(FORMAL_RUNTIME_CONFIG_ENV, str(config_path))
    monkeypatch.setenv(
        "FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST",
        str(portfolio_clock),
    )


def test_runtime_config_projects_waiting_from_same_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, portfolio_clock = _write_config(tmp_path)
    _bind_environment(monkeypatch, config_path, portfolio_clock)

    projection = load_formal_runtime_config(
        config_path,
        role="formal_input_wrapper",
        observed=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc),
    )

    assert projection["activation_status"] == "waiting_for_activation"
    expected_hash = "sha256:" + hashlib.sha256(config_path.read_bytes()).hexdigest()
    assert projection["file_hash"] == expected_hash
    assert projection["role_contract"]["environment_match"] is True


def test_runtime_config_missing_required_pin_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, portfolio_clock = _write_config(tmp_path)
    monkeypatch.setenv(FORMAL_RUNTIME_CONFIG_ENV, str(config_path))
    monkeypatch.delenv("FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST", raising=False)

    with pytest.raises(
        FormalRuntimeConfigError,
        match="formal_input_wrapper_required_environment_missing:FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST",
    ):
        load_formal_runtime_config(
            config_path,
            role="formal_input_wrapper",
            observed=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc),
        )


def test_runtime_config_legacy_contract_cannot_omit_minimum_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, portfolio_clock = _write_config(tmp_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    del payload["wrapper_contract"]["formal_input_wrapper"]["required_environment"]
    body = dict(payload)
    body.pop("config_hash")
    payload["config_hash"] = _payload_hash(body)
    config_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    monkeypatch.delenv(FORMAL_RUNTIME_CONFIG_ENV, raising=False)
    monkeypatch.delenv("FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST", raising=False)

    with pytest.raises(
        FormalRuntimeConfigError,
        match="formal_input_wrapper_required_environment_missing",
    ):
        load_formal_runtime_config(
            config_path,
            role="formal_input_wrapper",
            observed=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc),
        )


def test_runtime_config_tampering_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, portfolio_clock = _write_config(tmp_path)
    _bind_environment(monkeypatch, config_path, portfolio_clock)
    raw = config_path.read_bytes()
    # Keep schema/status valid so the body hash check is the first failure.
    config_path.write_bytes(
        raw.replace(b"2026-09-08T10:00:00+00:00", b"2026-09-08T10:00:01+00:00")
    )

    with pytest.raises(FormalRuntimeConfigError, match="config_hash_mismatch"):
        load_formal_runtime_config(
            config_path,
            role="formal_input_wrapper",
            observed=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc),
        )


def test_runtime_config_wrong_effective_clock_path_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, portfolio_clock = _write_config(tmp_path)
    _bind_environment(monkeypatch, config_path, tmp_path / "wrong-clock.json")

    with pytest.raises(
        FormalRuntimeConfigError,
        match="formal_input_wrapper_environment_mismatch:FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST",
    ):
        load_formal_runtime_config(
            config_path,
            role="formal_input_wrapper",
            observed=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc),
        )


def test_runtime_environment_binding_is_process_only_and_reloads_exact_map(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import data_module.formal_runtime_config as runtime_config

    monkeypatch.setattr(runtime_config, "_REPO_ROOT", tmp_path.resolve())
    config_path, expected = _write_binding_candidate(tmp_path)
    binding_path = tmp_path / "output" / "binding.json"

    status, file_hash = build_runtime_environment_binding(
        config_path,
        output_path=binding_path,
        owner_decision_id="root-v4-test",
        approved_at=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc),
    )
    assert status == "created"
    assert file_hash.startswith("sha256:")
    assert read_runtime_environment_values(config_path) == expected
    reused, reused_hash = build_runtime_environment_binding(
        config_path,
        output_path=binding_path,
        owner_decision_id="root-v4-test",
        approved_at=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc),
    )
    assert reused == "reused"
    assert reused_hash == file_hash
    with pytest.raises(
        FormalRuntimeConfigError,
        match="runtime_environment_binding_existing_bytes_mismatch",
    ):
        build_runtime_environment_binding(
            config_path,
            output_path=binding_path,
            owner_decision_id="root-v4-different-review",
            approved_at=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc),
        )

    for name in expected:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(RUNTIME_ENVIRONMENT_FILE_ENV, str(binding_path))
    loaded = load_runtime_environment_binding()
    assert loaded == binding_path.resolve()
    assert {name: os.environ[name] for name in expected} == expected
    # The production loader intentionally mutates this process environment;
    # clear that direct mutation explicitly so later scheduler tests do not
    # inherit a temporary fixture's source pins.
    for name in (*expected, RUNTIME_ENVIRONMENT_FILE_ENV):
        os.environ.pop(name, None)


def test_runtime_environment_binding_rejects_allowlist_and_source_map_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import data_module.formal_runtime_config as runtime_config

    monkeypatch.setattr(runtime_config, "_REPO_ROOT", tmp_path.resolve())
    config_path, expected = _write_binding_candidate(tmp_path)
    binding_path = tmp_path / "output" / "binding.json"
    build_runtime_environment_binding(
        config_path,
        output_path=binding_path,
        owner_decision_id="root-v4-test",
        approved_at=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc),
    )

    payload = json.loads(binding_path.read_text(encoding="utf-8"))
    payload["environment"]["FORMAL_DAILY_UNAPPROVED_PATH"] = "C:/unsafe"
    body = dict(payload)
    body.pop("content_sha256")
    payload["content_sha256"] = _payload_hash(body)
    binding_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(RUNTIME_ENVIRONMENT_FILE_ENV, str(binding_path))
    with pytest.raises(
        FormalRuntimeConfigError,
        match="key_not_allowlisted:FORMAL_DAILY_UNAPPROVED_PATH",
    ):
        load_runtime_environment_binding()

    # Keep the binding's own content hash valid, but point an allowed field at
    # a different source.  The loader must compare the map with the exact
    # source-config bytes instead of trusting a re-hashed binding alone.
    payload = json.loads(binding_path.read_text(encoding="utf-8"))
    payload["environment"]["FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST"] = str(
        tmp_path / "output" / "wrong-clock.json"
    )
    payload["environment"].pop("FORMAL_DAILY_UNAPPROVED_PATH", None)
    body = dict(payload)
    body.pop("content_sha256")
    payload["content_sha256"] = _payload_hash(body)
    binding_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        FormalRuntimeConfigError,
        match="config_environment_mismatch",
    ):
        load_runtime_environment_binding()


def test_runtime_environment_binding_rejects_future_machine_decision_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import data_module.formal_runtime_config as runtime_config

    monkeypatch.setattr(runtime_config, "_REPO_ROOT", tmp_path.resolve())
    config_path, _ = _write_binding_candidate(tmp_path)
    with pytest.raises(
        FormalRuntimeConfigError,
        match="owner_decision_timestamp_in_future",
    ):
        build_runtime_environment_binding(
            config_path,
            output_path=tmp_path / "output" / "binding.json",
            owner_decision_id="root-v4-test",
            approved_at=datetime.now(timezone.utc) + timedelta(days=1),
        )


def test_fresh_subprocess_uses_explicit_isolated_binding_path(
    isolated_formal_runtime_subprocess_env: dict[str, str],
) -> None:
    """A runtime-loading CLI subprocess must never inherit deployed binding."""

    repository_root = Path(__file__).resolve().parents[1]
    isolated_binding = Path(
        isolated_formal_runtime_subprocess_env["FORMAL_DAILY_RUNTIME_ENVIRONMENT_FILE"]
    )
    assert not isolated_binding.exists()
    cli = repository_root / "scripts" / "qa_formal_runtime_environment_preflight.py"
    completed = subprocess.run(
        [sys.executable, str(cli)],
        cwd=repository_root,
        env=isolated_formal_runtime_subprocess_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 2, completed.stdout + completed.stderr
    assert "runtime_environment_binding_missing" in completed.stdout
    assert '"status": "blocked"' in completed.stdout
    assert not isolated_binding.exists()


def test_binding_deployment_rejects_apply_before_both_preflight_booleans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import write_formal_runtime_environment_binding as writer

    output = tmp_path / "output"
    monkeypatch.setattr(writer, "OUTPUT_ROOT", output.resolve())
    monkeypatch.setattr(writer, "_bind_process_environment", lambda _path: {})
    monkeypatch.setattr(
        writer,
        "run_preflight",
        lambda **_kwargs: {
            "all_five_roles_verified": False,
            "source_pins_present": True,
        },
    )
    binding = output / "binding.json"
    code = writer.main(
        [
            "--config-path",
            str(output / "config.json"),
            "--output-path",
            str(binding),
            "--owner-decision-id",
            "root-v4-test",
            "--apply",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["status"] == "blocked"
    assert "all_five_roles_not_verified" in payload["blockers"][0]
    assert not binding.exists()
    assert not list(output.glob("formal_runtime_environment_backup_*.json"))


def test_binding_deployment_rolls_back_when_post_apply_preflight_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import write_formal_runtime_environment_binding as writer

    output = tmp_path / "output"
    output.mkdir()
    binding = output / "binding.json"
    config = output / "config.json"
    config.write_text("candidate", encoding="utf-8")
    backup = output / "backup.json"
    monkeypatch.setattr(writer, "OUTPUT_ROOT", output.resolve())
    monkeypatch.setattr(writer, "_backup_path", lambda: backup)
    preflight_calls: list[bool] = []

    def preflight(*_args, **kwargs):
        load_binding = bool(kwargs["load_binding"])
        preflight_calls.append(load_binding)
        if len(preflight_calls) == 1:
            return {
                "all_five_roles_verified": True,
                "source_pins_present": True,
            }
        raise FormalRuntimeConfigError(
            "runtime_environment_preflight_source_pins_missing"
        )

    monkeypatch.setattr(writer, "_preflight", preflight)

    def fake_build(*_args, output_path: Path, **_kwargs):
        output_path.write_bytes(b"active-binding")
        return "created", "sha256:" + "a" * 64

    monkeypatch.setattr(writer, "build_runtime_environment_binding", fake_build)
    disabled = {"called": False}

    def fake_disable(path: Path):
        disabled["called"] = True
        path.write_bytes(b"inactive-marker")
        return "disabled", "sha256:" + "d" * 64

    monkeypatch.setattr(writer, "disable_runtime_environment_binding", fake_disable)
    code = writer.main(
        [
            "--config-path",
            str(config),
            "--output-path",
            str(binding),
            "--owner-decision-id",
            "root-v4-test",
            "--apply",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["status"] == "blocked"
    assert "source_pins_missing" in payload["blockers"][0]
    assert preflight_calls == [False, True]
    assert disabled["called"] is True
    assert binding.read_bytes() == b"inactive-marker"
    assert backup.is_file()
