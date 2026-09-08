from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
import gc
import json
from pathlib import Path
import sqlite3
from typing import Any
from zoneinfo import ZoneInfo

import pytest

import data_module.formal_daily_input_producer as formal_daily_input_producer_module
from app_module.paper_portfolio_snapshot_repository import (
    PaperPortfolioSnapshotRepository,
)
from app_module.paper_trade_ledger import PaperTradeLedgerRepository
from data_module.formal_daily_input_producer import (
    DailyFormalInputPaths,
    run_daily_formal_input_producer,
)
from data_module.paper_daily_execution_producer import (
    PaperExecutionPaths,
    run_paper_execution_daily_from_queue,
)
from data_module.official_trading_calendar import OfficialTradingCalendar
from scripts.run_paper_portfolio_daily import run as run_paper_preopen
from tests.test_prospective_rule_only_decision import _clock


TAIPEI = ZoneInfo("Asia/Taipei")
DECISION_DATE = "2026-09-04"
EXECUTION_DATE = "2026-09-07"
NEXT_SNAPSHOT_DATE = "2026-09-08"
FORMAL_OBSERVED = datetime(2026, 9, 9, 9, 5, tzinfo=TAIPEI)
EOD_OBSERVED = datetime(2026, 9, 7, 15, 0, tzinfo=TAIPEI)


class _ChainCalendar(OfficialTradingCalendar):
    """隔離測試的官方日曆證據；未列日期不以 weekday 推定。"""

    _open_dates = {
        date(2026, 9, 4),
        date(2026, 9, 7),
        date(2026, 9, 8),
        date(2026, 9, 9),
    }

    def is_official_trading_day(
        self,
        target_date: date,
        allow_online_probe: bool = True,
    ) -> tuple[bool, str]:
        del allow_online_probe
        if target_date in self._open_dates:
            return True, "test_official_schedule_open"
        return False, "test_official_schedule_closed"

    def get_trading_days_in_range(
        self,
        start_date: date,
        end_date: date,
        allow_online_probe: bool = True,
    ) -> list[dict[str, object]]:
        del allow_online_probe
        return [
            {
                "date": current,
                "date_str": current.isoformat(),
                "is_trading_day": current in self._open_dates,
                "reason_code": (
                    "test_official_schedule_open"
                    if current in self._open_dates
                    else "test_official_schedule_closed"
                ),
            }
            for offset in range((end_date - start_date).days + 1)
            for current in (start_date + timedelta(days=offset),)
        ]


