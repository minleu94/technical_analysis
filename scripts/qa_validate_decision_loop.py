"""TASK-LOOP-07 專用離線 QA：雙根隔離、候選池、來源聚合與快照。"""

from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from typing import Iterator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@contextmanager
def isolated_environment(root: Path) -> Iterator[dict[str, str]]:
    values = {"DATA_ROOT": str(root / "data"), "OUTPUT_ROOT": str(root / "artifacts"),
              "PROFILE": "test", "QT_QPA_PLATFORM": "offscreen"}
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield values
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def isolated_fixture_resources() -> Iterator[None]:
    """只關閉 QA 借出的連線與新 logger handlers，不回收全程序物件。"""
    from app_module import recommendation_repository as repository_module

    original_sqlite = repository_module.sqlite3
    logger = logging.getLogger("data_module.config")
    original_handlers = list(logger.handlers)
    original_level, original_propagate = logger.level, logger.propagate

    def restore_logger() -> None:
        try:
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                if handler not in original_handlers:
                    handler.close()
        finally:
            for handler in original_handlers:
                logger.addHandler(handler)
            logger.setLevel(original_level)
            logger.propagate = original_propagate

    with ExitStack() as resources:
        resources.callback(setattr, repository_module, "sqlite3", original_sqlite)
        resources.callback(restore_logger)
        for handler in original_handlers:
            logger.removeHandler(handler)
        logger.propagate = False

        def connect(*args, **kwargs):
            connection = original_sqlite.connect(*args, **kwargs)
            resources.callback(connection.close)
            return connection

        # 只替換此 writer 模組的借用名稱；全域 sqlite3.connect 與真實 SQL 都不變。
        repository_module.sqlite3 = SimpleNamespace(connect=connect)
        yield


