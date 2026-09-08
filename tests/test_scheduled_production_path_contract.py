from __future__ import annotations

from pathlib import Path

import pytest

from scripts.scheduled import run_formal_input_producer_daily as formal_runner


ROOT = Path(__file__).resolve().parents[1]
SCHEDULED = ROOT / "scripts" / "scheduled"


def _clear_formal_path_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        *formal_runner._REQUIRED_SOURCE_ENV,
        "FORMAL_DAILY_RULE_SOURCE_ROOT",
        "FORMAL_DAILY_FORMAL_LEDGER_PATH",
        "FORMAL_DAILY_FORMAL_RULE_HISTORY_PATH",
        "FORMAL_DAILY_FORMAL_SECTOR_PATH",
        "FORMAL_DAILY_PIT_EXPECTED_UNIVERSE",
        "FORMAL_DAILY_PAPER_SNAPSHOT_DB",
        "FORMAL_DAILY_PAPER_TRADE_LEDGER_DB",
        "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH",
        "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH",
        "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH",
        "BALDR_ML_PIT_EXPECTED_UNIVERSE_PATH",
        "BALDR_ML_PAPER_PORTFOLIO_SNAPSHOT_DB_PATH",
        "BALDR_ML_PAPER_TRADE_LEDGER_DB_PATH",
        "FORMAL_DAILY_MARKET_DB",
    ):
        monkeypatch.delenv(name, raising=False)


def test_scheduled_cmds_bind_one_paper_ledger_and_the_same_snapshot() -> None:
    portfolio_cmd = (
        SCHEDULED / "run_paper_portfolio_daily.cmd"
    ).read_text(encoding="utf-8")
    formal_cmd = (
        SCHEDULED / "run_formal_input_producer_daily.cmd"
    ).read_text(encoding="utf-8")

    assert "run_paper_portfolio_daily_isolated.py" in portfolio_cmd
    assert (
        'set "REPO_PAPER_STATE_DB=%REPO_PAPER_OPERATION_ROOT%\\paper_portfolio\\'
        'paper_portfolio.sqlite"'
    ) in portfolio_cmd
    assert (
        'set "PAPER_EXECUTION_LEDGER_DB=%REPO_PAPER_OPERATION_ROOT%\\paper_trade_ledger.sqlite"'
    ) in portfolio_cmd
    assert 'scripts\\run_paper_portfolio_daily.py" --output-root "%OUTPUT_ROOT%"' not in portfolio_cmd
    assert (
        'set "PAPER_EXECUTION_LEDGER_DB=%OUTPUT_ROOT%\\paper_portfolio\\'
        'paper_trade_ledger.sqlite"'
    ) not in portfolio_cmd
    assert (
        'set "FORMAL_DAILY_PAPER_SNAPSHOT_DB=%REPO_ROOT%\\output\\'
        'paper_execution_eod_replay\\paper_portfolio\\paper_portfolio.sqlite"'
    ) in formal_cmd
    assert (
        'set "FORMAL_DAILY_PAPER_TRADE_LEDGER_DB=%REPO_ROOT%\\output\\'
        'paper_execution_eod_replay\\paper_trade_ledger.sqlite"'
    ) in formal_cmd
    assert (
        'set "FORMAL_DAILY_MARKET_DB=%DATA_ROOT%\\sqlite\\twstock.db"'
    ) in formal_cmd


def test_scheduled_formal_paths_match_preopen_and_eod_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_formal_path_environment(monkeypatch)
    data_root = tmp_path / "data"
    output_root = data_root / "output"
    monkeypatch.setenv("DATA_ROOT", str(data_root))
    monkeypatch.setenv("OUTPUT_ROOT", str(output_root))
    repository_state = (
        ROOT
        / "output"
        / "paper_execution_eod_replay"
        / "paper_portfolio"
        / "paper_portfolio.sqlite"
    ).resolve()
    monkeypatch.setenv("FORMAL_DAILY_PAPER_SNAPSHOT_DB", str(repository_state))

    observed_paths: list[formal_runner.DailyFormalInputPaths] = []

    def fake_producer(
        paths: formal_runner.DailyFormalInputPaths,
    ) -> dict[str, object]:
        observed_paths.append(paths)
        return {
            "status": "blocked",
            "formal_ready_input_count": 0,
            "formal_consumer_compatible_count": 0,
            "machine_candidate_input_count": 0,
            "inputs": {},
            "blockers": ["test_source_missing"],
        }

    monkeypatch.setattr(formal_runner, "run_daily_formal_input_producer", fake_producer)
    publication_root = tmp_path / "publication"
    status, exit_code = formal_runner.run_from_environment(
        publication_root=publication_root,
        status_root=publication_root / "scheduler",
    )

    assert exit_code == 2
    assert len(observed_paths) == 1
    paths = observed_paths[0]
    assert paths.paper_snapshot_db_path == repository_state
    assert paths.paper_trade_ledger_db_path == (
        ROOT / "output" / "paper_execution_eod_replay" / "paper_trade_ledger.sqlite"
    ).resolve()
    assert paths.market_db == (data_root / "sqlite" / "twstock.db").resolve()

    configuration = status["scheduled_source_configuration"]
    assert isinstance(configuration, dict)
    assert configuration["paper_snapshot_db_path"] == str(
        paths.paper_snapshot_db_path
    )
    assert configuration["paper_snapshot_read_mode"] == (
        "sqlite_mode_ro_query_only"
    )
    assert configuration["paper_trade_ledger_path"] == str(
        paths.paper_trade_ledger_db_path
    )


def test_scheduled_path_status_is_durable_and_does_not_claim_a_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_formal_path_environment(monkeypatch)
    data_root = tmp_path / "data"
    monkeypatch.setenv("DATA_ROOT", str(data_root))
    monkeypatch.setenv("OUTPUT_ROOT", str(data_root / "output"))
    monkeypatch.setattr(
        formal_runner,
        "run_daily_formal_input_producer",
        lambda _paths: {
            "status": "candidate_only",
            "formal_ready_input_count": 0,
            "formal_consumer_compatible_count": 0,
            "machine_candidate_input_count": 1,
            "inputs": {},
            "blockers": ["paper_fill_source_missing"],
        },
    )

    publication_root = tmp_path / "publication"
    status, exit_code = formal_runner.run_from_environment(
        publication_root=publication_root,
        status_root=publication_root / "scheduler",
    )

    assert exit_code == 2
    assert status["writes_formal_controlled_paths"] is False
    assert status["scheduled_source_configuration"]["paper_snapshot_read_mode"] == (
        "sqlite_mode_ro_query_only"
    )
    stored = publication_root / "scheduler" / "latest_status.json"
    assert stored.is_file()
    assert stored.read_text(encoding="utf-8").strip()
