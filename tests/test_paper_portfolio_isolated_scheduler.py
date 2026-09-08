from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

import pytest

from app_module.paper_portfolio_snapshot_repository import (
    PaperPortfolioPositionSnapshot,
    PaperPortfolioSnapshot,
    PaperPortfolioSnapshotRepository,
)
from scripts.scheduled import run_paper_execution_daily_isolated as eod_adapter
from scripts.scheduled import run_paper_portfolio_daily_isolated as preopen_adapter
from scripts.scheduled import run_formal_input_producer_daily as formal_adapter


class _OpenCalendar:
    def is_official_trading_day(self, _target_date):
        return True, "test_official_schedule_open"


def _make_source_state(path: Path) -> None:
    repository = PaperPortfolioSnapshotRepository(path)
    repository.append(
        PaperPortfolioSnapshot(
            snapshot_id="paper-main-20260712-baseline",
            portfolio_id="paper-main",
            decision_date="2026-07-12",
            source_result_id="source-baseline-1",
            cash=Decimal("80000.00"),
            total_value=Decimal("100000.00"),
            positions=(
                PaperPortfolioPositionSnapshot(
                    stock_code="2330",
                    quantity=1000,
                    mark_price=Decimal("20.00"),
                    market_value=Decimal("20000.00"),
                    weight_bp=2000,
                ),
            ),
        )
    )


