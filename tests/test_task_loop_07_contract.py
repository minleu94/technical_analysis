"""TASK-07 隔離候選池、日期聚合、快照與非同步展示契約。"""

import ast
from copy import deepcopy
from datetime import date, datetime
from dataclasses import replace
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from app_module.decision_desk_dtos import DecisionDeskQuality, MarketRegimeSummary, PortfolioAlertSummary
from app_module.decision_desk_service import DecisionDeskSnapshotBuilder, SavedRecommendationDeskProvider
from app_module.decision_desk_snapshot_repository import DecisionDeskSnapshotRepository
from app_module.dtos import RecommendationDTO, RecommendationResultDTO
from app_module.watchlist_service import WatchlistService
from app_module.watchlist_trigger_service import WatchlistTriggerService, WatchlistServiceWatchlistProvider
from data_module.watchlist_repository import WatchlistRepository
from data_module.watchlist_migration import migrate_watchlist_copy


def config(root):
    return SimpleNamespace(output_root=root / "output", db_file=root / "market.db", use_sqlite=True,
                           stock_data_file=root / "missing.csv", resolve_output_path=lambda name: root / "output" / name)


def legacy_pool():
    return {"version": 1, "name": "候選池", "description": "隔離副本", "created_at": "2026-05-01T10:00:00",
            "updated_at": "2026-05-01T10:00:00", "items": [{"stock_code": "2330", "stock_name": "台積電",
            "added_at": "2026-05-01T10:00:00", "source": "recommendation", "source_id": "rec-001", "notes": "", "tags": []}]}


def test_watchlist_copy_migration_reopen_duplicate_remove_and_hash(tmp_path):
    source, target = tmp_path / "default.json", tmp_path / "watchlists.db"
    source.write_text(json.dumps(legacy_pool(), ensure_ascii=False), encoding="utf-8")
    original = source.read_bytes()
    proof = migrate_watchlist_copy(source, target, sandbox_root=tmp_path)
    assert migrate_watchlist_copy(source, target, sandbox_root=tmp_path) == proof
    service = WatchlistService(config(tmp_path), repository=WatchlistRepository(target))
    assert service.add_stocks([{"stock_code": "2330", "stock_name": "台積電"}]) == 0
    assert service.get_stocks()[0]["source_id"] == "rec-001"
    assert service.add_stocks([{"stock_code": "2317", "stock_name": "鴻海", "source_id": "rec-002"}], source="recommendation") == 1
    reopened = WatchlistService(config(tmp_path), repository=WatchlistRepository(target))
    assert reopened.get_stock_codes() == ["2330", "2317"]
    assert reopened.remove_stocks(["2330"]) == 1
    assert reopened.get_stock_codes() == ["2317"]
    assert source.read_bytes() == original
    assert proof["source_hash"] == hashlib.sha256(original).hexdigest()
    with pytest.raises(RuntimeError, match="禁止覆寫"):
        migrate_watchlist_copy(source, target, sandbox_root=tmp_path)


def test_watchlist_migration_rejects_outside_source_and_conflicting_revision(tmp_path):
    with pytest.raises(ValueError, match="sandbox"):
        migrate_watchlist_copy(tmp_path.parent / "source.json", tmp_path / "copy.db", sandbox_root=tmp_path)
    repository = WatchlistRepository(tmp_path / "copy.db", initialize=True)
    repository.save("default", legacy_pool(), expected_revision=None)
    with pytest.raises(RuntimeError, match="revision_conflict"):
        repository.save("default", legacy_pool(), expected_revision=None)


def test_corrupt_json_is_not_replaced_or_renamed(tmp_path):
    path = tmp_path / "output" / "watchlist" / "default.json"
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    service = WatchlistService(config(tmp_path))
    with pytest.raises(json.JSONDecodeError):
        service.get_stocks()
    assert path.read_text(encoding="utf-8") == "{broken"
    assert not path.with_suffix(".json.bak").exists()


def test_stock_name_query_is_readonly_and_ui_has_no_storage_calls(tmp_path):
    settings = config(tmp_path)
    with sqlite3.connect(settings.db_file) as conn:
        conn.execute("CREATE TABLE daily_prices(日期 TEXT, 證券代號 TEXT, 證券名稱 TEXT)")
        conn.execute("INSERT INTO daily_prices VALUES('20260520','2330','台積電')")
    before = settings.db_file.read_bytes()
    service = WatchlistService(settings)
    assert service.query_stock_names(["2330", "9999"]) == {"2330": "台積電"}
    assert settings.db_file.read_bytes() == before
    source = Path("ui_qt/views/watchlist_view.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "DBManager" not in source and "sqlite3" not in source
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr in {"read_csv", "read_sql", "read_text", "read_bytes", "write_text"}]


