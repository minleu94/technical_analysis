"""將 MOPS 財報 research candidate 轉成明確單位的隔離 consumer rows。

此 adapter 不改動 ``StatementItemRecord`` 或正式 SQLite schema。它只接受
candidate 自己保存的 unit、scale、period semantics 與時間 lineage，並把
consumer 可讀的 Decimal 值與原始整數表示同時保留下來；缺任何語意欄位時
直接 fail-closed。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any, Mapping, Sequence

from data_module.fundamental_schema import apply_fundamental_schema
from data_module.fundamental_sqlite_provider import FundamentalSQLiteProvider


_TAIPEI_TIMEZONE = timezone(timedelta(hours=8))
_STATEMENT_TYPES = frozenset(
    {"balance_sheet", "income_statement", "cash_flows_statement"}
)
_REPORT_BASES = frozenset({"consolidated", "individual"})
_UNIT_SCALES = {"TWD": 1000, "TWD_per_share": 100}
_OFFICIAL_ITEM_CODE_RE = re.compile(r"[A-Z0-9]{2,8}\Z")
_SHA256_REFERENCE_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SOURCE_VERSION_REPORT_BASIS_RE = re.compile(
    r"(?:^|[-_.])(consolidated|individual)(?:$|[-_.])",
    re.IGNORECASE,
)
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DATA_ROOT = Path("D:/Min/Python/Project/FA_Data")
_ISOLATION_MARKER_SUFFIX = ".research-only.json"


@dataclass(frozen=True)
class MOPSStatementConsumerRow:
    """研究 adapter 的單位化 row，不代表正式資料表 row。"""

    stock_code: str
    market: str
    statement_type: str
    statement_scope: str
    report_basis: str
    period: str
    period_start: date | None
    period_end: date
    period_basis: str
    item_name: str
    item_code: str
    item_code_source: str
    official_item_name: str
    xbrl_concept: str | None
    item_indent_depth: int | None
    value: Decimal
    raw_value: str
    raw_integer_value: int
    value_unit: str
    value_scale: int
    announcement_event_timestamp: datetime
    numeric_available_at: datetime
    numeric_available_date: date
    available_date: date
    source_version: str
    content_hash: str
    numeric_source_row_sha256: str
    availability_event_sha256: str
    item_code_lineage_sha256: str


def load_mops_statement_candidate(
    candidate_path: Path,
    *,
    decision_date: date | None = None,
) -> tuple[MOPSStatementConsumerRow, ...]:
    """讀取單一隔離 candidate，必要時以 date-only 可得日篩選 rows。

    ``decision_date`` 只使用 candidate 的保守 ``available_date``；同日精確
    使用者應另行比較 row 上保留的 ``numeric_available_at``。
    """

    try:
        payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"unable to read MOPS statement candidate: {candidate_path}") from error
    if not isinstance(payload, Mapping):
        raise ValueError("MOPS statement candidate must be a JSON object")
    if payload.get("research_only") is not True:
        raise ValueError("MOPS statement candidate must remain research_only")
    if payload.get("formal_oos_allowed") is not False:
        raise ValueError("MOPS statement candidate cannot be formal OOS eligible")
    source_version = _required_text(payload, "source_version")
    candidate_report_basis = _resolve_report_basis(
        payload,
        source_version=source_version,
        label="MOPS statement candidate",
    )
    lineage = payload.get("lineage")
    if isinstance(lineage, Mapping):
        availability = lineage.get("availability_source")
        if isinstance(availability, Mapping):
            capture_mode = availability.get("capture_mode")
            evidence_status = availability.get("evidence_status")
            if (
                capture_mode == "previously_saved_official_response"
                and evidence_status != "verified_saved_response"
            ):
                raise ValueError(
                    "saved listing response without verified evidence is research-only and "
                    "cannot enter the consumer adapter"
                )
            if evidence_status == "verified_saved_response":
                evidence = availability.get("evidence")
                if not isinstance(evidence, Mapping) or not evidence.get("source_sha256"):
                    raise ValueError("verified listing evidence lineage is incomplete")
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("MOPS statement candidate rows must be a non-empty list")

    adapted: list[MOPSStatementConsumerRow] = []
    for row_index, raw_row in enumerate(raw_rows):
        if not isinstance(raw_row, Mapping):
            raise ValueError(f"MOPS statement candidate row {row_index} must be an object")
        row = _adapt_row(
            raw_row,
            source_version=source_version,
            row_index=row_index,
            candidate_report_basis=candidate_report_basis,
        )
        if decision_date is None or row.available_date <= decision_date:
            adapted.append(row)
    return tuple(adapted)


def _resolve_report_basis(
    payload: Mapping[str, Any],
    *,
    source_version: str,
    label: str,
) -> str:
    """解析候選／批次 row 的報表範圍，未知來源不得默認為合併。"""

    raw_value = payload.get("report_basis")
    if raw_value is not None:
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise ValueError(f"{label} report_basis is unsupported")
        normalized = raw_value.strip()
        if normalized not in _REPORT_BASES:
            raise ValueError(f"{label} report_basis is unsupported")
        return normalized

    matches = {
        match.group(1).lower()
        for match in _SOURCE_VERSION_REPORT_BASIS_RE.finditer(source_version.strip())
    }
    if len(matches) == 1:
        return next(iter(matches))
    raise ValueError(
        f"{label} report_basis is unknown and source_version does not establish it"
    )


def _adapt_row(
    row: Mapping[str, Any],
    *,
    source_version: str,
    row_index: int,
    candidate_report_basis: str = "consolidated",
) -> MOPSStatementConsumerRow:
    statement_type = _required_text(row, "statement_type")
    if statement_type not in _STATEMENT_TYPES:
        raise ValueError(f"unsupported statement_type at row {row_index}: {statement_type}")
    stock_code = _required_text(row, "stock_code")
    market = _required_text(row, "market")
    statement_scope = _required_text(row, "statement_scope")
    if statement_scope not in _REPORT_BASES:
        raise ValueError(f"unsupported statement_scope at row {row_index}: {statement_scope}")
    raw_report_basis = row.get("report_basis")
    if raw_report_basis is None or (isinstance(raw_report_basis, str) and not raw_report_basis.strip()):
        if statement_scope != "consolidated":
            raise ValueError(
                f"individual statement row must explicitly declare report_basis at row {row_index}"
            )
        report_basis = "consolidated"
    elif not isinstance(raw_report_basis, str) or raw_report_basis.strip() not in _REPORT_BASES:
        raise ValueError(f"unsupported report_basis at row {row_index}")
    else:
        report_basis = raw_report_basis.strip()
    if report_basis != statement_scope or report_basis != candidate_report_basis:
        raise ValueError(
            f"report_basis and statement_scope do not match candidate at row {row_index}"
        )
    period = _required_text(row, "period")
    period_basis = _required_text(row, "period_basis")
    period_start = _optional_date(row.get("period_start"), field="period_start")
    period_end = _required_date(row, "period_end")
    _validate_period_semantics(
        statement_type=statement_type,
        period_start=period_start,
        period_end=period_end,
        period_basis=period_basis,
    )

    raw_integer_value = row.get("value")
    if isinstance(raw_integer_value, bool) or not isinstance(raw_integer_value, int):
        raise ValueError(f"value must be an integer at row {row_index}")
    value_unit = _required_text(row, "value_unit")
    value_scale = row.get("value_scale")
    if isinstance(value_scale, bool) or not isinstance(value_scale, int):
        raise ValueError(f"value_scale must be an integer at row {row_index}")
    expected_scale = _UNIT_SCALES.get(value_unit)
    if expected_scale is None or value_scale != expected_scale:
        raise ValueError(
            f"unit/scale mismatch at row {row_index}: unit={value_unit}; scale={value_scale}"
        )
    if value_unit == "TWD_per_share":
        # EPS 的 cents/share 固定保留兩位小數，避免 790 被序列化成 7.9。
        consumer_value = (
            Decimal(raw_integer_value) / Decimal(value_scale)
        ).quantize(Decimal("0.01"))
    else:
        consumer_value = Decimal(raw_integer_value)

    announcement_event_timestamp = _required_timestamp(
        row, "announcement_event_timestamp"
    )
    numeric_available_at = _required_timestamp(row, "numeric_available_at")
    numeric_available_date = _required_date(row, "numeric_available_date")
    available_date = _required_date(row, "available_date")
    capture_local_date = numeric_available_at.astimezone(_TAIPEI_TIMEZONE).date()
    if numeric_available_date != capture_local_date + timedelta(days=1):
        raise ValueError(
            "numeric_available_date must be the next Taipei calendar date after capture"
        )
    if available_date != numeric_available_date:
        raise ValueError("available_date must preserve numeric_available_date")

    item_code = _required_text(row, "item_code")
    if _OFFICIAL_ITEM_CODE_RE.fullmatch(item_code) is None:
        raise ValueError(f"invalid official item_code at row {row_index}")
    item_code_source = _required_text(row, "item_code_source")
    if item_code_source != "mops.t164sb01.xbrl.row_code":
        raise ValueError(
            "item_code_source must be the official MOPS XBRL row-code source"
        )
    official_item_name = _required_text(row, "official_item_name")
    xbrl_concept_value = row.get("xbrl_concept")
    if xbrl_concept_value is not None and (
        not isinstance(xbrl_concept_value, str) or not xbrl_concept_value.strip()
    ):
        raise ValueError(f"xbrl_concept must be text or null at row {row_index}")
    item_indent_depth = row.get("item_indent")
    official_indent_depth = row.get("official_indent_depth")
    if isinstance(item_indent_depth, bool) or not isinstance(item_indent_depth, int):
        raise ValueError(f"item_indent must be an integer at row {row_index}")
    if isinstance(official_indent_depth, bool) or not isinstance(official_indent_depth, int):
        raise ValueError(f"official_indent_depth must be an integer at row {row_index}")
    item_code_lineage_sha256 = _required_text(row, "item_code_lineage_sha256")
    if _SHA256_REFERENCE_RE.fullmatch(item_code_lineage_sha256) is None:
        raise ValueError("item_code_lineage_sha256 must be a sha256 reference")

    return MOPSStatementConsumerRow(
        stock_code=stock_code,
        market=market,
        statement_type=statement_type,
        statement_scope=statement_scope,
        report_basis=report_basis,
        period=period,
        period_start=period_start,
        period_end=period_end,
        period_basis=period_basis,
        item_name=_required_text(row, "item_name"),
        item_code=item_code,
        item_code_source=item_code_source,
        official_item_name=official_item_name,
        xbrl_concept=(
            xbrl_concept_value.strip() if isinstance(xbrl_concept_value, str) else None
        ),
        item_indent_depth=item_indent_depth,
        value=consumer_value,
        raw_value=_required_text(row, "raw_value"),
        raw_integer_value=raw_integer_value,
        value_unit=value_unit,
        value_scale=value_scale,
        announcement_event_timestamp=announcement_event_timestamp,
        numeric_available_at=numeric_available_at,
        numeric_available_date=numeric_available_date,
        available_date=available_date,
        source_version=source_version,
        content_hash=_required_text(row, "content_hash"),
        numeric_source_row_sha256=_required_text(row, "numeric_source_row_sha256"),
        availability_event_sha256=_required_text(row, "availability_event_sha256"),
        item_code_lineage_sha256=item_code_lineage_sha256,
    )


def _validate_period_semantics(
    *,
    statement_type: str,
    period_start: date | None,
    period_end: date,
    period_basis: str,
) -> None:
    expected = {
        "balance_sheet": ("period_end_snapshot", None),
        "income_statement": ("quarter_single", True),
        "cash_flows_statement": ("year_to_date", True),
    }[statement_type]
    expected_basis, requires_start = expected
    if period_basis != expected_basis:
        raise ValueError(
            f"period_basis mismatch for {statement_type}: {period_basis} != {expected_basis}"
        )
    if requires_start is None and period_start is not None:
        raise ValueError("balance sheet period_start must be null")
    if requires_start is True and period_start is None:
        raise ValueError(f"{statement_type} period_start is required")
    if period_start is not None and period_start > period_end:
        raise ValueError("period_start cannot be after period_end")


def _required_text(row: Mapping[str, Any], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing {field}")
    return value.strip()


def _required_date(row: Mapping[str, Any], field: str) -> date:
    value = row.get(field)
    parsed = _optional_date(value, field=field, required=True)
    if parsed is None:
        raise ValueError(f"missing {field}")
    return parsed


def _optional_date(
    value: object,
    *,
    field: str,
    required: bool = False,
) -> date | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError(f"missing {field}")
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO date") from error


def _required_timestamp(row: Mapping[str, Any], field: str) -> datetime:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing {field}")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def _path_is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _configured_data_roots() -> tuple[Path, ...]:
    """取得與 TWStockConfig 相同的資料根目錄，且不建立任何目錄。"""
    configured = Path(os.environ.get("DATA_ROOT", str(_DEFAULT_DATA_ROOT))).expanduser()
    roots = [configured]
    if os.environ.get("PROFILE", "prod") == "test":
        roots.append(configured / "_test")
    resolved: list[Path] = []
    for root in roots:
        candidate = root.resolve(strict=False)
        if candidate not in resolved:
            resolved.append(candidate)
    return tuple(resolved)


def _isolated_database_path(db_path: Path) -> tuple[Path, Path]:
    """在建立目錄或 SQLite 連線前確認隔離資料庫的實際路徑。"""
    requested = Path(db_path).expanduser()
    if not requested.is_absolute():
        requested = Path.cwd() / requested
    if requested.exists() and requested.is_symlink():
        raise ValueError("isolated SQLite database must not be a symlink")
    resolved = requested.resolve(strict=False)
    protected_roots = _configured_data_roots()
    protected_paths = tuple(
        [*protected_roots]
        + [root / "sqlite" / "twstock.db" for root in protected_roots]
    )
    if any(_path_is_within(resolved, root) for root in protected_paths):
        raise ValueError(
            "isolated SQLite database must be outside DATA_ROOT and the formal database"
        )

    allowed_roots = (
        Path(tempfile.gettempdir()).resolve(strict=False),
        (_PROJECT_ROOT / "output").resolve(strict=False),
    )
    if not any(_path_is_within(resolved, root) for root in allowed_roots):
        raise ValueError(
            "isolated SQLite database must be under TEMP or the repository output root"
        )

    marker = resolved.with_name(resolved.name + _ISOLATION_MARKER_SUFFIX)
    if resolved.exists():
        if not resolved.is_file():
            raise ValueError("isolated SQLite database path must be a regular file")
        if not marker.is_file() or marker.is_symlink():
            raise ValueError(
                "existing SQLite database requires a research-only isolation marker"
            )
        try:
            marker_payload = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("research-only isolation marker is unreadable") from error
        if not isinstance(marker_payload, Mapping):
            raise ValueError("research-only isolation marker is malformed")
        marked_path = marker_payload.get("db_path")
        if not isinstance(marked_path, str) or Path(marked_path).expanduser().resolve() != resolved:
            raise ValueError("research-only isolation marker targets another database")
        if marker_payload.get("research_only") is not True:
            raise ValueError("research-only isolation marker must declare research_only=true")
        if marker_payload.get("formal_oos_allowed") is not False:
            raise ValueError("research-only isolation marker cannot allow formal OOS")
    elif marker.exists():
        raise ValueError("orphaned research-only isolation marker requires a new database path")
    return resolved, marker


def validate_research_output_path(
    path: Path,
    *,
    conflicts: Sequence[Path] = (),
    allow_existing: bool = False,
) -> Path:
    """在寫入 research evidence 前檢查路徑、alias、衝突與 create-only 規則。

    ``allow_existing`` 僅供可驗證既有 immutable 操作紀錄的 resume 入口使用；
    呼叫端仍須以內容 hash 驗證檔案，不能以此參數覆寫 evidence。
    """
    requested = Path(path).expanduser()
    if not requested.is_absolute():
        requested = Path.cwd() / requested
    if requested.exists() and requested.is_symlink():
        raise ValueError("research output must not be a symlink")
    resolved = requested.resolve(strict=False)
    protected_roots = _configured_data_roots()
    if any(_path_is_within(resolved, root) for root in protected_roots):
        raise ValueError("research output must be outside DATA_ROOT")
    allowed_roots = (
        Path(tempfile.gettempdir()).resolve(strict=False),
        (_PROJECT_ROOT / "output").resolve(strict=False),
    )
    if not any(_path_is_within(resolved, root) for root in allowed_roots):
        raise ValueError("research output must be under TEMP or the repository output root")
    resolved_conflicts = {
        Path(conflict).expanduser().resolve(strict=False) for conflict in conflicts
    }
    if resolved in resolved_conflicts:
        raise ValueError("research output must not overlap an input, database, or marker")
    if resolved.exists():
        if not allow_existing or not resolved.is_file() or resolved.is_symlink():
            raise ValueError("research evidence output must be a new file")
    return resolved


def _write_isolation_marker(marker: Path, db_path: Path) -> None:
    """為新隔離資料庫寫入不可省略的 research-only 標記。"""
    marker.write_text(
        json.dumps(
            {
                "schema_version": "v4-isolated-sqlite-marker.v1",
                "db_path": str(db_path),
                "research_only": True,
                "formal_oos_allowed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def materialize_mops_statement_candidates(
    candidate_paths: Sequence[Path],
    db_path: Path,
    *,
    decision_dates: Sequence[date],
) -> dict[str, Any]:
    """將已驗證候選寫入隔離 SQLite，並透過既有 provider 做讀取驗證。

    這條入口只接受官方 XBRL row code、單位與期間語意皆完整的 research
    candidate。資料表中的值與 consumer 相容，但 ``quality=degraded`` 且
    不會呼叫正式資料 writer；完整 raw lineage 放在同一個隔離 DB 的
    ``mops_statement_consumer_metadata`` sidecar。
    """
    if not candidate_paths:
        raise ValueError("at least one MOPS statement candidate is required")
    if any(not Path(path).is_file() for path in candidate_paths):
        missing = next(Path(path) for path in candidate_paths if not Path(path).is_file())
        raise FileNotFoundError(missing)
    if not decision_dates:
        raise ValueError("at least one provider decision date is required")

    normalized_paths = tuple(Path(path) for path in candidate_paths)
    candidate_hashes = {
        str(path): _sha256_file(path)
        for path in normalized_paths
    }
    all_rows: list[tuple[MOPSStatementConsumerRow, Path]] = []
    for path in normalized_paths:
        all_rows.extend(
            (row, path) for row in load_mops_statement_candidate(path)
        )
    if not all_rows:
        raise ValueError("MOPS statement candidates contain no rows")

    # 同一候選重試可去重；不同內容即使 item code 相同，也必須以內容 hash
    # 形成不同 source_version，保留修訂 lineage 供後續 gate 判斷。
    unique_rows: list[tuple[MOPSStatementConsumerRow, Path]] = []
    seen_identity: set[tuple[str, str, str, str, str]] = set()
    duplicate_input_count = 0
    for row, path in all_rows:
        identity = (
            row.stock_code,
            row.statement_type,
            row.period,
            row.item_code,
            row.content_hash,
        )
        if identity in seen_identity:
            duplicate_input_count += 1
            continue
        seen_identity.add(identity)
        unique_rows.append((row, path))

    db_path, isolation_marker = _isolated_database_path(Path(db_path))
    resolved_candidate_paths = {
        Path(path).expanduser().resolve(strict=False) for path in normalized_paths
    }
    if db_path in resolved_candidate_paths or isolation_marker in resolved_candidate_paths:
        raise ValueError("isolated database and candidate input paths must be distinct")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if not db_path.exists():
        _write_isolation_marker(isolation_marker, db_path)
    inserted_count = 0
    existing_count = 0
    sidecar_table = "mops_statement_consumer_metadata"
    connection = sqlite3.connect(db_path)
    try:
        apply_fundamental_schema(connection)
        connection.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS {sidecar_table} (
                stock_code TEXT NOT NULL,
                statement_type TEXT NOT NULL,
                report_basis TEXT NOT NULL,
                period TEXT NOT NULL,
                item_code TEXT NOT NULL,
                materialized_source_version TEXT NOT NULL,
                candidate_source_version TEXT NOT NULL,
                item_name TEXT NOT NULL,
                official_item_name TEXT NOT NULL,
                item_code_source TEXT NOT NULL,
                xbrl_concept TEXT,
                item_indent_depth INTEGER NOT NULL,
                period_start TEXT,
                period_end TEXT NOT NULL,
                period_basis TEXT NOT NULL,
                value TEXT NOT NULL,
                raw_value TEXT NOT NULL,
                raw_integer_value INTEGER NOT NULL,
                value_unit TEXT NOT NULL,
                value_scale INTEGER NOT NULL,
                announcement_event_timestamp TEXT NOT NULL,
                numeric_available_at TEXT NOT NULL,
                numeric_available_date TEXT NOT NULL,
                available_date TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                item_code_lineage_sha256 TEXT NOT NULL,
                numeric_source_row_sha256 TEXT NOT NULL,
                availability_event_sha256 TEXT NOT NULL,
                candidate_path TEXT NOT NULL,
                candidate_sha256 TEXT NOT NULL,
                PRIMARY KEY (
                    stock_code,
                    statement_type,
                    period,
                    item_code,
                    materialized_source_version
                )
            );
            """
        )
        sidecar_columns = {
            str(info[1])
            for info in connection.execute(f"PRAGMA table_info({sidecar_table})").fetchall()
        }
        if "report_basis" not in sidecar_columns:
            # 舊隔離 DB 只補欄位，保留既有 immutable rows 與 source version。
            connection.execute(
                f"ALTER TABLE {sidecar_table} ADD COLUMN report_basis TEXT NOT NULL DEFAULT 'consolidated'"
            )
        for row, candidate_path in unique_rows:
            materialized_source_version = (
                f"{row.source_version}:content:{row.content_hash}"
            )
            announced_date = row.announcement_event_timestamp.astimezone(
                _TAIPEI_TIMEZONE
            ).date()
            db_key = (
                row.stock_code,
                row.statement_type,
                row.period,
                row.item_code,
                materialized_source_version,
            )
            existing = connection.execute(
                """
                SELECT item_name, value, announced_date, available_date,
                       source, quality
                FROM fundamental_statement_items
                WHERE stock_code = ? AND statement_type = ? AND period = ?
                  AND item_code = ? AND source_version = ?
                """,
                db_key,
            ).fetchone()
            expected_db_row = (
                row.item_name,
                str(row.value),
                announced_date.isoformat(),
                row.available_date.isoformat(),
                "mops.financial_statement.raw",
                "degraded",
            )
            if existing is not None:
                if tuple(existing) != expected_db_row:
                    raise ValueError(
                        "isolated SQLite identity collision for statement row; "
                        f"key={db_key}"
                    )
                existing_count += 1
            else:
                connection.execute(
                    """
                    INSERT INTO fundamental_statement_items (
                        stock_code, statement_type, period, as_of_date,
                        announced_date, available_date, item_code, item_name,
                        value, source, source_version, quality
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row.stock_code,
                        row.statement_type,
                        row.period,
                        row.period_end.isoformat(),
                        announced_date.isoformat(),
                        row.available_date.isoformat(),
                        row.item_code,
                        row.item_name,
                        str(row.value),
                        "mops.financial_statement.raw",
                        materialized_source_version,
                        "degraded",
                    ),
                )
                inserted_count += 1

            sidecar_key = db_key
            sidecar_existing = connection.execute(
                f"""
                SELECT item_name, value, content_hash, candidate_sha256, report_basis
                FROM {sidecar_table}
                WHERE stock_code = ? AND statement_type = ? AND period = ?
                  AND item_code = ? AND materialized_source_version = ?
                """,
                sidecar_key,
            ).fetchone()
            sidecar_expected = (
                row.item_name,
                str(row.value),
                row.content_hash,
                candidate_hashes[str(candidate_path)],
                row.report_basis,
            )
            if sidecar_existing is not None:
                if tuple(sidecar_existing) != sidecar_expected:
                    raise ValueError(
                        "isolated sidecar identity collision for statement row; "
                        f"key={sidecar_key}"
                    )
                continue
            connection.execute(
                f"""
                INSERT INTO {sidecar_table} (
                    stock_code, statement_type, period, item_code,
                    report_basis,
                    materialized_source_version, candidate_source_version,
                    item_name, official_item_name, item_code_source, xbrl_concept,
                    item_indent_depth, period_start, period_end, period_basis,
                    value, raw_value, raw_integer_value, value_unit, value_scale,
                    announcement_event_timestamp, numeric_available_at,
                    numeric_available_date, available_date, content_hash,
                    item_code_lineage_sha256, numeric_source_row_sha256,
                    availability_event_sha256, candidate_path, candidate_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.stock_code,
                    row.statement_type,
                    row.period,
                    row.item_code,
                    row.report_basis,
                    materialized_source_version,
                    row.source_version,
                    row.item_name,
                    row.official_item_name,
                    row.item_code_source,
                    row.xbrl_concept,
                    row.item_indent_depth,
                    row.period_start.isoformat() if row.period_start else None,
                    row.period_end.isoformat(),
                    row.period_basis,
                    str(row.value),
                    row.raw_value,
                    row.raw_integer_value,
                    row.value_unit,
                    row.value_scale,
                    row.announcement_event_timestamp.isoformat(),
                    row.numeric_available_at.isoformat(),
                    row.numeric_available_date.isoformat(),
                    row.available_date.isoformat(),
                    row.content_hash,
                    row.item_code_lineage_sha256,
                    row.numeric_source_row_sha256,
                    row.availability_event_sha256,
                    str(candidate_path),
                    candidate_hashes[str(candidate_path)],
                ),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    provider = FundamentalSQLiteProvider(db_path)
    stocks = tuple(sorted({row.stock_code for row, _ in unique_rows}))
    visible_by_date: dict[str, int] = {}
    visible_by_stock_date: dict[str, dict[str, int]] = {}
    for decision_date in decision_dates:
        date_key = decision_date.isoformat()
        per_stock: dict[str, int] = {}
        for stock_code in stocks:
            records = provider.load_statement_items(
                stock_code=stock_code,
                decision_date=decision_date,
            )
            per_stock[stock_code] = len(records)
        visible_by_stock_date[date_key] = per_stock
        visible_by_date[date_key] = sum(per_stock.values())

    verification_connection = sqlite3.connect(db_path)
    try:
        sidecar_count = int(
            verification_connection.execute(
                f"SELECT COUNT(*) FROM {sidecar_table}"
            ).fetchone()[0]
        )
        materialized_count = int(
            verification_connection.execute(
                "SELECT COUNT(*) FROM fundamental_statement_items"
            ).fetchone()[0]
        )
    finally:
        verification_connection.close()

    item_code_source_counts: dict[str, int] = {}
    for row, _ in unique_rows:
        item_code_source_counts[row.item_code_source] = (
            item_code_source_counts.get(row.item_code_source, 0) + 1
        )
    latest_decision_date = max(decision_dates)
    sample_codes = {"1100", "4000", "9750", "A00010"}
    provider_samples_by_stock: dict[str, list[dict[str, str]]] = {}
    for stock_code in stocks:
        provider_samples_by_stock[stock_code] = [
            {
                "item_code": record.item_code,
                "item_name": record.item_name,
                "statement_type": record.statement_type,
                "period": record.period,
                "value": str(record.value),
                "report_basis": record.report_basis,
                "available_date": record.available_date.isoformat(),
            }
            for record in provider.load_statement_items(
                stock_code=stock_code,
                decision_date=latest_decision_date,
            )
            if record.item_code in sample_codes
        ]
    return {
        "schema_version": "v4-quarterly-isolated-materialization-evidence.v1",
        "db_path": str(db_path),
        "isolation_marker": str(isolation_marker),
        "candidate_paths": [str(path) for path in normalized_paths],
        "candidate_sha256": candidate_hashes,
        "input_row_count": len(all_rows),
        "unique_input_row_count": len(unique_rows),
        "duplicate_input_row_count": duplicate_input_count,
        "inserted_row_count": inserted_count,
        "idempotent_existing_row_count": existing_count,
        "materialized_row_count": materialized_count,
        "sidecar_table": sidecar_table,
        "sidecar_row_count": sidecar_count,
        "item_code_source_counts": item_code_source_counts,
        "provider_visible_rows_by_decision_date": visible_by_date,
        "provider_visible_rows_by_stock_date": visible_by_stock_date,
        "provider_sample_values_by_stock": provider_samples_by_stock,
        "formal_db_written": False,
        "raw_data_modified": False,
        "date_only_policy": "next_taipei_calendar_day; same-day use requires numeric_available_at comparison",
    }


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"
