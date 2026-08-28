from __future__ import annotations

from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import sqlite3

from app_module.paper_equal_weight_benchmark_ledger import EqualWeightBenchmarkLedger
from app_module.paper_portfolio_snapshot_repository import (
    PaperPortfolioPositionSnapshot,
    PaperPortfolioSnapshot,
    PaperPortfolioSnapshotRepository,
)
import scripts.build_paper_equal_weight_benchmark as benchmark_builder
from scripts.build_paper_equal_weight_benchmark import main


def _baseline(path: Path, *, decision_date: str = "2026-08-20") -> None:
    path.write_text(
        json.dumps(
            {
                "decision_date": decision_date,
                "source_result_id": "recommendation-1",
                "residual_cash": "800.00",
                "research_only": True,
                "writes_positions_db": False,
                "broker_order_allowed": False,
                "auto_rebalance_allowed": False,
                "allocations": [
                    {
                        "stock_code": "2330",
                        "reference_price": "100.00",
                        "executable_shares": 1,
                        "executable_amount": "100.00",
                    },
                    {
                        "stock_code": "2317",
                        "reference_price": "50.00",
                        "executable_shares": 2,
                        "executable_amount": "100.00",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def _state(path: Path, *, first_date: str = "2026-08-20") -> None:
    repository = PaperPortfolioSnapshotRepository(path)
    for snapshot_id, decision_date, total in (
        ("paper-main-20260820", first_date, "1000.00"),
        ("paper-main-20260821", "2026-08-21", "1010.00"),
    ):
        repository.append(
            PaperPortfolioSnapshot(
                snapshot_id=snapshot_id,
                portfolio_id="paper-main",
                decision_date=decision_date,
                source_result_id="recommendation-1",
                cash=Decimal("800.00"),
                total_value=Decimal(total),
                positions=(
                    PaperPortfolioPositionSnapshot(
                        stock_code="2330",
                        quantity=1,
                        mark_price=Decimal("100.00"),
                        market_value=Decimal("100.00"),
                        weight_bp=1000,
                    ),
                ),
            )
        )


def _market(path: Path, *, include_prices: bool = True) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE daily_prices (證券代號 TEXT, 日期 TEXT, 收盤價 TEXT)"
        )
        if include_prices:
            connection.executemany(
                "INSERT INTO daily_prices VALUES (?, ?, ?)",
                (
                    ("2330", "20260820", "101.00"),
                    ("2317", "20260820", "49.00"),
                ),
            )


def _args(tmp_path: Path, *, output: Path) -> list[str]:
    return [
        "--baseline",
        str(tmp_path / "baseline.json"),
        "--state-db",
        str(tmp_path / "state.sqlite"),
        "--market-db",
        str(tmp_path / "market.sqlite"),
        "--output-ledger",
        str(output),
    ]


def test_benchmark_cli_preview_is_read_only(tmp_path: Path, capsys) -> None:
    _baseline(tmp_path / "baseline.json")
    _state(tmp_path / "state.sqlite")
    _market(tmp_path / "market.sqlite")
    output = tmp_path / "benchmark.sqlite"

    assert main(_args(tmp_path, output=output)) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "preview"
    assert payload["observation_count"] == 2
    assert payload["constituents"] == ["2317", "2330"]
    assert payload["write_performed"] is False
    assert not output.exists()


def test_benchmark_cli_confirm_writes_new_ledger(tmp_path: Path, capsys) -> None:
    _baseline(tmp_path / "baseline.json")
    _state(tmp_path / "state.sqlite")
    _market(tmp_path / "market.sqlite")
    output = tmp_path / "benchmark.sqlite"

    assert main([*_args(tmp_path, output=output), "--confirm-build-paper-benchmark"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "built"
    assert payload["write_performed"] is True
    entries = EqualWeightBenchmarkLedger(output).list("paper-main-equal")
    assert [entry.decision_date for entry in entries] == ["2026-08-20", "2026-08-21"]
    assert entries[-1].total_value == Decimal("995.00")


def test_benchmark_cli_rejects_misaligned_snapshot_baseline(tmp_path: Path, capsys) -> None:
    _baseline(tmp_path / "baseline.json")
    _state(tmp_path / "state.sqlite", first_date="2026-08-19")
    _market(tmp_path / "market.sqlite")
    output = tmp_path / "benchmark.sqlite"

    assert main(_args(tmp_path, output=output)) == 2
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "rejected"
    assert "aligned first date" in payload["error"]
    assert not output.exists()


def test_benchmark_cli_rejects_missing_causal_price(tmp_path: Path, capsys) -> None:
    _baseline(tmp_path / "baseline.json")
    _state(tmp_path / "state.sqlite")
    _market(tmp_path / "market.sqlite", include_prices=False)
    output = tmp_path / "benchmark.sqlite"

    assert main(_args(tmp_path, output=output)) == 2
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "rejected"
    assert "missing causal T-1 benchmark prices" in payload["error"]
    assert not output.exists()


def test_benchmark_cli_rejects_future_snapshot_dates(tmp_path: Path, capsys, monkeypatch) -> None:
    _baseline(tmp_path / "baseline.json")
    _state(tmp_path / "state.sqlite")
    _market(tmp_path / "market.sqlite")
    output = tmp_path / "benchmark.sqlite"
    monkeypatch.setattr(benchmark_builder, "paper_portfolio_today", lambda: date(2026, 8, 20))

    assert main(_args(tmp_path, output=output)) == 2
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "rejected"
    assert "future-dated observations" in payload["error"]
    assert not output.exists()


def test_benchmark_cli_never_overwrites_existing_ledger(tmp_path: Path, capsys) -> None:
    _baseline(tmp_path / "baseline.json")
    _state(tmp_path / "state.sqlite")
    _market(tmp_path / "market.sqlite")
    output = tmp_path / "benchmark.sqlite"
    output.write_bytes(b"existing")

    assert main([*_args(tmp_path, output=output), "--confirm-build-paper-benchmark"]) == 2
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "rejected"
    assert "already exists" in payload["error"]
    assert output.read_bytes() == b"existing"