def test_watchlist_future_membership_and_empty_pool_are_distinct_from_missing(tmp_path):
    service = WatchlistService(config(tmp_path))
    provider = WatchlistServiceWatchlistProvider(service)
    assert provider.fetch(date(2026, 5, 20)) == []
    ranking = SimpleNamespace(fetch=lambda day: {}, fetch_previous=lambda day: {})
    assert WatchlistTriggerService(provider, ranking).build_snapshot(date(2026, 5, 20)).quality == DecisionDeskQuality.OBSERVED
    service.add_stocks([{"stock_code": "2330", "stock_name": "台積電"}])
    assert provider.fetch(date(2020, 1, 1)) == []


@pytest.mark.parametrize("score", [Decimal("NaN"), Decimal("Infinity"), None])
def test_trigger_unknown_score_and_future_provider_are_not_safe(tmp_path, score):
    watchlist = SimpleNamespace(fetch=lambda day: ["2330"])
    ranking = SimpleNamespace(fetch=lambda day: {"2330": {"score_bp": score}}, fetch_previous=lambda day: {})
    summary = WatchlistTriggerService(watchlist, ranking).build_snapshot(date(2026, 5, 20))
    assert summary.trigger_count is None and summary.quality == DecisionDeskQuality.MISSING
    assert any("data_insufficient" in item for item in summary.warnings)
    ranking.actual_date = date(2026, 5, 21)
    assert WatchlistTriggerService(watchlist, ranking).build_snapshot(date(2026, 5, 20)).quality == DecisionDeskQuality.MISSING


def recommendation(day="2026-05-20", result_id="rec-001"):
    return RecommendationResultDTO(result_id, "推薦", {"profile_id": "momentum"},
        [RecommendationDTO("2330", "台積電", Decimal("100"), 1, 70, 70, 0, 0, "已知理由", "未知", False)],
        created_at="2026-05-20T16:00:00", run_context={"schema_version": "recommendation-context.v1", "as_of_date": day,
        "profile_id": "momentum", "data_fingerprint": "a" * 64, "eligible_universe_size": 2})


def test_desk_rejects_future_sections_and_preserves_fallback_and_recommendation_lineage(tmp_path):
    provider = SimpleNamespace(fetch_market_regime=lambda day: MarketRegimeSummary(date(2026, 5, 19), DecisionDeskQuality.OBSERVED, (), "Trend"),
                               fetch_portfolio_alerts=lambda day: PortfolioAlertSummary(date(2026, 5, 21), DecisionDeskQuality.OBSERVED, (), 0, (), "safe"))
    builder = DecisionDeskSnapshotBuilder(provider, recommendation_provider=SimpleNamespace(fetch=lambda day: recommendation()))
    snapshot = builder.build_snapshot(date(2026, 5, 20))
    assert snapshot.market_regime.as_of_date == date(2026, 5, 19)
    assert snapshot.market_regime.quality == DecisionDeskQuality.DEGRADED
    assert snapshot.portfolio_alerts.quality == DecisionDeskQuality.MISSING
    assert snapshot.portfolio_alerts.alert_level is None
    assert snapshot.source_lineage["recommendations"]["result_id"] == "rec-001"
    assert snapshot.recommendations.context["data_fingerprint"] == "a" * 64
    repository = DecisionDeskSnapshotRepository(config(tmp_path), db_path=tmp_path / "desk.db")
    stored = repository.save_loop_snapshot(snapshot)
    assert repository.save_loop_snapshot(snapshot).snapshot_id == stored.snapshot_id
    assert repository.save_loop_snapshot(replace(snapshot, generated_at=datetime(2026, 5, 21))).snapshot_id == stored.snapshot_id
    assert repository.load_loop_snapshot_payload(stored.snapshot_id) == snapshot.to_dict()
    reloaded = repository.load_loop_snapshot(stored.snapshot_id)
    assert reloaded.recommendations == snapshot.recommendations
    assert reloaded.source_lineage == snapshot.source_lineage
    ro = DecisionDeskSnapshotRepository(config(tmp_path), db_path=tmp_path / "desk.db", read_only=True)
    before = (tmp_path / "desk.db").read_bytes()
    assert ro.load_loop_snapshot_payload(stored.snapshot_id) == snapshot.to_dict()
    assert (tmp_path / "desk.db").read_bytes() == before


def test_saved_recommendation_reader_ignores_future_append_without_writes(tmp_path):
    from app_module.recommendation_repository import RecommendationRepository
    settings = config(tmp_path)
    writer = RecommendationRepository(settings)
    writer.save_result(recommendation(), "已知")
    reader = SavedRecommendationDeskProvider(settings)
    assert reader.fetch(date(2026, 5, 20)).result_id == "rec-001"
    writer.save_result(recommendation("2026-06-01", "rec-future"), "未來")
    hashes = {path: path.read_bytes() for path in writer.runs_dir.iterdir() if path.is_file()}
    assert reader.fetch(date(2026, 5, 20)).result_id == "rec-001"
    assert all(path.read_bytes() == raw for path, raw in hashes.items())


