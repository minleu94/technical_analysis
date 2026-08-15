"""Create-only custody manifest for a prospective simulated Portfolio ledger."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from data_module.formal_simulated_portfolio_ledger import (
    SimulatedLedgerSummary,
    summarize_simulated_ledger,
)
from data_module.prospective_formal_clock import (
    ProspectiveFormalClock,
    canonical_json,
    file_sha256,
    load_clock_manifest_for_capture,
    payload_hash,
)


PROSPECTIVE_SIMULATED_LEDGER_MANIFEST_SCHEMA_VERSION = (
    "prospective-formal-simulated-portfolio-ledger-manifest.v1"
)
TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")


class ProspectiveSimulatedLedgerManifestError(ValueError):
    """Prospective ledger manifest custody contract error."""


def build_prospective_simulated_ledger_manifest(
    *,
    clock: ProspectiveFormalClock,
    sqlite_path: Path,
    manifest_path: Path,
    now: datetime,
) -> dict[str, object]:
    """Re-verify a SQLite chain and build a relative-path, create-only manifest."""

    if not isinstance(clock, ProspectiveFormalClock):
        raise ProspectiveSimulatedLedgerManifestError(
            "validated prospective clock is required"
        )
    _validate_now(now)
    manifest_output = manifest_path.expanduser().resolve()
    sqlite = sqlite_path.expanduser().resolve()
    if not manifest_output.parent.exists():
        raise ProspectiveSimulatedLedgerManifestError(
            "ledger manifest output parent must already exist"
        )
    if not sqlite.is_file():
        raise ProspectiveSimulatedLedgerManifestError("ledger sqlite must be an existing file")
    try:
        relative_sqlite = sqlite.relative_to(manifest_output.parent)
    except ValueError as error:
        raise ProspectiveSimulatedLedgerManifestError(
            "sqlite must be a child of the manifest output directory"
        ) from error
    if relative_sqlite == Path(".") or relative_sqlite.is_absolute():
        raise ProspectiveSimulatedLedgerManifestError("sqlite relative path is invalid")
    relative_text = relative_sqlite.as_posix()
    summary = summarize_simulated_ledger(sqlite, clock=clock)
    _validate_summary(summary, now=now, clock=clock)
    identity: dict[str, object] = {
        "schema_version": PROSPECTIVE_SIMULATED_LEDGER_MANIFEST_SCHEMA_VERSION,
        "clock_id": clock.clock_id,
        "clock_manifest_hash": clock.manifest_hash,
        "sqlite_path": relative_text,
        "sqlite_file_hash": summary.sqlite_file_hash,
        "transition_chain_hash": summary.transition_chain_hash,
        "decision_date_count": summary.decision_date_count,
        "non_cash_state_day_count": summary.non_cash_state_day_count,
    }
    body: dict[str, object] = {
        **identity,
        "status": "complete",
        "formal_source_only": True,
        "research_only": False,
        "formal_consumer_compatible": True,
        "promotion_eligible": False,
        "consumer_mode": "prospective_formal_simulation",
        "ledger_manifest_hash": payload_hash(identity),
    }
    return {**body, "manifest_hash": payload_hash(body)}


def publish_prospective_simulated_ledger_manifest(
    output_path: Path,
    manifest: Mapping[str, object],
) -> str:
    """Persist a canonical manifest exactly once and return its file hash."""

    _validate_manifest(manifest)
    output = output_path.expanduser().resolve()
    if not output.parent.exists():
        raise ProspectiveSimulatedLedgerManifestError(
            "ledger manifest output parent must already exist"
        )
    sqlite = (output.parent / str(manifest["sqlite_path"])).resolve()
    if not sqlite.is_relative_to(output.parent) or not sqlite.is_file():
        raise ProspectiveSimulatedLedgerManifestError(
            "ledger manifest sqlite custody path is invalid"
        )
    if file_sha256(sqlite) != manifest["sqlite_file_hash"]:
        raise ProspectiveSimulatedLedgerManifestError(
            "ledger manifest sqlite file hash mismatch"
        )
    try:
        with output.open("xb") as stream:
            stream.write(canonical_json(dict(manifest)).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ProspectiveSimulatedLedgerManifestError(
            "ledger manifest output already exists"
        ) from error
    return file_sha256(output)


def load_clock_for_ledger_manifest(path: Path, *, now: datetime) -> ProspectiveFormalClock:
    """Load an activation-bound clock without changing its immutable manifest."""

    try:
        return load_clock_manifest_for_capture(path, now=now)
    except Exception as error:
        raise ProspectiveSimulatedLedgerManifestError(
            f"prospective clock is invalid: {error}"
        ) from error


def _validate_summary(
    summary: SimulatedLedgerSummary,
    *,
    now: datetime,
    clock: ProspectiveFormalClock,
) -> None:
    if summary.schema_version != "causal-simulated-portfolio-ledger.v1":
        raise ProspectiveSimulatedLedgerManifestError("ledger schema_version is invalid")
    if summary.clock_id != clock.clock_id or summary.clock_manifest_hash != clock.manifest_hash:
        raise ProspectiveSimulatedLedgerManifestError("ledger clock identity mismatch")
    if summary.decision_date_count <= 0 or summary.non_cash_state_day_count <= 0:
        raise ProspectiveSimulatedLedgerManifestError(
            "ledger must contain transitions and a positive non-cash state day count"
        )
    today = now.astimezone(TAIPEI_TIMEZONE).date().isoformat()
    if any(item > today for item in summary.decision_dates):
        raise ProspectiveSimulatedLedgerManifestError(
            "ledger contains a decision date after now"
        )


def _validate_manifest(manifest: Mapping[str, object]) -> None:
    required = {
        "schema_version",
        "status",
        "formal_source_only",
        "research_only",
        "formal_consumer_compatible",
        "promotion_eligible",
        "consumer_mode",
        "clock_id",
        "clock_manifest_hash",
        "sqlite_path",
        "sqlite_file_hash",
        "ledger_manifest_hash",
        "transition_chain_hash",
        "decision_date_count",
        "non_cash_state_day_count",
        "manifest_hash",
    }
    if set(manifest) != required:
        raise ProspectiveSimulatedLedgerManifestError("ledger manifest fields are invalid")
    for field_name, expected in (
        ("schema_version", PROSPECTIVE_SIMULATED_LEDGER_MANIFEST_SCHEMA_VERSION),
        ("status", "complete"),
        ("formal_source_only", True),
        ("research_only", False),
        ("formal_consumer_compatible", True),
        ("promotion_eligible", False),
        ("consumer_mode", "prospective_formal_simulation"),
    ):
        if manifest.get(field_name) is not expected if isinstance(expected, bool) else manifest.get(field_name) != expected:
            raise ProspectiveSimulatedLedgerManifestError(
                f"ledger manifest {field_name} is invalid"
            )
    for field_name in (
        "clock_manifest_hash",
        "sqlite_file_hash",
        "ledger_manifest_hash",
        "transition_chain_hash",
        "manifest_hash",
    ):
        value = manifest.get(field_name)
        if (
            not isinstance(value, str)
            or len(value) != 71
            or not value.startswith("sha256:")
            or any(char not in "0123456789abcdef" for char in value[7:])
        ):
            raise ProspectiveSimulatedLedgerManifestError(
                f"ledger manifest {field_name} must be sha256"
            )
    for field_name in ("decision_date_count", "non_cash_state_day_count"):
        value = manifest.get(field_name)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ProspectiveSimulatedLedgerManifestError(
                f"ledger manifest {field_name} must be positive integer"
            )
    path_value = manifest.get("sqlite_path")
    if not isinstance(path_value, str) or not path_value or Path(path_value).is_absolute() or ".." in Path(path_value).parts:
        raise ProspectiveSimulatedLedgerManifestError(
            "ledger manifest sqlite_path must be a relative child"
        )
    identity = {
        "schema_version": manifest["schema_version"],
        "clock_id": manifest["clock_id"],
        "clock_manifest_hash": manifest["clock_manifest_hash"],
        "sqlite_path": manifest["sqlite_path"],
        "sqlite_file_hash": manifest["sqlite_file_hash"],
        "transition_chain_hash": manifest["transition_chain_hash"],
        "decision_date_count": manifest["decision_date_count"],
        "non_cash_state_day_count": manifest["non_cash_state_day_count"],
    }
    if manifest["ledger_manifest_hash"] != payload_hash(identity):
        raise ProspectiveSimulatedLedgerManifestError("ledger_manifest_hash mismatch")
    body = dict(manifest)
    supplied = body.pop("manifest_hash")
    if supplied != payload_hash(body):
        raise ProspectiveSimulatedLedgerManifestError("manifest_hash mismatch")


def _validate_now(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ProspectiveSimulatedLedgerManifestError("now must include timezone")
