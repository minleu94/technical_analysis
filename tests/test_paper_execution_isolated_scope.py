from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import subprocess
import tempfile

import pytest

from data_module.paper_daily_execution_producer import (
    PaperExecutionProducerError,
    _prepare_output_root,
)
from scripts.scheduled import run_paper_execution_daily_isolated as isolated
from scripts.scheduled.paper_portfolio_state_isolation import (
    ensure_repo_state_from_readonly_source,
)


def _make_directory_junction(link: Path, target: Path) -> None:
    """在 Windows 建立真正 junction；其他平台使用目錄 symlink。"""

    if os.name != "nt":
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as error:
            pytest.skip(f"directory reparse point unavailable: {error}")
        return
    completed = subprocess.run(
        [
            "cmd.exe",
            "/d",
            "/c",
            "mklink",
            "/J",
            str(link),
            str(target),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode == 0:
        return
    output = f"{completed.stdout}\n{completed.stderr}".casefold()
    if any(
        marker in output
        for marker in (
            "access is denied",
            "privilege",
            "not supported",
            "requires elevation",
        )
    ):
        pytest.skip(f"directory junction unavailable: {output.strip()}")
    pytest.fail(f"directory junction command failed: {output.strip()}")


def test_paper_output_requires_explicit_controlled_root_for_non_temp_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path / "other-temp"))
    with pytest.raises(PaperExecutionProducerError, match="under OS TEMP"):
        _prepare_output_root(tmp_path / "unscoped")

    controlled = tmp_path / "controlled"
    run_root = controlled / "run-1"
    prepared = _prepare_output_root(run_root, controlled_root=controlled)
    assert prepared == run_root.resolve()
    assert prepared.is_dir()

    with pytest.raises(PaperExecutionProducerError, match="direct child"):
        _prepare_output_root(
            controlled / "nested" / "run-2",
            controlled_root=controlled,
        )


def test_operation_root_junction_outside_repo_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repository_output = repo / "output"
    repository_output.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    operation_link = repository_output / "paper_execution_eod_replay"
    _make_directory_junction(operation_link, outside)

    source_root = tmp_path / "source"
    monkeypatch.setattr(isolated, "ROOT", repo)
    monkeypatch.setattr(isolated, "DEFAULT_DATA_ROOT", source_root)
    monkeypatch.setattr(isolated, "OPERATIONAL_ROOT", operation_link)
    monkeypatch.setattr(isolated, "CANDIDATE_ROOT", operation_link / "candidates")
    monkeypatch.setattr(isolated, "RECEIPT_ROOT", operation_link / "receipts")
    monkeypatch.setattr(isolated, "LEDGER_DB", operation_link / "paper_trade_ledger.sqlite")
    monkeypatch.setattr(isolated, "SCOPE_MANIFEST", operation_link / "scope_manifest.json")

    with pytest.raises(RuntimeError, match="operation root"):
        isolated._validate_write_scope()


