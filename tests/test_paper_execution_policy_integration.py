from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

import pytest

import data_module.paper_daily_execution_producer as producer
from app_module.paper_portfolio_policy import PaperPortfolioPolicyConfig
from app_module.paper_trade_ledger import PaperTradeFill, PaperTradeLedgerRepository
from data_module.paper_daily_execution_producer import (
    PAPER_EXECUTION_SOURCE_TYPE,
    PaperExecutionPaths,
    run_paper_execution_daily,
)
from data_module.portfolio_ml_dataset_assembler import (
    SECTOR_MEMBERSHIP_MANIFEST_SCHEMA_VERSION,
    SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION,
)
from app_module.paper_portfolio_snapshot_repository import (
    PaperPortfolioPositionSnapshot,
    PaperPortfolioSnapshot,
    PaperPortfolioSnapshotRepository,
)


TAIPEI = ZoneInfo("Asia/Taipei")
DECISION_DATE = date(2026, 9, 4)
EXECUTION_DATE = date(2026, 9, 7)
NOW = datetime(2026, 9, 7, 15, 0, tzinfo=TAIPEI)


class _Calendar:
    def is_official_trading_day(
        self,
        target_date: date,
        allow_online_probe: bool = True,
    ) -> tuple[bool, str]:
        del allow_online_probe
        if target_date in {DECISION_DATE, EXECUTION_DATE}:
            return True, "test_official_open"
        return False, "test_official_closed"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _write_sector_sidecar(
    path: Path,
    symbols: Sequence[str],
    *,
    sectors: Mapping[str, str] | None = None,
    available_at: str = "2026-01-01T00:00:00+00:00",
) -> str:
    sector_values = sectors or {symbol: "SEMICONDUCTOR" for symbol in symbols}
    rows = [
        {
            "symbol": symbol,
            "sector_id": sector_values[symbol],
            "available_at": available_at,
            "effective_from": "2026-01-01",
            "effective_to": None,
            "status": "accepted",
            "source_id": "official:twse:t187ap03_L",
            "license_id": "twse-open-data-license-v1",
            "source_hash": _sha256(f"source:{symbol}".encode("utf-8")),
        }
        for symbol in sorted(symbols)
    ]
    manifest_body = {
        "schema_version": SECTOR_MEMBERSHIP_MANIFEST_SCHEMA_VERSION,
        "row_count": len(rows),
        "rows_hash": _sha256(_canonical(rows)),
    }
    manifest = {
        **manifest_body,
        "canonical_hash": _sha256(
            _canonical(
                {
                    "sidecar_schema_version": SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION,
                    "manifest": manifest_body,
                }
            )
        ),
    }
    payload = {
        "schema_version": SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION,
        "manifest": manifest,
        "rows": rows,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(payload) + b"\n")
    return _sha256(path.read_bytes())


def _write_recommendation(path: Path, symbol: str = "2330", *, created_at: str = "2026-09-04T20:00:00+08:00") -> None:
    payload = {
        "result_id": "integration-recommendation-20260904",
        "created_at": created_at,
        "config": {
            "research_only": True,
            "decision_date": "2026-09-04",
            "top_n": 8,
            "profile_id": "integration-policy-v1",
            "safety_boundary": {
                "confirm": False,
                "writes_evidence_db": False,
                "auto_trading": False,
                "lifecycle_action": False,
            },
        },
        "recommendations": [
            {
                "證券代號": symbol,
                "證券名稱": f"測試{symbol}",
                "總分": "100.00",
                "收盤價": "10.00",
                "產業": "display-only-untrusted",
                "eligible_universe_date": "2026-09-04",
            }
        ],
    }
    path.write_bytes(_canonical(payload) + b"\n")


def _write_market(
    path: Path,
    symbols: Sequence[str],
    *,
    reference_volumes: Mapping[str, int] | None = None,
    execution_volumes: Mapping[str, int] | None = None,
) -> None:
    reference = reference_volumes or {symbol: 100_000 for symbol in symbols}
    execution = execution_volumes or {symbol: 100_000 for symbol in symbols}
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE daily_prices ("
            "日期 TEXT, 證券代號 TEXT, 證券名稱 TEXT, "
            "開盤價 TEXT, 收盤價 TEXT, 成交股數 INTEGER)"
        )
        rows = []
        for symbol in sorted(symbols):
            rows.extend(
                [
                    ("20260904", symbol, f"測試{symbol}", "9.80", "10.00", reference[symbol]),
                    ("20260907", symbol, f"測試{symbol}", "10.20", "10.50", execution[symbol]),
                ]
            )
        connection.executemany("INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?)", rows)
        connection.execute("CREATE TABLE market_indices (日期 TEXT, 指數名稱 TEXT)")
        connection.executemany(
            "INSERT INTO market_indices VALUES (?, ?)",
            (("20260904", "TAIEX"), ("20260907", "TAIEX")),
        )


