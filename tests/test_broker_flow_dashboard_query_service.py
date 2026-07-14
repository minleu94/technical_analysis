from datetime import date
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app_module.broker_flow_dashboard_dtos import BrokerFlowDashboardQuery
from app_module.broker_flow_dashboard_query_service import (
    BrokerFlowDashboardQueryService,
)
from app_module.broker_flow_sqlite_read_repository import BrokerFlowReadSnapshot
from decision_module.flow_contracts import BrokerFlowEvent
from scripts.qa_broker_flow_dashboard_latency import (
    benchmark_operation,
    evaluate_latency_gate,
    inspect_broker_flow_sqlite,
    summarize_latency_samples,
)


@pytest.mark.parametrize(
    ("period", "expected_days"),
    (("day", 1), ("week", 5), ("month", 20)),
)
def test_dashboard_query_maps_period_to_broker_trading_days(period, expected_days):
    query = BrokerFlowDashboardQuery(
        period=period,
        scope="top_bottom",
        requested_as_of_date=date(2026, 7, 5),
        limit_per_side=50,
    )

    assert query.period_trading_days == expected_days


def test_dashboard_query_selects_recent_dates_at_or_before_explicit_as_of():
    query = BrokerFlowDashboardQuery(
        period="week",
        scope="top_bottom",
        requested_as_of_date=date(2026, 7, 5),
        limit_per_side=50,
    )
    available_dates = (
        date(2026, 6, 26),
        date(2026, 6, 27),
        date(2026, 6, 30),
        date(2026, 7, 1),
        date(2026, 7, 2),
        date(2026, 7, 3),
        date(2026, 7, 6),
    )

    assert query.select_trading_dates(available_dates) == (
        date(2026, 6, 27),
        date(2026, 6, 30),
        date(2026, 7, 1),
        date(2026, 7, 2),
        date(2026, 7, 3),
    )


def test_dashboard_query_rejects_implicit_or_invalid_contract_values():
    with pytest.raises(ValueError, match="requested_as_of_date"):
        BrokerFlowDashboardQuery(
            period="week",
            scope="top_bottom",
            requested_as_of_date=None,
            limit_per_side=50,
        )
    with pytest.raises(ValueError, match="period"):
        BrokerFlowDashboardQuery(
            period="calendar_week",
            scope="top_bottom",
            requested_as_of_date=date(2026, 7, 5),
            limit_per_side=50,
        )
    with pytest.raises(ValueError, match="limit_per_side"):
        BrokerFlowDashboardQuery(
            period="week",
            scope="top_bottom",
            requested_as_of_date=date(2026, 7, 5),
            limit_per_side=0,
        )


def test_latency_summary_separates_cold_sample_and_warm_nearest_rank_p95():
    summary = summarize_latency_samples([900.0, 10.0, 20.0, 30.0, 40.0, 50.0])

    assert summary == {
        "sample_count": 6,
        "cold_ms": 900.0,
        "warm_sample_count": 5,
        "warm_p95_ms": 50.0,
        "warm_min_ms": 10.0,
        "warm_max_ms": 50.0,
    }


def test_acceptance_benchmark_keeps_warmup_and_twenty_raw_samples():
    calls = []

    result = benchmark_operation(
        "fixture",
        lambda: calls.append(len(calls)) or {"query_count": 2, "row_count": 7},
        runs=20,
    )

    assert len(calls) == 21
    assert len(result["raw_samples_ms"]) == 20
    assert result["warmup_ms"] >= 0
    assert result["last_result"] == {"query_count": 2, "row_count": 7}


def test_latency_gate_reports_failure_instead_of_masking_regression():
    result = evaluate_latency_gate(
        {"warm_p95_ms": 2000.0, "cold_ms": 4999.0},
        warm_limit_ms=2000.0,
        cold_limit_ms=5000.0,
    )

    assert result == {
        "status": "fail",
        "warm_limit_ms": 2000.0,
        "warm_p95_ms": 2000.0,
        "cold_limit_ms": 5000.0,
        "cold_ms": 4999.0,
    }


def test_latency_cli_emits_cjk_and_writes_output_under_cp1252_console(tmp_path):
    output_path = tmp_path / "latency.json"
    code = (
        "from pathlib import Path; "
        "from scripts.qa_broker_flow_dashboard_latency import _emit_report; "
        f"_emit_report('主力流向', Path({str(output_path)!r}))"
    )
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp1252"

    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    assert completed.stdout.decode("utf-8").strip() == "主力流向"
    assert output_path.read_text(encoding="utf-8") == "主力流向\n"


def test_sqlite_shape_probe_is_read_only_and_missing_path_is_not_created(tmp_path):
    missing = tmp_path / "missing.db"

    result = inspect_broker_flow_sqlite(missing)

    assert result["quality"] == "missing"
    assert result["row_count"] == 0
    assert not missing.exists()