def _write_recommendation(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "result_id": "scheduled_rec_20260904_200000",
                "created_at": "2026-09-04T20:00:00+08:00",
                "config": {
                    "research_only": True,
                    "decision_date": DECISION_DATE,
                    "top_n": 8,
                    "profile_id": "scheduled_daily_research_default_v1",
                    "safety_boundary": {
                        "confirm": False,
                        "writes_evidence_db": False,
                        "auto_trading": False,
                        "lifecycle_action": False,
                    },
                },
                "recommendations": [
                    {
                        "證券代號": "2330",
                        "證券名稱": "測試公司",
                        "總分": "100.00",
                        "收盤價": "10.00",
                        "產業": "半導體",
                        "eligible_universe_date": DECISION_DATE,
                    }
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _write_market(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE daily_prices ("
            "日期 TEXT, 證券代號 TEXT, 證券名稱 TEXT, "
            "開盤價 TEXT, 收盤價 TEXT, 成交股數 INTEGER)"
        )
        connection.executemany(
            "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?)",
            (
                ("20260904", "2330", "測試公司", "9.80", "10.00", 90000),
                ("20260907", "2330", "測試公司", "10.20", "10.50", 100000),
            ),
        )


def _write_baseline(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "decision_date": DECISION_DATE,
                "source_result_id": "paper-baseline-20260904",
                "residual_cash": "80000.00",
                "allocations": [
                    {
                        "stock_code": "2330",
                        "executable_shares": 2000,
                        "reference_price": "10.00",
                        "executable_amount": "20000.00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _prepare_paper_chain(
    tmp_path: Path,
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """用隔離來源跑盤前 snapshot→EOD queue→ledger→下一盤前。"""

    monkeypatch.delenv("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY", raising=False)
    monkeypatch.delenv("RULE_CHAMPION_CONTROLLED_STORE_ID", raising=False)
    calendar = _ChainCalendar(tmp_path / "unused-calendar.sqlite")
    output_root = tmp_path / "paper-output"
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline)
    market = tmp_path / "market.sqlite"
    _write_market(market)
    state = tmp_path / "paper-state.sqlite"
    ledger = tmp_path / "paper-ledger.sqlite"

    preopen = run_paper_preopen(
        baseline_path=baseline,
        state_db=state,
        market_db=market,
        output_root=output_root,
        decision_at=datetime(2026, 9, 7, 8, 30, tzinfo=TAIPEI),
        now=datetime(2026, 9, 7, 8, 30, 1, tzinfo=TAIPEI),
        calendar=calendar,
        ledger_db=ledger,
    )
    assert preopen["status"] == "passed"
    snapshot_before_eod = PaperPortfolioSnapshotRepository(state).get(
        "paper-main-20260907"
    )
    assert snapshot_before_eod is not None
    state_bytes_before_eod = state.read_bytes()

    recommendation_source = tmp_path / "recommendation.json"
    _write_recommendation(recommendation_source)
    recommendation_root = tmp_path / "recommendation-queue"
    recommendation_root.mkdir()
    queued = recommendation_root / "scheduled_rec_20260904.json"
    queued.write_bytes(recommendation_source.read_bytes())
    paper_candidate_root = tmp_path / "paper-candidate"
    operational_receipts = tmp_path / "paper-receipts"
    paper_result = run_paper_execution_daily_from_queue(
        PaperExecutionPaths(
            recommendation_json=tmp_path / "unused-placeholder.json",
            state_db=state,
            market_db=market,
            output_root=paper_candidate_root,
            ledger_db=ledger,
        ),
        recommendation_root=recommendation_root,
        receipt_root=operational_receipts,
        now=EOD_OBSERVED,
        calendar=calendar,
        confirm_append=True,
    )
    assert paper_result["status"] == "machine_verified_candidate"
    assert paper_result["ledger"]["appended"] is True
    assert paper_result["ledger"]["readback_verified"] is True
    assert paper_result["market_source"]["execution_price_field"] == "開盤價"
    assert paper_result["market_source"]["execution_event_time_proven"] is False
    assert paper_result["market_source"]["execution_data_availability"] == (
        "delayed_eod_replay_after_session_close"
    )
    assert state.read_bytes() == state_bytes_before_eod

    # 重跑只驗證 queue receipt 與 deterministic fill 不重複；新 output 目錄
    # 符合 writer 的 create-only 邊界，並不手動改 recommendation。
    retry = run_paper_execution_daily_from_queue(
        PaperExecutionPaths(
            recommendation_json=tmp_path / "unused-placeholder.json",
            state_db=state,
            market_db=market,
            output_root=tmp_path / "paper-candidate-retry",
            ledger_db=ledger,
        ),
        recommendation_root=recommendation_root,
        receipt_root=operational_receipts,
        now=EOD_OBSERVED,
        calendar=calendar,
        confirm_append=True,
    )
    assert retry["status"] == "skipped_no_pending_recommendation"
    assert len(PaperTradeLedgerRepository(ledger).list()) == 1

    fill = PaperTradeLedgerRepository(ledger).list()[0]
    assert fill.event_date == EXECUTION_DATE
    assert fill.filled_quantity == 1000
    assert isinstance(fill.fill_price, Decimal)

    # 正式 snapshot writer 在下一個自然日以唯讀 ledger projection 建立新邊界；
    # 這裡走公開 runner，不由測試直接捏造 snapshot 或成交。
    next_preopen = run_paper_preopen(
        baseline_path=baseline,
        state_db=state,
        market_db=market,
        output_root=output_root,
        decision_at=datetime(2026, 9, 8, 8, 30, tzinfo=TAIPEI),
        now=datetime(2026, 9, 8, 8, 30, 1, tzinfo=TAIPEI),
        calendar=calendar,
        ledger_db=ledger,
    )
    assert next_preopen["status"] == "passed"
    assert next_preopen["paper_ledger_transitions_applied"] == 1
    next_snapshot = PaperPortfolioSnapshotRepository(state).get(
        "paper-main-20260908"
    )
    assert next_snapshot is not None
    assert next_snapshot.positions[0].quantity == 1000
    expected_cash = (
        Decimal("80000.00")
        + fill.gross_amount
        - fill.commission
        - fill.tax
    ).quantize(Decimal("0.01"))
    assert next_snapshot.cash == expected_cash

    clock_root = tmp_path / "clock"
    clock_root.mkdir()
    clock_path, _, _, _ = _clock(clock_root)
    return {
        "calendar": calendar,
        "market": market,
        "state": state,
        "ledger": ledger,
        "clock": clock_path,
        "paper_result": paper_result,
        "next_preopen": next_preopen,
    }


def _formal_paths(
    tmp_path: Path,
    chain: dict[str, Any],
    label: str,
    publication_root: Path,
) -> DailyFormalInputPaths:
    return DailyFormalInputPaths(
        output_root=tmp_path / f"formal-output-{label}",
        development_output_root=(
            tmp_path / f"formal-development-{label}" / "technical_analysis_development_output"
        ),
        market_db=Path(chain["market"]),
        clock_manifest=Path(chain["clock"]),
        paper_snapshot_db_path=Path(chain["state"]),
        paper_trade_ledger_db_path=Path(chain["ledger"]),
        publication_root=publication_root,
    )


def _run_formal(
    tmp_path: Path,
    chain: dict[str, Any],
    *,
    label: str,
    publication_root: Path,
) -> dict[str, object]:
    return run_daily_formal_input_producer(
        _formal_paths(tmp_path, chain, label, publication_root),
        now=FORMAL_OBSERVED,
        calendar=chain["calendar"],
    )


def test_isolated_paper_open_data_queue_fill_and_formal_consumer_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """驗證真實 writer/reader 接線，所有來源與輸出均限隔離目錄。"""

    chain = _prepare_paper_chain(tmp_path, monkeypatch=monkeypatch)
    publication_root = tmp_path / "formal-publication"
    result = _run_formal(
        tmp_path,
        chain,
        label="success",
        publication_root=publication_root,
    )

    assert result["status"] == "candidate_only"
    assert result["formal_ready_input_count"] == 0
    inputs = result["inputs"]
    assert isinstance(inputs, dict)
    ledger = inputs["formal_ledger_candidate"]
    assert isinstance(ledger, dict)
    assert ledger["consumer_verified"] is True
    assert ledger["formal_consumer_compatible"] is True
    assert ledger["publication_status"] == "published"
    assert ledger["fill_rows_used"] == 1
    assert ledger["decision_dates"] == [EXECUTION_DATE, NEXT_SNAPSHOT_DATE]
    manifest_path = Path(str(ledger["manifest_path"]))
    receipt_path = Path(str(ledger["publication_receipt_path"]))
    assert manifest_path.is_file()
    assert receipt_path.is_file()
    with sqlite3.connect(Path(str(ledger["sqlite_path"]))) as connection:
        assert connection.execute("SELECT COUNT(*) FROM transitions").fetchone()[0] == 2
    assert result["formal_ready_input_count"] != 3


def test_paper_formal_chain_recovers_after_ledger_receipt_failure_and_source_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """manifest/SQLite 已持久化但 receipt 中斷時，下一輪只補同一 run。"""

    chain = _prepare_paper_chain(tmp_path, monkeypatch=monkeypatch)
    publication_root = tmp_path / "formal-publication"
    original_writer = formal_daily_input_producer_module._write_input_receipt
    failure = {"raised": False}

    def fail_causal_receipt_once(
        *,
        output_path: Path,
        input_name: str,
        result: dict[str, object],
        observed: datetime,
    ) -> tuple[Path, str, str]:
        if (
            output_path.name == "receipt.json"
            and output_path.resolve().parent.parent.parent
            == publication_root.resolve()
            and not failure["raised"]
        ):
            failure["raised"] = True
            raise OSError("simulated causal ledger receipt sink failure")
        return original_writer(
            output_path=output_path,
            input_name=input_name,
            result=result,
            observed=observed,
        )

    monkeypatch.setattr(
        formal_daily_input_producer_module,
        "_write_input_receipt",
        fail_causal_receipt_once,
    )
    first = _run_formal(
        tmp_path,
        chain,
        label="receipt-failure",
        publication_root=publication_root,
    )
    assert failure["raised"] is True
    assert first["status"] == "blocked"
    first_inputs = first["inputs"]
    assert isinstance(first_inputs, dict)
    failed_ledger = first_inputs["formal_ledger_candidate"]
    assert isinstance(failed_ledger, dict)
    assert "formal_ledger_source_rejected" in str(failed_ledger["reason"])
    run_dirs = list((publication_root / "causal_ledger").iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert (run_dir / "manifest.json").is_file()
    assert (run_dir / "portfolio_ledger.sqlite").is_file()
    assert (run_dir / "publication_context.json").is_file()
    assert not (run_dir / "receipt.json").exists()

    # 來源可能位於一次性工作目錄；第二輪應依 durable custody 恢復，
    # 不把缺少 TEMP source 誤當作可以另造一條 chain。
    monkeypatch.setattr(
        formal_daily_input_producer_module,
        "_write_input_receipt",
        original_writer,
    )
    gc.collect()
    Path(chain["state"]).unlink()
    Path(chain["ledger"]).unlink()
    recovered = _run_formal(
        tmp_path,
        chain,
        label="receipt-recovered",
        publication_root=publication_root,
    )
    assert recovered["status"] == "candidate_only"
    assert recovered["formal_ready_input_count"] == 0
    recovered_inputs = recovered["inputs"]
    assert isinstance(recovered_inputs, dict)
    recovered_ledger = recovered_inputs["formal_ledger_candidate"]
    assert isinstance(recovered_ledger, dict)
    assert recovered_ledger["consumer_verified"] is True
    assert recovered_ledger["publication_status"] == (
        "recovered_after_receipt_failure"
    )
    assert recovered_ledger["idempotent_retry"] is True
    assert (run_dir / "receipt.json").is_file()
    assert recovered["formal_ready_input_count"] != 3