def _write_state(
    path: Path,
    positions: Sequence[tuple[str, int, str]],
    *,
    cash: str,
    total_value: str = "100000.00",
) -> None:
    snapshot_positions = tuple(
        PaperPortfolioPositionSnapshot(
            stock_code=symbol,
            quantity=quantity,
            mark_price=Decimal(mark_price),
            market_value=Decimal(mark_price) * quantity,
            weight_bp=int(
                (Decimal(mark_price) * quantity * Decimal("10000") / Decimal(total_value))
                .to_integral_value()
            ),
        )
        for symbol, quantity, mark_price in positions
    )
    PaperPortfolioSnapshotRepository(path).append(
        PaperPortfolioSnapshot(
            snapshot_id="integration-snapshot-20260904",
            portfolio_id="paper-main",
            decision_date="2026-09-04",
            source_result_id="integration-state",
            cash=Decimal(cash),
            total_value=Decimal(total_value),
            positions=snapshot_positions,
        )
    )


def _make_fill(
    path: Path,
    *,
    symbol: str = "2330",
    event_date: str = "2026-09-04",
    side: str = "buy",
    quantity: int = 1000,
    turnover_bp: int = 1500,
) -> None:
    PaperTradeLedgerRepository(path).append(
        PaperTradeFill(
            fill_id="historical-fill-1",
            order_id="historical-order-1",
            portfolio_id="paper-main",
            event_date=event_date,
            stock_code=symbol,
            side=side,
            requested_quantity=quantity,
            filled_quantity=quantity,
            reference_price=Decimal("10.00"),
            fill_price=Decimal("10.20"),
            commission=Decimal("0.00"),
            tax=Decimal("0.00"),
            slippage_cost=Decimal("0.20") * quantity,
            turnover_bp=turnover_bp,
            execution_gap_bp=200,
            status="filled",
            source_event_id="historical-fill-1",
            source_type=PAPER_EXECUTION_SOURCE_TYPE,
        )
    )


def _paths(
    tmp_path: Path,
    *,
    recommendation_symbol: str = "2330",
    sector_symbols: Sequence[str] = ("2330",),
    positions: Sequence[tuple[str, int, str]] = (),
    cash: str = "100000.00",
    reference_volumes: Mapping[str, int] | None = None,
    execution_volumes: Mapping[str, int] | None = None,
    sectors: Mapping[str, str] | None = None,
) -> PaperExecutionPaths:
    recommendation = tmp_path / "recommendation.json"
    _write_recommendation(recommendation, recommendation_symbol)
    state = tmp_path / "state.sqlite"
    _write_state(state, positions, cash=cash)
    market = tmp_path / "market.sqlite"
    all_symbols = tuple(sorted(set(sector_symbols) | {symbol for symbol, _, _ in positions}))
    _write_market(
        market,
        all_symbols,
        reference_volumes=reference_volumes,
        execution_volumes=execution_volumes,
    )
    ledger = tmp_path / "ledger.sqlite"
    PaperTradeLedgerRepository(ledger)
    sector = tmp_path / "sector.json"
    sector_hash = _write_sector_sidecar(sector, all_symbols, sectors=sectors)
    return PaperExecutionPaths(
        recommendation_json=recommendation,
        state_db=state,
        market_db=market,
        output_root=tmp_path / "candidate",
        ledger_db=ledger,
        sector_membership_path=sector,
        sector_membership_file_hash=sector_hash,
    )


def _run(paths: PaperExecutionPaths) -> dict[str, object]:
    result = run_paper_execution_daily(
        paths,
        now=NOW,
        calendar=_Calendar(),
    )
    assert isinstance(result, dict)
    return result


def _adapter_results(result: Mapping[str, object]) -> list[Mapping[str, object]]:
    target_policy = result["target_policy"]
    assert isinstance(target_policy, Mapping)
    adapter = target_policy["adapter"]
    assert isinstance(adapter, Mapping)
    rows = adapter["results"]
    assert isinstance(rows, list)
    return [row for row in rows if isinstance(row, Mapping)]


def test_true_producer_caller_enforces_batch_policy_and_records_sources(tmp_path: Path) -> None:
    result = _run(_paths(tmp_path))

    assert result["status"] == "machine_verified_candidate"
    target_policy = result["target_policy"]
    assert isinstance(target_policy, Mapping)
    adapter = target_policy["adapter"]
    assert isinstance(adapter, Mapping)
    assert adapter["enforced"] is True
    assert adapter["consumer"].endswith("PaperPortfolioPolicyAdapter.evaluate_batch")
    assert adapter["sector_source"]["mode"] == "official_pit_sector_sidecar_ro_hash_bound"
    assert adapter["calendar_source"]["complete"] is True
    assert target_policy["policy"]["cooldown_policy"] == (
        "enforced_by_paper_portfolio_policy_adapter"
    )


