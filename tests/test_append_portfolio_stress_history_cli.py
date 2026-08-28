from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace

from app_module.portfolio_stress_history import PortfolioStressHistoryReadService
from app_module.portfolio_stress_lab_service import PortfolioStressLabService
from scripts.append_portfolio_stress_history import main


def _write_input(path: Path, *, research_only: bool = True) -> None:
    result = PortfolioStressLabService().evaluate_positions(
        [
            SimpleNamespace(
                is_holding=True,
                stock_code="2330",
                stock_name="台積電",
                quantity=Decimal("10"),
                current_price=Decimal("100.00"),
            )
        ],
        scenario_id="fast_drop",
        as_of_date="2026-08-27",
    )
    payload = result.to_dict()
    payload["research_only"] = research_only
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _args(source: Path, history_db: Path) -> list[str]:
    return ["--input-json", str(source), "--history-db", str(history_db)]


def test_cli_defaults_to_preview_without_creating_history(tmp_path: Path, capsys) -> None:
    source = tmp_path / "stress.json"
    history_db = tmp_path / "stress_history.sqlite"
    _write_input(source)

    assert main(_args(source, history_db)) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["write_performed"] is False
    assert payload["research_only"] is True
    assert not history_db.exists()


def test_cli_confirm_writes_history_and_read_service_can_inspect(tmp_path: Path, capsys) -> None:
    source = tmp_path / "stress.json"
    history_db = tmp_path / "stress_history.sqlite"
    _write_input(source)

    assert main([*_args(source, history_db), "--confirm-save-stress-history"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["write_performed"] is True
    result = PortfolioStressHistoryReadService(history_db).inspect()
    assert result.status == "ready"
    assert len(result.records) == 1


def test_cli_rejects_duplicate_snapshot_without_adding_rows(tmp_path: Path, capsys) -> None:
    source = tmp_path / "stress.json"
    history_db = tmp_path / "stress_history.sqlite"
    _write_input(source)
    args = [*_args(source, history_db), "--confirm-save-stress-history"]

    assert main(args) == 0
    capsys.readouterr()
    assert main(args) == 2
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "rejected"
    assert "already exists" in payload["error"]
    assert len(PortfolioStressHistoryReadService(history_db).inspect().records) == 1


def test_cli_rejects_unsafe_input_without_writing(tmp_path: Path, capsys) -> None:
    source = tmp_path / "unsafe.json"
    history_db = tmp_path / "stress_history.sqlite"
    _write_input(source, research_only=False)

    assert main([*_args(source, history_db), "--confirm-save-stress-history"]) == 2
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "rejected"
    assert "research_only" in payload["error"]
    assert not history_db.exists()
