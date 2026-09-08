from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import data_module.formal_rule_source_producer as producer
import data_module.formal_daily_input_producer as formal_daily_producer
from scripts.scheduled import run_formal_input_producer_daily as scheduled_runner
from data_module.prospective_formal_clock import (
    CALENDAR_EVIDENCE_SCHEMA_VERSION,
    PROSPECTIVE_FORMAL_CLOCK_MODE,
    PROSPECTIVE_FORMAL_CLOCK_SCHEMA_VERSION,
    ProspectiveFormalClockError,
    SAME_DAY_PREOPEN_MACHINE_REVALIDATION_REASON,
    build_clock_manifest,
    load_clock_manifest_for_capture,
    payload_hash,
    validate_clock_manifest,
)


TARGET_DAY = date(2026, 9, 8)
PREOPEN = datetime(2026, 9, 7, 23, 45, tzinfo=timezone.utc)
AFTER_PIT = datetime(2026, 9, 8, 0, 45, tzinfo=timezone.utc)
SOURCE_HASH = "sha256:" + "a" * 64
UNIVERSE_HASH = "sha256:" + "b" * 64
CALENDAR = {
    "schema_version": CALENDAR_EVIDENCE_SCHEMA_VERSION,
    "date": TARGET_DAY.isoformat(),
    "is_trading_day": True,
    "reason_code": "twse_holiday_schedule_open",
    "source": "TWSE official holidaySchedule hash-bound cache",
    "source_hash": "sha256:" + "c" * 64,
}


def _seed() -> dict[str, object]:
    value: dict[str, object] = {
        "kind": "cash",
        "cash_bp": 10_000,
        "position_count": 0,
    }
    value["state_hash"] = payload_hash(value)
    return value


def _baseline_clock() -> dict[str, object]:
    return build_clock_manifest(
        {
            "schema_version": PROSPECTIVE_FORMAL_CLOCK_SCHEMA_VERSION,
            "status": "planned",
            "clock_id": "clock:prospective:20260817:test-parent",
            "mode": PROSPECTIVE_FORMAL_CLOCK_MODE,
            "owner_decision_id": "owner:test-policy:20260814:v1",
            "owner_decision_timestamp": "2026-08-14T08:00:00+08:00",
            "activation_trading_day": "2026-08-17",
            "decision_timezone": "Asia/Taipei",
            "decision_time": "09:00:00",
            "pit_decision_time": "08:30:00",
            "activation_calendar_evidence": {
                **CALENDAR,
                "date": "2026-08-17",
            },
            "seed_state": _seed(),
            "virtual_notional_minor_units": 1_000_000,
            "strategy_version": "manual-rule-only-daily-rank-v1",
            "policy_version": "foreground-owner-bound-v1",
            "policy_hash": "sha256:" + "1" * 64,
            "universe_hash": "sha256:" + "2" * 64,
            "source_policy_hash": "sha256:" + "3" * 64,
            "candidate_model_hash": "sha256:" + "4" * 64,
            "candidate_feature_manifest_hash": "sha256:" + "5" * 64,
            "candidate_training_cutoff": "2026-08-13T08:30:00+08:00",
            "calibration_policy_hash": "sha256:" + "6" * 64,
            "evaluation_policy_hash": "sha256:" + "7" * 64,
            "real_money": False,
            "broker_execution": False,
            "historical_backfill_claimed": False,
        }
    )


