from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.continue_ml_release_after_ooc as continuation


def _write_training_custody(root: Path) -> tuple[Path, str]:
    training = root / "training"
    run = training / "runs" / "allocation-ooc-new"
    run.mkdir(parents=True)
    manifest_hash = "sha256:" + "1" * 64
    manifest = {
        "manifest_hash": manifest_hash,
        "schema_version": "allocation-ooc-training.v5",
    }
    (run / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (training / "latest_manifest.json").write_text(
        json.dumps(
            {
                "manifest_hash": manifest_hash,
                "manifest_path": "runs/allocation-ooc-new/manifest.json",
            }
        ),
        encoding="utf-8",
    )
    (training / "continuation_status.json").write_text(
        json.dumps({"status": "complete"}), encoding="utf-8"
    )
    return training, manifest_hash


def test_main_runs_all_followups_after_completed_ooc(
    tmp_path: Path, monkeypatch
) -> None:
    training, manifest_hash = _write_training_custody(tmp_path)
    calls: list[list[str]] = []
    heartbeat_phases: list[str] = []

    monkeypatch.setattr(
        continuation,
        "_wait_for_ooc_helper_process",
        lambda **_: None,
    )

    class FakeProcess:
        def __init__(self, command_index: int) -> None:
            self.pid = 9000 + command_index
            self._poll_values = iter((None, 0))

        def poll(self) -> int | None:
            return next(self._poll_values)

        def wait(self) -> int:
            return 0

    def fake_popen(command, **_):
        calls.append(list(command))
        return FakeProcess(len(calls))

    monkeypatch.setattr(continuation.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(continuation.time, "sleep", lambda _: None)

    original_publish = continuation._publish_followup_heartbeat

    def capture_heartbeat(**kwargs):
        heartbeat_phases.append(str(kwargs["phase"]))
        original_publish(**kwargs)

    monkeypatch.setattr(
        continuation,
        "_publish_followup_heartbeat",
        capture_heartbeat,
    )

    status_path = tmp_path / "followup.json"
    result = continuation.main(
        [
            "--ooc-helper-process-id",
            "123",
            "--training-output-dir",
            str(training),
            "--output-root",
            str(tmp_path / "output"),
            "--database",
            str(tmp_path / "twstock.db"),
            "--status-path",
            str(status_path),
        ]
    )

    assert result == 0
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["status"] == "complete"
    assert payload["training_manifest_hash"] == manifest_hash
    assert len(calls) == 3
    assert calls[0][1].endswith("run_ml_promotion_evidence_pipeline.py")
    assert calls[1][1].endswith("run_ml_promotion_authority.py")
    assert calls[2][1].endswith("run_daily_ml_allocation_orchestration.py")
    assert "--database" in calls[2]
    assert str(tmp_path / "twstock.db") in calls[2]
    assert "--auto-catch-up" in calls[2]
    continuation_payload = json.loads(
        (training / "continuation_status.json").read_text(encoding="utf-8")
    )
    assert continuation_payload["formal_oos_allowed"] is False
    assert continuation_payload["production_alpha_bp"] == 0
    assert continuation_payload["broker_order_allowed"] is False
    assert continuation_payload["status_contract_normalized_fields"] == [
        "formal_oos_allowed",
        "production_alpha_bp",
        "broker_order_allowed",
    ]
    assert heartbeat_phases.count("followup_command_running") == 6
    assert heartbeat_phases.count("followup_command_complete") == 3


def test_legacy_release_root_resolves_to_shared_operational_output(
    tmp_path: Path,
) -> None:
    shared_output = tmp_path / "output"
    release_root = shared_output / "release_v4"
    training_root = release_root / "portfolio_ml_direct_ooc_training_production_v4_v5"

    assert continuation._operational_output_root(
        chain_output_root=release_root,
        training_output_dir=training_root,
    ) == shared_output.resolve()


def test_unrelated_custom_output_root_is_not_rewritten(tmp_path: Path) -> None:
    custom_output = tmp_path / "custom-output"
    training_root = tmp_path / "training"

    assert continuation._operational_output_root(
        chain_output_root=custom_output,
        training_output_dir=training_root,
    ) == custom_output.resolve()


def test_main_does_not_run_followups_when_ooc_is_blocked(
    tmp_path: Path, monkeypatch
) -> None:
    training = tmp_path / "training"
    training.mkdir()
    (training / "continuation_status.json").write_text(
        json.dumps({"status": "blocked", "message": "failed"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        continuation,
        "_wait_for_ooc_helper_process",
        lambda **_: None,
    )
    monkeypatch.setattr(
        continuation.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("followup must not run")
        ),
    )
    status_path = tmp_path / "followup.json"

    result = continuation.main(
        [
            "--ooc-helper-process-id",
            "123",
            "--training-output-dir",
            str(training),
            "--output-root",
            str(tmp_path / "output"),
            "--database",
            str(tmp_path / "twstock.db"),
            "--status-path",
            str(status_path),
        ]
    )

    assert result == 2
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["status"] == "blocked"
    assert payload["blocker"] == "ooc_continuation_not_complete"


def test_main_blocks_when_training_pointer_is_stale(
    tmp_path: Path, monkeypatch
) -> None:
    training, _ = _write_training_custody(tmp_path)
    (training / "continuation_status.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "training_manifest_hash": "sha256:" + "2" * 64,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        continuation,
        "_wait_for_ooc_helper_process",
        lambda **_: None,
    )
    monkeypatch.setattr(
        continuation.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("followup must not run")
        ),
    )
    status_path = tmp_path / "followup.json"

    result = continuation.main(
        [
            "--ooc-helper-process-id",
            "123",
            "--training-output-dir",
            str(training),
            "--output-root",
            str(tmp_path / "output"),
            "--database",
            str(tmp_path / "twstock.db"),
            "--status-path",
            str(status_path),
        ]
    )

    assert result == 2
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["status"] == "blocked"
    assert payload["error_type"] == "RuntimeError"
    assert payload["message"] == "training_pointer_stale_after_ooc"


def test_main_blocks_when_continuation_status_explicitly_opens_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    training, _ = _write_training_custody(tmp_path)
    (training / "continuation_status.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "formal_oos_allowed": True,
                "production_alpha_bp": 0,
                "broker_order_allowed": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        continuation,
        "_wait_for_ooc_helper_process",
        lambda **_: None,
    )
    monkeypatch.setattr(
        continuation.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("followup must not run")
        ),
    )
    status_path = tmp_path / "followup.json"

    result = continuation.main(
        [
            "--ooc-helper-process-id",
            "123",
            "--training-output-dir",
            str(training),
            "--output-root",
            str(tmp_path / "output"),
            "--database",
            str(tmp_path / "twstock.db"),
            "--status-path",
            str(status_path),
        ]
    )

    assert result == 2
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["status"] == "blocked"
    assert payload["error_type"] == "RuntimeError"
    assert "formal_oos_allowed" in payload["message"]


def test_ooc_process_custody_mismatch_fails_closed() -> None:
    with pytest.raises(
        RuntimeError,
        match="ooc helper process custody mismatch",
    ):
        continuation._assert_expected_ooc_helper_command(
            "python unrelated_worker.py --output-dir c:\\other",
            "c:\\expected-training",
        )


def test_release_heartbeat_preserves_wait_status_and_process_custody(
    tmp_path: Path,
) -> None:
    status_path = tmp_path / "followup.json"
    status_path.write_text(
        json.dumps(
            {
                "status": "waiting_for_ooc_helper",
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
            }
        ),
        encoding="utf-8",
    )

    continuation._publish_followup_heartbeat(
        status_path=status_path,
        process_id=27182,
        command="python continue_ml_direct_ooc_after_store.py --training-output-dir C:\\training",
    )

    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["status"] == "waiting_for_ooc_helper"
    assert payload["heartbeat_schema_version"] == (
        "portfolio-ml-release-followup-heartbeat.v1"
    )
    assert payload["heartbeat_process_id"] == 27182
    assert payload["heartbeat_phase"] == "waiting_for_ooc_helper"
    assert payload["formal_oos_allowed"] is False


def test_followup_command_heartbeat_records_command_custody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    status_path = tmp_path / "followup.json"
    status_path.write_text(
        json.dumps({"status": "running", "formal_oos_allowed": False}),
        encoding="utf-8",
    )

    class FakeProcess:
        pid = 4242

        def __init__(self) -> None:
            self._poll_values = iter((None, 3))

        def poll(self) -> int | None:
            return next(self._poll_values)

        def wait(self) -> int:
            return 3

    monkeypatch.setattr(
        continuation.subprocess,
        "Popen",
        lambda *_args, **_kwargs: FakeProcess(),
    )
    monkeypatch.setattr(continuation.time, "sleep", lambda _: None)

    result = continuation._run_command(
        ["python", "followup.py"],
        status_path=status_path,
        poll_seconds=1,
        command_index=2,
        command_count=3,
    )

    assert result["returncode"] == 3
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["heartbeat_phase"] == "followup_command_complete"
    assert payload["heartbeat_process_id"] == 4242
    assert payload["followup_command_index"] == 2
    assert payload["followup_command_count"] == 3
    assert payload["followup_command_returncode"] == 3
