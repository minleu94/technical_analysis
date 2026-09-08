"""唯讀診斷 Portfolio ML teacher target 退化的資料原因。

這個模組直接讀取已完成的 Direct numeric manifest 與年度 artifacts，使用
chunked memmap、唯讀 SQLite 查詢及 manifest 宣告的 hash；不重建 PIT/OOC、
不改寫來源，也不把 prospective candidate 當成歷史 formal input。診斷的
目的，是把「策略在有候選時選擇 cash」與「資料缺件使 teacher 沒有可選候選」
分開，避免看到全 cash target 就誤稱模型已學會 cash-only 策略。
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence

import numpy as np

from data_module import portfolio_ml_out_of_core_store as store_module
from data_module.ml_direct_shared_block_resolver import (
    resolve_direct_numeric_artifact,
)
from data_module.portfolio_ml_out_of_core_store import (
    LABEL_FIELDS,
    TARGET_FIELDS,
)


TARGET_DIAGNOSTIC_SCHEMA_VERSION = (
    "portfolio-ml-target-degeneracy-diagnostic.v1"
)
ALLOCATION_TEACHER_GATE_SCHEMA_VERSION = (
    "allocation-teacher-eligibility-gate.v1"
)
TEACHER_INPUT_PROVENANCE_SCHEMA_VERSION = (
    "allocation-teacher-input-provenance.v1"
)
DIRECT_STORE_SCHEMA_VERSION = store_module.STORE_SCHEMA_VERSION
YEAR_SCHEMA_VERSION = "portfolio-ml-ooc-year.v3"
_SHA256_PREFIX = "sha256:"
_DEFAULT_CHUNK_ROWS = 65_536
_TEACHER_NUMERIC_TARGET_FIELDS = TARGET_FIELDS[:4] + (TARGET_FIELDS[5],)
_REQUIRED_TEACHER_BLOCKERS = frozenset(
    {
        "pit_sector_membership_missing_teacher_new_positions_disabled",
        "portfolio_ledger_missing_cash_only_fallback_turnover_and_cooldown_not_learned",
        "formal_rule_champion_snapshot_history_missing_formal_replay_blocked",
    }
)
_REQUIRED_TEACHER_DIAGNOSTIC_FIELDS = (
    "decision_date_count",
    "label_row_count",
    "input_candidate_count",
    "eligible_candidate_count",
    "unknown_sector_candidate_count",
    "teacher_incomplete_decision_count",
    "non_cash_target_decision_count",
    "cash_only_target_decision_count",
)
_REQUIRED_TEACHER_INPUT_SOURCES = (
    "pit_sector_membership",
    "causal_non_cash_portfolio_ledger",
    "formal_rule_champion_snapshot_history",
)
_REPLAY_FIELDS = (
    "sector_id",
    "price_event_at",
    "price_available_at",
    "open_int",
    "close_int",
    "volume_shares",
    "median_volume_20d_shares",
    "rule_score_bp",
)


class TargetDiagnosticError(ValueError):
    """Target diagnostic custody or schema validation failed."""


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_hash(payload: object) -> str:
    return _SHA256_PREFIX + hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TargetDiagnosticError(f"JSON manifest cannot be read: {path}") from exc
    if not isinstance(payload, dict):
        raise TargetDiagnosticError(f"JSON object required: {path}")
    return payload


def _required_int(value: object, *, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise TargetDiagnosticError(
            f"{field_name} must be an integer >= {minimum}"
        )
    return value


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TargetDiagnosticError(f"{field_name} must be non-empty text")
    return value


def _aware_datetime(value: object, *, field_name: str) -> datetime:
    text = _required_text(value, field_name=field_name)
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise TargetDiagnosticError(f"{field_name} is not ISO datetime") from exc
    if parsed.tzinfo is None:
        raise TargetDiagnosticError(f"{field_name} must include timezone")
    return parsed


def _manifest_hash_matches(payload: Mapping[str, Any], *, field_name: str) -> str:
    supplied = _required_text(payload.get(field_name), field_name=field_name)
    if not supplied.startswith(_SHA256_PREFIX) or len(supplied) != 71:
        raise TargetDiagnosticError(f"{field_name} must be a sha256 digest")
    body = dict(payload)
    body.pop(field_name, None)
    if _payload_hash(body) != supplied:
        raise TargetDiagnosticError(f"{field_name} mismatch")
    return supplied


def _artifact_entries(year_manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw = year_manifest.get("artifacts")
    if not isinstance(raw, (list, tuple)):
        raise TargetDiagnosticError("year artifacts must be an array")
    result: dict[str, Mapping[str, Any]] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            raise TargetDiagnosticError("year artifact must be an object")
        artifact_id = item.get("artifact_id")
        if artifact_id is None and isinstance(item.get("path"), str):
            artifact_id = Path(str(item["path"])).name
        if not isinstance(artifact_id, str) or artifact_id in result:
            raise TargetDiagnosticError("year artifact id is invalid or duplicated")
        result[artifact_id] = item
    expected = {
        "targets.i32",
        "labels.i32",
        "labels.masks.u8",
        "rows.sqlite",
        "replay_source.sqlite",
    }
    missing = sorted(expected - set(result))
    if missing:
        raise TargetDiagnosticError(
            "year artifacts missing diagnostic inputs: " + ",".join(missing)
        )
    return result


def _validated_teacher_diagnostics(
    value: object,
    *,
    field_name: str,
) -> dict[str, int] | None:
    """驗證新 manifest 的 provenance counters；舊 manifest 可省略。"""

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TargetDiagnosticError(f"{field_name} must be an object")
    result: dict[str, int] = {}
    for raw_key, raw_value in value.items():
        key = _required_text(raw_key, field_name=f"{field_name}.key")
        result[key] = _required_int(
            raw_value,
            field_name=f"{field_name}.{key}",
        )
    return dict(sorted(result.items()))


def _required_sha256(value: object, *, field_name: str) -> str:
    text = _required_text(value, field_name=field_name)
    if (
        len(text) != 71
        or not text.startswith(_SHA256_PREFIX)
        or any(character not in "0123456789abcdef" for character in text[7:])
    ):
        raise TargetDiagnosticError(f"{field_name} must be a sha256 digest")
    return text


def _validated_date_sequence(
    value: object,
    *,
    field_name: str,
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise TargetDiagnosticError(f"{field_name} must be an array")
    result: list[str] = []
    for position, raw_date in enumerate(value):
        text = _required_text(
            raw_date,
            field_name=f"{field_name}[{position}]",
        )
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            # Decision-date provenance deliberately uses a date-only key so
            # that a partial day cannot masquerade as a complete decision.
            try:
                parsed = datetime.fromisoformat(text + "T00:00:00")
            except ValueError as exc:
                raise TargetDiagnosticError(
                    f"{field_name}[{position}] must be an ISO date"
                ) from exc
        if parsed.time() != datetime.min.time() and "T" in text:
            raise TargetDiagnosticError(
                f"{field_name}[{position}] must be date-only"
            )
        normalized = parsed.date().isoformat()
        if normalized != text:
            raise TargetDiagnosticError(
                f"{field_name}[{position}] must be canonical YYYY-MM-DD"
            )
        result.append(normalized)
    if tuple(result) != tuple(sorted(set(result))):
        raise TargetDiagnosticError(
            f"{field_name} must contain unique sorted dates"
        )
    return tuple(result)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1 << 20):
                digest.update(chunk)
    except OSError as exc:
        raise TargetDiagnosticError(
            f"teacher provenance readback cannot be read: {path}"
        ) from exc
    return _SHA256_PREFIX + digest.hexdigest()


def _read_json_object(path: Path, *, field_name: str) -> dict[str, Any]:
    """讀取 provenance receipt/manifest；內容必須是可解析 JSON object。"""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TargetDiagnosticError(f"{field_name} JSON cannot be read") from exc
    if not isinstance(payload, dict):
        raise TargetDiagnosticError(f"{field_name} must be a JSON object")
    return payload


def _validated_decision_cutoffs(
    value: object,
    *,
    decision_dates: tuple[str, ...],
    field_name: str,
) -> dict[str, datetime]:
    if not isinstance(value, Mapping):
        raise TargetDiagnosticError(f"{field_name} must be an object")
    if set(value) != set(decision_dates):
        raise TargetDiagnosticError(
            f"{field_name} must bind exactly to decision_dates"
        )
    result: dict[str, datetime] = {}
    for decision_date in decision_dates:
        result[decision_date] = _aware_datetime(
            value.get(decision_date),
            field_name=f"{field_name}.{decision_date}",
        )
    return result


def _validated_source_receipt_rows(
    value: object,
    *,
    source_name: str,
    decision_dates: tuple[str, ...],
    decision_cutoffs: Mapping[str, datetime],
    field_name: str,
) -> tuple[list[dict[str, Any]], int, int]:
    """以 receipt 內逐筆 row 重算日期、數量與可得時間。

    外層 ``available_before_decision`` 等布林值是宣告，不能作為證據；
    這裡只接受每一列的實際 ``available_at`` 與候選計數，並逐一和 cutoff
    比較，避免晚到資料搭配正確 hash 偽裝成盤前來源。
    """

    if not isinstance(value, (list, tuple)):
        raise TargetDiagnosticError(f"{field_name} must be an array")
    if len(value) != len(decision_dates):
        raise TargetDiagnosticError(
            f"{field_name} must contain one row per decision date"
        )
    rows: list[dict[str, Any]] = []
    row_dates: list[str] = []
    total_candidates = 0
    total_eligible = 0
    for position, raw_row in enumerate(value):
        if not isinstance(raw_row, Mapping):
            raise TargetDiagnosticError(
                f"{field_name}[{position}] must be an object"
            )
        decision_date = _required_text(
            raw_row.get("decision_date"),
            field_name=f"{field_name}[{position}].decision_date",
        )
        if decision_date not in decision_cutoffs:
            raise TargetDiagnosticError(
                f"{field_name}[{position}] has an undeclared decision date"
            )
        available_at = _aware_datetime(
            raw_row.get("available_at"),
            field_name=f"{field_name}[{position}].available_at",
        )
        if available_at > decision_cutoffs[decision_date]:
            raise TargetDiagnosticError(
                f"{field_name}[{position}] source became available after decision"
            )
        candidate_count = _required_int(
            raw_row.get("candidate_row_count"),
            field_name=f"{field_name}[{position}].candidate_row_count",
        )
        eligible_count = _required_int(
            raw_row.get("eligible_candidate_count"),
            field_name=f"{field_name}[{position}].eligible_candidate_count",
        )
        if eligible_count > candidate_count:
            raise TargetDiagnosticError(
                f"{field_name}[{position}] eligible count exceeds candidates"
            )
        if raw_row.get("complete_candidate_set") is not True:
            raise TargetDiagnosticError(
                f"{field_name}[{position}] candidate set is not complete"
            )
        target_mode = raw_row.get("target_mode")
        if target_mode not in {"cash_only", "non_cash"}:
            raise TargetDiagnosticError(
                f"{field_name}[{position}].target_mode is invalid"
            )
        row_dates.append(decision_date)
        total_candidates += candidate_count
        total_eligible += eligible_count
        rows.append(
            {
                "decision_date": decision_date,
                "available_at": available_at.isoformat(),
                "candidate_row_count": candidate_count,
                "eligible_candidate_count": eligible_count,
                "complete_candidate_set": True,
                "target_mode": target_mode,
            }
        )
    if tuple(row_dates) != decision_dates:
        raise TargetDiagnosticError(
            f"{field_name} dates must be unique, sorted, and match decision_dates"
        )
    return rows, total_candidates, total_eligible


def _validated_teacher_input_provenance_v2(
    value: Mapping[str, Any],
    *,
    field_name: str,
) -> dict[str, Any]:
    """重讀實體 sector／ledger／Rule rows 的 teacher provenance v2。"""

    from data_module.teacher_input_source_producer import (  # noqa: PLC0415
        TEACHER_INPUT_PROVENANCE_V2_SCHEMA_VERSION,
        TEACHER_SOURCE_NAMES,
        TeacherSourceProvenanceError,
        validate_teacher_source_readback,
    )

    if value.get("schema_version") != TEACHER_INPUT_PROVENANCE_V2_SCHEMA_VERSION:
        raise TargetDiagnosticError(
            f"{field_name}.schema_version is unsupported"
        )
    if value.get("producer") != "data_module.teacher_input_source_producer":
        raise TargetDiagnosticError(f"{field_name}.producer is unsupported")
    if value.get("producer_version") != "formal-teacher-source-row-producer.v1":
        raise TargetDiagnosticError(
            f"{field_name}.producer_version is unsupported"
        )
    if value.get("source_rows_are_artifact_rebuilt") is not True:
        raise TargetDiagnosticError(
            f"{field_name}.source_rows_are_artifact_rebuilt must be true"
        )

    decision_dates = _validated_date_sequence(
        value.get("decision_dates"),
        field_name=f"{field_name}.decision_dates",
    )
    decision_date_count = _required_int(
        value.get("decision_date_count"),
        field_name=f"{field_name}.decision_date_count",
    )
    if decision_date_count != len(decision_dates):
        raise TargetDiagnosticError(
            f"{field_name}.decision_date_count does not match decision_dates"
        )
    decision_cutoffs = _validated_decision_cutoffs(
        value.get("decision_cutoffs"),
        decision_dates=decision_dates,
        field_name=f"{field_name}.decision_cutoffs",
    )
    input_candidate_count = _required_int(
        value.get("input_candidate_count"),
        field_name=f"{field_name}.input_candidate_count",
    )
    eligible_candidate_count = _required_int(
        value.get("eligible_candidate_count"),
        field_name=f"{field_name}.eligible_candidate_count",
    )
    raw_rows = value.get("decision_rows")
    if not isinstance(raw_rows, (list, tuple)):
        raise TargetDiagnosticError(f"{field_name}.decision_rows must be an array")
    if len(raw_rows) != decision_date_count:
        raise TargetDiagnosticError(
            f"{field_name}.decision_rows does not cover every decision date"
        )
    decision_rows: list[dict[str, Any]] = []
    total_candidates = 0
    total_eligible = 0
    for position, raw_row in enumerate(raw_rows):
        if not isinstance(raw_row, Mapping):
            raise TargetDiagnosticError(
                f"{field_name}.decision_rows[{position}] must be an object"
            )
        decision_date = _required_text(
            raw_row.get("decision_date"),
            field_name=f"{field_name}.decision_rows[{position}].decision_date",
        )
        if decision_date not in decision_cutoffs:
            raise TargetDiagnosticError(
                f"{field_name}.decision_rows[{position}] has an undeclared date"
            )
        candidate_count = _required_int(
            raw_row.get("candidate_row_count"),
            field_name=(
                f"{field_name}.decision_rows[{position}].candidate_row_count"
            ),
        )
        eligible_count = _required_int(
            raw_row.get("eligible_candidate_count"),
            field_name=(
                f"{field_name}.decision_rows[{position}].eligible_candidate_count"
            ),
        )
        if eligible_count > candidate_count:
            raise TargetDiagnosticError(
                f"{field_name}.decision_rows[{position}] eligible count exceeds candidates"
            )
        complete_candidate_set = raw_row.get("complete_candidate_set")
        if not isinstance(complete_candidate_set, bool):
            raise TargetDiagnosticError(
                f"{field_name}.decision_rows[{position}].complete_candidate_set is invalid"
            )
        target_mode = raw_row.get("target_mode")
        if target_mode not in {"cash_only", "non_cash"}:
            raise TargetDiagnosticError(
                f"{field_name}.decision_rows[{position}].target_mode is invalid"
            )
        decision_rows.append(
            {
                "decision_date": decision_date,
                "candidate_row_count": candidate_count,
                "eligible_candidate_count": eligible_count,
                "complete_candidate_set": complete_candidate_set,
                "target_mode": target_mode,
            }
        )
        total_candidates += candidate_count
        total_eligible += eligible_count
    if tuple(row["decision_date"] for row in decision_rows) != decision_dates:
        raise TargetDiagnosticError(
            f"{field_name}.decision_rows dates do not match decision_dates"
        )
    if total_candidates != input_candidate_count:
        raise TargetDiagnosticError(
            f"{field_name}.input_candidate_count does not match decision rows"
        )
    if total_eligible != eligible_candidate_count:
        raise TargetDiagnosticError(
            f"{field_name}.eligible_candidate_count does not match decision rows"
        )

    raw_sources = value.get("sources")
    if not isinstance(raw_sources, Mapping):
        raise TargetDiagnosticError(f"{field_name}.sources must be an object")
    if set(raw_sources) != set(TEACHER_SOURCE_NAMES):
        raise TargetDiagnosticError(
            f"{field_name}.sources must contain exactly the three Formal sources"
        )
    source_payloads: dict[str, Any] = {}
    source_availability_proven = True
    for source_name in TEACHER_SOURCE_NAMES:
        raw_source = raw_sources.get(source_name)
        if not isinstance(raw_source, Mapping):
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} is missing"
            )
        readback_path = Path(
            _required_text(
                raw_source.get("readback_path"),
                field_name=f"{field_name}.sources.{source_name}.readback_path",
            )
        ).resolve()
        manifest_path = Path(
            _required_text(
                raw_source.get("source_manifest_path"),
                field_name=(
                    f"{field_name}.sources.{source_name}.source_manifest_path"
                ),
            )
        ).resolve()
        for artifact_name, artifact_path in (
            ("readback", readback_path),
            ("source manifest", manifest_path),
        ):
            if artifact_path.is_symlink() or not artifact_path.is_file():
                raise TargetDiagnosticError(
                    f"{field_name}.sources.{source_name} {artifact_name} is missing"
                )
        declared_readback_hash = _required_sha256(
            raw_source.get("readback_file_sha256"),
            field_name=(
                f"{field_name}.sources.{source_name}.readback_file_sha256"
            ),
        )
        if _file_sha256(readback_path) != declared_readback_hash:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} readback hash mismatch"
            )
        declared_manifest_file_hash = _required_sha256(
            raw_source.get("source_manifest_file_sha256"),
            field_name=(
                f"{field_name}.sources.{source_name}.source_manifest_file_sha256"
            ),
        )
        if _file_sha256(manifest_path) != declared_manifest_file_hash:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} manifest file hash mismatch"
            )
        readback = _read_json_object(
            readback_path,
            field_name=f"{field_name}.sources.{source_name}.readback",
        )
        manifest = _read_json_object(
            manifest_path,
            field_name=f"{field_name}.sources.{source_name}.source_manifest",
        )
        declared_manifest_hash = _required_sha256(
            raw_source.get("source_manifest_hash"),
            field_name=f"{field_name}.sources.{source_name}.source_manifest_hash",
        )
        if _manifest_hash_matches(manifest, field_name="manifest_hash") != (
            declared_manifest_hash
        ):
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} manifest identity mismatch"
            )
        _manifest_hash_matches(readback, field_name="receipt_hash")
        declared_identity_hash = _required_sha256(
            raw_source.get("source_identity_hash"),
            field_name=f"{field_name}.sources.{source_name}.source_identity_hash",
        )
        if readback.get("source_identity_hash") != declared_identity_hash:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} identity hash mismatch"
            )
        declared_schema_version = _required_text(
            raw_source.get("source_schema_version"),
            field_name=f"{field_name}.sources.{source_name}.source_schema_version",
        )
        if readback.get("source_schema_version") != declared_schema_version:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} schema mismatch"
            )
        custody = readback.get("custody")
        if (
            not isinstance(custody, Mapping)
            or custody.get("access_mode") != "read_only"
            or custody.get("query_only") is not True
            or custody.get("write_performed") is not False
            or custody.get("source_rows_rebuilt_from_artifact") is not True
        ):
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} source-row custody is incomplete"
            )
        try:
            validation = validate_teacher_source_readback(
                source_name=source_name,
                source_meta=raw_source,
                readback=readback,
                manifest=manifest,
                decision_dates=decision_dates,
                decision_cutoffs=decision_cutoffs,
            )
        except (OSError, TypeError, ValueError, TeacherSourceProvenanceError) as exc:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} artifact readback failed"
            ) from exc
        if raw_source.get("read_only") is not True:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} is not read-only"
            )
        if raw_source.get("source_artifact_path") != readback.get(
            "source_identity", {}
        ).get("source_artifact_path"):
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} source path is not bound"
            )
        source_artifact_hash = _required_sha256(
            raw_source.get("source_artifact_file_sha256"),
            field_name=(
                f"{field_name}.sources.{source_name}.source_artifact_file_sha256"
            ),
        )
        identity = readback.get("source_identity")
        if not isinstance(identity, Mapping):
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} source identity is missing"
            )
        if identity.get("source_artifact_file_sha256") != source_artifact_hash:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} source artifact hash is not bound"
            )
        available_before_decision = validation["availability_proven"] is True
        if raw_source.get("available_before_decision") is not available_before_decision:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} availability declaration mismatch"
            )
        source_availability_proven = (
            source_availability_proven and available_before_decision
        )
        source_payloads[source_name] = {
            "readback_path": str(readback_path),
            "readback_file_sha256": declared_readback_hash,
            "readback_verified": True,
            "source_manifest_path": str(manifest_path),
            "source_manifest_file_sha256": declared_manifest_file_hash,
            "source_manifest_hash": declared_manifest_hash,
            "source_identity_hash": declared_identity_hash,
            "source_schema_version": declared_schema_version,
            "source_row_count": validation["source_row_count"],
            "covered_decision_dates": list(decision_dates),
            "read_only": True,
            "available_before_decision": available_before_decision,
            "receipt_rows": readback.get("rows"),
        }
    return {
        "schema_version": TEACHER_INPUT_PROVENANCE_V2_SCHEMA_VERSION,
        "decision_dates": list(decision_dates),
        "decision_date_count": decision_date_count,
        "decision_cutoffs": {
            decision_date: decision_cutoffs[decision_date].isoformat()
            for decision_date in decision_dates
        },
        "input_candidate_count": input_candidate_count,
        "eligible_candidate_count": eligible_candidate_count,
        "decision_rows": decision_rows,
        "sources": source_payloads,
        "source_rows_are_artifact_rebuilt": True,
        "source_availability_proven": source_availability_proven,
    }


def _validated_teacher_input_provenance(
    value: object,
    *,
    field_name: str = "teacher_input_provenance",
) -> dict[str, Any] | None:
    """驗證三個正式 teacher source 的 hash-bound readback 與逐日覆蓋。

    counters 只能告訴我們「曾經數到幾列」，不能證明來源真的存在或每個
    決策日都有完整候選。新的 provenance 必須附帶已持久化的 readback receipt、
    source identity、可取得時間與完整日期集合；缺任一項就不能讓 OOC fit 通過。
    """

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TargetDiagnosticError(f"{field_name} must be an object")
    schema_version = _required_text(
        value.get("schema_version"),
        field_name=f"{field_name}.schema_version",
    )
    if schema_version == "allocation-teacher-input-provenance.v2":
        return _validated_teacher_input_provenance_v2(
            value,
            field_name=field_name,
        )
    if schema_version != TEACHER_INPUT_PROVENANCE_SCHEMA_VERSION:
        raise TargetDiagnosticError(
            f"{field_name}.schema_version is unsupported"
        )
    decision_dates = _validated_date_sequence(
        value.get("decision_dates"),
        field_name=f"{field_name}.decision_dates",
    )
    decision_date_count = _required_int(
        value.get("decision_date_count"),
        field_name=f"{field_name}.decision_date_count",
    )
    if decision_date_count != len(decision_dates):
        raise TargetDiagnosticError(
            f"{field_name}.decision_date_count does not match decision_dates"
        )
    decision_cutoffs = _validated_decision_cutoffs(
        value.get("decision_cutoffs"),
        decision_dates=decision_dates,
        field_name=f"{field_name}.decision_cutoffs",
    )
    for counter_name in (
        "input_candidate_count",
        "eligible_candidate_count",
    ):
        _required_int(
            value.get(counter_name),
            field_name=f"{field_name}.{counter_name}",
        )

    raw_rows = value.get("decision_rows")
    if not isinstance(raw_rows, (list, tuple)):
        raise TargetDiagnosticError(f"{field_name}.decision_rows must be an array")
    if len(raw_rows) != decision_date_count:
        raise TargetDiagnosticError(
            f"{field_name}.decision_rows does not cover every decision date"
        )
    decision_rows: list[dict[str, Any]] = []
    row_dates: list[str] = []
    total_candidates = 0
    total_eligible = 0
    non_cash_decisions = 0
    cash_only_decisions = 0
    for position, raw_row in enumerate(raw_rows):
        if not isinstance(raw_row, Mapping):
            raise TargetDiagnosticError(
                f"{field_name}.decision_rows[{position}] must be an object"
            )
        decision_date = _required_text(
            raw_row.get("decision_date"),
            field_name=f"{field_name}.decision_rows[{position}].decision_date",
        )
        try:
            normalized_date = datetime.fromisoformat(
                decision_date + "T00:00:00"
            ).date().isoformat()
        except ValueError as exc:
            raise TargetDiagnosticError(
                f"{field_name}.decision_rows[{position}].decision_date is invalid"
            ) from exc
        if normalized_date != decision_date:
            raise TargetDiagnosticError(
                f"{field_name}.decision_rows[{position}].decision_date must be canonical"
            )
        candidate_count = _required_int(
            raw_row.get("candidate_row_count"),
            field_name=f"{field_name}.decision_rows[{position}].candidate_row_count",
        )
        eligible_count = _required_int(
            raw_row.get("eligible_candidate_count"),
            field_name=f"{field_name}.decision_rows[{position}].eligible_candidate_count",
        )
        if eligible_count > candidate_count:
            raise TargetDiagnosticError(
                f"{field_name}.decision_rows[{position}] eligible count exceeds candidates"
            )
        if raw_row.get("complete_candidate_set") is not True:
            raise TargetDiagnosticError(
                f"{field_name}.decision_rows[{position}] candidate set is not complete"
            )
        target_mode = raw_row.get("target_mode")
        if target_mode not in {"cash_only", "non_cash"}:
            raise TargetDiagnosticError(
                f"{field_name}.decision_rows[{position}].target_mode is invalid"
            )
        if target_mode == "cash_only":
            cash_only_decisions += 1
        else:
            non_cash_decisions += 1
        row_dates.append(normalized_date)
        total_candidates += candidate_count
        total_eligible += eligible_count
        decision_rows.append(
            {
                "decision_date": normalized_date,
                "candidate_row_count": candidate_count,
                "eligible_candidate_count": eligible_count,
                "complete_candidate_set": True,
                "target_mode": target_mode,
            }
        )
    if tuple(row_dates) != decision_dates:
        raise TargetDiagnosticError(
            f"{field_name}.decision_rows dates do not match decision_dates"
        )
    if total_candidates != int(value["input_candidate_count"]):
        raise TargetDiagnosticError(
            f"{field_name}.input_candidate_count does not match decision rows"
        )
    if total_eligible != int(value["eligible_candidate_count"]):
        raise TargetDiagnosticError(
            f"{field_name}.eligible_candidate_count does not match decision rows"
        )

    raw_sources = value.get("sources")
    if not isinstance(raw_sources, Mapping):
        raise TargetDiagnosticError(f"{field_name}.sources must be an object")
    source_payloads: dict[str, Any] = {}
    for source_name in _REQUIRED_TEACHER_INPUT_SOURCES:
        raw_source = raw_sources.get(source_name)
        if not isinstance(raw_source, Mapping):
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} is missing"
            )
        readback_path_text = _required_text(
            raw_source.get("readback_path"),
            field_name=f"{field_name}.sources.{source_name}.readback_path",
        )
        readback_path = Path(readback_path_text).resolve()
        if readback_path.is_symlink() or not readback_path.is_file():
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} readback is missing"
            )
        declared_file_hash = _required_sha256(
            raw_source.get("readback_file_sha256"),
            field_name=(
                f"{field_name}.sources.{source_name}.readback_file_sha256"
            ),
        )
        actual_file_hash = _file_sha256(readback_path)
        if actual_file_hash != declared_file_hash:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} readback hash mismatch"
            )

        # 來源 manifest 是獨立的實際檔案；只驗 outer 宣告的 digest 會讓
        # 任意 bytes + true flags 通過，因此必須讀取檔案並重算其內容 hash。
        manifest_path_text = _required_text(
            raw_source.get("source_manifest_path"),
            field_name=f"{field_name}.sources.{source_name}.source_manifest_path",
        )
        manifest_path = Path(manifest_path_text).resolve()
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} source manifest is missing"
            )
        declared_manifest_file_hash = _required_sha256(
            raw_source.get("source_manifest_file_sha256"),
            field_name=(
                f"{field_name}.sources.{source_name}.source_manifest_file_sha256"
            ),
        )
        actual_manifest_file_hash = _file_sha256(manifest_path)
        if actual_manifest_file_hash != declared_manifest_file_hash:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} source manifest file hash mismatch"
            )
        source_manifest = _read_json_object(
            manifest_path,
            field_name=(
                f"{field_name}.sources.{source_name}.source_manifest"
            ),
        )
        actual_manifest_hash = _manifest_hash_matches(
            source_manifest,
            field_name="manifest_hash",
        )
        declared_manifest_hash = _required_sha256(
            raw_source.get("source_manifest_hash"),
            field_name=(
                f"{field_name}.sources.{source_name}.source_manifest_hash"
            ),
        )
        if actual_manifest_hash != declared_manifest_hash:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} source manifest identity mismatch"
            )

        readback = _read_json_object(
            readback_path,
            field_name=f"{field_name}.sources.{source_name}.readback",
        )
        _manifest_hash_matches(readback, field_name="receipt_hash")
        if readback.get("source_name") != source_name:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} receipt source name mismatch"
            )
        source_schema_version = _required_text(
            raw_source.get("source_schema_version"),
            field_name=(
                f"{field_name}.sources.{source_name}.source_schema_version"
            ),
        )
        if readback.get("source_schema_version") != source_schema_version:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} receipt schema mismatch"
            )
        receipt_dates = _validated_date_sequence(
            readback.get("decision_dates"),
            field_name=(
                f"{field_name}.sources.{source_name}.readback.decision_dates"
            ),
        )
        if receipt_dates != decision_dates:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} receipt has partial date coverage"
            )
        receipt_cutoffs = _validated_decision_cutoffs(
            readback.get("decision_cutoffs"),
            decision_dates=decision_dates,
            field_name=(
                f"{field_name}.sources.{source_name}.readback.decision_cutoffs"
            ),
        )
        if any(
            receipt_cutoffs[decision_date] != decision_cutoffs[decision_date]
            for decision_date in decision_dates
        ):
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} receipt cutoff mismatch"
            )

        declared_identity_hash = _required_sha256(
            raw_source.get("source_identity_hash"),
            field_name=(
                f"{field_name}.sources.{source_name}.source_identity_hash"
            ),
        )
        identity = readback.get("source_identity")
        if not isinstance(identity, Mapping):
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} receipt identity is missing"
            )
        actual_identity_hash = _payload_hash(dict(identity))
        if actual_identity_hash != declared_identity_hash:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} source identity hash mismatch"
            )
        if readback.get("source_identity_hash") != actual_identity_hash:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} receipt identity hash mismatch"
            )
        if identity.get("source_name") != source_name:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} identity source name mismatch"
            )
        if identity.get("source_schema_version") != source_schema_version:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} identity schema mismatch"
            )
        if source_manifest.get("source_name") != source_name:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} manifest source name mismatch"
            )
        if source_manifest.get("source_schema_version") != source_schema_version:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} manifest schema mismatch"
            )
        if source_manifest.get("source_identity_hash") != actual_identity_hash:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} manifest identity mismatch"
            )
        manifest_dates = _validated_date_sequence(
            source_manifest.get("decision_dates"),
            field_name=(
                f"{field_name}.sources.{source_name}.source_manifest.decision_dates"
            ),
        )
        if manifest_dates != decision_dates:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} manifest has partial date coverage"
            )

        custody = readback.get("custody")
        if not isinstance(custody, Mapping):
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} readback custody is missing"
            )
        if (
            custody.get("access_mode") != "read_only"
            or custody.get("query_only") is not True
            or custody.get("write_performed") is not False
            or source_manifest.get("storage_mode") != "read_only"
        ):
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} readback is not read-only custody"
            )

        raw_receipt_rows = readback.get("rows")
        receipt_rows, receipt_candidate_count, receipt_eligible_count = (
            _validated_source_receipt_rows(
                raw_receipt_rows,
                source_name=source_name,
                decision_dates=decision_dates,
                decision_cutoffs=decision_cutoffs,
                field_name=f"{field_name}.sources.{source_name}.readback.rows",
            )
        )
        if readback.get("rows_hash") != _payload_hash(raw_receipt_rows):
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} readback rows hash mismatch"
            )
        if source_manifest.get("row_count") != len(receipt_rows):
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} manifest row count mismatch"
            )
        declared_row_count = _required_int(
            raw_source.get("source_row_count"),
            field_name=(
                f"{field_name}.sources.{source_name}.source_row_count"
            ),
            minimum=1,
        )
        if declared_row_count != len(receipt_rows):
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} source row count mismatch"
            )
        source_dates = _validated_date_sequence(
            raw_source.get("covered_decision_dates"),
            field_name=(
                f"{field_name}.sources.{source_name}.covered_decision_dates"
            ),
        )
        if source_dates != decision_dates:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} has partial date coverage"
            )
        if receipt_candidate_count != int(value["input_candidate_count"]):
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} candidate count mismatch"
            )
        if receipt_eligible_count != int(value["eligible_candidate_count"]):
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} eligible count mismatch"
            )
        if source_manifest.get("decision_cutoffs") != {
            decision_date: decision_cutoffs[decision_date].isoformat()
            for decision_date in decision_dates
        }:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} manifest cutoff mismatch"
            )
        if readback.get("source_manifest_hash") != declared_manifest_hash:
            raise TargetDiagnosticError(
                f"{field_name}.sources.{source_name} receipt manifest mismatch"
            )

        # 與 top-level decision_rows 逐日對齊，不能只靠總數相等掩蓋 partial
        # date 或把某日候選挪到另一日。
        for top_row, receipt_row in zip(decision_rows, receipt_rows):
            if (
                top_row["decision_date"] != receipt_row["decision_date"]
                or top_row["candidate_row_count"]
                != receipt_row["candidate_row_count"]
                or top_row["eligible_candidate_count"]
                != receipt_row["eligible_candidate_count"]
                or top_row["target_mode"] != receipt_row["target_mode"]
            ):
                raise TargetDiagnosticError(
                    f"{field_name}.sources.{source_name} receipt row does not bind decision row"
                )
        source_payloads[source_name] = {
            "readback_path": str(readback_path),
            "readback_file_sha256": declared_file_hash,
            "readback_verified": True,
            "source_manifest_path": str(manifest_path),
            "source_manifest_file_sha256": declared_manifest_file_hash,
            "source_manifest_hash": declared_manifest_hash,
            "source_identity_hash": declared_identity_hash,
            "source_schema_version": source_schema_version,
            "source_row_count": declared_row_count,
            "covered_decision_dates": list(source_dates),
            "read_only": True,
            "available_before_decision": True,
            "receipt_rows": receipt_rows,
        }

    return {
        "schema_version": TEACHER_INPUT_PROVENANCE_SCHEMA_VERSION,
        "decision_dates": list(decision_dates),
        "decision_date_count": decision_date_count,
        "decision_cutoffs": {
            decision_date: decision_cutoffs[decision_date].isoformat()
            for decision_date in decision_dates
        },
        "input_candidate_count": int(value["input_candidate_count"]),
        "eligible_candidate_count": int(value["eligible_candidate_count"]),
        "decision_rows": decision_rows,
        "sources": source_payloads,
    }


def _resolve_artifact(
    *,
    entry: Mapping[str, Any],
    year_directory: Path,
    shared_numeric_store_root: Path | None,
) -> Path:
    storage = entry.get("storage")
    if storage == "immutable_shared":
        if shared_numeric_store_root is None:
            raise TargetDiagnosticError(
                "shared_numeric_store_root is required for shared artifact"
            )
        try:
            return resolve_direct_numeric_artifact(
                entry,
                shared_store_root=shared_numeric_store_root,
            )
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise TargetDiagnosticError("shared artifact custody failed") from exc

    raw_path = entry.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise TargetDiagnosticError("local artifact path is missing")
    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise TargetDiagnosticError("local artifact path escapes year directory")
    path = (year_directory / relative).resolve()
    root = year_directory.resolve()
    if path != root and root not in path.parents:
        raise TargetDiagnosticError("local artifact path escapes year directory")
    if path.is_symlink() or not path.is_file():
        raise TargetDiagnosticError(f"local artifact is missing: {path}")
    expected_bytes = _required_int(
        entry.get("byte_count"),
        field_name="artifact.byte_count",
    )
    if path.stat().st_size != expected_bytes:
        raise TargetDiagnosticError(f"local artifact bytes mismatch: {path.name}")
    expected_hash = _required_text(
        entry.get("file_sha256"),
        field_name="artifact.file_sha256",
    )
    if not expected_hash.startswith(_SHA256_PREFIX) or len(expected_hash) != 71:
        raise TargetDiagnosticError("artifact.file_sha256 must be a sha256 digest")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
    if _SHA256_PREFIX + digest.hexdigest() != expected_hash:
        raise TargetDiagnosticError(f"local artifact hash mismatch: {path.name}")
    return path


def _open_readonly_sqlite(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _empty_numeric_summary(field_names: Sequence[str]) -> dict[str, dict[str, int | None]]:
    return {
        field: {
            "min": None,
            "max": None,
            "nonzero_count": 0,
            "observed_count": 0,
        }
        for field in field_names
    }


def _update_numeric_summary(
    summary: dict[str, dict[str, int | None]],
    values: np.ndarray,
    *,
    field_names: Sequence[str],
) -> None:
    for position, field_name in enumerate(field_names):
        column = np.asarray(values[:, position], dtype=np.int64)
        if column.size == 0:
            continue
        field_summary = summary[field_name]
        observed_min = int(column.min())
        observed_max = int(column.max())
        previous_min = field_summary["min"]
        previous_max = field_summary["max"]
        field_summary["min"] = (
            observed_min
            if previous_min is None
            else min(int(previous_min), observed_min)
        )
        field_summary["max"] = (
            observed_max
            if previous_max is None
            else max(int(previous_max), observed_max)
        )
        field_summary["nonzero_count"] = int(
            field_summary["nonzero_count"] or 0
        ) + int(np.count_nonzero(column))
        field_summary["observed_count"] = int(
            field_summary["observed_count"] or 0
        ) + int(column.size)


def _update_label_summary(
    summary: dict[str, dict[str, int | None]],
    values: np.ndarray,
    masks: np.ndarray,
    *,
    horizon: int,
    field_names: Sequence[str],
) -> None:
    for position, field_name in enumerate(field_names):
        column = np.asarray(values[:, position], dtype=np.int64)
        mask = np.asarray(masks[:, position], dtype=np.uint8)
        observed = column[mask == 0]
        field_summary = summary[f"h{horizon}.{field_name}"]
        if observed.size:
            observed_min = int(observed.min())
            observed_max = int(observed.max())
            previous_min = field_summary["min"]
            previous_max = field_summary["max"]
            field_summary["min"] = (
                observed_min
                if previous_min is None
                else min(int(previous_min), observed_min)
            )
            field_summary["max"] = (
                observed_max
                if previous_max is None
                else max(int(previous_max), observed_max)
            )
        field_summary["nonzero_count"] = int(
            field_summary["nonzero_count"] or 0
        ) + int(np.count_nonzero(observed))
        field_summary["observed_count"] = int(
            field_summary["observed_count"] or 0
        ) + int(observed.size)
        field_summary["missing_count"] = int(
            field_summary.get("missing_count", 0) or 0
        ) + int(np.count_nonzero(mask != 0))


def _row_maturity_and_state_counts(
    *,
    rows_path: Path,
    training_as_of: datetime,
) -> dict[str, int | str | None]:
    connection = _open_readonly_sqlite(rows_path)
    target_mature = 0
    max_label_mature = 0
    target_future = 0
    max_label_future = 0
    target_min: datetime | None = None
    target_max: datetime | None = None
    label_min: datetime | None = None
    label_max: datetime | None = None
    state_hashes: set[str] = set()
    row_count = 0
    decision_dates: set[str] = set()
    try:
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(rows)")
        }
        required = {
            "target_available_at",
            "max_label_available_at",
            "portfolio_state_hash",
            "decision_date",
        }
        if not required.issubset(columns):
            raise TargetDiagnosticError("rows.sqlite maturity schema is incomplete")
        cursor = connection.execute(
            "SELECT target_available_at, max_label_available_at, "
            "portfolio_state_hash, decision_date FROM rows "
            "ORDER BY local_row_index"
        )
        for row in cursor:
            target_at = _aware_datetime(
                row["target_available_at"],
                field_name="rows.target_available_at",
            )
            label_at = _aware_datetime(
                row["max_label_available_at"],
                field_name="rows.max_label_available_at",
            )
            target_min = target_at if target_min is None else min(target_min, target_at)
            target_max = target_at if target_max is None else max(target_max, target_at)
            label_min = label_at if label_min is None else min(label_min, label_at)
            label_max = label_at if label_max is None else max(label_max, label_at)
            if target_at <= training_as_of:
                target_mature += 1
            else:
                target_future += 1
            if label_at <= training_as_of:
                max_label_mature += 1
            else:
                max_label_future += 1
            state_hashes.add(str(row["portfolio_state_hash"]))
            decision_dates.add(str(row["decision_date"]))
            row_count += 1
    finally:
        connection.close()
    return {
        "row_count": row_count,
        "decision_date_count": len(decision_dates),
        "portfolio_state_hash_count": len(state_hashes),
        "target_available_mature_count": target_mature,
        "target_available_future_count": target_future,
        "max_label_available_mature_count": max_label_mature,
        "max_label_available_future_count": max_label_future,
        "target_available_min": None if target_min is None else target_min.isoformat(),
        "target_available_max": None if target_max is None else target_max.isoformat(),
        "max_label_available_min": None if label_min is None else label_min.isoformat(),
        "max_label_available_max": None if label_max is None else label_max.isoformat(),
    }


def _replay_source_counts(path: Path) -> dict[str, int]:
    connection = _open_readonly_sqlite(path)
    result = {
        "row_count": 0,
        "sector_observed_count": 0,
        "sector_missing_count": 0,
        "price_event_observed_count": 0,
        "price_available_observed_count": 0,
        "open_observed_count": 0,
        "close_observed_count": 0,
        "volume_observed_count": 0,
        "median_volume_observed_count": 0,
        "rule_score_observed_count": 0,
    }
    try:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(replay_source)")
        }
        if not set(_REPLAY_FIELDS).issubset(columns):
            raise TargetDiagnosticError("replay_source.sqlite schema is incomplete")
        cursor = connection.execute(
            "SELECT sector_id, price_event_at, price_available_at, open_int, "
            "close_int, volume_shares, median_volume_20d_shares, rule_score_bp "
            "FROM replay_source ORDER BY local_row_index"
        )
        for row in cursor:
            result["row_count"] += 1
            sector = row["sector_id"]
            if sector is None or not str(sector).strip():
                result["sector_missing_count"] += 1
            else:
                result["sector_observed_count"] += 1
            for column, output_name in (
                ("price_event_at", "price_event_observed_count"),
                ("price_available_at", "price_available_observed_count"),
                ("open_int", "open_observed_count"),
                ("close_int", "close_observed_count"),
                ("volume_shares", "volume_observed_count"),
                ("median_volume_20d_shares", "median_volume_observed_count"),
                ("rule_score_bp", "rule_score_observed_count"),
            ):
                if row[column] is not None:
                    result[output_name] += 1
    finally:
        connection.close()
    return result


def _summary_integer(
    summary: Mapping[str, Any],
    *,
    field_name: str,
    allow_none: bool = False,
) -> int | None:
    value = summary.get(field_name)
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TargetDiagnosticError(
            f"target summary {field_name} must be an integer"
        )
    return value


def _validated_target_summary(
    value: Mapping[str, Mapping[str, int | None]],
) -> dict[str, dict[str, int | None]]:
    """驗證 gate 只接受完整 target summary，不讀取任何未來 label。"""

    result: dict[str, dict[str, int | None]] = {}
    for field_name in TARGET_FIELDS:
        raw_field = value.get(field_name)
        if not isinstance(raw_field, Mapping):
            raise TargetDiagnosticError(
                f"target summary is missing field: {field_name}"
            )
        minimum = _summary_integer(
            raw_field,
            field_name="min",
            allow_none=True,
        )
        maximum = _summary_integer(
            raw_field,
            field_name="max",
            allow_none=True,
        )
        nonzero_count = _summary_integer(
            raw_field,
            field_name="nonzero_count",
        )
        observed_count = _summary_integer(
            raw_field,
            field_name="observed_count",
        )
        assert nonzero_count is not None
        assert observed_count is not None
        if nonzero_count < 0 or observed_count <= 0:
            raise TargetDiagnosticError(
                f"target summary {field_name} has invalid counts"
            )
        if nonzero_count > observed_count:
            raise TargetDiagnosticError(
                f"target summary {field_name} nonzero count exceeds observed"
            )
        if minimum is None or maximum is None:
            raise TargetDiagnosticError(
                f"target summary {field_name} has no observed range"
            )
        if minimum > maximum:
            raise TargetDiagnosticError(
                f"target summary {field_name} range is reversed"
            )
        result[field_name] = {
            "min": minimum,
            "max": maximum,
            "nonzero_count": nonzero_count,
            "observed_count": observed_count,
        }
    return result


def evaluate_allocation_teacher_eligibility(
    *,
    target_summary: Mapping[str, Mapping[str, int | None]],
    assembly_blockers: Sequence[str] = (),
    teacher_target_diagnostics: Mapping[str, int] | None = None,
    teacher_input_provenance: Mapping[str, Any] | None = None,
    portfolio_state_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """在 OOC fit 前判定 teacher target 是否有可證明的語意來源。

    這個 gate 僅檢查已產生的 target 與當時輸入 provenance counters；它不
    讀取 h5/benchmark label 的未來值，也不以 label 的正負替缺少的 PIT、
    ledger 或 Rule history。缺正式 teacher 輸入時直接拒絕 allocation teacher
    fit；不依賴 teacher 的 base expert outcome research 仍可由獨立比較器執行。
    """

    validated_summary = _validated_target_summary(target_summary)
    provenance = _validated_teacher_input_provenance(
        teacher_input_provenance
    )
    blockers = sorted({str(item) for item in assembly_blockers})
    blocker_set = set(blockers)
    if portfolio_state_policy is not None and not isinstance(
        portfolio_state_policy,
        Mapping,
    ):
        raise TargetDiagnosticError(
            "portfolio_state_policy must be an object when supplied"
        )

    policy_cash_fallback = bool(
        portfolio_state_policy is not None
        and portfolio_state_policy.get("cash_only_fallback") is True
    )
    present_required_blockers = sorted(
        blocker_set & _REQUIRED_TEACHER_BLOCKERS
    )
    if policy_cash_fallback and (
        "portfolio_ledger_missing_cash_only_fallback_turnover_and_cooldown_not_learned"
        not in present_required_blockers
    ):
        present_required_blockers.append(
            "portfolio_ledger_missing_cash_only_fallback_turnover_and_cooldown_not_learned"
        )
        present_required_blockers.sort()

    numeric_constant_zero = all(
        validated_summary[field_name]["min"] == 0
        and validated_summary[field_name]["max"] == 0
        and validated_summary[field_name]["nonzero_count"] == 0
        for field_name in _TEACHER_NUMERIC_TARGET_FIELDS
    )
    cash_constant = (
        validated_summary["cash_bp"]["min"] == 10_000
        and validated_summary["cash_bp"]["max"] == 10_000
        and validated_summary["cash_bp"]["nonzero_count"]
        == validated_summary["cash_bp"]["observed_count"]
    )
    all_cash_target = numeric_constant_zero and cash_constant

    diagnostics: dict[str, int] | None = None
    diagnostics_missing: list[str] = []
    if teacher_target_diagnostics is not None:
        if not isinstance(teacher_target_diagnostics, Mapping):
            raise TargetDiagnosticError(
                "teacher_target_diagnostics must be an object"
            )
        diagnostics = {}
        for raw_key, raw_value in teacher_target_diagnostics.items():
            if not isinstance(raw_key, str) or not raw_key.strip():
                raise TargetDiagnosticError(
                    "teacher_target_diagnostics key must be text"
                )
            diagnostics[raw_key] = _required_int(
                raw_value,
                field_name=f"teacher_target_diagnostics.{raw_key}",
            )
        diagnostics_missing = sorted(
            field_name
            for field_name in _REQUIRED_TEACHER_DIAGNOSTIC_FIELDS
            if field_name not in diagnostics
        )

    reasons: list[str] = []
    status = "blocked_teacher_eligibility_unclassified"
    allowed = False
    if present_required_blockers:
        reasons.extend(
            f"missing_formal_teacher_input:{item}"
            for item in present_required_blockers
        )
        status = "blocked_missing_formal_teacher_inputs"
    elif diagnostics is None:
        reasons.append("teacher_target_diagnostics_missing")
        status = "blocked_missing_teacher_provenance"
    elif diagnostics_missing:
        reasons.extend(
            f"teacher_target_diagnostics_missing:{item}"
            for item in diagnostics_missing
        )
        status = "blocked_incomplete_teacher_provenance"
    elif provenance is None:
        reasons.append("teacher_input_provenance_missing")
        status = "blocked_missing_teacher_provenance"
    else:
        assert diagnostics is not None
        if provenance["decision_date_count"] != diagnostics["decision_date_count"]:
            reasons.append("teacher_provenance_decision_date_count_mismatch")
        if provenance["input_candidate_count"] != diagnostics["input_candidate_count"]:
            reasons.append("teacher_provenance_input_candidate_count_mismatch")
        if provenance["eligible_candidate_count"] != diagnostics["eligible_candidate_count"]:
            reasons.append("teacher_provenance_eligible_candidate_count_mismatch")
        provenance_rows = provenance["decision_rows"]
        if len(provenance_rows) != diagnostics["decision_date_count"]:
            reasons.append("teacher_provenance_partial_decision_coverage")
        if provenance.get("schema_version") == (
            "allocation-teacher-input-provenance.v2"
        ):
            if provenance.get("source_availability_proven") is not True:
                reasons.append("teacher_source_availability_unproven")
            if any(
                row.get("complete_candidate_set") is not True
                for row in provenance_rows
            ):
                reasons.append("teacher_provenance_incomplete_candidate_set")
        if sum(
            row["target_mode"] == "non_cash" for row in provenance_rows
        ) != diagnostics["non_cash_target_decision_count"]:
            reasons.append("teacher_provenance_non_cash_counter_mismatch")
        if sum(
            row["target_mode"] == "cash_only" for row in provenance_rows
        ) != diagnostics["cash_only_target_decision_count"]:
            reasons.append("teacher_provenance_cash_only_counter_mismatch")
        if any(
            row["eligible_candidate_count"] <= 0
            for row in provenance_rows
        ):
            reasons.append("teacher_provenance_zero_eligible_decision")
        unknown_sector_count = diagnostics["unknown_sector_candidate_count"]
        eligible_count = diagnostics["eligible_candidate_count"]
        incomplete_count = diagnostics["teacher_incomplete_decision_count"]
        non_cash_count = diagnostics["non_cash_target_decision_count"]
        cash_only_count = diagnostics["cash_only_target_decision_count"]
        decision_count = diagnostics["decision_date_count"]
        if decision_count <= 0:
            reasons.append("teacher_decision_date_count_is_zero")
        if unknown_sector_count > 0:
            reasons.append(
                "unknown_sector_candidate_count_is_nonzero"
            )
        if eligible_count <= 0:
            reasons.append("eligible_candidate_count_is_zero")
        if diagnostics["label_row_count"] != validated_summary["cash_bp"]["observed_count"]:
            reasons.append("target_summary_row_count_mismatch")
        if incomplete_count > 0:
            reasons.append("teacher_incomplete_decision_count_is_nonzero")
        if all_cash_target and non_cash_count > 0:
            reasons.append("target_summary_disagrees_with_non_cash_counter")
        if not all_cash_target and non_cash_count == 0:
            reasons.append("target_summary_disagrees_with_cash_counter")
        if cash_only_count + non_cash_count != decision_count:
            reasons.append("teacher_target_decision_counters_do_not_balance")
        if reasons:
            status = "blocked_incomplete_teacher_eligibility"
        elif all_cash_target:
            # 只有完成 candidate/sector/teacher provenance 後的全 cash，才
            # 能標成策略結果；仍不得轉成 formal OOS 或 production alpha。
            allowed = True
            status = "allowed_strategy_cash_only_with_candidates"
        else:
            allowed = True
            status = "allowed_nonconstant_targets_with_candidates"

    result: dict[str, Any] = {
        "schema_version": ALLOCATION_TEACHER_GATE_SCHEMA_VERSION,
        "allowed": allowed,
        "status": status,
        "reasons": sorted(reasons),
        "required_formal_teacher_blockers_present": present_required_blockers,
        "target_summary_scope": {
            "numeric_targets_constant_zero": numeric_constant_zero,
            "cash_target_constant_10000": cash_constant,
            "all_cash_target": all_cash_target,
            "target_fields": list(TARGET_FIELDS),
        },
        "teacher_diagnostics_present": diagnostics is not None,
        "teacher_diagnostics_missing_fields": diagnostics_missing,
        "teacher_target_diagnostics": diagnostics,
        "teacher_input_provenance_present": provenance is not None,
        "teacher_input_provenance": provenance,
        "uses_future_labels": False,
        "outcome_research_allowed": True,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
    }
    result["identity_hash"] = _payload_hash(result)
    return result


def _classify(
    *,
    target_summary: Mapping[str, Mapping[str, int | None]],
    label_summary: Mapping[str, Mapping[str, int | None]],
    source_counts: Mapping[str, int],
    assembly_blockers: Sequence[str],
    state_policy: Mapping[str, Any] | None,
) -> dict[str, Any]:
    numeric_fields = TARGET_FIELDS[:4] + (TARGET_FIELDS[5],)
    numeric_constant_zero = all(
        target_summary[field]["min"] == 0
        and target_summary[field]["max"] == 0
        and target_summary[field]["nonzero_count"] == 0
        for field in numeric_fields
    )
    cash_constant = (
        target_summary["cash_bp"]["min"] == 10_000
        and target_summary["cash_bp"]["max"] == 10_000
        and target_summary["cash_bp"]["nonzero_count"]
        == target_summary["cash_bp"]["observed_count"]
    )
    benchmark_label = label_summary.get("h20.benchmark_excess_return_bp", {})
    label_varies = (
        benchmark_label.get("min") is not None
        and benchmark_label.get("max") is not None
        and benchmark_label.get("min") != benchmark_label.get("max")
    )
    all_sector_missing = source_counts.get("sector_observed_count", 0) == 0
    blockers = set(str(item) for item in assembly_blockers)
    sector_blocked = (
        "pit_sector_membership_missing_teacher_new_positions_disabled" in blockers
        or all_sector_missing
    )
    ledger_cash_only = bool(
        state_policy is not None and state_policy.get("cash_only_fallback") is True
    ) or "portfolio_ledger_missing_cash_only_fallback_turnover_and_cooldown_not_learned" in blockers
    if numeric_constant_zero and cash_constant and sector_blocked:
        category = "data_blocked_no_eligible_sector_candidates"
        explanation = (
            "成熟 benchmark label 有變化，但 teacher 候選缺少可證明的 PIT "
            "sector，因此新增持倉 fail closed；cash-only state 只代表缺正式 "
            "ledger，不能解讀為模型學會持有現金。"
        )
    elif numeric_constant_zero and cash_constant and not sector_blocked:
        category = "strategy_or_policy_cash_only_with_candidates"
        explanation = (
            "已有 sector candidate，但 teacher 在既定限制與觀測 label 下仍選 "
            "cash；這是策略／政策結果，不能歸因於 sector 缺件。"
        )
    elif numeric_constant_zero and cash_constant:
        category = "cash_only_degeneracy_unclassified"
        explanation = (
            "target 是全 cash，但現有 compact manifest 不足以證明候選 eligibility "
            "或 portfolio state 原因。"
        )
    else:
        category = "nonconstant_targets"
        explanation = "target 至少有一個非現金或非零配置欄位。"
    return {
        "category": category,
        "explanation": explanation,
        "numeric_targets_constant_zero": numeric_constant_zero,
        "cash_target_constant_10000": cash_constant,
        "matured_benchmark_label_varies": label_varies,
        "sector_candidates_all_missing": all_sector_missing,
        "cash_only_state_fallback_declared": ledger_cash_only,
        "formal_rule_history_blocked": (
            "formal_rule_champion_snapshot_history_missing_formal_replay_blocked"
            in blockers
        ),
        "formal_inputs_missing": sorted(
            item
            for item in (
                "pit_sector_membership",
                "causal_non_cash_portfolio_ledger",
                "formal_rule_champion_snapshot_history",
            )
            if (
                (item == "pit_sector_membership" and sector_blocked)
                or (
                    item == "causal_non_cash_portfolio_ledger"
                    and ledger_cash_only
                )
                or (
                    item == "formal_rule_champion_snapshot_history"
                    and "formal_rule_champion_snapshot_history_missing_formal_replay_blocked"
                    in blockers
                )
            )
        ),
    }


def diagnose_direct_numeric_store(
    manifest_path: Path,
    *,
    shared_numeric_store_root: Path | None = None,
    years: Sequence[int] = (),
    chunk_rows: int = _DEFAULT_CHUNK_ROWS,
) -> dict[str, Any]:
    """以 bounded read 產生 target／label／maturity 根因診斷。"""

    resolved_manifest = manifest_path.expanduser().resolve()
    manifest = _read_object(resolved_manifest)
    if manifest.get("schema_version") != DIRECT_STORE_SCHEMA_VERSION:
        raise TargetDiagnosticError(
            "manifest schema is not portfolio-ml-ooc-store.v3"
        )
    if manifest.get("status") != "complete":
        raise TargetDiagnosticError("Direct manifest is not complete")
    manifest_hash = _manifest_hash_matches(manifest, field_name="manifest_hash")
    training_as_of = _aware_datetime(
        manifest.get("training_as_of"),
        field_name="training_as_of",
    )
    if isinstance(chunk_rows, bool) or not isinstance(chunk_rows, int) or chunk_rows <= 0:
        raise TargetDiagnosticError("chunk_rows must be a positive integer")
    requested_years = frozenset(int(year) for year in years)
    year_entries = manifest.get("years")
    if not isinstance(year_entries, list):
        raise TargetDiagnosticError("manifest years must be an array")
    selected = [
        item
        for item in year_entries
        if isinstance(item, Mapping)
        and (not requested_years or int(item.get("year", -1)) in requested_years)
    ]
    if not selected:
        raise TargetDiagnosticError("diagnostic selected no years")

    target_summary = _empty_numeric_summary(TARGET_FIELDS)
    horizons_raw = manifest.get("horizons")
    if not isinstance(horizons_raw, list) or not horizons_raw:
        raise TargetDiagnosticError("manifest horizons are missing")
    horizons = tuple(_required_int(value, field_name="horizon", minimum=1) for value in horizons_raw)
    manifest_label_fields = manifest.get("label_fields")
    if manifest_label_fields != list(LABEL_FIELDS):
        raise TargetDiagnosticError("manifest label_fields contract mismatch")
    manifest_target_fields = manifest.get("target_fields")
    if manifest_target_fields != list(TARGET_FIELDS):
        raise TargetDiagnosticError("manifest target_fields contract mismatch")
    label_summary = _empty_numeric_summary(
        tuple(f"h{horizon}.{field}" for horizon in horizons for field in LABEL_FIELDS)
    )

    shared_root = (
        None
        if shared_numeric_store_root is None
        else shared_numeric_store_root.expanduser().resolve()
    )
    selected_years: list[dict[str, Any]] = []
    total_rows = 0
    total_source_counts = {
        "row_count": 0,
        "sector_observed_count": 0,
        "sector_missing_count": 0,
        "price_event_observed_count": 0,
        "price_available_observed_count": 0,
        "open_observed_count": 0,
        "close_observed_count": 0,
        "volume_observed_count": 0,
        "median_volume_observed_count": 0,
        "rule_score_observed_count": 0,
    }
    maturity_totals = {
        "row_count": 0,
        "decision_date_count": 0,
        "portfolio_state_hash_count": 0,
        "target_available_mature_count": 0,
        "target_available_future_count": 0,
        "max_label_available_mature_count": 0,
        "max_label_available_future_count": 0,
    }

    for raw_year in sorted(selected, key=lambda item: int(item["year"])):
        year = _required_int(raw_year.get("year"), field_name="year", minimum=1900)
        year_manifest_path = resolved_manifest.parent / f"year={year:04d}" / "manifest.json"
        if not year_manifest_path.is_file():
            raise TargetDiagnosticError(f"year manifest is missing: {year_manifest_path}")
        year_manifest = _read_object(year_manifest_path)
        if year_manifest.get("schema_version") != YEAR_SCHEMA_VERSION:
            raise TargetDiagnosticError(f"year {year} schema mismatch")
        actual_year_hash = _manifest_hash_matches(
            year_manifest,
            field_name="manifest_hash",
        )
        declared_year_hash = raw_year.get("manifest_hash")
        if (
            declared_year_hash is not None
            and declared_year_hash != actual_year_hash
        ):
            raise TargetDiagnosticError(
                f"top-level year {year} manifest hash mismatch"
            )
        year_directory = year_manifest_path.parent
        entries = _artifact_entries(year_manifest)
        target_path = _resolve_artifact(
            entry=entries["targets.i32"],
            year_directory=year_directory,
            shared_numeric_store_root=shared_root,
        )
        labels_path = _resolve_artifact(
            entry=entries["labels.i32"],
            year_directory=year_directory,
            shared_numeric_store_root=shared_root,
        )
        masks_path = _resolve_artifact(
            entry=entries["labels.masks.u8"],
            year_directory=year_directory,
            shared_numeric_store_root=shared_root,
        )
        rows_path = _resolve_artifact(
            entry=entries["rows.sqlite"],
            year_directory=year_directory,
            shared_numeric_store_root=shared_root,
        )
        replay_path = _resolve_artifact(
            entry=entries["replay_source.sqlite"],
            year_directory=year_directory,
            shared_numeric_store_root=shared_root,
        )
        row_count = _required_int(raw_year.get("row_count"), field_name=f"year {year}.row_count")
        expected_target_bytes = row_count * len(TARGET_FIELDS) * np.dtype("<i4").itemsize
        expected_label_bytes = row_count * len(horizons) * len(LABEL_FIELDS) * np.dtype("<i4").itemsize
        expected_mask_bytes = row_count * len(horizons) * len(LABEL_FIELDS) * np.dtype("u1").itemsize
        if target_path.stat().st_size != expected_target_bytes:
            raise TargetDiagnosticError(f"year {year} targets shape/bytes mismatch")
        if labels_path.stat().st_size != expected_label_bytes:
            raise TargetDiagnosticError(f"year {year} labels shape/bytes mismatch")
        if masks_path.stat().st_size != expected_mask_bytes:
            raise TargetDiagnosticError(f"year {year} label masks shape/bytes mismatch")
        year_teacher_diagnostics = _validated_teacher_diagnostics(
            year_manifest.get("teacher_target_diagnostics"),
            field_name=f"year {year}.teacher_target_diagnostics",
        )
        year_target_summary = _empty_numeric_summary(TARGET_FIELDS)
        year_label_summary = _empty_numeric_summary(
            tuple(
                f"h{horizon}.{field}"
                for horizon in horizons
                for field in LABEL_FIELDS
            )
        )
        target_values = np.memmap(
            target_path,
            mode="r",
            dtype="<i4",
            shape=(row_count, len(TARGET_FIELDS)),
        )
        label_values = np.memmap(
            labels_path,
            mode="r",
            dtype="<i4",
            shape=(row_count, len(horizons), len(LABEL_FIELDS)),
        )
        label_masks = np.memmap(
            masks_path,
            mode="r",
            dtype="u1",
            shape=(row_count, len(horizons), len(LABEL_FIELDS)),
        )
        for start in range(0, row_count, chunk_rows):
            end = min(row_count, start + chunk_rows)
            mask_chunk = np.asarray(label_masks[start:end])
            if np.any((mask_chunk != 0) & (mask_chunk != 1)):
                raise TargetDiagnosticError(
                    f"year {year} label mask contains non-binary values"
                )
            _update_numeric_summary(
                target_summary,
                np.asarray(target_values[start:end]),
                field_names=TARGET_FIELDS,
            )
            _update_numeric_summary(
                year_target_summary,
                np.asarray(target_values[start:end]),
                field_names=TARGET_FIELDS,
            )
            for horizon_position, horizon in enumerate(horizons):
                _update_label_summary(
                    label_summary,
                    np.asarray(label_values[start:end, horizon_position, :]),
                    mask_chunk[:, horizon_position, :],
                    horizon=horizon,
                    field_names=LABEL_FIELDS,
                )
                _update_label_summary(
                    year_label_summary,
                    np.asarray(label_values[start:end, horizon_position, :]),
                    mask_chunk[:, horizon_position, :],
                    horizon=horizon,
                    field_names=LABEL_FIELDS,
                )
        del target_values, label_values, label_masks
        maturity = _row_maturity_and_state_counts(
            rows_path=rows_path,
            training_as_of=training_as_of,
        )
        source_counts = _replay_source_counts(replay_path)
        if maturity["row_count"] != row_count:
            raise TargetDiagnosticError(
                f"year {year} rows.sqlite count mismatch"
            )
        if source_counts["row_count"] != row_count:
            raise TargetDiagnosticError(
                f"year {year} replay_source.sqlite count mismatch"
            )
        for key, source_value in source_counts.items():
            total_source_counts[key] = (
                total_source_counts.get(key, 0) + source_value
            )
        for key, maturity_value in maturity.items():
            if key.endswith("_count"):
                if (
                    isinstance(maturity_value, bool)
                    or not isinstance(maturity_value, int)
                ):
                    raise TargetDiagnosticError(
                        f"maturity count is not an integer: {key}"
                    )
                maturity_totals[key] = maturity_totals.get(key, 0) + int(
                    maturity_value
                )
        total_rows += row_count
        selected_years.append(
            {
                "year": year,
                "row_count": row_count,
                "target_summary": {
                    key: dict(value) for key, value in year_target_summary.items()
                },
                "label_summary": {
                    key: dict(value) for key, value in year_label_summary.items()
                },
                "maturity": maturity,
                "source_counts": source_counts,
                "teacher_target_diagnostics": year_teacher_diagnostics,
            }
        )

    expected_manifest_rows = _required_int(
        manifest.get("row_count"),
        field_name="manifest.row_count",
    )
    selected_scope_complete = not requested_years and total_rows == expected_manifest_rows
    assembly_blockers_raw = manifest.get("assembly_blockers", [])
    if not isinstance(assembly_blockers_raw, list):
        raise TargetDiagnosticError("assembly_blockers must be an array")
    state_policy = manifest.get("portfolio_state_policy")
    if state_policy is not None and not isinstance(state_policy, Mapping):
        raise TargetDiagnosticError("portfolio_state_policy must be an object")
    teacher_diagnostics = _validated_teacher_diagnostics(
        manifest.get("teacher_target_diagnostics"),
        field_name="teacher_target_diagnostics",
    )
    teacher_input_provenance = _validated_teacher_input_provenance(
        manifest.get("teacher_input_provenance"),
        field_name="teacher_input_provenance",
    )
    classification = _classify(
        target_summary=target_summary,
        label_summary=label_summary,
        source_counts=total_source_counts,
        assembly_blockers=[str(item) for item in assembly_blockers_raw],
        state_policy=state_policy,
    )
    allocation_teacher_eligibility = evaluate_allocation_teacher_eligibility(
        target_summary=target_summary,
        assembly_blockers=[str(item) for item in assembly_blockers_raw],
        teacher_target_diagnostics=teacher_diagnostics,
        teacher_input_provenance=teacher_input_provenance,
        portfolio_state_policy=state_policy,
    )
    source_missing_counts = {
        key.replace("_observed_count", "_missing_count"): total_rows - value
        for key, value in total_source_counts.items()
        if key.endswith("_observed_count")
    }
    return {
        "schema_version": TARGET_DIAGNOSTIC_SCHEMA_VERSION,
        "status": "complete",
        "read_only": True,
        "historical_backfill_claimed": False,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "source": {
            "direct_manifest_path": str(resolved_manifest),
            "direct_manifest_hash": manifest_hash,
            "run_id": manifest.get("run_id"),
            "dataset_identity_hash": manifest.get("dataset_identity_hash"),
            "source_training_manifest_hash": manifest.get(
                "source_training_manifest_hash"
            ),
            "source_manifest_hashes": manifest.get("source_manifest_hashes"),
            "feature_registry_hash": manifest.get("feature_registry_hash"),
            "direct_builder_schema_version": manifest.get(
                "direct_builder_schema_version"
            ),
            "training_as_of": training_as_of.isoformat(),
            "declared_row_count": expected_manifest_rows,
            "selected_row_count": total_rows,
            "selected_scope_complete": selected_scope_complete,
            "selected_years": [int(item["year"]) for item in selected_years],
        },
        "assembly_blockers": sorted(str(item) for item in assembly_blockers_raw),
        "teacher_target_diagnostics": teacher_diagnostics,
        "teacher_input_provenance": teacher_input_provenance,
        "allocation_teacher_eligibility": allocation_teacher_eligibility,
        "provenance": {
            "label_producer": (
                "PortfolioMLDatasetAssembler._build_label_spool"
            ),
            "label_contract": "benchmark/sector outcome labels are computed before teacher targets",
            "target_producer": (
                "CausalAllocationTeacher.build_targets via "
                "PortfolioMLDatasetAssembler._assemble_samples"
            ),
            "maturity_source": (
                "rows.sqlite.target_available_at and "
                "rows.sqlite.max_label_available_at"
            ),
            "eligibility_source": (
                "replay_source.sqlite.sector_id plus Direct assembly_blockers"
            ),
            "labels_are_teacher_independent": True,
            "target_values_are_not_reconstructed": True,
        },
        "maturity": maturity_totals,
        "candidate_inputs": total_source_counts,
        "candidate_input_missing_counts": source_missing_counts,
        "targets": {
            "fields": {
                key: dict(value) for key, value in target_summary.items()
            },
            "numeric_fields": list(TARGET_FIELDS[:4] + (TARGET_FIELDS[5],)),
        },
        "labels": {
            "fields": {
                key: dict(value) for key, value in label_summary.items()
            },
            "horizons": list(horizons),
        },
        "classification": classification,
        "years": selected_years,
        "prospective_repair": {
            "mode": "future_formal_input_handoff_only",
            "historical_backfill_allowed": False,
            "required_sources": {
                "pit_sector_membership": (
                    "accepted PIT sidecar with decision-time available_at/effective_from"
                ),
                "causal_non_cash_portfolio_ledger": (
                    "append-only formal T-1 transition ledger with non-cash state"
                ),
                "formal_rule_champion_snapshot_history": (
                    "verified controlled Rule snapshot history covering the same dates"
                ),
            },
            "handoff": (
                "run_formal_input_producer_daily.py creates candidate artifacts; "
                "maintain_ml_direct_v3_refresh_chain.py may consume only validated "
                "formal publications bound by hash and training_as_of"
            ),
            "candidate_artifacts_are_formal_inputs": False,
        },
    }


__all__ = [
    "ALLOCATION_TEACHER_GATE_SCHEMA_VERSION",
    "DIRECT_STORE_SCHEMA_VERSION",
    "TEACHER_INPUT_PROVENANCE_SCHEMA_VERSION",
    "TARGET_DIAGNOSTIC_SCHEMA_VERSION",
    "TargetDiagnosticError",
    "diagnose_direct_numeric_store",
    "evaluate_allocation_teacher_eligibility",
]
