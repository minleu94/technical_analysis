"""Persist a verified official-calendar candidate without changing its bytes.

The input bundle and its raw-response directory are copied into a durable,
candidate-only repository archive.  The bundle filename and raw directory name
are retained so the bundle's relative raw-evidence binding remains valid.
No market database, controlled path, scheduler, or broker state is written.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.formal_next_clock_preparation import (  # noqa: E402
    _inspect_calendar_raw_custody,
)
from data_module.prospective_formal_clock import file_sha256, payload_hash  # noqa: E402


class CalendarPersistenceError(ValueError):
    """A candidate cannot be copied with an independently verifiable binding."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--activation-date", required=True)
    parser.add_argument("--publication-root", type=Path, required=True)
    parser.add_argument("--qa-output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        activation = _parse_date(args.activation_date)
        source_path = args.bundle.expanduser().resolve()
        publication_root = args.publication_root.expanduser().resolve()
        qa_output = args.qa_output.expanduser().resolve()
        source_bundle = _load_json(source_path, "bundle")
        source_bundle_hash = _verify_bundle(source_path, source_bundle)
        source_projection, source_blockers = _inspect_calendar_raw_custody(
            source_path,
            source_bundle,
        )
        if source_blockers:
            raise CalendarPersistenceError(
                "source raw custody blockers: " + ", ".join(source_blockers)
            )
        _verify_activation_day(source_bundle, activation)
        raw_evidence = source_bundle.get("raw_evidence")
        if not isinstance(raw_evidence, Mapping):
            raise CalendarPersistenceError("bundle raw_evidence is missing")
        raw_manifest_ref = raw_evidence.get("manifest_path")
        if not isinstance(raw_manifest_ref, str) or not raw_manifest_ref.strip():
            raise CalendarPersistenceError("bundle raw manifest path is missing")
        source_manifest = (source_path.parent / raw_manifest_ref).resolve()
        if not source_manifest.is_file():
            raise CalendarPersistenceError("source raw manifest is missing")
        manifest = _load_json(source_manifest, "raw manifest")
        entries = manifest.get("entries")
        if not isinstance(entries, list) or not entries:
            raise CalendarPersistenceError("raw manifest entries are missing")

        manifest_hash = str(manifest.get("manifest_hash", ""))
        archive_root = (
            publication_root
            / "calendar_candidate_archive"
            / activation.isoformat()
            / f"{_hash_token(source_bundle_hash)}-{_hash_token(manifest_hash)}"
        )
        if archive_root.exists():
            raise CalendarPersistenceError(
                f"archive already exists; choose a new source or destination: {archive_root}"
            )
        archive_root.parent.mkdir(parents=True, exist_ok=True)
        archive_root.mkdir()

        durable_bundle = archive_root / source_path.name
        _copy_create_only(source_path, durable_bundle)
        durable_raw_dir = archive_root / source_manifest.parent.name
        durable_raw_dir.mkdir()
        durable_files: list[dict[str, object]] = []
        _copy_create_only(source_manifest, durable_raw_dir / source_manifest.name)
        durable_files.append(_file_record("raw_manifest", durable_raw_dir / source_manifest.name))
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise CalendarPersistenceError("raw manifest contains invalid entry")
            for field, role in (("raw_file", "raw"), ("metadata_file", "metadata")):
                name = entry.get(field)
                if not isinstance(name, str) or not name.strip():
                    raise CalendarPersistenceError(f"raw manifest {field} is missing")
                source_file = _resolve_child(source_manifest.parent, name)
                if source_file is None or not source_file.is_file():
                    raise CalendarPersistenceError(f"raw manifest {field} is not a file")
                durable_file = durable_raw_dir / source_file.name
                _copy_create_only(source_file, durable_file)
                durable_files.append(_file_record(role, durable_file))
        durable_files.insert(0, _file_record("bundle", durable_bundle))

        durable_projection, durable_blockers = _inspect_calendar_raw_custody(
            durable_bundle,
            _load_json(durable_bundle, "durable bundle"),
        )
        if durable_blockers:
            raise CalendarPersistenceError(
                "durable raw custody blockers: " + ", ".join(durable_blockers)
            )
        if file_sha256(durable_bundle) != file_sha256(source_path):
            raise CalendarPersistenceError("durable bundle bytes changed during copy")

        archive_body: dict[str, object] = {
            "schema_version": "official-calendar-candidate-archive.v1",
            "activation_date": activation.isoformat(),
            "candidate_only": True,
            "source_bundle_path": str(source_path),
            "source_bundle_file_hash": file_sha256(source_path),
            "source_bundle_hash": source_bundle_hash,
            "source_raw_manifest_path": str(source_manifest),
            "source_raw_manifest_file_hash": file_sha256(source_manifest),
            "durable_bundle_path": str(durable_bundle),
            "durable_raw_manifest_path": str(durable_raw_dir / source_manifest.name),
            "files": durable_files,
            "source_projection": source_projection,
            "durable_projection": durable_projection,
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "safety": {
                "read_only": True,
                "market_db_written": False,
                "formal_paths_written": False,
                "formal_clock_created": False,
                "formal_oos_allowed": False,
                "production_scheduler_allowed": False,
                "broker_order_allowed": False,
                "historical_backfill_claimed": False,
                "secret_values_emitted": False,
            },
        }
        archive_body["archive_hash"] = payload_hash(archive_body)
        archive_manifest = archive_root / "archive_manifest.json"
        _write_json_create_only(archive_manifest, archive_body)

        report: dict[str, object] = {
            "schema_version": "official-calendar-candidate-persistence-qa.v1",
            "status": "candidate_persisted",
            "activation_date": activation.isoformat(),
            "source_bundle": {
                "path": str(source_path),
                "file_hash": file_sha256(source_path),
                "bundle_hash": source_bundle_hash,
            },
            "archive": {
                "root": str(archive_root),
                "manifest_path": str(archive_manifest),
                "manifest_file_hash": file_sha256(archive_manifest),
                "archive_hash": archive_body["archive_hash"],
                "durable_bundle_path": str(durable_bundle),
                "durable_raw_manifest_path": str(durable_raw_dir / source_manifest.name),
            },
            "raw_source_hashes": [
                {
                    "kind": entry.get("kind"),
                    "key": entry.get("key"),
                    "source_hash": entry.get("source_hash"),
                    "raw_file_hash": entry.get("raw_file_hash"),
                    "metadata_file_hash": entry.get("metadata_file_hash"),
                }
                for entry in entries
                if isinstance(entry, Mapping)
            ],
            "safety": {
                "read_only": True,
                "market_db_written": False,
                "formal_paths_written": False,
                "formal_clock_created": False,
                "formal_oos_allowed": False,
                "production_scheduler_allowed": False,
                "broker_order_allowed": False,
                "historical_backfill_claimed": False,
                "secret_values_emitted": False,
            },
        }
        report["report_hash"] = payload_hash(report)
        _write_json_create_only(qa_output, report)
    except (OSError, ValueError, json.JSONDecodeError, CalendarPersistenceError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": f"{type(error).__name__}: {error}",
                    "candidate_only": True,
                    "formal_clock_created": False,
                    "formal_oos_allowed": False,
                    "market_db_written": False,
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
                "archive_root": report["archive"]["root"],  # type: ignore[index]
                "archive_manifest_path": report["archive"]["manifest_path"],  # type: ignore[index]
                "archive_manifest_file_hash": report["archive"]["manifest_file_hash"],  # type: ignore[index]
                "archive_hash": report["archive"]["archive_hash"],  # type: ignore[index]
                "report_hash": report["report_hash"],
                "read_only": True,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _load_json(path: Path, label: str) -> dict[str, object]:
    if not path.is_file():
        raise CalendarPersistenceError(f"{label} is missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CalendarPersistenceError(f"{label} root must be an object")
    return value


def _verify_bundle(path: Path, bundle: Mapping[str, object]) -> str:
    bundle_hash = bundle.get("bundle_hash")
    body = dict(bundle)
    body.pop("bundle_hash", None)
    if not isinstance(bundle_hash, str) or bundle_hash != payload_hash(body):
        raise CalendarPersistenceError("bundle hash is invalid")
    if bundle.get("candidate_only") is not True:
        raise CalendarPersistenceError("bundle must remain candidate_only")
    if bundle.get("formal_clock_created") is not False:
        raise CalendarPersistenceError("bundle must not create a formal clock")
    return bundle_hash


def _verify_activation_day(bundle: Mapping[str, object], activation: date) -> None:
    days = bundle.get("days")
    if not isinstance(days, list):
        raise CalendarPersistenceError("bundle days are missing")
    row = next(
        (item for item in days if isinstance(item, Mapping) and item.get("date") == activation.isoformat()),
        None,
    )
    if not isinstance(row, Mapping):
        raise CalendarPersistenceError("activation day is missing from bundle")
    if not (
        isinstance(row.get("twse"), Mapping)
        and row["twse"].get("is_trading_day") is True  # type: ignore[index]
        and isinstance(row.get("tpex"), Mapping)
        and row["tpex"].get("is_trading_day") is True  # type: ignore[index]
    ):
        raise CalendarPersistenceError("activation day is not open in both markets")


def _resolve_child(parent: Path, name: object) -> Path | None:
    if not isinstance(name, str) or not name.strip():
        return None
    candidate = (parent / name).resolve()
    try:
        candidate.relative_to(parent.resolve())
    except ValueError:
        return None
    return candidate


def _copy_create_only(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as source_handle, destination.open("xb") as destination_handle:
        for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
            destination_handle.write(chunk)


def _file_record(role: str, path: Path) -> dict[str, object]:
    return {
        "role": role,
        "path": str(path),
        "file_hash": file_sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _write_json_create_only(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with path.open("xb") as handle:
        handle.write(encoded)


def _hash_token(value: str) -> str:
    if not value.startswith("sha256:") or len(value) < 23:
        raise CalendarPersistenceError("hash identity is invalid")
    return value[len("sha256:") : len("sha256:") + 16]


def _parse_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise CalendarPersistenceError("activation-date must be YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise CalendarPersistenceError("activation-date must be YYYY-MM-DD")
    return parsed


if __name__ == "__main__":  # pragma: no cover
    from runtime.console_encoding import configure_utf8_console

    configure_utf8_console()
    raise SystemExit(main())
