"""Create one immutable, natural-date ML forward caller configuration.

The producer runs at the real Taipei decision boundary and chooses exactly one
already persisted PIT archive.  It asks the existing ML archive consumer to
re-validate every candidate, then writes a date-keyed configuration with
create-only semantics.  A later run may reuse the same bytes, but it can never
replace a date's frozen source with a newer candidate.  The producer writes
configuration and selection receipts only; it does not touch the source DB,
the PIT archive, a release, or a broker.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Protocol, Sequence
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


TAIPEI = ZoneInfo("Asia/Taipei")
TAIPEI_DECISION_TIME = time(8, 30)
FORWARD_DEADLINE_TIME = time(8, 35)
SCHEDULED_WAKE_LOCAL_TIME = "16:15"
TASK_NAME = "baldr-ml-allocation-forward-daily"
CONFIG_SCHEMA_VERSION = "ml-forward-scheduled-config.v1"
STATUS_SCHEMA_VERSION = "ml-forward-config-producer-status.v1"
DEFAULT_CONFIG_ROOT = ROOT / "output" / "v4_ml_forward_scheduler"
DEFAULT_ARCHIVE_ROOT = (
    ROOT / "output" / "formal_daily_publications" / "pit_candidate_archive"
)
DEFAULT_RELEASE_ROOT = ROOT / "output" / "v4_ml_derived_h5_20260907_real_v2"
# This is the immutable release manifest hash for the V2 model that has been
# independently verified for the V4 forward caller.  Keeping the value in the
# producer means a changed/defaulted release path cannot silently turn into a
# newly frozen model during a daily config run.
DEFAULT_RELEASE_MANIFEST_FILE_HASH = (
    "sha256:c306c1ea53ccef112204a8412a605b575e4d107b4503b2b5be5d6d5ee50910ea"
)
SHA256_PREFIX = "sha256:"


class ForwardConfigProducerError(ValueError):
    """The daily frozen-source configuration cannot be created safely."""


class TradingCalendar(Protocol):
    def is_official_trading_day(
        self,
        target_date: date,
        allow_online_probe: bool = True,
    ) -> tuple[bool | None, str]:
        """Return an official open/closed/unknown result."""


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return SHA256_PREFIX + digest.hexdigest()


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ForwardConfigProducerError(f"{field_name} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ForwardConfigProducerError(
            f"{field_name} must be an ISO timestamp"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ForwardConfigProducerError(f"{field_name} must contain a timezone")
    return parsed.astimezone(TAIPEI)


def _path(value: Path | str) -> Path:
    return Path(value).expanduser().resolve()


def _default_data_root() -> Path:
    return _path(
        os.environ.get("DATA_ROOT", r"D:\Min\Python\Project\FA_Data")
    )


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    if not isinstance(value, str) or not value.strip():
        return None
    return _path(value.strip())


def default_output_root() -> Path:
    # Forward shadow artifacts are repository-isolated.  The market database
    # remains the explicit D: source, while this output root is never allowed
    # to drift onto the data drive by an implicit fallback.
    return _env_path("ML_FORWARD_OUTPUT_ROOT") or (
        ROOT / "output" / "v4_ml_daily_derived_shadow_real_v2"
    )


def default_archive_root() -> Path:
    configured = (
        _env_path("ML_FORWARD_ARCHIVE_ROOT")
        or _env_path("FORMAL_DAILY_PIT_PREOPEN_ARCHIVE_ROOT")
    )
    if configured is not None:
        return configured
    publication_root = _env_path("FORMAL_DAILY_PUBLICATION_ROOT")
    if publication_root is not None:
        return publication_root / "pit_candidate_archive"
    return DEFAULT_ARCHIVE_ROOT


def default_calendar_cache_root() -> Path:
    return (
        _env_path("ML_FORWARD_CALENDAR_CACHE_ROOT")
        or _env_path("FORMAL_DAILY_CALENDAR_CACHE_ROOT")
        or ROOT / "output" / "paper_execution_eod_replay" / "calendar_cache"
    )


def default_temporary_closure_path() -> Path:
    return default_calendar_cache_root()


def default_database() -> Path:
    return _env_path("ML_FORWARD_DATABASE") or (
        _default_data_root() / "sqlite" / "twstock.db"
    )


def default_paper_state_db() -> Path:
    return _env_path("ML_FORWARD_PAPER_STATE_DB") or (
        ROOT
        / "output"
        / "paper_execution_eod_replay"
        / "paper_portfolio"
        / "paper_portfolio.sqlite"
    )


def default_release_root() -> Path:
    return _env_path("BALDR_ML_RELEASE_ROOT") or DEFAULT_RELEASE_ROOT


def default_release_manifest_file_hash() -> str:
    """Return the hash-bound release manifest expected by the daily caller."""

    configured = os.environ.get("BALDR_ML_RELEASE_MANIFEST_FILE_HASH")
    if isinstance(configured, str) and configured.strip():
        value = configured.strip().lower()
        if not value.startswith(SHA256_PREFIX) or len(value) != len(SHA256_PREFIX) + 64:
            raise ForwardConfigProducerError(
                "BALDR_ML_RELEASE_MANIFEST_FILE_HASH must be sha256:<64 hex>"
            )
        try:
            int(value[len(SHA256_PREFIX) :], 16)
        except ValueError as error:
            raise ForwardConfigProducerError(
                "BALDR_ML_RELEASE_MANIFEST_FILE_HASH must be sha256:<64 hex>"
            ) from error
        return value
    return DEFAULT_RELEASE_MANIFEST_FILE_HASH


def _validated_release_manifest_hash(value: str) -> str:
    candidate = value.strip().lower()
    if not candidate.startswith(SHA256_PREFIX) or len(candidate) != len(SHA256_PREFIX) + 64:
        raise ForwardConfigProducerError(
            "release_manifest_file_hash must be sha256:<64 hex>"
        )
    try:
        int(candidate[len(SHA256_PREFIX) :], 16)
    except ValueError as error:
        raise ForwardConfigProducerError(
            "release_manifest_file_hash must be sha256:<64 hex>"
        ) from error
    return candidate


def _read_object(path: Path, *, field_name: str) -> dict[str, object]:
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ForwardConfigProducerError(
            f"{field_name} is unreadable or invalid"
        ) from error
    if not isinstance(decoded, dict):
        raise ForwardConfigProducerError(f"{field_name} must be a JSON object")
    return {str(key): value for key, value in decoded.items()}


def _manifest_candidates(archive_root: Path) -> list[Path]:
    root = _path(archive_root)
    if root.name != "pit_candidate_archive" or not root.is_dir():
        raise ForwardConfigProducerError(
            "archive_root must be an existing pit_candidate_archive directory"
        )
    try:
        candidates = list(root.glob("*/*/archive_manifest.json"))
    except OSError as error:
        raise ForwardConfigProducerError(
            "archive_root cannot be enumerated"
        ) from error
    return sorted(path.resolve() for path in candidates if path.is_file())


def _selection_projection(
    manifest_path: Path,
    result: Mapping[str, object],
) -> dict[str, object]:
    fields = (
        "archive_id",
        "archive_manifest_hash",
        "archive_manifest_file_hash",
        "captured_at",
        "available_at",
        "archived_at",
        "effective_from",
        "capture_id",
        "row_count",
        "source_ids",
        "current_code_hash_match",
        "code_hash_compatibility",
        "legacy_code_hash_compatibility_verified",
        "source_custody_verified",
        "rows_rebuilt_from_raw",
        "candidate_only",
        "formal_oos_allowed",
        "promotion_eligible",
        "production_action_allowed",
    )
    code_hash_mode = result.get("code_hash_compatibility")
    current_hash_match = result.get("current_code_hash_match")
    legacy_hash_verified = result.get(
        "legacy_code_hash_compatibility_verified"
    )
    if not (
        (
            code_hash_mode == "current"
            and current_hash_match is True
            and legacy_hash_verified is False
        )
        or (
            code_hash_mode == "audited_legacy"
            and current_hash_match is False
            and legacy_hash_verified is True
        )
    ):
        raise ForwardConfigProducerError(
            "archive consumer code hash compatibility is invalid"
        )
    verified_manifest_hash = result.get("archive_manifest_file_hash")
    if (
        not isinstance(verified_manifest_hash, str)
        or not verified_manifest_hash.startswith(SHA256_PREFIX)
        or len(verified_manifest_hash) != len(SHA256_PREFIX) + 64
    ):
        raise ForwardConfigProducerError(
            "archive consumer did not return a valid manifest file hash"
        )
    projection: dict[str, object] = {
        "manifest_path": str(manifest_path),
        # This is the hash returned by the consumer's final readback.  The
        # caller compares it with the pre-consumer bytes before freezing it;
        # it must never silently hash a replacement file after validation.
        "manifest_file_hash": verified_manifest_hash,
        "consumer_status": result.get("status"),
    }
    for field in fields:
        if field in result:
            projection[field] = result[field]
    return projection


def select_verified_archive(
    *,
    archive_root: Path,
    decision_at: datetime,
    now: datetime,
    allowed_effective_from: set[date] | None = None,
) -> tuple[Path, dict[str, object], list[dict[str, object]]]:
    """Select the newest archive fully verified before this decision clock."""

    requested_decision = _aware(
        decision_at.isoformat(), field_name="decision_at"
    )
    observed = _aware(now.isoformat(), field_name="now")
    if observed < requested_decision:
        raise ForwardConfigProducerError(
            "config producer requires the real Taipei 08:30 clock"
        )
    if requested_decision.time() != TAIPEI_DECISION_TIME:
        raise ForwardConfigProducerError("decision_at must equal Taipei 08:30")
    try:
        from ml_module.pit_archive_consumer import (  # noqa: PLC0415
            consume_pit_candidate_archive,
        )
    except ImportError as error:
        raise ForwardConfigProducerError(
            "ML PIT archive consumer is unavailable"
        ) from error

    verified: list[tuple[date, datetime, str, Path, dict[str, object]]] = []
    attempts: list[dict[str, object]] = []
    for manifest_path in _manifest_candidates(archive_root):
        try:
            manifest = _read_object(
                manifest_path,
                field_name="archive manifest",
            )
            effective_text = manifest.get("effective_from")
            if not isinstance(effective_text, str):
                raise ForwardConfigProducerError(
                    "archive effective_from is missing"
                )
            effective = date.fromisoformat(effective_text)
            if effective > requested_decision.date():
                raise ForwardConfigProducerError(
                    "archive effective_from is after decision date"
                )
            if (
                allowed_effective_from is not None
                and effective not in allowed_effective_from
            ):
                raise ForwardConfigProducerError(
                    "archive effective_from is outside the one-session freshness window"
                )
            # The consumer verifies this exact byte hash and returns the hash
            # from its final TOCTOU readback.  A change during consumption is
            # therefore rejected below instead of becoming a new frozen hash.
            manifest_file_hash = _file_hash(manifest_path)
            result = consume_pit_candidate_archive(
                archive_root=_path(archive_root),
                manifest_path=manifest_path,
                expected_manifest_file_hash=manifest_file_hash,
                decision_at=requested_decision,
                now=observed,
            )
            verified_manifest_hash = result.get("archive_manifest_file_hash")
            if verified_manifest_hash != manifest_file_hash:
                raise ForwardConfigProducerError(
                    "archive manifest changed during consumer verification"
                )
            captured = _aware(
                result.get("captured_at"),
                field_name="archive.captured_at",
            )
            if captured > requested_decision:
                raise ForwardConfigProducerError(
                    "archive capture is after decision clock"
                )
            projection = _selection_projection(manifest_path, result)
            attempts.append({**projection, "selected": False})
            verified.append(
                (
                    effective,
                    captured,
                    str(result.get("archive_id", "")),
                    manifest_path,
                    result,
                )
            )
        except Exception as error:  # noqa: BLE001 - one bad archive cannot hide another
            attempts.append(
                {
                    "manifest_path": str(manifest_path),
                    "manifest_file_hash": (
                        _file_hash(manifest_path)
                        if manifest_path.is_file()
                        else None
                    ),
                    "selected": False,
                    "status": "rejected",
                    "reason": f"{type(error).__name__}:{str(error).splitlines()[0][:220]}",
                }
            )
    if not verified:
        raise ForwardConfigProducerError(
            "no verified PIT archive was persisted before Taipei 08:30"
        )
    selected_effective, selected_captured, selected_id, selected_path, selected = max(
        verified,
        key=lambda item: (item[0], item[1], item[2]),
    )
    del selected_effective, selected_captured, selected_id
    selected_projection = _selection_projection(selected_path, selected)
    selected_projection["selected"] = True
    for attempt in attempts:
        if attempt.get("manifest_path") == str(selected_path):
            attempt["selected"] = True
    return selected_path, selected_projection, attempts


def _canonical_json(payload: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _create_only(path: Path, raw: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        try:
            existing = path.read_bytes()
        except OSError as error:
            raise ForwardConfigProducerError(
                "existing daily config cannot be read"
            ) from error
        if existing != raw:
            raise ForwardConfigProducerError(
                "daily config already exists with different frozen source"
            )
        return "reused_existing"
    return "created"


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _write_selection_status(
    *,
    config_root: Path,
    payload: Mapping[str, object],
) -> dict[str, str]:
    root = _path(config_root)
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    receipt = root / "selection_receipts" / f"{stamp}-{os.getpid()}.json"
    latest = root / "latest_selection.json"
    record = dict(payload)
    record["receipt_path"] = str(receipt)
    record["latest_selection_path"] = str(latest)
    raw = _canonical_json(record)
    _create_only(receipt, raw)
    _atomic_write(latest, raw)
    return {
        "receipt_path": str(receipt),
        "latest_selection_path": str(latest),
    }


def prepare_daily_config(
    *,
    config_root: Path,
    archive_root: Path,
    decision_at: datetime,
    now: datetime,
    database: Path,
    paper_state_db: Path,
    output_root: Path,
    release_root: Path,
    release_manifest_file_hash: str | None = None,
    calendar: TradingCalendar | None = None,
    calendar_cache_path: Path | None = None,
    temporary_closure_path: Path | None = None,
) -> dict[str, object]:
    """Create or reuse the exact config for ``decision_at.date()``."""

    decision = _aware(decision_at.isoformat(), field_name="decision_at")
    observed = _aware(now.isoformat(), field_name="now")
    if decision.time() != TAIPEI_DECISION_TIME:
        raise ForwardConfigProducerError("decision_at must equal Taipei 08:30")
    deadline = datetime.combine(
        decision.date(),
        FORWARD_DEADLINE_TIME,
        tzinfo=TAIPEI,
    )
    try:
        from data_module.official_trading_calendar import (  # noqa: PLC0415
            OfficialTradingCalendar,
        )

        calendar_service: TradingCalendar = calendar or OfficialTradingCalendar(
            db_path=_path(database),
            calendar_cache_path=_path(calendar_cache_path or default_calendar_cache_root()),
            temporary_closure_path=_path(
                temporary_closure_path or default_temporary_closure_path()
            ),
        )
        is_trading_day, calendar_reason = calendar_service.is_official_trading_day(
            decision.date(),
            allow_online_probe=False,
        )
    except (OSError, TypeError, ValueError) as error:
        raise ForwardConfigProducerError(
            f"official calendar validation failed:{type(error).__name__}"
        ) from error
    calendar_evidence: dict[str, object] = {
        "decision_date": decision.date().isoformat(),
        "is_trading_day": is_trading_day,
        "reason_code": calendar_reason,
        "source": "OfficialTradingCalendar",
        "cache_path": str(
            _path(calendar_cache_path or default_calendar_cache_root())
        ),
        "temporary_closure_path": str(
            _path(temporary_closure_path or default_temporary_closure_path())
        ),
    }
    evidence_for = getattr(calendar_service, "evidence_for", None)
    if callable(evidence_for):
        try:
            current_evidence = evidence_for(decision.date())
        except Exception:  # noqa: BLE001 - status remains governed by calendar result
            current_evidence = None
        if isinstance(current_evidence, Mapping):
            calendar_evidence["official_evidence"] = dict(current_evidence)
    if is_trading_day is False:
        nontrading_payload: dict[str, object] = {
            "schema_version": STATUS_SCHEMA_VERSION,
            "task": TASK_NAME,
            "producer": "scripts.scheduled.prepare_ml_allocation_forward_config",
            "observed_at": observed.astimezone(timezone.utc).isoformat(),
            "decision_at": decision.isoformat(),
            "run_date": decision.date().isoformat(),
            "status": "skipped_non_trading_day",
            "calendar": calendar_evidence,
            "create_only": True,
            "candidate_only": True,
            "formal_oos_allowed": False,
            "forward_credit_granted": False,
            "production_action_allowed": False,
            "broker_order_allowed": False,
        }
        nontrading_payload.update(
            _write_selection_status(
                config_root=config_root,
                payload=nontrading_payload,
            )
        )
        return nontrading_payload
    if is_trading_day is not True:
        raise ForwardConfigProducerError(
            f"official calendar is unknown:{calendar_reason}"
        )

    # The archive may be captured on the current date before 08:30 or on the
    # immediately preceding official trading session.  This prevents a stale
    # 9/8 archive from silently serving a 9/10 decision when 9/9 was a trading
    # day; weekends and holidays are resolved by the official calendar, not a
    # weekday convention.
    previous_session: date | None = None
    for offset in range(1, 32):
        candidate_date = date.fromordinal(decision.date().toordinal() - offset)
        previous_is_trading, previous_reason = calendar_service.is_official_trading_day(
            candidate_date,
            allow_online_probe=False,
        )
        if previous_is_trading is True:
            previous_session = candidate_date
            calendar_evidence["previous_session"] = candidate_date.isoformat()
            calendar_evidence["previous_session_reason"] = previous_reason
            if callable(evidence_for):
                try:
                    previous_evidence = evidence_for(candidate_date)
                except Exception:  # noqa: BLE001
                    previous_evidence = None
                if isinstance(previous_evidence, Mapping):
                    calendar_evidence["previous_session_evidence"] = dict(
                        previous_evidence
                    )
            break
        if previous_is_trading is None:
            raise ForwardConfigProducerError(
                f"official calendar unknown for previous session:{candidate_date.isoformat()}"
            )
    if previous_session is None:
        raise ForwardConfigProducerError(
            "previous official trading session was not found within 31 days"
        )

    manifest_path, selected, attempts = select_verified_archive(
        archive_root=archive_root,
        decision_at=decision,
        now=observed,
        allowed_effective_from={decision.date(), previous_session},
    )
    config_payload: dict[str, object] = {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "task_name": TASK_NAME,
        "decision_timezone": "Asia/Taipei",
        "decision_time": "08:30",
        "scheduled_wake_local": SCHEDULED_WAKE_LOCAL_TIME,
        "run_date": decision.date().isoformat(),
        "database": str(_path(database)),
        "paper_state_db": str(_path(paper_state_db)),
        "output_root": str(_path(output_root)),
        "release_root": str(_path(release_root)),
        "release_manifest_file_hash": _validated_release_manifest_hash(
            release_manifest_file_hash or default_release_manifest_file_hash()
        ),
        "natural_forward_deadline_at": deadline.isoformat(),
        "source": {
            "kind": "archive",
            "root": str(_path(archive_root)),
            "manifest": str(manifest_path),
            "manifest_file_hash": selected["manifest_file_hash"],
        },
    }
    raw = _canonical_json(config_payload)
    config_path = _path(config_root) / "configs" / f"{decision.date().isoformat()}.json"
    write_state = _create_only(config_path, raw)
    config_file_hash = SHA256_PREFIX + hashlib.sha256(raw).hexdigest()
    status: dict[str, object] = {
        "schema_version": STATUS_SCHEMA_VERSION,
        "task": TASK_NAME,
        "producer": "scripts.scheduled.prepare_ml_allocation_forward_config",
        "observed_at": observed.astimezone(timezone.utc).isoformat(),
        "decision_at": decision.isoformat(),
        "run_date": decision.date().isoformat(),
        "status": "created" if write_state == "created" else "reused_existing",
        "config_path": str(config_path),
        "config_file_hash": config_file_hash,
        "source_kind": "archive",
        "release_root": str(_path(release_root)),
        "release_manifest_file_hash": config_payload["release_manifest_file_hash"],
        "calendar": calendar_evidence,
        "selected_archive": selected,
        "archive_candidates": attempts,
        "selection_reason": (
            "newest fully machine-verified immutable archive whose capture and "
            "persistence were available no later than Taipei 08:30"
        ),
        "create_only": True,
        "candidate_only": True,
        "formal_oos_allowed": False,
        "forward_credit_granted": False,
        "production_action_allowed": False,
        "broker_order_allowed": False,
        "writes_source_database": False,
        "writes_market_database": False,
        "training_started": False,
        "promotion_eligible": False,
    }
    status.update(_write_selection_status(config_root=config_root, payload=status))
    return status


def build_parser() -> Any:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-root", type=Path, default=DEFAULT_CONFIG_ROOT)
    parser.add_argument("--archive-root", type=Path, default=default_archive_root())
    parser.add_argument("--database", type=Path, default=default_database())
    parser.add_argument("--paper-state-db", type=Path, default=default_paper_state_db())
    parser.add_argument("--output-root", type=Path, default=default_output_root())
    parser.add_argument("--release-root", type=Path, default=default_release_root())
    parser.add_argument(
        "--release-manifest-file-hash",
        default=default_release_manifest_file_hash(),
        help="凍結 release_manifest.json 的 sha256；V2 預設值不可省略",
    )
    parser.add_argument(
        "--calendar-cache-path",
        type=Path,
        default=default_calendar_cache_root(),
        help="已驗證官方 TWSE 年度 calendar cache；缺少/過期時 fail closed",
    )
    parser.add_argument(
        "--temporary-closure-path",
        type=Path,
        default=default_temporary_closure_path(),
        help="已驗證官方臨時休市 cache；缺少時不推定臨時休市",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = datetime.now(TAIPEI)
    decision_at = datetime.combine(now.date(), TAIPEI_DECISION_TIME, tzinfo=TAIPEI)
    if now < decision_at:
        payload: dict[str, object] = {
            "schema_version": STATUS_SCHEMA_VERSION,
            "task": TASK_NAME,
            "status": "waiting_for_taipei_cutoff",
            "observed_at": now.isoformat(),
            "decision_at": decision_at.isoformat(),
            "blockers": ["taipei_08:30_decision_clock_not_reached"],
            "create_only": True,
            "forward_credit_granted": False,
            "production_action_allowed": False,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    try:
        payload = prepare_daily_config(
            config_root=args.config_root,
            archive_root=args.archive_root,
            decision_at=decision_at,
            now=now,
            database=args.database,
            paper_state_db=args.paper_state_db,
            output_root=args.output_root,
            release_root=args.release_root,
            release_manifest_file_hash=args.release_manifest_file_hash,
            calendar_cache_path=args.calendar_cache_path,
            temporary_closure_path=args.temporary_closure_path,
        )
    except (OSError, TypeError, ValueError) as error:
        payload = {
            "schema_version": STATUS_SCHEMA_VERSION,
            "task": TASK_NAME,
            "status": "blocked",
            "observed_at": now.isoformat(),
            "decision_at": decision_at.isoformat(),
            "blockers": [
                f"forward_config_producer:{type(error).__name__}:{str(error).splitlines()[0][:220]}"
            ],
            "create_only": True,
            "forward_credit_granted": False,
            "production_action_allowed": False,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
