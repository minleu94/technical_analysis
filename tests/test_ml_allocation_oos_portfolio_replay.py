from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
from typing import Mapping

from ml_module.allocation_oos_portfolio_replay import (
    ALPHA_LANES,
    AllocationOOSPortfolioReplayRequest,
    _expected_fold_bindings,
    _load_formal_custody as _load_replay_formal_custody,
    build_allocation_oos_portfolio_replay,
)
from ml_module.allocation_promotion_evidence_builder import (
    AllocationPromotionEvidenceBuildRequest,
    _load_formal_custody as _load_promotion_formal_custody,
    _load_replay_custody,
)
from ml_module.allocation_oos_replay_input_builder import (
    _Bar,
    _Candidate,
    _LaneState,
    _execute_day,
    _require_daily_bars,
)
import pytest
from scripts.build_ml_allocation_oos_portfolio_replay import main


HASH = "sha256:" + "1" * 64
AS_OF = datetime(2026, 4, 30, 23, 59, tzinfo=timezone.utc)
POLICY = {
    "minimum_cash_bp": 2_000,
    "maximum_positions": 8,
    "maximum_symbol_weight_bp": 1_500,
    "maximum_sector_weight_bp": 3_000,
    "maximum_t_minus_1_median_volume_participation_bp": 500,
    "maximum_weekly_turnover_bp": 2_000,
    "rebalance_band_bp": 300,
    "minimum_trade_bp": 200,
    "cooldown_trading_days": 5,
    "lot_size_shares": 1_000,
    "buy_cost_bp": 25,
    "sell_cost_bp": 55,
}
EXECUTION_SAFETY = {
    "causal_t_minus_one_portfolio_state": True,
    "actual_next_tradable_execution": True,
    "transaction_costs_included": True,
    "rule_baseline_replayed": True,
    "hard_constraints_replayed": True,
    "advice_feedback_forbidden": True,
    "teacher_future_targets_used_for_execution": False,
    "decision_time_local": "08:30:00",
    "decision_timezone": "Asia/Taipei",
    "execution_return_basis": (
        "next_tradable_execution_to_next_tradable_mark_after_cost"
    ),
}
EXECUTION_COMPONENT_CONTRACT = {
    "schema_version": "allocation-ooc-replay-calculation-components.v1",
    "daily_return_recomputed_from_minor_units": True,
    "turnover_recomputed_from_integer_weights": True,
    "price_component_set_hash_verified": True,
    "maximum_daily_after_cost_return_bp": 10_000,
    "maximum_daily_turnover_bp": 10_000,
}


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _with_hash(
    value: Mapping[str, object],
    field_name: str,
) -> dict[str, object]:
    result = dict(value)
    result[field_name] = _payload_hash(result)
    return result


def _artifact_file(path: Path, content: bytes) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {
        "path": path.name,
        "byte_count": len(content),
        "file_sha256": _file_hash(path),
    }


def _artifact(
    run: Path,
    *,
    relative_directory: str,
    schema: str,
    kind: str,
    fold_id: str,
    expert_id: str | None,
    with_oof: bool,
) -> dict[str, object]:
    directory = run / relative_directory
    head = _artifact_file(
        directory / "head.joblib",
        f"{kind}:{fold_id}".encode(),
    )
    artifacts = [head]
    shape: list[int] | None = None
    dtype: str | None = None
    is_meta = schema == "allocation-ooc-meta.v3"
    target_fields = [
        "target_weight_bp",
        "delta_weight_bp",
        "risk_contribution_bp",
        "risky_budget_bp",
        "cash_bp",
        "rebalance_worthwhile",
    ]
    if with_oof:
        row_count = 5 if is_meta else 20
        column_count = len(target_fields) if is_meta else 1
        oof = _artifact_file(
            directory / "oof.i32",
            bytes([len(fold_id)]) * row_count * column_count * 4,
        )
        artifacts.append(oof)
        shape = [row_count, column_count]
        dtype = "<i4"
    body: dict[str, object] = {
        "schema_version": schema,
        "artifact_kind": kind,
        "fold_id": fold_id,
        "expert_id": expert_id,
        "oof_shape": shape,
        "oof_dtype": dtype,
        "artifacts": artifacts,
    }
    if is_meta:
        body.update(
            {
                "target_fields": target_fields,
                "test_row_count": 5 if with_oof else 0,
                "head_models": [
                    {"head_id": field_name}
                    for field_name in target_fields
                ],
            }
        )
    manifest = _with_hash(body, "manifest_hash")
    _write(directory / "manifest.json", manifest)
    return {
        **manifest,
        "artifact_path": directory.relative_to(run).as_posix(),
    }


