from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import audit_ml_oos_exposure


def _write_json(path: Path, value: dict[str, object]) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _metadata(evidence_id: str) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "sha256": "a" * 64,
        "recorded_at": "2026-07-13T00:00:00Z",
        "access_state": "unopened",
    }


def test_cli_writes_only_to_explicit_isolated_output_and_discloses_safety_flags(
    tmp_path: Path,
) -> None:
    generation = _write_json(tmp_path / "generation.json", _metadata("generation"))
    inventory = _write_json(tmp_path / "inventory.json", _metadata("inventory"))
    declaration = _write_json(
        tmp_path / "declaration.json",
        {
            "declaration_id": "declaration-001",
            "reviewer_identity": "named-reviewer",
            "signed_at": "2026-07-13T00:00:00Z",
            "declares_no_design_influence": True,
        },
    )
    isolated_root = tmp_path / "isolated"
    output = isolated_root / "audit-report.json"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/audit_ml_oos_exposure.py",
            "--generation-manifest-metadata",
            str(generation),
            "--access-inventory",
            str(inventory),
            "--signed-declaration",
            str(declaration),
            "--isolated-output-root",
            str(isolated_root),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "custody_verified_unopened"
    assert '"oos_payload_read": false' in completed.stdout
    assert '"training_performed": false' in completed.stdout
    assert '"formal_oos_changed": false' in completed.stdout


def test_cli_rejects_any_oos_payload_argument_before_creating_output(tmp_path: Path) -> None:
    isolated_root = tmp_path / "isolated"
    output = isolated_root / "audit-report.json"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/audit_ml_oos_exposure.py",
            "--oos-payload",
            str(tmp_path / "forbidden.json"),
            "--isolated-output-root",
            str(isolated_root),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert not output.exists()


def test_cli_refuses_to_overwrite_an_existing_audit_report(tmp_path: Path) -> None:
    generation = _write_json(tmp_path / "generation.json", _metadata("generation"))
    inventory = _write_json(tmp_path / "inventory.json", _metadata("inventory"))
    isolated_root = tmp_path / "isolated"
    output = isolated_root / "audit-report.json"
    output.parent.mkdir(parents=True)
    output.write_text("existing report", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/audit_ml_oos_exposure.py",
            "--generation-manifest-metadata",
            str(generation),
            "--access-inventory",
            str(inventory),
            "--isolated-output-root",
            str(isolated_root),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert output.read_text(encoding="utf-8") == "existing report"


def test_metadata_loader_refuses_forbidden_path_before_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden = _write_json(
        tmp_path / "2025-outcome-report.json",
        _metadata("generation"),
    )
    reads: list[Path] = []
    original_read_text = Path.read_text

    def tracking_read_text(self: Path, *args: object, **kwargs: object) -> str:
        reads.append(self)
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracking_read_text)

    with pytest.raises(ValueError, match="unsafe_metadata_path"):
        audit_ml_oos_exposure._load_object(forbidden)

    assert reads == []


def test_metadata_loader_rejects_outcome_like_or_unknown_keys(tmp_path: Path) -> None:
    metadata = _write_json(
        tmp_path / "generation.json",
        {**_metadata("generation"), "outcome_return_bp": 100},
    )

    with pytest.raises(ValueError, match="metadata_key_not_allowed"):
        audit_ml_oos_exposure._load_object(metadata)