def test_true_caller_weekly_turnover_gate_blocks_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_config = PaperPortfolioPolicyConfig
    monkeypatch.setattr(
        producer,
        "PaperPortfolioPolicyConfig",
        lambda: original_config(same_symbol_cooldown_trading_days=0),
    )
    paths = _paths(tmp_path, positions=(("2330", 1000, "10.00"),), cash="90000.00")
    assert paths.ledger_db is not None
    _make_fill(
        paths.ledger_db,
        event_date="2026-09-07",
        turnover_bp=1800,
    )

    result = _run(paths)

    rows = _adapter_results(result)
    assert rows and rows[0]["action"] == "NO_PAPER_TRADE"
    assert rows[0]["reasons"] == ["weekly_turnover_cap_exceeded"]
    assert result["fill_count"] == 0
    assert result["status"] == "no_trade_required_candidate"


def test_true_caller_cooldown_gate_uses_official_days_and_blocks_target(tmp_path: Path) -> None:
    paths = _paths(tmp_path, positions=(("2330", 1000, "10.00"),), cash="90000.00")
    assert paths.ledger_db is not None
    _make_fill(
        paths.ledger_db,
        event_date="2026-09-07",
        turnover_bp=100,
    )

    result = _run(paths)

    rows = _adapter_results(result)
    assert rows and rows[0]["reasons"] == ["same_symbol_cooldown_active"]
    assert result["fill_count"] == 0
    adapter = result["target_policy"]["adapter"]
    assert adapter["context"]["official_trading_days"] == [
        "2026-09-04",
        "2026-09-07",
    ]


def test_true_caller_sector_gate_uses_pit_mapping_not_display_industry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_config = PaperPortfolioPolicyConfig
    monkeypatch.setattr(
        producer,
        "PaperPortfolioPolicyConfig",
        lambda: original_config(weekly_turnover_cap_bp=10_000),
    )
    paths = _paths(
        tmp_path,
        recommendation_symbol="2317",
        sector_symbols=("2317", "2330"),
        positions=(("2330", 2000, "10.00"),),
        cash="80000.00",
        sectors={"2317": "SEMICONDUCTOR", "2330": "SEMICONDUCTOR"},
    )

    result = _run(paths)

    rows = _adapter_results(result)
    by_symbol = {str(row["stock_code"]): row for row in rows}
    assert by_symbol["2317"]["reasons"] == ["sector_cap_exceeded"]
    # The existing holding can still be proposed for a corrective sell; the
    # blocked new position must never be emitted as a buy.
    assert result["fill_count"] == 1
    assert result["fills"][0]["stock_code"] == "2330"
    assert result["fills"][0]["side"] == "sell"


def test_rejected_sell_does_not_release_cash_or_sector_for_later_buy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_config = PaperPortfolioPolicyConfig
    monkeypatch.setattr(
        producer,
        "PaperPortfolioPolicyConfig",
        lambda: original_config(
            max_sector_weight_bp=6000,
            weekly_turnover_cap_bp=10_000,
        ),
    )
    paths = _paths(
        tmp_path,
        recommendation_symbol="1101",
        sector_symbols=("1101", "2317", "2330"),
        positions=(("2330", 2000, "10.00"), ("2317", 5000, "10.00")),
        cash="30000.00",
        reference_volumes={"1101": 100000, "2317": 100000, "2330": 1000},
        sectors={"1101": "HEALTH", "2317": "FINANCE", "2330": "TECH"},
    )

    result = _run(paths)

    fills = result["fills"]
    assert isinstance(fills, list)
    assert [fill["stock_code"] for fill in fills] == ["2317", "2330"]
    assert fills[0]["status"] == "filled"
    assert fills[1]["status"] == "rejected"
    assert fills[1]["filled_quantity"] == 0
    projection = result["post_execution_projection"]
    assert isinstance(projection, Mapping)
    # Only the actually filled 2317 sell changes cash; the rejected 2330 sell
    # contributes no proceeds and does not make 1101 buyable.
    assert projection["cash_after"] == "80521.62"
    assert result["target_policy"]["adapter"]["target_quantities_after_policy"]["1101"] == 0
    post_policy = result["target_policy"]["post_fill_reconciliation"]
    assert post_policy["cash_reservation_semantics"] == (
        "sell_proceeds_count_only_after_actual_fill_settlement"
    )
    assert post_policy["sector_reservation_semantics"] == (
        "sell_exposure_count_only_after_actual_fill_readback"
    )


