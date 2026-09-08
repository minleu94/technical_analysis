from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import gc
import json
from pathlib import Path
import shutil
import sqlite3
from zoneinfo import ZoneInfo

import pytest

import data_module.formal_daily_input_producer as formal_daily_input_producer_module
from app_module.paper_portfolio_snapshot_repository import (
    PaperPortfolioPositionSnapshot,
    PaperPortfolioSnapshot,
    PaperPortfolioSnapshotRepository,
)
from app_module.paper_trade_ledger import PaperTradeFill, PaperTradeLedgerRepository
from data_module.formal_daily_input_producer import (
    DailyFormalInputPaths,
    FormalDailyInputProducerError,
    OfficialSourceResponse,
    _produce_formal_ledger_candidate,
    _produce_pit_candidate,
    _produce_rule_candidate,
    build_daily_formal_input_preflight,
    run_daily_formal_input_producer,
    _calendar_projection,
)
from data_module.official_trading_calendar import OfficialTradingCalendar
from data_module.prospective_formal_clock import load_clock_manifest_for_capture
from data_module.prospective_official_pit_source import (
    OFFICIAL_COMPANY_SOURCE_DEFINITIONS,
)
from tests.test_prospective_rule_only_decision import _clock, _market_db


TAIPEI = ZoneInfo("Asia/Taipei")


class _AdjacentTradingCalendar(OfficialTradingCalendar):
    """隔離測試用的官方日曆證據，不使用週末推定。"""

    def is_official_trading_day(
        self,
        target_date: date,
        allow_online_probe: bool = True,
    ) -> tuple[bool | None, str]:
        return True, "test_official_calendar_evidence"

    def get_trading_days_in_range(
        self,
        start_date: date,
        end_date: date,
        allow_online_probe: bool = True,
    ) -> list[dict[str, object]]:
        return [
            {
                "date": current,
                "date_str": current.isoformat(),
                "is_trading_day": current in {start_date, end_date},
                "reason_code": "test_official_calendar_evidence",
            }
            for offset in range((end_date - start_date).days + 1)
            for current in (start_date + timedelta(days=offset),)
        ]


class _ClosedFillCalendar(_AdjacentTradingCalendar):
    def is_official_trading_day(
        self,
        target_date: date,
        allow_online_probe: bool = True,
    ) -> tuple[bool | None, str]:
        if target_date == date(2026, 8, 17):
            return False, "test_fill_day_closed"
        return super().is_official_trading_day(
            target_date,
            allow_online_probe=allow_online_probe,
        )


class _CaptureCalendar(OfficialTradingCalendar):
    """隔離測試用的休市／日曆不可得結果。"""

    def __init__(
        self,
        db_path: Path,
        *,
        result: bool | None,
        reason: str,
    ) -> None:
        super().__init__(db_path)
        self._result = result
        self._reason = reason

    def is_official_trading_day(
        self,
        target_date: date,
        allow_online_probe: bool = True,
    ) -> tuple[bool | None, str]:
        return self._result, self._reason


def _paper_sources(
    tmp_path: Path,
    *,
    fill_date: str = "2026-08-17",
) -> tuple[Path, Path]:
    snapshots_path = tmp_path / "paper_snapshots.sqlite"
    snapshots = PaperPortfolioSnapshotRepository(snapshots_path)
    snapshots.append(
        PaperPortfolioSnapshot(
            snapshot_id="snapshot-20260817",
            portfolio_id="paper-main",
            decision_date="2026-08-17",
            source_result_id="paper-result-20260817",
            cash=Decimal("9000.00"),
            total_value=Decimal("10000.00"),
            positions=(
                PaperPortfolioPositionSnapshot(
                    stock_code="2330",
                    quantity=10,
                    mark_price=Decimal("100.00"),
                    market_value=Decimal("1000.00"),
                    weight_bp=1000,
                ),
            ),
        )
    )
    snapshots.append(
        PaperPortfolioSnapshot(
            snapshot_id="snapshot-20260818",
            portfolio_id="paper-main",
            decision_date="2026-08-18",
            source_result_id="paper-result-20260818",
            cash=Decimal("8000.00"),
            total_value=Decimal("10000.00"),
            positions=(
                PaperPortfolioPositionSnapshot(
                    stock_code="2330",
                    quantity=20,
                    mark_price=Decimal("100.00"),
                    market_value=Decimal("2000.00"),
                    weight_bp=2000,
                ),
            ),
        )
    )

    fills_path = tmp_path / "paper_fills.sqlite"
    PaperTradeLedgerRepository(fills_path).append(
        PaperTradeFill(
            fill_id="fill-20260817-2330",
            order_id="order-20260817-2330",
            portfolio_id="paper-main",
            event_date=fill_date,
            stock_code="2330",
            side="buy",
            requested_quantity=10,
            filled_quantity=10,
            reference_price=Decimal("100.00"),
            fill_price=Decimal("100.00"),
            commission=Decimal("0.00"),
            tax=Decimal("0.00"),
            slippage_cost=Decimal("0.00"),
            turnover_bp=1000,
            execution_gap_bp=0,
            status="filled",
            source_event_id="source-event-20260817-2330",
        )
    )
    return snapshots_path, fills_path


