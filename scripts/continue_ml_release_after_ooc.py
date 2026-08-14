"""Continue ML release checks after the direct-store OOC helper finishes.

This process only coordinates existing fail-closed commands.  It never changes
the production database, promotion alpha, or broker-order authorization.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
_MAX_OUTPUT_CHARS = 4_000
_HEARTBEAT_SCHEMA_VERSION = "portfolio-ml-release-followup-heartbeat.v1"
# Keep release-followup heartbeat writes alive through ordinary Windows file
# scanner locks; after the bounded window the workflow remains fail-closed.
_ATOMIC_REPLACE_RETRY_COUNT = 120
_ATOMIC_REPLACE_RETRY_DELAY_SECONDS = 0.5
_FAIL_CLOSED_GATE_DEFAULTS: dict[str, object] = {
    "formal_oos_allowed": False,
    "production_alpha_bp": 0,
    "broker_order_allowed": False,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ooc-helper-process-id", type=int, required=True)
    parser.add_argument("--training-output-dir", type=Path, required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help=(
            "Chain artifact root. Legacy maintainers pass .../output/release_v4; "
            "the coordinator resolves the operational output root before "
            "invoking scheduled follow-ups."
        ),
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--paper-state-db", type=Path)
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--status-path", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_streams()
    args = build_parser().parse_args(argv)
    training_output_dir = args.training_output_dir.resolve()
    chain_output_root = args.output_root.resolve()
    output_root = _operational_output_root(
        chain_output_root=chain_output_root,
        training_output_dir=training_output_dir,
    )
    database_path = args.database.resolve()
    paper_state_db = (
        args.paper_state_db.resolve()
        if args.paper_state_db is not None
        else output_root / "paper_portfolio" / "paper_portfolio.sqlite"
    )
    status_path = (
        args.status_path.resolve()
        if args.status_path is not None
        else training_output_dir / "post_ooc_followup_status.json"
    )
    _atomic_write_json(
        status_path,
        {
            "status": "waiting_for_ooc_helper",
            "ooc_helper_process_id": args.ooc_helper_process_id,
            "training_output_dir": str(training_output_dir),
            "chain_output_root": str(chain_output_root),
            "operational_output_root": str(output_root),
            "formal_oos_allowed": False,
            "production_alpha_bp": 0,
            "broker_order_allowed": False,
        },
    )
    try:
        _wait_for_ooc_helper_process(
            process_id=args.ooc_helper_process_id,
            expected_training_output_dir=training_output_dir,
            poll_seconds=args.poll_seconds,
            status_path=status_path,
        )
        continuation_status_path = (
            training_output_dir / "continuation_status.json"
        )
        continuation_status = _read_json(continuation_status_path)
        continuation_status = _normalize_continuation_gate_status(
            continuation_status,
            status_path=continuation_status_path,
        )
        if continuation_status.get("status") != "complete":
            payload = {
                "status": "blocked",
                "blocker": "ooc_continuation_not_complete",
                "continuation_status_path": str(continuation_status_path),
                "continuation_status": continuation_status,
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
                "broker_order_allowed": False,
            }
            _atomic_write_json(status_path, payload)
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return 2

        training_manifest_path, training_manifest = _latest_manifest(
            training_output_dir
        )
        continuation_manifest_hash = continuation_status.get(
            "training_manifest_hash"
        )
        if (
            continuation_manifest_hash is not None
            and continuation_manifest_hash != training_manifest.get(
                "manifest_hash"
            )
        ):
            raise RuntimeError("training_pointer_stale_after_ooc")
        commands = _followup_commands(
            output_root=output_root,
            database_path=database_path,
            paper_state_db=paper_state_db,
        )
        command_results = [
            _run_command(
                command,
                status_path=status_path,
                poll_seconds=args.poll_seconds,
                command_index=index,
                command_count=len(commands),
            )
            for index, command in enumerate(commands, start=1)
        ]
        command_failed = any(
            int(result["returncode"]) != 0 for result in command_results
        )
        payload = {
            "status": "blocked" if command_failed else "complete",
            "blocker": (
                "followup_command_failed"
                if command_failed
                else None
            ),
            "continuation_status_path": str(continuation_status_path),
            "training_manifest_path": str(training_manifest_path),
            "training_manifest_hash": training_manifest.get(
                "manifest_hash"
            ),
            "chain_output_root": str(chain_output_root),
            "operational_output_root": str(output_root),
            "command_results": command_results,
            "formal_oos_allowed": False,
            "production_alpha_bp": 0,
            "broker_order_allowed": False,
        }
        _atomic_write_json(status_path, payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if not command_failed else 2
    except Exception as exc:  # noqa: BLE001 - preserve machine-readable status
        payload = {
            "status": "blocked",
            "error_type": type(exc).__name__,
            "message": str(exc),
            "formal_oos_allowed": False,
            "production_alpha_bp": 0,
            "broker_order_allowed": False,
        }
        _atomic_write_json(status_path, payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 2


def _operational_output_root(
    *,
    chain_output_root: Path,
    training_output_dir: Path,
) -> Path:
    """Resolve the shared output root from legacy release-root custody.

    Direct/OOC artifacts live directly under ``output/release_v4`` while the
    promotion, authority, daily-orchestration, and upstream proof contracts
    all take the shared ``output`` root and append ``release_v4`` themselves.
    A legacy chain passes the former path to this coordinator.  Detect that
    exact topology from the training directory instead of relying only on the
    directory name; unrelated custom output roots remain unchanged.
    """

    resolved_chain_root = chain_output_root.resolve()
    resolved_training_root = training_output_dir.resolve()
    if (
        resolved_training_root.parent == resolved_chain_root
        and resolved_chain_root.name.casefold() == "release_v4"
    ):
        return resolved_chain_root.parent
    return resolved_chain_root


def _followup_commands(
    *,
    output_root: Path,
    database_path: Path,
    paper_state_db: Path,
) -> tuple[tuple[str, ...], ...]:
    python = sys.executable
    return (
        (
            python,
            str(ROOT / "scripts" / "run_ml_promotion_evidence_pipeline.py"),
            "--output-root",
            str(output_root),
            "--database",
            str(database_path),
        ),
        (
            python,
            str(ROOT / "scripts" / "run_ml_promotion_authority.py"),
            "--output-root",
            str(output_root),
        ),
        (
            python,
            str(ROOT / "scripts" / "run_daily_ml_allocation_orchestration.py"),
            "--output-root",
            str(output_root),
            "--database",
            str(database_path),
            "--paper-state-db",
            str(paper_state_db),
            "--auto-catch-up",
        ),
    )


def _normalize_continuation_gate_status(
    payload: dict[str, Any],
    *,
    status_path: Path,
) -> dict[str, Any]:
    """Normalize legacy status fields without ever widening a safety gate.

    A helper started by an older checkout may finish with the three explicit
    fail-closed fields absent.  Once that helper has exited, it is safe for
    this downstream coordinator to persist the compatibility fields.  An
    explicit unsafe value is never normalized: it blocks the release chain so
    a malformed or tampered status cannot be treated as a safe completion.
    """

    normalized = dict(payload)
    missing_fields: list[str] = []
    for field, default in _FAIL_CLOSED_GATE_DEFAULTS.items():
        if field not in normalized:
            normalized[field] = default
            missing_fields.append(field)

    if normalized["formal_oos_allowed"] is not False:
        raise RuntimeError(
            "continuation status is not fail-closed: formal_oos_allowed"
        )
    alpha = normalized["production_alpha_bp"]
    if isinstance(alpha, bool) or not isinstance(alpha, int) or alpha != 0:
        raise RuntimeError(
            "continuation status is not fail-closed: production_alpha_bp"
        )
    if normalized["broker_order_allowed"] is not False:
        raise RuntimeError(
            "continuation status is not fail-closed: broker_order_allowed"
        )

    if missing_fields:
        normalized["status_contract_normalized_fields"] = missing_fields
        _atomic_write_json(status_path, normalized)
    return normalized


def _run_command(
    command: Sequence[str],
    *,
    status_path: Path | None = None,
    poll_seconds: int = 15,
    command_index: int | None = None,
    command_count: int | None = None,
) -> dict[str, Any]:
    """Run one follow-up with live process custody and bounded output capture."""

    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    command_list = list(command)
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with (
        tempfile.TemporaryFile(mode="w+b") as stdout_stream,
        tempfile.TemporaryFile(mode="w+b") as stderr_stream,
    ):
        process = subprocess.Popen(
            command_list,
            cwd=ROOT,
            stdout=stdout_stream,
            stderr=stderr_stream,
        )
        while True:
            returncode = process.poll()
            if status_path is not None:
                _publish_followup_heartbeat(
                    status_path=status_path,
                    process_id=process.pid,
                    command=" ".join(command_list),
                    phase="followup_command_running",
                    command_index=command_index,
                    command_count=command_count,
                    command_started_at=started_at,
                    returncode=returncode,
                )
            if returncode is not None:
                break
            time.sleep(poll_seconds)
        process.wait()
        stdout_stream.seek(0)
        stderr_stream.seek(0)
        stdout = stdout_stream.read().decode("utf-8", errors="replace")
        stderr = stderr_stream.read().decode("utf-8", errors="replace")
    if status_path is not None:
        _publish_followup_heartbeat(
            status_path=status_path,
            process_id=process.pid,
            command=" ".join(command_list),
            phase="followup_command_complete",
            command_index=command_index,
            command_count=command_count,
            command_started_at=started_at,
            returncode=int(returncode),
        )
    return {
        "command": command_list,
        "returncode": int(returncode),
        "stdout_tail": stdout[-_MAX_OUTPUT_CHARS:],
        "stderr_tail": stderr[-_MAX_OUTPUT_CHARS:],
    }


def _wait_for_ooc_helper_process(
    *,
    process_id: int,
    expected_training_output_dir: Path,
    poll_seconds: int,
    status_path: Path | None = None,
) -> None:
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError("psutil is required for process custody") from exc
    expected_text = str(expected_training_output_dir).casefold()
    observed_expected_process = False
    while True:
        try:
            process = psutil.Process(process_id)
            command = " ".join(process.cmdline())
            _assert_expected_ooc_helper_command(command, expected_text)
            observed_expected_process = True
            if status_path is not None:
                _publish_followup_heartbeat(
                    status_path=status_path,
                    process_id=process_id,
                    command=command,
                )
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            if not observed_expected_process:
                raise RuntimeError(
                    "ooc helper process was not observed under expected custody"
                )
            return
        time.sleep(poll_seconds)


def _publish_followup_heartbeat(
    *,
    status_path: Path,
    process_id: int,
    command: str,
    phase: str = "waiting_for_ooc_helper",
    command_index: int | None = None,
    command_count: int | None = None,
    command_started_at: str | None = None,
    returncode: int | None = None,
) -> None:
    payload = _read_json(status_path)
    payload.update(
        {
            "heartbeat_schema_version": _HEARTBEAT_SCHEMA_VERSION,
            "heartbeat_at": datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            ),
            "heartbeat_process_id": process_id,
            "heartbeat_phase": phase,
            "heartbeat_command": command,
        }
    )
    if command_index is not None:
        payload["followup_command_index"] = int(command_index)
    if command_count is not None:
        payload["followup_command_count"] = int(command_count)
    if command_started_at is not None:
        payload["followup_command_started_at"] = command_started_at
    if returncode is not None:
        payload["followup_command_returncode"] = int(returncode)
    _atomic_write_json(status_path, payload)


def _assert_expected_ooc_helper_command(
    command: str,
    expected_training_output_dir: str,
) -> None:
    if (
        "continue_ml_direct_ooc_after_store.py" not in command
        or expected_training_output_dir not in command.casefold()
    ):
        raise RuntimeError("ooc helper process custody mismatch")


def _latest_manifest(output_root: Path) -> tuple[Path, dict[str, Any]]:
    pointer = _read_json(output_root / "latest_manifest.json")
    relative = pointer.get("manifest_path")
    if not isinstance(relative, str) or not relative:
        raise TypeError("latest pointer manifest_path must be non-empty text")
    manifest_path = (output_root / relative).resolve()
    if not manifest_path.is_relative_to(output_root):
        raise ValueError("latest pointer escapes output root")
    manifest = _read_json(manifest_path)
    pointer_hash = pointer.get("manifest_hash")
    if pointer_hash != manifest.get("manifest_hash"):
        raise ValueError("latest training pointer hash mismatch")
    return manifest_path, manifest


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return payload


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as stream:
            json.dump(
                payload,
                stream,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(_ATOMIC_REPLACE_RETRY_COUNT):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt + 1 >= _ATOMIC_REPLACE_RETRY_COUNT:
                    raise
                time.sleep(_ATOMIC_REPLACE_RETRY_DELAY_SECONDS)
    finally:
        temporary.unlink(missing_ok=True)


def _configure_utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