def _dashboard_event(code, net_qty, branch="branch_a"):
    return BrokerFlowEvent(
        date="2026-07-03",
        branch_system_key=branch,
        branch_display_name=branch,
        stock_code=code,
        stock_name=f"股票{code}",
        buy_qty=max(net_qty, 0),
        sell_qty=abs(min(net_qty, 0)),
        net_qty=net_qty,
        lots_quality="observed",
        lots_observed=True,
    )


class _DashboardRepository:
    def __init__(self, source):
        self.source = source
        self.calls = []

    def load_dashboard_source(self, query):
        self.calls.append(query)
        return self.source


class _BatchSemanticPort:
    def __init__(self):
        self.calls = []

    def build_batch_semantics(self, stock_codes, decision_date):
        self.calls.append((stock_codes, decision_date))
        return {}


def test_dashboard_service_scans_market_once_then_batches_only_selected_codes():
    events = tuple(
        [
            _dashboard_event(f"P{index:03d}", 10_000 - index, f"buy_{index % 3}")
            for index in range(60)
        ]
        + [
            _dashboard_event(f"N{index:03d}", -10_000 - index, f"sell_{index % 3}")
            for index in range(60)
        ]
    )
    source = BrokerFlowReadSnapshot(
        selected_trading_dates=(date(2026, 7, 3),),
        events=events,
        tracked_branches=(("branch_a", "branch_a"),),
        quality="observed",
        warnings=(),
        source_fingerprint="fixture-v1",
        query_count=2,
        materialized_row_count=len(events),
    )
    repository = _DashboardRepository(source)
    semantic_port = _BatchSemanticPort()
    service = BrokerFlowDashboardQueryService(
        repository,
        semantic_port=semantic_port,
    )
    query = BrokerFlowDashboardQuery(
        period="week",
        scope="top_bottom",
        requested_as_of_date=date(2026, 7, 5),
        limit_per_side=50,
    )

    snapshot = service.load_dashboard_snapshot(query)

    assert repository.calls == [query]
    assert len(snapshot.top_signals) == 50
    assert len(snapshot.bottom_signals) == 50
    assert snapshot.summary.bullish_stock_count == 60
    assert snapshot.summary.bearish_stock_count == 60
    assert snapshot.as_of_date == date(2026, 7, 3)
    assert snapshot.source_fingerprint == "fixture-v1"
    assert snapshot.query_counts == {"repository": 2, "semantic_batch": 1}
    assert len(semantic_port.calls) == 1
    selected_codes, semantic_date = semantic_port.calls[0]
    assert len(selected_codes) == 100
    assert len(set(selected_codes)) == 100
    assert semantic_date == date(2026, 7, 3)


def test_dashboard_service_returns_typed_missing_without_semantic_query():
    source = BrokerFlowReadSnapshot(
        selected_trading_dates=(),
        events=(),
        tracked_branches=(),
        quality="missing",
        warnings=("broker_flows_table_missing",),
        source_fingerprint="",
        query_count=1,
        materialized_row_count=0,
    )
    semantic_port = _BatchSemanticPort()
    query = BrokerFlowDashboardQuery(
        period="week",
        scope="top_bottom",
        requested_as_of_date=date(2026, 7, 5),
        limit_per_side=50,
    )

    snapshot = BrokerFlowDashboardQueryService(
        _DashboardRepository(source), semantic_port=semantic_port
    ).load_dashboard_snapshot(query)

    assert snapshot.quality == "missing"
    assert snapshot.top_signals == ()
    assert snapshot.bottom_signals == ()
    assert snapshot.warnings == ("broker_flows_table_missing",)
    assert semantic_port.calls == []


def test_dashboard_cache_reuses_exact_query_and_invalidates_on_source_change():
    source = BrokerFlowReadSnapshot(
        selected_trading_dates=(date(2026, 7, 3),),
        events=(_dashboard_event("2330", 1000),),
        tracked_branches=(), quality="observed", warnings=(),
        source_fingerprint="fixture-v1", query_count=2, materialized_row_count=1,
    )

    class VersionedRepository(_DashboardRepository):
        version = "v1"

        def source_cache_key(self):
            return self.version

    repository = VersionedRepository(source)
    semantic_port = _BatchSemanticPort()
    service = BrokerFlowDashboardQueryService(repository, semantic_port=semantic_port)
    query = BrokerFlowDashboardQuery(
        period="week", scope="top_bottom_50",
        requested_as_of_date=date(2026, 7, 5), limit_per_side=50,
    )

    first = service.load_dashboard_snapshot(query)
    second = service.load_dashboard_snapshot(query)
    repository.version = "v2"
    third = service.load_dashboard_snapshot(query)

    assert first is second
    assert third is not second
    assert repository.calls == [query, query]
    assert len(semantic_port.calls) == 2