def _write_baseline(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, object]]:
    bundle = tmp_path / "baseline" / "clock-20260817"
    clock_path = bundle / "clock" / "manifest.json"
    owner_path = bundle / "metadata" / "owner_acceptance.json"
    symbols_path = bundle / "metadata" / "universe_symbols.json"
    clock_path.parent.mkdir(parents=True)
    owner_path.parent.mkdir(parents=True)
    clock = _baseline_clock()
    owner = {
        "schema_version": "prospective-formal-rule-champion-owner-acceptance.v1",
        "decision_id": clock["owner_decision_id"],
        "accepted_strategy_version": clock["strategy_version"],
        "accepted_policy_version": clock["policy_version"],
        "policy_hash": clock["policy_hash"],
        "universe_hash": clock["universe_hash"],
        "score_configuration_hash": "sha256:" + "8" * 64,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "acceptance_source": "owner_message",
    }
    symbols = ["1101", "2330", "6505"]
    clock_path.write_text(json.dumps(clock, ensure_ascii=False), encoding="utf-8")
    owner_path.write_text(json.dumps(owner, ensure_ascii=False), encoding="utf-8")
    symbols_path.write_text(json.dumps(symbols), encoding="utf-8")
    return clock_path, owner_path, symbols_path, owner


def _patch_real_source_checks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    symbols: tuple[str, ...],
) -> None:
    monkeypatch.setattr(
        producer,
        "_load_owner_acceptance",
        lambda _path, _clock: (
            {
                "decision_id": "owner:test-policy:20260814:v1",
                "accepted_strategy_version": "manual-rule-only-daily-rank-v1",
                "accepted_policy_version": "foreground-owner-bound-v1",
                "policy_hash": "sha256:" + "1" * 64,
                "universe_hash": "sha256:" + "2" * 64,
                "score_configuration_hash": "sha256:" + "8" * 64,
                "formal_oos_allowed": False,
                "production_blend_alpha_bp": 0,
                "promotion_eligible": False,
                "broker_order_allowed": False,
                "acceptance_source": "owner_message",
            },
            "sha256:" + "9" * 64,
        ),
    )
    monkeypatch.setattr(
        producer,
        "_official_calendar_evidence",
        lambda **_kwargs: dict(CALENDAR),
    )
    window = SimpleNamespace(
        source_hash=SOURCE_HASH,
        data_as_of_date="2026-09-07",
        max_available_timestamp="2026-09-07T18:10:20+00:00",
        session_dates=["2026-09-05", "2026-09-07"],
    )
    monkeypatch.setattr(
        producer,
        "load_read_only_daily_price_window",
        lambda *_args, **_kwargs: window,
    )
    monkeypatch.setattr(
        producer,
        "rank_rule_only_candidates",
        lambda *_args, **_kwargs: [SimpleNamespace(symbol=s) for s in symbols],
    )
    monkeypatch.setattr(producer, "_universe_hash", lambda _value: UNIVERSE_HASH)
    monkeypatch.setattr(producer, "file_sha256", lambda path: _real_file_hash(path))


