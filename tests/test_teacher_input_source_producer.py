from __future__ import annotations

from datetime import datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

import pytest

from data_module.portfolio_ml_dataset_assembler import (
    SECTOR_MEMBERSHIP_MANIFEST_SCHEMA_VERSION,
    SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION,
    build_teacher_source_row_provenance_for_assembly,
)
from data_module.portfolio_ml_target_diagnostics import (
    TargetDiagnosticError,
    evaluate_allocation_teacher_eligibility,
)
from data_module.formal_portfolio_ledger import (
    FORMAL_PORTFOLIO_LEDGER_SCHEMA_VERSION,
    FORMAL_PORTFOLIO_LEDGER_TRANSITION_SCHEMA_VERSION,
)
from data_module.rule_champion_snapshot_service import (
    FORMAL_RULE_ONLY,
    FORMAL_RULE_ONLY_IMMUTABLE_DECISION_SNAPSHOT,
    RULE_CHAMPION_HISTORY_SCHEMA_VERSION,
)
from ml_module.allocation_contracts import (
    AllocationWeightContract,
    CausalPortfolioState,
)
from ml_module.allocation_out_of_core_training_service import TARGET_FIELDS


DECISION_DATE = "2020-01-02"
CUTOFF = "2020-01-02T08:30:00+08:00"
_KEY = b"teacher-source-test-key"
_STORE_ID = "teacher-source-test-store"
_ZERO = "sha256:" + ("0" * 64)


# 小型合成資料驗證使用可控容量；實體低空間另由專用capacity tests驗證。
pytestmark = pytest.mark.usefixtures("synthetic_ml_capacity")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(value) + b"\n")


def _write_sector_sidecar(path: Path) -> None:
    rows = [
        {
            "symbol": "2330",
            "sector_id": "SEMI",
            "available_at": "2020-01-01T08:00:00+08:00",
            "effective_from": "2020-01-01",
            "effective_to": None,
            "status": "accepted",
            "source_id": "twse:historical-sector-membership",
            "license_id": "twse-open-data-license-v1",
            "source_hash": "sha256:" + ("1" * 64),
        }
    ]
    manifest_body = {
        "schema_version": SECTOR_MEMBERSHIP_MANIFEST_SCHEMA_VERSION,
        "row_count": len(rows),
        "rows_hash": _hash(rows),
    }
    payload = {
        "schema_version": SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION,
        "manifest": {
            **manifest_body,
            "canonical_hash": _hash(
                {
                    "sidecar_schema_version": (
                        SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION
                    ),
                    "manifest": manifest_body,
                }
            ),
        },
        "rows": rows,
    }
    _write_json(path, payload)


def _write_rule_history(path: Path) -> None:
    row_body: dict[str, object] = {
        "schema_version": "FormalRuleDecisionSnapshot.v1",
        "source_artifact_kind": FORMAL_RULE_ONLY_IMMUTABLE_DECISION_SNAPSHOT,
        "rule_only_proof": FORMAL_RULE_ONLY,
        "decision_snapshot_id": "rule-decision-20200102",
        "decision_timestamp": "2020-01-02T08:20:00+08:00",
        "symbol": "2330",
        "rule_score_bp": 120,
        "rule_rank": 1,
        "source_lineage_artifact_id": "rule-lineage-20200102",
        "source_lineage_hash": "sha256:" + ("2" * 64),
        "restrictions_hash": "sha256:" + ("3" * 64),
    }
    row_body["immutable_snapshot_hash"] = _hash(row_body)
    row_body["registered_store_id"] = _STORE_ID
    row_body["attestation_signature"] = "hmac-sha256:" + hmac.new(
        _KEY,
        _canonical(row_body),
        hashlib.sha256,
    ).hexdigest()
    snapshot_payload = {
        "schema_version": "RuleChampionSnapshot.v1",
        "source_kind": FORMAL_RULE_ONLY,
        "strategy_version": "teacher-test-rule-v1",
        "policy_version": "teacher-test-policy-v1",
        "score_configuration_hash": "sha256:" + ("4" * 64),
        "universe_hash": "sha256:" + ("5" * 64),
        "selection_capacity": 1,
        "decision_timestamp": row_body["decision_timestamp"],
        "decision_snapshot_ids": [row_body["decision_snapshot_id"]],
        "source_lineage_artifact_ids": [row_body["source_lineage_artifact_id"]],
        "rule_only_proof": FORMAL_RULE_ONLY,
        "decision_rows": [row_body],
    }
    snapshot = {
        **snapshot_payload,
        "champion_snapshot_family_id": (
            "champion:teacher-test-rule-v1:" + _hash(snapshot_payload)[7:19]
        ),
        "content_hash": _hash(snapshot_payload),
    }
    history_body = {
        "schema_version": RULE_CHAMPION_HISTORY_SCHEMA_VERSION,
        "status": "complete",
        "formal_source_only": True,
        "research_only": False,
        "formal_consumer_compatible": True,
        "promotion_eligible": False,
        "rule_only_proof": FORMAL_RULE_ONLY,
        "registered_store_id": _STORE_ID,
        "decision_dates": [DECISION_DATE],
        "snapshot_count": 1,
        "snapshots": [snapshot],
    }
    _write_json(path, {**history_body, "manifest_hash": _hash(history_body)})