def _pit_raw_payloads() -> dict[str, bytes]:
    return {
        "twse": json.dumps(
            [
                {"公司代號": "1101", "產業別": "01", "出表日期": "20260907"},
                {"公司代號": "1102", "產業別": "02", "出表日期": "20260907"},
            ],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8"),
        "tpex": json.dumps(
            [
                {
                    "SecuritiesCompanyCode": "5501",
                    "SecuritiesIndustryCode": "03",
                    "Date": "2026-09-07",
                },
                {
                    "SecuritiesCompanyCode": "5502",
                    "SecuritiesIndustryCode": "05",
                    "Date": "2026-09-07",
                },
            ],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8"),
    }


def _candidate_paths(
    tmp_path: Path,
    *,
    clock_path: Path,
    snapshots_path: Path,
    fills_path: Path,
    publication_root: Path | None = None,
) -> DailyFormalInputPaths:
    return DailyFormalInputPaths(
        output_root=tmp_path / "producer-output",
        development_output_root=tmp_path / "technical_analysis_development_output",
        market_db=tmp_path / "unused-market.sqlite",
        clock_manifest=clock_path,
        paper_snapshot_db_path=snapshots_path,
        paper_trade_ledger_db_path=fills_path,
        publication_root=publication_root,
    )


def test_paper_fill_on_start_boundary_is_consumed_and_read_back(
    tmp_path: Path,
) -> None:
    clock_path, _, _, _ = _clock(tmp_path)
    snapshots_path, fills_path = _paper_sources(tmp_path)
    PaperPortfolioSnapshotRepository(snapshots_path).append(
        PaperPortfolioSnapshot(
            snapshot_id="snapshot-pre-activation",
            portfolio_id="paper-main",
            decision_date="2026-08-14",
            source_result_id="paper-result-pre-activation",
            cash=Decimal("9000.00"),
            total_value=Decimal("10000.00"),
            positions=(
                PaperPortfolioPositionSnapshot(
                    stock_code="2330",
                    quantity=10,
                    mark_price=Decimal("100.00"),
                    market_value=Decimal("1000.00"),
                    weight_bp=1000,
                ),
            ),
        )
    )
    paths = _candidate_paths(
        tmp_path,
        clock_path=clock_path,
        snapshots_path=snapshots_path,
        fills_path=fills_path,
    )
    paths.output_root.mkdir()

    result = _produce_formal_ledger_candidate(
        paths=paths,
        output_root=paths.output_root,
        observed=datetime(2026, 8, 19, 9, 5, tzinfo=TAIPEI),
        calendar=_AdjacentTradingCalendar(tmp_path / "unused.sqlite"),
    )

    assert result["consumer_verified"] is True
    assert result["formal_consumer_compatible"] is True
    assert result["source_read_consistency"] == "sqlite_read_transaction"
    assert result["snapshot_rows_read"] == 3
    assert result["snapshot_rows_used"] == 2
    assert result["pre_activation_snapshot_rows_excluded"] == 1
    assert str(result["snapshot_source_content_hash"]).startswith("sha256:")
    assert str(result["fill_source_content_hash"]).startswith("sha256:")
    manifest = json.loads(Path(str(result["manifest_path"])).read_text(encoding="utf-8"))
    assert manifest["manifest_hash"].startswith("sha256:")
    with sqlite3.connect(Path(str(result["sqlite_path"]))) as connection:
        assert connection.execute("SELECT COUNT(*) FROM transitions").fetchone()[0] == 1


def test_paper_fill_on_end_boundary_is_rejected_as_future_interval(
    tmp_path: Path,
) -> None:
    clock_path, _, _, _ = _clock(tmp_path)
    snapshots_path, fills_path = _paper_sources(
        tmp_path,
        fill_date="2026-08-18",
    )
    paths = _candidate_paths(
        tmp_path,
        clock_path=clock_path,
        snapshots_path=snapshots_path,
        fills_path=fills_path,
    )
    paths.output_root.mkdir()

    with pytest.raises(
        FormalDailyInputProducerError,
        match=r"\[start, end\) snapshot intervals",
    ):
        _produce_formal_ledger_candidate(
            paths=paths,
            output_root=paths.output_root,
            observed=datetime(2026, 8, 19, 9, 5, tzinfo=TAIPEI),
            calendar=_AdjacentTradingCalendar(tmp_path / "unused.sqlite"),
        )


def test_paper_fill_requires_independent_official_trading_day_evidence(
    tmp_path: Path,
) -> None:
    clock_path, _, _, _ = _clock(tmp_path)
    snapshots_path, fills_path = _paper_sources(tmp_path)
    paths = _candidate_paths(
        tmp_path,
        clock_path=clock_path,
        snapshots_path=snapshots_path,
        fills_path=fills_path,
    )
    paths.output_root.mkdir()

    with pytest.raises(
        FormalDailyInputProducerError,
        match="paper fill event date is not an officially proven trading day",
    ):
        _produce_formal_ledger_candidate(
            paths=paths,
            output_root=paths.output_root,
            observed=datetime(2026, 8, 19, 9, 5, tzinfo=TAIPEI),
            calendar=_ClosedFillCalendar(tmp_path / "unused.sqlite"),
        )


def test_preflight_allows_follow_up_trading_day_after_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock_path, symbols_path, acceptance_path, _ = _clock(tmp_path)
    market_path = _market_db(tmp_path)
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY", "test-key")
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_ID", "controlled-store:test")
    paths = DailyFormalInputPaths(
        output_root=tmp_path / "output",
        development_output_root=tmp_path / "technical_analysis_development_output",
        market_db=market_path,
        clock_manifest=clock_path,
        universe_symbols=symbols_path,
        owner_acceptance=acceptance_path,
    )

    result = build_daily_formal_input_preflight(
        paths,
        now=datetime(2026, 8, 19, 9, 5, tzinfo=TAIPEI),
        calendar=_AdjacentTradingCalendar(market_path),
    )

    rule_capture = result["rule_capture"]
    assert isinstance(rule_capture, dict)
    assert rule_capture["eligible"] is True
    assert not any(
        "activation_day_not_current" in str(item)
        or "prospective_rule_session_mismatch" in str(item)
        for item in rule_capture["blockers"]
    )
    assert result["human_review_required"] is False


def test_preflight_missing_paper_fill_is_a_machine_blocker(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "snapshot.sqlite"
    with sqlite3.connect(snapshot_path) as connection:
        connection.execute(
            "CREATE TABLE paper_portfolio_snapshots (snapshot_id TEXT)"
        )
    paths = DailyFormalInputPaths(
        output_root=tmp_path / "output",
        development_output_root=tmp_path / "technical_analysis_development_output",
        market_db=tmp_path / "market.sqlite",
        paper_snapshot_db_path=snapshot_path,
    )

    result = build_daily_formal_input_preflight(paths)

    raw_blockers = result["blockers"]
    assert isinstance(raw_blockers, (list, tuple))
    blockers = {str(item) for item in raw_blockers}
    assert "formal_ledger_paper_fill_source_missing" in blockers
    assert result["human_review_required"] is False
    paper_sources = result["paper_sources"]
    assert isinstance(paper_sources, dict)
    fill_projection = paper_sources["paper_trade_ledger"]
    assert isinstance(fill_projection, dict)
    assert fill_projection["state"] == "missing"


def test_public_daily_run_connects_paper_source_to_formal_consumer(
    tmp_path: Path,
) -> None:
    clock_path, _, _, _ = _clock(tmp_path)
    snapshots_path, fills_path = _paper_sources(tmp_path)
    paths = DailyFormalInputPaths(
        output_root=tmp_path / "public-output",
        development_output_root=tmp_path / "technical_analysis_development_output",
        market_db=tmp_path / "unavailable-market.sqlite",
        clock_manifest=clock_path,
        paper_snapshot_db_path=snapshots_path,
        paper_trade_ledger_db_path=fills_path,
    )

    result = run_daily_formal_input_producer(
        paths,
        now=datetime(2026, 8, 19, 9, 5, tzinfo=TAIPEI),
        calendar=_AdjacentTradingCalendar(tmp_path / "unused.sqlite"),
    )

    assert result["status"] == "candidate_only"
    assert result["formal_ready_input_count"] == 0
    inputs = result["inputs"]
    assert isinstance(inputs, dict)
    ledger_result = inputs["formal_ledger_candidate"]
    assert isinstance(ledger_result, dict)
    assert ledger_result["consumer_verified"] is True
    assert ledger_result["candidate_only"] is True


def test_public_daily_run_reuses_cache_calendar_for_ledger_producer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Paper ledger producer 不得丟掉同一輪已驗證的 cache calendar。"""

    clock_path, _, _, _ = _clock(tmp_path)
    snapshots_path, fills_path = _paper_sources(tmp_path)
    calendar_cache = tmp_path / "calendar-cache"

    class _CacheRequiredCalendar(_AdjacentTradingCalendar):
        def __init__(
            self,
            db_path: Path,
            *,
            calendar_cache_path: Path,
            temporary_closure_path: Path,
        ) -> None:
            if calendar_cache_path != calendar_cache:
                raise AssertionError("calendar cache was not passed to runner")
            if temporary_closure_path != calendar_cache:
                raise AssertionError("temporary closure cache was not passed")
            super().__init__(db_path)

    monkeypatch.setattr(
        formal_daily_input_producer_module,
        "OfficialTradingCalendar",
        _CacheRequiredCalendar,
    )
    paths = DailyFormalInputPaths(
        output_root=tmp_path / "public-output",
        development_output_root=tmp_path / "technical_analysis_development_output",
        market_db=tmp_path / "unavailable-market.sqlite",
        clock_manifest=clock_path,
        paper_snapshot_db_path=snapshots_path,
        paper_trade_ledger_db_path=fills_path,
        official_calendar_cache_path=calendar_cache,
        official_temporary_closure_path=calendar_cache,
    )

    result = run_daily_formal_input_producer(
        paths,
        now=datetime(2026, 8, 19, 9, 5, tzinfo=TAIPEI),
    )

    inputs = result["inputs"]
    assert isinstance(inputs, dict)
    ledger_result = inputs["formal_ledger_candidate"]
    assert isinstance(ledger_result, dict)
    assert ledger_result["consumer_verified"] is True


def test_public_pit_handoff_reuses_the_preflight_calendar_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PIT handoff must consume the same official calendar evidence as preflight."""

    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY", "test-key")
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_ID", "controlled-store:test")
    instances: list[OfficialTradingCalendar] = []

    class _RecordingCalendar(OfficialTradingCalendar):
        def __init__(self, db_path: str | Path) -> None:
            super().__init__(db_path)
            instances.append(self)

        def is_official_trading_day(
            self,
            target_date: date,
            allow_online_probe: bool = True,
        ) -> tuple[bool | None, str]:
            del target_date, allow_online_probe
            return True, "test_official_calendar_evidence"

    monkeypatch.setattr(
        formal_daily_input_producer_module,
        "OfficialTradingCalendar",
        _RecordingCalendar,
    )
    monkeypatch.setattr(
        formal_daily_input_producer_module,
        "_produce_pit_candidate",
        lambda **_kwargs: {
            "status": "machine_verified_candidate",
            "candidate_only": True,
            "formal_consumer_compatible": False,
        },
    )
    import data_module.formal_pit_history_handoff as handoff_module

    captured: dict[str, object] = {}

    def record_handoff(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "status": "candidate_history_verified",
            "blockers": ["pit_formal_sidecar_publication_required"],
            "formal_ready": False,
            "formal_consumer_compatible": False,
        }

    monkeypatch.setattr(
        handoff_module,
        "persist_pit_candidate_history_handoff",
        record_handoff,
    )
    paths = DailyFormalInputPaths(
        output_root=tmp_path / "public-output",
        development_output_root=tmp_path / "technical_analysis_development_output",
        market_db=tmp_path / "market.sqlite",
        publication_root=tmp_path / "publication",
    )

    result = run_daily_formal_input_producer(
        paths,
        now=datetime.now(timezone.utc),
    )

    assert result["status"] == "candidate_only"
    assert len(instances) == 1
    assert captured["calendar"] is instances[0]


@pytest.mark.parametrize(
    ("calendar_result", "calendar_reason"),
    [
        (False, "test_official_holiday_closed"),
        (None, "test_official_calendar_unavailable"),
    ],
)
def test_public_daily_run_captures_pit_when_calendar_cannot_authorize_trading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    calendar_result: bool | None,
    calendar_reason: str,
) -> None:
    """PIT 現況 capture 與交易日授權分離，休市或日曆未知仍可保存來源。"""

    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY", "test-key")
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_ID", "controlled-store:test")
    raw = _pit_raw_payloads()
    captured_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    responses = {
        OFFICIAL_COMPANY_SOURCE_DEFINITIONS["twse"].endpoint: OfficialSourceResponse(
            body=raw["twse"],
            metadata={
                "requested_url": OFFICIAL_COMPANY_SOURCE_DEFINITIONS["twse"].endpoint,
                "final_url": OFFICIAL_COMPANY_SOURCE_DEFINITIONS["twse"].endpoint,
                "http_status": 200,
                "content_type": "application/json",
                "http_date": None,
                "http_last_modified": None,
                "captured_at": captured_at.isoformat(),
            },
        ),
        OFFICIAL_COMPANY_SOURCE_DEFINITIONS["tpex"].endpoint: OfficialSourceResponse(
            body=raw["tpex"],
            metadata={
                "requested_url": OFFICIAL_COMPANY_SOURCE_DEFINITIONS["tpex"].endpoint,
                "final_url": OFFICIAL_COMPANY_SOURCE_DEFINITIONS["tpex"].endpoint,
                "http_status": 200,
                "content_type": "application/json",
                "http_date": None,
                "http_last_modified": None,
                "captured_at": captured_at.isoformat(),
            },
        ),
    }
    market_path = _market_db(tmp_path)
    paths = DailyFormalInputPaths(
        output_root=tmp_path / "public-output",
        development_output_root=tmp_path / "technical_analysis_development_output",
        market_db=market_path,
    )
    observed = captured_at + timedelta(seconds=1)
    result = run_daily_formal_input_producer(
        paths,
        now=observed,
        calendar=_CaptureCalendar(
            market_path,
            result=calendar_result,
            reason=calendar_reason,
        ),
        fetch_source=lambda url: responses[url],
    )

    assert result["status"] == "candidate_only"
    assert result["formal_ready_input_count"] == 0
    preflight = result["preflight"]
    assert isinstance(preflight, dict)
    pit_preflight = preflight["pit_capture"]
    assert isinstance(pit_preflight, dict)
    assert pit_preflight["capture_eligible"] is True
    assert pit_preflight["trading_decision_eligible"] is False
    assert pit_preflight["trading_decision_blockers"] == [
        "pit_official_trading_day_not_proven"
    ]
    inputs = result["inputs"]
    assert isinstance(inputs, dict)
    pit = inputs["pit_candidate"]
    assert isinstance(pit, dict)
    assert pit["status"] == "machine_verified_candidate"
    assert pit["consumer_verified"] is True
    assert pit["trading_decision_eligible"] is False
    assert pit["trading_decision_blockers"] == [
        "pit_official_trading_day_not_proven"
    ]
    assert Path(str(pit["publication_path"])).is_file()
    assert Path(str(pit["receipt_path"])).is_file()
    assert Path(str(pit["operational_path"])).is_file()


def test_rule_candidate_supports_later_clock_day_and_reads_published_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock_path, symbols_path, acceptance_path, _ = _clock(tmp_path)
    market_path = _market_db(tmp_path)
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY", "test-key")
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_ID", "controlled-store:test")
    development_root = tmp_path / "technical_analysis_development_output"
    output_root = tmp_path / "rule-output"
    development_root.mkdir()
    output_root.mkdir()
    paths = DailyFormalInputPaths(
        output_root=output_root,
        development_output_root=development_root,
        market_db=market_path,
        clock_manifest=clock_path,
        universe_symbols=symbols_path,
        owner_acceptance=acceptance_path,
    )

    result = _produce_rule_candidate(
        paths=paths,
        output_root=output_root,
        clock=load_clock_manifest_for_capture(
            clock_path,
            now=datetime(2026, 8, 19, 9, 5, tzinfo=TAIPEI),
        ),
        now=datetime(2026, 8, 19, 9, 5, tzinfo=TAIPEI),
    )

    assert result["status"] == "machine_verified_candidate"
    assert result["consumer_verified"] is True
    assert result["consumer_manifest_hash"] == result["publisher_manifest_hash"]
    assert result["formal_consumer_verified"] is True
    assert result["formal_consumer_compatible"] is False
    assert result["candidate_only"] is True
    formal_manifest = Path(str(result["formal_manifest_path"]))
    formal_receipt = Path(str(result["receipt_path"]))
    assert formal_manifest.is_file()
    assert formal_receipt.is_file()
    formal_payload = json.loads(formal_manifest.read_text(encoding="utf-8"))
    assert formal_payload["schema_version"] == "rule-champion-snapshot-history.v1"
    assert formal_payload["formal_consumer_compatible"] is True
    receipt_payload = json.loads(formal_receipt.read_text(encoding="utf-8"))
    assert receipt_payload["input"] == "formal_rule_champion_snapshot_history"
    assert receipt_payload["result"]["formal_consumer_verified"] is True


def test_rule_formal_publication_is_durable_and_retry_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock_path, symbols_path, acceptance_path, _ = _clock(tmp_path)
    market_path = _market_db(tmp_path)
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY", "test-key")
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_ID", "controlled-store:test")
    observed = datetime(2026, 8, 19, 9, 5, tzinfo=TAIPEI)
    clock = load_clock_manifest_for_capture(clock_path, now=observed)
    publication_root = tmp_path / "persistent-output"
    first_development = tmp_path / "first" / "technical_analysis_development_output"
    first_output = tmp_path / "first" / "candidate-output"
    first_development.mkdir(parents=True)
    first_output.mkdir(parents=True)
    first = _produce_rule_candidate(
        paths=DailyFormalInputPaths(
            output_root=first_output,
            development_output_root=first_development,
            market_db=market_path,
            clock_manifest=clock_path,
            universe_symbols=symbols_path,
            owner_acceptance=acceptance_path,
            publication_root=publication_root,
        ),
        output_root=first_output,
        clock=clock,
        now=observed,
        publication_root=publication_root,
    )
    manifest_path = Path(str(first["formal_manifest_path"]))
    receipt_path = Path(str(first["publication_receipt_path"]))
    manifest_bytes = manifest_path.read_bytes()
    receipt_bytes = receipt_path.read_bytes()
    assert manifest_path == publication_root / "rule_history" / "2026-08-19" / "manifest.json"
    assert receipt_path == publication_root / "rule_history" / "2026-08-19" / "receipt.json"
    assert first["publication_status"] == "published"
    shutil.rmtree(first_development)
    shutil.rmtree(first_output)

    second_development = tmp_path / "second" / "technical_analysis_development_output"
    second_output = tmp_path / "second" / "candidate-output"
    second_development.mkdir(parents=True)
    second_output.mkdir(parents=True)
    second = _produce_rule_candidate(
        paths=DailyFormalInputPaths(
            output_root=second_output,
            development_output_root=second_development,
            market_db=market_path,
            clock_manifest=clock_path,
            universe_symbols=symbols_path,
            owner_acceptance=acceptance_path,
            publication_root=publication_root,
        ),
        output_root=second_output,
        clock=clock,
        now=observed,
        publication_root=publication_root,
    )
    assert second["publication_status"] == "idempotent_retry"
    assert second["idempotent_retry"] is True
    assert second["formal_manifest_hash"] == first["formal_manifest_hash"]
    assert manifest_path.read_bytes() == manifest_bytes
    assert receipt_path.read_bytes() == receipt_bytes


def test_rule_formal_publication_rejects_before_or_after_capture_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock_path, symbols_path, acceptance_path, _ = _clock(tmp_path)
    market_path = _market_db(tmp_path)
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY", "test-key")
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_ID", "controlled-store:test")
    for label, observed in (
        ("before", datetime(2026, 8, 17, 8, 59, tzinfo=TAIPEI)),
        ("after", datetime(2026, 8, 17, 14, 0, tzinfo=TAIPEI)),
    ):
        development_root = tmp_path / label / "technical_analysis_development_output"
        output_root = tmp_path / label / "candidate-output"
        development_root.mkdir(parents=True)
        output_root.mkdir(parents=True)
        clock = load_clock_manifest_for_capture(clock_path, now=observed)
        with pytest.raises(
            FormalDailyInputProducerError,
            match="Rule capture is outside Taiwan regular session",
        ):
            _produce_rule_candidate(
                paths=DailyFormalInputPaths(
                    output_root=output_root,
                    development_output_root=development_root,
                    market_db=market_path,
                    clock_manifest=clock_path,
                    universe_symbols=symbols_path,
                    owner_acceptance=acceptance_path,
                ),
                output_root=output_root,
                clock=clock,
                now=observed,
            )


def test_rule_publication_recovers_when_receipt_write_fails_after_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """manifest 已固定但 receipt 中斷時，retry 只能補寫同一 run。"""

    clock_path, symbols_path, acceptance_path, _ = _clock(tmp_path)
    market_path = _market_db(tmp_path)
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY", "test-key")
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_ID", "controlled-store:test")
    observed = datetime(2026, 8, 19, 9, 5, tzinfo=TAIPEI)
    clock = load_clock_manifest_for_capture(clock_path, now=observed)
    publication_root = tmp_path / "persistent-output"
    development_root = tmp_path / "technical_analysis_development_output"
    output_root = tmp_path / "candidate-output"
    development_root.mkdir()
    output_root.mkdir()
    paths = DailyFormalInputPaths(
        output_root=output_root,
        development_output_root=development_root,
        market_db=market_path,
        clock_manifest=clock_path,
        universe_symbols=symbols_path,
        owner_acceptance=acceptance_path,
        publication_root=publication_root,
    )
    original_writer = formal_daily_input_producer_module._write_input_receipt
    failure = {"raised": False}
    durable_receipt = publication_root / "rule_history" / "2026-08-19" / "receipt.json"

    def fail_durable_receipt_once(
        *,
        output_path: Path,
        input_name: str,
        result: dict[str, object],
        observed: datetime,
    ) -> tuple[Path, str, str]:
        if output_path.resolve() == durable_receipt.resolve() and not failure["raised"]:
            failure["raised"] = True
            raise OSError("simulated receipt sink failure")
        return original_writer(
            output_path=output_path,
            input_name=input_name,
            result=result,
            observed=observed,
        )

    monkeypatch.setattr(
        formal_daily_input_producer_module,
        "_write_input_receipt",
        fail_durable_receipt_once,
    )
    with pytest.raises(OSError, match="simulated receipt sink failure"):
        _produce_rule_candidate(
            paths=paths,
            output_root=output_root,
            clock=clock,
            now=observed,
            publication_root=publication_root,
        )
    run_dir = publication_root / "rule_history" / "2026-08-19"
    assert (run_dir / "manifest.json").is_file()
    assert (run_dir / "publication_context.json").is_file()
    assert not durable_receipt.exists()
    shutil.rmtree(development_root)
    shutil.rmtree(output_root)

    monkeypatch.setattr(
        formal_daily_input_producer_module,
        "_write_input_receipt",
        original_writer,
    )
    recovered = _produce_rule_candidate(
        paths=paths,
        output_root=output_root,
        clock=clock,
        now=observed,
        publication_root=publication_root,
    )
    assert recovered["publication_status"] == "recovered_after_receipt_failure"
    assert recovered["idempotent_retry"] is True
    assert durable_receipt.is_file()


def test_causal_ledger_publication_is_durable_retryable_and_source_independent(
    tmp_path: Path,
) -> None:
    clock_path, _, _, _ = _clock(tmp_path)
    snapshots_path, fills_path = _paper_sources(tmp_path)
    publication_root = tmp_path / "persistent-output"
    first_paths = _candidate_paths(
        tmp_path / "first",
        clock_path=clock_path,
        snapshots_path=snapshots_path,
        fills_path=fills_path,
        publication_root=publication_root,
    )
    first_paths.output_root.mkdir(parents=True)
    first = _produce_formal_ledger_candidate(
        paths=first_paths,
        output_root=first_paths.output_root,
        observed=datetime(2026, 8, 19, 9, 5, tzinfo=TAIPEI),
        calendar=_AdjacentTradingCalendar(tmp_path / "unused.sqlite"),
        publication_root=publication_root,
    )
    run_dir = publication_root / "causal_ledger" / str(first["publication_run_id"])
    manifest_path = Path(str(first["manifest_path"]))
    receipt_path = Path(str(first["publication_receipt_path"]))
    assert first["publication_status"] == "published"
    assert manifest_path == run_dir / "manifest.json"
    assert receipt_path == run_dir / "receipt.json"
    assert (run_dir / "snapshot_source_custody.json").is_file()
    assert (run_dir / "fill_source_custody.json").is_file()
    manifest_bytes = manifest_path.read_bytes()
    sqlite_bytes = Path(str(first["sqlite_path"])).read_bytes()
    receipt_bytes = receipt_path.read_bytes()

    # durable custody must make a retry independent of the TEMP source files.
    gc.collect()
    snapshots_path.unlink()
    fills_path.unlink()
    second_paths = _candidate_paths(
        tmp_path / "second",
        clock_path=clock_path,
        snapshots_path=snapshots_path,
        fills_path=fills_path,
        publication_root=publication_root,
    )
    second_paths.output_root.mkdir(parents=True)
    second = _produce_formal_ledger_candidate(
        paths=second_paths,
        output_root=second_paths.output_root,
        observed=datetime(2026, 8, 19, 9, 5, tzinfo=TAIPEI),
        calendar=_AdjacentTradingCalendar(tmp_path / "unused.sqlite"),
        publication_root=publication_root,
    )
    assert second["publication_status"] == "idempotent_retry"
    assert second["idempotent_retry"] is True
    assert second["manifest_hash"] == first["manifest_hash"]
    assert manifest_path.read_bytes() == manifest_bytes
    assert Path(str(first["sqlite_path"])).read_bytes() == sqlite_bytes
    assert receipt_path.read_bytes() == receipt_bytes


def test_causal_ledger_publication_recovers_after_receipt_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock_path, _, _, _ = _clock(tmp_path)
    snapshots_path, fills_path = _paper_sources(tmp_path)
    publication_root = tmp_path / "persistent-output"
    paths = _candidate_paths(
        tmp_path,
        clock_path=clock_path,
        snapshots_path=snapshots_path,
        fills_path=fills_path,
        publication_root=publication_root,
    )
    paths.output_root.mkdir(parents=True)
    original_writer = formal_daily_input_producer_module._write_input_receipt
    failure = {"raised": False}

    def fail_durable_receipt_once(
        *,
        output_path: Path,
        input_name: str,
        result: dict[str, object],
        observed: datetime,
    ) -> tuple[Path, str, str]:
        if (
            output_path.parent.parent.parent == publication_root
            and output_path.name == "receipt.json"
            and not failure["raised"]
        ):
            failure["raised"] = True
            raise OSError("simulated ledger receipt sink failure")
        return original_writer(
            output_path=output_path,
            input_name=input_name,
            result=result,
            observed=observed,
        )

    monkeypatch.setattr(
        formal_daily_input_producer_module,
        "_write_input_receipt",
        fail_durable_receipt_once,
    )
    observed = datetime(2026, 8, 19, 9, 5, tzinfo=TAIPEI)
    with pytest.raises(OSError, match="simulated ledger receipt sink failure"):
        _produce_formal_ledger_candidate(
            paths=paths,
            output_root=paths.output_root,
            observed=observed,
            calendar=_AdjacentTradingCalendar(tmp_path / "unused.sqlite"),
            publication_root=publication_root,
        )
    run_dirs = list((publication_root / "causal_ledger").iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert (run_dir / "manifest.json").is_file()
    assert (run_dir / "publication_context.json").is_file()
    assert not (run_dir / "receipt.json").exists()

    monkeypatch.setattr(
        formal_daily_input_producer_module,
        "_write_input_receipt",
        original_writer,
    )
    recovered = _produce_formal_ledger_candidate(
        paths=paths,
        output_root=paths.output_root,
        observed=observed,
        calendar=_AdjacentTradingCalendar(tmp_path / "unused.sqlite"),
        publication_root=publication_root,
    )
    assert recovered["publication_status"] == "recovered_after_receipt_failure"
    assert recovered["idempotent_retry"] is True
    assert (run_dir / "receipt.json").is_file()


def test_public_daily_run_publishes_ledger_and_keeps_partial_failure_machine_visible(
    tmp_path: Path,
) -> None:
    """一項來源失敗時其餘 producer 可續跑，但不偽造三項完成。"""

    clock_path, _, _, _ = _clock(tmp_path)
    snapshots_path, fills_path = _paper_sources(tmp_path)
    output_root = tmp_path / "public-output"
    publication_root = tmp_path / "persistent-output"
    paths = DailyFormalInputPaths(
        output_root=output_root,
        development_output_root=tmp_path / "technical_analysis_development_output",
        market_db=tmp_path / "unavailable-market.sqlite",
        clock_manifest=clock_path,
        paper_snapshot_db_path=snapshots_path,
        paper_trade_ledger_db_path=fills_path,
        publication_root=publication_root,
    )

    result = run_daily_formal_input_producer(
        paths,
        now=datetime(2026, 8, 19, 9, 5, tzinfo=TAIPEI),
        calendar=_AdjacentTradingCalendar(tmp_path / "unused.sqlite"),
        fetch_source=lambda _url: (_ for _ in ()).throw(
            RuntimeError("test PIT source unavailable")
        ),
    )

    assert result["status"] == "candidate_only"
    assert result["formal_ready_input_count"] == 0
    inputs = result["inputs"]
    assert isinstance(inputs, dict)
    assert inputs["rule_candidate"]["status"] == "blocked"
    assert inputs["pit_candidate"]["status"] == "blocked"
    ledger = inputs["formal_ledger_candidate"]
    assert ledger["publication_status"] == "published"
    assert Path(str(ledger["publication_receipt_path"])).is_file()
    assert result["formal_ready_input_count"] != 3


def test_public_daily_run_retries_durable_ledger_after_temp_sources_are_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock_path, _, _, _ = _clock(tmp_path)
    snapshots_path, fills_path = _paper_sources(tmp_path)
    publication_root = tmp_path / "persistent-output"
    observed = datetime(2026, 8, 19, 9, 5, tzinfo=TAIPEI)

    def build_paths(label: str) -> DailyFormalInputPaths:
        return DailyFormalInputPaths(
            output_root=tmp_path / label / "public-output",
            development_output_root=tmp_path / label / "technical_analysis_development_output",
            market_db=tmp_path / "unavailable-market.sqlite",
            clock_manifest=clock_path,
            paper_snapshot_db_path=snapshots_path,
            paper_trade_ledger_db_path=fills_path,
            publication_root=publication_root,
        )

    def unavailable_pit(_url: str) -> OfficialSourceResponse:
        raise RuntimeError("test PIT source unavailable")

    first = run_daily_formal_input_producer(
        build_paths("first"),
        now=observed,
        calendar=_AdjacentTradingCalendar(tmp_path / "unused.sqlite"),
        fetch_source=unavailable_pit,
    )
    first_inputs = first["inputs"]
    assert isinstance(first_inputs, dict)
    assert first_inputs["formal_ledger_candidate"]["publication_status"] == "published"
    gc.collect()
    snapshots_path.unlink()
    fills_path.unlink()

    second = run_daily_formal_input_producer(
        build_paths("second"),
        now=observed,
        calendar=_AdjacentTradingCalendar(tmp_path / "unused.sqlite"),
        fetch_source=unavailable_pit,
    )
    assert second["status"] == "candidate_only"
    assert second["formal_ready_input_count"] == 0
    preflight = second["preflight"]
    assert isinstance(preflight, dict)
    assert not any(
        "paper_snapshot_source_missing" in str(item)
        or "paper_trade_ledger_source_missing" in str(item)
        for item in preflight["blockers"]
    )
    sources = preflight["paper_sources"]
    assert isinstance(sources, dict)
    durable = sources["durable_causal_ledger"]
    assert durable["state"] == "ready"
    second_inputs = second["inputs"]
    assert isinstance(second_inputs, dict)
    assert second_inputs["formal_ledger_candidate"]["publication_status"] == "idempotent_retry"
    assert second["formal_ready_input_count"] != 3


def test_pit_candidate_uses_response_completion_and_operational_readback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY", "test-key")
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_ID", "controlled-store:test")
    raw = _pit_raw_payloads()
    captured_at = "2026-09-07T10:00:00+00:00"
    responses = {
        OFFICIAL_COMPANY_SOURCE_DEFINITIONS["twse"].endpoint: OfficialSourceResponse(
            body=raw["twse"],
            metadata={
                "requested_url": OFFICIAL_COMPANY_SOURCE_DEFINITIONS["twse"].endpoint,
                "final_url": OFFICIAL_COMPANY_SOURCE_DEFINITIONS["twse"].endpoint,
                "http_status": 200,
                "content_type": "application/json",
                "http_date": None,
                "http_last_modified": None,
                "captured_at": captured_at,
            },
        ),
        OFFICIAL_COMPANY_SOURCE_DEFINITIONS["tpex"].endpoint: OfficialSourceResponse(
            body=raw["tpex"],
            metadata={
                "requested_url": OFFICIAL_COMPANY_SOURCE_DEFINITIONS["tpex"].endpoint,
                "final_url": OFFICIAL_COMPANY_SOURCE_DEFINITIONS["tpex"].endpoint,
                "http_status": 200,
                "content_type": "application/json",
                "http_date": None,
                "http_last_modified": None,
                "captured_at": captured_at,
            },
        ),
    }
    paths = DailyFormalInputPaths(
        output_root=tmp_path / "pit-output",
        development_output_root=tmp_path / "technical_analysis_development_output",
        market_db=tmp_path / "unused-market.sqlite",
    )
    paths.output_root.mkdir()

    result = _produce_pit_candidate(
        paths=paths,
        output_root=paths.output_root,
        observed=datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc),
        expected_symbols=None,
        fetch_source=lambda url: responses[url],
    )

    assert result["consumer_verified"] is True
    assert datetime.fromisoformat(str(result["captured_at"])).astimezone(
        timezone.utc
    ) == datetime.fromisoformat(captured_at)
    assert result["effective_from"] == "2026-09-07"
    assert result["candidate_only"] is True


def test_calendar_projection_uses_local_market_indices_when_online_schedule_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_path = tmp_path / "market.sqlite"
    with sqlite3.connect(market_path) as connection:
        connection.execute("CREATE TABLE market_indices (日期 TEXT, 指數名稱 TEXT)")
        connection.execute(
            "INSERT INTO market_indices VALUES ('20260907', 'TAIEX')"
        )
    calendar = OfficialTradingCalendar(market_path)
    monkeypatch.setattr(
        "data_module.official_trading_calendar.safe_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    projection, blockers = _calendar_projection(
        market_path,
        target_date=date(2026, 9, 7),
        calendar=calendar,
    )

    assert blockers == []
    assert projection["is_trading_day"] is True
    assert projection["reason_code"] == "twstock_db_market_indices_evidence"
    assert projection["online_probe_reason_code"] == "twse_holiday_schedule_unavailable"
    assert projection["fallback_evidence"] == {
        "is_trading_day": True,
        "reason_code": "twstock_db_market_indices_evidence",
        "mode": "read_only_market_indices_date_evidence",
    }


def test_pit_candidate_rejects_future_response_completion_instead_of_rebasing_now(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY", "test-key")
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_ID", "controlled-store:test")
    raw = _pit_raw_payloads()
    future = "2099-09-07T10:00:00+00:00"
    responses = {
        OFFICIAL_COMPANY_SOURCE_DEFINITIONS[market].endpoint: OfficialSourceResponse(
            body=raw[market],
            metadata={
                "requested_url": OFFICIAL_COMPANY_SOURCE_DEFINITIONS[market].endpoint,
                "final_url": OFFICIAL_COMPANY_SOURCE_DEFINITIONS[market].endpoint,
                "http_status": 200,
                "content_type": "application/json",
                "http_date": None,
                "http_last_modified": None,
                "captured_at": future,
            },
        )
        for market in ("twse", "tpex")
    }
    paths = DailyFormalInputPaths(
        output_root=tmp_path / "pit-output",
        development_output_root=tmp_path / "technical_analysis_development_output",
        market_db=tmp_path / "unused-market.sqlite",
    )
    paths.output_root.mkdir()

    with pytest.raises(
        FormalDailyInputProducerError,
        match="captured_at cannot be after current wall clock",
    ):
        _produce_pit_candidate(
            paths=paths,
            output_root=paths.output_root,
            observed=datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc),
            expected_symbols=None,
            fetch_source=lambda url: responses[url],
        )