def test_stale_async_result_or_error_cannot_overwrite_new_date(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from ui_qt.views import decision_desk_view as module
    app = QApplication.instance() or QApplication([])

    class Signal:
        def connect(self, callback): self.callback = callback
        def emit(self, *args): self.callback(*args)

    class Worker:
        created = []
        def __init__(self, function, request_date):
            self.function, self.request_date = function, request_date
            self.finished, self.error, self.cancelled = Signal(), Signal(), Signal()
            self.running = True
            Worker.created.append(self)
        def start(self): pass
        def isRunning(self): return self.running
        def deleteLater(self): self.running = False

    monkeypatch.setattr(module, "TaskWorker", Worker)
    builder = DecisionDeskSnapshotBuilder()
    view = module.DecisionDeskView(builder, as_of_date=date(2026, 5, 20), auto_refresh=False)
    view.refresh_snapshot()
    old = Worker.created[0]
    view.as_of_date = date(2026, 5, 21)
    view.refresh_snapshot()
    old.finished.emit(builder.build_snapshot(old.request_date))
    assert view._last_snapshot is None
    newest = Worker.created[-1]
    old.error.emit("舊錯誤")
    assert view._refresh_worker is newest
    newest.finished.emit(builder.build_snapshot(newest.request_date))
    assert view._last_snapshot.as_of_date == date(2026, 5, 21)
    assert view.refresh_btn.isEnabled()
    view.close()
    app.processEvents()


def test_ledger_read_model_date_quality_hash_and_future_append(tmp_path):
    from app_module.decision_desk_service import PortfolioLedgerDeskProvider
    from app_module.portfolio_service import PortfolioService
    from data_module.config import TWStockConfig
    from data_module.portfolio_ledger_repository import PortfolioLedgerEvent, PortfolioLedgerRepository

    event = PortfolioLedgerEvent(event_id="buy-1", portfolio_id="default", source_namespace="manual",
        occurred_at="2026-05-20", stock_code="2330", stock_name="台積電", side="buy", quantity=10,
        price=Decimal("100"), fees=Decimal("0"), taxes=Decimal("0"), source_id="rec-001", thesis_id="thesis-001")
    repo = PortfolioLedgerRepository.create_synthetic_fixture(tmp_path / "candidate.db", events=(event,))
    service = PortfolioService(TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output", profile="unit"), ledger_repository=repo)
    builder = DecisionDeskSnapshotBuilder(portfolio_ledger_provider=PortfolioLedgerDeskProvider(service))
    before = builder.build_snapshot(date(2026, 5, 20))
    model = before.source_lineage["portfolio_ledger"]
    assert model["quality"] == "blocked" and "market_prices" in model["missing_inputs"]
    assert model["candidate_only"] and model["source_ledger_hash"].startswith("sha256:")
    assert before.portfolio_alerts.alert_level is None and before.portfolio_alerts.quality == DecisionDeskQuality.MISSING
    repo.append(replace(event, event_id="buy-future", occurred_at="2026-06-01"))
    assert builder.build_snapshot(date(2026, 5, 20)).source_lineage["portfolio_ledger"] == model
    readonly_bytes = (tmp_path / "candidate.db").read_bytes()
    builder.build_snapshot(date(2026, 5, 20))
    assert (tmp_path / "candidate.db").read_bytes() == readonly_bytes


def test_decision_qa_failure_is_nonzero_and_preserves_environment(tmp_path, monkeypatch):
    from scripts import qa_validate_decision_loop as qa
    monkeypatch.setenv("DATA_ROOT", "outer-data")
    monkeypatch.setenv("OUTPUT_ROOT", "outer-output")
    def fail(root): raise AssertionError("injected")
    monkeypatch.setattr(qa, "run_checks", fail)
    output = tmp_path / "report.json"
    assert qa.main(["--output-json", str(output)]) == 1
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "failed"
    import os
    assert os.environ["DATA_ROOT"] == "outer-data" and os.environ["OUTPUT_ROOT"] == "outer-output"


@pytest.mark.parametrize("result_id", ["saved-rec-001", None])
def test_recommendation_selected_candidate_keeps_real_identity_without_inventing_one(tmp_path, monkeypatch, result_id):
    import pandas as pd
    from ui_qt.views import recommendation_view as module
    service = WatchlistService(config(tmp_path))
    frame = pd.DataFrame([{"證券代號": "2330", "證券名稱": "台積電"}])
    monkeypatch.setattr(module.QMessageBox, "information", lambda *args: None)
    errors = []
    monkeypatch.setattr(module.QMessageBox, "critical", lambda *args: errors.append(args))
    view = SimpleNamespace(watchlist_service=service, recommendations_model=SimpleNamespace(getDataFrame=lambda: frame),
        results_table=SimpleNamespace(selectionModel=lambda: SimpleNamespace(selectedRows=lambda: [SimpleNamespace(row=lambda: 0)])),
        current_result_id=result_id, current_profile=None, current_regime=None, profiles={})
    module.RecommendationView._add_selected_to_watchlist(view)
    reopened = WatchlistService(config(tmp_path))
    assert not errors and reopened.get_stocks()[0]["source_id"] == (result_id or "")
    assert reopened.get_stocks()[0]["source"] == "recommendation"


@pytest.mark.parametrize("id_column", ["source_id", "result_id"])
def test_watchlist_dataframe_handoff_preserves_result_identity(tmp_path, id_column):
    import pandas as pd
    from ui_qt.views.watchlist_view import WatchlistView
    service = WatchlistService(config(tmp_path))
    view = SimpleNamespace(watchlist_service=service, _load_watchlist=lambda: None,
                           watchlistUpdated=SimpleNamespace(emit=lambda: None))
    frame = pd.DataFrame([{"證券代號": "2330", "證券名稱": "台積電", "source_id": pd.NA, id_column: "saved-rec-002"}])
    assert WatchlistView.add_stocks_from_dataframe(view, frame, source="recommendation") == 1
    assert WatchlistService(config(tmp_path)).get_stocks()[0]["source_id"] == "saved-rec-002"


def test_watchlist_dataframe_missing_identity_is_empty(tmp_path):
    import pandas as pd
    from ui_qt.views.watchlist_view import WatchlistView
    service = WatchlistService(config(tmp_path))
    view = SimpleNamespace(watchlist_service=service, _load_watchlist=lambda: None,
                           watchlistUpdated=SimpleNamespace(emit=lambda: None))
    frame = pd.DataFrame([{"證券代號": "2330", "證券名稱": "台積電", "source_id": pd.NA}])
    assert WatchlistView.add_stocks_from_dataframe(view, frame, source="recommendation") == 1
    assert service.get_stocks()[0]["source_id"] == ""


def test_decision_qa_failure_closes_owned_connections_and_restores_borrowed_logger(tmp_path, monkeypatch):
    import logging
    from app_module import recommendation_repository as repository_module
    from data_module.config import TWStockConfig
    from scripts import qa_validate_decision_loop as qa

    logger = logging.getLogger("data_module.config")
    borrowed = logging.FileHandler(tmp_path / "borrowed.log", encoding="utf-8")
    logger.addHandler(borrowed)
    handlers, level, propagate = list(logger.handlers), logger.level, logger.propagate
    original_sqlite = repository_module.sqlite3
    connections, fixture_roots, own_handlers = [], [], []

    def fail(root):
        fixture_roots.append(root)
        TWStockConfig(data_root=root / "data", output_root=root / "artifacts", profile="unit")
        own_handlers.extend(logger.handlers)
        connection = repository_module.sqlite3.connect(root / "unclosed.db")
        connections.append(connection)
        connection.execute("CREATE TABLE fixture(value TEXT)")
        raise RuntimeError("failure_after_open_connection")

    monkeypatch.setattr(qa, "run_checks", fail)
    try:
        output = tmp_path / "failed.json"
        assert qa.main(["--output-json", str(output)]) == 1
        report = json.loads(output.read_text(encoding="utf-8"))
        assert report["error"] == "RuntimeError: failure_after_open_connection"
        assert not fixture_roots[0].exists()
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connections[0].execute("SELECT 1")
        assert logger.handlers == handlers and (logger.level, logger.propagate) == (level, propagate)
        assert borrowed.stream is not None and not borrowed.stream.closed
        assert all(handler._closed for handler in own_handlers)
        assert repository_module.sqlite3 is original_sqlite
        assert (tmp_path / "borrowed.log").read_bytes() == b""
    finally:
        logger.removeHandler(borrowed)
        borrowed.close()


def test_decision_qa_success_removes_temp_root_in_same_process(tmp_path, monkeypatch):
    from scripts import qa_validate_decision_loop as qa
    original_checks = qa.run_checks
    roots = []
    def checks(root):
        roots.append(root)
        return original_checks(root)
    monkeypatch.setattr(qa, "run_checks", checks)
    report_path = tmp_path / "passed.json"
    assert qa.main(["--output-json", str(report_path)]) == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "passed" and len(report["checks"]) == 7
    assert not roots[0].exists()
