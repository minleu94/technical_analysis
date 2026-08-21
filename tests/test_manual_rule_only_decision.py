from __future__ import annotations

from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import tempfile

import pytest

from app_module.external_evidence_contracts import ExternalEvidenceDecisionSnapshot
from development_module.formal_observation_lane import (
    CANDIDATE_SOURCE_IDS,
    FormalObservationLaneDecision,
    RULE_ONLY_SOURCE_IDS,
)
from development_module.manual_rule_only_decision import (
    DEVELOPMENT_OUTPUT_ROOT_NAME,
    MANUAL_CONFIRMATION,
    TAIPEI_TIME_ZONE,
    ManualRuleOnlyDecisionError,
    produce_manual_rule_only_decision,
    require_development_temp_root,
)
from scripts.inspect_formal_clock_readiness import inspect_readiness
from scripts.run_manual_rule_only_decision import build_parser


_KEY_ENV = "RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY"
_STORE_ENV = "RULE_CHAMPION_CONTROLLED_STORE_ID"


def _development_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    temp_base = tmp_path / "temp"
    temp_base.mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(temp_base))
    root = temp_base / DEVELOPMENT_OUTPUT_ROOT_NAME
    governance = root / "governance"
    governance.mkdir(parents=True)

    usage_decision = {
        "decision": "seen_oos",
        "owner_provided_authorization": "owner-record-20260806",
        "year_2025_usage": "development_only",
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "effective_timestamp_utc": "2026-08-06T05:15:10+08:00",
        "development_output_root": str(root),
        "new_holdout_start": "2026-07-14",
    }
    usage_path = governance / "DevelopmentDataUsageDecision.jsonl"
    usage_path.write_text(json.dumps(usage_decision) + "\n", encoding="utf-8")

    lane = FormalObservationLaneDecision(
        decision_id="decision:formal.rule_only_candidate_exclusion:20260807-r1",
        holdout_id="formal-rule-only-20260807-r1",
        decided_at="2026-08-06T05:15:10+08:00",
        owner_id="archi",
        first_eligible_session="2026-08-07",
        allowed_source_ids=RULE_ONLY_SOURCE_IDS,
        excluded_source_ids=CANDIDATE_SOURCE_IDS,
        rollback_reference="append-only owner rollback reference",
    )
    lane_path = governance / "FormalObservationLaneDecision_20260807_r1.json"
    lane_path.write_text(
        json.dumps({**lane.to_dict(), "content_hash": lane.content_hash}),
        encoding="utf-8",
    )
    registry_record = {
        "schema_version": "holdout-consumption-registry.v3",
        "record_type": "formal_observation_lane_binding",
        "holdout_id": lane.holdout_id,
        "development_holdout_start": "2026-07-14",
        "formal_trading_session": lane.first_eligible_session,
        "owner_id": "archi",
        "binding_authorization": lane.decision_id,
        "bound_at": "2026-08-06T05:20:00+08:00",
        "lane_decision_sha256": lane.content_hash,
        "development_decision_sha256": "sha256:" + sha256(usage_path.read_bytes()).hexdigest(),
        "unconsumed_before_binding": True,
        "rule_only_formal_path": True,
        "no_retroactive_credit": True,
        "formal_oos_allowed": False,
        "formal_evidence_credit_authorized": False,
        "production_blend_alpha_bp": 0,
    }
    (governance / "HoldoutConsumptionRegistry.jsonl").write_text(
        json.dumps(registry_record) + "\n", encoding="utf-8"
    )
    return root, lane_path


def _daily_price_db(tmp_path: Path, *, include_decision_day: bool = False) -> Path:
    db_path = tmp_path / "market.sqlite"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            'CREATE TABLE daily_prices ("日期" TEXT, "證券代號" TEXT, "收盤價" TEXT, "成交股數" INTEGER)'
        )
        start = date(2026, 7, 1)
        for offset in range(25):
            session = start + timedelta(days=offset)
            date_key = session.strftime("%Y%m%d")
            connection.execute(
                "INSERT INTO daily_prices VALUES (?, ?, ?, ?)",
                (date_key, "2330", str(700 + offset * 2), 1_000_000 + offset * 10_000),
            )
            connection.execute(
                "INSERT INTO daily_prices VALUES (?, ?, ?, ?)",
                (date_key, "2317", str(500 - offset), 1_500_000 - offset * 8_000),
            )
        if include_decision_day:
            connection.execute(
                "INSERT INTO daily_prices VALUES (?, ?, ?, ?)",
                ("20260807", "2317", "9999", 999_999_999),
            )
    # 固定 fixture 的發布時間，讓 look-ahead guard 不受測試執行日期影響。
    os.utime(db_path, (1, 1))
    return db_path


def _observed_at() -> datetime:
    return datetime(2026, 8, 7, 10, 0, tzinfo=TAIPEI_TIME_ZONE)