def test_isolated_adapter_ignores_path_environment_and_keeps_ledger_empty_until_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "source"
    source_state_db = data_root / "output" / "paper_portfolio" / "paper_portfolio.sqlite"
    market_db = data_root / "sqlite" / "twstock.db"
    recommendation_root = data_root / "output" / "recommendation" / "runs"
    source_state_db.parent.mkdir(parents=True)
    market_db.parent.mkdir(parents=True)
    recommendation_root.mkdir(parents=True)
    with sqlite3.connect(source_state_db) as connection:
        connection.execute(
            "CREATE TABLE paper_portfolio_snapshots (snapshot_id TEXT)"
        )
        connection.execute(
            "CREATE TABLE paper_portfolio_positions (snapshot_id TEXT)"
        )
    with sqlite3.connect(market_db) as connection:
        connection.execute("CREATE TABLE daily_prices (日期 TEXT)")

    repo = tmp_path / "repo"
    repo_output = repo / "output"
    repo_output.mkdir(parents=True)
    operation_root = repo_output / "operation"
    candidate_root = operation_root / "candidates"
    receipt_root = operation_root / "receipts"
    ledger_db = operation_root / "paper_trade_ledger.sqlite"
    state_db = operation_root / "paper_portfolio" / "paper_portfolio.sqlite"
    scope_manifest = operation_root / "scope_manifest.json"
    for name, value in {
        "DEFAULT_DATA_ROOT": data_root,
        "OPERATIONAL_ROOT": operation_root,
        "CANDIDATE_ROOT": candidate_root,
        "RECEIPT_ROOT": receipt_root,
        "LEDGER_DB": ledger_db,
        "SOURCE_STATE_DB": source_state_db,
        "PAPER_STATE_ROOT": state_db.parent,
        "STATE_SEED_MANIFEST": state_db.parent / "state_seed_manifest.json",
        "STATE_DB": state_db,
        "MARKET_DB": market_db,
        "RECOMMENDATION_ROOT": recommendation_root,
        "SCOPE_MANIFEST": scope_manifest,
        }.items():
            monkeypatch.setattr(isolated, name, value)
    monkeypatch.setattr(isolated, "ROOT", repo)
    ensure_repo_state_from_readonly_source(
        source=source_state_db,
        target=state_db,
        manifest_path=state_db.parent / "state_seed_manifest.json",
        observed_at=datetime.now(timezone.utc),
    )
    monkeypatch.setenv("PAPER_EXECUTION_LEDGER_DB", r"D:\unsafe\ledger.sqlite")
    monkeypatch.setenv("PAPER_EXECUTION_OUTPUT_ROOT", r"D:\unsafe\output")
    monkeypatch.setattr(
        isolated,
        "_refresh_calendar_cache",
        lambda observed: {
            "status": "cache_valid",
            "calendar_year": 2026,
            "refresh_attempted": False,
            "network_attempts": 0,
        },
    )
    monkeypatch.setattr(
        isolated,
        "_refresh_temporary_closure_events",
        lambda observed: {
            "status": "temporary_closure_discovery_blocked",
            "calendar_year": 2026,
            "network_attempts": 0,
            "detail_requests": 0,
            "reason": "test_no_network",
            "events": [],
        },
    )

    observed: dict[str, object] = {}

    def fake_runner(paths: object, **kwargs: object) -> dict[str, object]:
        observed["paths"] = paths
        observed.update(kwargs)
        return {
            "status": "waiting_for_execution_session",
            "formal_credit": False,
        }

    monkeypatch.setattr(isolated, "run_paper_execution_daily_from_queue", fake_runner)
    result = isolated.run_isolated()

    paths = observed["paths"]
    assert isinstance(paths, isolated.PaperExecutionPaths)
    assert paths.state_db == state_db
    assert paths.market_db == market_db
    assert paths.ledger_db == ledger_db
    assert paths.controlled_output_root == candidate_root
    assert paths.output_root.parent == candidate_root
    assert observed["recommendation_root"] == recommendation_root
    assert observed["receipt_root"] == receipt_root
    calendar = observed["calendar"]
    assert isinstance(calendar, isolated.OfficialTradingCalendar)
    assert calendar.calendar_cache_path == operation_root / "calendar_cache"
    assert calendar.temporary_closure_path == operation_root / "calendar_cache"
    assert observed["confirm_append"] is True
    assert result["status"] == "waiting_for_execution_session"
    scope = result["isolated_scope"]
    assert isinstance(scope, dict)
    assert scope["append_target"] == str(ledger_db.resolve())
    assert scope["append_target_is_d_source"] is False
    assert scope["environment_path_overrides_ignored"] is True
    source_observation = scope["source_observation"]
    assert isinstance(source_observation, dict)
    assert source_observation["calendar_refresh"]["status"] == "cache_valid"  # type: ignore[index]
    assert source_observation["temporary_closure_refresh"]["status"] == (  # type: ignore[index]
        "temporary_closure_discovery_blocked"
    )
    refresh_receipt = source_observation["calendar_refresh_receipt"]  # type: ignore[index]
    assert isinstance(refresh_receipt, dict)
    assert Path(str(refresh_receipt["path"])).is_file()
    assert ledger_db.exists() is False
    manifest = json.loads(scope_manifest.read_text(encoding="utf-8"))
    assert manifest["safety"]["formal_credit"] is False
    assert manifest["writable"]["ledger_db"] == str(ledger_db.resolve())


def test_calendar_refresh_uses_taipei_year_and_operation_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation_root = tmp_path / "repo-output" / "paper"
    monkeypatch.setattr(isolated, "OPERATIONAL_ROOT", operation_root)
    observed = datetime(2026, 12, 31, 16, 30, tzinfo=timezone.utc)
    captured: dict[str, object] = {}

    def fake_refresh(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "status": "cache_valid",
            "calendar_year": 2027,
            "refresh_attempted": False,
            "network_attempts": 0,
        }

    monkeypatch.setattr(isolated, "refresh_twse_calendar_cache", fake_refresh)
    result = isolated._refresh_calendar_cache(observed)

    assert result["status"] == "cache_valid"
    assert captured["calendar_year"] == 2027
    assert captured["cache_root"] == operation_root / "calendar_cache"
    assert captured["allowed_root"] == operation_root.resolve()
    assert captured["observed_at"] == observed