def test_same_day_ledger_fill_is_projected_without_duplicate_execution(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    assert paths.ledger_db is not None
    _make_fill(paths.ledger_db, event_date="2026-09-07", turnover_bp=1900)

    result = _run(paths)

    assert result["status"] == "no_trade_required_candidate"
    adapter = result["target_policy"]["adapter"]
    assert adapter["context"]["current_weights_bp"]["2330"] == 1020
    assert adapter["ledger_state"]["weekly_turnover_used_bp"] == 1900
    assert adapter["ledger_state"]["future_rows_excluded"] == 0
    assert result["fill_count"] == 0


def test_missing_or_late_sector_source_fails_closed(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    missing = PaperExecutionPaths(**{**paths.__dict__, "sector_membership_path": None, "sector_membership_file_hash": None})
    result = _run(missing)
    assert result["status"] == "blocked"
    assert "sector mapping source is missing" in result["blockers"][0]

    late_path = tmp_path / "late-sector.json"
    late_hash = _write_sector_sidecar(
        late_path,
        ("2330",),
        available_at="2026-09-07T08:31:00+08:00",
    )
    late = PaperExecutionPaths(
        **{
            **paths.__dict__,
            "output_root": tmp_path / "late-candidate",
            "sector_membership_path": late_path,
            "sector_membership_file_hash": late_hash,
        }
    )
    result_late = _run(late)
    assert result_late["status"] == "blocked"
    assert "sector mapping missing as-of recommendation freeze" in result_late["blockers"][0]


def test_archive_manifest_sector_source_uses_durable_custody_consumer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_root = tmp_path / "pit_candidate_archive"
    manifest = archive_root / "2026-09-07" / "capture-1" / "archive_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(b"{}\n")
    expected_hash = producer._file_sha256(manifest)
    calls: dict[str, object] = {}

    def fake_consume(**kwargs: object) -> dict[str, object]:
        calls.update(kwargs)
        return {
            "publication_content_hash": "sha256:" + "b" * 64,
            "archive_manifest_hash": "sha256:" + "c" * 64,
            "archive_id": "pit-candidate:test",
            "captured_at": "2026-09-07T08:30:00+08:00",
            "available_at": "2026-09-07T08:31:00+08:00",
            "archived_at": "2026-09-07T08:32:00+08:00",
            "source_custody_verified": True,
            "rows_rebuilt_from_raw": True,
            "rows": [
                {
                    "symbol": "2330",
                    "sector_id": "SEMICONDUCTOR",
                    "available_at": "2026-09-07T08:30:00+08:00",
                    "effective_from": "2026-09-07",
                    "effective_to": None,
                    "status": "accepted",
                    "source_id": "official:twse:t187ap03_L",
                }
            ],
        }

    import ml_module.pit_archive_consumer as archive_consumer

    monkeypatch.setattr(
        archive_consumer,
        "consume_pit_candidate_archive",
        fake_consume,
    )
    mapping, source = producer._load_policy_sector_mapping(
        manifest,
        expected_file_hash=expected_hash,
        as_of=datetime(2026, 9, 7, 20, 0, tzinfo=TAIPEI),
        decision_date=EXECUTION_DATE,
        symbols=("2330",),
    )

    assert mapping == {"2330": "SEMICONDUCTOR"}
    assert source["mode"] == "official_pit_archive_manifest_ro_hash_bound"
    assert source["archive_consumer"].endswith("consume_pit_candidate_archive")
    assert calls["archive_root"] == archive_root.resolve()
    assert calls["manifest_path"] == manifest.resolve()
    assert calls["expected_manifest_file_hash"] == expected_hash


def test_explicit_append_and_retry_keep_policy_readback_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_config = PaperPortfolioPolicyConfig
    monkeypatch.setattr(
        producer,
        "PaperPortfolioPolicyConfig",
        lambda: original_config(weekly_turnover_cap_bp=10_000),
    )
    paths = _paths(
        tmp_path,
        positions=(("2330", 3000, "10.00"),),
        cash="70000.00",
        reference_volumes={"2330": 30_000},
    )
    first = run_paper_execution_daily(
        paths,
        now=NOW,
        calendar=_Calendar(),
        confirm_append=True,
    )
    assert first["status"] == "machine_verified_candidate"
    assert first["fills"][0]["status"] == "partially_filled"
    assert first["ledger"]["readback_verified"] is True
    assert first["target_policy"]["post_fill_reconciliation"]["execution_readback_verified"] is True
    retry = run_paper_execution_daily(
        PaperExecutionPaths(
            **{**paths.__dict__, "output_root": tmp_path / "retry-candidate"}
        ),
        now=NOW,
        calendar=_Calendar(),
        confirm_append=True,
    )
    assert retry["status"] == "machine_verified_candidate"
    assert retry["ledger"]["idempotent_replay"] is True
    assert retry["target_policy"]["post_fill_reconciliation"]["ledger_readback"]["status"] == "ready"
