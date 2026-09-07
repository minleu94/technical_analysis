"""持續維護 Direct v4 → OOC v5 chain，避免中斷後需要人工續跑。

這個維護器只負責 process custody 與可重入重試：它不建立 raw data、不改寫
SQLite、不直接寫入任何 model pointer，也不放寬 formal promotion gate。每次
重試都呼叫既有 ``continue_ml_direct_v3_refresh_chain.py`` 的
``--resume-after-legacy-chain``，由 Direct builder 以相同 immutable run identity
驗證 checkpoint 後續跑。
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from typing import Any, Iterable, Sequence

try:
    import winreg
except ImportError:  # pragma: no cover - non-Windows runtime
    winreg = None  # type: ignore[assignment]

try:
    import psutil
except ImportError as exc:  # pragma: no cover - runtime dependency contract
    raise RuntimeError("psutil is required for process custody") from exc


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.continue_ml_direct_ooc_after_store as ooc_continuation
from data_module.rule_champion_snapshot_service import (
    load_verified_rule_champion_snapshot_history,
)
from data_module import portfolio_ml_dataset_assembler as dataset_assembler
from data_module.formal_portfolio_ledger import (
    load_formal_portfolio_state_ledger,
)
from runtime.controlled_environment import (
    refresh_controlled_runtime_environment,
    windows_effective_environment_value,
)


_TARGET_SCRIPTS = (
    "continue_ml_direct_v3_refresh_chain.py",
    "build_portfolio_ml_direct_numeric_store.py",
    "continue_ml_direct_ooc_after_store.py",
    "continue_ml_release_after_ooc.py",
)
_DIRECT_SCHEMA_VERSION = "portfolio-ml-direct-numeric.v4"
_RAW_PIT_ROOT_NAME = "ml_pit_year_shards"
_OFFICIAL_EVENT_ROOT_NAME = "official_market_events"
FORMAL_PORTFOLIO_LEDGER_ENV = "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH"
FORMAL_RULE_CHAMPION_HISTORY_ENV = (
    "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH"
)
PIT_SECTOR_MEMBERSHIP_ENV = "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH"
RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY_ENV = (
    "RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY"
)
RULE_CHAMPION_CONTROLLED_STORE_ID_ENV = "RULE_CHAMPION_CONTROLLED_STORE_ID"
_CONTROLLED_RUNTIME_ENVIRONMENT_NAMES = (
    FORMAL_PORTFOLIO_LEDGER_ENV,
    FORMAL_RULE_CHAMPION_HISTORY_ENV,
    PIT_SECTOR_MEMBERSHIP_ENV,
    RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY_ENV,
    RULE_CHAMPION_CONTROLLED_STORE_ID_ENV,
)
_INITIAL_CONTROLLED_RUNTIME_ENVIRONMENT = {
    name: os.environ.get(name)
    for name in _CONTROLLED_RUNTIME_ENVIRONMENT_NAMES
}
_ADOPTED_CONTROLLED_RUNTIME_ENVIRONMENT: dict[str, str] = {}


@dataclass(frozen=True)
class _RefreshCandidate:
    """Validated immutable inputs that justify one new Direct/OOC chain."""

    raw_manifest: Path
    training_as_of: str
    sector_membership: Path | None
    corporate_action_manifest: Path | None
    formal_portfolio_ledger: Path | None
    formal_rule_champion_history: Path | None
    reasons: tuple[str, ...]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-manifest", type=Path, required=True)
    parser.add_argument("--store-output-dir", type=Path, required=True)
    parser.add_argument("--training-output-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--training-as-of", required=True)
    parser.add_argument("--benchmark-entity", required=True)
    parser.add_argument("--sector-membership", type=Path)
    parser.add_argument("--corporate-action-manifest", type=Path)
    parser.add_argument("--formal-portfolio-ledger", type=Path)
    parser.add_argument("--formal-rule-champion-history", type=Path)
    parser.add_argument("--minimum-train-dates", type=int, default=252)
    parser.add_argument("--test-date-count", type=int, default=63)
    parser.add_argument("--purge-trading-days", type=int, default=60)
    parser.add_argument("--embargo-trading-days", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=8_192)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--memory-budget-mb", type=int, default=4_096)
    parser.add_argument(
        "--temporary-storage-budget-bytes",
        "--temporary-peak-bytes-budget",
        dest="temporary_storage_budget_bytes",
        type=int,
    )
    parser.add_argument(
        "--persistent-storage-budget-bytes",
        "--persistent-new-bytes-budget",
        dest="persistent_storage_budget_bytes",
        type=int,
    )
    parser.add_argument("--safety-reserve-bytes", type=int)
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--retry-delay-seconds", type=int, default=30)
    parser.add_argument(
        "--watch-formal-inputs",
        action="store_true",
        help=(
            "keep the supervisor alive after a complete fail-closed chain "
            "and automatically resume when a validated formal input "
            "appears"
        ),
    )
    parser.add_argument(
        "--max-restarts",
        type=int,
        default=0,
        help="0 means retry without an artificial cap; positive values cap retries",
    )
    return parser


def _normalise_command_line(command_line: Iterable[str] | None) -> str:
    return " ".join(command_line or ()).casefold()


def _windows_effective_environment_value(name: str) -> str | None:
    """Compatibility wrapper around the shared Windows registry reader."""

    return windows_effective_environment_value(
        name,
        platform_name=os.name,
        registry=winreg,
    )


def _refresh_controlled_runtime_environment() -> tuple[str, ...]:
    """Adopt changed controlled Windows values into this process only.

    The function never writes a file, emits a value, or relaxes validation.
    It only updates the current process environment so the existing formal
    Rule loader can read a newly available HMAC/store identity.  Values that
    this watcher adopted are also removed when their registry source is
    removed; an unrelated process-supplied value is left untouched.
    """

    return refresh_controlled_runtime_environment(
        environment=os.environ,
        initial_environment=_INITIAL_CONTROLLED_RUNTIME_ENVIRONMENT,
        adopted_environment=_ADOPTED_CONTROLLED_RUNTIME_ENVIRONMENT,
        names=_CONTROLLED_RUNTIME_ENVIRONMENT_NAMES,
        platform_name=os.name,
        registry=winreg,
    )


def _is_matching_maintenance_owner(
    command_line: Iterable[str] | None,
    training_output_dir: Path,
) -> bool:
    """Require the live owner to custody this exact training lineage."""

    normalized = _normalise_command_line(command_line)
    return (
        "maintain_ml_direct_v3_refresh_chain.py" in normalized
        and str(training_output_dir.resolve()).casefold() in normalized
    )


def _target_processes(output_dir: Path) -> list[tuple[int, str]]:
    output_token = str(output_dir.resolve()).casefold()
    found: list[tuple[int, str]] = []
    for process in psutil.process_iter(attrs=("pid", "cmdline")):
        try:
            command_line = _normalise_command_line(process.info.get("cmdline"))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if output_token not in command_line:
            continue
        if not any(script.casefold() in command_line for script in _TARGET_SCRIPTS):
            continue
        found.append((int(process.info["pid"]), command_line))
    return sorted(found)


def _chain_status_path(training_output_dir: Path) -> Path:
    return training_output_dir / "v3_refresh_chain_status.json"


def _read_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    return payload


def _chain_complete(training_output_dir: Path) -> bool:
    payload = _read_object(_chain_status_path(training_output_dir))
    return payload.get("status") == "complete"


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _resolve_child(root: Path, relative_path: object) -> Path | None:
    if not isinstance(relative_path, str) or not relative_path.strip():
        return None
    try:
        resolved_root = root.resolve()
        resolved = (resolved_root / Path(relative_path)).resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    if not resolved.is_relative_to(resolved_root):
        return None
    return resolved


def _current_direct_identity(args: argparse.Namespace) -> dict[str, Any] | None:
    try:
        _manifest_path, manifest = ooc_continuation._latest_manifest(
            args.store_output_dir.resolve()
        )
        store_identity = ooc_continuation._mapping(
            manifest.get("store_identity"),
            field_name="store_identity",
        )
        direct_identity = ooc_continuation._mapping(
            store_identity.get("direct_identity"),
            field_name="store_identity.direct_identity",
        )
        if direct_identity.get("schema_version") != _DIRECT_SCHEMA_VERSION:
            return None
        training_as_of = direct_identity.get("training_as_of")
        if not isinstance(training_as_of, str) or not training_as_of.strip():
            return None
        return dict(direct_identity)
    except (
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        KeyError,
    ):
        return None


def _validated_latest_raw_dataset(
    args: argparse.Namespace,
    *,
    direct_identity: dict[str, Any],
) -> tuple[Path, str] | None:
    """Return a newer pointer-bound all-field raw PIT dataset if available."""

    try:
        publication_root = args.output_root.resolve() / _RAW_PIT_ROOT_NAME
        pointer = ooc_continuation._read_json(
            publication_root / "latest_manifest.json"
        )
        if pointer.get("schema_version") != "ml-pit-year-shards-pointer.v1":
            return None
        pointer_hash = ooc_continuation._required_sha256_text(
            pointer.get("manifest_hash"),
            "raw PIT pointer manifest_hash",
        )
        publication_manifest_path = _resolve_child(
            publication_root,
            pointer.get("manifest_path"),
        )
        if publication_manifest_path is None:
            return None
        publication_manifest = ooc_continuation._read_json(
            publication_manifest_path
        )
        if (
            publication_manifest.get("schema_version")
            != "ml-pit-year-shards.v1"
            or publication_manifest.get("publication_id")
            != pointer.get("publication_id")
            or publication_manifest.get("manifest_hash") != pointer_hash
        ):
            return None
        logical_publication = dict(publication_manifest)
        logical_publication.pop("manifest_hash", None)
        if _canonical_sha256(logical_publication) != pointer_hash:
            return None
        datasets = ooc_continuation._mapping(
            publication_manifest.get("datasets"),
            field_name="raw PIT publication.datasets",
        )
        dataset_meta = ooc_continuation._mapping(
            datasets.get("all_field_enriched"),
            field_name="raw PIT publication.datasets.all_field_enriched",
        )
        dataset_path = _resolve_child(
            publication_manifest_path.parent,
            dataset_meta.get("manifest_path"),
        )
        if dataset_path is None:
            return None
        dataset_manifest = ooc_continuation._read_json(dataset_path)
        dataset_assembler._validate_raw_dataset_manifest(dataset_manifest)
        dataset_hash = ooc_continuation._required_sha256_text(
            dataset_manifest.get("manifest_hash"),
            "raw PIT dataset manifest_hash",
        )
        if (
            dataset_manifest.get("dataset_id") != "all_field_enriched"
            or dataset_meta.get("manifest_hash") != dataset_hash
            or dataset_manifest.get("decision_at")
            != publication_manifest.get("decision_at")
            or dataset_manifest.get("history_start_date")
            != publication_manifest.get("history_start_date")
        ):
            return None
        current_hash = ooc_continuation._required_sha256_text(
            direct_identity.get("raw_manifest_hash"),
            "direct_identity.raw_manifest_hash",
        )
        if dataset_hash == current_hash:
            return None
        current_cutoff = dataset_assembler._available_datetime(
            str(direct_identity["training_as_of"]),
            field_name="direct_identity.training_as_of",
        )
        candidate_cutoff = dataset_assembler._decision_datetime(
            str(dataset_manifest["decision_at"])
        )
        if candidate_cutoff < current_cutoff:
            return None
        return dataset_path, candidate_cutoff.isoformat()
    except (
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        KeyError,
        json.JSONDecodeError,
    ):
        return None


def _validated_latest_corporate_action_manifest(
    args: argparse.Namespace,
    *,
    training_as_of: str,
) -> tuple[Path, str, str] | None:
    """Return the latest pointer-bound formal market-event publication."""

    try:
        publication_root = (
            args.output_root.resolve() / _OFFICIAL_EVENT_ROOT_NAME
        )
        pointer = ooc_continuation._read_json(
            publication_root / "latest_manifest.json"
        )
        if pointer.get("schema_version") != "official-market-event-latest.v1":
            return None
        manifest_path = _resolve_child(
            publication_root,
            pointer.get("manifest_path"),
        )
        if manifest_path is None:
            return None
        manifest = dataset_assembler._read_json(manifest_path)
        if (
            manifest.get("schema_version")
            != "official-market-event-publication.v1"
            or manifest.get("status") != "formal_source_publication"
            or manifest.get("publication_id")
            != pointer.get("publication_id")
        ):
            return None
        manifest_hash = ooc_continuation._required_sha256_text(
            manifest.get("manifest_hash"),
            "official market-event manifest_hash",
        )
        if pointer.get("manifest_hash") != manifest_hash:
            return None
        logical_manifest = dict(manifest)
        logical_manifest.pop("manifest_hash", None)
        if dataset_assembler._sha256_json(logical_manifest) != manifest_hash:
            return None
        manifest_file_hash = ooc_continuation._file_sha256(manifest_path)
        if pointer.get("manifest_file_hash") != manifest_file_hash:
            return None
        canonical_events = ooc_continuation._mapping(
            manifest.get("canonical_events"),
            field_name="official market-event canonical_events",
        )
        canonical_events_hash = ooc_continuation._required_sha256_text(
            canonical_events.get("file_hash"),
            "official market-event canonical_events.file_hash",
        )
        dataset_assembler._load_corporate_action_custody(
            manifest_path,
            training_as_of=dataset_assembler._available_datetime(
                training_as_of,
                field_name="training_as_of",
            ),
        )
        return manifest_path, manifest_file_hash, canonical_events_hash
    except (
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        KeyError,
        json.JSONDecodeError,
    ):
        return None


def _auto_sector_refresh_candidate(
    args: argparse.Namespace,
    *,
    training_as_of: str | None = None,
) -> Path | None:
    """Return a newly deposited, validated sector sidecar if one exists."""

    try:
        direct_identity = _current_direct_identity(args)
        if direct_identity is None:
            return None
        sector_hash = direct_identity.get("sector_membership_file_hash")
        if sector_hash is not None and not ooc_continuation._is_zero_sha256(
            str(sector_hash)
        ):
            return None
        effective_training_as_of = training_as_of or str(
            direct_identity["training_as_of"]
        )
        return ooc_continuation.discover_valid_sector_membership(
            output_root=args.store_output_dir.resolve(),
            training_as_of=effective_training_as_of,
        )
    except (
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        KeyError,
    ):
        return None


def _environment_path(environment_name: str) -> Path | None:
    """Resolve one explicitly configured, user-controlled source path.

    Formal portfolio and Rule Champion artifacts are intentionally not guessed
    from arbitrary output or research directories.  The environment variables
    below are the scheduled-process handoff for an owner-controlled source;
    the downstream builders still perform the complete schema and custody
    validation before any immutable run is started.
    """

    _refresh_controlled_runtime_environment()
    raw_value = os.environ.get(environment_name)
    if raw_value is None or not raw_value.strip():
        return None
    try:
        candidate = Path(raw_value.strip()).expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    return candidate if candidate.is_file() else None


def _prospective_only_manifest_declaration(path: Path) -> str | None:
    """Return a safe discriminator when a path belongs to the PFS lane.

    The legacy maintainer must not pass a prospective wrapper to the historical
    Direct/OOC consumer.  Only a small JSON header is inspected; no command
    line, environment value, HMAC secret, or path is returned by this helper.
    Invalid/legacy files return ``None`` and continue through the existing
    strict validators, which preserves the old fail-closed behaviour.
    """

    try:
        suffix = path.name.casefold()
        if suffix.endswith(".jsonl.gz") or suffix.endswith(".jsonl"):
            opener = gzip.open if suffix.endswith(".jsonl.gz") else open
            with opener(path, "rt", encoding="utf-8") as stream:
                first_line = next(
                    (line for line in stream if line.strip()),
                    "",
                )
            if not first_line:
                return None
            payload = json.loads(first_line)
        elif suffix.endswith(".json") and path.stat().st_size > 2_000_000:
            # PIT JSON envelopes can contain millions of rows.  Their manifest
            # is emitted before ``rows``; bounded marker inspection prevents
            # the legacy watcher from loading the entire sidecar every poll.
            with path.open("rb") as stream:
                prefix = stream.read(256 * 1024)
            text = prefix.decode("utf-8")
            markers = (
                (b'"mode":"prospective_formal_simulation"', "mode=prospective_formal_simulation"),
                (b'"scope":"prospective_only"', "scope=prospective_only"),
            )
            for marker, reason in markers:
                if marker in prefix:
                    return reason
            if b'"schema_version":"prospective-formal-' in prefix:
                return "schema=prospective-formal-*"
            return None
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    candidates: list[Mapping[str, object]] = []
    if isinstance(payload, Mapping):
        candidates.append(payload)
        nested = payload.get("manifest")
        if isinstance(nested, Mapping):
            candidates.append(nested)
    for candidate in candidates:
        schema = candidate.get("schema_version")
        mode = candidate.get("mode")
        scope = candidate.get("scope")
        if mode == "prospective_formal_simulation":
            return "mode=prospective_formal_simulation"
        if scope == "prospective_only":
            return "scope=prospective_only"
        if isinstance(schema, str) and schema.startswith("prospective-formal-"):
            return f"schema={schema}"
    return None


def _legacy_watcher_prospective_guard(args: argparse.Namespace) -> tuple[str, ...]:
    """Detect prospective inputs before the legacy watcher can launch work."""

    configured: list[tuple[str, Path]] = []
    for label, argument_name, environment_name in (
        (
            "formal_portfolio_ledger",
            "formal_portfolio_ledger",
            FORMAL_PORTFOLIO_LEDGER_ENV,
        ),
        (
            "formal_rule_champion_history",
            "formal_rule_champion_history",
            FORMAL_RULE_CHAMPION_HISTORY_ENV,
        ),
        ("pit_sector_membership", "sector_membership", PIT_SECTOR_MEMBERSHIP_ENV),
    ):
        explicit = getattr(args, argument_name, None)
        candidates: list[Path] = []
        if isinstance(explicit, Path):
            candidates.append(explicit)
        environment_path = _environment_path(environment_name)
        if environment_path is not None:
            candidates.append(environment_path)
        seen: set[Path] = set()
        for candidate in candidates:
            resolved = candidate.expanduser().resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            configured.append((label, resolved))
    reasons: list[str] = []
    for label, path in configured:
        if not path.is_file():
            continue
        declaration = _prospective_only_manifest_declaration(path)
        if declaration is not None:
            reasons.append(f"{label}:{declaration}")
    return tuple(sorted(set(reasons)))


def _validated_formal_portfolio_ledger_path(
    path: Path | None,
    *,
    training_as_of: str,
) -> Path | None:
    """Accept only a complete, non-future formal ledger manifest."""

    if path is None:
        return None
    try:
        resolved = path.resolve()
        ledger = load_formal_portfolio_state_ledger(resolved)
        cutoff = dataset_assembler._available_datetime(
            training_as_of,
            field_name="training_as_of",
        ).date()
        if any(
            datetime.fromisoformat(decision_date).date() > cutoff
            for decision_date in ledger.decision_dates
        ):
            return None
        return resolved
    except (
        OSError,
        UnicodeError,
        TypeError,
        ValueError,
        KeyError,
        sqlite3.Error,
    ):
        return None


def _validated_formal_rule_champion_history_path(
    path: Path | None,
    *,
    training_as_of: str,
) -> Path | None:
    """Accept only a HMAC-verified Rule Champion history before cutoff."""

    if path is None:
        return None
    try:
        _refresh_controlled_runtime_environment()
        resolved = path.resolve()
        load_verified_rule_champion_snapshot_history(
            resolved,
            training_as_of=training_as_of,
        )
        return resolved
    except (
        OSError,
        UnicodeError,
        TypeError,
        ValueError,
        KeyError,
    ):
        return None


def _auto_formal_portfolio_ledger_candidate(
    *,
    training_as_of: str,
) -> Path | None:
    return _validated_formal_portfolio_ledger_path(
        _environment_path(FORMAL_PORTFOLIO_LEDGER_ENV),
        training_as_of=training_as_of,
    )


def _auto_formal_rule_champion_history_candidate(
    *,
    training_as_of: str,
) -> Path | None:
    return _validated_formal_rule_champion_history_path(
        _environment_path(FORMAL_RULE_CHAMPION_HISTORY_ENV),
        training_as_of=training_as_of,
    )


def _auto_refresh_candidate(args: argparse.Namespace) -> _RefreshCandidate | None:
    """Detect one atomic refresh from validated formal input publications."""

    _refresh_controlled_runtime_environment()
    direct_identity = _current_direct_identity(args)
    if direct_identity is None:
        return None
    current_training_as_of = str(direct_identity["training_as_of"])
    raw_manifest = args.raw_manifest.resolve()
    training_as_of = current_training_as_of
    reasons: list[str] = []

    raw_candidate = _validated_latest_raw_dataset(
        args,
        direct_identity=direct_identity,
    )
    if raw_candidate is not None:
        raw_manifest, training_as_of = raw_candidate
        reasons.append("new_validated_raw_pit_publication")

    corporate_action_manifest = args.corporate_action_manifest
    latest_corporate = _validated_latest_corporate_action_manifest(
        args,
        training_as_of=training_as_of,
    )
    if latest_corporate is not None:
        latest_path, latest_hash, latest_canonical_hash = latest_corporate
        current_hash = str(
            direct_identity.get(
                "corporate_action_manifest_file_hash",
                "sha256:" + ("0" * 64),
            )
        )
        current_canonical_hash: str | None = None
        if args.corporate_action_manifest is not None:
            try:
                current_manifest = dataset_assembler._read_json(
                    args.corporate_action_manifest.resolve()
                )
                current_canonical = ooc_continuation._mapping(
                    current_manifest.get("canonical_events"),
                    field_name="current official canonical_events",
                )
                current_canonical_hash = (
                    ooc_continuation._required_sha256_text(
                        current_canonical.get("file_hash"),
                        "current official canonical_events.file_hash",
                    )
                )
            except (
                OSError,
                TypeError,
                ValueError,
                RuntimeError,
                KeyError,
                json.JSONDecodeError,
            ):
                current_canonical_hash = None
        publication_changed = (
            latest_canonical_hash != current_canonical_hash
            if current_canonical_hash is not None
            else latest_hash != current_hash
        )
        if publication_changed:
            reasons.append("new_validated_official_market_event_publication")
        if raw_candidate is not None or publication_changed:
            corporate_action_manifest = latest_path
        elif corporate_action_manifest is None:
            corporate_action_manifest = latest_path

    raw_sector_hash = direct_identity.get("sector_membership_file_hash")
    sector_hash = (
        "sha256:" + ("0" * 64)
        if raw_sector_hash is None
        else str(raw_sector_hash)
    )
    sector_membership: Path | None
    if ooc_continuation._is_zero_sha256(sector_hash):
        sector_membership = _auto_sector_refresh_candidate(
            args,
            training_as_of=training_as_of,
        )
        if sector_membership is not None:
            reasons.append("new_validated_pit_sector_sidecar")
    else:
        try:
            sector_membership = (
                ooc_continuation._discover_hash_bound_sector_sidecar(
                    output_root=args.store_output_dir.resolve(),
                    expected_file_hash=sector_hash,
                    training_as_of=training_as_of,
                )
            )
        except (
            OSError,
            TypeError,
            ValueError,
            RuntimeError,
            KeyError,
        ):
            # Never silently drop an already-bound sector sidecar in a newer
            # immutable run; wait for a compatible validated sidecar.
            return None

    explicit_formal_portfolio_ledger = getattr(
        args,
        "formal_portfolio_ledger",
        None,
    )
    if (
        explicit_formal_portfolio_ledger is None
        and (
            direct_identity.get("formal_portfolio_ledger_file_hash") is None
            or ooc_continuation._is_zero_sha256(
                str(direct_identity.get("formal_portfolio_ledger_file_hash"))
            )
        )
    ):
        explicit_formal_portfolio_ledger = (
            _auto_formal_portfolio_ledger_candidate(
                training_as_of=training_as_of,
            )
        )
    explicit_formal_rule_champion_history = getattr(
        args,
        "formal_rule_champion_history",
        None,
    )
    if (
        explicit_formal_rule_champion_history is None
        and (
            direct_identity.get("formal_rule_champion_history_file_hash") is None
            or ooc_continuation._is_zero_sha256(
                str(
                    direct_identity.get(
                        "formal_rule_champion_history_file_hash"
                    )
                )
            )
        )
    ):
        explicit_formal_rule_champion_history = (
            _auto_formal_rule_champion_history_candidate(
                training_as_of=training_as_of,
            )
        )

    formal_portfolio_ledger = _bound_formal_input_candidate(
        direct_identity=direct_identity,
        explicit_path=explicit_formal_portfolio_ledger,
        path_field="formal_portfolio_ledger_path",
        hash_field="formal_portfolio_ledger_file_hash",
        label="formal portfolio ledger",
    )
    formal_rule_champion_history = _bound_formal_input_candidate(
        direct_identity=direct_identity,
        explicit_path=explicit_formal_rule_champion_history,
        path_field="formal_rule_champion_history_path",
        hash_field="formal_rule_champion_history_file_hash",
        label="formal Rule Champion history",
        )

    if formal_portfolio_ledger is not None:
        validated_ledger = _validated_formal_portfolio_ledger_path(
            formal_portfolio_ledger,
            training_as_of=training_as_of,
        )
        if validated_ledger is None:
            return None
        formal_portfolio_ledger = validated_ledger
    if formal_rule_champion_history is not None:
        validated_history = _validated_formal_rule_champion_history_path(
            formal_rule_champion_history,
            training_as_of=training_as_of,
        )
        if validated_history is None:
            return None
        formal_rule_champion_history = validated_history

    formal_reasons: list[str] = []
    for path, hash_field, reason in (
        (
            formal_portfolio_ledger,
            "formal_portfolio_ledger_file_hash",
            "new_validated_formal_portfolio_ledger",
        ),
        (
            formal_rule_champion_history,
            "formal_rule_champion_history_file_hash",
            "new_validated_formal_rule_champion_history",
        ),
    ):
        expected = direct_identity.get(hash_field)
        if path is not None and (
            expected is None
            or ooc_continuation._is_zero_sha256(str(expected))
        ):
            formal_reasons.append(reason)

    # A formal-only refresh is useful only when the three independent formal
    # inputs can travel together.  Waiting here avoids expensive partial
    # Direct/OOC rebuilds when an owner deposits the sources one at a time.
    if formal_reasons and not reasons and not all(
        (
            sector_membership is not None,
            formal_portfolio_ledger is not None,
            formal_rule_champion_history is not None,
        )
    ):
        return None
    reasons.extend(formal_reasons)

    if not reasons:
        return None
    return _RefreshCandidate(
        raw_manifest=raw_manifest,
        training_as_of=training_as_of,
        sector_membership=sector_membership,
        corporate_action_manifest=(
            None
            if corporate_action_manifest is None
            else corporate_action_manifest.resolve()
        ),
        formal_portfolio_ledger=formal_portfolio_ledger,
        formal_rule_champion_history=formal_rule_champion_history,
        reasons=tuple(reasons),
    )


def _bound_formal_input_candidate(
    *,
    direct_identity: dict[str, Any],
    explicit_path: Path | None,
    path_field: str,
    hash_field: str,
    label: str,
) -> Path | None:
    expected_value = direct_identity.get(hash_field)
    if explicit_path is None:
        bound_path = direct_identity.get(path_field)
        if isinstance(bound_path, str) and bound_path.strip():
            explicit_path = Path(bound_path)
        elif expected_value is None or ooc_continuation._is_zero_sha256(
            str(expected_value)
        ):
            return None
        else:
            # A previously bound formal source without its immutable path
            # cannot be reconstructed safely from a research/output folder.
            raise RuntimeError(
                f"{label} path is required to carry its bound formal source"
            )
    candidate = explicit_path.resolve()
    if not candidate.is_file():
        raise RuntimeError(f"{label} file is missing")
    if expected_value is not None and not ooc_continuation._is_zero_sha256(
        str(expected_value)
    ) and ooc_continuation._file_sha256(candidate) != str(expected_value):
        raise RuntimeError(f"{label} file hash does not match bound identity")
    return candidate


def _continuation_command(
    args: argparse.Namespace,
    *,
    sector_membership: Path | None = None,
    raw_manifest: Path | None = None,
    training_as_of: str | None = None,
    corporate_action_manifest: Path | None = None,
    formal_portfolio_ledger: Path | None = None,
    formal_rule_champion_history: Path | None = None,
) -> list[str]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "continue_ml_direct_v3_refresh_chain.py"),
        "--resume-after-legacy-chain",
        "--legacy-direct-process-id",
        "0",
        "--legacy-ooc-helper-process-id",
        "0",
        "--legacy-release-process-id",
        "0",
        "--raw-manifest",
        str((raw_manifest or args.raw_manifest).resolve()),
        "--store-output-dir",
        str(args.store_output_dir.resolve()),
        "--training-output-dir",
        str(args.training_output_dir.resolve()),
        "--output-root",
        str(args.output_root.resolve()),
        "--database",
        str(args.database.resolve()),
        "--training-as-of",
        str(training_as_of or args.training_as_of),
        "--benchmark-entity",
        str(args.benchmark_entity),
        "--minimum-train-dates",
        str(args.minimum_train_dates),
        "--test-date-count",
        str(args.test_date_count),
        "--purge-trading-days",
        str(args.purge_trading_days),
        "--embargo-trading-days",
        str(args.embargo_trading_days),
        "--batch-size",
        str(args.batch_size),
        "--workers",
        str(args.workers),
        "--memory-budget-mb",
        str(args.memory_budget_mb),
        "--poll-seconds",
        str(args.poll_seconds),
    ]
    optional = (
        (
            "--sector-membership",
            args.sector_membership
            if sector_membership is None
            else sector_membership,
        ),
        (
            "--corporate-action-manifest",
            args.corporate_action_manifest
            if corporate_action_manifest is None
                else corporate_action_manifest,
        ),
        (
            "--formal-portfolio-ledger",
            getattr(args, "formal_portfolio_ledger", None)
            if formal_portfolio_ledger is None
            else formal_portfolio_ledger,
        ),
        (
            "--formal-rule-champion-history",
            getattr(args, "formal_rule_champion_history", None)
            if formal_rule_champion_history is None
            else formal_rule_champion_history,
        ),
        (
            "--temporary-storage-budget-bytes",
            getattr(args, "temporary_storage_budget_bytes", None),
        ),
        (
            "--persistent-storage-budget-bytes",
            getattr(args, "persistent_storage_budget_bytes", None),
        ),
        ("--safety-reserve-bytes", getattr(args, "safety_reserve_bytes", None)),
    )
    for flag, value in optional:
        if value is not None:
            command.extend(
                [
                    flag,
                    str(Path(value).resolve())
                    if isinstance(value, Path)
                    else str(value),
                ]
            )
    return command


def _log(log_path: Path, message: str, **fields: object) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "message": message,
        **fields,
    }
    with log_path.open("a", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")


def _start_continuation(command: Sequence[str], log_path: Path) -> subprocess.Popen[Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("a", encoding="utf-8", newline="\n")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = subprocess.Popen(
            list(command),
            cwd=ROOT,
            stdout=handle,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        handle.close()
        return process
    except Exception:
        handle.close()
        raise


def _acquire_instance_lock(training_output_dir: Path) -> tuple[Path, Any] | None:
    lock_path = training_output_dir / ".ml_direct_chain_maintenance.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            handle = lock_path.open("x", encoding="utf-8", newline="\n")
            handle.write(f"{os.getpid()}\n")
            handle.flush()
            return lock_path, handle
        except FileExistsError:
            try:
                owner_pid = int(lock_path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                owner_pid = 0
            if owner_pid and psutil.pid_exists(owner_pid):
                try:
                    owner_command = _normalise_command_line(
                        psutil.Process(owner_pid).cmdline()
                    )
                except psutil.AccessDenied:
                    # A live owner whose command line cannot be inspected is
                    # not safe to classify as stale.  Preserve the lock and
                    # let the next invocation retry custody verification.
                    return None
                except (psutil.NoSuchProcess, OSError):
                    owner_command = ""
                if _is_matching_maintenance_owner(
                    owner_command.split(), training_output_dir
                ):
                    return None
            try:
                lock_path.unlink()
            except FileNotFoundError:
                continue
    return None


def _release_instance_lock(lock: tuple[Path, Any] | None) -> None:
    if lock is None:
        return
    path, handle = lock
    try:
        handle.close()
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.poll_seconds <= 0 or args.retry_delay_seconds < 0:
        raise ValueError("poll/retry intervals must be non-negative and poll > 0")
    if args.max_restarts < 0:
        raise ValueError("max-restarts must be non-negative")
    training_output_dir = args.training_output_dir.resolve()
    log_path = training_output_dir / "logs" / "ml_direct_chain_maintenance.log"
    restart_count = 0
    last_prospective_guard: tuple[str, ...] | None = None
    lock = _acquire_instance_lock(training_output_dir)
    if lock is None:
        return 0
    try:
        while True:
            refreshed_environment = _refresh_controlled_runtime_environment()
            if refreshed_environment:
                _log(
                    log_path,
                    "controlled_environment_refreshed",
                    variables=list(refreshed_environment),
                )
            prospective_guard = _legacy_watcher_prospective_guard(args)
            if prospective_guard:
                if prospective_guard != last_prospective_guard:
                    _log(
                        log_path,
                        "prospective_only_inputs_detected_legacy_watcher_blocked",
                        reasons=list(prospective_guard),
                        capture_lane="prospective_formal_simulation",
                        heavy_rebuild_launch_allowed=False,
                        formal_oos_allowed=False,
                        secret_values_emitted=False,
                    )
                    last_prospective_guard = prospective_guard
                if not args.watch_formal_inputs:
                    return 2
                time.sleep(args.poll_seconds)
                continue
            last_prospective_guard = None
            targets = _target_processes(args.store_output_dir)
            if targets:
                _log(
                    log_path,
                    "target_chain_observed",
                    restart_count=restart_count,
                    process_ids=[pid for pid, _ in targets],
                )
                time.sleep(args.poll_seconds)
                continue
            if _chain_complete(training_output_dir):
                candidate = _auto_refresh_candidate(args)
                if candidate is None:
                    if not args.watch_formal_inputs:
                        _log(
                            log_path,
                            "chain_complete",
                            restart_count=restart_count,
                        )
                        return 0
                    time.sleep(args.poll_seconds)
                    continue
                _log(
                    log_path,
                    "validated_formal_input_detected",
                    restart_count=restart_count,
                    reasons=list(candidate.reasons),
                    raw_manifest_path=str(candidate.raw_manifest),
                    training_as_of=candidate.training_as_of,
                    sector_membership_path=(
                        None
                        if candidate.sector_membership is None
                        else str(candidate.sector_membership)
                    ),
                    corporate_action_manifest=(
                        None
                        if candidate.corporate_action_manifest is None
                        else str(candidate.corporate_action_manifest)
                    ),
                    formal_portfolio_ledger=(
                        None
                        if candidate.formal_portfolio_ledger is None
                        else str(candidate.formal_portfolio_ledger)
                    ),
                    formal_rule_champion_history=(
                        None
                        if candidate.formal_rule_champion_history is None
                        else str(candidate.formal_rule_champion_history)
                    ),
                )
                command = _continuation_command(
                    args,
                    sector_membership=candidate.sector_membership,
                    raw_manifest=candidate.raw_manifest,
                    training_as_of=candidate.training_as_of,
                    corporate_action_manifest=(
                        candidate.corporate_action_manifest
                    ),
                    formal_portfolio_ledger=(
                        candidate.formal_portfolio_ledger
                    ),
                    formal_rule_champion_history=(
                        candidate.formal_rule_champion_history
                    ),
                )
            else:
                command = _continuation_command(args)
            if args.max_restarts and restart_count >= args.max_restarts:
                _log(log_path, "restart_cap_reached", restart_count=restart_count)
                return 2
            restart_count += 1
            _log(
                log_path,
                "starting_checkpoint_recovery",
                restart_count=restart_count,
                command=command,
            )
            process = _start_continuation(command, log_path)
            return_code = process.wait()
            _log(
                log_path,
                "continuation_exited",
                restart_count=restart_count,
                return_code=return_code,
            )
            if _chain_complete(training_output_dir):
                if not args.watch_formal_inputs:
                    return 0
                # A successful refresh must not turn a formal-input watcher
                # into a one-shot process.  Keep its custody lock and return
                # to the polling loop so late owner deposits are still
                # observed without a manual restart.
                _log(
                    log_path,
                    "chain_complete_watching_formal_inputs",
                    restart_count=restart_count,
                )
                time.sleep(args.poll_seconds)
                continue
            if args.retry_delay_seconds:
                time.sleep(args.retry_delay_seconds)
    finally:
        _release_instance_lock(lock)


if __name__ == "__main__":
    raise SystemExit(main())
