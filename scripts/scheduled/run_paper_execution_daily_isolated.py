"""執行固定 repository scope 的研究用 Paper EOD replay。

這個入口是唯一可由 ``baldr-paper-execution-eod-replay-daily`` 使用的
scheduled adapter。官方 recommendation 與行情 SQLite 固定從既有資料根目錄
以 ``mode=ro`` 讀取；盤前 adapter 先將 D 槽 Paper snapshot 以一致 backup
seed 到 repository state，EOD 只讀該 repository state。candidate、operational
receipt 與 append-only Paper ledger 固定寫入 repository 的隔離目錄。它不接受環境變數
覆寫路徑，也不把隔離 ledger 當成 Formal input。
官方 TWSE annual holidaySchedule cache 也固定從 operation root 讀取並逐次重驗
raw bytes、完整年度與 freshness；cache 不會改寫任何 D 或市場資料。
每輪另以 bounded 官方 newsList/newsDetail 探測臨時全面休市公告，將 list/detail
custody 綁定的 sidecar 寫入同一 operation root；公告清單或明細不可得時只回傳
observable discovery blocker，不把失敗視為休市或正式 credit。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import uuid


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.paper_daily_execution_producer import (  # noqa: E402
    PAPER_EXECUTION_PRODUCER_VERSION,
    PAPER_EXECUTION_SCHEMA_VERSION,
    TAIPEI,
    PaperExecutionPaths,
    persist_operational_receipt,
    run_paper_execution_daily_from_queue,
)
from data_module.official_trading_calendar import OfficialTradingCalendar  # noqa: E402
from data_module.official_trading_calendar_cache import (  # noqa: E402
    OfficialCalendarCacheError,
    refresh_twse_calendar_cache,
    refresh_twse_temporary_closure_events,
)
from scripts.scheduled.paper_portfolio_state_isolation import (  # noqa: E402
    verify_repo_state_seed,
)


DEFAULT_DATA_ROOT = Path(r"D:\Min\Python\Project\FA_Data")
OPERATIONAL_ROOT = ROOT / "output" / "paper_execution_eod_replay"
CANDIDATE_ROOT = OPERATIONAL_ROOT / "candidates"
RECEIPT_ROOT = OPERATIONAL_ROOT / "receipts"
LEDGER_DB = OPERATIONAL_ROOT / "paper_trade_ledger.sqlite"
SOURCE_STATE_DB = (
    DEFAULT_DATA_ROOT / "output" / "paper_portfolio" / "paper_portfolio.sqlite"
)
PAPER_STATE_ROOT = OPERATIONAL_ROOT / "paper_portfolio"
STATE_DB = PAPER_STATE_ROOT / "paper_portfolio.sqlite"
STATE_SEED_MANIFEST = PAPER_STATE_ROOT / "state_seed_manifest.json"
MARKET_DB = DEFAULT_DATA_ROOT / "sqlite" / "twstock.db"
RECOMMENDATION_ROOT = DEFAULT_DATA_ROOT / "output" / "recommendation" / "runs"
# v2 使用新檔名，保留先前 D state scope manifest 作為歷史證據，避免以
# 可變覆寫將舊 scope 靜默改成 repository state scope。
SCOPE_MANIFEST = OPERATIONAL_ROOT / "scope_manifest_v2.json"
SCOPE_SCHEMA_VERSION = "paper-execution-isolated-scope.v2"


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _file_signature(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {
        "size_bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def _resolved(value: Path) -> Path:
    return value.expanduser().resolve()


def _calendar_cache_root() -> Path:
    """回傳固定 repository output 下的官方日曆 cache 根目錄。"""

    return OPERATIONAL_ROOT / "calendar_cache"


def _refresh_calendar_cache(observed: datetime) -> dict[str, object]:
    """在已通過 scope 驗證後，最多重試兩次官方年度 cache。"""

    cache_root = _resolved(_calendar_cache_root())
    operation_root = _resolved(OPERATIONAL_ROOT)
    try:
        result = refresh_twse_calendar_cache(
            calendar_year=observed.astimezone(TAIPEI).year,
            cache_root=cache_root,
            allowed_root=operation_root,
            observed_at=observed,
        )
    except (OSError, RuntimeError, ValueError, OfficialCalendarCacheError) as error:
        return {
            "status": "refresh_blocked",
            "calendar_year": observed.astimezone(TAIPEI).year,
            "refresh_attempted": False,
            "network_attempts": 0,
            "reason": (
                "official_calendar_cache_refresh_scope_failed:"
                f"{type(error).__name__}:{error}"
            ),
        }
    return result


def _refresh_temporary_closure_events(observed: datetime) -> dict[str, object]:
    """在同一 operational run 以 bounded 官方公告清單更新臨時休市 sidecar。"""

    cache_root = _resolved(_calendar_cache_root())
    operation_root = _resolved(OPERATIONAL_ROOT)
    try:
        result = refresh_twse_temporary_closure_events(
            calendar_year=observed.astimezone(TAIPEI).year,
            cache_root=cache_root,
            allowed_root=operation_root,
            observed_at=observed,
        )
    except (OSError, RuntimeError, ValueError, OfficialCalendarCacheError) as error:
        return {
            "status": "temporary_closure_discovery_blocked",
            "calendar_year": observed.astimezone(TAIPEI).year,
            "network_attempts": 0,
            "detail_requests": 0,
            "reason": (
                "official_temporary_closure_refresh_scope_failed:"
                f"{type(error).__name__}:{error}"
            ),
            "events": [],
        }
    return result


def _write_calendar_refresh_receipt(
    result: Mapping[str, object],
    *,
    observed: datetime,
) -> Path:
    """保存每次 cache freshness／refresh 決定的 immutable operational receipt。"""

    receipt_root = _resolved(RECEIPT_ROOT)
    operation_root = _resolved(OPERATIONAL_ROOT)
    if not _is_under(receipt_root, operation_root) or receipt_root == operation_root:
        raise RuntimeError("calendar refresh receipt escaped operation root")
    receipt_root.mkdir(parents=True, exist_ok=True)
    body: dict[str, object] = {
        "schema_version": "twse-calendar-refresh-receipt.v1",
        "recorded_at": observed.astimezone(timezone.utc).isoformat(),
        "result": dict(result),
        "candidate_only": True,
        "formal_credit": False,
        "formal_clock_created": False,
        "market_db_written": False,
        "paper_ledger_written": False,
        "broker_order_allowed": False,
    }
    body["content_sha256"] = _payload_hash(body)
    stamp = observed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    for suffix in range(100):
        token = "" if suffix == 0 else f"_{suffix}"
        path = receipt_root / f"calendar_refresh_{stamp}{token}.json"
        try:
            with path.open("xb") as stream:
                stream.write((_canonical_json(body) + "\n").encode("utf-8"))
                stream.flush()
                import os

                os.fsync(stream.fileno())
        except FileExistsError:
            continue
        return path
    raise RuntimeError("calendar refresh receipt filename collision")


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _new_candidate_root() -> Path:
    """回傳 repository candidates 下的未建立 run 目錄。"""

    CANDIDATE_ROOT.mkdir(parents=True, exist_ok=True)
    for _ in range(20):
        run_root = CANDIDATE_ROOT / f"run_{uuid.uuid4().hex}"
        if not run_root.exists():
            return run_root
    raise RuntimeError("isolated Paper candidate run id collision")


def _expected_scope() -> dict[str, object]:
    return {
        "schema_version": SCOPE_SCHEMA_VERSION,
        "scope_id": "research-paper-eod-replay-repository-isolated-v1",
        "source": {
            "data_root": str(_resolved(DEFAULT_DATA_ROOT)),
            "recommendation_root": str(_resolved(RECOMMENDATION_ROOT)),
            "source_state_db": str(_resolved(SOURCE_STATE_DB)),
            "state_db": str(_resolved(STATE_DB)),
            "market_db": str(_resolved(MARKET_DB)),
            "state_read_mode": "sqlite_uri_mode_ro_and_query_only",
            "source_state_read_mode": "盤前 seed 專用；EOD 不回讀 D",
            "environment_path_overrides": "ignored",
        },
        "writable": {
            "repository_output_root": str(_resolved(ROOT / "output")),
            "operation_root": str(_resolved(OPERATIONAL_ROOT)),
            "candidate_root": str(_resolved(CANDIDATE_ROOT)),
            "receipt_root": str(_resolved(RECEIPT_ROOT)),
            "ledger_db": str(_resolved(LEDGER_DB)),
            "scope_manifest": str(_resolved(SCOPE_MANIFEST)),
            "ledger_mode": "append_only_research_paper_only",
        },
        "read_only": {
            "repository_state_db": str(_resolved(STATE_DB)),
            "state_seed_manifest": str(_resolved(STATE_SEED_MANIFEST)),
            "state_read_mode": "sqlite_uri_mode_ro_and_query_only",
        },
        "safety": {
            "research_only": True,
            "formal_credit": False,
            "writes_formal_controlled_paths": False,
            "writes_market_database": False,
            "broker_order_allowed": False,
            "broker_execution": False,
            "training_started": False,
            "historical_backfill_claimed": False,
            "clock_override": False,
        },
    }


def _validate_write_scope() -> dict[str, Path]:
    """確認所有 writer 目標仍在 repository output 且不在來源根目錄。"""

    repository_root = _resolved(ROOT)
    repository_output = _resolved(ROOT / "output")
    data_root = _resolved(DEFAULT_DATA_ROOT)
    operation = _resolved(OPERATIONAL_ROOT)
    candidate = _resolved(CANDIDATE_ROOT)
    receipt = _resolved(RECEIPT_ROOT)
    ledger = _resolved(LEDGER_DB)
    scope_manifest = _resolved(SCOPE_MANIFEST)
    state = _resolved(STATE_DB)
    state_root = _resolved(PAPER_STATE_ROOT)

    if not _is_under(repository_output, repository_root) or (
        repository_output == repository_root
    ):
        raise RuntimeError(
            "isolated Paper repository output root is outside repository"
        )
    if not _is_under(operation, repository_output) or operation == repository_output:
        raise RuntimeError(
            "isolated Paper operation root must be a repository output child"
        )

    for name, target in {
        "paper_state_root": state_root,
        "state_db": state,
        "state_seed_manifest": _resolved(STATE_SEED_MANIFEST),
    }.items():
        if not _is_under(target, operation):
            raise RuntimeError(
                f"isolated Paper repository state escaped operation root:{name}"
            )
        if not _is_under(target, repository_output) or _is_under(target, data_root):
            raise RuntimeError(
                f"isolated Paper repository state escaped repository scope:{name}"
            )

    write_targets = {
        "operation_root": operation,
        "candidate_root": candidate,
        "receipt_root": receipt,
        "ledger_db": ledger,
        "scope_manifest": scope_manifest,
    }
    for name, target in write_targets.items():
        if not _is_under(target, operation):
            raise RuntimeError(
                f"isolated Paper write target escaped operation root:{name}"
            )
        if not _is_under(target, repository_output):
            raise RuntimeError(
                f"isolated Paper write target escaped repository output:{name}"
            )
        if _is_under(target, data_root):
            raise RuntimeError(
                f"isolated Paper write target overlaps source data root:{name}"
            )
    return {
        "repository_output_root": repository_output,
        "data_root": data_root,
        "paper_state_root": state_root,
        "state_db": state,
        "state_seed_manifest": _resolved(STATE_SEED_MANIFEST),
        **write_targets,
    }


def _write_or_verify_scope_manifest() -> tuple[Path, str]:
    """建立或驗證固定 scope manifest；不建立空 ledger。"""

    _validate_write_scope()
    body = _expected_scope()
    payload = {**body, "content_sha256": _payload_hash(body)}
    encoded = (_canonical_json(payload) + "\n").encode("utf-8")
    SCOPE_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    if SCOPE_MANIFEST.exists():
        existing = json.loads(SCOPE_MANIFEST.read_text(encoding="utf-8"))
        if not isinstance(existing, Mapping):
            raise RuntimeError("isolated Paper scope manifest is not an object")
        existing_body = dict(existing)
        declared = existing_body.pop("content_sha256", None)
        if declared != _payload_hash(existing_body) or existing_body != body:
            raise RuntimeError("isolated Paper scope manifest changed")
    else:
        try:
            with SCOPE_MANIFEST.open("xb") as stream:
                stream.write(encoded)
                stream.flush()
                import os

                os.fsync(stream.fileno())
        except FileExistsError:
            existing = json.loads(SCOPE_MANIFEST.read_text(encoding="utf-8"))
            if not isinstance(existing, Mapping):
                raise RuntimeError("isolated Paper scope manifest is not an object")
            existing_body = dict(existing)
            declared = existing_body.pop("content_sha256", None)
            if declared != _payload_hash(existing_body) or existing_body != body:
                raise RuntimeError("isolated Paper scope manifest changed")
    return SCOPE_MANIFEST, _file_hash(SCOPE_MANIFEST)


def _sqlite_source_observation(
    path: Path,
    *,
    required_tables: set[str],
) -> dict[str, object]:
    """以 SQLite URI ``mode=ro`` 觀察來源，並確認讀取前後檔案 signature 不變。"""

    if path.expanduser().is_symlink():
        raise RuntimeError(f"isolated Paper source must not be a symlink:{path}")
    resolved = _resolved(path)
    if not resolved.is_file():
        raise RuntimeError(f"isolated Paper source is missing:{resolved}")
    before = _file_signature(resolved)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"file:{resolved.as_posix()}?mode=ro",
            uri=True,
        )
        connection.execute("PRAGMA query_only=ON")
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        missing = sorted(required_tables - tables)
        if missing:
            raise RuntimeError(
                f"isolated Paper source tables missing:{resolved}:{','.join(missing)}"
            )
    except sqlite3.Error as error:
        raise RuntimeError(
            f"isolated Paper source read failed:{resolved}:{type(error).__name__}"
        ) from error
    finally:
        if connection is not None:
            connection.close()
    after = _file_signature(resolved)
    if before != after:
        raise RuntimeError(f"isolated Paper source changed during read:{resolved}")
    return {
        "path": str(resolved),
        "mode": "ro/query_only",
        "file_signature": before,
        "required_tables": sorted(required_tables),
    }


def _scope_preflight() -> dict[str, object]:
    """驗證 source／target 路徑，且拒絕 D ledger 作為 writer target。"""

    write_scope = _validate_write_scope()
    candidate_root = write_scope["candidate_root"]
    receipt_root = write_scope["receipt_root"]
    ledger = write_scope["ledger_db"]
    state = _resolved(STATE_DB)
    market = _resolved(MARKET_DB)
    recommendation_root = _resolved(RECOMMENDATION_ROOT)
    calendar_cache_root = _resolved(_calendar_cache_root())
    if not _is_under(calendar_cache_root, _resolved(write_scope["operation_root"])):
        raise RuntimeError("isolated Paper calendar cache escaped operation root")
    if _is_under(calendar_cache_root, _resolved(DEFAULT_DATA_ROOT)):
        raise RuntimeError("isolated Paper calendar cache overlaps source data root")
    if calendar_cache_root.exists() and not calendar_cache_root.is_dir():
        raise RuntimeError("isolated Paper calendar cache root is not a directory")
    if ledger == _resolved(
        DEFAULT_DATA_ROOT / "output" / "paper_portfolio" / "paper_trade_ledger.sqlite"
    ):
        raise RuntimeError("isolated Paper ledger cannot target D source output")
    if ledger.exists() and not ledger.is_file():
        raise RuntimeError("isolated Paper ledger target is not a file")
    if not recommendation_root.is_dir():
        raise RuntimeError(f"isolated Paper recommendation root is missing:{recommendation_root}")
    state_seed = verify_repo_state_seed(
        target=state,
        manifest_path=_resolved(STATE_SEED_MANIFEST),
        source=_resolved(SOURCE_STATE_DB),
    )
    state_observation = _sqlite_source_observation(
        state,
        required_tables={"paper_portfolio_snapshots", "paper_portfolio_positions"},
    )
    market_observation = _sqlite_source_observation(
        market,
        required_tables={"daily_prices"},
    )
    cache_files: list[dict[str, object]] = []
    if calendar_cache_root.is_dir():
        for cache_file in sorted(calendar_cache_root.glob("*.json")):
            if not cache_file.is_file():
                raise RuntimeError(
                    f"isolated Paper calendar cache entry is not a file:{cache_file}"
                )
            resolved_cache_file = _resolved(cache_file)
            if not _is_under(resolved_cache_file, calendar_cache_root):
                raise RuntimeError(
                    f"isolated Paper calendar cache entry escaped root:{cache_file}"
                )
            if _is_under(resolved_cache_file, _resolved(DEFAULT_DATA_ROOT)):
                raise RuntimeError(
                    f"isolated Paper calendar cache entry overlaps source:{cache_file}"
                )
            cache_files.append(
                {
                    "path": str(resolved_cache_file),
                    "file_sha256": _file_hash(resolved_cache_file),
                }
            )
    return {
        "state": state_observation,
        "state_seed": state_seed,
        "market": market_observation,
        "recommendation_root": {
            "path": str(recommendation_root),
            "mode": "read_only_file_scan_by_queue_resolver",
        },
        "calendar_cache": {
            "path": str(calendar_cache_root),
            "mode": "hash_bound_official_annual_cache_read_only",
            "files": cache_files,
            "missing": not calendar_cache_root.exists(),
        },
        "ledger_target": {
            "path": str(ledger),
            "existing": ledger.is_file(),
            "mode": "append_only_research_paper_only",
        },
        "candidate_root": str(candidate_root),
        "receipt_root": str(receipt_root),
        "operation_root": str(write_scope["operation_root"]),
        "repository_output_root": str(write_scope["repository_output_root"]),
    }


def _paths() -> PaperExecutionPaths:
    return PaperExecutionPaths(
        recommendation_json=RECOMMENDATION_ROOT / "__queue_selection__.json",
        state_db=STATE_DB,
        market_db=MARKET_DB,
        output_root=_new_candidate_root(),
        ledger_db=LEDGER_DB,
        controlled_output_root=CANDIDATE_ROOT,
    )


def _write_scope_blocked_result(
    *,
    paths: PaperExecutionPaths,
    observed: datetime,
    blockers: list[str],
    scope_manifest_path: Path,
    scope_manifest_file_hash: str,
) -> dict[str, object]:
    """把 scope preflight 失敗保存為 candidate／receipt，維持可觀測性。"""

    output_root = paths.output_root
    output_root.mkdir(parents=True, exist_ok=False)
    body: dict[str, object] = {
        "schema_version": PAPER_EXECUTION_SCHEMA_VERSION,
        "producer": "scripts.scheduled.run_paper_execution_daily_isolated",
        "producer_version": PAPER_EXECUTION_PRODUCER_VERSION,
        "observed_at": observed.isoformat(),
        "status": "blocked",
        "blockers": blockers,
        "candidate_only": True,
        "formal_ready": False,
        "formal_consumer_compatible": False,
        "formal_credit": False,
        "research_only": True,
        "broker_order_allowed": False,
        "broker_execution": False,
        "writes_formal_controlled_paths": False,
        "writes_market_database": False,
        "training_started": False,
        "historical_backfill_claimed": False,
        "append_requested": True,
        "scope_manifest_path": str(scope_manifest_path),
        "scope_manifest_file_hash": scope_manifest_file_hash,
        "repository_state": {
            "path": str(_resolved(STATE_DB)),
            "read_mode": "sqlite_uri_mode_ro_and_query_only",
            "seed_manifest_path": str(_resolved(STATE_SEED_MANIFEST)),
        },
        "ledger": {
            "path": str(_resolved(LEDGER_DB)),
            "append_requested": True,
            "appended": False,
            "readback_verified": False,
        },
    }
    body["content_sha256"] = _payload_hash(body)
    candidate_path = output_root / "paper_execution_candidate.json"
    encoded = (_canonical_json(body) + "\n").encode("utf-8")
    with candidate_path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        import os

        os.fsync(stream.fileno())
    result = {
        **body,
        "candidate_path": str(candidate_path),
        "candidate_file_hash": _file_hash(candidate_path),
    }
    return persist_operational_receipt(
        result,
        RECEIPT_ROOT,
        observed=observed,
    )


def run_isolated() -> dict[str, object]:
    observed = datetime.now(timezone.utc)
    scope_manifest_path, scope_manifest_file_hash = _write_or_verify_scope_manifest()
    paths = _paths()
    try:
        source_observation = _scope_preflight()
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as error:
        return _write_scope_blocked_result(
            paths=paths,
            observed=observed,
            blockers=[f"isolated_scope_preflight_failed:{type(error).__name__}:{error}"],
            scope_manifest_path=scope_manifest_path,
            scope_manifest_file_hash=scope_manifest_file_hash,
        )
    calendar_refresh = _refresh_calendar_cache(observed)
    temporary_closure_refresh = _refresh_temporary_closure_events(observed)
    refresh_receipt_path = _write_calendar_refresh_receipt(
        {
            "annual_calendar": calendar_refresh,
            "temporary_closure_events": temporary_closure_refresh,
        },
        observed=observed,
    )
    source_observation["calendar_refresh"] = calendar_refresh
    source_observation["temporary_closure_refresh"] = temporary_closure_refresh
    source_observation["calendar_refresh_receipt"] = {
        "path": str(refresh_receipt_path),
        "file_sha256": _file_hash(refresh_receipt_path),
    }
    calendar = OfficialTradingCalendar(
        db_path=MARKET_DB,
        calendar_cache_path=_calendar_cache_root(),
        temporary_closure_path=_calendar_cache_root(),
    )
    result = run_paper_execution_daily_from_queue(
        paths,
        recommendation_root=RECOMMENDATION_ROOT,
        receipt_root=RECEIPT_ROOT,
        calendar=calendar,
        confirm_append=True,
    )
    return {
        **result,
        "isolated_scope": {
            "scope_manifest_path": str(scope_manifest_path),
            "scope_manifest_file_hash": scope_manifest_file_hash,
            "source_observation": source_observation,
            "append_target": str(_resolved(LEDGER_DB)),
            "append_target_is_d_source": False,
            "repository_state_db": str(_resolved(STATE_DB)),
            "source_state_db": str(_resolved(SOURCE_STATE_DB)),
            "repository_state_read_mode": "sqlite_uri_mode_ro_and_query_only",
            "environment_path_overrides_ignored": True,
            "formal_credit": False,
            "broker_execution": False,
            "writes_market_database": False,
        },
    }


def main() -> int:
    try:
        result = run_isolated()
    except Exception as error:  # noqa: BLE001 - scheduled boundary is fail-closed
        result = {
            "schema_version": SCOPE_SCHEMA_VERSION,
            "producer": "scripts.scheduled.run_paper_execution_daily_isolated",
            "status": "blocked",
            "blockers": [
                f"isolated_paper_execution_failed:{type(error).__name__}:{error}"
            ],
            "candidate_only": True,
            "formal_ready": False,
            "formal_credit": False,
            "broker_execution": False,
            "writes_market_database": False,
        }
    _print_json(result)
    return 0 if str(result.get("status")) in {
        "machine_verified_candidate",
        "no_trade_required_candidate",
        "skipped_non_trading_day",
        "skipped_no_pending_recommendation",
        "waiting_for_execution_session",
        "waiting_for_execution_source",
    } else 2


def _print_json(value: Mapping[str, object]) -> None:
    """在 Windows 非 UTF-8 console 仍輸出完整的中文 custody 結果。"""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    try:
        sys.stdout.write(encoded.decode())
    except UnicodeEncodeError:
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is None:
            sys.stdout.write(encoded.decode("utf-8"))
        else:
            buffer.write(encoded)
            buffer.flush()


if __name__ == "__main__":
    raise SystemExit(main())
