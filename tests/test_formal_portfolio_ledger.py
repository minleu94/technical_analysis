from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from data_module import formal_portfolio_ledger as ledger
from ml_module.allocation_contracts import (
    AllocationWeightContract,
    CausalPortfolioState,
)
from ml_module.allocation_oos_portfolio_replay import (
    _load_formal_portfolio_state_ledger_custody,
)


def _state_payload(state: CausalPortfolioState) -> str:
    return ledger._canonical_json(
        {
            "as_of_date": state.as_of_date,
            "weights": ledger._weight_payload(state.weights),
            "weekly_turnover_used_bp": state.weekly_turnover_used_bp,
            "state_hash": state.state_hash,
        }
    )


def _build_ledger(
    root: Path,
    *,
    research_only: bool = False,
    tamper_sqlite: bool = False,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    sqlite_path = root / "portfolio_ledger.sqlite"
    connection = sqlite3.connect(sqlite_path)
    connection.execute(
        """
        CREATE TABLE transitions (
            decision_date TEXT PRIMARY KEY,
            input_state_json TEXT NOT NULL,
            desired_weights_json TEXT NOT NULL,
            output_state_json TEXT NOT NULL,
            feature_input_hash TEXT NOT NULL,
            buy_turnover_bp INTEGER NOT NULL,
            sell_turnover_bp INTEGER NOT NULL,
            canonical_turnover_bp INTEGER NOT NULL,
            estimated_cost_bp INTEGER NOT NULL,
            add_count INTEGER NOT NULL,
            reduce_count INTEGER NOT NULL,
            transition_hash TEXT NOT NULL UNIQUE,
            chain_hash TEXT NOT NULL UNIQUE
        )
        """
    )
    connection.execute(
        """
        CREATE TRIGGER transitions_no_update
        BEFORE UPDATE ON transitions
        BEGIN
            SELECT RAISE(ABORT, 'append-only ledger');
        END;
        """
    )
    connection.execute(
        """
        CREATE TRIGGER transitions_no_delete
        BEFORE DELETE ON transitions
        BEGIN
            SELECT RAISE(ABORT, 'append-only ledger');
        END;
        """
    )

    cash = AllocationWeightContract(positions_bp=(), cash_bp=10_000)
    invested = AllocationWeightContract(
        positions_bp=(("2330", 1_000),),
        cash_bp=9_000,
    )
    first_input = CausalPortfolioState.create(
        as_of_date="2024-01-01",
        weights=cash,
        weekly_turnover_used_bp=0,
    )
    first_output = CausalPortfolioState.create(
        as_of_date="2024-01-02",
        weights=invested,
        weekly_turnover_used_bp=1_000,
    )
    second_output = CausalPortfolioState.create(
        as_of_date="2024-01-03",
        weights=invested,
        weekly_turnover_used_bp=1_000,
    )
    desired_json = ledger._canonical_json(ledger._weight_payload(invested))
    previous_chain = ledger._ZERO_SHA256
    for decision_date, input_state, output_state, feature_hash in (
        (
            "2024-01-02",
            first_input,
            first_output,
            "sha256:" + "1" * 64,
        ),
        (
            "2024-01-03",
            first_output,
            second_output,
            "sha256:" + "2" * 64,
        ),
    ):
        transition_payload = {
            "schema_version": ledger.FORMAL_PORTFOLIO_LEDGER_TRANSITION_SCHEMA_VERSION,
            "decision_date": decision_date,
            "input_state_hash": input_state.state_hash,
            "feature_input_hash": feature_hash,
            "desired_weights": ledger._weight_payload(invested),
            "output_state_hash": output_state.state_hash,
            "buy_turnover_bp": 1_000,
            "sell_turnover_bp": 0,
            "canonical_turnover_bp": 1_000,
            "estimated_cost_bp": 25,
            "add_count": 1,
            "reduce_count": 0,
            "future_teacher_target_used": False,
            "same_day_advice_used": False,
        }
        transition_hash = ledger._payload_hash(transition_payload)
        chain_hash = ledger._payload_hash(
            {
                "previous_chain_hash": previous_chain,
                "transition_hash": transition_hash,
            }
        )
        connection.execute(
            """
            INSERT INTO transitions(
                decision_date, input_state_json, desired_weights_json,
                output_state_json, feature_input_hash, buy_turnover_bp,
                sell_turnover_bp, canonical_turnover_bp, estimated_cost_bp,
                add_count, reduce_count, transition_hash, chain_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision_date,
                _state_payload(input_state),
                desired_json,
                _state_payload(output_state),
                feature_hash,
                1_000,
                0,
                1_000,
                25,
                1,
                0,
                transition_hash,
                chain_hash,
            ),
        )
        previous_chain = chain_hash
    connection.commit()
    connection.close()

    sqlite_file_hash = ledger._file_hash(sqlite_path)
    identity = {
        "schema_version": ledger.FORMAL_PORTFOLIO_LEDGER_SCHEMA_VERSION,
        "transition_schema_version": ledger.FORMAL_PORTFOLIO_LEDGER_TRANSITION_SCHEMA_VERSION,
        "sqlite_file_hash": sqlite_file_hash,
        "policy_hash": "sha256:" + "3" * 64,
        "decision_dates": ["2024-01-02", "2024-01-03"],
        "decision_date_count": 2,
        "non_cash_state_day_count": 1,
        "transition_chain_hash": previous_chain,
        "future_teacher_target_used": False,
        "same_day_advice_used": False,
    }
    body: dict[str, object] = {
        "schema_version": ledger.FORMAL_PORTFOLIO_LEDGER_SCHEMA_VERSION,
        "status": "complete",
        "formal_source_only": True,
        "research_only": research_only,
        "formal_consumer_compatible": True,
        "promotion_eligible": False,
        "transition_schema_version": ledger.FORMAL_PORTFOLIO_LEDGER_TRANSITION_SCHEMA_VERSION,
        "sqlite_path": sqlite_path.name,
        "sqlite_file_hash": sqlite_file_hash,
        "policy_hash": identity["policy_hash"],
        "decision_dates": identity["decision_dates"],
        "decision_date_count": 2,
        "non_cash_state_day_count": 1,
        "transition_chain_hash": previous_chain,
        "future_teacher_target_used": False,
        "same_day_advice_used": False,
        "ledger_manifest_hash": ledger._payload_hash(identity),
    }
    body["manifest_hash"] = ledger._payload_hash(body)
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    if tamper_sqlite:
        sqlite_path.write_bytes(sqlite_path.read_bytes() + b"tamper")
    return manifest_path


def test_formal_ledger_builds_non_cash_t_minus_one_replay(tmp_path: Path) -> None:
    manifest_path = _build_ledger(tmp_path)

    replay = ledger.load_formal_portfolio_state_ledger(
        manifest_path,
        calendar=("2024-01-01", "2024-01-02", "2024-01-03"),
        decision_dates=("2024-01-02", "2024-01-03"),
    )

    assert replay.cash_only_fallback is False
    assert replay.state_for("2024-01-02").weights.cash_bp == 10_000
    assert replay.state_for("2024-01-03").weights.invested_bp == 1_000
    custody = replay.custody_payload()
    assert custody["ledger_present"] is True
    assert custody["turnover_learning_claim_allowed"] is True
    assert custody["non_cash_state_day_count"] == 1


def test_formal_ledger_rejects_research_shadow_and_file_tamper(
    tmp_path: Path,
) -> None:
    research_manifest = _build_ledger(tmp_path / "research", research_only=True)
    with pytest.raises(ValueError, match="research-only"):
        ledger.load_formal_portfolio_state_ledger(research_manifest)

    tamper_root = tmp_path / "tamper"
    tamper_root.mkdir()
    tamper_manifest = _build_ledger(tamper_root, tamper_sqlite=True)
    with pytest.raises(ValueError, match="sqlite hash mismatch"):
        ledger.load_formal_portfolio_state_ledger(tamper_manifest)


def test_formal_ledger_rejects_non_t_minus_one_coverage(tmp_path: Path) -> None:
    manifest_path = _build_ledger(tmp_path)
    with pytest.raises(ValueError, match="input state is not T-1"):
        ledger.load_formal_portfolio_state_ledger(
            manifest_path,
            calendar=("2023-12-31", "2024-01-02", "2024-01-03"),
            decision_dates=("2024-01-02", "2024-01-03"),
        )


def test_oos_consumer_revalidates_formal_ledger_custody(
    tmp_path: Path,
) -> None:
    manifest_path = _build_ledger(tmp_path)
    source = ledger.load_formal_portfolio_state_ledger(manifest_path)

    verified = _load_formal_portfolio_state_ledger_custody(
        {"portfolio_state_policy": source.custody_payload()}
    )

    assert verified is not None
    assert verified.ledger_manifest_hash == source.ledger_manifest_hash
    assert verified.state_for("2024-01-03").weights.invested_bp == 1_000
