from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
import tempfile

import pytest

from data_module.prospective_formal_clock import build_clock_manifest, payload_hash
from development_module.manual_rule_only_decision import _RULE_CONFIGURATION, TAIPEI_TIME_ZONE
from development_module.prospective_rule_only_decision import (
    ProspectiveRuleOnlyDecisionError,
    produce_prospective_rule_only_decision,
)


def _clock(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    universe_hash = "sha256:" + "5" * 64
    score_hash = "sha256:1a11086fb3551ba24acb58e4f880eafa49c1e49fc87187ff8e7be02999e891c4"
    seed = {"kind": "cash", "cash_bp": 10_000, "position_count": 0}
    seed["state_hash"] = payload_hash(seed)
    calendar = {
        "schema_version": "official-trading-calendar-evidence.v1",
        "date": "2026-08-17",
        "is_trading_day": True,
        "reason_code": "twse_holiday_schedule_open",
        "source": "TWSE holidaySchedule; TPEX mktCalendar",
        "source_hash": "sha256:" + "1" * 64,
    }
    body: dict[str, object] = {
        "schema_version": "prospective-formal-simulated-portfolio-clock.v1",
        "status": "planned",
        "clock_id": "clock:prospective:test-rule-producer:v1",
        "mode": "prospective_formal_simulation",
        "owner_decision_id": "owner-acceptance:test-rule-producer",
        "owner_decision_timestamp": "2026-08-14T08:45:00+08:00",
        "activation_trading_day": "2026-08-17",
        "decision_timezone": "Asia/Taipei",
        "decision_time": "09:00:00",
        "pit_decision_time": "08:30:00",
        "activation_calendar_evidence": calendar,
        "seed_state": seed,
        "virtual_notional_minor_units": 50_000_000,
        "strategy_version": "manual-rule-only-daily-rank-v1",
        "policy_version": "foreground-owner-bound-v1",
        "policy_hash": "sha256:" + "4" * 64,
        "universe_hash": universe_hash,
        "source_policy_hash": "sha256:" + "6" * 64,
        "candidate_model_hash": "sha256:" + "7" * 64,
        "candidate_feature_manifest_hash": "sha256:" + "8" * 64,
        "candidate_training_cutoff": "2026-08-13T08:30:00+08:00",
        "calibration_policy_hash": "sha256:" + "9" * 64,
        "evaluation_policy_hash": "sha256:" + "a" * 64,
        "real_money": False,
        "broker_execution": False,
        "historical_backfill_claimed": False,
    }
    clock_path = tmp_path / "clock.json"
    clock_path.write_text(json.dumps(build_clock_manifest(body)), encoding="utf-8")
    symbols_path = tmp_path / "symbols.json"
    symbols_path.write_text(json.dumps(["2317", "2330"]), encoding="utf-8")
    acceptance_path = tmp_path / "owner_acceptance.json"
    acceptance_path.write_text(
        json.dumps(
            {
                "decision_id": "owner-acceptance:test-rule-producer",
                "accepted_strategy_version": "manual-rule-only-daily-rank-v1",
                "accepted_policy_version": "foreground-owner-bound-v1",
                "policy_hash": body["policy_hash"],
                "universe_hash": universe_hash,
                "score_configuration_hash": score_hash,
                "formal_oos_allowed": False,
                "production_blend_alpha_bp": 0,
                "promotion_eligible": False,
                "broker_order_allowed": False,
            }
        ),
        encoding="utf-8",
    )
    return clock_path, symbols_path, acceptance_path, score_hash


def _market_db(tmp_path: Path) -> Path:
    path = tmp_path / "market.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            'CREATE TABLE daily_prices ("日期" TEXT, "證券代號" TEXT, "收盤價" TEXT, "成交股數" INTEGER)'
        )
        start = date(2026, 7, 1)
        for offset in range(25):
            session = start + timedelta(days=offset)
            date_key = session.strftime("%Y%m%d")
            connection.executemany(
                "INSERT INTO daily_prices VALUES (?, ?, ?, ?)",
                [
                    (date_key, "2317", str(500 - offset), 1_500_000),
                    (date_key, "2330", str(700 + offset * 2), 1_000_000),
                ],
            )
    os.utime(path, (1, 1))
    return path


def test_produces_clock_bound_hmac_source_without_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_root = tmp_path / "temp"
    root = temp_root / "technical_analysis_development_output"
    root.mkdir(parents=True)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(temp_root))
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY", "test-key")
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_ID", "controlled-store:test")
    clock, symbols, acceptance, score_hash = _clock(tmp_path)
    result = produce_prospective_rule_only_decision(
        development_output_root=root,
        market_db=_market_db(tmp_path),
        clock_manifest_path=clock,
        universe_symbols_json=symbols,
        owner_acceptance_json=acceptance,
        now=datetime(2026, 8, 17, 9, 5, tzinfo=TAIPEI_TIME_ZONE),
    )
    assert result["status"] == "prospective_rule_only_source_created"
    assert result["score_configuration_hash"] == score_hash
    assert result["universe_hash"] == "sha256:" + "5" * 64
    assert result["secret_values_emitted"] is False
    for key in ("decision_output_json", "formal_rule_decision_json", "requests_json", "artifacts_json"):
        assert Path(str(result[key])).is_file()
    artifact_text = Path(str(result["formal_rule_decision_json"])).read_text(encoding="utf-8")
    assert "test-key" not in artifact_text
    requests = json.loads(Path(str(result["requests_json"])).read_text(encoding="utf-8"))
    assert requests[0]["decision_date"] == "2026-08-17"


def test_rejects_before_owner_boundary_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_root = tmp_path / "temp"
    root = temp_root / "technical_analysis_development_output"
    root.mkdir(parents=True)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(temp_root))
    clock, symbols, acceptance, _ = _clock(tmp_path)
    with pytest.raises(ProspectiveRuleOnlyDecisionError, match="outside_taiwan_regular_session"):
        produce_prospective_rule_only_decision(
            development_output_root=root,
            market_db=_market_db(tmp_path),
            clock_manifest_path=clock,
            universe_symbols_json=symbols,
            owner_acceptance_json=acceptance,
            now=datetime(2026, 8, 17, 8, 59, tzinfo=TAIPEI_TIME_ZONE),
        )
    assert not (root / "prospective_formal_rule_only").exists()
