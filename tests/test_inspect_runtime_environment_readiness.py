from __future__ import annotations

import json
from pathlib import Path

from scripts.inspect_runtime_environment_readiness import main


def test_environment_readiness_cli_emits_json_without_creating_paths(
    tmp_path: Path,
    capsys,
) -> None:
    data_root = tmp_path / "data"
    output_root = tmp_path / "output"
    (data_root / "logs").mkdir(parents=True)
    (output_root / "research_runs").mkdir(parents=True)
    (output_root / "research_runs" / "research_runs.db").write_bytes(b"db")

    result = main(
        [
            "--data-root",
            str(data_root),
            "--output-root",
            str(output_root),
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "runtime-environment-readiness.v1"
    assert payload["overall_state"] == "ready"
    assert payload["side_effect_free"] is True


def test_environment_readiness_cli_returns_attention_code_and_keeps_missing_root_missing(
    tmp_path: Path,
    capsys,
) -> None:
    data_root = tmp_path / "missing-data"
    output_root = tmp_path / "missing-output"

    result = main(
        [
            "--data-root",
            str(data_root),
            "--output-root",
            str(output_root),
            "--format",
            "markdown",
        ]
    )

    output = capsys.readouterr().out
    assert result == 2
    assert "`unavailable`" in output
    assert "data_root_not_created" in output
    assert not data_root.exists()
    assert not output_root.exists()


def test_environment_readiness_cli_actual_write_probe_is_explicit_and_ephemeral(
    tmp_path: Path,
    capsys,
) -> None:
    data_root = tmp_path / "formal-data"
    output_root = tmp_path / "formal-output"
    probe_root = tmp_path / "staging"
    data_root.mkdir()
    output_root.mkdir()
    probe_root.mkdir()

    result = main(
        [
            "--data-root",
            str(data_root),
            "--output-root",
            str(output_root),
            "--write-probe-root",
            str(probe_root),
            "--confirm-write-probe",
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "runtime-environment-write-probe.v1"
    assert payload["status"] == "passed"
    assert payload["side_effect_free"] is False
    assert payload["write_probe"] == "actual_ephemeral_registry_transaction"
    assert payload["registry_transaction_succeeded"] is True
    assert not list(probe_root.iterdir())


def test_environment_readiness_cli_write_probe_without_confirmation_does_not_write(
    tmp_path: Path,
    capsys,
) -> None:
    data_root = tmp_path / "formal-data"
    output_root = tmp_path / "formal-output"
    probe_root = tmp_path / "staging"
    data_root.mkdir()
    output_root.mkdir()
    probe_root.mkdir()

    result = main(
        [
            "--data-root",
            str(data_root),
            "--output-root",
            str(output_root),
            "--write-probe-root",
            str(probe_root),
        ]
    )

    assert result == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "confirmation_required"
    assert payload["side_effect_free"] is True
    assert not list(probe_root.iterdir())


def test_environment_readiness_cli_can_save_write_probe_artifact(
    tmp_path: Path,
    capsys,
) -> None:
    data_root = tmp_path / "formal-data"
    output_root = tmp_path / "formal-output"
    probe_root = tmp_path / "staging"
    artifact = tmp_path / "runtime-write-probe.json"
    data_root.mkdir()
    output_root.mkdir()
    probe_root.mkdir()

    result = main(
        [
            "--data-root",
            str(data_root),
            "--output-root",
            str(output_root),
            "--write-probe-root",
            str(probe_root),
            "--confirm-write-probe",
            "--output",
            str(artifact),
        ]
    )

    assert result == 0
    assert json.loads(artifact.read_text(encoding="utf-8"))["status"] == "passed"
    assert json.loads(capsys.readouterr().out)["status"] == "passed"
    assert not list(probe_root.iterdir())
