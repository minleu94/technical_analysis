from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from app_module import ml_allocation_shadow_evidence as evidence_module
from app_module.ml_allocation_shadow_evidence import (
    MLAllocationShadowCollector,
    SHADOW_ALPHA_LANES_BP,
    ShadowEvidenceRepository,
    SQLiteTMinusOneMarketReader,
    calibration_metrics,
    deterministic_blend_weights,
    deterministic_block_bootstrap_lower_95_bp,
    fixed_weight_path_metrics,
    load_t_minus_one_paper_ledger,
)
from ml_module.allocation_promotion_reference import PROMOTION_HORIZONS
from app_module.paper_portfolio_snapshot_repository import (
    PaperPortfolioSnapshot,
    PaperPortfolioSnapshotRepository,
)
from app_module.portfolio_allocation_dtos import (
    AllocationWeightContract,
    MLAllocationProposal,
    MLAllocationSignalRow,
)


def _hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _make_market_db(path: Path) -> tuple[date, date]:
    decision_date = date(2026, 2, 2)
    strict_t_minus_one = decision_date - timedelta(days=1)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE daily_prices (
                "日期" TEXT NOT NULL,
                "證券代號" TEXT NOT NULL,
                "證券名稱" TEXT,
                "成交股數" INTEGER,
                "開盤價" TEXT,
                "收盤價" TEXT,
                PRIMARY KEY ("日期", "證券代號")
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE market_indices (
                "日期" TEXT NOT NULL,
                "指數名稱" TEXT NOT NULL,
                "開盤價" TEXT,
                "收盤價" TEXT,
                PRIMARY KEY ("日期", "指數名稱")
            )
            """
        )
        start = strict_t_minus_one - timedelta(days=19)
        prior_rows = [
            (
                (start + timedelta(days=index)).strftime("%Y%m%d"),
                "2330",
                "台積電",
                1_000_000 + index,
                str(Decimal("99") + Decimal(index)),
                str(Decimal("100") + Decimal(index)),
            )
            for index in range(20)
        ]
        future_rows = [
            (
                (decision_date + timedelta(days=index)).strftime("%Y%m%d"),
                "2330",
                "台積電",
                1_100_000 + index,
                str(Decimal("120") + Decimal(index)),
                str(Decimal("121") + Decimal(index)),
            )
            for index in range(60)
        ]
        connection.executemany(
            "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?)",
            [*prior_rows, *future_rows],
        )
        connection.executemany(
            "INSERT INTO market_indices VALUES (?, ?, ?, ?)",
            [
                (
                    (decision_date + timedelta(days=index)).strftime("%Y%m%d"),
                    "TAIEX",
                    str(Decimal("1000") + Decimal(index)),
                    str(Decimal("1001") + Decimal(index)),
                )
                for index in range(60)
            ],
        )
    return decision_date, strict_t_minus_one


def _make_official_event_pointer(root: Path) -> Path:
    publication_root = root / "official_market_events"
    run_root = publication_root / "runs" / "fixture-publication"
    canonical_path = run_root / "canonical" / "events.jsonl"
    canonical_path.parent.mkdir(parents=True)
    canonical_path.write_text("", encoding="utf-8")
    canonical_hash = (
        "sha256:" + hashlib.sha256(canonical_path.read_bytes()).hexdigest()
    )
    source_registry = {
        "schema_version": "official-market-event-sources.v1",
        "sources": [
            {
                "source_id": "fixture.official.events",
                "source_version": "fixture-v1",
                "venue": "TWSE",
                "endpoint_url": "https://example.invalid/official",
                "license_url": "https://example.invalid/license",
                "parser_id": "fixture-v1",
                "request_mode": "fixture",
                "result_only": False,
                "allowed_uses": [
                    "formal_label",
                    "formal_trading_restriction_timeline",
                ],
            }
        ],
    }
    manifest_body = {
        "schema_version": "official-market-event-publication.v1",
        "status": "formal_source_publication",
        "publication_id": "fixture-publication",
        "coverage": [
            {
                "source_id": "fixture.official.events",
                "complete_year_coverage": True,
                "requested_start_year": 2026,
                "requested_end_year": 2026,
            }
        ],
        "canonical_events": {
            "schema_version": "official-market-event.v1",
            "path": "canonical/events.jsonl",
            "file_hash": canonical_hash,
            "event_count": 0,
        },
        "source_registry": source_registry,
        "safety": {
            "active_sqlite_written": False,
            "all_official_revision_vintages_preserved": True,
            "append_only_canonical_events": True,
            "available_at_effective_at_separated": True,
            "formal_source_publication": True,
            "result_tables_label_ledger_only": True,
            "unlinked_revision_fails_closed": True,
        },
    }
    manifest_hash = _hash(manifest_body)
    manifest = {**manifest_body, "manifest_hash": manifest_hash}
    manifest_path = run_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    manifest_file_hash = (
        "sha256:" + hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    )
    pointer_path = publication_root / "latest_manifest.json"
    pointer_path.write_text(
        json.dumps(
            {
                "schema_version": "official-market-event-latest.v1",
                "publication_id": "fixture-publication",
                "manifest_path": "runs/fixture-publication/manifest.json",
                "manifest_hash": manifest_hash,
                "manifest_file_hash": manifest_file_hash,
                "canonical_events_hash": canonical_hash,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return pointer_path


def _make_paper_db(path: Path, *, snapshot_date: date) -> None:
    PaperPortfolioSnapshotRepository(path).append(
        PaperPortfolioSnapshot(
            snapshot_id="paper-main-baseline",
            portfolio_id="paper-main",
            decision_date=snapshot_date.isoformat(),
            source_result_id="baseline",
            cash=Decimal("10000"),
            total_value=Decimal("10000"),
            positions=(),
        )
    )


def _write_proposal(path: Path, *, decision_date: date) -> tuple[str, str]:
    signal = MLAllocationSignalRow(
        stock_code="2330",
        expected_excess_return_bp=100,
        downside_probability_bp=4000,
        predicted_mae_bp=300,
        rank_bp=9000,
        confidence_bp=8000,
        coverage_bp=10000,
        feature_manifest_hash=f"sha256:{'1' * 64}",
        expected_sector_excess_return_bp=None,
        predicted_mfe_bp=500,
        predicted_realized_volatility_bp=200,
        predicted_max_drawdown_bp=400,
        predicted_tail_loss_bp=350,
        fill_feasibility_probability_bp=9900,
        missing_head_ids=("expected_sector_excess_return_bp",),
    )
    proposal = MLAllocationProposal(
        decision_date=decision_date.isoformat(),
        model_id="test-model",
        dataset_id="test-dataset",
        universe_id="test-universe",
        policy_id="test-policy",
        requested_weights=AllocationWeightContract(
            symbol_weights_bp={"2330": 1500},
            cash_weight_bp=8500,
        ),
        model_hash=f"sha256:{'2' * 64}",
        dataset_identity_hash=f"sha256:{'3' * 64}",
        dataset_manifest_file_hash=f"sha256:{'4' * 64}",
        universe_hash=f"sha256:{'5' * 64}",
        policy_hash=f"sha256:{'6' * 64}",
        coverage_bp=10000,
        feature_family_weights_bp={"price_liquidity_technical": 10000},
        signals=(signal,),
    )
    body = proposal.to_dict()
    proposal_hash = _hash(body)
    replay_hash = f"sha256:{'7' * 64}"
    path.write_text(
        json.dumps(
            {
                "status": "inference_completed",
                "proposal": body,
                "proposal_hash": proposal_hash,
                "replay_hash": replay_hash,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return proposal_hash, replay_hash


def _append_minimal_observation(
    sidecar_path: Path,
    *,
    decision_date: date,
    symbols: tuple[str, ...],
) -> dict[str, object]:
    record, _ = ShadowEvidenceRepository(sidecar_path).append_observation(
        decision_date=decision_date.isoformat(),
        custody_hash=_hash(
            {
                "decision_date": decision_date.isoformat(),
                "symbols": list(symbols),
            }
        ),
        payload={
            # 這個 helper 用於 outcome/calendar 單元測試；它刻意代表已由
            # 測試 fixture 提供正式 Rule/context custody 的 observation。
            "promotion_day_credit_allowed": True,
            "promotion_day_credit_blockers": [],
            "proposal": {
                "coverage_bp": 10_000,
                "signals": [
                    {"stock_code": symbol}
                    for symbol in symbols
                ],
            },
            "future_prefix_violation_count": 0,
            "pit_violation_count": 0,
            "constraint_violation_count": 0,
        },
    )
    return record


def test_four_lane_blend_conserves_integer_bp_and_is_deterministic() -> None:
    rule = AllocationWeightContract(
        symbol_weights_bp={"1101": 1001, "2330": 1499},
        cash_weight_bp=7500,
    )
    ml = AllocationWeightContract(
        symbol_weights_bp={"1101": 333, "2454": 1167},
        cash_weight_bp=8500,
    )
    hashes = []
    for alpha_bp in SHADOW_ALPHA_LANES_BP:
        first = deterministic_blend_weights(
            rule_weights=rule,
            ml_weights=ml,
            alpha_bp=alpha_bp,
        )
        second = deterministic_blend_weights(
            rule_weights=rule,
            ml_weights=ml,
            alpha_bp=alpha_bp,
        )
        assert first == second
        assert (
            sum(first.symbol_weights_bp.values()) + first.cash_weight_bp
            == 10000
        )
        hashes.append(_hash(first.to_dict()))
    assert len(set(hashes)) == 4


def test_market_reader_uses_strict_t_minus_one_and_ignores_future_poison(
    tmp_path: Path,
) -> None:
    database = tmp_path / "market.sqlite"
    decision_date, strict_t_minus_one = _make_market_db(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            'UPDATE daily_prices SET "收盤價" = ? WHERE "日期" = ?',
            ("999999", decision_date.strftime("%Y%m%d")),
        )

    result = SQLiteTMinusOneMarketReader(database).read_contexts(
        symbols=("2330",),
        strict_t_minus_one=strict_t_minus_one,
    )

    assert result["2330"].price_date == strict_t_minus_one.isoformat()
    assert result["2330"].close_price == Decimal("119")
    assert result["2330"].median_volume_20d_shares == 1_000_009


def test_sidecar_is_idempotent_and_changed_custody_appends_revision(
    tmp_path: Path,
) -> None:
    repository = ShadowEvidenceRepository(tmp_path / "shadow.sqlite")
    payload = {
        "promotion_day_credit_allowed": True,
        "promotion_day_credit_blockers": [],
        "proposal": {"coverage_bp": 10000},
        "future_prefix_violation_count": 0,
        "pit_violation_count": 0,
        "constraint_violation_count": 0,
    }

    first, first_idempotent = repository.append_observation(
        decision_date="2026-02-02",
        custody_hash=f"sha256:{'1' * 64}",
        payload=payload,
    )
    replay, replay_idempotent = repository.append_observation(
        decision_date="2026-02-02",
        custody_hash=f"sha256:{'1' * 64}",
        payload=payload,
    )
    revised, revised_idempotent = repository.append_observation(
        decision_date="2026-02-02",
        custody_hash=f"sha256:{'2' * 64}",
        payload=payload,
    )

    assert first_idempotent is False
    assert replay_idempotent is True
    assert revised_idempotent is False
    assert first == replay
    assert first["revision"] == 1
    assert revised["revision"] == 2
    assert revised["previous_revision_hash"] == first["record_hash"]
    assert len(repository.observations()) == 2
    latest = repository.latest_observations()
    assert len(latest) == 1
    assert latest[0]["record_hash"] == revised["record_hash"]

    first_outcome, _ = repository.append_outcome(
        observation_hash=str(revised["record_hash"]),
        custody_hash=f"sha256:{'3' * 64}",
        payload={
            "status": "matured_all_horizons",
            "completed_horizons_trading_sessions": list(PROMOTION_HORIZONS),
            "blockers": [],
            "trading_day_count": 20,
            "feasible_fill_coverage_bp": None,
        },
    )
    revised_outcome, _ = repository.append_outcome(
        observation_hash=str(revised["record_hash"]),
        custody_hash=f"sha256:{'4' * 64}",
        payload={
            "status": "matured_all_horizons",
            "completed_horizons_trading_sessions": list(PROMOTION_HORIZONS),
            "blockers": [],
            "trading_day_count": 20,
            "feasible_fill_coverage_bp": None,
        },
    )
    latest_outcomes = repository.latest_outcomes(
        observation_hashes=(str(revised["record_hash"]),)
    )
    assert first_outcome["revision"] == 1
    assert revised_outcome["revision"] == 2
    assert len(latest_outcomes) == 1
    assert (
        latest_outcomes[0]["record_hash"]
        == revised_outcome["record_hash"]
    )
    collector = MLAllocationShadowCollector(
        market_database_path=tmp_path / "unused-market.sqlite",
        paper_state_db_path=tmp_path / "unused-paper.sqlite",
        sidecar_database_path=tmp_path / "shadow.sqlite",
        artifact_root=tmp_path / "artifacts",
    )
    summary = collector._aggregate_evidence(  # noqa: SLF001
        cutoff_date=date(2026, 3, 1)
    )
    assert summary["observation_count"] == 1
    assert summary["observation_revision_record_count"] == 2
    assert summary["matured_observation_count"] == 1
    assert summary["outcome_revision_record_count"] == 2


def test_missing_prior_paper_state_fails_closed(tmp_path: Path) -> None:
    state_db = tmp_path / "paper.sqlite"
    _make_paper_db(state_db, snapshot_date=date(2026, 2, 2))

    with pytest.raises(ValueError, match="strictly prior"):
        load_t_minus_one_paper_ledger(
            state_db_path=state_db,
            portfolio_id="paper-main",
            decision_date=date(2026, 2, 2),
        )


def test_collector_records_four_lanes_then_matures_all_four_horizons(
    tmp_path: Path,
) -> None:
    market_db = tmp_path / "market.sqlite"
    decision_date, strict_t_minus_one = _make_market_db(market_db)
    paper_db = tmp_path / "paper.sqlite"
    _make_paper_db(
        paper_db,
        snapshot_date=strict_t_minus_one - timedelta(days=1),
    )
    proposal_path = tmp_path / "proposal.json"
    proposal_hash, replay_hash = _write_proposal(
        proposal_path,
        decision_date=decision_date,
    )
    proposal_file_hash = (
        "sha256:" + hashlib.sha256(proposal_path.read_bytes()).hexdigest()
    )
    official_event_pointer = _make_official_event_pointer(tmp_path)
    collector = MLAllocationShadowCollector(
        market_database_path=market_db,
        paper_state_db_path=paper_db,
        sidecar_database_path=tmp_path / "shadow.sqlite",
        artifact_root=tmp_path / "artifacts",
        official_market_event_pointer_path=official_event_pointer,
    )
    forward_deadline = datetime.now(timezone.utc) + timedelta(minutes=1)

    first = collector.record_and_mature(
        decision_date=decision_date,
        strict_t_minus_one=strict_t_minus_one,
        proposal_path=proposal_path,
        proposal_hash=proposal_hash,
        proposal_file_hash=proposal_file_hash,
        replay_hash=replay_hash,
        orchestration_run_hash=f"sha256:{'8' * 64}",
        rule_policy_hash=f"sha256:{'9' * 64}",
        release_training_manifest_file_hash=f"sha256:{'a' * 64}",
        raw_publication_manifest_hash=f"sha256:{'b' * 64}",
        inference_universe_hash=f"sha256:{'c' * 64}",
        natural_forward_deadline_at=forward_deadline,
    )
    replay = collector.record_and_mature(
        decision_date=decision_date,
        strict_t_minus_one=strict_t_minus_one,
        proposal_path=proposal_path,
        proposal_hash=proposal_hash,
        proposal_file_hash=proposal_file_hash,
        replay_hash=replay_hash,
        orchestration_run_hash=f"sha256:{'8' * 64}",
        rule_policy_hash=f"sha256:{'9' * 64}",
        release_training_manifest_file_hash=f"sha256:{'a' * 64}",
        raw_publication_manifest_hash=f"sha256:{'b' * 64}",
        inference_universe_hash=f"sha256:{'c' * 64}",
        natural_forward_deadline_at=forward_deadline,
    )
    matured = collector.mature_and_summarize(
        cutoff_date=decision_date + timedelta(days=59)
    )

    assert first["lane_count"] == 4
    assert first["lane_alphas_bp"] == [0, 2000, 3500, 5000]
    assert first["matured_observation_count"] == 0
    assert first["shadow_day_credit_allowed"] is False
    assert first["formal_oos_allowed"] is False
    assert first["selected_alpha_bp"] == 0
    assert first["broker_order_allowed"] is False
    assert isinstance(first["observation_emitted_at"], str)
    assert datetime.fromisoformat(
        str(first["observation_emitted_at"])
    ) <= forward_deadline
    assert first["maturity_deferred_for_forward_deadline"] is True
    assert replay["observation_idempotent"] is True
    assert replay["observation_hash"] == first["observation_hash"]
    assert matured["matured_observation_count"] == 0
    assert matured["promotion_credit_observation_count"] == 0
    assert (
        "shadow_rule_baseline_or_context_not_formal_no_promotion_credit"
        in matured["blockers"]
    )
    assert matured["status"] == "insufficient_evidence"
    assert matured["formal_consumer_compatible"] is False
    assert matured["compatible_promotion_evidence_path"] is None
    assert matured["outcome_contract_hash"].startswith("sha256:")
    outcomes = ShadowEvidenceRepository(
        tmp_path / "shadow.sqlite"
    ).latest_outcomes(observation_hashes=(str(first["observation_hash"]),))
    assert len(outcomes) == 1
    assert outcomes[0]["status"] == "matured_all_horizons"
    assert outcomes[0]["completed_horizons_trading_sessions"] == list(
        PROMOTION_HORIZONS
    )
    assert {
        item["horizon_trading_sessions"]
        for item in outcomes[0]["downside_outcomes"]
    } == set(PROMOTION_HORIZONS)
    assert all(
        item["benchmark_excess_return_bp"]
        == (
            item["stock_open_to_close_return_bp"]
            - item["taiex_open_to_close_return_bp"]
            - 25
            - 55
        )
        for item in outcomes[0]["downside_outcomes"]
    )

    observation = json.loads(
        Path(str(first["observation_path"])).read_text(encoding="utf-8")
    )
    assert observation["four_lane_weight_conservation"] is True
    assert observation["future_prefix_violation_count"] == 0
    assert observation["pit_violation_count"] == 0
    assert [lane["alpha_bp"] for lane in observation["lanes"]] == [
        0,
        2000,
        3500,
        5000,
    ]
    for lane in observation["lanes"]:
        assert lane["research_only"] is True
        assert lane["allocation_result"]["broker_order_allowed"] is False
        assert lane["advice"]["research_only"] is True
        assert lane["advice"]["broker_order_allowed"] is False
        assert all(row["why"] for row in lane["advice"]["rows"])
        assert all(row["why_not"] for row in lane["advice"]["rows"])


def test_forward_deadline_rolls_back_slow_observation_emission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """append 跨越 08:35 時，repository transaction 必須 rollback。"""

    market_db = tmp_path / "market.sqlite"
    decision_date, strict_t_minus_one = _make_market_db(market_db)
    paper_db = tmp_path / "paper.sqlite"
    _make_paper_db(
        paper_db,
        snapshot_date=strict_t_minus_one - timedelta(days=1),
    )
    proposal_path = tmp_path / "proposal.json"
    proposal_hash, replay_hash = _write_proposal(
        proposal_path,
        decision_date=decision_date,
    )
    proposal_file_hash = (
        "sha256:" + hashlib.sha256(proposal_path.read_bytes()).hexdigest()
    )
    official_event_pointer = _make_official_event_pointer(tmp_path)
    collector = MLAllocationShadowCollector(
        market_database_path=market_db,
        paper_state_db_path=paper_db,
        sidecar_database_path=tmp_path / "shadow.sqlite",
        artifact_root=tmp_path / "artifacts",
        official_market_event_pointer_path=official_event_pointer,
    )
    deadline = datetime(2026, 2, 2, 23, 0, tzinfo=timezone.utc)
    before = deadline - timedelta(seconds=1)
    after = deadline + timedelta(seconds=1)
    clock = iter((before, before, before, after))
    monkeypatch.setattr(evidence_module, "_utc_now", lambda: next(clock))

    with pytest.raises(
        TimeoutError,
        match="emission crossed deadline",
    ):
        collector.record_and_mature(
            decision_date=decision_date,
            strict_t_minus_one=strict_t_minus_one,
            proposal_path=proposal_path,
            proposal_hash=proposal_hash,
            proposal_file_hash=proposal_file_hash,
            replay_hash=replay_hash,
            orchestration_run_hash=f"sha256:{'8' * 64}",
            rule_policy_hash=f"sha256:{'9' * 64}",
            release_training_manifest_file_hash=f"sha256:{'a' * 64}",
            raw_publication_manifest_hash=f"sha256:{'b' * 64}",
            inference_universe_hash=f"sha256:{'c' * 64}",
            natural_forward_deadline_at=deadline,
        )

    repository = ShadowEvidenceRepository(tmp_path / "shadow.sqlite")
    assert repository.observations() == ()


@pytest.mark.parametrize(
    ("missing_source", "expected_blocker"),
    (
        ("corporate_action", "corporate_action_manifest_missing"),
        ("benchmark_open", "benchmark_open_missing"),
        ("stock_open", "stock_open_missing"),
    ),
)
def test_outcome_sources_fail_closed_without_creating_labels(
    tmp_path: Path,
    missing_source: str,
    expected_blocker: str,
) -> None:
    market_db = tmp_path / f"{missing_source}-market.sqlite"
    decision_date, _ = _make_market_db(market_db)
    pointer = (
        None
        if missing_source == "corporate_action"
        else _make_official_event_pointer(tmp_path / missing_source)
    )
    with sqlite3.connect(market_db) as connection:
        if missing_source == "benchmark_open":
            connection.execute(
                """
                UPDATE market_indices SET "開盤價" = NULL
                WHERE "日期" = ? AND "指數名稱" = 'TAIEX'
                """,
                (decision_date.strftime("%Y%m%d"),),
            )
        elif missing_source == "stock_open":
            connection.execute(
                """
                UPDATE daily_prices SET "開盤價" = NULL
                WHERE "日期" = ? AND "證券代號" = '2330'
                """,
                (decision_date.strftime("%Y%m%d"),),
            )
    sidecar = tmp_path / f"{missing_source}-shadow.sqlite"
    observation = _append_minimal_observation(
        sidecar,
        decision_date=decision_date,
        symbols=("2330",),
    )
    collector = MLAllocationShadowCollector(
        market_database_path=market_db,
        paper_state_db_path=tmp_path / "unused-paper.sqlite",
        sidecar_database_path=sidecar,
        artifact_root=tmp_path / f"{missing_source}-artifacts",
        official_market_event_pointer_path=pointer,
    )

    summary = collector.mature_and_summarize(
        cutoff_date=decision_date + timedelta(days=59)
    )
    outcomes = ShadowEvidenceRepository(sidecar).latest_outcomes(
        observation_hashes=(str(observation["record_hash"]),)
    )

    assert summary["matured_observation_count"] == 0
    assert len(outcomes) == 1
    assert outcomes[0]["status"] == "blocked"
    assert outcomes[0]["downside_outcomes"] == []
    assert any(
        expected_blocker in blocker for blocker in outcomes[0]["blockers"]
    )


def test_outcome_uses_each_symbol_calendar_without_common_date_intersection(
    tmp_path: Path,
) -> None:
    market_db = tmp_path / "market.sqlite"
    decision_date, _ = _make_market_db(market_db)
    with sqlite3.connect(market_db) as connection:
        connection.execute(
            'DELETE FROM daily_prices WHERE "日期" >= ?',
            (decision_date.strftime("%Y%m%d"),),
        )
        connection.execute("DELETE FROM market_indices")
        stock_rows = []
        benchmark_rows = []
        for session_index in range(60):
            for symbol, offset in (("2330", 0), ("2317", 1)):
                observed = decision_date + timedelta(
                    days=session_index * 2 + offset
                )
                stock_rows.append(
                    (
                        observed.strftime("%Y%m%d"),
                        symbol,
                        symbol,
                        1_000_000,
                        str(Decimal("100") + session_index),
                        str(Decimal("101") + session_index),
                    )
                )
                benchmark_rows.append(
                    (
                        observed.strftime("%Y%m%d"),
                        "TAIEX",
                        str(Decimal("1000") + session_index),
                        str(Decimal("1001") + session_index),
                    )
                )
        connection.executemany(
            "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?)",
            stock_rows,
        )
        connection.executemany(
            "INSERT OR IGNORE INTO market_indices VALUES (?, ?, ?, ?)",
            benchmark_rows,
        )
    sidecar = tmp_path / "shadow.sqlite"
    observation = _append_minimal_observation(
        sidecar,
        decision_date=decision_date,
        symbols=("2317", "2330"),
    )
    pointer = _make_official_event_pointer(tmp_path)
    collector = MLAllocationShadowCollector(
        market_database_path=market_db,
        paper_state_db_path=tmp_path / "unused-paper.sqlite",
        sidecar_database_path=sidecar,
        artifact_root=tmp_path / "artifacts",
        official_market_event_pointer_path=pointer,
    )

    summary = collector.mature_and_summarize(
        cutoff_date=decision_date + timedelta(days=119)
    )
    outcome = ShadowEvidenceRepository(sidecar).latest_outcomes(
        observation_hashes=(str(observation["record_hash"]),)
    )[0]

    assert summary["matured_observation_count"] == 1
    assert outcome["status"] == "matured_all_horizons"
    assert len(outcome["downside_outcomes"]) == 8
    entry_dates = {
        item["symbol"]: item["entry_date"]
        for item in outcome["downside_outcomes"]
        if item["horizon_trading_sessions"] == 5
    }
    assert entry_dates["2317"] != entry_dates["2330"]


def test_horizon_outcome_hash_is_prefix_stable_and_revisions_append(
    tmp_path: Path,
) -> None:
    market_db = tmp_path / "market.sqlite"
    decision_date, _ = _make_market_db(market_db)
    sidecar = tmp_path / "shadow.sqlite"
    observation = _append_minimal_observation(
        sidecar,
        decision_date=decision_date,
        symbols=("2330",),
    )
    pointer = _make_official_event_pointer(tmp_path)
    collector = MLAllocationShadowCollector(
        market_database_path=market_db,
        paper_state_db_path=tmp_path / "unused-paper.sqlite",
        sidecar_database_path=sidecar,
        artifact_root=tmp_path / "artifacts",
        official_market_event_pointer_path=pointer,
    )

    collector.mature_and_summarize(
        cutoff_date=decision_date + timedelta(days=4)
    )
    repository = ShadowEvidenceRepository(sidecar)
    first = repository.latest_outcomes(
        observation_hashes=(str(observation["record_hash"]),)
    )[0]
    first_h5_hash = first["downside_outcomes"][0]["outcome_hash"]
    assert first["status"] == "partial_horizon_maturity"
    assert first["completed_horizons_trading_sessions"] == [5]

    with sqlite3.connect(market_db) as connection:
        connection.execute(
            """
            UPDATE daily_prices SET "收盤價" = '999999'
            WHERE "日期" = ? AND "證券代號" = '2330'
            """,
            ((decision_date + timedelta(days=59)).strftime("%Y%m%d"),),
        )
    collector.mature_and_summarize(
        cutoff_date=decision_date + timedelta(days=4)
    )
    assert len(repository.outcomes()) == 1

    collector.mature_and_summarize(
        cutoff_date=decision_date + timedelta(days=59)
    )
    second = repository.latest_outcomes(
        observation_hashes=(str(observation["record_hash"]),)
    )[0]
    second_h5_hash = next(
        item["outcome_hash"]
        for item in second["downside_outcomes"]
        if item["horizon_trading_sessions"] == 5
    )
    assert second["revision"] == 2
    assert second["status"] == "matured_all_horizons"
    assert second_h5_hash == first_h5_hash

    with sqlite3.connect(market_db) as connection:
        connection.execute(
            """
            UPDATE daily_prices SET "收盤價" = '88'
            WHERE "日期" = ? AND "證券代號" = '2330'
            """,
            ((decision_date + timedelta(days=4)).strftime("%Y%m%d"),),
        )
    collector.mature_and_summarize(
        cutoff_date=decision_date + timedelta(days=59)
    )
    third = repository.latest_outcomes(
        observation_hashes=(str(observation["record_hash"]),)
    )[0]
    third_h5_hash = next(
        item["outcome_hash"]
        for item in third["downside_outcomes"]
        if item["horizon_trading_sessions"] == 5
    )
    assert third["revision"] == 3
    assert third["previous_revision_hash"] == second["record_hash"]
    assert third_h5_hash != second_h5_hash
    collector.mature_and_summarize(
        cutoff_date=decision_date + timedelta(days=59)
    )
    assert len(repository.outcomes()) == 3


def test_maturity_refresh_excludes_future_eod_rows_until_available(
    tmp_path: Path,
) -> None:
    market_db = tmp_path / "market.sqlite"
    decision_date, _ = _make_market_db(market_db)
    sidecar = tmp_path / "shadow.sqlite"
    observation = _append_minimal_observation(
        sidecar,
        decision_date=decision_date,
        symbols=("2330",),
    )
    pointer = _make_official_event_pointer(tmp_path)
    collector = MLAllocationShadowCollector(
        market_database_path=market_db,
        paper_state_db_path=None,
        sidecar_database_path=sidecar,
        artifact_root=tmp_path / "artifacts",
        official_market_event_pointer_path=pointer,
    )

    before_eod = collector.mature_and_summarize(
        cutoff_date=decision_date + timedelta(days=59),
        available_at_cutoff=datetime(
            2026,
            2,
            2,
            15,
            0,
            tzinfo=timezone.utc,
        ),
    )
    assert before_eod["status"] == "insufficient_evidence"
    assert before_eod["matured_observation_count"] == 0

    after_eod = collector.mature_and_summarize(
        cutoff_date=decision_date + timedelta(days=59),
        available_at_cutoff=datetime(
            2026,
            4,
            10,
            0,
            0,
            tzinfo=timezone.utc,
        ),
    )
    assert after_eod["matured_observation_count"] == 1
    assert after_eod["outcome_records_appended"] == 1
    outcomes = ShadowEvidenceRepository(sidecar).latest_outcomes(
        observation_hashes=(str(observation["record_hash"]),)
    )
    assert outcomes[0]["status"] == "matured_all_horizons"


def test_reference_metrics_are_immutable_and_have_hash_bound_latest_pointer(
    tmp_path: Path,
) -> None:
    collector = MLAllocationShadowCollector(
        market_database_path=tmp_path / "unused-market.sqlite",
        paper_state_db_path=tmp_path / "unused-paper.sqlite",
        sidecar_database_path=tmp_path / "shadow.sqlite",
        artifact_root=tmp_path / "artifacts",
    )
    body = {
        "schema_version": "fixture-reference-metrics-v1",
        "status": "not_evaluated",
        "horizon_metrics": {
            str(horizon): {
                "status": "not_evaluated",
                "matured_unique_decision_date_count": 0,
            }
            for horizon in PROMOTION_HORIZONS
        },
    }
    metrics = {**body, "metrics_hash": _hash(body)}

    first = collector._write_reference_metrics(metrics)  # noqa: SLF001
    replay = collector._write_reference_metrics(metrics)  # noqa: SLF001
    pointer = json.loads(
        Path(
            str(first["latest_reference_metrics_pointer_path"])
        ).read_text(encoding="utf-8")
    )

    assert first == replay
    assert Path(str(first["reference_metrics_path"])).is_file()
    assert pointer["reference_metrics_hash"] == metrics["metrics_hash"]
    assert pointer["reference_metrics_file_hash"] == first[
        "reference_metrics_file_hash"
    ]
    assert pointer["outcome_contract_hash"].startswith("sha256:")
    assert pointer["formal_oos_allowed"] is False
    assert pointer["production_blend_alpha_bp"] == 0


def test_after_cost_drawdown_cvar_and_calibration_are_integer_bp() -> None:
    dates = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(3))
    metrics = fixed_weight_path_metrics(
        weights={
            "symbol_weights_bp": {"2330": 5000},
            "cash_weight_bp": 5000,
        },
        price_paths={
            "2330": {
                dates[0]: Decimal("100"),
                dates[1]: Decimal("90"),
                dates[2]: Decimal("110"),
            }
        },
        dates=dates,
        transaction_cost=Decimal("25"),
        capital_amount=Decimal("10000"),
    )
    calibration = calibration_metrics(((2000, 0), (8000, 1)))

    assert metrics == {
        "after_cost_return_bp": 475,
        "max_drawdown_bp": 500,
        "cvar_loss_bp": 500,
        "transaction_cost_bp": 25,
    }
    assert calibration == {
        "ece_bp": 2000,
        "brier_bp": 400,
        "observation_count": 2,
    }


def test_bootstrap_requires_real_maturity_and_is_deterministic() -> None:
    with pytest.raises(ValueError, match="20"):
        deterministic_block_bootstrap_lower_95_bp([1] * 19)
    first = deterministic_block_bootstrap_lower_95_bp(
        [100, -25, 75, 0, 50] * 4
    )
    second = deterministic_block_bootstrap_lower_95_bp(
        [100, -25, 75, 0, 50] * 4
    )
    assert first == second