def _write_ledger(path: Path, *, include_available_at: bool = True) -> None:
    input_state = CausalPortfolioState.create(
        as_of_date="2020-01-01",
        weights=AllocationWeightContract(
            positions_bp=(("2330", 1_000),),
            cash_bp=9_000,
        ),
        weekly_turnover_used_bp=0,
    )
    output_state = CausalPortfolioState.create(
        as_of_date=DECISION_DATE,
        weights=AllocationWeightContract(
            positions_bp=(("2330", 1_000),),
            cash_bp=9_000,
        ),
        weekly_turnover_used_bp=0,
    )
    feature_input_hash = "sha256:" + ("6" * 64)
    transition_payload = {
        "schema_version": FORMAL_PORTFOLIO_LEDGER_TRANSITION_SCHEMA_VERSION,
        "decision_date": DECISION_DATE,
        "input_state_hash": input_state.state_hash,
        "feature_input_hash": feature_input_hash,
        "desired_weights": {
            "positions_bp": [["2330", 1_000]],
            "cash_bp": 9_000,
        },
        "output_state_hash": output_state.state_hash,
        "buy_turnover_bp": 0,
        "sell_turnover_bp": 0,
        "canonical_turnover_bp": 0,
        "estimated_cost_bp": 0,
        "add_count": 0,
        "reduce_count": 0,
        "future_teacher_target_used": False,
        "same_day_advice_used": False,
    }
    transition_hash = _hash(transition_payload)
    chain_hash = _hash(
        {"previous_chain_hash": _ZERO, "transition_hash": transition_hash}
    )
    transition_columns = [
        "decision_date TEXT PRIMARY KEY",
        "input_state_json TEXT NOT NULL",
        "desired_weights_json TEXT NOT NULL",
        "output_state_json TEXT NOT NULL",
        "feature_input_hash TEXT NOT NULL",
        "buy_turnover_bp INTEGER NOT NULL",
        "sell_turnover_bp INTEGER NOT NULL",
        "canonical_turnover_bp INTEGER NOT NULL",
        "estimated_cost_bp INTEGER NOT NULL",
        "add_count INTEGER NOT NULL",
        "reduce_count INTEGER NOT NULL",
        "transition_hash TEXT NOT NULL UNIQUE",
        "chain_hash TEXT NOT NULL UNIQUE",
    ]
    if include_available_at:
        transition_columns.append("available_at TEXT")
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE transitions (" + ",".join(transition_columns) + ")"
        )
        columns = [
            "decision_date",
            "input_state_json",
            "desired_weights_json",
            "output_state_json",
            "feature_input_hash",
            "buy_turnover_bp",
            "sell_turnover_bp",
            "canonical_turnover_bp",
            "estimated_cost_bp",
            "add_count",
            "reduce_count",
            "transition_hash",
            "chain_hash",
        ]
        values: list[object] = [
            DECISION_DATE,
            _canonical(
                {
                    "as_of_date": input_state.as_of_date,
                    "weights": {
                        "positions_bp": [["2330", 1_000]],
                        "cash_bp": 9_000,
                    },
                    "weekly_turnover_used_bp": 0,
                    "state_hash": input_state.state_hash,
                }
            ).decode("utf-8"),
            _canonical(
                {"positions_bp": [["2330", 1_000]], "cash_bp": 9_000}
            ).decode("utf-8"),
            _canonical(
                {
                    "as_of_date": output_state.as_of_date,
                    "weights": {
                        "positions_bp": [["2330", 1_000]],
                        "cash_bp": 9_000,
                    },
                    "weekly_turnover_used_bp": 0,
                    "state_hash": output_state.state_hash,
                }
            ).decode("utf-8"),
            feature_input_hash,
            0,
            0,
            0,
            0,
            0,
            0,
            transition_hash,
            chain_hash,
        ]
        if include_available_at:
            columns.append("available_at")
            values.append("2020-01-02T08:00:00+08:00")
        connection.execute(
            "INSERT INTO transitions ("
            + ",".join(columns)
            + ") VALUES ("
            + ",".join("?" for _ in columns)
            + ")",
            values,
        )
        connection.commit()
    sqlite_hash = _file_hash(path)
    policy_hash = "sha256:" + ("7" * 64)
    ledger_identity = {
        "schema_version": FORMAL_PORTFOLIO_LEDGER_SCHEMA_VERSION,
        "transition_schema_version": FORMAL_PORTFOLIO_LEDGER_TRANSITION_SCHEMA_VERSION,
        "sqlite_file_hash": sqlite_hash,
        "policy_hash": policy_hash,
        "decision_dates": [DECISION_DATE],
        "decision_date_count": 1,
        "non_cash_state_day_count": 1,
        "transition_chain_hash": chain_hash,
        "future_teacher_target_used": False,
        "same_day_advice_used": False,
    }
    body: dict[str, object] = {
        "schema_version": FORMAL_PORTFOLIO_LEDGER_SCHEMA_VERSION,
        "status": "complete",
        "formal_source_only": True,
        "research_only": False,
        "formal_consumer_compatible": True,
        "promotion_eligible": False,
        "transition_schema_version": FORMAL_PORTFOLIO_LEDGER_TRANSITION_SCHEMA_VERSION,
        "sqlite_path": path.name,
        "sqlite_file_hash": sqlite_hash,
        "policy_hash": policy_hash,
        "decision_dates": [DECISION_DATE],
        "decision_date_count": 1,
        "non_cash_state_day_count": 1,
        "transition_chain_hash": chain_hash,
        "future_teacher_target_used": False,
        "same_day_advice_used": False,
        "ledger_manifest_hash": _hash(ledger_identity),
    }
    _write_json(path.with_name("manifest.json"), {**body, "manifest_hash": _hash(body)})