def run_checks(root: Path) -> dict[str, object]:
    from app_module.decision_desk_dtos import DecisionDeskQuality, MarketRegimeSummary
    from app_module.decision_desk_service import DecisionDeskSnapshotBuilder, PortfolioLedgerDeskProvider, SavedRecommendationDeskProvider
    from app_module.decision_desk_snapshot_repository import DecisionDeskSnapshotRepository
    from app_module.dtos import RecommendationDTO, RecommendationResultDTO
    from app_module.portfolio_service import PortfolioService
    from app_module.recommendation_repository import RecommendationRepository
    from app_module.watchlist_service import WatchlistService
    from app_module.watchlist_trigger_service import WatchlistTriggerService, WatchlistServiceWatchlistProvider
    from data_module.config import TWStockConfig
    from data_module.portfolio_ledger_repository import PortfolioLedgerEvent, PortfolioLedgerRepository
    from data_module.watchlist_migration import migrate_watchlist_copy
    from data_module.watchlist_repository import WatchlistRepository

    checks: list[str] = []
    config = TWStockConfig(data_root=root / "data", output_root=root / "artifacts", profile="unit")
    source = root / "default-copy.json"
    payload = {"version": 1, "name": "隔離候選池", "description": "", "created_at": "2026-05-01T00:00:00",
               "updated_at": "2026-05-01T00:00:00", "items": [{"stock_code": "2330", "stock_name": "台積電",
               "added_at": "2026-05-01T00:00:00", "source": "recommendation", "source_id": "rec-qa", "notes": "", "tags": []}]}
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    original = source.read_bytes()
    target = root / "data" / "watchlists.db"
    proof = migrate_watchlist_copy(source, target, sandbox_root=root)
    assert migrate_watchlist_copy(source, target, sandbox_root=root) == proof
    watchlist = WatchlistService(config, repository=WatchlistRepository(target))
    assert watchlist.add_stocks([{"stock_code": "2330", "stock_name": "台積電"}]) == 0
    assert watchlist.add_stocks([{"stock_code": "2317", "stock_name": "鴻海", "source_id": "rec-qa"}]) == 1
    reopened = WatchlistService(config, repository=WatchlistRepository(target))
    assert reopened.remove_stocks(["2317"]) == 1 and reopened.get_stock_codes() == ["2330"]
    assert source.read_bytes() == original
    checks.append("watchlist_copy_migrate_reopen_identity_hash")

    result = RecommendationResultDTO("rec-qa", "QA", {"profile_id": "momentum"},
        [RecommendationDTO("2330", "台積電", Decimal("100"), 1, 70, 70, 0, 0, "已知理由", "未知", False)],
        created_at="2026-05-20T16:00:00", run_context={"schema_version": "recommendation-context.v1",
        "as_of_date": "2026-05-20", "profile_id": "momentum", "data_fingerprint": "fixture-sha256"})
    rec_writer = RecommendationRepository(config)
    rec_writer.save_result(result, "已知推薦")
    rec_provider = SavedRecommendationDeskProvider(config)
    rec_writer.save_result(replace(result, result_id="rec-future", run_context={**result.run_context, "as_of_date": "2026-06-01"}), "未來推薦")
    assert rec_provider.fetch(date(2026, 5, 20)).result_id == "rec-qa"
    checks.append("saved_recommendation_future_append")

    event = PortfolioLedgerEvent(event_id="buy-qa", portfolio_id="default", source_namespace="manual",
        occurred_at="2026-05-20", stock_code="2330", stock_name="台積電", side="buy", quantity=10,
        price=Decimal("100"), fees=Decimal("0"), taxes=Decimal("0"), source_id="rec-qa", thesis_id="thesis-qa")
    ledger = PortfolioLedgerRepository.create_synthetic_fixture(root / "data" / "candidate.db", events=(event,))
    portfolio = PortfolioService(config, ledger_repository=ledger)
    ranking = SimpleNamespace(fetch=lambda day: {"2330": {"score_bp": 8000}}, fetch_previous=lambda day: {"2330": {"score_bp": 5000}})
    triggers = WatchlistTriggerService(WatchlistServiceWatchlistProvider(reopened), ranking)
    market = SimpleNamespace(fetch_market_regime=lambda day: MarketRegimeSummary(date(2026, 5, 19), DecisionDeskQuality.OBSERVED, (), "Trend"))
    builder = DecisionDeskSnapshotBuilder(market, watchlist_trigger_service=triggers,
        recommendation_provider=rec_provider, portfolio_ledger_provider=PortfolioLedgerDeskProvider(portfolio),
        clock=lambda: datetime(2026, 5, 20, 17))
    observed_paths = [source, target, ledger.db_path, *[path for path in rec_writer.runs_dir.iterdir() if path.is_file()]]
    before = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in observed_paths}
    snapshot = builder.build_snapshot(date(2026, 5, 20))
    assert snapshot.market_regime.quality == DecisionDeskQuality.DEGRADED
    assert snapshot.recommendations.result_id == "rec-qa"
    assert snapshot.source_lineage["portfolio_ledger"]["quality"] == "blocked"
    assert snapshot.portfolio_alerts.alert_level is None
    assert snapshot.watchlist_triggers.trigger_count == 1
    checks.extend(("desk_dates_and_missing_inputs_visible", "candidate_ledger_hash_quality_lineage", "watchlist_trigger_aggregation"))

    snapshots = DecisionDeskSnapshotRepository(config, db_path=root / "data" / "desk.db")
    saved = snapshots.save_loop_snapshot(snapshot)
    assert snapshots.save_loop_snapshot(replace(snapshot, generated_at=datetime(2026, 5, 21))).snapshot_id == saved.snapshot_id
    assert snapshots.load_loop_snapshot_payload(saved.snapshot_id) == snapshot.to_dict()
    reloaded = snapshots.load_loop_snapshot(saved.snapshot_id)
    assert reloaded.source_lineage == snapshot.source_lineage and reloaded.recommendations == snapshot.recommendations
    checks.append("snapshot_idempotent_and_lineage_reload")
    after = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in observed_paths}
    assert after == before
    checks.append("aggregation_preserves_source_hashes")
    return {"status": "passed", "scope": "TASK-LOOP-07", "checks": checks, "skipped": [],
            "source_hashes": after, "fixture_only": True, "source_unchanged": True,
            "production_migration_allowed": False, "snapshot_id": saved.snapshot_id}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-json", type=Path, default=PROJECT_ROOT / "output" / "qa" / "decision_loop" / "report.json")
    args = parser.parse_args(argv)
    try:
        with tempfile.TemporaryDirectory(prefix="baldr_task_loop_07_") as directory:
            with isolated_environment(Path(directory)) as environment:
                with isolated_fixture_resources():
                    result = run_checks(Path(directory))
                    result["isolation"] = environment
    except Exception as exc:
        result = {"status": "failed", "scope": "TASK-LOOP-07", "error": f"{type(exc).__name__}: {exc}"}
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
