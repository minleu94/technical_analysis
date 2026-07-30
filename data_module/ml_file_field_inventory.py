"""唯讀盤點 DATA_ROOT 內可供 ML 治理的 file-backed 欄位。

本模組刻意不讀取 SQLite（SQLite 欄位由 ``ml_module.feature_eligibility``
負責），也不把任何新發現的檔案欄位自動提升為正式特徵：

* CSV 僅讀取有界 header，不讀資料列。
* JSON / JSONL 僅在固定 byte / line 上限內辨識 top-level 與 row keys。
* 未知欄位一律 ``unreviewed``，財報快照缺少公告時間則
  ``blocked_no_provenance``。
* prediction、model、replay、outcome、backtest 與 legacy pickle 明確隔離。

報告中的路徑全部相對於 ``DATA_ROOT``，不持久化本機絕對路徑。
"""

from __future__ import annotations

from collections import Counter
import csv
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Callable, Iterable, Literal, Mapping, Sequence


FileEligibilityStatus = Literal[
    "formal_backfill",
    "first_seen_only",
    "research_shadow",
    "availability_only",
    "excluded_identifier",
    "excluded_leakage",
    "blocked_no_provenance",
    "unreviewed",
]

FILE_ELIGIBILITY_STATUSES: frozenset[str] = frozenset(
    {
        "formal_backfill",
        "first_seen_only",
        "research_shadow",
        "availability_only",
        "excluded_identifier",
        "excluded_leakage",
        "blocked_no_provenance",
        "unreviewed",
    }
)

_SCANNED_SUFFIXES = frozenset({".csv", ".json", ".jsonl"})
_EXPLICIT_BINARY_SUFFIXES = frozenset({".pkl", ".pickle"})
_SKIPPED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".pytest_cache",
        "__pycache__",
        "_test",
        "backup",
        "backup_daily_etf",
        "cache",
        "logs",
        "temp",
        "test_data",
        "test_results",
        "tmp",
    }
)
_LEAKAGE_PATH_TOKENS = frozenset(
    {
        "backtest",
        "equity_curve",
        "label",
        "labels",
        "model",
        "models",
        "outcome",
        "outcomes",
        "prediction",
        "predictions",
        "replay",
        "research_runs",
        "target",
        "targets",
        "trade",
        "trades",
    }
)
_OUTPUT_DETAIL_TOKENS = frozenset(
    {
        "detail",
        "details",
        "rows",
        "shard",
        "shards",
    }
)
_RESEARCH_PATH_ROOTS = frozenset(
    {
        "broker_flow",
        "features",
        "industry_analysis",
        "industry_correlation",
        "ky__buy_sell",
        "portfolio",
        "predictions",
    }
)
_IDENTIFIER_NAMES = frozenset(
    {
        "branch_broker_code",
        "branch_code",
        "branch_system_key",
        "code",
        "company_id",
        "company_name",
        "id",
        "industry",
        "industry_id",
        "industry_name",
        "name",
        "row_id",
        "run_id",
        "security_code",
        "security_name",
        "stock_code",
        "stock_id",
        "stock_name",
        "symbol",
        "ticker",
        "uuid",
        "公司代號",
        "公司名稱",
        "產業別",
        "證券代號",
        "證券名稱",
    }
)
_LEAKAGE_FIELD_TOKENS = (
    "future_",
    "forward_",
    "label",
    "next_",
    "outcome",
    "prediction",
    "realized_",
    "target_",
)

_TIME_CANDIDATES: Mapping[str, frozenset[str]] = {
    "event_at": frozenset(
        {
            "as_of_date",
            "date",
            "data_date",
            "decision_date",
            "event_at",
            "event_date",
            "observation_date",
            "period",
            "period_end",
            "report_date",
            "trade_date",
            "year_month",
            "日期",
            "年月",
        }
    ),
    "announced_at": frozenset(
        {
            "announced_at",
            "announced_date",
            "announcement_at",
            "announcement_date",
            "publication_at",
            "publication_date",
            "公告日期",
            "出表日期",
        }
    ),
    "available_at": frozenset(
        {
            "available_at",
            "available_date",
            "published_at",
            "published_date",
            "publication_at",
            "publication_date",
            "資料可用日期",
            "出表日期",
        }
    ),
    "first_seen_at": frozenset(
        {
            "created_at",
            "fetched_at",
            "first_observed_at",
            "first_seen_at",
            "ingested_at",
            "observed_at",
        }
    ),
    "effective_at": frozenset(
        {
            "effective_at",
            "effective_date",
            "生效日期",
        }
    ),
    "revision_id": frozenset(
        {
            "revision",
            "revision_id",
            "source_version",
            "updated_at",
            "version",
            "修訂版本",
        }
    ),
}


