"""由三個實際 Formal source artifact 產生 teacher source-row receipt。

既有 assembler 的 ``teacher_input_provenance`` 只保存每日 counters，無法
證明 counters 來自哪一筆 sector、Rule 或 ledger source row。本模組由
assembler 明確呼叫，唯讀重驗三個 source artifact，將與決策日相關的實際
rows 放入 readback receipt，並以 source artifact bytes、schema、semantic
identity、日期 cutoff 與 rows hash 綁定。它不會把 candidate 或手工 JSON
升格成 Formal source，也不會寫回 D 資料庫。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any
from zoneinfo import ZoneInfo


TEACHER_INPUT_PROVENANCE_V2_SCHEMA_VERSION = (
    "allocation-teacher-input-provenance.v2"
)
TEACHER_INPUT_READBACK_V2_SCHEMA_VERSION = (
    "allocation-teacher-input-readback.v2"
)
TEACHER_SOURCE_MANIFEST_V2_SCHEMA_VERSION = (
    "allocation-teacher-source-manifest.v2"
)
TEACHER_SOURCE_PRODUCER_VERSION = "formal-teacher-source-row-producer.v1"
TEACHER_SOURCE_NAMES = (
    "pit_sector_membership",
    "causal_non_cash_portfolio_ledger",
    "formal_rule_champion_snapshot_history",
)
_SHA256_PREFIX = "sha256:"
_TAIPEI = ZoneInfo("Asia/Taipei")


class TeacherSourceProvenanceError(ValueError):
    """實際 teacher source rows 或其 custody 不符合契約。"""


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def payload_hash(value: object) -> str:
    return _SHA256_PREFIX + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1 << 20):
                digest.update(chunk)
    except OSError as exc:
        raise TeacherSourceProvenanceError(
            f"teacher source artifact cannot be read: {path}"
        ) from exc
    return _SHA256_PREFIX + digest.hexdigest()


def sequence_hash(records: Iterable[Mapping[str, object]]) -> str:
    """以串流 canonical rows 計算 hash，避免把完整 source list 另存一份。"""

    digest = hashlib.sha256()
    for record in records:
        digest.update(_canonical_json(dict(record)).encode("utf-8"))
        digest.update(b"\n")
    return _SHA256_PREFIX + digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TeacherSourceProvenanceError(
            f"teacher source JSON cannot be read: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise TeacherSourceProvenanceError(
            f"teacher source JSON must be an object: {path}"
        )
    return value


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise TeacherSourceProvenanceError(f"{field_name} must be ISO datetime")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise TeacherSourceProvenanceError(
            f"{field_name} must be ISO datetime"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TeacherSourceProvenanceError(
            f"{field_name} must include timezone"
        )
    return parsed


def _decision_dates(value: Sequence[str]) -> tuple[str, ...]:
    result = tuple(str(item) for item in value)
    if not result or result != tuple(sorted(set(result))):
        raise TeacherSourceProvenanceError(
            "teacher provenance decision_dates must be sorted and unique"
        )
    for item in result:
        try:
            if date.fromisoformat(item).isoformat() != item:
                raise ValueError
        except ValueError as exc:
            raise TeacherSourceProvenanceError(
                f"invalid teacher decision date: {item}"
            ) from exc
    return result


def _source_paths(source_paths: Mapping[str, Path]) -> dict[str, Path]:
    if set(source_paths) != set(TEACHER_SOURCE_NAMES):
        raise TeacherSourceProvenanceError(
            "teacher source paths must contain exactly the three Formal sources"
        )
    result: dict[str, Path] = {}
    for source_name in TEACHER_SOURCE_NAMES:
        path = Path(source_paths[source_name]).expanduser().resolve()
        if path.is_symlink() or not path.is_file():
            raise TeacherSourceProvenanceError(
                f"teacher source artifact is missing: {source_name}"
            )
        result[source_name] = path
    return result


def _sector_records(path: Path) -> tuple[tuple[dict[str, object], ...], dict[str, object]]:
    # 使用 assembler 既有 canonical sidecar parser；它會驗證 rows hash、
    # canonical hash、row count 與每列 schema，避免另寫一套寬鬆 parser。
    from data_module.portfolio_ml_dataset_assembler import (  # noqa: PLC0415
        _load_sector_membership_sidecar,
    )

    rows, canonical_hash = _load_sector_membership_sidecar(path)
    normalized: list[dict[str, object]] = []
    for row in rows:
        payload = {str(key): value for key, value in row.items()}
        available_at = payload.get("available_at")
        _aware(available_at, field_name="sector row available_at")
        normalized.append(payload)
    return tuple(normalized), {
        "source_schema_version": "pit-sector-membership-sidecar-v1",
        "canonical_manifest_hash": canonical_hash,
        "row_count": len(normalized),
    }


def _rule_records(path: Path) -> tuple[tuple[dict[str, object], ...], dict[str, object]]:
    from data_module.rule_champion_snapshot_service import (  # noqa: PLC0415
        load_verified_rule_champion_snapshot_history,
    )

    history = load_verified_rule_champion_snapshot_history(path)
    records: list[dict[str, object]] = []
    for snapshot in history.snapshots:
        snapshot_manifest = snapshot.to_manifest()
        snapshot_date = _aware(
            snapshot.decision_timestamp,
            field_name="Rule snapshot decision_timestamp",
        ).astimezone(_TAIPEI).date().isoformat()
        rows = snapshot_manifest.get("decision_rows")
        if not isinstance(rows, list):
            raise TeacherSourceProvenanceError(
                "Rule snapshot decision_rows must be an array"
            )
        for row in rows:
            if not isinstance(row, Mapping):
                raise TeacherSourceProvenanceError(
                    "Rule snapshot decision row must be an object"
                )
            records.append(
                {
                    "snapshot_date": snapshot_date,
                    "decision_timestamp": snapshot.decision_timestamp,
                    "snapshot_content_hash": snapshot.content_hash,
                    "decision_row": dict(row),
                }
            )
    records.sort(
        key=lambda item: _rule_record_sort_key(item)
    )
    return tuple(records), {
        "source_schema_version": "rule-champion-snapshot-history.v1",
        "manifest_hash": history.manifest_hash,
        "registered_store_id": history.registered_store_id,
        "snapshot_count": len(history.snapshots),
        "row_count": len(records),
    }


def _ledger_records(path: Path) -> tuple[tuple[dict[str, object], ...], dict[str, object]]:
    from data_module.formal_portfolio_ledger import (  # noqa: PLC0415
        load_formal_portfolio_state_ledger,
    )

    replay = load_formal_portfolio_state_ledger(path)
    manifest = _read_json(path)
    sqlite_name = manifest.get("sqlite_path")
    if not isinstance(sqlite_name, str) or not sqlite_name:
        raise TeacherSourceProvenanceError("ledger sqlite_path is missing")
    sqlite_path = (path.parent / sqlite_name).resolve()
    if path.parent.resolve() not in sqlite_path.parents:
        raise TeacherSourceProvenanceError("ledger sqlite path escapes source root")
    if not sqlite_path.is_file():
        raise TeacherSourceProvenanceError("ledger sqlite artifact is missing")
    connection = sqlite3.connect(
        f"file:{sqlite_path.as_posix()}?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(transitions)")
        }
        required = {
            "decision_date",
            "input_state_json",
            "desired_weights_json",
            "output_state_json",
            "feature_input_hash",
            "buy_turnover_bp",
            "sell_turnover_bp",
            "canonical_turnover_bp",
            "estimated_cost_bp",
            "add_count",
            "reduce_count",
            "transition_hash",
            "chain_hash",
        }
        if not required.issubset(columns):
            raise TeacherSourceProvenanceError(
                "ledger transition source columns are incomplete"
            )
        select_columns = sorted(required | ({"available_at"} & columns))
        cursor = connection.execute(
            "SELECT " + ",".join('"' + value + '"' for value in select_columns)
            + ' FROM transitions ORDER BY "decision_date"'
        )
        records: list[dict[str, object]] = []
        for row in cursor:
            record = {column: row[column] for column in select_columns}
            available_at = record.get("available_at")
            if available_at not in (None, ""):
                _aware(available_at, field_name="ledger row available_at")
            records.append(record)
    finally:
        connection.close()
    return tuple(records), {
        "source_schema_version": "causal-portfolio-ledger.v1",
        "manifest_hash": replay.ledger_manifest_hash,
        "sqlite_file_hash": file_hash(sqlite_path),
        "sqlite_path": str(sqlite_path),
        "row_count": len(records),
        "availability_column_present": "available_at" in columns,
    }


def _records_for_source(
    source_name: str,
    path: Path,
) -> tuple[tuple[dict[str, object], ...], dict[str, object]]:
    if source_name == "pit_sector_membership":
        return _sector_records(path)
    if source_name == "causal_non_cash_portfolio_ledger":
        return _ledger_records(path)
    if source_name == "formal_rule_champion_snapshot_history":
        return _rule_records(path)
    raise TeacherSourceProvenanceError(f"unknown teacher source: {source_name}")


def _record_hash(record: Mapping[str, object]) -> str:
    return payload_hash(dict(record))


def _required_counter(row: Mapping[str, object], field_name: str) -> int:
    value = row.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TeacherSourceProvenanceError(
            f"teacher decision row {field_name} is invalid"
        )
    return value


def _verified_source_row_count(
    rows: Sequence[Mapping[str, object]],
) -> int:
    verified = 0
    for row in rows:
        record = row.get("record")
        if not isinstance(record, Mapping):
            raise TeacherSourceProvenanceError(
                "teacher selected source row must contain a record object"
            )
        if record.get("availability_status") == "verified":
            verified += 1
    return verified


def _rule_record_sort_key(item: Mapping[str, object]) -> tuple[str, str, str]:
    decision_row = item.get("decision_row")
    if not isinstance(decision_row, Mapping):
        raise TeacherSourceProvenanceError(
            "Rule source decision_row must remain an object"
        )
    return (
        str(item.get("snapshot_date")),
        str(decision_row.get("rule_rank")),
        str(decision_row.get("symbol")),
    )


def _selected_rows(
    source_name: str,
    records: Sequence[Mapping[str, object]],
    *,
    decision_date: str,
    cutoff: datetime,
) -> tuple[list[dict[str, object]], str, bool]:
    selected: list[dict[str, object]] = []
    source_complete = False
    for raw in records:
        available: datetime | None = None
        if source_name == "pit_sector_membership":
            effective_from = str(raw.get("effective_from") or "")
            effective_to = raw.get("effective_to")
            if effective_from > decision_date:
                continue
            if effective_to not in (None, "") and str(effective_to) < decision_date:
                continue
            available_text = raw.get("available_at")
            available = _aware(available_text, field_name="sector row available_at")
            source_complete = True
        elif source_name == "formal_rule_champion_snapshot_history":
            if str(raw.get("snapshot_date")) != decision_date:
                continue
            available_text = raw.get("decision_timestamp")
            available = _aware(
                available_text,
                field_name="Rule row decision_timestamp",
            )
            source_complete = True
        else:
            if str(raw.get("decision_date")) != decision_date:
                continue
            available_text = raw.get("available_at")
            if available_text not in (None, ""):
                available = _aware(
                    available_text,
                    field_name="ledger row available_at",
                )
            source_complete = True
        normalized = dict(raw)
        if available is None:
            normalized["availability_status"] = "unproven"
            normalized.pop("available_at", None)
            selected.append(
                {
                    "record_hash": _record_hash(normalized),
                    "available_at": None,
                    "record": normalized,
                }
            )
            continue
        normalized["available_at"] = available.isoformat()
        availability_status = "verified" if available <= cutoff else "late"
        normalized["availability_status"] = availability_status
        selected.append(
            {
                "record_hash": _record_hash(normalized),
                "available_at": available.isoformat(),
                "record": normalized,
            }
        )
    if not selected:
        return [], "missing", source_complete
    statuses: set[str] = set()
    for row in selected:
        record = row.get("record")
        if not isinstance(record, Mapping):
            raise TeacherSourceProvenanceError(
                "teacher selected source row must contain a record object"
            )
        statuses.add(str(record.get("availability_status")))
    if "late" in statuses:
        return selected, "late", source_complete
    if "unproven" in statuses:
        return selected, "unproven", source_complete
    return selected, "verified", source_complete


def _write_create_only(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (_canonical_json(dict(payload)) + "\n").encode("utf-8")
    try:
        with path.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
    except FileExistsError:
        existing = _read_json(path)
        if existing != dict(payload):
            raise TeacherSourceProvenanceError(
                f"teacher provenance output identity collision: {path}"
            )


def _source_manifest_payload(
    *,
    source_name: str,
    source_schema_version: str,
    source_path: Path,
    source_file_hash: str,
    source_identity_hash: str,
    records: Sequence[Mapping[str, object]],
    semantic: Mapping[str, object],
    decision_dates: tuple[str, ...],
) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": TEACHER_SOURCE_MANIFEST_V2_SCHEMA_VERSION,
        "source_name": source_name,
        "source_schema_version": source_schema_version,
        "source_artifact_path": str(source_path),
        "source_artifact_file_sha256": source_file_hash,
        "source_row_count": len(records),
        "source_records_hash": sequence_hash(records),
        "source_identity_hash": source_identity_hash,
        "source_semantic_identity": dict(semantic),
        "decision_dates": list(decision_dates),
        "storage_mode": "read_only",
    }
    return {**body, "manifest_hash": payload_hash(body)}


def build_teacher_input_provenance(
    *,
    source_paths: Mapping[str, Path],
    output_root: Path,
    decision_dates: Sequence[str],
    decision_cutoffs: Mapping[str, datetime | str],
    decision_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """從三個 source artifact 實際讀取 rows 並產生 v2 provenance。"""

    dates = _decision_dates(tuple(decision_dates))
    sources = _source_paths(source_paths)
    cutoffs: dict[str, datetime] = {}
    for decision_date in dates:
        if decision_date not in decision_cutoffs:
            raise TeacherSourceProvenanceError(
                f"teacher cutoff missing: {decision_date}"
            )
        cutoffs[decision_date] = _aware(
            decision_cutoffs[decision_date],
            field_name=f"decision_cutoffs.{decision_date}",
        )
    summary_rows = [dict(row) for row in decision_rows]
    if len(summary_rows) != len(dates):
        raise TeacherSourceProvenanceError(
            "teacher decision rows must cover every decision date"
        )
    if tuple(str(row.get("decision_date")) for row in summary_rows) != dates:
        raise TeacherSourceProvenanceError(
            "teacher decision rows dates must match decision_dates"
        )
    for row in summary_rows:
        for field_name in (
            "candidate_row_count",
            "eligible_candidate_count",
        ):
            value = row.get(field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise TeacherSourceProvenanceError(
                    f"teacher decision row {field_name} is invalid"
                )
        candidate_count = row.get("candidate_row_count")
        eligible_count = row.get("eligible_candidate_count")
        if (
            isinstance(candidate_count, bool)
            or not isinstance(candidate_count, int)
            or isinstance(eligible_count, bool)
            or not isinstance(eligible_count, int)
        ):
            raise TeacherSourceProvenanceError(
                "teacher decision row counters are invalid"
            )
        if eligible_count > candidate_count:
            raise TeacherSourceProvenanceError(
                "teacher decision row eligible count exceeds candidate count"
            )
        if row.get("target_mode") not in {"cash_only", "non_cash"}:
            raise TeacherSourceProvenanceError("teacher decision target_mode is invalid")

    source_storage_identity = {
        "producer_version": TEACHER_SOURCE_PRODUCER_VERSION,
        "source_paths": {
            source_name: str(sources[source_name])
            for source_name in TEACHER_SOURCE_NAMES
        },
        "source_file_hashes": {
            source_name: file_hash(sources[source_name])
            for source_name in TEACHER_SOURCE_NAMES
        },
        "decision_dates": list(dates),
        "decision_cutoffs": {
            decision_date: cutoffs[decision_date].isoformat()
            for decision_date in dates
        },
        "decision_rows": summary_rows,
    }
    storage_key = payload_hash(source_storage_identity)
    root = output_root.expanduser().resolve() / storage_key[7:]
    root.mkdir(parents=True, exist_ok=True)
    source_meta: dict[str, dict[str, object]] = {}
    for source_name in TEACHER_SOURCE_NAMES:
        path = sources[source_name]
        records, semantic = _records_for_source(source_name, path)
        source_file_hash = file_hash(path)
        source_schema_version = str(semantic.pop("source_schema_version"))
        source_records_hash = sequence_hash(records)
        identity = {
            "source_name": source_name,
            "source_schema_version": source_schema_version,
            "source_artifact_path": str(path),
            "source_artifact_file_sha256": source_file_hash,
            "source_row_count": len(records),
            "source_records_hash": source_records_hash,
            "source_semantic_identity": dict(semantic),
        }
        identity_hash = payload_hash(identity)
        manifest = _source_manifest_payload(
            source_name=source_name,
            source_schema_version=source_schema_version,
            source_path=path,
            source_file_hash=source_file_hash,
            source_identity_hash=identity_hash,
            records=records,
            semantic=semantic,
            decision_dates=dates,
        )
        slug = source_name.replace("_", "-")
        manifest_path = root / f"teacher-source-{slug}.manifest.json"
        _write_create_only(manifest_path, manifest)

        receipt_rows: list[dict[str, object]] = []
        for decision_date in dates:
            selected, availability_status, source_complete = _selected_rows(
                source_name,
                records,
                decision_date=decision_date,
                cutoff=cutoffs[decision_date],
            )
            receipt_rows.append(
                {
                    "decision_date": decision_date,
                    "source_row_count": len(selected),
                    "eligible_source_row_count": _verified_source_row_count(
                        selected
                    ),
                    "complete_source_set": bool(
                        source_complete and availability_status == "verified"
                    ),
                    "availability_status": availability_status,
                    "source_rows": selected,
                }
            )
        receipt_body: dict[str, object] = {
            "schema_version": TEACHER_INPUT_READBACK_V2_SCHEMA_VERSION,
            "source_name": source_name,
            "source_schema_version": source_schema_version,
            "source_identity": identity,
            "source_identity_hash": identity_hash,
            "source_manifest_path": str(manifest_path),
            "source_manifest_hash": manifest["manifest_hash"],
            "decision_dates": list(dates),
            "decision_cutoffs": {
                decision_date: cutoffs[decision_date].isoformat()
                for decision_date in dates
            },
            "rows": receipt_rows,
            "rows_hash": payload_hash(receipt_rows),
            "custody": {
                "access_mode": "read_only",
                "query_only": True,
                "write_performed": False,
                "source_rows_rebuilt_from_artifact": True,
            },
        }
        receipt = {**receipt_body, "receipt_hash": payload_hash(receipt_body)}
        receipt_path = root / f"teacher-source-{slug}.readback.json"
        _write_create_only(receipt_path, receipt)
        source_meta[source_name] = {
            "readback_path": str(receipt_path),
            "readback_file_sha256": file_hash(receipt_path),
            "source_manifest_path": str(manifest_path),
            "source_manifest_file_sha256": file_hash(manifest_path),
            "source_artifact_path": str(path),
            "source_artifact_file_sha256": source_file_hash,
            "source_manifest_hash": manifest["manifest_hash"],
            "source_identity_hash": identity_hash,
            "source_schema_version": source_schema_version,
            "source_row_count": len(records),
            "covered_decision_dates": list(dates),
            "read_only": True,
            "available_before_decision": all(
                row["complete_source_set"] is True for row in receipt_rows
            ),
            "receipt_rows": receipt_rows,
        }

    candidate_count = sum(
        _required_counter(row, "candidate_row_count") for row in summary_rows
    )
    eligible_count = sum(
        _required_counter(row, "eligible_candidate_count")
        for row in summary_rows
    )
    return {
        "schema_version": TEACHER_INPUT_PROVENANCE_V2_SCHEMA_VERSION,
        "producer": "data_module.teacher_input_source_producer",
        "producer_version": TEACHER_SOURCE_PRODUCER_VERSION,
        "decision_dates": list(dates),
        "decision_date_count": len(dates),
        "decision_cutoffs": {
            decision_date: cutoffs[decision_date].isoformat()
            for decision_date in dates
        },
        "input_candidate_count": candidate_count,
        "eligible_candidate_count": eligible_count,
        "decision_rows": summary_rows,
        "sources": source_meta,
        "source_rows_are_artifact_rebuilt": True,
        "source_availability_proven": all(
            bool(item["available_before_decision"])
            for item in source_meta.values()
        ),
        "storage_key": storage_key,
        "storage_root": str(root),
    }


def _expected_source_metadata(
    source_name: str,
    path: Path,
) -> tuple[tuple[dict[str, object], ...], dict[str, object]]:
    records, semantic = _records_for_source(source_name, path)
    return records, semantic


def validate_teacher_source_readback(
    *,
    source_name: str,
    source_meta: Mapping[str, object],
    readback: Mapping[str, object],
    manifest: Mapping[str, object],
    decision_dates: Sequence[str],
    decision_cutoffs: Mapping[str, datetime],
) -> dict[str, object]:
    """重讀 source artifact，確認 receipt 的 rows 不是自洽假 JSON。"""

    if source_name not in TEACHER_SOURCE_NAMES:
        raise TeacherSourceProvenanceError("unknown source in teacher receipt")
    source_path_text = source_meta.get("source_artifact_path")
    if not isinstance(source_path_text, str) or not source_path_text:
        identity = readback.get("source_identity")
        source_path_text = (
            identity.get("source_artifact_path")
            if isinstance(identity, Mapping)
            else None
        )
    if not isinstance(source_path_text, str) or not source_path_text:
        raise TeacherSourceProvenanceError("teacher receipt source path is missing")
    source_path = Path(source_path_text).expanduser().resolve()
    actual_file_hash = file_hash(source_path)
    identity = readback.get("source_identity")
    if not isinstance(identity, Mapping):
        raise TeacherSourceProvenanceError("teacher receipt source identity is missing")
    if identity.get("source_artifact_file_sha256") != actual_file_hash:
        raise TeacherSourceProvenanceError(
            f"{source_name} source artifact bytes changed"
        )
    records, semantic = _expected_source_metadata(source_name, source_path)
    expected_schema = str(semantic.pop("source_schema_version"))
    expected_records_hash = sequence_hash(records)
    expected_identity = {
        "source_name": source_name,
        "source_schema_version": expected_schema,
        "source_artifact_path": str(source_path),
        "source_artifact_file_sha256": actual_file_hash,
        "source_row_count": len(records),
        "source_records_hash": expected_records_hash,
        "source_semantic_identity": dict(semantic),
    }
    expected_identity_hash = payload_hash(expected_identity)
    if identity != expected_identity:
        raise TeacherSourceProvenanceError(
            f"{source_name} source identity does not match artifact"
        )
    if readback.get("source_identity_hash") != expected_identity_hash:
        raise TeacherSourceProvenanceError(
            f"{source_name} source identity hash is stale"
        )
    if readback.get("source_manifest_hash") != manifest.get("manifest_hash"):
        raise TeacherSourceProvenanceError(
            f"{source_name} source manifest binding is stale"
        )
    if readback.get("source_schema_version") != expected_schema:
        raise TeacherSourceProvenanceError(
            f"{source_name} source schema changed"
        )
    if manifest.get("source_artifact_file_sha256") != actual_file_hash:
        raise TeacherSourceProvenanceError(
            f"{source_name} source manifest is stale"
        )
    if manifest.get("source_records_hash") != sequence_hash(records):
        raise TeacherSourceProvenanceError(
            f"{source_name} source records changed"
        )
    if manifest.get("source_row_count") != len(records):
        raise TeacherSourceProvenanceError(
            f"{source_name} source row count changed"
        )
    if identity.get("source_records_hash") != manifest.get("source_records_hash"):
        raise TeacherSourceProvenanceError(
            f"{source_name} source records identity mismatch"
        )
    if manifest.get("source_identity_hash") != expected_identity_hash:
        raise TeacherSourceProvenanceError(
            f"{source_name} source manifest identity is stale"
        )
    if manifest.get("source_name") != source_name:
        raise TeacherSourceProvenanceError(
            f"{source_name} source manifest name mismatch"
        )
    if manifest.get("source_schema_version") != expected_schema:
        raise TeacherSourceProvenanceError(
            f"{source_name} source manifest schema mismatch"
        )
    if manifest.get("source_artifact_path") != str(source_path):
        raise TeacherSourceProvenanceError(
            f"{source_name} source manifest path mismatch"
        )
    if manifest.get("source_semantic_identity") != semantic:
        raise TeacherSourceProvenanceError(
            f"{source_name} source semantic identity changed"
        )
    manifest_hash = manifest.get("manifest_hash")
    manifest_body = dict(manifest)
    manifest_body.pop("manifest_hash", None)
    if manifest_hash != payload_hash(manifest_body):
        raise TeacherSourceProvenanceError(
            f"{source_name} source manifest hash is invalid"
        )
    receipt_hash = readback.get("receipt_hash")
    receipt_body = dict(readback)
    receipt_body.pop("receipt_hash", None)
    if receipt_hash != payload_hash(receipt_body):
        raise TeacherSourceProvenanceError(
            f"{source_name} source readback hash is invalid"
        )
    raw_rows = readback.get("rows")
    if not isinstance(raw_rows, list):
        raise TeacherSourceProvenanceError("teacher source receipt rows are invalid")
    if tuple(str(row.get("decision_date")) for row in raw_rows if isinstance(row, Mapping)) != tuple(decision_dates):
        raise TeacherSourceProvenanceError(
            f"{source_name} receipt date coverage is invalid"
        )
    normalized_rows: list[dict[str, object]] = []
    availability_proven = True
    for raw_row, decision_date in zip(raw_rows, decision_dates):
        if not isinstance(raw_row, Mapping):
            raise TeacherSourceProvenanceError("teacher source receipt row is invalid")
        cutoff = decision_cutoffs[decision_date]
        selected, status, source_complete = _selected_rows(
            source_name,
            records,
            decision_date=decision_date,
            cutoff=cutoff,
        )
        if raw_row.get("source_rows") != selected:
            raise TeacherSourceProvenanceError(
                f"{source_name} receipt source rows do not match artifact"
            )
        if raw_row.get("source_row_count") != len(selected):
            raise TeacherSourceProvenanceError(
                f"{source_name} receipt source row count mismatch"
            )
        if raw_row.get("eligible_source_row_count") != _verified_source_row_count(
            selected
        ):
            raise TeacherSourceProvenanceError(
                f"{source_name} receipt eligible source row count mismatch"
            )
        expected_complete = bool(source_complete and status == "verified")
        if raw_row.get("complete_source_set") is not expected_complete:
            raise TeacherSourceProvenanceError(
                f"{source_name} receipt completeness mismatch"
            )
        if raw_row.get("availability_status") != status:
            raise TeacherSourceProvenanceError(
                f"{source_name} receipt availability status mismatch"
            )
        availability_proven = availability_proven and expected_complete
        normalized_rows.append(dict(raw_row))
    if readback.get("rows_hash") != payload_hash(normalized_rows):
        raise TeacherSourceProvenanceError(
            f"{source_name} receipt rows hash mismatch"
        )
    return {
        "source_row_count": len(records),
        "covered_decision_dates": list(decision_dates),
        "availability_proven": availability_proven,
        "source_records_hash": manifest["source_records_hash"],
    }


__all__ = [
    "TEACHER_INPUT_PROVENANCE_V2_SCHEMA_VERSION",
    "TEACHER_INPUT_READBACK_V2_SCHEMA_VERSION",
    "TEACHER_SOURCE_MANIFEST_V2_SCHEMA_VERSION",
    "TEACHER_SOURCE_NAMES",
    "TEACHER_SOURCE_PRODUCER_VERSION",
    "TeacherSourceProvenanceError",
    "build_teacher_input_provenance",
    "file_hash",
    "payload_hash",
    "sequence_hash",
    "validate_teacher_source_readback",
]