def test_produces_signed_temp_only_manual_observed_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, lane_path = _development_root(tmp_path, monkeypatch)
    db_path = _daily_price_db(tmp_path, include_decision_day=True)
    before_mtime = db_path.stat().st_mtime_ns
    monkeypatch.setenv(_KEY_ENV, "isolated-test-controlled-store-key")
    monkeypatch.setenv(_STORE_ENV, "controlled-store:test")

    result = produce_manual_rule_only_decision(
        development_output_root=root,
        market_db=db_path,
        lane_decision_json=lane_path,
        confirmation=MANUAL_CONFIRMATION,
        observed_at=_observed_at(),
        eligible_symbols=("2317", "2330"),
    )

    assert result["status"] == "manual_observed_source_created"
    assert result["write_performed"] is True
    assert result["symbol"] == "2330"
    assert result["data_as_of_date"] == "2026-07-25"
    assert result["source_versions"].keys() == {"daily_prices"}
    assert result["evidence_ledger_write_performed"] is False
    assert result["formal_oos_allowed"] is False
    assert result["production_blend_alpha_bp"] == 0
    assert db_path.stat().st_mtime_ns == before_mtime

    snapshot_payload = json.loads(Path(str(result["manual_observed_json"])).read_text(encoding="utf-8"))
    snapshot = ExternalEvidenceDecisionSnapshot.create(**snapshot_payload)
    assert snapshot.capture_kind == "manual_observed"
    assert snapshot.data_as_of_date == "2026-07-25"
    assert snapshot.source_versions.keys() == {"daily_prices"}
    assert all(":sha256:" in item for item in snapshot.parent_artifact_ids)

    readiness = inspect_readiness(
        root,
        Path(str(result["manual_observed_json"])),
        lane_path,
    )
    assert readiness["can_capture_shadow_snapshot"] is True
    assert readiness["formal_readiness"] is False

    persisted = json.loads(Path(str(result["formal_rule_decision_json"])).read_text(encoding="utf-8"))
    assert persisted["rule_only_proof"] == "formal_rule_only"
    assert persisted["registered_store_id"] == "controlled-store:test"
    assert persisted["rule_rank"] == 1


def test_clock_bound_rule_universe_missing_t1_history_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, lane_path = _development_root(tmp_path, monkeypatch)
    db_path = _daily_price_db(tmp_path)
    monkeypatch.setenv(_KEY_ENV, "isolated-test-controlled-store-key")
    monkeypatch.setenv(_STORE_ENV, "controlled-store:test")

    with pytest.raises(
        ManualRuleOnlyDecisionError,
        match="clock_bound_rule_universe_incomplete_t1_history",
    ):
        produce_manual_rule_only_decision(
            development_output_root=root,
            market_db=db_path,
            lane_decision_json=lane_path,
            confirmation=MANUAL_CONFIRMATION,
            observed_at=_observed_at(),
            eligible_symbols=("2317", "9999"),
        )
    assert not (root / "formal_rule_only_manual").exists()


def test_confirmation_required_does_not_create_a_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, lane_path = _development_root(tmp_path, monkeypatch)
    db_path = _daily_price_db(tmp_path)

    result = produce_manual_rule_only_decision(
        development_output_root=root,
        market_db=db_path,
        lane_decision_json=lane_path,
        confirmation="",
        observed_at=_observed_at(),
    )

    assert result["status"] == "confirmation_required"
    assert result["write_performed"] is False
    assert not (root / "formal_rule_only_manual").exists()


def test_rejects_pre_market_and_missing_attestation_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, lane_path = _development_root(tmp_path, monkeypatch)
    db_path = _daily_price_db(tmp_path)
    monkeypatch.setenv(_KEY_ENV, "isolated-test-controlled-store-key")
    monkeypatch.setenv(_STORE_ENV, "controlled-store:test")

    with pytest.raises(ManualRuleOnlyDecisionError, match="outside_taiwan_regular_session"):
        produce_manual_rule_only_decision(
            development_output_root=root,
            market_db=db_path,
            lane_decision_json=lane_path,
            confirmation=MANUAL_CONFIRMATION,
            observed_at=datetime(2026, 8, 7, 8, 59, tzinfo=TAIPEI_TIME_ZONE),
        )

    monkeypatch.delenv(_KEY_ENV)
    with pytest.raises(ManualRuleOnlyDecisionError, match="attestation_key_missing"):
        produce_manual_rule_only_decision(
            development_output_root=root,
            market_db=db_path,
            lane_decision_json=lane_path,
            confirmation=MANUAL_CONFIRMATION,
            observed_at=_observed_at(),
        )
    assert not (root / "formal_rule_only_manual").exists()


def test_requires_named_temp_root_and_cli_has_no_time_override(tmp_path: Path) -> None:
    with pytest.raises(ManualRuleOnlyDecisionError, match="root_name"):
        require_development_temp_root(tmp_path / "not-a-development-root")

    parser_destinations = {action.dest for action in build_parser()._actions}
    assert "decision_at" not in parser_destinations
    assert "observed_at" not in parser_destinations