@dataclass(frozen=True)
class PITAvailabilityFields:
    """檔案 schema 中可辨識的 PIT 時間／修訂欄位。"""

    event_at: tuple[str, ...] = ()
    announced_at: tuple[str, ...] = ()
    available_at: tuple[str, ...] = ()
    first_seen_at: tuple[str, ...] = ()
    effective_at: tuple[str, ...] = ()
    revision_id: tuple[str, ...] = ()

    @property
    def has_availability_evidence(self) -> bool:
        return bool(self.available_at or self.first_seen_at)

    def all_fields(self) -> frozenset[str]:
        return frozenset(
            field_name
            for values in (
                self.event_at,
                self.announced_at,
                self.available_at,
                self.first_seen_at,
                self.effective_at,
                self.revision_id,
            )
            for field_name in values
        )


@dataclass(frozen=True)
class FileFieldEligibilityRecord:
    """單一 file-backed ``source.field`` 的 fail-closed disposition。"""

    source_field_id: str
    source_id: str
    field_name: str
    path_pattern: str
    file_format: str
    canonical_dtype: str
    dtype_basis: str
    eligibility_status: FileEligibilityStatus
    reason_code: str
    pit_availability_fields: PITAvailabilityFields
    source_hash: str
    source_hash_scope: str
    license_policy: str
    quality_policy: str

    def __post_init__(self) -> None:
        required = (
            self.source_field_id,
            self.source_id,
            self.field_name,
            self.path_pattern,
            self.file_format,
            self.canonical_dtype,
            self.dtype_basis,
            self.reason_code,
            self.source_hash,
            self.source_hash_scope,
            self.license_policy,
            self.quality_policy,
        )
        if any(not value.strip() for value in required):
            raise ValueError("file field eligibility text values must be non-empty")
        if self.eligibility_status not in FILE_ELIGIBILITY_STATUSES:
            raise ValueError(
                f"invalid file eligibility status: {self.eligibility_status}"
            )
        _require_sha256(self.source_hash, field_name="source_hash")


@dataclass(frozen=True)
class FileSourceSchemaRecord:
    """依相對 path pattern + bounded schema 去重後的來源。"""

    source_id: str
    path_pattern: str
    file_format: str
    file_count: int
    representative_relative_path: str
    field_count: int
    source_hash: str
    source_hash_scope: str
    default_status: FileEligibilityStatus
    reason_code: str
    license_policy: str
    quality_policy: str

    def __post_init__(self) -> None:
        if isinstance(self.file_count, bool) or self.file_count <= 0:
            raise ValueError("file_count must be positive")
        if isinstance(self.field_count, bool) or self.field_count <= 0:
            raise ValueError("field_count must be positive")
        _require_sha256(self.source_hash, field_name="source_hash")


@dataclass(frozen=True)
class SkippedFileScope:
    """未解析 schema、但已有明確隔離 disposition 的檔案／目錄群。"""

    path_pattern: str
    object_kind: Literal["file", "directory"]
    file_count: int
    eligibility_status: FileEligibilityStatus
    reason_code: str

    def __post_init__(self) -> None:
        if isinstance(self.file_count, bool) or self.file_count < 0:
            raise ValueError("file_count must be non-negative")
        if self.eligibility_status not in FILE_ELIGIBILITY_STATUSES:
            raise ValueError(
                f"invalid skipped eligibility status: {self.eligibility_status}"
            )


@dataclass(frozen=True)
class FileFieldInventory:
    """完整 file-backed schema inventory。"""

    generated_at: str
    sources: tuple[FileSourceSchemaRecord, ...]
    fields: tuple[FileFieldEligibilityRecord, ...]
    skipped: tuple[SkippedFileScope, ...]
    candidate_file_count: int
    schema_scanned_file_count: int
    skipped_file_count: int
    unsupported_extension_counts: tuple[tuple[str, int], ...]
    inventory_hash: str

    def __post_init__(self) -> None:
        if self.candidate_file_count != (
            self.schema_scanned_file_count + self.skipped_file_count
        ):
            raise ValueError("every discovered candidate file requires a disposition")
        source_ids = tuple(source.source_id for source in self.sources)
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source_id must be unique")
        valid_sources = set(source_ids)
        if any(field.source_id not in valid_sources for field in self.fields):
            raise ValueError("every field must reference an inventoried source")
        _require_sha256(self.inventory_hash, field_name="inventory_hash")

    def to_dict(self) -> dict[str, object]:
        status_counts = Counter(
            field.eligibility_status for field in self.fields
        )
        skipped_reason_counts = Counter(
            skipped.reason_code for skipped in self.skipped
        )
        dispositioned = self.schema_scanned_file_count + self.skipped_file_count
        coverage_bp = (
            10_000
            if self.candidate_file_count == 0
            else (
                dispositioned * 10_000 + self.candidate_file_count // 2
            )
            // self.candidate_file_count
        )
        return {
            "schema_version": "ml-file-field-inventory.v1",
            "generated_at": self.generated_at,
            "summary": {
                "candidate_file_count": self.candidate_file_count,
                "schema_scanned_file_count": self.schema_scanned_file_count,
                "skipped_file_count": self.skipped_file_count,
                "dispositioned_file_count": dispositioned,
                "undispositioned_file_count": 0,
                "disposition_coverage_bp": coverage_bp,
                "source_schema_count": len(self.sources),
                "source_field_count": len(self.fields),
                "field_status_counts": dict(sorted(status_counts.items())),
                "skipped_reason_counts": dict(sorted(skipped_reason_counts.items())),
                "unsupported_extension_counts": dict(
                    self.unsupported_extension_counts
                ),
            },
            "sources": [asdict(source) for source in self.sources],
            "fields": [asdict(field) for field in self.fields],
            "skipped": [asdict(skipped) for skipped in self.skipped],
            "safety": {
                "sqlite_inspected": False,
                "data_root_source_write_allowed": False,
                "artifact_write_scope": "caller_selected_output_directory_only",
                "csv_data_rows_read": False,
                "json_reads_bounded": True,
                "unknown_fields_fail_closed": True,
                "unreviewed_training_allowed": False,
                "legacy_pickle_training_allowed": False,
                "prediction_replay_outcome_training_allowed": False,
                "absolute_paths_persisted": False,
            },
            "inventory_hash": self.inventory_hash,
        }