def _build_formal_ooc(root: Path) -> tuple[Path, Path]:
    run = root / "formal-ooc" / "runs" / "run-001"
    fold_rows: list[dict[str, object]] = []
    row_dates: list[tuple[int, str]] = []
    # 第一個 expanding outer fold 只建立 base OOF；要有四個有效 ML
    # meta OOF folds，因此 fixture 需五個 outer folds。
    for index in range(1, 6):
        fold_id = f"fold-{index:03d}"
        start = date(2026, 1, 5) + timedelta(days=(index - 1) * 14)
        local_indexes = tuple(range((index - 1) * 5, index * 5))
        refs = b"".join(
            struct.pack("<qq", 0, local_index)
            for local_index in local_indexes
        )
        row_dates.extend(
            (local_index, (start + timedelta(days=offset)).isoformat())
            for offset, local_index in enumerate(local_indexes)
        )
        ref_path = run / "folds" / f"{fold_id}.test.refs.i64"
        ref_path.parent.mkdir(parents=True, exist_ok=True)
        ref_path.write_bytes(refs)
        fold_rows.append(
            {
                "schema_version": "portfolio-ml-ooc-fold-index.v1",
                "fold_id": fold_id,
                "test_start": start.isoformat(),
                "test_end": (start + timedelta(days=6)).isoformat(),
                "test": {
                    "path": ref_path.name,
                    "row_count": 5,
                    "shape": [5, 2],
                    "dtype": "<i8",
                    "content_sha256": _file_hash(ref_path),
                    "file_sha256": _file_hash(ref_path),
                },
            }
        )

    year_directory = run / "year=2026"
    year_artifacts = [
        _artifact_file(year_directory / name, name.encode() * 3)
        for name in (
            "targets.i32",
            "labels.i32",
            "labels.masks.u8",
        )
    ]
    rows_path = year_directory / "rows.sqlite"
    connection = sqlite3.connect(rows_path)
    connection.execute(
        "CREATE TABLE rows (local_row_index INTEGER PRIMARY KEY, "
        "decision_date TEXT NOT NULL)"
    )
    connection.executemany(
        "INSERT INTO rows(local_row_index, decision_date) VALUES (?, ?)",
        row_dates,
    )
    connection.commit()
    connection.close()
    year_artifacts.append(
        {
            "path": rows_path.name,
            "byte_count": rows_path.stat().st_size,
            "file_sha256": _file_hash(rows_path),
        }
    )
    year_body: dict[str, object] = {
        "schema_version": "portfolio-ml-ooc-year.v3",
        "year": 2026,
        "year_ordinal": 0,
        "row_count": 25,
        "artifacts": year_artifacts,
    }
    year = _with_hash(year_body, "manifest_hash")
    dataset_body: dict[str, object] = {
        "schema_version": "portfolio-ml-ooc-store.v3",
        "status": "complete",
        "dataset_id": "formal-ooc-dataset",
        "dataset_identity_hash": HASH,
        "formal_source_only": True,
        "research_shadow_included": False,
        "research_only": False,
        "store_identity": {
            "direct_identity": {
                "raw_manifest_hash": "sha256:" + "6" * 64,
                "raw_manifest_file_hash": "sha256:" + "7" * 64,
            }
        },
        "readiness": {"full_market_ready": True},
        "safety": {
            "pit_contract_revalidated_per_row": True,
            "t_minus_1_contract_revalidated_per_row": True,
        },
        "years": [year],
        "folds": fold_rows,
    }
    dataset = _with_hash(dataset_body, "manifest_hash")
    dataset_path = run / "store_manifest.json"
    _write(dataset_path, dataset)

    base_summaries = [
        _artifact(
            run,
            relative_directory=f"artifacts/base/fold-{index:03d}",
            schema="allocation-ooc-expert.v5",
            kind="base_oof_expert",
            fold_id=f"fold-{index:03d}",
            expert_id=f"expert:fold-{index:03d}",
            with_oof=True,
        )
        for index in range(1, 6)
    ]
    meta_summaries = [
        _artifact(
            run,
            relative_directory=f"artifacts/meta/fold-{index:03d}",
            schema="allocation-ooc-meta.v3",
            kind="meta_oof_allocator",
            fold_id=f"fold-{index:03d}",
            expert_id=None,
            with_oof=True,
        )
        for index in range(2, 6)
    ]
    final_meta = _artifact(
        run,
        relative_directory="artifacts/meta/final",
        schema="allocation-ooc-meta.v3",
        kind="final_meta_allocator",
        fold_id="final",
        expert_id=None,
        with_oof=False,
    )
    training_body: dict[str, object] = {
        "schema_version": "allocation-ooc-training.v5",
        "status": "complete",
        "run_id": "formal-ooc-model-001",
        "store_manifest_path": dataset_path.relative_to(run).as_posix(),
        "store_manifest_file_hash": _file_hash(dataset_path),
        "dataset_identity_hash": HASH,
        "formal_source_only": True,
        "research_shadow_included": False,
        "research_only": False,
        "fold_count": 5,
        "base_expert_count": 5,
        "base_experts": base_summaries,
        "meta_folds": meta_summaries,
        "final_meta": final_meta,
        "validation": {
            "pit_violation_count": 0,
            "future_prefix_violation_count": 0,
            "constraint_violation_count": 0,
            "deterministic_custody": True,
        },
    }
    training = _with_hash(training_body, "manifest_hash")
    training_path = run / "manifest.json"
    _write(training_path, training)
    return training_path, dataset_path