def _make_baseline(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "decision_date": "2026-07-12",
                "source_result_id": "source-baseline-1",
                "residual_cash": "80000.00",
                "allocations": [
                    {
                        "stock_code": "2330",
                        "executable_shares": 1000,
                        "reference_price": "20.00",
                        "executable_amount": "20000.00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _make_market(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE daily_prices (日期 TEXT, 證券代號 TEXT, 收盤價 TEXT)"
        )
        connection.execute(
            "INSERT INTO daily_prices VALUES (?, ?, ?)",
            ("20260713", "2330", "21.00"),
        )


def _patch_preopen_paths(
    monkeypatch: pytest.MonkeyPatch,
    *,
    data_root: Path,
    operation_root: Path,
) -> tuple[Path, Path, Path, Path]:
    source_state = data_root / "output" / "paper_portfolio" / "paper_portfolio.sqlite"
    baseline = data_root / "output" / "paper_portfolio" / "baseline_20260712.json"
    market = data_root / "sqlite" / "twstock.db"
    state = operation_root / "paper_portfolio" / "paper_portfolio.sqlite"
    manifest = operation_root / "paper_portfolio" / "state_seed_manifest.json"
    ledger = operation_root / "paper_trade_ledger.sqlite"
    _make_source_state(source_state)
    _make_baseline(baseline)
    _make_market(market)
    monkeypatch.setattr(preopen_adapter, "ROOT", operation_root.parents[1])
    monkeypatch.setattr(preopen_adapter, "DEFAULT_DATA_ROOT", data_root)
    monkeypatch.setattr(preopen_adapter, "SOURCE_STATE_DB", source_state)
    monkeypatch.setattr(preopen_adapter, "SOURCE_BASELINE_PATH", baseline)
    monkeypatch.setattr(preopen_adapter, "OPERATIONAL_ROOT", operation_root)
    monkeypatch.setattr(preopen_adapter, "PAPER_STATE_ROOT", state.parent)
    monkeypatch.setattr(preopen_adapter, "STATE_DB", state)
    monkeypatch.setattr(preopen_adapter, "STATE_SEED_MANIFEST", manifest)
    monkeypatch.setattr(preopen_adapter, "MARKET_DB", market)
    monkeypatch.setattr(preopen_adapter, "LEDGER_DB", ledger)
    return source_state, baseline, market, state


def test_isolated_preopen_seeds_readonly_source_then_calls_public_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "D-source"
    operation_root = tmp_path / "repo" / "output" / "paper_execution_eod_replay"
    source_state, baseline, market, state = _patch_preopen_paths(
        monkeypatch,
        data_root=data_root,
        operation_root=operation_root,
    )
    source_bytes = source_state.read_bytes()
    baseline_bytes = baseline.read_bytes()
    market_bytes = market.read_bytes()
    decision_at = datetime.fromisoformat("2026-07-14T08:30:00+08:00")
    observed = datetime.fromisoformat("2026-07-14T08:31:00+08:00")

    first = preopen_adapter.run_isolated(
        now=observed,
        decision_at=decision_at,
        calendar=_OpenCalendar(),  # type: ignore[arg-type]
    )
    assert first["status"] == "passed"
    assert first["state_db"] == str(state)
    scope = first["isolated_scope"]
    assert isinstance(scope, dict)
    seed = scope["state_seed"]
    assert isinstance(seed, dict)
    assert seed["status"] == "seeded"
    assert seed["seed_method"] == "sqlite_readonly_consistent_backup"
    assert source_state.read_bytes() == source_bytes
    assert baseline.read_bytes() == baseline_bytes
    assert market.read_bytes() == market_bytes
    assert state.is_file()
    seed_manifest_path = operation_root / "paper_portfolio" / "state_seed_manifest.json"
    assert seed_manifest_path.is_file()
    seed_manifest = json.loads(seed_manifest_path.read_text(encoding="utf-8"))
    assert seed_manifest["source"]["read_mode"] == (
        "sqlite_uri_mode_ro_and_query_only"
    )
    assert seed_manifest["source"]["bundle"]["files"][0]["path"] == str(
        source_state.resolve()
    )
    assert seed_manifest["target"]["seed_file_sha256"] == seed["target_file_sha256"]
    state_head_path = operation_root / "paper_portfolio" / "state_head_manifest.json"
    assert state_head_path.is_file()
    state_head = json.loads(state_head_path.read_text(encoding="utf-8"))
    assert state_head["target_file_sha256"] == preopen_adapter._file_hash(state)
    assert state_head["target_file_sha256"] != seed["target_file_sha256"]
    snapshot = PaperPortfolioSnapshotRepository(state).get("paper-main-20260714")
    assert snapshot is not None
    assert snapshot.total_value == Decimal("101000.00")

    second = preopen_adapter.run_isolated(
        now=observed,
        decision_at=decision_at,
        calendar=_OpenCalendar(),  # type: ignore[arg-type]
    )
    second_scope = second["isolated_scope"]
    assert isinstance(second_scope, dict)
    second_seed = second_scope["state_seed"]
    assert isinstance(second_seed, dict)
    assert second_seed["status"] == "existing_verified"
    assert second["snapshot_appended"] is False
    assert source_state.read_bytes() == source_bytes
    assert baseline.read_bytes() == baseline_bytes
    assert market.read_bytes() == market_bytes


def test_scheduled_adapter_main_waits_then_calls_public_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "D-source"
    operation_root = tmp_path / "repo" / "output" / "paper_execution_eod_replay"
    _source_state, _baseline, _market, state = _patch_preopen_paths(
        monkeypatch,
        data_root=data_root,
        operation_root=operation_root,
    )
    public_runner = preopen_adapter.run_paper_portfolio_daily

    def _run_public_runner(**kwargs):
        kwargs["calendar"] = _OpenCalendar()
        return public_runner(**kwargs)

    monkeypatch.setattr(preopen_adapter, "run_paper_portfolio_daily", _run_public_runner)
    monkeypatch.setattr(
        preopen_adapter,
        "_wait_until_taipei_cutoff",
        lambda: datetime.fromisoformat("2026-07-14T08:31:00+08:00"),
    )

    assert preopen_adapter.main([]) == 0
    assert PaperPortfolioSnapshotRepository(state).get("paper-main-20260714") is not None


def test_isolated_preopen_rejects_missing_source_without_creating_repo_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "D-source"
    operation_root = tmp_path / "repo" / "output" / "paper_execution_eod_replay"
    source_state, _baseline, _market, state = _patch_preopen_paths(
        monkeypatch,
        data_root=data_root,
        operation_root=operation_root,
    )
    monkeypatch.setattr(preopen_adapter, "SOURCE_STATE_DB", source_state.with_name("missing.sqlite"))
    result = preopen_adapter.run_isolated(
        now=datetime.fromisoformat("2026-07-14T08:31:00+08:00"),
        decision_at=datetime.fromisoformat("2026-07-14T08:30:00+08:00"),
        calendar=_OpenCalendar(),  # type: ignore[arg-type]
    )
    assert result["status"] == "blocked"
    assert any("source" in str(item) for item in result["blockers"])
    assert not state.exists()


def test_isolated_preopen_rejects_changed_repository_state_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "D-source"
    operation_root = tmp_path / "repo" / "output" / "paper_execution_eod_replay"
    _source_state, _baseline, _market, state = _patch_preopen_paths(
        monkeypatch,
        data_root=data_root,
        operation_root=operation_root,
    )
    observed = datetime.fromisoformat("2026-07-14T08:31:00+08:00")
    decision_at = datetime.fromisoformat("2026-07-14T08:30:00+08:00")
    assert preopen_adapter.run_isolated(
        now=observed,
        decision_at=decision_at,
        calendar=_OpenCalendar(),  # type: ignore[arg-type]
    )["status"] == "passed"
    with state.open("ab") as stream:
        stream.write(b"tamper")
    result = preopen_adapter.run_isolated(
        now=observed,
        decision_at=decision_at,
        calendar=_OpenCalendar(),  # type: ignore[arg-type]
    )
    assert result["status"] == "blocked"
    assert "target changed" in str(result["blockers"])


def test_registered_paths_use_one_repository_state_for_eod_and_formal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert preopen_adapter.STATE_DB == eod_adapter.STATE_DB
    assert preopen_adapter.LEDGER_DB == eod_adapter.LEDGER_DB
    monkeypatch.setenv("FORMAL_DAILY_PAPER_SNAPSHOT_DB", str(preopen_adapter.STATE_DB))
    paths = formal_adapter._build_paths(
        source_paths={},
        publication_root=Path("output") / "formal-test-publication",
    )
    assert paths.paper_snapshot_db_path == preopen_adapter.STATE_DB.resolve()
    assert paths.paper_trade_ledger_db_path == preopen_adapter.LEDGER_DB.resolve()


def test_eod_scope_preflight_reads_seeded_repository_state_after_preopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "D-source"
    operation_root = tmp_path / "repo" / "output" / "paper_execution_eod_replay"
    source_state, _baseline, market, state = _patch_preopen_paths(
        monkeypatch,
        data_root=data_root,
        operation_root=operation_root,
    )
    recommendation_root = data_root / "output" / "recommendation" / "runs"
    recommendation_root.mkdir(parents=True)
    assert preopen_adapter.run_isolated(
        now=datetime.fromisoformat("2026-07-14T08:31:00+08:00"),
        decision_at=datetime.fromisoformat("2026-07-14T08:30:00+08:00"),
        calendar=_OpenCalendar(),  # type: ignore[arg-type]
    )["status"] == "passed"

    monkeypatch.setattr(eod_adapter, "ROOT", operation_root.parents[1])
    monkeypatch.setattr(eod_adapter, "DEFAULT_DATA_ROOT", data_root)
    monkeypatch.setattr(eod_adapter, "SOURCE_STATE_DB", source_state)
    monkeypatch.setattr(eod_adapter, "OPERATIONAL_ROOT", operation_root)
    monkeypatch.setattr(eod_adapter, "PAPER_STATE_ROOT", state.parent)
    monkeypatch.setattr(eod_adapter, "STATE_DB", state)
    monkeypatch.setattr(
        eod_adapter,
        "STATE_SEED_MANIFEST",
        state.parent / "state_seed_manifest.json",
    )
    monkeypatch.setattr(eod_adapter, "MARKET_DB", market)
    monkeypatch.setattr(eod_adapter, "RECOMMENDATION_ROOT", recommendation_root)
    monkeypatch.setattr(eod_adapter, "CANDIDATE_ROOT", operation_root / "candidates")
    monkeypatch.setattr(eod_adapter, "RECEIPT_ROOT", operation_root / "receipts")
    monkeypatch.setattr(eod_adapter, "LEDGER_DB", operation_root / "paper_trade_ledger.sqlite")
    monkeypatch.setattr(eod_adapter, "SCOPE_MANIFEST", operation_root / "scope_manifest_v2.json")
    observed = eod_adapter._scope_preflight()
    assert observed["state"]["path"] == str(state.resolve())  # type: ignore[index]
    assert observed["state_seed"]["status"] == "existing_verified"  # type: ignore[index]
    assert observed["market"]["path"] == str(market.resolve())  # type: ignore[index]


def test_isolated_adapter_blocks_before_taipei_cutoff_without_reading_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _unexpected_source_access() -> dict[str, Path]:
        raise AssertionError("preopen source must not be opened before Taipei cutoff")

    monkeypatch.setattr(preopen_adapter, "_validate_scope", _unexpected_source_access)
    result = preopen_adapter.run_isolated(
        now=datetime.fromisoformat("2026-07-14T07:59:59+08:00"),
        decision_at=datetime.fromisoformat("2026-07-14T08:30:00+08:00"),
    )
    assert result["status"] == "waiting_for_taipei_cutoff"
    assert result["blockers"] == ["taipei_preopen_cutoff_not_reached"]
    assert result["writes_D_source"] is False


def test_scheduled_wakeup_waits_on_injected_clock_until_taipei_cutoff() -> None:
    readings = iter(
        (
            datetime.fromisoformat("2026-07-14T07:30:00+08:00"),
            datetime.fromisoformat("2026-07-14T08:29:59+08:00"),
            datetime.fromisoformat("2026-07-14T08:30:00+08:00"),
        )
    )
    sleeps: list[float] = []

    reached = preopen_adapter._wait_until_taipei_cutoff(
        now_fn=lambda: next(readings),
        sleep_fn=sleeps.append,
    )

    assert reached == datetime.fromisoformat("2026-07-14T08:30:00+08:00")
    assert sleeps == [60.0, 1.0]


def test_paper_portfolio_schedule_wakes_before_or_at_taipei_cutoff_in_both_dst_modes() -> None:
    pacific = ZoneInfo("America/Los_Angeles")
    for local_day in ("2026-01-12", "2026-07-13"):
        trigger = datetime.fromisoformat(
            f"{local_day}T{preopen_adapter.SCHEDULED_WAKE_LOCAL_TIME}:00"
        ).replace(
            tzinfo=pacific
        )
        taipei = trigger.astimezone(ZoneInfo("Asia/Taipei"))
        if local_day == "2026-01-12":
            assert taipei.timetz().replace(tzinfo=None) == datetime.strptime(
                "08:30", "%H:%M"
            ).time()
        else:
            assert taipei.timetz().replace(tzinfo=None) == datetime.strptime(
                "07:30", "%H:%M"
            ).time()
        assert taipei.date().isoformat() > local_day
