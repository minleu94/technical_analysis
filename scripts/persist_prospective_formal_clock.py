"""Persist an explicitly validated prospective clock candidate.

The source manifest is copied byte-for-byte into a candidate-only repository
archive.  This script never changes a controlled clock root, market database,
calendar source, scheduler, or broker state.  The candidate remains planned and
simulation-only; persistence does not activate or promote it.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.prospective_formal_clock import (  # noqa: E402
    ProspectiveFormalClockError,
    canonical_json,
    file_sha256,
    load_clock_manifest,
    payload_hash,
)


class ClockPersistenceError(ValueError):
    """The candidate cannot be persisted with an auditable binding."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--activation-date", required=True)
    parser.add_argument("--expected-clock-id", required=True)
    parser.add_argument("--now", required=True)
    parser.add_argument("--publication-root", type=Path, required=True)
    parser.add_argument("--qa-output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        activation = _parse_date(args.activation_date)
        now = _parse_datetime(args.now, "--now")
        source = args.source_manifest.expanduser().resolve()
        publication_root = args.publication_root.expanduser().resolve()
        qa_output = args.qa_output.expanduser().resolve()
        manifest = _load_object(source, "source manifest")
        manifest_hash = _verify_manifest(
            source,
            manifest,
            now=now,
            activation=activation,
            expected_clock_id=args.expected_clock_id,
        )
        archive_root = (
            publication_root
            / "clock_candidate_archive"
            / activation.isoformat()
            / _hash_token(manifest_hash)
        )
        if archive_root.exists():
            raise ClockPersistenceError(
                f"clock candidate archive already exists: {archive_root}"
            )
        archive_root.parent.mkdir(parents=True, exist_ok=True)
        archive_root.mkdir()
        durable_clock = archive_root / "clock" / "manifest.json"
        _copy_create_only(source, durable_clock)
        durable_hash = file_sha256(durable_clock)
        if durable_hash != file_sha256(source):
            raise ClockPersistenceError("durable clock bytes changed during copy")
        durable_clock_obj = _load_object(durable_clock, "durable clock")
        durable_manifest_hash = _verify_manifest(
            durable_clock,
            durable_clock_obj,
            now=now,
            activation=activation,
            expected_clock_id=args.expected_clock_id,
        )
        archive_body: dict[str, object] = {
            "schema_version": "prospective-formal-clock-candidate-archive.v1",
            "activation_date": activation.isoformat(),
            "clock_id": args.expected_clock_id,
            "candidate_only": True,
            "source_manifest_path": str(source),
            "source_manifest_file_hash": file_sha256(source),
            "source_manifest_hash": manifest_hash,
            "durable_manifest_path": str(durable_clock),
            "durable_manifest_file_hash": durable_hash,
            "durable_manifest_hash": durable_manifest_hash,
            "identity_scope": "rule_only_simulation",
            "ml_identity_verified": False,
            "promotion_allowed": False,
            "files": [
                {
                    "role": "clock_manifest",
                    "path": str(durable_clock),
                    "file_hash": durable_hash,
                    "size_bytes": durable_clock.stat().st_size,
                }
            ],
            "validated_at": now.isoformat(),
            "safety": {
                "read_only": True,
                "formal_clock_created": False,
                "formal_oos_allowed": False,
                "promotion_eligible": False,
                "broker_order_allowed": False,
                "market_database_written": False,
                "controlled_paths_written": False,
                "historical_backfill_claimed": False,
                "secret_values_emitted": False,
            },
        }
        archive_body["archive_hash"] = payload_hash(archive_body)
        archive_manifest = archive_root / "archive_manifest.json"
        _write_json_create_only(archive_manifest, archive_body)

        report: dict[str, object] = {
            "schema_version": "prospective-formal-clock-candidate-persistence-qa.v1",
            "status": "candidate_persisted",
            "activation_date": activation.isoformat(),
            "clock_id": args.expected_clock_id,
            "source": {
                "path": str(source),
                "file_hash": file_sha256(source),
                "manifest_hash": manifest_hash,
            },
            "archive": {
                "root": str(archive_root),
                "clock_manifest_path": str(durable_clock),
                "clock_manifest_file_hash": durable_hash,
                "clock_manifest_hash": durable_manifest_hash,
                "archive_manifest_path": str(archive_manifest),
                "archive_manifest_file_hash": file_sha256(archive_manifest),
                "archive_hash": archive_body["archive_hash"],
            },
            "identity_scope": "rule_only_simulation",
            "ml_identity_verified": False,
            "promotion_allowed": False,
            "safety": archive_body["safety"],
        }
        report["report_hash"] = payload_hash(report)
        _write_json_create_only(qa_output, report)
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        ClockPersistenceError,
        ProspectiveFormalClockError,
    ) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": f"{type(error).__name__}: {error}",
                    "candidate_only": True,
                    "formal_clock_created": False,
                    "formal_oos_allowed": False,
                    "promotion_eligible": False,
                    "broker_order_allowed": False,
                    "market_database_written": False,
                    "secret_values_emitted": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    print(
        json.dumps(
            {
                "status": report["status"],
                "activation_date": report["activation_date"],
                "clock_id": report["clock_id"],
                "clock_manifest_path": report["archive"]["clock_manifest_path"],  # type: ignore[index]
                "clock_manifest_file_hash": report["archive"]["clock_manifest_file_hash"],  # type: ignore[index]
                "clock_manifest_hash": report["archive"]["clock_manifest_hash"],  # type: ignore[index]
                "archive_manifest_path": report["archive"]["archive_manifest_path"],  # type: ignore[index]
                "archive_manifest_file_hash": report["archive"]["archive_manifest_file_hash"],  # type: ignore[index]
                "archive_hash": report["archive"]["archive_hash"],  # type: ignore[index]
                "report_hash": report["report_hash"],
                "identity_scope": report["identity_scope"],
                "ml_identity_verified": report["ml_identity_verified"],
                "promotion_allowed": report["promotion_allowed"],
                "read_only": True,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _load_object(path: Path, label: str) -> dict[str, object]:
    if not path.is_file():
        raise ClockPersistenceError(f"{label} is missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ClockPersistenceError(f"{label} root must be an object")
    return value


def _verify_manifest(
    path: Path,
    manifest: Mapping[str, object],
    *,
    now: datetime,
    activation: date,
    expected_clock_id: str,
) -> str:
    if manifest.get("clock_id") != expected_clock_id:
        raise ClockPersistenceError("clock_id does not match explicit expected identity")
    if manifest.get("activation_trading_day") != activation.isoformat():
        raise ClockPersistenceError("activation date does not match explicit archive date")
    if manifest.get("status") != "planned":
        raise ClockPersistenceError("candidate clock must remain planned")
    if manifest.get("real_money") is not False or manifest.get("broker_execution") is not False:
        raise ClockPersistenceError("candidate clock must remain simulation-only")
    supplied = manifest.get("manifest_hash")
    body = dict(manifest)
    body.pop("manifest_hash", None)
    if not isinstance(supplied, str) or supplied != payload_hash(body):
        raise ClockPersistenceError("clock manifest hash is invalid")
    load_clock_manifest(path, now=now)
    return supplied


def _copy_create_only(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as source_stream:
        content = source_stream.read()
    with destination.open("xb") as destination_stream:
        destination_stream.write(content)
        destination_stream.flush()
        os.fsync(destination_stream.fileno())


def _write_json_create_only(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical_json(dict(value)).encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())


def _hash_token(value: str) -> str:
    token = value.removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", token):
        raise ClockPersistenceError("manifest hash is not a SHA-256 token")
    return token


def _parse_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("--activation-date must be YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise ValueError("--activation-date must be YYYY-MM-DD")
    return parsed


def _parse_datetime(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field_name} is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone")
    return parsed.astimezone(timezone.utc)


if __name__ == "__main__":  # pragma: no cover
    from runtime.console_encoding import configure_utf8_console

    configure_utf8_console()
    raise SystemExit(main())