def _daily_metrics(
    *,
    return_bp: int,
    turnover_bp: int,
) -> dict[str, int]:
    return {
        "after_cost_return_bp": return_bp,
        "turnover_bp": turnover_bp,
        "core_coverage_bp": 9_800,
        "enriched_coverage_bp": 9_400,
        "feasible_fill_coverage_bp": 9_700,
        "pit_violation_count": 0,
        "future_prefix_violation_count": 0,
        "constraint_violation_count": 0,
    }


def _calculation_component(
    *,
    return_bp: int,
    turnover_bp: int,
) -> dict[str, object]:
    opening = 1_000_000
    return {
        "opening_value_minor": opening,
        "closing_value_minor": opening + return_bp * 100,
        "transaction_cost_minor": 0,
        "opening_cash_minor": opening,
        "closing_cash_minor": opening + return_bp * 100,
        "holdings": [],
        "before_weights": [{"key": "CASH", "weight_bp": 10_000}],
        "after_trade_weights": [{"key": "CASH", "weight_bp": 10_000}],
    }


def _build_replay_input(
    training_path: Path,
    *,
    directory_name: str = "",
    future_outcome: bool = False,
    alpha_zero_return_bp: int | None = None,
    naked_float: bool = False,
) -> Path:
    custody = _load_replay_formal_custody(training_path)
    directory = (
        training_path.parent
        / "artifacts"
        / "oos_portfolio_replay_inputs"
        / directory_name
    )
    input_path = directory / "manifest.json"
    rows_path = directory / "rows.jsonl"
    rule_policy_hash = "sha256:" + "2" * 64
    cost_policy_hash = "sha256:" + "3" * 64
    ledger_hash = "sha256:" + "4" * 64
    records: list[dict[str, object]] = []
    record_hashes: list[str] = []
    for fold_index, fold_id in enumerate(custody.outer_fold_ids):
        fold = custody.folds_by_id[fold_id]
        start = date.fromisoformat(str(fold["test_start"]))
        meta = custody.meta_oof_by_fold.get(fold_id)
        for day_offset in range(5):
            decision_date = start + timedelta(days=day_offset)
            decision_at = datetime.combine(
                decision_date,
                datetime.min.time(),
                tzinfo=timezone(timedelta(hours=8)),
            ) + timedelta(hours=8, minutes=30)
            outcome_at = (
                datetime(2027, 1, 1, tzinfo=timezone.utc)
                if future_outcome and fold_index == 0 and day_offset == 0
                else decision_at + timedelta(hours=20)
            )
            rule = _daily_metrics(return_bp=0, turnover_bp=0)
            if naked_float and fold_index == 0 and day_offset == 0:
                rule["turnover_bp"] = 50.0  # type: ignore[assignment]
            lanes: list[dict[str, object]] = []
            lane_calculations: list[dict[str, object]] = []
            for alpha in ALPHA_LANES:
                if meta is None:
                    lane_return = 0
                    turnover = 0
                else:
                    lane_return = 0
                    turnover = 0
                if alpha == 0 and alpha_zero_return_bp is not None:
                    lane_return = alpha_zero_return_bp
                lanes.append(
                    {
                        "alpha_bp": alpha,
                        **_daily_metrics(
                            return_bp=lane_return,
                            turnover_bp=turnover,
                        ),
                    }
                )
                lane_calculations.append(
                    {
                        "alpha_bp": alpha,
                        **_calculation_component(
                            return_bp=lane_return,
                            turnover_bp=turnover,
                        ),
                    }
                )
            body: dict[str, object] = {
                "schema_version": "allocation-ooc-replay-observation.v1",
                "fold_id": fold_id,
                "decision_date": decision_date.isoformat(),
                "decision_at": decision_at.isoformat(timespec="seconds"),
                "outcome_available_at": outcome_at.isoformat(
                    timespec="seconds"
                ),
                "allocation_source": (
                    "rule_fallback" if meta is None else "meta_oof"
                ),
                "source_meta_oof_file_hash": (
                    None if meta is None else meta["oof_file_hash"]
                ),
                "rule_policy_hash": rule_policy_hash,
                "cost_policy_hash": cost_policy_hash,
                "causal_portfolio_ledger_hash": ledger_hash,
                "calculation_verification": {
                    "price_components": [],
                    "price_source_set_hash": _payload_hash([]),
                    "rule": _calculation_component(
                        return_bp=0,
                        turnover_bp=0,
                    ),
                    "lanes": lane_calculations,
                },
                "rule": rule,
                "lanes": lanes,
            }
            record = _with_hash(body, "record_hash")
            records.append(record)
            record_hashes.append(str(record["record_hash"]))
    rows_path.parent.mkdir(parents=True, exist_ok=True)
    rows_path.write_text(
        "".join(_canonical_json(record) + "\n" for record in records),
        encoding="utf-8",
    )
    manifest_body: dict[str, object] = {
        "schema_version": "allocation-ooc-replay-inputs.v1",
        "status": "complete",
        "formal_source_only": True,
        "research_shadow_included": False,
        "research_only": False,
        "input_custody": dict(custody.input_custody),
        "dataset_replay_source_hash": custody.dataset_replay_source_hash,
        "outer_fold_ids": list(custody.outer_fold_ids),
        "alpha_lanes_bp": list(ALPHA_LANES),
        "policy": POLICY,
        "execution_safety": EXECUTION_SAFETY,
        "execution_component_contract": EXECUTION_COMPONENT_CONTRACT,
        "rule_policy_hash": rule_policy_hash,
        "cost_policy_hash": cost_policy_hash,
        "causal_portfolio_ledger_hash": ledger_hash,
        "fold_bindings": _expected_fold_bindings(custody),
        "rows": {
            "path": rows_path.name,
            "row_count": len(records),
            "byte_count": rows_path.stat().st_size,
            "file_sha256": _file_hash(rows_path),
            "record_hashes_hash": _payload_hash(record_hashes),
        },
    }
    _write(input_path, _with_hash(manifest_body, "manifest_hash"))
    return input_path


