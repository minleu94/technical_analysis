from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
import gc
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any
from urllib.error import URLError
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
    resolve_pending_recommendation,
    run_paper_execution_daily_from_queue,
)
from data_module.paper_event_source_capture import (
    PaperEventSourceCaptureError,
    bind_paper_candidate_file_to_capture,
    bind_paper_execution_result_to_capture,
    capture_twse_session_open_prices,
    capture_twse_session_open_prices_for_recommendation,
    load_persisted_twse_event_source_capture,
    persist_twse_event_source_capture,
    resolve_persisted_twse_event_source_capture_for_recommendation,
)
from data_module.official_trading_calendar import OfficialTradingCalendar
from data_module.portfolio_ml_dataset_assembler import (
    SECTOR_MEMBERSHIP_MANIFEST_SCHEMA_VERSION,
    SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION,
)
from scripts.run_paper_portfolio_daily import run as run_paper_preopen
from scripts.scheduled import run_paper_execution_daily_isolated as isolated_paper_runner
from scripts.scheduled.run_paper_event_source_capture_daily import (
    run_capture,
)
from scripts.scheduled.paper_portfolio_state_isolation import (
    ensure_repo_state_from_readonly_source,
)
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


def _write_sector_sidecar(path: Path) -> str:
    rows = [
        {
            "symbol": "2330",
            "sector_id": "SEMICONDUCTOR",
            "available_at": "2026-01-01T00:00:00+00:00",
            "effective_from": "2026-01-01",
            "effective_to": None,
            "status": "accepted",
            "source_id": "official:twse:t187ap03_L",
            "license_id": "twse-open-data-license-v1",
            "source_hash": "sha256:" + "a" * 64,
        }
    ]
    rows_hash = "sha256:" + hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    manifest_body = {
        "schema_version": SECTOR_MEMBERSHIP_MANIFEST_SCHEMA_VERSION,
        "row_count": 1,
        "rows_hash": rows_hash,
    }
    manifest = {
        **manifest_body,
        "canonical_hash": "sha256:"
        + hashlib.sha256(
            json.dumps(
                {
                    "sidecar_schema_version": SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION,
                    "manifest": manifest_body,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }
    payload = {
        "schema_version": SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION,
        "manifest": manifest,
        "rows": rows,
    }
    path.write_bytes(
        (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
    )
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


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
    sector_path = tmp_path / "pit-sector.json"
    sector_hash = _write_sector_sidecar(sector_path)
    PaperTradeLedgerRepository(ledger)
    paper_candidate_root = tmp_path / "paper-candidate"
    operational_receipts = tmp_path / "paper-receipts"
    paper_result = run_paper_execution_daily_from_queue(
        PaperExecutionPaths(
            recommendation_json=tmp_path / "unused-placeholder.json",
            state_db=state,
            market_db=market,
            output_root=paper_candidate_root,
            ledger_db=ledger,
            sector_membership_path=sector_path,
            sector_membership_file_hash=sector_hash,
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
            sector_membership_path=sector_path,
            sector_membership_file_hash=sector_hash,
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
    paper_receipt = chain["paper_result"]["operational_receipt"]
    assert isinstance(paper_receipt, dict)
    paper_receipt_path = Path(str(paper_receipt["path"]))
    return DailyFormalInputPaths(
        output_root=tmp_path / f"formal-output-{label}",
        development_output_root=(
            tmp_path / f"formal-development-{label}" / "technical_analysis_development_output"
        ),
        market_db=Path(chain["market"]),
        clock_manifest=Path(chain["clock"]),
        paper_snapshot_db_path=Path(chain["state"]),
        paper_trade_ledger_db_path=Path(chain["ledger"]),
        paper_execution_receipt_root=paper_receipt_path.parent,
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
    # The append-only Paper producer receipt proves custody of the committed
    # row, but this fixture deliberately uses the delayed EOD replay contract.
    # Fill-ID coverage therefore remains custody evidence and cannot satisfy
    # the Formal event-time gate.
    assert result["formal_ready_input_count"] == 0
    inputs = result["inputs"]
    assert isinstance(inputs, dict)
    ledger = inputs["formal_ledger_candidate"]
    assert isinstance(ledger, dict)
    assert ledger["consumer_verified"] is True
    assert ledger["formal_consumer_compatible"] is True
    assert ledger["paper_execution_receipt_verified"] is False
    projection = ledger["paper_execution_receipt_projection"]
    assert isinstance(projection, dict)
    assert projection["custody_verified"] is True
    assert projection["formal_eligible"] is False
    assert projection["formal_ready"] is False
    assert projection["execution_event_time_proven"] is False
    assert projection["formal_ineligible_reasons"]
    assert ledger["publication_status"] == "published"
    assert ledger["fill_rows_used"] == 1
    assert ledger["decision_dates"] == [EXECUTION_DATE, NEXT_SNAPSHOT_DATE]
    manifest_path = Path(str(ledger["manifest_path"]))
    receipt_path = Path(str(ledger["publication_receipt_path"]))
    assert manifest_path.is_file()
    assert receipt_path.is_file()
    with sqlite3.connect(Path(str(ledger["sqlite_path"]))) as connection:
        assert connection.execute("SELECT COUNT(*) FROM transitions").fetchone()[0] == 2
    assert inputs["causal_non_cash_portfolio_ledger"]["formal_ready"] is False
    assert inputs["causal_non_cash_portfolio_ledger"][
        "formal_consumer_compatible"
    ] is False
    assert inputs["formal_ledger_candidate"]["formal_ready"] is False
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
    assert recovered_ledger["paper_execution_receipt_verified"] is False
    recovered_projection = recovered_ledger["paper_execution_receipt_projection"]
    assert isinstance(recovered_projection, dict)
    assert recovered_projection["custody_verified"] is True
    assert recovered_projection["formal_eligible"] is False
    assert (run_dir / "receipt.json").is_file()
    assert recovered_inputs["causal_non_cash_portfolio_ledger"]["formal_ready"] is False
    assert recovered_inputs["causal_non_cash_portfolio_ledger"][
        "formal_consumer_compatible"
    ] is False
    assert recovered_inputs["formal_ledger_candidate"]["formal_ready"] is False
    assert recovered["formal_ready_input_count"] != 3


def test_paper_receipt_formal_eligibility_requires_timestamped_intraday_source(
    tmp_path: Path,
) -> None:
    """正式資格必須重建官方 raw response 並逐筆綁定實際 fill。"""

    capture_path = tmp_path / "official-session-open-capture.json"
    raw_response_path = tmp_path / "raw_response.bin"
    execution_date = date(2026, 9, 7)
    event_at = "2026-09-07T09:00:00+08:00"
    capture_at = "2026-09-07T09:00:03+08:00"
    request_channels = "tse_2330.tw|tse_2317.tw"
    raw_response_payload: dict[str, object] = {
        "rtcode": "000",
        "rtmessage": "OK",
        "msgArray": [
            {
                "c": "2330",
                "ex": "tse",
                "d": "20260907",
                "t": "09:00:00",
                "tlong": "1788742800000",
                "o": "10.20",
            },
            {
                "c": "2317",
                "ex": "tse",
                "d": "20260907",
                "t": "09:00:02",
                "tlong": "1788742802000",
                "o": "20.30",
            },
        ],
    }
    raw_response = (
        formal_daily_input_producer_module._canonical_json(raw_response_payload)
    ).encode("utf-8")
    fill = {
        "fill_id": "fill-1",
        "order_id": "order-1",
        "source_event_id": "paper-event-1",
        "stock_code": "2330",
        "side": "buy",
        "event_date": execution_date.isoformat(),
        "filled_quantity": 1000,
        "status": "filled",
        "reference_price": "10.20",
        "fill_price": "10.21",
    }
    fills = [{"fill": fill}]

    def _capture_body(
        *,
        raw_bytes: bytes = raw_response,
        **updates: object,
    ) -> dict[str, object]:
        body: dict[str, object] = {
            "schema_version": (
                formal_daily_input_producer_module.PAPER_EXECUTION_EVENT_CAPTURE_SCHEMA_VERSION
            ),
            "source_authority": "twse",
            "source_url": formal_daily_input_producer_module.TWSE_MIS_STOCK_INFO_ENDPOINT,
            "source_kind": "official_session_open_capture",
            "parser": formal_daily_input_producer_module.PAPER_EXECUTION_EVENT_CAPTURE_PARSER_VERSION,
            "request": {
                "ex_ch": request_channels,
                "json": "1",
                "delay": "0",
            },
            "response": {
                "http_status": 200,
                "final_url": formal_daily_input_producer_module._twse_mis_request_url(
                    request_channels
                ),
                "content_type": "application/json",
                "content_encoding": "identity",
            },
            "execution_date": execution_date.isoformat(),
            "execution_event_at": event_at,
            "captured_at": capture_at,
            "capture_window": {
                "start_at": event_at,
                "end_at": capture_at,
            },
            "source_time_semantics": (
                formal_daily_input_producer_module.PAPER_EXECUTION_SOURCE_TIME_SEMANTICS
            ),
            "raw_response_path": raw_response_path.name,
            "raw_response_sha256": "sha256:" + hashlib.sha256(raw_bytes).hexdigest(),
            "raw_response_bytes": len(raw_bytes),
            "raw_row_count": 2,
        }
        body.update(updates)
        if "captured_at" in updates and "capture_window" not in updates:
            body["capture_window"] = {
                "start_at": body["execution_event_at"],
                "end_at": body["captured_at"],
            }
        body["content_sha256"] = formal_daily_input_producer_module._payload_hash(body)
        return body

    recorded_at = datetime(2026, 9, 7, 1, 0, 4, tzinfo=ZoneInfo("UTC"))
    observed = datetime(2026, 9, 7, 1, 5, tzinfo=ZoneInfo("UTC"))

    def _evaluate(
        body: dict[str, object],
        *,
        raw_bytes: bytes = raw_response,
        source_updates: dict[str, object] | None = None,
        at_recorded: datetime = recorded_at,
        at_observed: datetime = observed,
        mutate_capture_after_write: bytes | None = None,
    ) -> tuple[bool, str | None]:
        envelope_raw = (
            formal_daily_input_producer_module._canonical_json(body) + "\n"
        ).encode("utf-8")
        raw_response_path.write_bytes(raw_bytes)
        capture_path.write_bytes(envelope_raw)
        if mutate_capture_after_write is not None:
            capture_path.write_bytes(mutate_capture_after_write)
        body_execution_date = body.get("execution_date")
        body_event_at = body.get("execution_event_at")
        body_capture_at = body.get("captured_at")
        body_request = body.get("request")
        body_request_channels = (
            body_request.get("ex_ch")
            if isinstance(body_request, dict)
            else request_channels
        )
        source: dict[str, object] = {
            "execution_event_time_proven": True,
            "execution_source_capture_at_proven": True,
            "intraday_open_availability_proven": True,
            "execution_source_kind": "official_session_open_capture",
            "execution_data_availability": "same_session_intraday_capture",
            "execution_source_time_semantics": (
                formal_daily_input_producer_module.PAPER_EXECUTION_SOURCE_TIME_SEMANTICS
            ),
            "execution_date": execution_date.isoformat(),
            "execution_source_capture_schema_version": (
                formal_daily_input_producer_module.PAPER_EXECUTION_EVENT_CAPTURE_SCHEMA_VERSION
            ),
            "execution_source_parser_version": (
                formal_daily_input_producer_module.PAPER_EXECUTION_EVENT_CAPTURE_PARSER_VERSION
            ),
            "execution_source_authority": "twse",
            "execution_source_url": formal_daily_input_producer_module.TWSE_MIS_STOCK_INFO_ENDPOINT,
            "execution_source_request_url": formal_daily_input_producer_module._twse_mis_request_url(
                str(body_request_channels)
            ),
            "execution_source_capture_path": str(capture_path),
            "execution_source_capture_file_hash": (
                "sha256:" + hashlib.sha256(envelope_raw).hexdigest()
            ),
            "execution_source_capture_content_hash": body["content_sha256"],
            "execution_source_capture_row_count": body["raw_row_count"],
            "execution_source_raw_response_path": str(raw_response_path.resolve()),
            "execution_source_raw_response_hash": body["raw_response_sha256"],
            "execution_event_at": body_event_at,
            "execution_source_capture_at": body_capture_at,
        }
        if source_updates:
            source.update(source_updates)
        result = {
            "execution_event_time_proven": True,
            "formal_consumer_compatible": True,
            "execution_replay_mode": "same_session_event_time_capture",
            "market_source": source,
        }
        return formal_daily_input_producer_module._paper_receipt_formal_eligibility(
            result,
            fills=fills,
            execution_date=execution_date,
            recorded_at=at_recorded,
            observed=at_observed,
        )

    eligible, reason = _evaluate(_capture_body())
    assert eligible is True
    assert reason is None

    # A valid file hash cannot rescue arbitrary bytes; the validator must
    # parse the official MIS response and rebuild the raw quote rows.
    arbitrary_raw = b"arbitrary source bytes with a correct file hash"
    arbitrary_body = _capture_body(raw_bytes=arbitrary_raw)
    eligible, reason = _evaluate(arbitrary_body, raw_bytes=arbitrary_raw)
    assert eligible is False
    assert reason == "market_source_capture_raw_response_json_invalid"

    empty_raw = b'{"msgArray":[],"rtcode":"000","rtmessage":"OK"}'
    empty_body = _capture_body(raw_bytes=empty_raw)
    eligible, reason = _evaluate(empty_body, raw_bytes=empty_raw)
    assert eligible is False
    assert reason == "market_source_capture_raw_response_rows_missing"

    wrong_date_body = _capture_body(execution_date="2026-09-08")
    eligible, reason = _evaluate(wrong_date_body)
    assert eligible is False
    assert reason == "market_source_capture_execution_date_mismatch"

    eligible, reason = _evaluate(
        _capture_body(),
        source_updates={"execution_date": "2026-09-08"},
    )
    assert eligible is False
    assert reason == "market_source_metadata_execution_date_mismatch"

    wrong_stock_payload = {
        **raw_response_payload,
        "msgArray": [{
            **raw_response_payload["msgArray"][0],  # type: ignore[index]
            "c": "2318",
        }],
    }
    wrong_stock_raw = formal_daily_input_producer_module._canonical_json(
        wrong_stock_payload
    ).encode("utf-8")
    wrong_stock_body = _capture_body(
        raw_bytes=wrong_stock_raw,
        request={"ex_ch": "tse_2330.tw", "json": "1", "delay": "0"},
        response={
            "http_status": 200,
            "final_url": formal_daily_input_producer_module._twse_mis_request_url(
                "tse_2330.tw"
            ),
            "content_type": "application/json",
            "content_encoding": "identity",
        },
    )
    eligible, reason = _evaluate(wrong_stock_body, raw_bytes=wrong_stock_raw)
    assert eligible is False
    assert reason == "market_source_capture_raw_response_symbol_mismatch"

    wrong_price_payload = {
        **raw_response_payload,
        "msgArray": [
            {
                **raw_response_payload["msgArray"][0],  # type: ignore[index]
                "o": "99.99",
            },
            raw_response_payload["msgArray"][1],  # type: ignore[index]
        ],
    }
    wrong_price_raw = formal_daily_input_producer_module._canonical_json(
        wrong_price_payload
    ).encode("utf-8")
    wrong_price_body = _capture_body(raw_bytes=wrong_price_raw)
    eligible, reason = _evaluate(wrong_price_body, raw_bytes=wrong_price_raw)
    assert eligible is False
    assert reason == "market_source_capture_source_price_mismatch"

    next_day_body = _capture_body(captured_at="2026-09-08T09:00:01+08:00")
    next_day_eligible, next_day_reason = _evaluate(
        next_day_body,
        at_recorded=datetime(2026, 9, 8, 1, 0, 2, tzinfo=ZoneInfo("UTC")),
        at_observed=datetime(2026, 9, 8, 1, 5, tzinfo=ZoneInfo("UTC")),
    )
    assert next_day_eligible is False
    assert next_day_reason == "market_source_capture_not_same_trading_session"

    # The envelope hash is checked before the parser, even if the original
    # raw response bytes remain unchanged.
    valid_body = _capture_body()
    eligible, reason = _evaluate(
        valid_body,
        mutate_capture_after_write=b'{"schema_version":"tampered"}\n',
    )
    assert eligible is False
    assert reason == "market_source_capture_file_hash_mismatch"


def test_twse_event_source_producer_preserves_raw_bytes_and_quote_observation_window(
    tmp_path: Path,
) -> None:
    """真正 producer 的 raw bytes 可重建，且多檔 tlong 不被當成同一成交時間。"""

    raw_payload = {
        "rtcode": "000",
        "rtmessage": "OK",
        "msgArray": [
            {
                "c": "2330",
                "ex": "tse",
                "d": "20260907",
                "t": "09:00:00",
                "tlong": "1788742800000",
                "o": "10.20",
            },
            {
                "c": "2317",
                "ex": "tse",
                "d": "20260907",
                "t": "09:00:02",
                "tlong": "1788742802000",
                "o": "20.30",
            },
        ],
    }
    raw = formal_daily_input_producer_module._canonical_json(raw_payload).encode(
        "utf-8"
    )
    now = datetime(2026, 9, 7, 1, 0, 3, tzinfo=ZoneInfo("UTC"))
    calls: list[str] = []

    class _Response:
        status = 200
        headers = {
            "Content-Type": "application/json",
            "Content-Encoding": "identity",
        }

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def geturl(self) -> str:
            return calls[-1]

        def read(self, limit: int) -> bytes:
            assert limit == (
                formal_daily_input_producer_module.PAPER_EXECUTION_EVENT_CAPTURE_MAX_BYTES
                + 1
            )
            return raw

    def fetcher(request: object, timeout: float) -> _Response:
        del timeout
        calls.append(str(request.full_url))  # type: ignore[attr-defined]
        return _Response()

    result = capture_twse_session_open_prices(
        symbols=("2330", "2317"),
        execution_date=date(2026, 9, 7),
        output_dir=tmp_path / "twse-capture",
        now=now,
        fetcher=fetcher,
    )
    assert result["status"] == "source_capture_ready"
    assert result["raw_row_count"] == 2
    assert result["execution_event_time_proven"] is False
    capture_path = Path(str(result["capture_path"]))
    raw_path = Path(str(result["raw_response_path"]))
    assert raw_path.read_bytes() == raw
    payload = json.loads(capture_path.read_text(encoding="utf-8"))
    assert "raw_rows" not in payload
    assert payload["source_time_semantics"] == (
        formal_daily_input_producer_module.PAPER_EXECUTION_SOURCE_TIME_SEMANTICS
    )
    assert payload["capture_window"]["start_at"] == "2026-09-07T01:00:00+00:00"
    assert payload["capture_window"]["end_at"] == "2026-09-07T01:00:03+00:00"
    assert len(calls) == 1
    assert calls[0].startswith(
        formal_daily_input_producer_module.TWSE_MIS_STOCK_INFO_ENDPOINT + "?"
    )

    fill = {
        "fill_id": "fill-1",
        "order_id": "order-1",
        "source_event_id": "paper-event-1",
        "stock_code": "2330",
        "side": "buy",
        "event_date": "2026-09-07",
        "filled_quantity": 1000,
        "status": "filled",
        "reference_price": "10.20",
        "fill_price": "10.21",
    }
    source = dict(result["market_source"])
    source["execution_event_time_proven"] = True
    eligible, reason = formal_daily_input_producer_module._paper_receipt_formal_eligibility(
        {
            "execution_event_time_proven": True,
            "formal_consumer_compatible": True,
            "execution_replay_mode": "same_session_event_time_capture",
            "market_source": source,
        },
        fills=[{"fill": fill}],
        execution_date=date(2026, 9, 7),
        recorded_at=datetime(2026, 9, 7, 1, 0, 4, tzinfo=ZoneInfo("UTC")),
        observed=datetime(2026, 9, 7, 1, 5, tzinfo=ZoneInfo("UTC")),
    )
    assert eligible is True
    assert reason is None


def test_twse_event_source_production_clock_uses_response_completion_and_rejects_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """production ``now=None`` 以 HTTP 完成時刻定界，跨收盤則拒絕。"""

    import data_module.paper_event_source_capture as capture_module

    raw = formal_daily_input_producer_module._canonical_json(
        {
            "rtcode": "000",
            "rtmessage": "OK",
            "msgArray": [
                {
                    "c": "2330",
                    "ex": "tse",
                    "d": "20260907",
                    "t": "09:00:00",
                    "tlong": "1788742800000",
                    "o": "10.20",
                }
            ],
        }
    ).encode("utf-8")
    request_urls: list[str] = []

    class _Response:
        status = 200
        headers = {"Content-Type": "application/json"}

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def geturl(self) -> str:
            return request_urls[-1]

        def read(self, limit: int) -> bytes:
            assert limit == (
                formal_daily_input_producer_module.PAPER_EXECUTION_EVENT_CAPTURE_MAX_BYTES
                + 1
            )
            return raw

    def fetcher(request: object, timeout: float) -> _Response:
        del timeout
        request_urls.append(str(request.full_url))  # type: ignore[attr-defined]
        return _Response()

    clock_values = iter(
        (
            datetime(2026, 9, 7, 1, 0, 1, tzinfo=ZoneInfo("UTC")),
            datetime(2026, 9, 7, 1, 0, 4, tzinfo=ZoneInfo("UTC")),
        )
    )
    monkeypatch.setattr(capture_module, "_utc_now", lambda: next(clock_values))
    result = capture_twse_session_open_prices(
        symbols=("2330",),
        execution_date=date(2026, 9, 7),
        output_dir=tmp_path / "completion-clock-capture",
        now=None,
        fetcher=fetcher,
    )
    assert result["captured_at"] == "2026-09-07T01:00:04+00:00"
    payload = json.loads(Path(str(result["capture_path"])).read_text(encoding="utf-8"))
    assert payload["capture_window"]["end_at"] == "2026-09-07T01:00:04+00:00"

    close_clock_values = iter(
        (
            # 13:29:59 Taipei: start is still inside the capture window.
            datetime(2026, 9, 7, 5, 29, 59, tzinfo=ZoneInfo("UTC")),
            # 13:30:01 Taipei: a slow response crossed the exclusive close.
            datetime(2026, 9, 7, 5, 30, 1, tzinfo=ZoneInfo("UTC")),
        )
    )
    monkeypatch.setattr(
        capture_module,
        "_utc_now",
        lambda: next(close_clock_values),
    )
    with pytest.raises(PaperEventSourceCaptureError, match="capture completion"):
        capture_twse_session_open_prices(
            symbols=("2330",),
            execution_date=date(2026, 9, 7),
            output_dir=tmp_path / "cross-close-capture",
            now=None,
            fetcher=fetcher,
        )
    assert not (tmp_path / "cross-close-capture" / "raw_response.bin").exists()


def test_twse_event_source_producer_rejects_late_capture_and_immutable_conflict(
    tmp_path: Path,
) -> None:
    """錯誤時窗與 immutable bytes 衝突都必須 fail closed。"""

    with pytest.raises(PaperEventSourceCaptureError, match="regular session"):
        capture_twse_session_open_prices(
            symbols=("2330",),
            execution_date=date(2026, 9, 7),
            output_dir=tmp_path / "late-capture",
            now=datetime(2026, 9, 7, 5, 31, tzinfo=ZoneInfo("UTC")),
            fetcher=lambda request, timeout: pytest.fail("late capture must not fetch"),
        )

    immutable_path = tmp_path / "immutable.bin"
    formal_daily_input_producer_module._write_immutable_bytes_atomic(
        immutable_path,
        b"first",
        "test immutable",
    )
    with pytest.raises(
        formal_daily_input_producer_module.FormalDailyInputProducerError,
        match="immutable bytes differ",
    ):
        formal_daily_input_producer_module._write_immutable_bytes_atomic(
            immutable_path,
            b"second",
            "test immutable",
        )


def test_frozen_recommendation_capture_persists_and_replays_without_refetch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """自然 caller 以 frozen recommendation 綁定 durable source，retry 不重抓。"""

    recommendation_path = tmp_path / "recommendation.json"
    _write_recommendation(recommendation_path)
    raw_payload = {
        "rtcode": "000",
        "rtmessage": "OK",
        "msgArray": [
            {
                "c": "2330",
                "ex": "tse",
                "d": "20260907",
                "t": "09:00:00",
                "tlong": "1788742800000",
                "o": "10.20",
            }
        ],
    }
    raw = formal_daily_input_producer_module._canonical_json(raw_payload).encode(
        "utf-8"
    )
    requested_urls: list[str] = []

    class _Response:
        status = 200
        headers = {"Content-Type": "application/json"}

        def __init__(self, url: str) -> None:
            self._url = url

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def geturl(self) -> str:
            return self._url

        def read(self, limit: int) -> bytes:
            assert limit == (
                formal_daily_input_producer_module.PAPER_EXECUTION_EVENT_CAPTURE_MAX_BYTES
                + 1
            )
            return raw

    def fetcher(request: object, timeout: float) -> _Response:
        del timeout
        url = str(request.full_url)  # type: ignore[attr-defined]
        requested_urls.append(url)
        return _Response(url)

    durable_root = tmp_path / "controlled-output" / "event_captures"
    first = capture_twse_session_open_prices_for_recommendation(
        recommendation_path=recommendation_path,
        execution_date=date(2026, 9, 7),
        output_dir=tmp_path / "first-temp-capture",
        durable_root=durable_root,
        allowed_durable_root=tmp_path / "controlled-output",
        now=datetime(2026, 9, 7, 1, 0, 3, tzinfo=ZoneInfo("UTC")),
        fetcher=fetcher,
    )
    assert first["status"] == "source_capture_ready"
    assert first["durable_readback_verified"] is True
    assert len(requested_urls) == 1
    durable_value = first["durable_capture"]
    assert isinstance(durable_value, dict)
    manifest_path = Path(str(durable_value["manifest_path"]))
    assert manifest_path.is_file()
    loaded = load_persisted_twse_event_source_capture(manifest_path)
    assert loaded["recommendation"] == first["recommendation"]
    assert loaded["raw_response_hash"] == first["raw_response_hash"]

    # A retry after the regular session may only replay the pinned durable
    # source.  The fetcher would fail the test if the caller tried a new GET.
    second = capture_twse_session_open_prices_for_recommendation(
        recommendation_path=recommendation_path,
        execution_date=date(2026, 9, 7),
        output_dir=tmp_path / "retry-temp-must-stay-empty",
        durable_root=durable_root,
        allowed_durable_root=tmp_path / "controlled-output",
        now=datetime(2026, 9, 8, 1, 0, 3, tzinfo=ZoneInfo("UTC")),
        fetcher=lambda request, timeout: pytest.fail(
            "durable replay must not issue another official GET"
        ),
    )
    assert second["idempotent_replay"] is True
    assert second["raw_response_hash"] == first["raw_response_hash"]
    assert requested_urls == [requested_urls[0]]

    # The deterministic 16-character directory is only a namespace.  The
    # complete recommendation hash in manifest must still reject a collision.
    fake_identity = dict(first["recommendation"])
    original_hash = str(fake_identity["file_hash"])
    fake_identity["file_hash"] = "sha256:" + original_hash[7:23] + "b" * 48
    conflict = dict(first)
    conflict["recommendation"] = fake_identity
    conflict_source = dict(conflict["market_source"])
    conflict["market_source"] = conflict_source
    with pytest.raises(PaperEventSourceCaptureError, match="identity hash collision"):
        persist_twse_event_source_capture(
            conflict,
            durable_root=durable_root,
            allowed_root=tmp_path / "controlled-output",
        )

    # If manifest publication crashes after the two immutable payload files are
    # present, the original candidate can complete the manifest without a new
    # HTTP response.  A divergent payload remains a conflict.
    candidate = dict(
        capture_twse_session_open_prices(
            symbols=("2330",),
            execution_date=date(2026, 9, 7),
            output_dir=tmp_path / "second-candidate",
            now=datetime(2026, 9, 7, 1, 0, 4, tzinfo=ZoneInfo("UTC")),
            fetcher=fetcher,
        )
    )
    candidate["recommendation"] = dict(first["recommendation"])
    partial_root = tmp_path / "partial-output" / "event_captures"
    import data_module.paper_event_source_capture as capture_module

    real_writer = capture_module._write_create_only_bytes

    def fail_manifest(path: Path, payload: bytes, role: str) -> str:
        if "manifest" in role:
            raise PaperEventSourceCaptureError("simulated manifest crash")
        return real_writer(path, payload, role)

    monkeypatch.setattr(capture_module, "_write_create_only_bytes", fail_manifest)
    with pytest.raises(PaperEventSourceCaptureError, match="simulated manifest crash"):
        persist_twse_event_source_capture(
            candidate,
            durable_root=partial_root,
            allowed_root=tmp_path / "partial-output",
        )
    monkeypatch.setattr(capture_module, "_write_create_only_bytes", real_writer)
    # Recreate the caller from disk after the TEMP candidate is gone.  The
    # public route reads identity/raw/envelope and completes the manifest;
    # it must not issue a second GET or require the old Python mapping.
    import shutil

    shutil.rmtree(Path(str(candidate["capture_path"])).parent)
    recovered = capture_twse_session_open_prices_for_recommendation(
        recommendation_path=recommendation_path,
        execution_date=date(2026, 9, 7),
        output_dir=tmp_path / "recovery-temp-must-stay-empty",
        durable_root=partial_root,
        allowed_durable_root=tmp_path / "partial-output",
        now=datetime(2026, 9, 8, 1, 0, 4, tzinfo=ZoneInfo("UTC")),
        fetcher=lambda request, timeout: pytest.fail(
            "partial durable recovery must not issue another official GET"
        ),
    )
    assert recovered["recovered_after_manifest_failure"] is True
    assert recovered["durable_readback_verified"] is True
    assert Path(str(recovered["manifest_path"])).is_file()


def test_paper_candidate_binding_to_durable_capture_reaches_formal_validator(
    tmp_path: Path,
) -> None:
    """Paper candidate 消費 durable capture 後，Formal 再以同一 raw rows 驗證。"""

    recommendation_path = tmp_path / "recommendation.json"
    _write_recommendation(recommendation_path)
    raw_payload = {
        "rtcode": "000",
        "rtmessage": "OK",
        "msgArray": [
            {
                "c": "2330",
                "ex": "tse",
                "d": "20260907",
                "t": "09:00:00",
                "tlong": "1788742800000",
                "o": "10.20",
            }
        ],
    }
    raw = formal_daily_input_producer_module._canonical_json(raw_payload).encode(
        "utf-8"
    )

    class _Response:
        status = 200
        headers = {"Content-Type": "application/json"}

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def geturl(self) -> str:
            return formal_daily_input_producer_module._twse_mis_request_url(
                "tse_2330.tw"
            )

        def read(self, limit: int) -> bytes:
            del limit
            return raw

    capture = capture_twse_session_open_prices_for_recommendation(
        recommendation_path=recommendation_path,
        execution_date=date(2026, 9, 7),
        output_dir=tmp_path / "capture-temp",
        durable_root=tmp_path / "controlled-output" / "event_captures",
        allowed_durable_root=tmp_path / "controlled-output",
        now=datetime(2026, 9, 7, 1, 0, 2, tzinfo=ZoneInfo("UTC")),
        fetcher=lambda request, timeout: _Response(),
    )
    recommendation = capture["recommendation"]
    assert isinstance(recommendation, dict)
    fill = {
        "fill_id": "paper-fill-1",
        "order_id": "paper-order-1",
        "source_event_id": "paper-event-1",
        "stock_code": "2330",
        "side": "buy",
        "event_date": "2026-09-07",
        "filled_quantity": 1000,
        "status": "filled",
        "reference_price": "10.20",
        "fill_price": "10.21",
    }
    paper_result: dict[str, object] = {
        "status": "machine_verified_candidate",
        "execution_date": "2026-09-07",
        "recommendation": recommendation,
        "fills": [fill],
        "market_source": {
            "execution_source_kind": "official_daily_prices_eod",
            "execution_data_availability": "delayed_eod_replay_after_session_close",
        },
        "formal_credit": False,
        "broker_order_allowed": False,
    }
    bound = bind_paper_execution_result_to_capture(paper_result, capture)
    assert bound["execution_event_time_proven"] is True
    assert bound["formal_consumer_compatible"] is True
    assert bound["execution_replay_mode"] == "same_session_event_time_capture"
    bound_source = bound["market_source"]
    assert isinstance(bound_source, dict)
    assert str(bound_source["execution_source_capture_path"]).startswith(
        str(tmp_path / "controlled-output")
    )
    eligible, reason = formal_daily_input_producer_module._paper_receipt_formal_eligibility(
        bound,
        fills=[{"fill": fill}],
        execution_date=date(2026, 9, 7),
        recorded_at=datetime(2026, 9, 7, 1, 0, 4, tzinfo=ZoneInfo("UTC")),
        observed=datetime(2026, 9, 7, 1, 5, tzinfo=ZoneInfo("UTC")),
    )
    assert eligible is True
    assert reason is None

    candidate_body = dict(paper_result)
    candidate_body["content_sha256"] = formal_daily_input_producer_module._payload_hash(
        paper_result
    )
    candidate_path = tmp_path / "paper-candidate.json"
    candidate_path.write_bytes(
        (
            formal_daily_input_producer_module._canonical_json(candidate_body) + "\n"
        ).encode("utf-8")
    )
    bound_path = tmp_path / "bound-output" / "paper-event-bound.json"
    bound_file = bind_paper_candidate_file_to_capture(
        candidate_path,
        capture_manifest_path=Path(str(capture["manifest_path"])),
        output_path=bound_path,
        allowed_output_root=tmp_path / "bound-output",
    )
    assert bound_file["bound_candidate_readback_verified"] is True
    assert bound_file["candidate_path"] == str(bound_path.resolve())
    bound_file_payload = json.loads(bound_path.read_text(encoding="utf-8"))
    assert bound_file_payload["event_source_binding"]["capture_file_hash"] == (
        bound_source["execution_source_capture_file_hash"]
    )

    mismatched = dict(paper_result)
    mismatched_recommendation = dict(recommendation)
    mismatched_recommendation["result_id"] = "other-recommendation"
    mismatched["recommendation"] = mismatched_recommendation
    with pytest.raises(PaperEventSourceCaptureError, match="recommendation identity mismatch"):
        bind_paper_execution_result_to_capture(mismatched, capture)


def test_paper_event_capture_custody_replay_rejects_modified_or_missing_raw(
    tmp_path: Path,
) -> None:
    """正式 publication 的 raw custody 被改寫或遺失時，retry 必須拒絕。"""

    raw_payload = {
        "rtcode": "000",
        "rtmessage": "OK",
        "msgArray": [
            {
                "c": "2330",
                "ex": "tse",
                "d": "20260907",
                "t": "09:00:00",
                "tlong": "1788742800000",
                "o": "10.20",
            }
        ],
    }
    raw = formal_daily_input_producer_module._canonical_json(raw_payload).encode(
        "utf-8"
    )

    class _Response:
        status = 200
        headers = {"Content-Type": "application/json"}

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def geturl(self) -> str:
            return formal_daily_input_producer_module._twse_mis_request_url(
                "tse_2330.tw"
            )

        def read(self, limit: int) -> bytes:
            del limit
            return raw

    capture_result = capture_twse_session_open_prices(
        symbols=("2330",),
        execution_date=date(2026, 9, 7),
        output_dir=tmp_path / "source-capture",
        now=datetime(2026, 9, 7, 1, 0, 1, tzinfo=ZoneInfo("UTC")),
        fetcher=lambda request, timeout: _Response(),
    )
    source = dict(capture_result["market_source"])
    source["execution_event_time_proven"] = True
    run_dir = tmp_path / "causal-run"
    run_dir.mkdir()
    projection: dict[str, object] = {
        "formal_eligible": True,
        "verified": True,
        "formal_ready": True,
        "receipts": [
            {
                "recorded_at": "2026-09-07T01:00:04+00:00",
                "market_source": source,
            }
        ],
    }
    projection = formal_daily_input_producer_module._persist_paper_event_capture_custody(
        projection=projection,
        run_dir=run_dir,
    )
    custody = projection["paper_event_capture_custody"]
    assert isinstance(custody, dict)
    fill = {
        "fill_id": "fill-1",
        "order_id": "order-1",
        "source_event_id": "paper-event-1",
        "portfolio_id": "paper-main",
        "stock_code": "2330",
        "side": "buy",
        "event_date": "2026-09-07",
        "filled_quantity": 1000,
        "status": "filled",
        "reference_price": "10.20",
        "fill_price": "10.21",
    }
    fill_row = {
        **fill,
        "content_hash": formal_daily_input_producer_module._payload_hash(fill),
    }
    fill_body = {
        "schema_version": formal_daily_input_producer_module.FORMAL_PAPER_SOURCE_CUSTODY_SCHEMA_VERSION,
        "kind": "paper_fills",
        "source_path": "C:/temporary/paper-ledger.sqlite",
        "source_content_hash": "sha256:" + "0" * 64,
        "row_count": 1,
        "rows": [fill_row],
    }
    fill_payload = {
        **fill_body,
        "custody_hash": formal_daily_input_producer_module._payload_hash(fill_body),
    }
    fill_custody_path = run_dir / "fill_source_custody.json"
    formal_daily_input_producer_module._write_immutable_bytes_atomic(
        fill_custody_path,
        (
            formal_daily_input_producer_module._canonical_json(fill_payload) + "\n"
        ).encode("utf-8"),
        "test fill custody",
    )
    result = {"fill_source_custody_path": str(fill_custody_path)}
    eligible, reason = formal_daily_input_producer_module._revalidate_paper_event_capture_retry(
        run_dir=run_dir,
        result=result,
        projection=projection,
        observed=datetime(2026, 9, 7, 1, 5, tzinfo=ZoneInfo("UTC")),
    )
    assert eligible is True
    assert reason == "paper_execution_capture_custody_revalidated"

    raw_path = Path(str(custody["raw_response_path"]))
    original_raw = raw_path.read_bytes()
    raw_path.write_bytes(original_raw + b"tampered")
    eligible, reason = formal_daily_input_producer_module._revalidate_paper_event_capture_retry(
        run_dir=run_dir,
        result=result,
        projection=projection,
        observed=datetime(2026, 9, 7, 1, 5, tzinfo=ZoneInfo("UTC")),
    )
    assert eligible is False
    assert reason == "paper_execution_capture_custody_raw_hash_mismatch"
    raw_path.unlink()
    eligible, reason = formal_daily_input_producer_module._revalidate_paper_event_capture_retry(
        run_dir=run_dir,
        result=result,
        projection=projection,
        observed=datetime(2026, 9, 7, 1, 5, tzinfo=ZoneInfo("UTC")),
    )
    assert eligible is False
    assert reason == "paper event custody raw response file is missing"


def test_causal_ledger_retry_rejects_legacy_and_v2_without_capture_custody(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """舊 v1 與沒有 raw custody 的 v2 projection 都不能升格 retry。"""

    chain = _prepare_paper_chain(tmp_path, monkeypatch=monkeypatch)
    publication_root = tmp_path / "formal-publication"
    result = _run_formal(
        tmp_path,
        chain,
        label="retry-schema",
        publication_root=publication_root,
    )
    inputs = result["inputs"]
    assert isinstance(inputs, dict)
    ledger = inputs["formal_ledger_candidate"]
    assert isinstance(ledger, dict)
    run_dir = publication_root / "causal_ledger" / str(ledger["publication_run_id"])
    context_path = run_dir / "publication_context.json"
    receipt_path = run_dir / "receipt.json"
    receipt_path.unlink()
    context = json.loads(context_path.read_text(encoding="utf-8"))

    def _rewrite_projection(schema: str) -> None:
        rewritten = dict(context)
        rewritten_result = dict(rewritten["result"])
        projection = dict(rewritten_result["paper_execution_receipt_projection"])
        projection.update(
            {
                "formal_eligibility_schema_version": schema,
                "formal_eligible": True,
                "verified": True,
                "formal_ready": True,
            }
        )
        rewritten_result["paper_execution_receipt_projection"] = projection
        rewritten["result"] = rewritten_result
        rewritten.pop("context_hash", None)
        rewritten["context_hash"] = formal_daily_input_producer_module._payload_hash(
            rewritten
        )
        context_path.unlink()
        context_path.write_bytes(
            (
                formal_daily_input_producer_module._canonical_json(rewritten) + "\n"
            ).encode("utf-8")
        )

    _rewrite_projection("paper-receipt-formal-eligibility.v1")
    retry = formal_daily_input_producer_module._load_ledger_publication_retry(
        run_dir,
        observed=FORMAL_OBSERVED,
        snapshot_source_hash=str(ledger["snapshot_source_content_hash"]),
        fill_source_hash=str(ledger["fill_source_content_hash"]),
        recover_missing_receipt=False,
    )
    retry_projection = retry["paper_execution_receipt_projection"]
    assert isinstance(retry_projection, dict)
    assert retry_projection["formal_eligible"] is False
    assert retry_projection["reason"] == (
        "paper_execution_receipt_legacy_schema_not_retryable"
    )

    _rewrite_projection("paper-receipt-formal-eligibility.v2")
    retry = formal_daily_input_producer_module._load_ledger_publication_retry(
        run_dir,
        observed=FORMAL_OBSERVED,
        snapshot_source_hash=str(ledger["snapshot_source_content_hash"]),
        fill_source_hash=str(ledger["fill_source_content_hash"]),
        recover_missing_receipt=False,
    )
    retry_projection = retry["paper_execution_receipt_projection"]
    assert isinstance(retry_projection, dict)
    assert retry_projection["formal_eligible"] is False
    assert retry_projection["reason"] == (
        "paper_execution_capture_custody_missing_for_retry"
    )


def test_paper_receipt_matching_ids_still_reject_changed_ledger_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """相同 fill IDs 不足以掩蓋 receipt 與 SQLite 欄位內容的漂移。"""

    chain = _prepare_paper_chain(tmp_path, monkeypatch=monkeypatch)
    ledger_path = Path(chain["ledger"])
    fill = PaperTradeLedgerRepository(ledger_path).list()[0]
    with sqlite3.connect(ledger_path) as connection:
        # Queue readback checks identity/safety fields, so deliberately change
        # a financial column that ID-only validation would leave untouched.
        connection.execute(
            "UPDATE paper_trade_ledger SET commission = ? WHERE fill_id = ?",
            ("999.99", fill.fill_id),
        )

    current_fills = formal_daily_input_producer_module._read_paper_fills(ledger_path)
    operational_receipt = chain["paper_result"]["operational_receipt"]
    assert isinstance(operational_receipt, dict)
    projection = formal_daily_input_producer_module._paper_execution_receipt_projection(
        receipt_root=Path(str(operational_receipt["path"])).parent,
        snapshot_path=Path(chain["state"]),
        fill_path=ledger_path,
        fills=current_fills,
        observed=FORMAL_OBSERVED,
    )

    assert projection["custody_verified"] is False
    assert projection["formal_eligible"] is False
    assert any(
        "paper_ledger_row_mismatch" in str(item)
        and "commission" in str(item)
        for item in projection["rejected_receipts"]
    )


def test_paper_event_capture_resolver_binds_exact_recommendation_bucket(
    tmp_path: Path,
) -> None:
    """EOD resolver 只讀同 execution date／完整 recommendation hash 的 manifest。"""

    recommendation_path = tmp_path / "recommendation.json"
    _write_recommendation(recommendation_path)
    raw = formal_daily_input_producer_module._canonical_json(
        {
            "rtcode": "000",
            "rtmessage": "OK",
            "msgArray": [
                {
                    "c": "2330",
                    "ex": "tse",
                    "d": "20260907",
                    "t": "09:00:00",
                    "tlong": "1788742800000",
                    "o": "10.20",
                }
            ],
        }
    ).encode("utf-8")

    class _Response:
        status = 200
        headers = {"Content-Type": "application/json"}

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def geturl(self) -> str:
            return formal_daily_input_producer_module._twse_mis_request_url(
                "tse_2330.tw"
            )

        def read(self, limit: int) -> bytes:
            del limit
            return raw

    controlled = tmp_path / "controlled"
    capture = capture_twse_session_open_prices_for_recommendation(
        recommendation_path=recommendation_path,
        execution_date=date(2026, 9, 7),
        output_dir=tmp_path / "temp-capture",
        durable_root=controlled / "event_captures",
        allowed_durable_root=controlled,
        now=datetime(2026, 9, 7, 1, 0, 2, tzinfo=ZoneInfo("UTC")),
        fetcher=lambda request, timeout: _Response(),
    )
    resolved = resolve_persisted_twse_event_source_capture_for_recommendation(
        recommendation_path=recommendation_path,
        execution_date=date(2026, 9, 7),
        durable_root=controlled / "event_captures",
        allowed_durable_root=controlled,
        observed=datetime(2026, 9, 7, 2, 0, tzinfo=ZoneInfo("UTC")),
    )
    assert resolved is not None
    assert resolved["manifest_path"] == capture["manifest_path"]
    assert resolved["recommendation"] == capture["recommendation"]
    assert resolved["readback_verified"] is True


def test_paper_event_capture_rejects_date_junction_before_source_fetch(
    tmp_path: Path,
) -> None:
    """日期 bucket 若為 junction，不能把 durable bytes 寫到 output 外。"""

    recommendation_path = tmp_path / "recommendation.json"
    _write_recommendation(recommendation_path)
    controlled = tmp_path / "controlled"
    durable_root = controlled / "event_captures"
    durable_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    date_link = durable_root / "2026-09-07"
    try:
        date_link.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory reparse point unavailable: {error}")

    with pytest.raises(PaperEventSourceCaptureError, match="symlink or junction"):
        resolve_persisted_twse_event_source_capture_for_recommendation(
            recommendation_path=recommendation_path,
            execution_date=date(2026, 9, 7),
            durable_root=durable_root,
            allowed_durable_root=controlled,
            observed=datetime(2026, 9, 7, 1, 0, tzinfo=ZoneInfo("UTC")),
        )


def test_scheduled_event_capture_reads_queue_persists_and_replays_without_refetch(
    tmp_path: Path,
) -> None:
    """自然 caller 完成 queue→官方 capture→durable manifest，重跑不重抓。"""

    recommendation_root = tmp_path / "recommendation-queue"
    recommendation_root.mkdir()
    recommendation_path = recommendation_root / "scheduled_rec_20260904.json"
    _write_recommendation(recommendation_path)
    market_db = tmp_path / "market.sqlite"
    market_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(market_db) as connection:
        connection.execute("CREATE TABLE daily_prices (日期 TEXT)")
    controlled = tmp_path / "controlled"
    calendar = _ChainCalendar(tmp_path / "calendar.sqlite")
    raw = formal_daily_input_producer_module._canonical_json(
        {
            "rtcode": "000",
            "rtmessage": "OK",
            "msgArray": [
                {
                    "c": "2330",
                    "ex": "tse",
                    "d": "20260907",
                    "t": "09:00:00",
                    "tlong": "1788742800000",
                    "o": "10.20",
                }
            ],
        }
    ).encode("utf-8")
    requested: list[str] = []

    class _Response:
        status = 200
        headers = {"Content-Type": "application/json"}

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def geturl(self) -> str:
            return formal_daily_input_producer_module._twse_mis_request_url(
                "tse_2330.tw"
            )

        def read(self, limit: int) -> bytes:
            del limit
            return raw

    def fetcher(request: object, timeout: float) -> _Response:
        del timeout
        requested.append(str(request.full_url))  # type: ignore[attr-defined]
        return _Response()

    first, first_exit = run_capture(
        now=datetime(2026, 9, 7, 1, 0, 2, tzinfo=ZoneInfo("UTC")),
        recommendation_root=recommendation_root,
        market_db=market_db,
        durable_root=controlled / "event_captures",
        allowed_durable_root=controlled,
        receipt_root=controlled / "receipts",
        status_root=controlled / "status",
        calendar=calendar,
        load_runtime=False,
        fetcher=fetcher,
        retry_delay_seconds=0,
    )
    assert first_exit == 0
    assert first["status"] == "source_capture_durable"
    assert first["durable_readback_verified"] is True
    assert first["temporary_cleanup"] == "removed"
    assert len(requested) == 1
    manifest_path = Path(str(first["manifest_path"]))
    assert manifest_path.is_file()
    assert Path(str(first["status_path"])).is_file()

    second, second_exit = run_capture(
        now=datetime(2026, 9, 7, 1, 5, 2, tzinfo=ZoneInfo("UTC")),
        recommendation_root=recommendation_root,
        market_db=market_db,
        durable_root=controlled / "event_captures",
        allowed_durable_root=controlled,
        receipt_root=controlled / "receipts",
        status_root=controlled / "status",
        calendar=calendar,
        load_runtime=False,
        fetcher=lambda request, timeout: pytest.fail(
            "complete durable capture must not issue another GET"
        ),
        retry_delay_seconds=0,
    )
    assert second_exit == 0
    assert second["status"] == "source_capture_durable"
    assert second["idempotent_replay"] is True
    assert second["manifest_path"] == str(manifest_path)
    assert len(requested) == 1


def test_scheduled_event_capture_retry_pins_initial_recommendation_identity(
    tmp_path: Path,
) -> None:
    """暫時 GET 失敗後 recommendation 被換檔，第二次必拒絕且保留診斷。"""

    recommendation_root = tmp_path / "recommendation-queue"
    recommendation_root.mkdir()
    recommendation_path = recommendation_root / "scheduled_rec_20260904.json"
    _write_recommendation(recommendation_path)
    original = recommendation_path.read_bytes()
    market_db = tmp_path / "market.sqlite"
    with sqlite3.connect(market_db) as connection:
        connection.execute("CREATE TABLE daily_prices (日期 TEXT)")
    controlled = tmp_path / "controlled"
    calendar = _ChainCalendar(tmp_path / "calendar.sqlite")
    call_count = 0

    def changing_fetcher(request: object, timeout: float) -> object:
        del request, timeout
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            recommendation_path.write_bytes(original + b"\n")
            raise URLError("temporary source unavailable")
        pytest.fail("changed recommendation must fail before second GET")

    result, exit_code = run_capture(
        now=datetime(2026, 9, 7, 1, 0, 2, tzinfo=ZoneInfo("UTC")),
        recommendation_root=recommendation_root,
        market_db=market_db,
        durable_root=controlled / "event_captures",
        allowed_durable_root=controlled,
        receipt_root=controlled / "receipts",
        status_root=controlled / "status",
        calendar=calendar,
        load_runtime=False,
        fetcher=changing_fetcher,
        max_attempts=2,
        retry_delay_seconds=0,
    )
    assert exit_code == 2
    assert result["status"] == "blocked"
    attempts = result["capture_attempts"]
    assert isinstance(attempts, list)
    assert len(attempts) == 2
    assert attempts[0]["retryable"] is True
    assert attempts[1]["retryable"] is False
    assert "file hash changed" in str(attempts[1]["reason"])


def test_isolated_eod_writer_binds_durable_capture_then_formal_reads_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """實際 isolated writer 走 durable capture、receipt，再交 Formal consumer。"""

    monkeypatch.delenv("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY", raising=False)
    monkeypatch.delenv("RULE_CHAMPION_CONTROLLED_STORE_ID", raising=False)
    calendar = _ChainCalendar(tmp_path / "calendar.sqlite")
    source_root = tmp_path / "source"
    source_state_db = (
        source_root / "output" / "paper_portfolio" / "paper_portfolio.sqlite"
    )
    market_db = source_root / "sqlite" / "twstock.db"
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline)
    market_db.parent.mkdir(parents=True, exist_ok=True)
    _write_market(market_db)
    preopen = run_paper_preopen(
        baseline_path=baseline,
        state_db=source_state_db,
        market_db=market_db,
        output_root=tmp_path / "source-preopen-output",
        decision_at=datetime(2026, 9, 7, 8, 30, tzinfo=TAIPEI),
        now=datetime(2026, 9, 7, 8, 30, 1, tzinfo=TAIPEI),
        calendar=calendar,
        ledger_db=tmp_path / "source-ledger.sqlite",
    )
    assert preopen["status"] == "passed"

    recommendation_root = source_root / "output" / "recommendation" / "runs"
    recommendation_root.mkdir(parents=True, exist_ok=True)
    recommendation_path = recommendation_root / "scheduled_rec_20260904.json"
    _write_recommendation(recommendation_path)

    repo = tmp_path / "repo"
    operation_root = repo / "output" / "paper_execution_eod_replay"
    state_db = operation_root / "paper_portfolio" / "paper_portfolio.sqlite"
    ledger_db = operation_root / "paper_trade_ledger.sqlite"
    state_seed_manifest = state_db.parent / "state_seed_manifest.json"
    ensure_repo_state_from_readonly_source(
        source=source_state_db,
        target=state_db,
        manifest_path=state_seed_manifest,
        observed_at=EOD_OBSERVED.astimezone(ZoneInfo("UTC")),
    )
    # The policy adapter reads the append-only ledger history before the first
    # EOD append; an empty, schema-valid repository ledger is still a real
    # source boundary and must exist before run_isolated starts.
    PaperTradeLedgerRepository(ledger_db)

    sector_path = tmp_path / "pit-sector.json"
    sector_hash = _write_sector_sidecar(sector_path)
    capture_root = operation_root / "event_captures"
    raw = formal_daily_input_producer_module._canonical_json(
        {
            "rtcode": "000",
            "rtmessage": "OK",
            "msgArray": [
                {
                    "c": "2330",
                    "ex": "tse",
                    "d": "20260907",
                    "t": "09:00:00",
                    "tlong": "1788742800000",
                    "o": "10.20",
                }
            ],
        }
    ).encode("utf-8")

    class _Response:
        status = 200
        headers = {"Content-Type": "application/json"}

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def geturl(self) -> str:
            return formal_daily_input_producer_module._twse_mis_request_url(
                "tse_2330.tw"
            )

        def read(self, limit: int) -> bytes:
            del limit
            return raw

    capture = capture_twse_session_open_prices_for_recommendation(
        recommendation_path=recommendation_path,
        execution_date=date(2026, 9, 7),
        output_dir=tmp_path / "capture-temp",
        durable_root=capture_root,
        allowed_durable_root=operation_root,
        now=datetime(2026, 9, 7, 1, 0, 2, tzinfo=ZoneInfo("UTC")),
        fetcher=lambda request, timeout: _Response(),
    )
    assert capture["durable_readback_verified"] is True

    scope_manifest = operation_root / "scope_manifest_v2.json"
    constants = {
        "ROOT": repo,
        "DEFAULT_DATA_ROOT": source_root,
        "OPERATIONAL_ROOT": operation_root,
        "CANDIDATE_ROOT": operation_root / "candidates",
        "RECEIPT_ROOT": operation_root / "receipts",
        "LEDGER_DB": ledger_db,
        "SOURCE_STATE_DB": source_state_db,
        "PAPER_STATE_ROOT": state_db.parent,
        "STATE_SEED_MANIFEST": state_seed_manifest,
        "STATE_DB": state_db,
        "MARKET_DB": market_db,
        "RECOMMENDATION_ROOT": recommendation_root,
        "EVENT_CAPTURE_ROOT": capture_root,
        "SCOPE_MANIFEST": scope_manifest,
    }
    for name, value in constants.items():
        monkeypatch.setattr(isolated_paper_runner, name, value)
    monkeypatch.setattr(
        isolated_paper_runner,
        "load_optional_formal_runtime_config",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        isolated_paper_runner,
        "OfficialTradingCalendar",
        lambda **kwargs: calendar,
    )
    monkeypatch.setattr(
        isolated_paper_runner,
        "_resolve_pit_sector_manifest",
        lambda observed: (
            sector_path,
            sector_hash,
            {
                "status": "selected",
                "manifest_path": str(sector_path),
                "manifest_file_hash": sector_hash,
            },
        ),
    )
    monkeypatch.setattr(
        isolated_paper_runner,
        "_refresh_calendar_cache",
        lambda observed: {
            "status": "cache_valid",
            "calendar_year": 2026,
            "refresh_attempted": False,
            "network_attempts": 0,
        },
    )
    monkeypatch.setattr(
        isolated_paper_runner,
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

    direct_selected, direct_reason = resolve_pending_recommendation(
        recommendation_root,
        observed=EOD_OBSERVED.astimezone(ZoneInfo("UTC")),
        market_db=market_db,
        calendar=calendar,
        receipt_root=operation_root / "receipts",
    )
    assert direct_selected == recommendation_path, direct_reason
    isolated_result = isolated_paper_runner.run_isolated(now=EOD_OBSERVED)
    assert isolated_result["status"] == "machine_verified_candidate"
    binding = isolated_result["paper_event_source_binding"]
    assert isinstance(binding, dict)
    assert binding["status"] == "bound"
    assert binding["readback_verified"] is True
    operational_receipt = isolated_result["operational_receipt"]
    assert isinstance(operational_receipt, dict)
    receipt_path = Path(str(operational_receipt["path"]))
    receipt_payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt_payload["queue_state"] == "processed"
    assert receipt_payload["result"]["paper_event_source_binding"]["status"] == "bound"
    bound_candidate = Path(str(isolated_result["candidate_path"]))
    assert bound_candidate.name == "paper_execution_candidate_bound.json"
    assert bound_candidate.is_file()
    assert Path(str(binding["capture_manifest_path"])).is_file()

    clock_root = tmp_path / "clock"
    clock_root.mkdir()
    clock_path, _, _, _ = _clock(clock_root)
    formal_result = _run_formal(
        tmp_path,
        {
            "calendar": calendar,
            "market": market_db,
            "state": state_db,
            "ledger": ledger_db,
            "clock": clock_path,
            "paper_result": isolated_result,
        },
        label="isolated-e2e",
        publication_root=tmp_path / "formal-publication",
    )
    assert formal_result["status"] == "candidate_only"
    inputs = formal_result["inputs"]
    assert isinstance(inputs, dict)
    formal_ledger = inputs["formal_ledger_candidate"]
    assert isinstance(formal_ledger, dict)
    assert formal_ledger["consumer_verified"] is True
    assert formal_ledger["paper_execution_receipt_verified"] is True, formal_ledger
    projection = formal_ledger["paper_execution_receipt_projection"]
    assert isinstance(projection, dict)
    assert projection["custody_verified"] is True
    assert projection["formal_eligible"] is True
    assert formal_result["formal_ready_input_count"] != 3