def _real_file_hash(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def test_machine_bundle_binds_current_window_policy_and_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_root = tmp_path / "baseline"
    clock_path, owner_path, symbols_path, _ = _write_baseline(tmp_path)
    _patch_real_source_checks(monkeypatch, symbols=("1101", "2330", "6505"))
    market_db = tmp_path / "readonly-market.sqlite"
    market_db.write_bytes(b"readonly market fixture")

    result = producer.produce_current_rule_source_bundle(
        output_root=tmp_path / "publication" / "rule_source",
        market_db=market_db,
        baseline_root=baseline_root,
        calendar_cache_root=tmp_path / "calendar",
        now=PREOPEN,
    )

    assert result["status"] == "rule_source_bundle_created"
    assert result["candidate_only"] is True
    assert result["formal_oos_allowed"] is False
    validated = producer.validate_machine_revalidation_bundle(
        str(result["bundle_root"]),
        market_db=market_db,
        observed=AFTER_PIT,
    )
    assert validated["status"] == "machine_revalidation_verified"
    assert validated["machine_review_identity"] == producer.MACHINE_REVIEW_IDENTITY
    receipt_path = Path(str(result["machine_revalidation_receipt"]))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["machine_review_identity"] == producer.MACHINE_REVIEW_IDENTITY
    assert receipt["source_window_hash"] == SOURCE_HASH
    assert receipt["parent_policy"]["clock_manifest_path"] == str(clock_path)
    assert receipt["parent_policy"]["owner_acceptance_path"] == str(owner_path)
    assert receipt["parent_policy"]["universe_symbols_path"] == str(symbols_path)
    for name, expected in receipt["files"].items():
        child = receipt_path.parents[1] / ("clock/manifest.json" if name == "clock" else f"metadata/{'owner_acceptance.json' if name == 'owner' else 'universe_symbols.json' if name == 'symbols' else 'universe_identity.json'}")
        assert _real_file_hash(child) == expected

    clock = load_clock_manifest_for_capture(
        Path(str(result["clock_manifest"])), now=AFTER_PIT
    )
    assert clock.payload["universe_hash"] == UNIVERSE_HASH
    assert clock.payload["activation_timing_override"]["reason_code"] == (
        SAME_DAY_PREOPEN_MACHINE_REVALIDATION_REASON
    )
    projection, blockers = formal_daily_producer._acceptance_projection(
        Path(str(result["owner_acceptance"])),
        clock=clock,
        market_db=market_db,
        observed=AFTER_PIT,
    )
    assert blockers == []
    assert projection["machine_revalidation"]["status"] == (
        "machine_revalidation_verified"
    )


def test_same_day_bundle_is_not_created_after_preopen_cutoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_root = tmp_path / "baseline"
    _write_baseline(tmp_path)
    _patch_real_source_checks(monkeypatch, symbols=("1101", "2330", "6505"))
    market_db = tmp_path / "readonly-market.sqlite"
    market_db.write_bytes(b"readonly market fixture")

    with pytest.raises(
        producer.FormalRuleSourceWaiting,
        match="same_day_rule_source_preopen_window_missed",
    ):
        producer.produce_current_rule_source_bundle(
            output_root=tmp_path / "publication" / "rule_source",
            market_db=market_db,
            baseline_root=baseline_root,
            calendar_cache_root=tmp_path / "calendar",
            now=AFTER_PIT,
        )
    assert not (tmp_path / "publication").exists()


def test_existing_bundle_child_tamper_is_rejected_on_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_root = tmp_path / "baseline"
    _write_baseline(tmp_path)
    _patch_real_source_checks(monkeypatch, symbols=("1101", "2330", "6505"))
    market_db = tmp_path / "readonly-market.sqlite"
    market_db.write_bytes(b"readonly market fixture")
    result = producer.produce_current_rule_source_bundle(
        output_root=tmp_path / "publication" / "rule_source",
        market_db=market_db,
        baseline_root=baseline_root,
        calendar_cache_root=tmp_path / "calendar",
        now=PREOPEN,
    )
    identity_path = Path(str(result["universe_identity"]))
    identity_path.write_text(identity_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(
        producer.FormalRuleSourceProducerError,
        match="existing_bundle_file_hash_mismatch:identity",
    ):
        producer.produce_current_rule_source_bundle(
            output_root=tmp_path / "publication" / "rule_source",
            market_db=market_db,
            baseline_root=baseline_root,
            calendar_cache_root=tmp_path / "calendar",
            now=PREOPEN,
        )


def test_machine_receipt_tamper_is_rejected_even_when_child_hashes_remain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_root = tmp_path / "baseline"
    _write_baseline(tmp_path)
    _patch_real_source_checks(monkeypatch, symbols=("1101", "2330", "6505"))
    market_db = tmp_path / "readonly-market.sqlite"
    market_db.write_bytes(b"readonly market fixture")
    result = producer.produce_current_rule_source_bundle(
        output_root=tmp_path / "publication" / "rule_source",
        market_db=market_db,
        baseline_root=baseline_root,
        calendar_cache_root=tmp_path / "calendar",
        now=PREOPEN,
    )
    receipt_path = Path(str(result["machine_revalidation_receipt"]))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["machine_review_reason"] = "caller_asserted"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(
        producer.FormalRuleSourceProducerError,
        match="machine_revalidation_receipt_reason_invalid",
    ):
        producer.produce_current_rule_source_bundle(
            output_root=tmp_path / "publication" / "rule_source",
            market_db=market_db,
            baseline_root=baseline_root,
            calendar_cache_root=tmp_path / "calendar",
            now=PREOPEN,
        )


def test_consumer_rechecks_current_source_window_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_root = tmp_path / "baseline"
    _write_baseline(tmp_path)
    _patch_real_source_checks(monkeypatch, symbols=("1101", "2330", "6505"))
    market_db = tmp_path / "readonly-market.sqlite"
    market_db.write_bytes(b"readonly market fixture")
    result = producer.produce_current_rule_source_bundle(
        output_root=tmp_path / "publication" / "rule_source",
        market_db=market_db,
        baseline_root=baseline_root,
        calendar_cache_root=tmp_path / "calendar",
        now=PREOPEN,
    )
    monkeypatch.setattr(
        producer,
        "load_read_only_daily_price_window",
        lambda *_args, **_kwargs: SimpleNamespace(
            source_hash="sha256:" + "d" * 64,
            data_as_of_date="2026-09-07",
            max_available_timestamp="2026-09-07T18:10:20+00:00",
            session_dates=["2026-09-05", "2026-09-07"],
        ),
    )
    with pytest.raises(
        producer.FormalRuleSourceProducerError,
        match="machine_revalidation_current_source_window_hash_mismatch",
    ):
        producer.validate_machine_revalidation_bundle(
            str(result["bundle_root"]),
            market_db=market_db,
            observed=AFTER_PIT,
        )


def test_consumer_rejects_receipt_safety_flag_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_root = tmp_path / "baseline"
    _write_baseline(tmp_path)
    _patch_real_source_checks(monkeypatch, symbols=("1101", "2330", "6505"))
    market_db = tmp_path / "readonly-market.sqlite"
    market_db.write_bytes(b"readonly market fixture")
    result = producer.produce_current_rule_source_bundle(
        output_root=tmp_path / "publication" / "rule_source",
        market_db=market_db,
        baseline_root=baseline_root,
        calendar_cache_root=tmp_path / "calendar",
        now=PREOPEN,
    )
    receipt_path = Path(str(result["machine_revalidation_receipt"]))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["safety"]["broker_order_allowed"] = True
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(
        producer.FormalRuleSourceProducerError,
        match="machine_revalidation_receipt_safety_flags_invalid",
    ):
        producer.validate_machine_revalidation_bundle(
            str(result["bundle_root"]),
            market_db=market_db,
            observed=AFTER_PIT,
        )


def test_machine_clock_cannot_be_downgraded_to_owner_only_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_root = tmp_path / "baseline"
    _write_baseline(tmp_path)
    _patch_real_source_checks(monkeypatch, symbols=("1101", "2330", "6505"))
    market_db = tmp_path / "readonly-market.sqlite"
    market_db.write_bytes(b"readonly market fixture")
    result = producer.produce_current_rule_source_bundle(
        output_root=tmp_path / "publication" / "rule_source",
        market_db=market_db,
        baseline_root=baseline_root,
        calendar_cache_root=tmp_path / "calendar",
        now=PREOPEN,
    )
    owner_path = Path(str(result["owner_acceptance"]))
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    owner["acceptance_source"] = "owner_message"
    owner_path.write_text(json.dumps(owner), encoding="utf-8")
    clock = load_clock_manifest_for_capture(
        Path(str(result["clock_manifest"])), now=AFTER_PIT
    )
    projection, blockers = formal_daily_producer._acceptance_projection(
        owner_path,
        clock=clock,
        market_db=market_db,
        observed=AFTER_PIT,
    )
    assert projection["acceptance_source"] == "owner_message"
    assert blockers == ["machine_revalidation_clock_owner_identity_mismatch"]


def test_scheduled_resolver_requires_machine_receipt_for_machine_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_root = tmp_path / "baseline"
    _write_baseline(tmp_path)
    _patch_real_source_checks(monkeypatch, symbols=("1101", "2330", "6505"))
    market_db = tmp_path / "readonly-market.sqlite"
    market_db.write_bytes(b"readonly market fixture")
    result = producer.produce_current_rule_source_bundle(
        output_root=tmp_path / "publication" / "rule_source",
        market_db=market_db,
        baseline_root=baseline_root,
        calendar_cache_root=tmp_path / "calendar",
        now=PREOPEN,
    )
    monkeypatch.setattr(
        scheduled_runner,
        "_validate_rule_universe_against_market_db",
        lambda **_kwargs: None,
    )
    root = tmp_path / "publication" / "rule_source"
    paths, reason = scheduled_runner._discover_latest_rule_source_paths(
        source_root=root,
        observed=AFTER_PIT,
        market_db=market_db,
    )
    assert paths["FORMAL_DAILY_CLOCK_MANIFEST"] == Path(
        str(result["clock_manifest"])
    ).resolve()
    assert reason == "auto_discovered_latest_verified_bundle"
    Path(str(result["machine_revalidation_receipt"])).unlink()
    paths, reason = scheduled_runner._discover_latest_rule_source_paths(
        source_root=root,
        observed=AFTER_PIT,
        market_db=market_db,
    )
    assert paths == {}
    assert "machine_revalidation_receipt_missing" in reason


def test_machine_override_requires_machine_identity_prefix() -> None:
    manifest = build_clock_manifest(
        {
            "schema_version": PROSPECTIVE_FORMAL_CLOCK_SCHEMA_VERSION,
            "status": "planned",
            "clock_id": "clock:test:machine",
            "mode": PROSPECTIVE_FORMAL_CLOCK_MODE,
            "owner_decision_id": "owner:test",
            "owner_decision_timestamp": "2026-08-14T08:00:00+08:00",
            "activation_trading_day": "2026-08-14",
            "decision_timezone": "Asia/Taipei",
            "decision_time": "09:00:00",
            "pit_decision_time": "08:30:00",
            "activation_calendar_evidence": {
                **CALENDAR,
                "date": "2026-08-14",
            },
            "seed_state": _seed(),
            "virtual_notional_minor_units": 1,
            "strategy_version": "rule",
            "policy_version": "policy",
            "policy_hash": "sha256:" + "1" * 64,
            "universe_hash": "sha256:" + "2" * 64,
            "source_policy_hash": "sha256:" + "3" * 64,
            "candidate_model_hash": "sha256:" + "4" * 64,
            "candidate_feature_manifest_hash": "sha256:" + "5" * 64,
            "candidate_training_cutoff": "2026-08-13T08:30:00+08:00",
            "calibration_policy_hash": "sha256:" + "6" * 64,
            "evaluation_policy_hash": "sha256:" + "7" * 64,
            "real_money": False,
            "broker_execution": False,
            "historical_backfill_claimed": False,
            "activation_timing_override": {
                "schema_version": "prospective-same-day-preopen-owner-override.v1",
                "owner_override_id": "owner-override:untrusted",
                "owner_override_timestamp": "2026-08-14T07:45:00+08:00",
                "reason_code": SAME_DAY_PREOPEN_MACHINE_REVALIDATION_REASON,
                "activation_trading_day": "2026-08-14",
                "historical_backfill_allowed": False,
                "same_day_preopen_only": True,
            },
        }
    )
    with pytest.raises(ProspectiveFormalClockError, match="identity is invalid"):
        validate_clock_manifest(
            manifest,
            now=datetime(2026, 8, 14, 0, 0, tzinfo=timezone.utc),
        )