def _source_fixture(tmp_path: Path, *, include_available_at: bool = True) -> dict[str, Path]:
    sector_path = tmp_path / "sector.json"
    rule_path = tmp_path / "rule-history.json"
    ledger_path = tmp_path / "ledger" / "manifest.json"
    _write_sector_sidecar(sector_path)
    _write_rule_history(rule_path)
    _write_ledger(
        ledger_path.with_name("ledger.sqlite"),
        include_available_at=include_available_at,
    )
    return {
        "pit_sector_membership": sector_path,
        "causal_non_cash_portfolio_ledger": ledger_path,
        "formal_rule_champion_snapshot_history": rule_path,
    }


def _decision_rows() -> list[dict[str, object]]:
    return [
        {
            "decision_date": DECISION_DATE,
            "candidate_row_count": 1,
            "eligible_candidate_count": 1,
            "complete_candidate_set": True,
            "target_mode": "non_cash",
        }
    ]


def _diagnostics() -> dict[str, int]:
    return {
        "decision_date_count": 1,
        "label_row_count": 1,
        "input_candidate_count": 1,
        "eligible_candidate_count": 1,
        "unknown_sector_candidate_count": 0,
        "teacher_incomplete_decision_count": 0,
        "non_cash_target_decision_count": 1,
        "cash_only_target_decision_count": 0,
    }


