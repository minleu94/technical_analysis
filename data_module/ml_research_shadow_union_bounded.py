"""建立 33 檔 ResearchShadowUnion 的 bounded、可追溯研究切片。

這個入口只把既有 D SQLite 的指定股票與已核准來源表，以串流方式複製到
C repo 的隔離 SQLite staging，再交給既有 public PIT exporter、dataset
assembler 與 ``ResearchShadowUnionBuilder``。它不修改 D source，也不猜測
缺失的 report basis；目前無法證明的 ``fundamental_statement_items`` 會被
排除並寫入 lineage。

輸出永遠是 research-only。training/label maturity 和 available_at 由既有
public producer 決定，這個模組不把事後資料改寫成歷史可得資料。
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Callable, Mapping, Sequence
import uuid

from data_module.ml_pit_year_shard_exporter import (
    PITYearShardBuildRequest,
    PITYearShardExporter,
)
from data_module.ml_research_shadow_union import (
    ResearchShadowUnionBuilder,
    ResearchShadowUnionRequest,
)
from data_module.ml_storage_capacity import (
    BYTES_PER_GIB,
    CANONICAL_HEAVY_CHAIN_SAFETY_RESERVE_BYTES,
    MLStorageCapacityBudget,
    StorageCapacityError,
    acquire_heavy_chain_reservation,
    directory_size_bytes,
    heavy_chain_capacity_budget,
    preflight_capacity,
    release_heavy_chain_reservation,
)
from data_module.portfolio_ml_dataset_assembler import (
    PortfolioMLDatasetAssembler,
    PortfolioMLDatasetAssemblyRequest,
)
from ml_module.feature_eligibility import ALL_FIELD_SOURCE_TABLES


BOUNDED_UNION_SCHEMA_VERSION = "ml-research-shadow-union-bounded-run.v1"
SOURCE_LINEAGE_SCHEMA_VERSION = "ml-research-shadow-union-source-lineage.v1"
_EXCLUDED_SOURCE_TABLE = "fundamental_statement_items"
_SOURCE_TABLES = tuple(
    table for table in ALL_FIELD_SOURCE_TABLES if table != _EXCLUDED_SOURCE_TABLE
)
_STOCK_COLUMNS: Mapping[str, str] = {
    "daily_prices": "證券代號",
    "technical_indicators": "證券代號",
    "fundamental_monthly_revenues": "stock_code",
    "fundamental_valuation_metrics": "stock_code",
    "institutional_flows": "stock_code",
    "credit_transactions": "stock_code",
    "tdcc_shareholding": "stock_code",
    "broker_flows": "證券代號",
}


@dataclass(frozen=True)
class BoundedResearchShadowUnionRequest:
    """一輪 bounded raw→base→union 研究建置的固定 request。"""

    database_path: Path
    output_root: Path
    decision_at: str
    training_as_of: str
    benchmark_entity_id: str
    symbols: tuple[str, ...]
    history_start_date: str = "2014-01-01"
    years: tuple[int, ...] = ()
    corporate_action_manifest_path: Path | None = None
    sector_membership_path: Path | None = None
    formal_portfolio_ledger_path: Path | None = None
    formal_rule_champion_history_path: Path | None = None
    # bounded 研究切片可用較小的 expanding windows；這些值仍須滿足
    # assembler 的 purge/embargo 最低契約，且會寫入 request identity。
    minimum_train_dates: int = 20
    test_date_count: int = 10
    purge_trading_days: int = 60
    embargo_trading_days: int = 5
    batch_size: int = 2_048
    compression_level: int = 6
    persistent_new_bytes_budget: int = BYTES_PER_GIB
    temporary_peak_bytes_budget: int = BYTES_PER_GIB
    safety_reserve_bytes: int = CANONICAL_HEAVY_CHAIN_SAFETY_RESERVE_BYTES
    heavy_lock_path: Path | None = None

    def __post_init__(self) -> None:
        symbols = tuple(sorted({str(item).strip() for item in self.symbols if str(item).strip()}))
        if not symbols:
            raise ValueError("symbols must be non-empty")
        object.__setattr__(self, "symbols", symbols)
        years = tuple(sorted(set(int(item) for item in self.years)))
        if any(year < 1900 or year > 9999 for year in years):
            raise ValueError("years must be valid calendar years")
        object.__setattr__(self, "years", years)
        if not self.benchmark_entity_id.strip():
            raise ValueError("benchmark_entity_id is required")
        for field_name in (
            "minimum_train_dates",
            "test_date_count",
            "purge_trading_days",
            "embargo_trading_days",
            "batch_size",
            "compression_level",
            "persistent_new_bytes_budget",
            "temporary_peak_bytes_budget",
            "safety_reserve_bytes",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be integer")
            if value <= 0:
                raise ValueError(f"{field_name} must be positive")
        if self.purge_trading_days < 60:
            raise ValueError("purge_trading_days must be at least 60")
        if self.embargo_trading_days < 5:
            raise ValueError("embargo_trading_days must be at least 5")
        if self.compression_level > 9:
            raise ValueError("compression_level must be within 0..9")


def _canonical_json(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _sha256_json(payload: object) -> str:
    return _sha256_bytes(_canonical_json(payload))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    encoded = _canonical_json(payload) + b"\n"
    try:
        with temporary.open("wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _table_sql(connection: sqlite3.Connection, table: str) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    if row is None or not isinstance(row[0], str) or not row[0].strip():
        raise ValueError(f"source table is missing or has no schema: {table}")
    return str(row[0])


def _sqlite_sidecar_stats(database: Path) -> dict[str, dict[str, int] | None]:
    """讀取 main/WAL/SHM 狀態，避免只依賴 main mtime。"""

    result: dict[str, dict[str, int] | None] = {}
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{database}{suffix}")
        try:
            stat = path.stat()
        except FileNotFoundError:
            result[suffix or "main"] = None
        except OSError as exc:
            raise ValueError(
                f"cannot inspect SQLite source sidecar: {path}"
            ) from exc
        else:
            result[suffix or "main"] = {
                "size_bytes": int(stat.st_size),
                "mtime_ns": int(stat.st_mtime_ns),
            }
    return result


def _sqlite_content_sidecar_stats(
    database: Path,
) -> dict[str, dict[str, int] | None]:
    """只取代表 SQLite content 的 main/WAL 狀態。

    ``-shm`` 是讀取連線共享的索引檔；開啟另一個唯讀 reader 也可能更新
    其 mtime，不能把它當成 WAL commit 的 content identity。保留完整
    sidecar stats 作診斷，但 source identity/change check 只綁 main 與 WAL。
    """

    stats = _sqlite_sidecar_stats(database)
    return {key: stats[key] for key in ("main", "-wal")}


def _json_safe_value(value: object) -> object:
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    return value


def _row_digest_update(
    digest: Any,
    *,
    table: str,
    row: Sequence[object],
) -> None:
    digest.update(
        _canonical_json(
            {
                "table": table,
                "values": [_json_safe_value(value) for value in row],
            }
        )
    )


def _selected_row_digest(
    source: sqlite3.Connection,
    *,
    table: str,
    symbols: tuple[str, ...],
    batch_size: int,
) -> tuple[int, str]:
    stock_column = _STOCK_COLUMNS.get(table)
    if stock_column is None:
        cursor = source.execute(f'SELECT * FROM "{table}"')
    else:
        marks = ",".join("?" for _ in symbols)
        cursor = source.execute(
            f'SELECT * FROM "{table}" WHERE "{stock_column}" IN ({marks})',
            symbols,
        )
    digest = hashlib.sha256()
    row_count = 0
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        for row in rows:
            _row_digest_update(digest, table=table, row=row)
            row_count += 1
    cursor.close()
    return row_count, "sha256:" + digest.hexdigest()


def _copy_table(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    *,
    table: str,
    symbols: tuple[str, ...],
    batch_size: int,
    before_write: Callable[[str, int], None] | None = None,
    after_write: Callable[[str], None] | None = None,
) -> tuple[int, str]:
    target.execute(_table_sql(source, table))
    stock_column = _STOCK_COLUMNS.get(table)
    if stock_column is None:
        cursor = source.execute(f'SELECT * FROM "{table}"')
    else:
        marks = ",".join("?" for _ in symbols)
        cursor = source.execute(
            f'SELECT * FROM "{table}" WHERE "{stock_column}" IN ({marks})',
            symbols,
        )
    column_count = len(cursor.description or ())
    if column_count <= 0:
        raise ValueError(f"source table has no columns: {table}")
    insert_sql = (
        f'INSERT INTO "{table}" VALUES '
        f"({','.join('?' for _ in range(column_count))})"
    )
    row_count = 0
    digest = hashlib.sha256()
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        for row in rows:
            _row_digest_update(digest, table=table, row=row)
        estimated_bytes = sum(
            len(
                _canonical_json(
                    {
                        "table": table,
                        "values": [_json_safe_value(value) for value in row],
                    }
                )
            )
            for row in rows
        )
        if before_write is not None:
            before_write(table, estimated_bytes)
        target.executemany(insert_sql, rows)
        row_count += len(rows)
        if after_write is not None:
            after_write(table)
    cursor.close()
    target.commit()
    return row_count, "sha256:" + digest.hexdigest()


def _source_snapshot(
    *,
    database_path: Path,
    output_root: Path,
    symbols: tuple[str, ...],
    batch_size: int,
    budget: MLStorageCapacityBudget,
    baseline_bytes: int,
) -> tuple[Path, dict[str, Any]]:
    """以保留原 schema 的 bounded SQLite snapshot 複製 D source。"""

    database = database_path.resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    source_stat = database.stat()
    source_sidecars = _sqlite_sidecar_stats(database)
    source_content_sidecars = _sqlite_content_sidecar_stats(database)
    source = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    source.execute("PRAGMA query_only=ON")
    # 一輪 source snapshot 必須在同一 SQLite read transaction 內完成；否則
    # WAL commit 可能讓不同年度／table 來自不同版本。
    source.execute("BEGIN")
    data_version = int(source.execute("PRAGMA data_version").fetchone()[0])
    available_tables = {
        str(row[0])
        for row in source.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    missing = [table for table in _SOURCE_TABLES if table not in available_tables]
    included = tuple(table for table in _SOURCE_TABLES if table in available_tables)
    schema_hashes = {
        table: _sha256_bytes(_table_sql(source, table).encode("utf-8"))
        for table in included
    }
    identity = {
        "schema_version": SOURCE_LINEAGE_SCHEMA_VERSION,
        "source_path": str(database),
        "source_size_bytes": int(source_stat.st_size),
        "source_mtime_ns": int(source_stat.st_mtime_ns),
        # identity 只綁 main/WAL；完整 SHM 狀態留在 lineage diagnostic，
        # 避免唯讀 reader 自身更新 -shm mtime 造成同一 source 無法 reuse。
        "source_sidecar_stats": source_content_sidecars,
        "source_content_sidecar_stats": source_content_sidecars,
        "source_data_version": data_version,
        "symbols": list(symbols),
        "included_tables": list(included),
        "excluded_tables": {
            _EXCLUDED_SOURCE_TABLE: "report_basis_not_explicit_in_D_source"
        },
        "missing_tables": missing,
        "source_schema_hashes": schema_hashes,
    }
    identity_hash = _sha256_json(identity)
    source_dir = output_root / "source_snapshots"
    source_dir.mkdir(parents=True, exist_ok=True)
    target = source_dir / f"source-{identity_hash[7:23]}.sqlite"
    lineage_path = source_dir / f"source-{identity_hash[7:23]}.lineage.json"
    if target.exists() or lineage_path.exists():
        if not target.is_file() or not lineage_path.is_file():
            source.close()
            raise ValueError("incomplete existing source snapshot")
        existing = json.loads(lineage_path.read_text(encoding="utf-8"))
        if existing.get("identity_hash") != identity_hash:
            source.close()
            raise ValueError("source snapshot identity collision")
        expected_file_hash = existing.get("snapshot_file_hash")
        expected_size = existing.get("snapshot_size_bytes")
        if (
            not isinstance(expected_file_hash, str)
            or not isinstance(expected_size, int)
            or expected_size < 0
            or target.stat().st_size != expected_size
            or _file_sha256(target) != expected_file_hash
        ):
            source.close()
            raise ValueError("existing source snapshot content hash mismatch")
        selected_counts: dict[str, int] = {}
        existing_selected_hashes: dict[str, str] = {}
        for table in included:
            count, digest = _selected_row_digest(
                source,
                table=table,
                symbols=symbols,
                batch_size=batch_size,
            )
            selected_counts[table] = count
            existing_selected_hashes[table] = digest
        if (
            existing.get("copied_row_counts") != selected_counts
            or existing.get("selected_source_row_hashes")
            != existing_selected_hashes
        ):
            source.close()
            raise ValueError("existing source snapshot source rows changed")
        source.rollback()
        source.close()
        _capacity_checkpoint(
            output_root=output_root,
            baseline_bytes=baseline_bytes,
            budget=budget,
            temporary_path=None,
            stage="source_snapshot_reuse",
        )
        return target, existing

    temporary = source_dir / f".{target.name}.{uuid.uuid4().hex}.tmp"
    target_connection: sqlite3.Connection | None = None
    table_counts: dict[str, int] = {}
    selected_hashes: dict[str, str] = {}
    capacity_observations: list[dict[str, Any]] = []
    try:
        target_connection = sqlite3.connect(temporary)
        target_connection.execute("PRAGMA journal_mode=DELETE")
        target_connection.execute("PRAGMA synchronous=FULL")

        def before_write(table: str, estimated_bytes: int) -> None:
            capacity_observations.append(
                _capacity_checkpoint(
                    output_root=output_root,
                    baseline_bytes=baseline_bytes,
                    budget=budget,
                    temporary_path=temporary,
                    stage=f"source_snapshot_{table}_before_batch",
                    projected_bytes=estimated_bytes,
                )
            )

        def after_write(table: str) -> None:
            capacity_observations.append(
                _capacity_checkpoint(
                    output_root=output_root,
                    baseline_bytes=baseline_bytes,
                    budget=budget,
                    temporary_path=temporary,
                    stage=f"source_snapshot_{table}_after_batch",
                )
            )

        for table in included:
            table_counts[table], selected_hashes[table] = _copy_table(
                source,
                target_connection,
                table=table,
                symbols=symbols,
                batch_size=batch_size,
                before_write=before_write,
                after_write=after_write,
            )
        target_connection.commit()
        target_connection.close()
        target_connection = None
        source_stat_after = database.stat()
        source_sidecars_after = _sqlite_sidecar_stats(database)
        source_content_sidecars_after = _sqlite_content_sidecar_stats(database)
        data_version_after = int(
            source.execute("PRAGMA data_version").fetchone()[0]
        )
        if (
            source_stat.st_size,
            source_stat.st_mtime_ns,
            source_content_sidecars,
            data_version,
        ) != (
            source_stat_after.st_size,
            source_stat_after.st_mtime_ns,
            source_content_sidecars_after,
            data_version_after,
        ):
            raise RuntimeError("D SQLite source changed while copying")
        source.rollback()
        os.replace(temporary, target)
    finally:
        source.close()
        if target_connection is not None:
            target_connection.close()
        if temporary.exists():
            temporary.unlink()
    lineage = {
        **identity,
        "source_sidecar_diagnostic_stats": source_sidecars,
        "identity_hash": identity_hash,
        "snapshot_path": str(target),
        "snapshot_file_hash": _file_sha256(target),
        "snapshot_size_bytes": int(target.stat().st_size),
        "copied_row_counts": table_counts,
        "selected_source_row_hashes": selected_hashes,
        "read_only_source": True,
        "source_rows_rewritten": False,
        "available_at_rewritten": False,
        "historical_pit_backfill_claimed": False,
        "capacity_checkpoint_count": len(capacity_observations),
        "temporary_peak_bytes_observed": max(
            (
                int(item["temporary_bytes"])
                for item in capacity_observations
                if isinstance(item.get("temporary_bytes"), int)
            ),
            default=0,
        ),
        "excluded_table_reasons": {
            _EXCLUDED_SOURCE_TABLE: (
                "D source has no explicit report_basis; public exporter "
                "must fail closed rather than infer one"
            )
        },
    }
    _write_json(lineage_path, lineage)
    return target, lineage


def _output_size(output_root: Path) -> int:
    return directory_size_bytes(output_root)


def _capacity_checkpoint(
    *,
    output_root: Path,
    baseline_bytes: int,
    budget: MLStorageCapacityBudget,
    temporary_path: Path | None,
    stage: str,
    projected_bytes: int = 0,
) -> dict[str, Any]:
    """在每批 source 寫入前後檢查 aggregate bytes 與 filesystem headroom。"""

    if projected_bytes < 0:
        raise ValueError("projected_bytes must be non-negative")
    current_output = _output_size(output_root)
    temporary_bytes = (
        0
        if temporary_path is None
        else directory_size_bytes(temporary_path)
    )
    persistent_new_bytes = max(
        0,
        current_output - baseline_bytes + projected_bytes,
    )
    projected_temporary_bytes = temporary_bytes + projected_bytes
    persistent_budget = budget.persistent_new_bytes_budget
    temporary_budget = budget.temporary_peak_bytes_budget
    if (
        persistent_budget is not None
        and persistent_new_bytes > persistent_budget
    ):
        raise StorageCapacityError(
            f"bounded output persistent budget exceeded at {stage}",
            preflight={
                "stage": stage,
                "persistent_new_bytes": persistent_new_bytes,
                "persistent_new_bytes_budget": persistent_budget,
                "temporary_bytes": temporary_bytes,
            },
        )
    if (
        temporary_budget is not None
        and projected_temporary_bytes > temporary_budget
    ):
        raise StorageCapacityError(
            f"bounded output temporary budget exceeded at {stage}",
            preflight={
                "stage": stage,
                "temporary_bytes": projected_temporary_bytes,
                "temporary_peak_bytes_budget": temporary_budget,
                "persistent_new_bytes": persistent_new_bytes,
            },
        )
    result = preflight_capacity(
        probe_path=output_root,
        budget=budget,
        stage=stage,
        persistent_roots=(output_root,),
        persistent_new_bytes_estimate=persistent_new_bytes,
        temporary_roots=(temporary_path,) if temporary_path is not None else (),
        temporary_peak_bytes_observed=projected_temporary_bytes,
    )
    return {
        **result.as_dict(),
        "output_directory_bytes": current_output,
        "persistent_new_bytes": persistent_new_bytes,
        "temporary_bytes": temporary_bytes,
        "projected_temporary_bytes": projected_temporary_bytes,
    }


def _remaining_stage_budget(
    *,
    output_root: Path,
    baseline_bytes: int,
    budget: MLStorageCapacityBudget,
    temporary_path: Path,
    stage: str,
) -> tuple[MLStorageCapacityBudget, dict[str, Any]]:
    """解析目前 chain 的剩餘 stage budget。

    每個 public producer 都只看自己的 output root；bounded wrapper 必須先
    扣掉同一輪已發布的 source/PIT bytes，否則三個 producer 各自取得 1 GiB
    會讓 aggregate output 超過本輪上限。
    """

    observed = _capacity_checkpoint(
        output_root=output_root,
        baseline_bytes=baseline_bytes,
        budget=budget,
        temporary_path=temporary_path,
        stage=stage,
    )
    persistent_limit = budget.persistent_new_bytes_budget
    temporary_limit = budget.temporary_peak_bytes_budget
    persistent_used = int(observed["persistent_new_bytes"])
    temporary_used = int(observed["temporary_bytes"])
    persistent_remaining = (
        None
        if persistent_limit is None
        else persistent_limit - persistent_used
    )
    temporary_remaining = (
        None
        if temporary_limit is None
        else temporary_limit - temporary_used
    )
    for name, value in (
        ("persistent", persistent_remaining),
        ("temporary", temporary_remaining),
    ):
        if value is not None and value <= 0:
            raise StorageCapacityError(
                f"bounded chain has no remaining {name} budget at {stage}",
                preflight={
                    **observed,
                    "stage": stage,
                    "persistent_remaining_bytes": persistent_remaining,
                    "temporary_remaining_bytes": temporary_remaining,
                },
            )
    return (
        MLStorageCapacityBudget(
            persistent_new_bytes_budget=persistent_remaining,
            temporary_peak_bytes_budget=temporary_remaining,
            safety_reserve_bytes=budget.safety_reserve_bytes,
        ),
        {
            **observed,
            "persistent_remaining_bytes": persistent_remaining,
            "temporary_remaining_bytes": temporary_remaining,
        },
    )


def _preflight(
    *,
    probe_path: Path,
    budget: MLStorageCapacityBudget,
    stage: str,
    persistent_estimate: int = 0,
) -> dict[str, Any]:
    result = preflight_capacity(
        probe_path=probe_path,
        budget=budget,
        stage=stage,
        persistent_new_bytes_estimate=persistent_estimate,
        temporary_peak_bytes_observed=0,
    )
    return result.as_dict()


def _check_output_budget(
    *,
    output_root: Path,
    baseline_bytes: int,
    budget: MLStorageCapacityBudget,
    stage: str,
) -> dict[str, Any]:
    current = _output_size(output_root)
    new_bytes = max(0, current - baseline_bytes)
    if (
        budget.persistent_new_bytes_budget is not None
        and new_bytes > budget.persistent_new_bytes_budget
    ):
        raise StorageCapacityError(
            f"bounded research output exceeded persistent budget at {stage}",
            preflight={
                "stage": stage,
                "persistent_new_bytes": new_bytes,
                "persistent_new_bytes_budget": budget.persistent_new_bytes_budget,
            },
        )
    return {
        "stage": stage,
        "output_directory_bytes": current,
        "persistent_new_bytes": new_bytes,
        "persistent_new_bytes_budget": budget.persistent_new_bytes_budget,
        "within_persistent_budget": True,
    }


def build_bounded_research_shadow_union(
    request: BoundedResearchShadowUnionRequest,
) -> dict[str, Any]:
    """執行受控 raw PIT→base assembly→ResearchShadowUnion public chain。"""

    database = request.database_path.resolve()
    output_root = request.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    budget = heavy_chain_capacity_budget(
        persistent_new_bytes_budget=request.persistent_new_bytes_budget,
        temporary_peak_bytes_budget=request.temporary_peak_bytes_budget,
        safety_reserve_bytes=request.safety_reserve_bytes,
    )
    lock_path = (
        request.heavy_lock_path.resolve()
        if request.heavy_lock_path is not None
        else output_root / ".ml_heavy_chain.lock"
    )
    reservation = acquire_heavy_chain_reservation(lock_path)
    if reservation is None:
        raise StorageCapacityError(
            "bounded research chain heavy lock is already held",
            preflight={
                "lock_path": str(lock_path),
                "blocker": "heavy_chain_reservation_unavailable",
            },
        )
    baseline_bytes = _output_size(output_root)
    preflights: list[dict[str, Any]] = []
    old_temp = os.environ.get("TEMP")
    old_tmp = os.environ.get("TMP")
    old_tempdir = tempfile.tempdir
    temp_root = output_root / ".tmp"
    try:
        temp_root.mkdir(parents=True, exist_ok=True)
        # D 只作 reserve/read-only probe；C output 另做初始 headroom probe。
        preflights.append(
            _preflight(
                probe_path=database,
                budget=budget,
                stage="bounded_d_source_preflight",
            )
        )
        preflights.append(
            _preflight(
                probe_path=output_root,
                budget=budget,
                stage="bounded_c_output_preflight",
            )
        )
        source_snapshot, source_lineage = _source_snapshot(
            database_path=database,
            output_root=output_root,
            symbols=request.symbols,
            batch_size=request.batch_size,
            budget=budget,
            baseline_bytes=baseline_bytes,
        )
        preflights.append(
            _capacity_checkpoint(
                output_root=output_root,
                baseline_bytes=baseline_bytes,
                budget=budget,
                temporary_path=temp_root,
                stage="source_snapshot_complete",
            )
        )

        os.environ["TEMP"] = str(temp_root)
        os.environ["TMP"] = str(temp_root)
        tempfile.tempdir = str(temp_root)

        pit_output = output_root / "pit"
        pit_budget, pit_preflight = _remaining_stage_budget(
            output_root=output_root,
            baseline_bytes=baseline_bytes,
            budget=budget,
            temporary_path=temp_root,
            stage="pit_stage_start",
        )
        preflights.append(pit_preflight)
        pit_publication = PITYearShardExporter().build(
            PITYearShardBuildRequest(
                database_path=source_snapshot,
                output_root=pit_output,
                decision_at=request.decision_at,
                history_start_date=request.history_start_date,
                symbols=request.symbols,
                years=request.years,
                batch_size=request.batch_size,
                compression_level=request.compression_level,
                temporary_storage_budget_bytes=(
                    pit_budget.temporary_peak_bytes_budget
                ),
                persistent_storage_budget_bytes=(
                    pit_budget.persistent_new_bytes_budget
                ),
                safety_reserve_bytes=pit_budget.safety_reserve_bytes,
            )
        )
        preflights.append(
            _capacity_checkpoint(
                output_root=output_root,
                baseline_bytes=baseline_bytes,
                budget=budget,
                temporary_path=temp_root,
                stage="pit_publication_complete",
            )
        )

        formal_manifest = pit_publication.dataset_manifest_paths[
            "all_field_enriched"
        ]
        shadow_manifest = pit_publication.dataset_manifest_paths[
            "research_shadow_all_fields"
        ]
        base_output = output_root / "base"
        # assembler 的 spool 在 bounded TEMP 內以 SQLite 累積；先以已發布
        # PIT bytes 的保守倍數做 stage preflight，再由 assembler callback
        # 在實際 shard/date 邊界重查，避免中途才發現整輪已超額。
        pit_directory_bytes = _output_size(pit_output)
        assembly_projected_temp = max(
            64 * 1024 * 1024,
            pit_directory_bytes * 5,
        )
        _, assembly_preflight = _remaining_stage_budget(
            output_root=output_root,
            baseline_bytes=baseline_bytes,
            budget=budget,
            temporary_path=temp_root,
            stage="base_stage_start",
        )
        assembly_preflight = _capacity_checkpoint(
            output_root=output_root,
            baseline_bytes=baseline_bytes,
            budget=budget,
            temporary_path=temp_root,
            stage="base_stage_projected_temp",
            projected_bytes=assembly_projected_temp,
        )
        assembly_preflight["projected_assembly_temp_bytes"] = (
            assembly_projected_temp
        )
        preflights.append(assembly_preflight)

        def assembly_capacity_checkpoint(stage: str) -> None:
            preflights.append(
                _capacity_checkpoint(
                    output_root=output_root,
                    baseline_bytes=baseline_bytes,
                    budget=budget,
                    temporary_path=temp_root,
                    stage=f"base_{stage}",
                )
            )

        base_publication = PortfolioMLDatasetAssembler().build(
            PortfolioMLDatasetAssemblyRequest(
                dataset_manifest_path=formal_manifest,
                output_root=base_output,
                training_as_of=request.training_as_of,
                benchmark_entity_id=request.benchmark_entity_id,
                sector_membership_path=request.sector_membership_path,
                corporate_action_manifest_path=request.corporate_action_manifest_path,
                formal_portfolio_ledger_path=request.formal_portfolio_ledger_path,
                formal_rule_champion_history_path=request.formal_rule_champion_history_path,
                years=request.years,
                minimum_train_dates=request.minimum_train_dates,
                test_date_count=request.test_date_count,
                purge_trading_days=request.purge_trading_days,
                embargo_trading_days=request.embargo_trading_days,
                batch_size=request.batch_size,
                compression_level=request.compression_level,
                capacity_callback=assembly_capacity_checkpoint,
            )
        )
        preflights.append(
            _capacity_checkpoint(
                output_root=output_root,
                baseline_bytes=baseline_bytes,
                budget=budget,
                temporary_path=temp_root,
                stage="base_assembly_complete",
            )
        )

        union_output = output_root / "union"
        _, union_preflight = _remaining_stage_budget(
            output_root=output_root,
            baseline_bytes=baseline_bytes,
            budget=budget,
            temporary_path=temp_root,
            stage="union_stage_start",
        )
        preflights.append(union_preflight)
        union_publication = ResearchShadowUnionBuilder().build(
            ResearchShadowUnionRequest(
                formal_raw_manifest_path=formal_manifest,
                shadow_raw_manifest_path=shadow_manifest,
                base_training_manifest_path=base_publication.manifest_path,
                output_root=union_output,
                corporate_action_manifest_path=request.corporate_action_manifest_path,
                symbols=request.symbols,
                years=request.years,
                batch_size=request.batch_size,
                compression_level=request.compression_level,
            )
        )
        preflights.append(
            _capacity_checkpoint(
                output_root=output_root,
                baseline_bytes=baseline_bytes,
                budget=budget,
                temporary_path=temp_root,
                stage="union_publication_complete",
            )
        )

        summary: dict[str, Any] = {
            "schema_version": BOUNDED_UNION_SCHEMA_VERSION,
            "status": "published_research_only",
            "research_only": True,
            "formal_oos_allowed": False,
            "production_alpha_bp": 0,
            "production_action_allowed": False,
            "promotion_eligible": False,
            "broker_order_allowed": False,
            "source_lineage": source_lineage,
            "request": {
                "database_path": str(database),
                "output_root": str(output_root),
                "decision_at": request.decision_at,
                "training_as_of": request.training_as_of,
                "benchmark_entity_id": request.benchmark_entity_id,
                "symbols": list(request.symbols),
                "history_start_date": request.history_start_date,
                "years": list(request.years),
                "sector_membership_path": (
                    None
                    if request.sector_membership_path is None
                    else str(request.sector_membership_path.resolve())
                ),
                "formal_portfolio_ledger_path": (
                    None
                    if request.formal_portfolio_ledger_path is None
                    else str(request.formal_portfolio_ledger_path.resolve())
                ),
                "formal_rule_champion_history_path": (
                    None
                    if request.formal_rule_champion_history_path is None
                    else str(
                        request.formal_rule_champion_history_path.resolve()
                    )
                ),
                "minimum_train_dates": request.minimum_train_dates,
                "test_date_count": request.test_date_count,
                "purge_trading_days": request.purge_trading_days,
                "embargo_trading_days": request.embargo_trading_days,
                "batch_size": request.batch_size,
                "compression_level": request.compression_level,
                "persistent_new_bytes_budget": (
                    request.persistent_new_bytes_budget
                ),
                "temporary_peak_bytes_budget": (
                    request.temporary_peak_bytes_budget
                ),
                "safety_reserve_bytes": request.safety_reserve_bytes,
                "heavy_lock_path": str(lock_path),
                "corporate_action_manifest_path": (
                    None
                    if request.corporate_action_manifest_path is None
                    else str(request.corporate_action_manifest_path.resolve())
                ),
            },
            "raw_pit": {
                "publication_id": pit_publication.publication_id,
                "publication_manifest_path": str(
                    pit_publication.manifest_path
                ),
                "publication_manifest_hash": pit_publication.manifest_hash,
                "all_field_manifest_path": str(formal_manifest),
                "shadow_manifest_path": str(shadow_manifest),
                "row_count": pit_publication.row_count,
                "shard_count": pit_publication.shard_count,
                "temporary_peak_bytes_observed": (
                    pit_publication.temporary_peak_bytes_observed
                ),
            },
            "base_assembly": {
                "publication_id": base_publication.publication_id,
                "manifest_path": str(base_publication.manifest_path),
                "manifest_hash": base_publication.manifest_hash,
                "sample_count": base_publication.sample_count,
                "fold_count": base_publication.fold_count,
            },
            "union": {
                "publication_id": union_publication.publication_id,
                "manifest_path": str(union_publication.manifest_path),
                "manifest_hash": union_publication.manifest_hash,
                "dataset_identity_hash": union_publication.dataset_identity_hash,
                "sample_count": union_publication.sample_count,
                "shard_paths": [str(path) for path in union_publication.shard_paths],
            },
            "capacity": {
                "budget": budget.as_dict(),
                # Detach the list from the live checkpoint accumulator.  The
                # final summary write itself is checked below and must not
                # mutate the payload after its summary hash is calculated.
                "preflights": list(preflights),
                "output_directory_bytes": _output_size(output_root),
                "persistent_new_bytes": max(
                    0, _output_size(output_root) - baseline_bytes
                ),
                "d_source_read_only": True,
                "summary_write_guard": {
                    "stage": "bounded_summary_before_write",
                    "checked": True,
                    "projected_bytes": 0,
                },
            },
            "date_semantics": {
                "decision_at": request.decision_at,
                "training_as_of": request.training_as_of,
                "available_at_rewritten": False,
                "historical_pit_backfill_claimed": False,
                "union_date_limit_is_base_assembly_maturity": True,
                "requested_years_are_bounded_research_scope": bool(
                    request.years
                ),
            },
        }
        # The final summary is also a persistent artifact.  Project its exact
        # encoded size (a SHA-256 placeholder has the same length as the real
        # summary hash) before the atomic write, so a run cannot cross the
        # persistent quota on its last metadata file.  Iterate only to account
        # for the decimal width of the stored projection itself.
        summary_projection = 0
        summary_hash_placeholder = "sha256:" + ("0" * 64)
        for _ in range(3):
            summary["capacity"]["summary_write_guard"]["projected_bytes"] = (
                summary_projection
            )
            candidate = dict(summary)
            candidate["summary_hash"] = summary_hash_placeholder
            next_projection = len(_canonical_json(candidate)) + 1
            if next_projection == summary_projection:
                break
            summary_projection = next_projection
        summary["capacity"]["summary_write_guard"]["projected_bytes"] = (
            summary_projection
        )
        _capacity_checkpoint(
            output_root=output_root,
            baseline_bytes=baseline_bytes,
            budget=budget,
            temporary_path=temp_root,
            stage="bounded_summary_before_write",
            projected_bytes=summary_projection,
        )
        summary_body = dict(summary)
        summary_body["summary_hash"] = _sha256_json(summary)
        _write_json(output_root / "bounded_run_summary.json", summary_body)
        _capacity_checkpoint(
            output_root=output_root,
            baseline_bytes=baseline_bytes,
            budget=budget,
            temporary_path=temp_root,
            stage="bounded_summary_complete",
        )
        return summary_body
    finally:
        if old_temp is None:
            os.environ.pop("TEMP", None)
        else:
            os.environ["TEMP"] = old_temp
        if old_tmp is None:
            os.environ.pop("TMP", None)
        else:
            os.environ["TMP"] = old_tmp
        tempfile.tempdir = old_tempdir
        release_heavy_chain_reservation(reservation)


__all__ = [
    "BOUNDED_UNION_SCHEMA_VERSION",
    "BoundedResearchShadowUnionRequest",
    "SOURCE_LINEAGE_SCHEMA_VERSION",
    "build_bounded_research_shadow_union",
]