@dataclass(frozen=True)
class _SchemaField:
    name: str
    dtype: str
    dtype_basis: str


@dataclass(frozen=True)
class _SchemaReadResult:
    fields: tuple[_SchemaField, ...]
    bounded_evidence_hash: str
    quality_suffix: str


@dataclass(frozen=True)
class _PathPolicy:
    default_status: FileEligibilityStatus
    reason_code: str
    license_policy: str
    quality_policy: str
    scan_schema: bool = True


@dataclass
class _SourceAccumulator:
    path_pattern: str
    file_format: str
    fields: tuple[_SchemaField, ...]
    policy: _PathPolicy
    pit_fields: PITAvailabilityFields
    file_count: int
    representative_relative_path: str
    bounded_evidence_hash: str
    quality_suffix: str


@dataclass
class _SkipAccumulator:
    path_pattern: str
    object_kind: Literal["file", "directory"]
    eligibility_status: FileEligibilityStatus
    reason_code: str
    file_count: int = 0


def inspect_ml_file_fields(
    data_root: Path,
    *,
    max_csv_header_bytes: int = 256 * 1024,
    max_json_bytes: int = 256 * 1024,
    max_jsonl_lines: int = 5,
    max_json_fields: int = 512,
    max_output_detail_bytes: int = 1024 * 1024,
    clock: Callable[[], datetime] | None = None,
) -> FileFieldInventory:
    """唯讀掃描 ``DATA_ROOT``，回傳去重後的欄位 inventory。

    ``candidate_file_count`` 僅計入 CSV/JSON/JSONL 與需明確隔離的 pickle；
    其他副檔名會依副檔名計數，但不宣稱已解析其 schema。
    """

    root = data_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"DATA_ROOT not found: {root}")
    for name, value in (
        ("max_csv_header_bytes", max_csv_header_bytes),
        ("max_json_bytes", max_json_bytes),
        ("max_jsonl_lines", max_jsonl_lines),
        ("max_json_fields", max_json_fields),
        ("max_output_detail_bytes", max_output_detail_bytes),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")

    source_groups: dict[
        tuple[
            str,
            str,
            tuple[tuple[str, str, str], ...],
            FileEligibilityStatus,
            str,
        ],
        _SourceAccumulator,
    ] = {}
    skipped_groups: dict[
        tuple[str, Literal["file", "directory"], FileEligibilityStatus, str],
        _SkipAccumulator,
    ] = {}
    unsupported_extensions: Counter[str] = Counter()
    candidate_file_count = 0
    schema_scanned_file_count = 0
    skipped_file_count = 0

    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(
                os.scandir(directory),
                key=lambda entry: entry.name.casefold(),
                reverse=True,
            )
        except OSError:
            relative = _relative_path(directory, root)
            _add_skipped(
                skipped_groups,
                path_pattern=_generalize_relative_path(relative),
                object_kind="directory",
                eligibility_status="unreviewed",
                reason_code="directory_read_error_fail_closed",
                file_count=0,
            )
            continue
        for entry in entries:
            path = Path(entry.path)
            if entry.is_symlink():
                relative = _relative_path(path, root)
                _add_skipped(
                    skipped_groups,
                    path_pattern=_generalize_relative_path(relative),
                    object_kind="file" if entry.is_file() else "directory",
                    eligibility_status="unreviewed",
                    reason_code="symlink_not_followed",
                    file_count=0,
                )
                continue
            if entry.is_dir(follow_symlinks=False):
                if _skip_directory(entry.name):
                    relative = _relative_path(path, root)
                    _add_skipped(
                        skipped_groups,
                        path_pattern=_generalize_relative_path(relative) + "/**",
                        object_kind="directory",
                        eligibility_status="research_shadow",
                        reason_code="excluded_backup_temp_log_or_test_scope",
                        file_count=0,
                    )
                else:
                    stack.append(path)
                continue
            if not entry.is_file(follow_symlinks=False):
                continue

            suffix = path.suffix.casefold()
            if path.name.casefold() == "ml_file_field_inventory.json":
                relative = _relative_path(path, root)
                _add_skipped(
                    skipped_groups,
                    path_pattern=_generalize_relative_path(relative),
                    object_kind="file",
                    eligibility_status="research_shadow",
                    reason_code="inventory_self_artifact_outside_discovery_scope",
                    file_count=0,
                )
                continue
            if suffix not in _SCANNED_SUFFIXES | _EXPLICIT_BINARY_SUFFIXES:
                unsupported_extensions[suffix or "<none>"] += 1
                continue
            candidate_file_count += 1
            relative = _relative_path(path, root)
            path_pattern = _generalize_relative_path(relative)
            policy = _policy_for(relative, path, max_output_detail_bytes)

            if suffix in _EXPLICIT_BINARY_SUFFIXES:
                _add_skipped(
                    skipped_groups,
                    path_pattern=path_pattern,
                    object_kind="file",
                    eligibility_status="excluded_leakage",
                    reason_code="legacy_pickle_or_model_binary_excluded",
                    file_count=1,
                )
                skipped_file_count += 1
                continue
            if not policy.scan_schema:
                _add_skipped(
                    skipped_groups,
                    path_pattern=path_pattern,
                    object_kind="file",
                    eligibility_status=policy.default_status,
                    reason_code=policy.reason_code,
                    file_count=1,
                )
                skipped_file_count += 1
                continue

            try:
                if suffix == ".csv":
                    schema = _read_csv_schema(
                        path, max_header_bytes=max_csv_header_bytes
                    )
                elif suffix == ".json":
                    schema = _read_json_schema(
                        path,
                        max_bytes=max_json_bytes,
                        max_fields=max_json_fields,
                    )
                else:
                    schema = _read_jsonl_schema(
                        path,
                        max_bytes=max_json_bytes,
                        max_lines=max_jsonl_lines,
                        max_fields=max_json_fields,
                    )
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
                _add_skipped(
                    skipped_groups,
                    path_pattern=path_pattern,
                    object_kind="file",
                    eligibility_status=policy.default_status,
                    reason_code=_schema_error_reason(error),
                    file_count=1,
                )
                skipped_file_count += 1
                continue

            pit_fields = _detect_pit_fields(
                tuple(field.name for field in schema.fields),
                path_pattern=path_pattern,
            )
            schema_signature = tuple(
                (field.name, field.dtype, field.dtype_basis)
                for field in schema.fields
            )
            group_key = (
                path_pattern,
                suffix.removeprefix("."),
                schema_signature,
                policy.default_status,
                policy.reason_code,
            )
            accumulator = source_groups.get(group_key)
            if accumulator is None:
                source_groups[group_key] = _SourceAccumulator(
                    path_pattern=path_pattern,
                    file_format=suffix.removeprefix("."),
                    fields=schema.fields,
                    policy=policy,
                    pit_fields=pit_fields,
                    file_count=1,
                    representative_relative_path=relative,
                    bounded_evidence_hash=schema.bounded_evidence_hash,
                    quality_suffix=schema.quality_suffix,
                )
            else:
                accumulator.file_count += 1
                if relative < accumulator.representative_relative_path:
                    accumulator.representative_relative_path = relative
                    accumulator.bounded_evidence_hash = schema.bounded_evidence_hash
            schema_scanned_file_count += 1

    sources: list[FileSourceSchemaRecord] = []
    fields: list[FileFieldEligibilityRecord] = []
    for accumulator in sorted(
        source_groups.values(),
        key=lambda item: (
            item.path_pattern,
            item.file_format,
            tuple(field.name for field in item.fields),
        ),
    ):
        source_payload = {
            "path_pattern": accumulator.path_pattern,
            "file_format": accumulator.file_format,
            "schema": [
                {
                    "name": field.name,
                    "dtype": field.dtype,
                    "dtype_basis": field.dtype_basis,
                }
                for field in accumulator.fields
            ],
            "default_status": accumulator.policy.default_status,
            "reason_code": accumulator.policy.reason_code,
            "license_policy": accumulator.policy.license_policy,
        }
        source_hash = _sha256_canonical(source_payload)
        source_id = _source_id(
            accumulator.path_pattern,
            accumulator.file_format,
            source_hash,
        )
        quality_policy = (
            f"{accumulator.policy.quality_policy}; "
            f"{accumulator.quality_suffix}; "
            "bounded_evidence_hash="
            f"{accumulator.bounded_evidence_hash}"
        )
        sources.append(
            FileSourceSchemaRecord(
                source_id=source_id,
                path_pattern=accumulator.path_pattern,
                file_format=accumulator.file_format,
                file_count=accumulator.file_count,
                representative_relative_path=(
                    accumulator.representative_relative_path
                ),
                field_count=len(accumulator.fields),
                source_hash=source_hash,
                source_hash_scope="relative_path_pattern_and_bounded_schema",
                default_status=accumulator.policy.default_status,
                reason_code=accumulator.policy.reason_code,
                license_policy=accumulator.policy.license_policy,
                quality_policy=quality_policy,
            )
        )
        pit_field_names = accumulator.pit_fields.all_fields()
        for field in accumulator.fields:
            status, reason = _field_disposition(
                field.name,
                policy=accumulator.policy,
                pit_fields=pit_field_names,
            )
            fields.append(
                FileFieldEligibilityRecord(
                    source_field_id=f"{source_id}:{field.name}",
                    source_id=source_id,
                    field_name=field.name,
                    path_pattern=accumulator.path_pattern,
                    file_format=accumulator.file_format,
                    canonical_dtype=field.dtype,
                    dtype_basis=field.dtype_basis,
                    eligibility_status=status,
                    reason_code=reason,
                    pit_availability_fields=accumulator.pit_fields,
                    source_hash=source_hash,
                    source_hash_scope=(
                        "relative_path_pattern_and_bounded_schema"
                    ),
                    license_policy=accumulator.policy.license_policy,
                    quality_policy=quality_policy,
                )
            )

    sorted_sources = tuple(sorted(sources, key=lambda item: item.source_id))
    sorted_fields = tuple(
        sorted(fields, key=lambda item: item.source_field_id)
    )
    sorted_skipped = tuple(
        sorted(
            (
                SkippedFileScope(
                    path_pattern=item.path_pattern,
                    object_kind=item.object_kind,
                    file_count=item.file_count,
                    eligibility_status=item.eligibility_status,
                    reason_code=item.reason_code,
                )
                for item in skipped_groups.values()
            ),
            key=lambda item: (
                item.object_kind,
                item.path_pattern,
                item.reason_code,
            ),
        )
    )
    generated_at = (clock or (lambda: datetime.now(UTC)))().astimezone(
        UTC
    ).isoformat()
    hash_payload = {
        "sources": [asdict(source) for source in sorted_sources],
        "fields": [asdict(field) for field in sorted_fields],
        "skipped": [asdict(item) for item in sorted_skipped],
        "candidate_file_count": candidate_file_count,
        "schema_scanned_file_count": schema_scanned_file_count,
        "skipped_file_count": skipped_file_count,
        "unsupported_extension_counts": sorted(
            unsupported_extensions.items()
        ),
    }
    return FileFieldInventory(
        generated_at=generated_at,
        sources=sorted_sources,
        fields=sorted_fields,
        skipped=sorted_skipped,
        candidate_file_count=candidate_file_count,
        schema_scanned_file_count=schema_scanned_file_count,
        skipped_file_count=skipped_file_count,
        unsupported_extension_counts=tuple(
            sorted(unsupported_extensions.items())
        ),
        inventory_hash=_sha256_canonical(hash_payload),
    )


def _read_csv_schema(path: Path, *, max_header_bytes: int) -> _SchemaReadResult:
    with path.open("rb") as stream:
        bounded = stream.read(max_header_bytes + 1)
    newline_positions = [
        position
        for position in (bounded.find(b"\n"), bounded.find(b"\r"))
        if position >= 0
    ]
    if newline_positions:
        header_bytes = bounded[: min(newline_positions)]
    elif len(bounded) > max_header_bytes:
        raise ValueError("csv_header_exceeds_bound")
    else:
        header_bytes = bounded
    if not header_bytes.strip():
        raise ValueError("empty_csv_header")
    header_text = _decode_bounded_text(header_bytes)
    try:
        raw_names = next(csv.reader([header_text]))
    except (csv.Error, StopIteration) as error:
        raise ValueError("invalid_csv_header") from error
    names = _deduplicate_field_names(raw_names)
    if not names:
        raise ValueError("empty_csv_header")
    fields = tuple(
        _SchemaField(
            name=name,
            dtype="unknown",
            dtype_basis="csv_header_only",
        )
        for name in names
    )
    return _SchemaReadResult(
        fields=fields,
        bounded_evidence_hash=_sha256_bytes(header_bytes),
        quality_suffix="csv_header_only_no_data_rows_read",
    )


def _read_json_schema(
    path: Path,
    *,
    max_bytes: int,
    max_fields: int,
) -> _SchemaReadResult:
    with path.open("rb") as stream:
        bounded = stream.read(max_bytes + 1)
    truncated = len(bounded) > max_bytes
    bounded = bounded[:max_bytes]
    if not bounded.strip():
        raise ValueError("empty_json")
    text = _decode_bounded_text(bounded)
    typed_fields: dict[str, set[str]] = {}
    if not truncated:
        payload = json.loads(text, parse_float=Decimal)
        _collect_json_fields(
            payload,
            typed_fields,
            max_fields=max_fields,
        )
    else:
        _collect_lexical_json_fields(
            text,
            typed_fields,
            max_fields=max_fields,
        )
    fields = _schema_fields_from_types(
        typed_fields,
        dtype_basis=(
            "bounded_json_value_inference"
            if not truncated
            else "bounded_json_lexical_inference"
        ),
    )
    if not fields:
        raise ValueError("json_schema_not_available_within_bound")
    return _SchemaReadResult(
        fields=fields,
        bounded_evidence_hash=_sha256_bytes(bounded),
        quality_suffix=(
            "bounded_json_schema_truncated"
            if truncated
            else "bounded_json_schema_complete_small_file"
        ),
    )


def _read_jsonl_schema(
    path: Path,
    *,
    max_bytes: int,
    max_lines: int,
    max_fields: int,
) -> _SchemaReadResult:
    typed_fields: dict[str, set[str]] = {}
    evidence = bytearray()
    parsed_lines = 0
    with path.open("rb") as stream:
        while parsed_lines < max_lines and len(evidence) < max_bytes:
            remaining = max_bytes - len(evidence)
            raw_line = stream.readline(remaining + 1)
            if not raw_line:
                break
            if len(raw_line) > remaining:
                raw_line = raw_line[:remaining]
            evidence.extend(raw_line)
            if not raw_line.strip():
                continue
            payload = json.loads(
                _decode_bounded_text(raw_line),
                parse_float=Decimal,
            )
            _collect_jsonl_row_fields(
                payload,
                typed_fields,
                max_fields=max_fields,
            )
            parsed_lines += 1
    fields = _schema_fields_from_types(
        typed_fields,
        dtype_basis="bounded_jsonl_row_inference",
    )
    if not fields:
        raise ValueError("jsonl_schema_not_available_within_bound")
    return _SchemaReadResult(
        fields=fields,
        bounded_evidence_hash=_sha256_bytes(bytes(evidence)),
        quality_suffix=(
            f"bounded_jsonl_schema_first_{parsed_lines}_rows"
        ),
    )


def _collect_json_fields(
    payload: object,
    typed_fields: dict[str, set[str]],
    *,
    max_fields: int,
) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            _add_type(
                typed_fields,
                f"top.{key}",
                _json_dtype(value),
                max_fields=max_fields,
            )
            if isinstance(value, dict):
                for nested_key, nested_value in value.items():
                    _add_type(
                        typed_fields,
                        f"top.{key}.{nested_key}",
                        _json_dtype(nested_value),
                        max_fields=max_fields,
                    )
            elif isinstance(value, list):
                for row in value[:5]:
                    if isinstance(row, dict):
                        for row_key, row_value in row.items():
                            _add_type(
                                typed_fields,
                                f"row.{row_key}",
                                _json_dtype(row_value),
                                max_fields=max_fields,
                            )
    elif isinstance(payload, list):
        for row in payload[:5]:
            if isinstance(row, dict):
                for key, value in row.items():
                    _add_type(
                        typed_fields,
                        f"row.{key}",
                        _json_dtype(value),
                        max_fields=max_fields,
                    )
    else:
        _add_type(
            typed_fields,
            "top.$value",
            _json_dtype(payload),
            max_fields=max_fields,
        )


def _collect_jsonl_row_fields(
    payload: object,
    typed_fields: dict[str, set[str]],
    *,
    max_fields: int,
) -> None:
    if not isinstance(payload, dict):
        _add_type(
            typed_fields,
            "row.$value",
            _json_dtype(payload),
            max_fields=max_fields,
        )
        return
    for key, value in payload.items():
        _add_type(
            typed_fields,
            f"row.{key}",
            _json_dtype(value),
            max_fields=max_fields,
        )


def _collect_lexical_json_fields(
    text: str,
    typed_fields: dict[str, set[str]],
    *,
    max_fields: int,
) -> None:
    """從 truncated JSON prefix 辨識 object keys；不要求載入完整 JSON。"""

    stack: list[str] = []
    index = 0
    text_length = len(text)
    while index < text_length and len(typed_fields) < max_fields:
        character = text[index]
        if character in "[{":
            stack.append(character)
            index += 1
            continue
        if character in "]}":
            if stack:
                stack.pop()
            index += 1
            continue
        if character != '"':
            index += 1
            continue
        end = _json_string_end(text, index)
        if end is None:
            break
        cursor = end + 1
        while cursor < text_length and text[cursor].isspace():
            cursor += 1
        if cursor >= text_length or text[cursor] != ":":
            index = end + 1
            continue
        try:
            key = json.loads(text[index : end + 1])
        except json.JSONDecodeError:
            index = end + 1
            continue
        if not isinstance(key, str):
            index = end + 1
            continue
        value_start = cursor + 1
        while value_start < text_length and text[value_start].isspace():
            value_start += 1
        dtype = _lexical_json_dtype(text, value_start)
        if stack == ["{"]:
            field_name = f"top.{key}"
        elif stack and stack[-1] == "{":
            field_name = f"row.{key}"
        else:
            index = end + 1
            continue
        _add_type(
            typed_fields,
            field_name,
            dtype,
            max_fields=max_fields,
        )
        index = end + 1


def _json_string_end(text: str, start: int) -> int | None:
    escaped = False
    for index in range(start + 1, len(text)):
        character = text[index]
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character == '"':
            return index
    return None


def _lexical_json_dtype(text: str, start: int) -> str:
    if start >= len(text):
        return "unknown"
    character = text[start]
    if character == '"':
        return "text"
    if character == "{":
        return "object"
    if character == "[":
        return "array"
    if text.startswith(("true", "false"), start):
        return "boolean"
    if text.startswith("null", start):
        return "null"
    number_match = re.match(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", text[start:])
    if number_match:
        token = number_match.group(0)
        return "decimal" if any(mark in token for mark in ".eE") else "integer"
    return "unknown"


def _json_dtype(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, Decimal):
        return "decimal"
    if isinstance(value, str):
        return "text"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _schema_fields_from_types(
    typed_fields: Mapping[str, set[str]],
    *,
    dtype_basis: str,
) -> tuple[_SchemaField, ...]:
    result: list[_SchemaField] = []
    for field_name, types in sorted(typed_fields.items()):
        concrete = sorted(dtype for dtype in types if dtype != "null")
        if not concrete:
            dtype = "unknown"
        elif len(concrete) == 1:
            dtype = concrete[0]
        else:
            dtype = "mixed"
        result.append(
            _SchemaField(
                name=field_name,
                dtype=dtype,
                dtype_basis=dtype_basis,
            )
        )
    return tuple(result)


def _add_type(
    typed_fields: dict[str, set[str]],
    field_name: str,
    dtype: str,
    *,
    max_fields: int,
) -> None:
    normalized = field_name.strip()
    if not normalized:
        return
    if normalized not in typed_fields and len(typed_fields) >= max_fields:
        return
    typed_fields.setdefault(normalized, set()).add(dtype)


def _deduplicate_field_names(raw_names: Sequence[str]) -> tuple[str, ...]:
    counts: Counter[str] = Counter()
    result: list[str] = []
    for index, raw_name in enumerate(raw_names, start=1):
        base = raw_name.strip().lstrip("\ufeff") or f"__unnamed_column_{index}"
        counts[base] += 1
        result.append(
            base if counts[base] == 1 else f"{base}#{counts[base]}"
        )
    return tuple(result)


def _detect_pit_fields(
    field_names: Iterable[str],
    *,
    path_pattern: str,
) -> PITAvailabilityFields:
    discovered: dict[str, list[str]] = {
        field: [] for field in _TIME_CANDIDATES
    }
    for field_name in field_names:
        base_name = _base_field_name(field_name).casefold()
        for policy_field, candidates in _TIME_CANDIDATES.items():
            if base_name in candidates:
                discovered[policy_field].append(field_name)
    if "{date}" in path_pattern and not discovered["event_at"]:
        discovered["event_at"].append("path:{date}")
    if "{period}" in path_pattern and not discovered["event_at"]:
        discovered["event_at"].append("path:{period}")
    return PITAvailabilityFields(
        event_at=tuple(sorted(discovered["event_at"])),
        announced_at=tuple(sorted(discovered["announced_at"])),
        available_at=tuple(sorted(discovered["available_at"])),
        first_seen_at=tuple(sorted(discovered["first_seen_at"])),
        effective_at=tuple(sorted(discovered["effective_at"])),
        revision_id=tuple(sorted(discovered["revision_id"])),
    )


def _field_disposition(
    field_name: str,
    *,
    policy: _PathPolicy,
    pit_fields: frozenset[str],
) -> tuple[FileEligibilityStatus, str]:
    if policy.default_status == "excluded_leakage":
        return "excluded_leakage", policy.reason_code
    base_name = _base_field_name(field_name)
    lowered = base_name.casefold()
    if any(token in lowered for token in _LEAKAGE_FIELD_TOKENS):
        return "excluded_leakage", "future_label_or_output_field_excluded"
    if lowered in _IDENTIFIER_NAMES or lowered.endswith("_id"):
        return "excluded_identifier", "identifier_or_category_field_excluded"
    if field_name in pit_fields:
        return "availability_only", "pit_availability_or_revision_metadata"
    if policy.default_status == "blocked_no_provenance":
        return (
            "blocked_no_provenance",
            "source_snapshot_lacks_provable_publication_timeline",
        )
    if policy.default_status == "research_shadow":
        return "research_shadow", policy.reason_code
    return "unreviewed", "unknown_file_field_fail_closed"


def _policy_for(
    relative_path: str,
    path: Path,
    max_output_detail_bytes: int,
) -> _PathPolicy:
    parts = tuple(part.casefold() for part in Path(relative_path).parts)
    tokens = _path_tokens(relative_path)
    top = parts[0] if parts else ""
    if tokens & _LEAKAGE_PATH_TOKENS:
        return _PathPolicy(
            default_status="excluded_leakage",
            reason_code="prediction_model_replay_outcome_or_backtest_excluded",
            license_policy="legacy-or-generated-artifact-not-a-training-source",
            quality_policy="isolated_from_formal_training",
            scan_schema=False,
        )
    if top == "output":
        size = path.stat().st_size
        if size > max_output_detail_bytes or tokens & _OUTPUT_DETAIL_TOKENS:
            return _PathPolicy(
                default_status="research_shadow",
                reason_code="large_output_detail_isolated_without_schema_scan",
                license_policy="derived-output-not-a-formal-source",
                quality_policy="output_detail_isolated",
                scan_schema=False,
            )
        return _PathPolicy(
            default_status="research_shadow",
            reason_code="generated_output_sidecar_research_only",
            license_policy="derived-output-not-a-formal-source",
            quality_policy="bounded_sidecar_schema_only",
        )
    if top == "financial_data":
        return _PathPolicy(
            default_status="blocked_no_provenance",
            reason_code="financial_snapshot_missing_publication_revision_timeline",
            license_policy="source-license-and-publication-timeline-required",
            quality_policy="schema_only_publication_time_unverified",
        )
    if top == "broker_flow":
        return _PathPolicy(
            default_status="research_shadow",
            reason_code="broker_flow_license_and_publication_time_not_formal",
            license_policy="broker-source-license-acceptance-required",
            quality_policy="schema_only_broker_source_shadow",
        )
    if top in _RESEARCH_PATH_ROOTS:
        return _PathPolicy(
            default_status="research_shadow",
            reason_code="legacy_or_short_history_file_research_only",
            license_policy="source-specific-license-review-required",
            quality_policy="schema_only_research_artifact",
        )
    if top == "technical_analysis":
        return _PathPolicy(
            default_status="unreviewed",
            reason_code="derived_feature_file_requires_lineage_review",
            license_policy="derived-from-governed-price-source-required",
            quality_policy="csv_schema_only_transform_lineage_unverified",
        )
    if top in {"daily_price", "daily_price_tpex"}:
        return _PathPolicy(
            default_status="unreviewed",
            reason_code="raw_price_file_requires_source_registry_link",
            license_policy="source-registry:twse-tpex-required",
            quality_policy="csv_schema_only_values_not_read",
        )
    if top == "meta_data":
        return _PathPolicy(
            default_status="unreviewed",
            reason_code="metadata_file_requires_field_level_review",
            license_policy="source-specific-license-review-required",
            quality_policy="bounded_metadata_schema_only",
        )
    return _PathPolicy(
        default_status="unreviewed",
        reason_code="unknown_file_source_fail_closed",
        license_policy="unreviewed-source-license-fail-closed",
        quality_policy="bounded_schema_only_quality_unverified",
    )


def _path_tokens(relative_path: str) -> frozenset[str]:
    return frozenset(
        token
        for token in re.split(r"[^0-9A-Za-z\u4e00-\u9fff]+", relative_path.casefold())
        if token
    )


def _skip_directory(name: str) -> bool:
    lowered = name.casefold()
    return (
        lowered in _SKIPPED_DIRECTORY_NAMES
        or lowered.startswith("backup_")
        or lowered.startswith(".tmp")
        or lowered.endswith("_backup")
    )


def _generalize_relative_path(relative_path: str) -> str:
    parts = relative_path.replace("\\", "/").split("/")
    generalized = [_generalize_segment(part) for part in parts if part]
    return "/".join(generalized) or "."


def _generalize_segment(segment: str) -> str:
    value = segment
    value = re.sub(
        r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
        r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
        "{uuid}",
        value,
    )
    value = re.sub(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)", "{date}", value)
    value = re.sub(r"(?<!\d)(?:19|20)\d{6}(?!\d)", "{date}", value)
    value = re.sub(r"(?<!\d)(?:19|20)\d{4}(?!\d)", "{period}", value)
    value = re.sub(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{16,}(?![0-9A-Fa-f])", "{hash}", value)
    value = re.sub(r"(?<!\d)\d{4,7}(?!\d)", "{entity}", value)
    value = re.sub(r"(?<!\d)\d{6}(?!\d)", "{time_or_period}", value)
    return value


def _source_id(
    path_pattern: str,
    file_format: str,
    source_hash: str,
) -> str:
    top = path_pattern.split("/", 1)[0]
    readable = re.sub(r"[^0-9a-z]+", "_", top.casefold()).strip("_") or "root"
    return f"file.{readable}.{file_format}.{source_hash[-16:]}"


def _base_field_name(field_name: str) -> str:
    value = field_name.rsplit(".", 1)[-1]
    return value.removesuffix("[]").split("#", 1)[0].strip()


def _relative_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _decode_bounded_text(value: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp950", "big5"):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeError("unsupported_text_encoding")


def _schema_error_reason(error: BaseException) -> str:
    text = str(error)
    known_reasons = (
        "csv_header_exceeds_bound",
        "empty_csv_header",
        "invalid_csv_header",
        "empty_json",
        "json_schema_not_available_within_bound",
        "jsonl_schema_not_available_within_bound",
        "unsupported_text_encoding",
    )
    for reason in known_reasons:
        if reason in text:
            return reason
    if isinstance(error, json.JSONDecodeError):
        return "invalid_or_truncated_json_within_bound"
    if isinstance(error, UnicodeError):
        return "unsupported_text_encoding"
    if isinstance(error, OSError):
        return "file_read_error_fail_closed"
    return "schema_read_error_fail_closed"


def _add_skipped(
    groups: dict[
        tuple[str, Literal["file", "directory"], FileEligibilityStatus, str],
        _SkipAccumulator,
    ],
    *,
    path_pattern: str,
    object_kind: Literal["file", "directory"],
    eligibility_status: FileEligibilityStatus,
    reason_code: str,
    file_count: int,
) -> None:
    key = (path_pattern, object_kind, eligibility_status, reason_code)
    accumulator = groups.get(key)
    if accumulator is None:
        groups[key] = _SkipAccumulator(
            path_pattern=path_pattern,
            object_kind=object_kind,
            eligibility_status=eligibility_status,
            reason_code=reason_code,
            file_count=file_count,
        )
    else:
        accumulator.file_count += file_count


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _sha256_canonical(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _require_sha256(value: str, *, field_name: str) -> None:
    if re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field_name} must be sha256:<64 lowercase hex>")
