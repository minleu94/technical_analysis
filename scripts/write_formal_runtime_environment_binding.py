"""Deploy the one-time Formal/Paper runtime binding file.

The command is intentionally the only deployment entrypoint for this
candidate.  A default invocation is a process-only dry-run.  ``--apply``
creates the immutable binding after the five-role preflight; ``--rollback-from``
restores the exact prior binding bytes, or writes a fail-closed inactive marker
when no binding existed before the apply.  No User/System environment and no
Task Scheduler registration are changed.
"""

from __future__ import annotations

import argparse
from base64 import b64decode, b64encode
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import json
import os
import sys
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.formal_runtime_config import (  # noqa: E402
    DEFAULT_RUNTIME_ENVIRONMENT_FILE,
    FORMAL_RUNTIME_CONFIG_ENV,
    FormalRuntimeConfigError,
    RUNTIME_ENVIRONMENT_FILE_ENV,
    build_runtime_environment_binding,
    disable_runtime_environment_binding,
    read_runtime_environment_values,
)
from scripts.qa_formal_runtime_environment_preflight import run_preflight  # noqa: E402


BACKUP_SCHEMA = "formal-runtime-environment-backup.v1"
OUTPUT_ROOT = (ROOT / "output").resolve()


def _payload_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _bytes_hash(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _output_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(OUTPUT_ROOT)
    except ValueError as error:
        raise FormalRuntimeConfigError(
            f"deployment_path_outside_repository_output:{resolved}"
        ) from error
    return resolved


def _write_create_only(path: Path, raw: bytes) -> tuple[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_bytes()
        if existing == raw:
            return "reused", _bytes_hash(existing)
        raise FormalRuntimeConfigError(
            f"deployment_existing_bytes_mismatch:{path}"
        )
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            existing = path.read_bytes()
            if existing == raw:
                return "reused", _bytes_hash(existing)
            raise FormalRuntimeConfigError(
                f"deployment_existing_bytes_mismatch:{path}"
            )
    finally:
        if temporary.exists():
            temporary.unlink()
    return "created", _bytes_hash(raw)


def _backup_payload(target: Path, *, recorded_at: datetime) -> bytes:
    previous_exists = target.is_file()
    previous_bytes = target.read_bytes() if previous_exists else b""
    body: dict[str, object] = {
        "schema_version": BACKUP_SCHEMA,
        "recorded_at": recorded_at.astimezone(timezone.utc).isoformat(
            timespec="microseconds"
        ),
        "target_path": str(target),
        "previous_exists": previous_exists,
        "previous_file_sha256": _bytes_hash(previous_bytes) if previous_exists else None,
        "previous_bytes_base64": b64encode(previous_bytes).decode("ascii")
        if previous_exists
        else None,
        "safety": {
            "candidate_only": True,
            "persistent_environment_written": False,
            "scheduler_written": False,
        },
    }
    payload = {**body, "content_sha256": _payload_hash(body)}
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _read_backup(path: Path, target: Path) -> tuple[bool, bytes]:
    resolved = _output_path(path)
    if not resolved.is_file():
        raise FormalRuntimeConfigError(f"rollback_backup_missing:{resolved}")
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise FormalRuntimeConfigError("rollback_backup_must_be_object")
    if payload.get("schema_version") != BACKUP_SCHEMA:
        raise FormalRuntimeConfigError("rollback_backup_schema_invalid")
    supplied = payload.get("content_sha256")
    body = dict(payload)
    body.pop("content_sha256", None)
    if supplied != _payload_hash(body):
        raise FormalRuntimeConfigError("rollback_backup_content_hash_mismatch")
    recorded_target = Path(str(payload.get("target_path", ""))).expanduser().resolve()
    if recorded_target != target:
        raise FormalRuntimeConfigError("rollback_backup_target_mismatch")
    previous_exists = payload.get("previous_exists") is True
    encoded = payload.get("previous_bytes_base64")
    if not previous_exists:
        if encoded is not None:
            raise FormalRuntimeConfigError("rollback_backup_absent_state_invalid")
        return False, b""
    if not isinstance(encoded, str) or not encoded:
        raise FormalRuntimeConfigError("rollback_backup_bytes_missing")
    try:
        previous = b64decode(encoded.encode("ascii"), validate=True)
    except (ValueError, UnicodeError) as error:
        raise FormalRuntimeConfigError("rollback_backup_bytes_invalid") from error
    if payload.get("previous_file_sha256") != _bytes_hash(previous):
        raise FormalRuntimeConfigError("rollback_backup_file_hash_mismatch")
    return True, previous


def _bind_process_environment(config_path: Path) -> dict[str, str]:
    values = read_runtime_environment_values(config_path)
    for name, value in values.items():
        os.environ[name] = value
    return values


def _preflight(config_path: Path, binding_path: Path, *, load_binding: bool) -> dict[str, object]:
    if load_binding:
        os.environ[RUNTIME_ENVIRONMENT_FILE_ENV] = str(binding_path)
    _bind_process_environment(config_path)
    payload = run_preflight(load_binding=load_binding)
    if payload.get("all_five_roles_verified") is not True:
        raise FormalRuntimeConfigError(
            "runtime_environment_preflight_all_five_roles_not_verified"
        )
    if payload.get("source_pins_present") is not True:
        raise FormalRuntimeConfigError(
            "runtime_environment_preflight_source_pins_missing"
        )
    return payload


def _approved_at(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise FormalRuntimeConfigError("approved_at_invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FormalRuntimeConfigError("approved_at_requires_timezone")
    return parsed


def _backup_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return OUTPUT_ROOT / "v4_next_formal" / (
        f"formal_runtime_environment_backup_{stamp}.json"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config-path",
        type=Path,
        default=ROOT
        / "output"
        / "v4_next_formal"
        / "formal_daily_runtime_config_v6"
        / "2026-09-09.json",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=DEFAULT_RUNTIME_ENVIRONMENT_FILE,
    )
    parser.add_argument("--owner-decision-id")
    parser.add_argument(
        "--approved-at",
        help="timezone-aware root machine review time; defaults to this process time",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="create the active binding after process-only five-role preflight",
    )
    parser.add_argument(
        "--rollback-from",
        type=Path,
        help="restore the exact previous binding recorded by an apply backup",
    )
    parser.add_argument(
        "--disable",
        action="store_true",
        help="write an inactive marker (legacy explicit fail-closed operation)",
    )
    return parser


def _main_impl(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.disable and (args.apply or args.rollback_from is not None):
            raise FormalRuntimeConfigError(
                "--disable cannot be combined with --apply or --rollback-from"
            )
        output_path = _output_path(args.output_path)
        if args.rollback_from is not None:
            if args.apply or args.disable or args.owner_decision_id or args.approved_at:
                raise FormalRuntimeConfigError(
                    "--rollback-from cannot be combined with apply, disable, or owner decision"
                )
            previous_exists, previous = _read_backup(args.rollback_from, output_path)
            if previous_exists:
                status, file_hash = _write_replace(output_path, previous)
                rollback_state = "previous_binding_restored"
            else:
                status, file_hash = disable_runtime_environment_binding(output_path)
                rollback_state = "binding_disabled_fail_closed"
            payload = {
                "status": "rolled_back",
                "rollback_state": rollback_state,
                "path": str(output_path),
                "file_status": status,
                "file_sha256": file_hash,
                "persistent_environment_written": False,
                "scheduler_written": False,
            }
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return 0

        if args.disable:
            if args.owner_decision_id or args.approved_at:
                raise FormalRuntimeConfigError(
                    "--disable cannot be combined with owner decision"
                )
            status, file_hash = disable_runtime_environment_binding(output_path)
            payload = {
                "status": status,
                "path": str(output_path),
                "file_sha256": file_hash,
                "persistent_environment_written": False,
                "scheduler_written": False,
            }
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return 0

        config_path = _output_path(args.config_path)
        preflight = _preflight(config_path, output_path, load_binding=False)
        if preflight.get("status") == "blocked":
            raise FormalRuntimeConfigError("runtime_environment_preflight_blocked")
        if not args.apply:
            payload = {
                "status": "dry_run_verified",
                "config_path": str(config_path),
                "binding_path": str(output_path),
                "preflight": preflight,
                "persistent_environment_written": False,
                "scheduler_written": False,
                "apply_command": (
                    f".\\.venv\\Scripts\\python.exe scripts\\write_formal_runtime_environment_binding.py "
                    f"--config-path \"{config_path}\" --owner-decision-id "
                    "<root-machine-decision-id> --approved-at "
                    "<root-machine-decision-time> --apply"
                ),
                "rollback_command": (
                    ".\\.venv\\Scripts\\python.exe scripts\\write_formal_runtime_environment_binding.py "
                    f"--output-path \"{output_path}\" --rollback-from "
                    "<backup-path>"
                ),
            }
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return 0

        if not isinstance(args.owner_decision_id, str) or not args.owner_decision_id.strip():
            raise FormalRuntimeConfigError(
                "--owner-decision-id is required with --apply"
            )
        backup_path = _backup_path()
        backup_status, backup_hash = _write_create_only(
            backup_path,
            _backup_payload(output_path, recorded_at=datetime.now(timezone.utc)),
        )
        status, file_hash = build_runtime_environment_binding(
            config_path,
            output_path=output_path,
            owner_decision_id=args.owner_decision_id,
            approved_at=_approved_at(args.approved_at),
        )
        try:
            postflight = _preflight(config_path, output_path, load_binding=True)
        except Exception:
            previous_exists, previous = _read_backup(backup_path, output_path)
            if previous_exists:
                _write_replace(output_path, previous)
            else:
                disable_runtime_environment_binding(output_path)
            raise
        payload = {
            "status": "applied",
            "config_path": str(config_path),
            "binding_path": str(output_path),
            "binding_status": status,
            "binding_file_sha256": file_hash,
            "backup_path": str(backup_path),
            "backup_status": backup_status,
            "backup_file_sha256": backup_hash,
            "post_apply_preflight": postflight,
            "persistent_environment_written": False,
            "scheduler_written": False,
        }
    except Exception as error:  # noqa: BLE001 - CLI status boundary
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "blockers": [
                        f"runtime_environment_binding_failed:{type(error).__name__}:{str(error).splitlines()[0][:240]}"
                    ],
                    "persistent_environment_written": False,
                    "scheduler_written": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the deployment command without leaking process-only pins.

    The wrappers need the target map while preflight runs, but callers that
    embed this CLI (including QA) must not inherit a temporary binding after
    the command returns.  Restore the complete process environment on every
    success and failure path; no User/System environment is touched.
    """

    original_environment = dict(os.environ)
    try:
        return _main_impl(argv)
    finally:
        os.environ.clear()
        os.environ.update(original_environment)


def _write_replace(path: Path, raw: bytes) -> tuple[str, str]:
    """Atomically restore a verified rollback snapshot."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.rollback.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return "restored", _bytes_hash(raw)


if __name__ == "__main__":  # pragma: no cover - CLI boundary
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
