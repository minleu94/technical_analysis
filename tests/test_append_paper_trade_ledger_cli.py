from __future__ import annotations

import json
from pathlib import Path

from app_module.paper_trade_ledger import PaperTradeLedgerRepository
from scripts.append_paper_trade_ledger import main


def _write_input(path: Path, *, execution_gap: object = 8) -> None:
    path.write_text(
        json.dumps(
            {
                "fills": [
                    {
                        "fill_id": "fill-1",
                        "order_id": "order-1",
                        "portfolio_id": "paper-main",
                        "event_date": "2026-08-27",
                        "stock_code": "2330",
                        "side": "buy",
                        "requested_quantity": 1000,
                        "filled_quantity": 1000,
                        "reference_price": "100.00",
                        "fill_price": "100.08",
                        "commission": "15.00",
                        "tax": "0.00",
                        "slippage_cost": "8.00",
                        "turnover_bp": 120,
                        "execution_gap_bp": execution_gap,
                        "status": "filled",
                        "source_event_id": "event-1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_cli_defaults_to_preview_without_creating_ledger(tmp_path: Path, capsys) -> None:
    source = tmp_path / "fills.json"
    ledger = tmp_path / "paper_trade.sqlite"
    _write_input(source)

    assert main(["--input-json", str(source), "--ledger-db", str(ledger)]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["fill_count"] == 1
    assert payload["total_cost"] == "23.00"
    assert payload["write_performed"] is False
    assert not ledger.exists()


def test_cli_requires_explicit_confirmation_for_write(tmp_path: Path, capsys) -> None:
    source = tmp_path / "fills.json"
    ledger = tmp_path / "paper_trade.sqlite"
    _write_input(source)

    assert main(
        [
            "--input-json",
            str(source),
            "--ledger-db",
            str(ledger),
            "--confirm-append-paper-ledger",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["write_performed"] is True
    assert len(PaperTradeLedgerRepository(ledger).list()) == 1


def test_cli_rejects_missing_execution_gap_without_writing(tmp_path: Path, capsys) -> None:
    source = tmp_path / "fills.json"
    ledger = tmp_path / "paper_trade.sqlite"
    _write_input(source, execution_gap=None)

    assert main(
        [
            "--input-json",
            str(source),
            "--ledger-db",
            str(ledger),
            "--confirm-append-paper-ledger",
        ]
    ) == 2
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "rejected"
    assert "execution_gap_bp" in payload["error"]
    assert not ledger.exists()


def test_cli_rejects_duplicate_fill_as_atomic_batch(tmp_path: Path, capsys) -> None:
    source = tmp_path / "fills.json"
    ledger = tmp_path / "paper_trade.sqlite"
    _write_input(source)
    assert main(
        [
            "--input-json",
            str(source),
            "--ledger-db",
            str(ledger),
            "--confirm-append-paper-ledger",
        ]
    ) == 0
    capsys.readouterr()
    source.write_text(
        json.dumps(
            {
                "fills": [
                    json.loads(source.read_text(encoding="utf-8"))["fills"][0],
                    json.loads(source.read_text(encoding="utf-8"))["fills"][0],
                ]
            }
        ),
        encoding="utf-8",
    )

    assert main(
        [
            "--input-json",
            str(source),
            "--ledger-db",
            str(ledger),
            "--confirm-append-paper-ledger",
        ]
    ) == 2
    json.loads(capsys.readouterr().out)
    assert len(PaperTradeLedgerRepository(ledger).list()) == 1