def _target_summary() -> dict[str, dict[str, int]]:
    result = {
        field: {
            "min": 0,
            "max": 0,
            "nonzero_count": 0,
            "observed_count": 1,
        }
        for field in TARGET_FIELDS
    }
    result["target_weight_bp"] = {
        "min": 1_000,
        "max": 1_000,
        "nonzero_count": 1,
        "observed_count": 1,
    }
    result["cash_bp"] = {
        "min": 9_000,
        "max": 9_000,
        "nonzero_count": 1,
        "observed_count": 1,
    }
    return result


def _gate(provenance: dict[str, object]) -> dict[str, Any]:
    return evaluate_allocation_teacher_eligibility(
        target_summary=_target_summary(),
        teacher_target_diagnostics=_diagnostics(),
        teacher_input_provenance=provenance,
    )


def test_real_source_rows_flow_through_assembler_producer_and_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY", _KEY.decode())
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_ID", _STORE_ID)
    qa_root_text = os.environ.get("TEACHER_SOURCE_QA_OUTPUT_ROOT")
    fixture_root = (
        Path(qa_root_text).expanduser().resolve()
        if qa_root_text
        else tmp_path
    )
    sources = _source_fixture(fixture_root / "sources")
    provenance = build_teacher_source_row_provenance_for_assembly(
        source_paths=sources,
        output_root=fixture_root / "provenance",
        decision_dates=(DECISION_DATE,),
        decision_cutoffs={DECISION_DATE: CUTOFF},
        decision_rows=_decision_rows(),
    )
    assert provenance["source_rows_are_artifact_rebuilt"] is True
    assert provenance["source_availability_proven"] is True
    for source in provenance["sources"].values():
        assert source["receipt_rows"]
    gate = _gate(provenance)
    assert gate["allowed"] is True
    assert gate["formal_oos_allowed"] is False
    assert gate["broker_order_allowed"] is False
    if qa_root_text:
        qa_root = Path(qa_root_text).expanduser().resolve()
        qa_root.mkdir(parents=True, exist_ok=True)
        _write_json(
            qa_root / "source_rows_assembler_gate_positive.v2.json",
            {
                "schema_version": "teacher-source-assembler-gate-qa.v1",
                "source_nature": "synthetic_test_fixture",
                "formal_source": False,
                "production_formal_custody": False,
                "scope_note": (
                    "這是合成 source artifact 的 assembler→producer→gate QA；"
                    "不可當成 Direct/Formal production custody。"
                ),
                "flow": [
                    "actual_fixture_source_artifacts",
                    "assembler_build_teacher_source_row_provenance_for_assembly",
                    "target_diagnostics_teacher_gate",
                ],
                "source_paths": {
                    name: str(path.resolve()) for name, path in sources.items()
                },
                "provenance": provenance,
                "gate": gate,
            },
        )


def test_source_bytes_tamper_is_rejected_after_valid_hash_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY", _KEY.decode())
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_ID", _STORE_ID)
    sources = _source_fixture(tmp_path)
    provenance = build_teacher_source_row_provenance_for_assembly(
        source_paths=sources,
        output_root=tmp_path / "provenance",
        decision_dates=(DECISION_DATE,),
        decision_cutoffs={DECISION_DATE: CUTOFF},
        decision_rows=_decision_rows(),
    )
    sources["pit_sector_membership"].write_bytes(
        sources["pit_sector_membership"].read_bytes() + b"\n"
    )
    with pytest.raises(TargetDiagnosticError, match="artifact readback failed"):
        _gate(provenance)


def test_missing_ledger_availability_is_a_blocked_gate_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY", _KEY.decode())
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_ID", _STORE_ID)
    sources = _source_fixture(tmp_path, include_available_at=False)
    provenance = build_teacher_source_row_provenance_for_assembly(
        source_paths=sources,
        output_root=tmp_path / "provenance",
        decision_dates=(DECISION_DATE,),
        decision_cutoffs={DECISION_DATE: CUTOFF},
        decision_rows=_decision_rows(),
    )
    assert provenance["source_availability_proven"] is False
    gate = _gate(provenance)
    assert gate["allowed"] is False
    assert "teacher_source_availability_unproven" in gate["reasons"]
