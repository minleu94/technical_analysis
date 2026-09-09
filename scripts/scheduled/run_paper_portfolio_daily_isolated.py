"""以 repository state 執行 Paper 盤前 snapshot producer。

這是 ``baldr-paper-portfolio-daily`` 的正式 scheduled adapter。D 槽既有
Paper snapshot 與 baseline 只以 SQLite ``mode=ro``／檔案 hash 作為來源；首次
執行會透過一致 backup 建立 repository copy，之後不再將 D snapshot 當 writer
target。盤前、EOD replay 與 Formal reader 共用
``output/paper_execution_eod_replay/paper_portfolio/paper_portfolio.sqlite``，
而市場 SQLite 仍只讀。所有這些結果都是 research／candidate scope，不會
產生正式信用、券商委託或歷史回填。
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from collections.abc import Callable
from datetime import datetime, time as datetime_time, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time as time_module


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.official_trading_calendar import OfficialTradingCalendar  # noqa: E402
from runtime.console_encoding import configure_utf8_console  # noqa: E402
from scripts.run_paper_portfolio_daily import (  # noqa: E402
    TAIPEI,
    _latest_reached_decision_at,
    run as run_paper_portfolio_daily,
)
from scripts.scheduled.paper_portfolio_state_isolation import (  # noqa: E402
    ensure_repo_state_from_readonly_source,
    publish_repo_state_head,
)


DEFAULT_DATA_ROOT = Path(r"D:\Min\Python\Project\FA_Data")
SOURCE_STATE_DB = (
    DEFAULT_DATA_ROOT / "output" / "paper_portfolio" / "paper_portfolio.sqlite"
)
SOURCE_BASELINE_PATH = (
    DEFAULT_DATA_ROOT / "output" / "paper_portfolio" / "baseline_20260712.json"
)
OPERATIONAL_ROOT = ROOT / "output" / "paper_execution_eod_replay"
PAPER_STATE_ROOT = OPERATIONAL_ROOT / "paper_portfolio"
STATE_DB = PAPER_STATE_ROOT / "paper_portfolio.sqlite"
STATE_SEED_MANIFEST = PAPER_STATE_ROOT / "state_seed_manifest.json"
MARKET_DB = DEFAULT_DATA_ROOT / "sqlite" / "twstock.db"
LEDGER_DB = OPERATIONAL_ROOT / "paper_trade_ledger.sqlite"
SCHEMA_VERSION = "paper-portfolio-daily-isolated-scope.v1"
TAIPEI_PREOPEN_CUTOFF = datetime_time(8, 30)
SCHEDULED_WAKE_LOCAL_TIME = "16:15"


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


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve()


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    resolved = _resolved(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    encoded = (_canonical_json(payload) + "\n").encode("utf-8")
    temporary = resolved.with_name(f".{resolved.name}.tmp")
    with temporary.open("wb") as stream:
        stream.write(encoded)
        stream.flush()
        import os

        os.fsync(stream.fileno())
    os.replace(temporary, resolved)


def _scope_paths() -> dict[str, Path]:
    return {
        "repository_root": _resolved(ROOT),
        "repository_output": _resolved(ROOT / "output"),
        "operation_root": _resolved(OPERATIONAL_ROOT),
        "paper_state_root": _resolved(PAPER_STATE_ROOT),
        "state_db": _resolved(STATE_DB),
        "state_seed_manifest": _resolved(STATE_SEED_MANIFEST),
        "ledger_db": _resolved(LEDGER_DB),
        "source_data_root": _resolved(DEFAULT_DATA_ROOT),
        "source_state_db": _resolved(SOURCE_STATE_DB),
        "source_baseline": _resolved(SOURCE_BASELINE_PATH),
        "market_db": _resolved(MARKET_DB),
    }


def _validate_scope() -> dict[str, Path]:
    paths = _scope_paths()
    repository_output = paths["repository_output"]
    operation = paths["operation_root"]
    if not _is_under(repository_output, paths["repository_root"]):
        raise RuntimeError("isolated Paper repository output escaped repository")
    if operation == repository_output or not _is_under(operation, repository_output):
        raise RuntimeError("isolated Paper operation root escaped repository output")
    # resolve() 會展開 junction／reparse point，因此也會拒絕表面位於 repo、
    # 實際解析後指向 repo 外的 operation root。
    writable = (
        ("operation_root", operation),
        ("paper_state_root", paths["paper_state_root"]),
        ("state_db", paths["state_db"]),
        ("state_seed_manifest", paths["state_seed_manifest"]),
    )
    for name, target in writable:
        if not _is_under(target, operation):
            raise RuntimeError(f"isolated Paper write target escaped operation:{name}")
        if _is_under(target, paths["source_data_root"]):
            raise RuntimeError(f"isolated Paper write target overlaps D source:{name}")
    if paths["source_state_db"] == paths["state_db"]:
        raise RuntimeError("isolated Paper state source and target are identical")
    for name in ("source_state_db", "source_baseline", "market_db"):
        source = paths[name]
        if source.expanduser().is_symlink():
            raise RuntimeError(f"isolated Paper source must not be a symlink:{name}")
        if not _is_under(source, paths["source_data_root"]):
            raise RuntimeError(f"isolated Paper source escaped D data root:{name}")
        if _is_under(source, operation):
            raise RuntimeError(f"isolated Paper source overlaps writer operation:{name}")
    if not paths["source_baseline"].is_file() or paths["source_baseline"].is_symlink():
        raise RuntimeError(f"isolated Paper baseline source is unavailable:{paths['source_baseline']}")
    if not paths["market_db"].is_file() or paths["market_db"].is_symlink():
        raise RuntimeError(f"isolated Paper market source is unavailable:{paths['market_db']}")
    return paths


def _observe_baseline(path: Path) -> dict[str, object]:
    """以唯讀檔案 hash 保存 public runner 所需 baseline 的來源證據。"""

    resolved = _resolved(path)
    before = _file_hash(resolved)
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise RuntimeError("isolated Paper baseline source is not an object")
    after = _file_hash(resolved)
    if before != after:
        raise RuntimeError("isolated Paper baseline changed during read")
    return {
        "path": str(resolved),
        "read_mode": "read_only_file",
        "file_sha256": before,
        "source_result_id": payload.get("source_result_id"),
        "decision_date": payload.get("decision_date"),
    }


def _observe_market(path: Path) -> dict[str, object]:
    """只驗證市場 SQLite 可以 query-only 開啟；不向其寫入。"""

    resolved = _resolved(path)
    before = _file_hash(resolved)
    try:
        with sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True) as connection:
            connection.execute("PRAGMA query_only=ON")
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "daily_prices" not in tables:
                raise RuntimeError("isolated Paper market source lacks daily_prices")
    except sqlite3.Error as error:
        raise RuntimeError(f"isolated Paper market source read failed:{type(error).__name__}") from error
    after = _file_hash(resolved)
    if before != after:
        raise RuntimeError("isolated Paper market source changed during read")
    return {
        "path": str(resolved),
        "read_mode": "sqlite_uri_mode_ro_and_query_only",
        "file_sha256": before,
        "required_tables": ["daily_prices"],
    }


def _scope_manifest(paths: Mapping[str, Path]) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "scope_id": "research-paper-preopen-repository-state-v1",
        "source": {
            "state_db": str(paths["source_state_db"]),
            "baseline": str(paths["source_baseline"]),
            "market_db": str(paths["market_db"]),
            "read_mode": "D_read_only_seed_then_repository_state",
        },
        "repository_state": {
            "state_db": str(paths["state_db"]),
            "seed_manifest": str(paths["state_seed_manifest"]),
            "operation_root": str(paths["operation_root"]),
            "writer": "scripts.run_paper_portfolio_daily.run",
            "ledger_read_mode": "sqlite_mode_ro_query_only",
        },
        "safety": {
            "writes_D_source": False,
            "writes_market_database": False,
            "formal_credit": False,
            "broker_execution": False,
            "training_started": False,
            "historical_backfill_claimed": False,
        },
    }
    return body


def _write_or_verify_scope_manifest(paths: Mapping[str, Path]) -> tuple[Path, str]:
    manifest_path = paths["operation_root"] / "paper_portfolio_scope_manifest.json"
    body = _scope_manifest(paths)
    payload = {**body, "content_sha256": _payload_hash(body)}
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError("isolated Paper preopen scope manifest is unreadable") from error
        if not isinstance(existing, Mapping):
            raise RuntimeError("isolated Paper preopen scope manifest is not an object")
        existing_body = dict(existing)
        declared = existing_body.pop("content_sha256", None)
        if declared != _payload_hash(existing_body) or existing_body != body:
            raise RuntimeError("isolated Paper preopen scope manifest changed")
    else:
        _atomic_write_json(manifest_path, payload)
    return manifest_path, _file_hash(manifest_path)


def _blocked_result(
    *,
    paths: Mapping[str, Path] | None,
    observed: datetime,
    blockers: list[str],
) -> dict[str, object]:
    operation = None if paths is None else paths.get("operation_root")
    result: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "producer": "scripts.scheduled.run_paper_portfolio_daily_isolated",
        "observed_at": observed.astimezone(timezone.utc).isoformat(),
        "status": "blocked",
        "blockers": blockers,
        "candidate_only": True,
        "formal_credit": False,
        "writes_D_source": False,
        "writes_market_database": False,
        "broker_execution": False,
        "historical_backfill_claimed": False,
        "state_db": None if paths is None else str(paths["state_db"]),
        "source_state_db": None if paths is None else str(paths["source_state_db"]),
    }
    if operation is not None:
        result["status_path"] = str(operation / "scheduled" / "paper_portfolio_isolated" / "latest_status.json")
    return result


def _taipei_cutoff_for(value: datetime) -> datetime:
    """回傳 value 所在台北自然日的 08:30 cutoff。"""

    taipei = value.astimezone(TAIPEI)
    return datetime.combine(taipei.date(), TAIPEI_PREOPEN_CUTOFF, tzinfo=TAIPEI)


def _waiting_for_taipei_cutoff(
    *,
    observed: datetime,
) -> dict[str, object]:
    """在自然 cutoff 前只回報等待，不開啟任何 D 或 repository SQLite。"""

    taipei = observed.astimezone(TAIPEI)
    cutoff = _taipei_cutoff_for(observed)
    return {
        "schema_version": SCHEMA_VERSION,
        "producer": "scripts.scheduled.run_paper_portfolio_daily_isolated",
        "observed_at": observed.astimezone(timezone.utc).isoformat(),
        "taipei_now": taipei.isoformat(),
        "taipei_cutoff": cutoff.isoformat(),
        "status": "waiting_for_taipei_cutoff",
        "blockers": ["taipei_preopen_cutoff_not_reached"],
        "candidate_only": True,
        "formal_credit": False,
        "writes_D_source": False,
        "writes_market_database": False,
        "broker_execution": False,
        "historical_backfill_claimed": False,
        "state_db": str(_resolved(STATE_DB)),
        "source_state_db": str(_resolved(SOURCE_STATE_DB)),
        "guard": "taipei_08:30_natural_clock",
    }


def _wait_until_taipei_cutoff(
    *,
    now_fn: Callable[[], datetime] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
) -> datetime:
    """在排程的早期喚醒後等待真實台北 08:30，再回傳可用時間。

    排程設在 16:15 Pacific：PDT 時為台北 07:15，PST 時為台北 08:15。
    此 guard 讓同一個 task 在兩種 DST 狀態都只於已到達 08:30 cutoff 後讀取來源；
    測試可注入 clock/sleep，正式入口使用實際系統時間。
    """

    clock = now_fn or (lambda: datetime.now(TAIPEI))
    sleeper = sleep_fn or time_module.sleep
    while True:
        current_raw = clock()
        if current_raw.tzinfo is None or current_raw.utcoffset() is None:
            raise ValueError("scheduled Taipei clock must include timezone")
        current = current_raw.astimezone(TAIPEI)
        cutoff = _taipei_cutoff_for(current)
        if current >= cutoff:
            return current
        remaining = (cutoff - current).total_seconds()
        # 每次最多等待一分鐘，讓作業系統時鐘跳變及終止訊號能被觀察。
        sleeper(min(max(remaining, 0.1), 60.0))


def run_isolated(
    *,
    now: datetime | None = None,
    decision_at: datetime | None = None,
    calendar: OfficialTradingCalendar | None = None,
) -> dict[str, object]:
    """執行一次自然時間盤前 snapshot；``now`` 僅供隔離測試傳入。"""

    observed_raw = now or datetime.now(timezone.utc)
    if observed_raw.tzinfo is None or observed_raw.utcoffset() is None:
        raise ValueError("now must include timezone")
    observed = observed_raw.astimezone(timezone.utc)
    if observed.astimezone(TAIPEI) < _taipei_cutoff_for(observed):
        return _waiting_for_taipei_cutoff(observed=observed)
    paths: dict[str, Path] | None = None
    try:
        paths = _validate_scope()
        manifest_path, manifest_hash = _write_or_verify_scope_manifest(paths)
        seed = ensure_repo_state_from_readonly_source(
            source=paths["source_state_db"],
            target=paths["state_db"],
            manifest_path=paths["state_seed_manifest"],
            observed_at=observed,
        )
        baseline_observation = _observe_baseline(paths["source_baseline"])
        market_observation = _observe_market(paths["market_db"])
        resolved_decision = decision_at or _latest_reached_decision_at(
            None,
            now=observed.astimezone(TAIPEI),
        )
        result = run_paper_portfolio_daily(
            baseline_path=paths["source_baseline"],
            state_db=paths["state_db"],
            market_db=paths["market_db"],
            output_root=paths["operation_root"],
            decision_at=resolved_decision,
            calendar=calendar,
            now=observed.astimezone(TAIPEI),
            ledger_db=paths["ledger_db"],
        )
        state_head = publish_repo_state_head(
            target=paths["state_db"],
            manifest_path=paths["state_seed_manifest"],
            observed_at=observed,
        )
        combined: dict[str, object] = {
            **result,
            "producer": "scripts.scheduled.run_paper_portfolio_daily_isolated",
            "isolated_scope": {
                "scope_manifest_path": str(manifest_path),
                "scope_manifest_file_sha256": manifest_hash,
                "source_state_db": str(paths["source_state_db"]),
                "source_state_read_mode": "sqlite_uri_mode_ro_and_query_only",
                "repository_state_db": str(paths["state_db"]),
                "repository_state_scope": "repository_output_only",
                "state_seed": seed,
                "state_head": state_head,
                "baseline": baseline_observation,
                "market": market_observation,
                "ledger_db": str(paths["ledger_db"]),
                "formal_credit": False,
                "writes_D_source": False,
                "writes_market_database": False,
                "broker_execution": False,
            },
        }
        _atomic_write_json(
            paths["operation_root"]
            / "scheduled"
            / "paper_portfolio_isolated"
            / "latest_status.json",
            combined,
        )
        return combined
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        blocked = _blocked_result(
            paths=paths,
            observed=observed,
            blockers=[f"isolated_paper_preopen_failed:{type(error).__name__}:{error}"],
        )
        if paths is not None:
            _atomic_write_json(
                paths["operation_root"]
                / "scheduled"
                / "paper_portfolio_isolated"
                / "latest_status.json",
                blocked,
            )
        return blocked


def _print_json(value: Mapping[str, object]) -> None:
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    try:
        sys.stdout.write(encoded.decode())
    except UnicodeEncodeError:
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is None:
            sys.stdout.write(encoded.decode("utf-8"))
        else:
            buffer.write(encoded)
            buffer.flush()


def main(argv: list[str] | None = None) -> int:
    configure_utf8_console()
    parser = argparse.ArgumentParser(description=__doc__)
    # 只保留受控測試／人工診斷所需的明確 cutoff；scheduled cmd 不傳入，
    # 因此 production 永遠使用此刻已到達的 Taipei 08:30。
    parser.add_argument("--decision-at", default=None)
    args = parser.parse_args(argv)
    explicit_decision = None
    if args.decision_at is not None:
        explicit_decision = datetime.fromisoformat(str(args.decision_at).replace("Z", "+00:00"))
    # Task Scheduler 在 Pacific 16:15 喚醒；兩種 DST offset 都早於台北 cutoff，
    # 故此處只等待真實時鐘到 08:30，絕不以「最近已到達」把前一日當成今日輸入。
    reached_taipei = _wait_until_taipei_cutoff()
    result = run_isolated(
        now=reached_taipei,
        decision_at=explicit_decision,
    )
    _print_json(result)
    return 0 if str(result.get("status")) in {
        "passed",
        "skipped_non_trading_day",
        "skipped_future_decision",
        "waiting_for_taipei_cutoff",
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())