def _request(
    training_path: Path,
    output_root: Path,
    *,
    role: str,
    run_id: str,
    input_path: Path | None = None,
) -> AllocationOOSPortfolioReplayRequest:
    return AllocationOOSPortfolioReplayRequest(
        training_manifest_path=training_path,
        replay_input_manifest_path=input_path,
        output_root=output_root,
        replay_run_id=run_id,
        role=role,
        replay_as_of=AS_OF,
    )


def _tamper_first_row(
    input_path: Path,
    mutator: object,
) -> None:
    manifest = json.loads(input_path.read_text(encoding="utf-8"))
    rows_path = input_path.parent / manifest["rows"]["path"]
    rows = [
        json.loads(line)
        for line in rows_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert callable(mutator)
    mutator(rows[0])
    rows[0].pop("record_hash", None)
    rows[0] = _with_hash(rows[0], "record_hash")
    rows_path.write_text(
        "".join(_canonical_json(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    manifest["rows"].update(
        {
            "byte_count": rows_path.stat().st_size,
            "file_sha256": _file_hash(rows_path),
            "record_hashes_hash": _payload_hash(
                [row["record_hash"] for row in rows]
            ),
        }
    )
    manifest.pop("manifest_hash", None)
    _write(input_path, _with_hash(manifest, "manifest_hash"))


def _attach_retro_source_artifact(
    input_path: Path,
    training_path: Path,
) -> tuple[Path, Path]:
    custody = _load_replay_formal_custody(training_path)
    source_root = input_path.parent / "replay_sources"
    source_root.mkdir(parents=True, exist_ok=True)
    database_path = source_root / "year=2026.sqlite"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE replay_source (
            symbol TEXT,
            price_event_at TEXT,
            price_available_at TEXT,
            open_int INTEGER,
            open_scale INTEGER,
            close_int INTEGER,
            close_scale INTEGER,
            volume_shares INTEGER,
            source_values_hash TEXT
        )
        """
    )
    connection.commit()
    connection.close()
    database_hash = _file_hash(database_path)
    retro_body: dict[str, object] = {
        "schema_version": "portfolio-ml-replay-source.v1",
        "source_mode": "retro_hash_bound_raw_pit",
        "year": 2026,
        "row_count": 0,
        "database_path": database_path.name,
        "database_file_hash": database_hash,
        "training_manifest_hash": custody.training["manifest_hash"],
        "training_manifest_file_hash": _file_hash(custody.training_path),
        "store_manifest_hash": custody.dataset["manifest_hash"],
        "store_manifest_file_hash": _file_hash(custody.dataset_path),
        "raw_manifest_hash": "sha256:" + "6" * 64,
        "raw_manifest_file_hash": "sha256:" + "7" * 64,
        "teacher_targets_or_horizon_labels_read": False,
        "sector_unknown_no_new_position": True,
        "trade_restriction_unknown_no_new_position": True,
    }
    retro_path = source_root / "year=2026.manifest.json"
    _write(retro_path, _with_hash(retro_body, "manifest_hash"))
    retro = json.loads(retro_path.read_text(encoding="utf-8"))
    input_manifest = json.loads(input_path.read_text(encoding="utf-8"))
    input_manifest["replay_source_manifest_set_hash"] = _payload_hash(
        [database_hash]
    )
    input_manifest["replay_source_artifacts"] = [
        {
            "year": 2026,
            "path": str(database_path.resolve()),
            "file_sha256": database_hash,
            "row_count": 0,
            "source_mode": "retro_hash_bound_raw_pit",
            "lineage": {
                "schema_version": "allocation-replay-source-lineage.v1",
                "derivation_manifest_path": str(retro_path.resolve()),
                "derivation_manifest_hash": retro["manifest_hash"],
                "derivation_manifest_file_hash": _file_hash(retro_path),
                "database_file_hash": database_hash,
                "training_manifest_hash": custody.training["manifest_hash"],
                "training_manifest_file_hash": _file_hash(
                    custody.training_path
                ),
                "store_manifest_hash": custody.dataset["manifest_hash"],
                "store_manifest_file_hash": _file_hash(
                    custody.dataset_path
                ),
                "raw_manifest_hash": "sha256:" + "6" * 64,
                "raw_manifest_file_hash": "sha256:" + "7" * 64,
            },
        }
    ]
    input_manifest.pop("manifest_hash", None)
    _write(input_path, _with_hash(input_manifest, "manifest_hash"))
    return database_path, retro_path


def test_missing_actual_execution_ledger_blocks_without_pointer(
    tmp_path: Path,
) -> None:
    training_path, _ = _build_formal_ooc(tmp_path)

    result = build_allocation_oos_portfolio_replay(
        _request(
            training_path,
            tmp_path / "output",
            role="primary",
            run_id="missing-ledger",
        )
    )

    assert result.status == "blocked"
    assert set(result.blockers) == {
        "formal_oos_replay_execution_ledger_missing",
        "formal_oos_replay_realized_daily_returns_missing",
        "formal_oos_replay_rule_baseline_missing",
    }
    assert result.replay_path.is_file()
    assert not result.latest_pointer_path.exists()


def _active_candidate(day: date) -> _Candidate:
    decision_at = datetime.combine(
        day,
        datetime.min.time(),
        tzinfo=timezone(timedelta(hours=8)),
    ) + timedelta(hours=8, minutes=30)
    return _Candidate(
        fold_id="fold-001",
        decision_date=day,
        decision_at=decision_at,
        symbol="2330",
        sector_id="semi",
        price_event_at=decision_at - timedelta(hours=18),
        price_available_at=decision_at - timedelta(hours=18),
        median_volume_20d_shares=10_000_000,
        rule_score_bp=500,
        trade_restriction_status="officially_tradable",
        source_values_hash=HASH,
        ml_target_weight_bp=1_500,
    )


def _bar(day: date, price: str) -> _Bar:
    scaled = int(Decimal(price) * Decimal(100))
    return _Bar(
        symbol="2330",
        event_date=day,
        available_at=datetime.combine(
            day,
            datetime.min.time(),
            tzinfo=timezone(timedelta(hours=8)),
        ) + timedelta(hours=14, minutes=30),
        open_price=Decimal(price),
        close_price=Decimal(price),
        open_int=scaled,
        open_scale=100,
        close_int=scaled,
        close_scale=100,
        volume_shares=10_000_000,
        source_values_hash=HASH,
    )


def test_second_day_overnight_gap_is_included_in_portfolio_return() -> None:
    state = _LaneState()
    first = date(2026, 3, 2)
    second = date(2026, 3, 3)
    requested = {"2330": 1_500, "CASH": 8_500}
    _execute_day(
        state=state,
        decision_day=first,
        session_index=0,
        candidates=(_active_candidate(first),),
        bars={"2330": _bar(first, "10")},
        requested=requested,
    )
    assert state.shares["2330"] > 0

    metrics, _ = _execute_day(
        state=state,
        decision_day=second,
        session_index=1,
        candidates=(_active_candidate(second),),
        bars={"2330": _bar(second, "20")},
        requested=requested,
    )

    assert metrics["after_cost_return_bp"] > 1_000


def test_held_symbol_without_actual_bar_blocks_instead_of_stale_mark() -> None:
    state = _LaneState()
    first = date(2026, 3, 2)
    _execute_day(
        state=state,
        decision_day=first,
        session_index=0,
        candidates=(_active_candidate(first),),
        bars={"2330": _bar(first, "10")},
        requested={"2330": 1_500, "CASH": 8_500},
    )
    with pytest.raises(ValueError, match="held_symbol_bar_missing:2330"):
        _execute_day(
            state=state,
            decision_day=date(2026, 3, 3),
            session_index=1,
            candidates=(),
            bars={},
            requested={"CASH": 10_000},
        )


def test_missing_fold_day_bar_blocks_instead_of_being_skipped() -> None:
    with pytest.raises(
        ValueError,
        match="formal_oos_replay_outcome_bar_missing:fold-001:2026-03-02",
    ):
        _require_daily_bars(
            {},
            fold_id="fold-001",
            decision_day=date(2026, 3, 2),
        )


def test_forged_extreme_return_is_rejected_even_when_rehashed(
    tmp_path: Path,
) -> None:
    training_path, _ = _build_formal_ooc(tmp_path)
    input_path = _build_replay_input(training_path)

    def mutate(row: dict[str, object]) -> None:
        rule = row["rule"]
        assert isinstance(rule, dict)
        rule["after_cost_return_bp"] = 1_000_000
        verification = row["calculation_verification"]
        assert isinstance(verification, dict)
        calculation = verification["rule"]
        assert isinstance(calculation, dict)
        calculation["closing_value_minor"] = 101_000_000

    _tamper_first_row(input_path, mutate)
    result = build_allocation_oos_portfolio_replay(
        _request(
            training_path,
            tmp_path / "output",
            role="primary",
            run_id="forged-return",
            input_path=input_path,
        )
    )
    assert result.status == "blocked"
    assert any("daily_return_above_bound" in item for item in result.blockers)


def test_turnover_tamper_is_rejected_by_component_recompute(
    tmp_path: Path,
) -> None:
    training_path, _ = _build_formal_ooc(tmp_path)
    input_path = _build_replay_input(training_path)

    def mutate(row: dict[str, object]) -> None:
        rule = row["rule"]
        assert isinstance(rule, dict)
        rule["turnover_bp"] = 51
        lanes = row["lanes"]
        assert isinstance(lanes, list)
        lane_zero = lanes[0]
        assert isinstance(lane_zero, dict)
        lane_zero["turnover_bp"] = 51

    _tamper_first_row(input_path, mutate)
    result = build_allocation_oos_portfolio_replay(
        _request(
            training_path,
            tmp_path / "output",
            role="primary",
            run_id="forged-turnover",
            input_path=input_path,
        )
    )
    assert result.status == "blocked"
    assert any(
        "turnover_recompute_mismatch" in item for item in result.blockers
    )


def test_closing_cash_tamper_is_rejected_even_when_row_is_rehashed(
    tmp_path: Path,
) -> None:
    training_path, _ = _build_formal_ooc(tmp_path)
    input_path = _build_replay_input(training_path)

    def mutate(row: dict[str, object]) -> None:
        verification = row["calculation_verification"]
        assert isinstance(verification, dict)
        calculation = verification["rule"]
        assert isinstance(calculation, dict)
        calculation["closing_cash_minor"] = (
            int(calculation["closing_cash_minor"]) + 1
        )

    _tamper_first_row(input_path, mutate)
    result = build_allocation_oos_portfolio_replay(
        _request(
            training_path,
            tmp_path / "output",
            role="primary",
            run_id="forged-closing-cash",
            input_path=input_path,
        )
    )
    assert result.status == "blocked"
    assert any(
        "closing_value_recompute_mismatch" in item
        for item in result.blockers
    )


def test_retro_source_manifest_lineage_tamper_is_rejected(
    tmp_path: Path,
) -> None:
    training_path, _ = _build_formal_ooc(tmp_path)
    input_path = _build_replay_input(training_path)
    _, retro_path = _attach_retro_source_artifact(
        input_path,
        training_path,
    )
    baseline = build_allocation_oos_portfolio_replay(
        _request(
            training_path,
            tmp_path / "baseline-output",
            role="primary",
            run_id="valid-retro-lineage",
            input_path=input_path,
        )
    )
    assert baseline.status == "complete"

    retro = json.loads(retro_path.read_text(encoding="utf-8"))
    retro["raw_manifest_hash"] = "sha256:" + "8" * 64
    retro.pop("manifest_hash", None)
    _write(retro_path, _with_hash(retro, "manifest_hash"))
    retro = json.loads(retro_path.read_text(encoding="utf-8"))
    input_manifest = json.loads(input_path.read_text(encoding="utf-8"))
    lineage = input_manifest["replay_source_artifacts"][0]["lineage"]
    lineage["derivation_manifest_hash"] = retro["manifest_hash"]
    lineage["derivation_manifest_file_hash"] = _file_hash(retro_path)
    input_manifest.pop("manifest_hash", None)
    _write(input_path, _with_hash(input_manifest, "manifest_hash"))

    result = build_allocation_oos_portfolio_replay(
        _request(
            training_path,
            tmp_path / "tampered-output",
            role="primary",
            run_id="tampered-retro-lineage",
            input_path=input_path,
        )
    )
    assert result.status == "blocked"
    assert any(
        "retro_manifest_custody_mismatch" in item
        for item in result.blockers
    )


def test_price_component_hash_tamper_is_rejected(
    tmp_path: Path,
) -> None:
    training_path, _ = _build_formal_ooc(tmp_path)
    input_path = _build_replay_input(training_path)

    def mutate(row: dict[str, object]) -> None:
        verification = row["calculation_verification"]
        assert isinstance(verification, dict)
        verification["price_source_set_hash"] = "sha256:" + "9" * 64

    _tamper_first_row(input_path, mutate)
    result = build_allocation_oos_portfolio_replay(
        _request(
            training_path,
            tmp_path / "output",
            role="primary",
            run_id="forged-price-hash",
            input_path=input_path,
        )
    )
    assert result.status == "blocked"
    assert any(
        "price_component_hash_mismatch" in item
        for item in result.blockers
    )


def test_primary_and_verification_are_deterministic_but_fail_closed_for_promotion(
    tmp_path: Path,
) -> None:
    training_path, dataset_path = _build_formal_ooc(tmp_path)
    _build_replay_input(training_path)
    output = tmp_path / "output"

    primary = build_allocation_oos_portfolio_replay(
        _request(
            training_path,
            output,
            role="primary",
            run_id="replay-primary",
        )
    )
    verification = build_allocation_oos_portfolio_replay(
        _request(
            training_path,
            output,
            role="verification",
            run_id="replay-verification",
        )
    )

    assert primary.status == verification.status == "complete"
    assert primary.replay_result_hash == verification.replay_result_hash
    assert primary.replay_run_id != verification.replay_run_id
    primary_payload = json.loads(primary.replay_path.read_text(encoding="utf-8"))
    assert [lane["alpha_bp"] for lane in primary_payload["lanes"]] == list(
        ALPHA_LANES
    )
    assert all(len(lane["folds"]) == 5 for lane in primary_payload["lanes"])
    assert (
        primary_payload["lanes"][0]["mdd_worsening_vs_rule_bp"] == 0
    )
    pointer = json.loads(
        primary.latest_pointer_path.read_text(encoding="utf-8")
    )
    assert pointer["schema_version"] == (
        "allocation-ooc-portfolio-replay-pointer.v1"
    )
    assert Path(pointer["replay_path"]).is_absolute()
    assert pointer["status"] == "complete"
    assert primary_payload["promotion_eligible_input"] is False
    assert (
        primary_payload["formal_semantic_validation"]["verified"] is False
    )
    assert primary_payload["formal_semantic_validation"]["blockers"]

    promotion_request = AllocationPromotionEvidenceBuildRequest(
        experiment_id="release-v4-prod",
        decision_at=datetime.fromisoformat("2026-05-01T08:30:00+08:00"),
        as_of_date=date(2026, 4, 30),
        training_manifest_path=training_path,
        dataset_manifest_path=dataset_path,
        replay_primary_path=primary.replay_path,
        replay_verification_path=verification.replay_path,
        shadow_sidecar_database_path=tmp_path / "unused-shadow.sqlite",
        promotion_reference_path=tmp_path / "unused-reference.json",
        promotion_reference_metrics_path=tmp_path / "unused-metrics.json",
        output_root=tmp_path / "unused-promotion",
    )
    formal = _load_promotion_formal_custody(promotion_request)
    with pytest.raises(
        ValueError,
        match="formal_replay_primary_semantic_validation_incomplete",
    ):
        _load_replay_custody(promotion_request, formal=formal)


def test_future_outcome_blocks_and_preserves_existing_complete_pointer(
    tmp_path: Path,
) -> None:
    training_path, _ = _build_formal_ooc(tmp_path)
    _build_replay_input(training_path)
    output = tmp_path / "output"
    complete = build_allocation_oos_portfolio_replay(
        _request(
            training_path,
            output,
            role="primary",
            run_id="complete-first",
        )
    )
    pointer_before = complete.latest_pointer_path.read_bytes()
    bad_input = _build_replay_input(
        training_path,
        directory_name="future",
        future_outcome=True,
    )

    blocked = build_allocation_oos_portfolio_replay(
        _request(
            training_path,
            output,
            role="primary",
            run_id="future-blocked",
            input_path=bad_input,
        )
    )

    assert blocked.status == "blocked"
    assert any(
        blocker.startswith("formal_oos_replay_outcome_not_available")
        for blocker in blocked.blockers
    )
    assert complete.latest_pointer_path.read_bytes() == pointer_before
    assert not blocked.latest_pointer_updated


def test_alpha_zero_must_equal_actual_rule_lane(tmp_path: Path) -> None:
    training_path, _ = _build_formal_ooc(tmp_path)
    input_path = _build_replay_input(
        training_path,
        alpha_zero_return_bp=11,
    )

    result = build_allocation_oos_portfolio_replay(
        _request(
            training_path,
            tmp_path / "output",
            role="primary",
            run_id="bad-alpha-zero",
            input_path=input_path,
        )
    )

    assert result.status == "blocked"
    assert any(
        blocker.startswith("formal_oos_replay_alpha_zero_not_rule")
        for blocker in result.blockers
    )


def test_public_financial_metrics_reject_naked_float(tmp_path: Path) -> None:
    training_path, _ = _build_formal_ooc(tmp_path)
    input_path = _build_replay_input(training_path, naked_float=True)

    result = build_allocation_oos_portfolio_replay(
        _request(
            training_path,
            tmp_path / "output",
            role="primary",
            run_id="naked-float-blocked",
            input_path=input_path,
        )
    )

    assert result.status == "blocked"
    assert any(
        "row.rule.turnover_bp must be an integer" in blocker
        for blocker in result.blockers
    )
    assert not result.latest_pointer_updated


def test_identical_run_id_is_idempotent_without_rewriting(
    tmp_path: Path,
) -> None:
    training_path, _ = _build_formal_ooc(tmp_path)
    _build_replay_input(training_path)
    request = _request(
        training_path,
        tmp_path / "output",
        role="primary",
        run_id="idempotent-primary",
    )

    first = build_allocation_oos_portfolio_replay(request)
    first_bytes = first.replay_path.read_bytes()
    second = build_allocation_oos_portfolio_replay(request)

    assert first.status == second.status == "complete"
    assert not first.idempotent
    assert second.idempotent
    assert second.replay_path.read_bytes() == first_bytes
    assert first.replay_result_hash == second.replay_result_hash


def test_cli_writes_fixed_role_layout_and_complete_pointer(
    tmp_path: Path,
) -> None:
    training_path, _ = _build_formal_ooc(tmp_path)
    _build_replay_input(training_path)
    output = tmp_path / "ml_allocation_oos_replay_production_v4"

    exit_code = main(
        [
            "--training-manifest",
            str(training_path),
            "--output-root",
            str(output),
            "--role",
            "verification",
            "--replay-run-id",
            "cli-verification",
            "--replay-as-of",
            AS_OF.isoformat(),
        ]
    )

    assert exit_code == 0
    pointer_path = output / "verification" / "latest_replay.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    assert pointer["replay_run_id"] == "cli-verification"
    assert pointer["replay_path"].endswith(
        "verification\\runs\\cli-verification\\replay.json"
    ) or pointer["replay_path"].endswith(
        "verification/runs/cli-verification/replay.json"
    )
