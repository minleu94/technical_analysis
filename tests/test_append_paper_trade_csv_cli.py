from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app_module.paper_trade_ledger import PaperTradeLedgerRepository
from scripts.export_paper_trade_csv_template import main as export_template_main
from scripts.append_paper_trade_csv import main


_HEADER = (
    "fill_id,order_id,portfolio_id,event_date,stock_code,side,requested_quantity,"
    "filled_quantity,reference_price,fill_price,commission,tax,slippage_cost,"
    "turnover_bp,execution_gap_bp,status,source_event_id,override_reason\n"
)
_ROW = "fill-1,order-1,paper-main,2026-08-27,2330,buy,1000,1000,100.00,100.08,15.00,0.00,8.00,120,8,filled,broker-1,\n"


def _write(path: Path, body: str = _ROW) -> None:
    path.write_text(_HEADER + body, encoding="utf-8-sig")


def _args(source: Path, ledger: Path) -> list[str]:
    return ["--input-csv", str(source), "--ledger-db", str(ledger)]


def test_csv_cli_defaults_to_preview_without_creating_ledger(tmp_path: Path, capsys) -> None:
    source = tmp_path / "paper_fills.csv"
    ledger = tmp_path / "paper_portfolio" / "paper_trade_ledger.sqlite"
    _write(source)

    assert main(_args(source, ledger)) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["row_count"] == 1
    assert payload["valid_row_count"] == 1
    assert payload["total_cost"] == "23.00"
    assert payload["write_performed"] is False
    assert not ledger.exists()
    assert not ledger.parent.exists()


def test_csv_cli_confirm_appends_paper_ledger(tmp_path: Path, capsys) -> None:
    source = tmp_path / "paper_fills.csv"
    ledger = tmp_path / "paper_portfolio" / "paper_trade_ledger.sqlite"
    _write(source)

    assert main([*_args(source, ledger), "--confirm-append-paper-ledger"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["write_performed"] is True
    assert [fill.fill_id for fill in PaperTradeLedgerRepository(ledger).list()] == ["fill-1"]


def test_csv_cli_rejects_invalid_rows_without_writing(tmp_path: Path, capsys) -> None:
    source = tmp_path / "invalid.csv"
    ledger = tmp_path / "paper_trade.sqlite"
    _write(source, _ROW.replace(",filled,", ",filled,").replace(",1000,100.00,", ",500,100.00,"))

    assert main([*_args(source, ledger), "--confirm-append-paper-ledger"]) == 2
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "rejected"
    assert payload["invalid_row_count"] == 1
    assert not ledger.exists()


def test_csv_cli_rejects_missing_required_headers(tmp_path: Path, capsys) -> None:
    source = tmp_path / "missing.csv"
    ledger = tmp_path / "paper_trade.sqlite"
    source.write_text("fill_id,stock_code\nfill-1,2330\n", encoding="utf-8")

    assert main(_args(source, ledger)) == 2
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "rejected"
    assert "columns missing" in payload["error"]
    assert not ledger.exists()


def test_export_template_cli_writes_headers_only_without_ledger(tmp_path: Path, capsys) -> None:
    template = tmp_path / "paper_fills_template.csv"

    assert export_template_main(["--output-csv", str(template)]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "created"
    assert payload["row_count"] == 0
    assert payload["writes_paper_ledger"] is False
    assert template.read_text(encoding="utf-8-sig").startswith("fill_id,order_id,portfolio_id,event_date")


def test_export_template_cli_refuses_overwrite_without_flag(tmp_path: Path, capsys) -> None:
    template = tmp_path / "paper_fills_template.csv"
    template.write_text("existing\n", encoding="utf-8")

    assert export_template_main(["--output-csv", str(template)]) == 2
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "rejected"
    assert "already exists" in payload["error"]
    assert template.read_text(encoding="utf-8") == "existing\n"


def test_export_template_help_is_safe_on_cp1252_console() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "export_paper_trade_csv_template.py"
    environment = dict(os.environ)
    environment["PYTHONIOENCODING"] = "cp1252"

    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=script.parents[1],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0
    assert "允許覆寫" in completed.stdout.decode("utf-8")


@pytest.mark.parametrize("script_name", ["append_paper_trade_csv.py", "append_paper_trade_ledger.py"])
def test_paper_trade_append_help_is_safe_on_cp1252_console(script_name: str) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / script_name
    environment = dict(os.environ)
    environment["PYTHONIOENCODING"] = "cp1252"

    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=script.parents[1],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0
    assert "Paper Trade Ledger" in completed.stdout.decode("utf-8")
