from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import os
import json
from pathlib import Path
import sqlite3
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
POST_OPEN = datetime(2026, 9, 8, 1, 15, tzinfo=timezone.utc)
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


def _patch_policy_and_calendar_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the market window and ranking on the real SQLite implementation."""

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


def _patch_frozen_machine_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the real frozen Rule champion score identity for E2E decision tests."""

    score_hash = (
        "sha256:1a11086fb3551ba24acb58e4f880eafa49c1e49fc87187ff8e7be02999e891c4"
    )
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
                "score_configuration_hash": score_hash,
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


def _real_file_hash(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _real_market_db(tmp_path: Path) -> Path:
    """建立足夠 20-session history 的 SQLite read-only fixture。"""

    path = tmp_path / "real-market.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            'CREATE TABLE daily_prices ("日期" TEXT, "證券代號" TEXT, "收盤價" TEXT, "成交股數" INTEGER)'
        )
        start = date(2026, 8, 1)
        symbols = ("1101", "2330", "6505")
        rows: list[tuple[str, str, str, int]] = []
        for offset in range(25):
            session = start + timedelta(days=offset)
            date_key = session.strftime("%Y%m%d")
            for index, symbol in enumerate(symbols):
                close = 100 + index * 50 + offset * (index + 1)
                volume = 1_000_000 + index * 100_000 + offset * 1_000
                rows.append((date_key, symbol, str(close), volume))
        connection.executemany(
            "INSERT INTO daily_prices VALUES (?, ?, ?, ?)",
            rows,
        )
    # The fixture represents a source completed before PREOPEN.  The loader
    # derives max_available_timestamp from the DB mtime, so pin it explicitly.
    os.utime(path, (1, 1))
    return path


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


def test_machine_consumer_rejects_receipt_observed_after_preopen_cutoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """下游 validator 也必須拒絕盤後偽造的 preopen receipt。"""

    baseline_root = tmp_path / "baseline"
    _write_baseline(tmp_path)
    _patch_policy_and_calendar_only(monkeypatch)
    market_db = _real_market_db(tmp_path)
    result = producer.produce_current_rule_source_bundle(
        output_root=tmp_path / "publication" / "rule_source",
        market_db=market_db,
        baseline_root=baseline_root,
        calendar_cache_root=tmp_path / "calendar",
        now=PREOPEN,
    )
    receipt_path = Path(str(result["machine_revalidation_receipt"]))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["observed_at"] = POST_OPEN.isoformat(timespec="microseconds")
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(
        producer.FormalRuleSourceProducerError,
        match="machine_revalidation_observed_after_preopen_cutoff",
    ):
        producer.validate_machine_revalidation_bundle(
            str(result["bundle_root"]),
            market_db=market_db,
            observed=POST_OPEN,
        )


def test_machine_bundle_uses_real_sqlite_window_and_ranker_before_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """首建與盤中重用都重跑真實 SQLite T-1 window/ranker。"""

    baseline_root = tmp_path / "baseline"
    _write_baseline(tmp_path)
    _patch_policy_and_calendar_only(monkeypatch)
    market_db = _real_market_db(tmp_path)
    output_root = tmp_path / "publication" / "rule_source"

    prepublished = producer.produce_current_rule_source_bundle(
        output_root=output_root,
        market_db=market_db,
        baseline_root=baseline_root,
        calendar_cache_root=tmp_path / "calendar",
        now=PREOPEN,
    )
    identity = json.loads(
        Path(str(prepublished["universe_identity"])).read_text(encoding="utf-8")
    )
    assert identity["data_as_of_date"] < TARGET_DAY.isoformat()
    assert len(identity["session_dates"]) == 25
    assert identity["candidate_count"] == 3
    assert identity["source_window_hash"].startswith("sha256:")

    reused = producer.produce_current_rule_source_bundle(
        output_root=output_root,
        market_db=market_db,
        baseline_root=baseline_root,
        calendar_cache_root=tmp_path / "calendar",
        now=POST_OPEN,
    )
    assert reused["status"] == "rule_source_bundle_reused"
    assert reused["bundle_root"] == prepublished["bundle_root"]
    validated = producer.validate_machine_revalidation_bundle(
        str(reused["bundle_root"]),
        market_db=market_db,
        observed=POST_OPEN,
    )
    assert validated["status"] == "machine_revalidation_verified"
    assert validated["source_window_hash"] == identity["source_window_hash"]


def test_post_capture_future_append_keeps_t1_replay_and_reports_db_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB 追加當日行情不應使相同 T-1 decision source 失效。"""

    baseline_root = tmp_path / "baseline"
    _write_baseline(tmp_path)
    _patch_policy_and_calendar_only(monkeypatch)
    market_db = _real_market_db(tmp_path)
    output_root = tmp_path / "publication" / "rule_source"

    prepublished = producer.produce_current_rule_source_bundle(
        output_root=output_root,
        market_db=market_db,
        baseline_root=baseline_root,
        calendar_cache_root=tmp_path / "calendar",
        now=PREOPEN,
    )
    assert prepublished["source_window"] is not None
    identity = json.loads(
        Path(str(prepublished["universe_identity"])).read_text(encoding="utf-8")
    )

    # Simulate the normal updater appending today's rows after the pre-open
    # capture.  The mtime remains before the consumer observation, while the
    # strict ``date < decision_session`` query remains byte-identical.
    with sqlite3.connect(market_db) as connection:
        connection.executemany(
            'INSERT INTO daily_prices VALUES (?, ?, ?, ?)',
            [
                ("20260908", symbol, str(200 + index), 2_000_000 + index)
                for index, symbol in enumerate(("1101", "2330", "6505"))
            ],
        )
    append_time = AFTER_PIT.timestamp()
    os.utime(market_db, (append_time, append_time))

    validated = producer.validate_machine_revalidation_bundle(
        str(prepublished["bundle_root"]),
        market_db=market_db,
        observed=POST_OPEN,
    )
    assert validated["status"] == "machine_revalidation_verified"
    assert validated["source_window_persisted"] is True
    assert validated["source_window_hash"] == identity["source_window_hash"]
    assert validated["market_db_file_hash_matches_capture"] is False
    assert validated["market_db_hash_semantics"].startswith(
        "capture_time_diagnostic_only"
    )


def test_v3_captured_window_drives_real_decision_after_live_row_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真 prospective decision 必須使用 v3 captured rows，不重讀 mutated DB。"""

    baseline_root = tmp_path / "baseline"
    _write_baseline(tmp_path)
    _patch_frozen_machine_policy(monkeypatch)
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY", "test-key")
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_ID", "controlled-store:test")
    market_db = _real_market_db(tmp_path)
    output_root = tmp_path / "publication" / "rule_source"

    captured = producer.produce_current_rule_source_bundle(
        output_root=output_root,
        market_db=market_db,
        baseline_root=baseline_root,
        calendar_cache_root=tmp_path / "calendar",
        now=PREOPEN,
    )
    assert captured["source_window"] is not None
    captured_window = producer.load_verified_rule_source_window(
        str(captured["bundle_root"]),
        market_db=market_db,
        observed=POST_OPEN,
    )
    from development_module.manual_rule_only_decision import (  # noqa: PLC0415
        load_read_only_daily_price_window,
        rank_rule_only_candidates,
    )

    symbols = tuple(json.loads(
        Path(str(captured["universe_symbols"])).read_text(encoding="utf-8")
    ))
    captured_rank = rank_rule_only_candidates(
        captured_window,
        eligible_symbols=symbols,
    )[0].symbol

    # Change one already-captured T-1 close after pre-open.  The live rank
    # must move, while the v3 decision remains bound to the immutable source.
    with sqlite3.connect(market_db) as connection:
        connection.execute(
            'UPDATE daily_prices SET "收盤價" = ? WHERE "日期" = ? AND "證券代號" = ?',
            ("10000", "20260825", "1101"),
        )
    os.utime(market_db, (AFTER_PIT.timestamp(), AFTER_PIT.timestamp()))
    live_window = load_read_only_daily_price_window(
        market_db,
        decision_session=TARGET_DAY,
    )
    live_rank = rank_rule_only_candidates(
        live_window,
        eligible_symbols=symbols,
    )[0].symbol
    assert live_rank != captured_rank

    decision_root = tmp_path / "development" / "technical_analysis_development_output"
    decision_root.mkdir(parents=True)
    pinned_clock_path = Path(str(captured["clock_manifest"])).resolve()
    pinned_clock = load_clock_manifest_for_capture(
        pinned_clock_path,
        now=POST_OPEN,
    )
    paths = formal_daily_producer.DailyFormalInputPaths(
        output_root=tmp_path / "candidate",
        development_output_root=decision_root,
        market_db=market_db,
        clock_manifest=pinned_clock_path,
        universe_symbols=Path(str(captured["universe_symbols"])),
        owner_acceptance=Path(str(captured["owner_acceptance"])),
    )
    decision = formal_daily_producer._produce_rule_candidate(
        paths=paths,
        output_root=paths.output_root,
        clock=pinned_clock,
        now=POST_OPEN.astimezone(producer._TAIPEI),
        daily_rule_lineage={
            "clock_id": pinned_clock.clock_id,
            "clock_manifest_hash": pinned_clock.manifest_hash,
            "activation_trading_day": pinned_clock.activation_trading_day.isoformat(),
            "universe_hash": pinned_clock.payload["universe_hash"],
            "policy_hash": pinned_clock.payload["policy_hash"],
            "source_window_hash": captured_window.source_hash,
            "source_bundle_path": str(Path(str(captured["bundle_root"])).resolve()),
        },
    )
    assert decision["selected_symbol"] == captured_rank
    assert decision["decision_source_window_mode"] == "immutable_captured_window"
    assert decision["decision_source_window_hash"] == captured_window.source_hash


def test_legacy_v2_source_window_mutation_is_rejected_before_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """沒有 persisted rows 的 v2 仍須拒絕 live T-1 變更。"""

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
    receipt = json.loads(
        Path(str(result["machine_revalidation_receipt"])).read_text(
            encoding="utf-8"
        )
    )
    assert receipt["schema_version"] == producer.LEGACY_MACHINE_RULE_SOURCE_PRODUCER_SCHEMA_VERSION
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
        producer.load_verified_rule_source_window(
            str(result["bundle_root"]),
            market_db=market_db,
            observed=AFTER_PIT,
        )


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("future", "machine_revalidation_source_payload_record_outside_t1_window"),
        ("duplicate", "machine_revalidation_source_payload_duplicate_symbol_date"),
    ],
)
def test_persisted_window_rejects_future_or_duplicate_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    expected_error: str,
) -> None:
    """window 內的 row identity 也要驗證，不能只驗 envelope 自身 hash。"""

    baseline_root = tmp_path / "baseline"
    _write_baseline(tmp_path)
    _patch_policy_and_calendar_only(monkeypatch)
    market_db = _real_market_db(tmp_path)
    result = producer.produce_current_rule_source_bundle(
        output_root=tmp_path / "publication" / "rule_source",
        market_db=market_db,
        baseline_root=baseline_root,
        calendar_cache_root=tmp_path / "calendar",
        now=PREOPEN,
    )
    source_path = Path(str(result["source_window"]))
    receipt_path = Path(str(result["machine_revalidation_receipt"]))
    envelope = json.loads(source_path.read_text(encoding="utf-8"))
    source_payload = dict(envelope["source_payload"])
    records = list(source_payload["records"])
    if mutation == "future":
        records[0] = {**records[0], "日期": "20260908"}
    else:
        records.append(dict(records[0]))
    source_payload["records"] = records
    envelope["source_payload"] = source_payload
    envelope["source_window_hash"] = producer.sha256_identifier(source_payload)
    source_path.write_bytes(producer._canonical_file_bytes(envelope))

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["source_window_hash"] = envelope["source_window_hash"]
    receipt["source_window_file_hash"] = producer._bytes_hash(
        producer._canonical_file_bytes(envelope)
    )
    receipt_path.write_bytes(producer._canonical_file_bytes(receipt))

    with pytest.raises(
        producer.FormalRuleSourceProducerError,
        match=expected_error,
    ):
        producer.validate_machine_revalidation_bundle(
            str(result["bundle_root"]),
            market_db=market_db,
            observed=POST_OPEN,
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


def test_postopen_retry_reuses_prepublished_bundle_without_new_clock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """盤中只能消費盤前已預發布的 machine source。"""

    baseline_root = tmp_path / "baseline"
    _write_baseline(tmp_path)
    _patch_real_source_checks(monkeypatch, symbols=("1101", "2330", "6505"))
    market_db = tmp_path / "readonly-market.sqlite"
    market_db.write_bytes(b"readonly market fixture")
    output_root = tmp_path / "publication" / "rule_source"

    prepublished = producer.produce_current_rule_source_bundle(
        output_root=output_root,
        market_db=market_db,
        baseline_root=baseline_root,
        calendar_cache_root=tmp_path / "calendar",
        now=PREOPEN,
    )
    reused = producer.produce_current_rule_source_bundle(
        output_root=output_root,
        market_db=market_db,
        baseline_root=baseline_root,
        calendar_cache_root=tmp_path / "calendar",
        now=POST_OPEN,
    )

    assert prepublished["status"] == "rule_source_bundle_created"
    assert prepublished["rule_source_phase"] == (
        "preopen_machine_source_prepublication"
    )
    assert reused["status"] == "rule_source_bundle_reused"
    assert reused["rule_source_phase"] == "postopen_machine_source_reuse"
    assert reused["write_performed"] is False
    assert reused["bundle_root"] == prepublished["bundle_root"]
    assert reused["clock_manifest"] == prepublished["clock_manifest"]
    assert reused["clock_manifest_hash"] == prepublished["clock_manifest_hash"]
    assert reused["consumer_validation"]["status"] == "machine_revalidation_verified"
    assert len(list(output_root.glob("clock-*/clock/manifest.json"))) == 1


def test_postopen_first_attempt_is_blocked_without_prepublished_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """盤中沒有盤前來源時不能臨時建立同日 clock。"""

    baseline_root = tmp_path / "baseline"
    _write_baseline(tmp_path)
    _patch_real_source_checks(monkeypatch, symbols=("1101", "2330", "6505"))
    market_db = tmp_path / "readonly-market.sqlite"
    market_db.write_bytes(b"readonly market fixture")

    with pytest.raises(
        producer.FormalRuleSourceWaiting,
        match="same_day_rule_source_window_missed",
    ):
        producer.produce_current_rule_source_bundle(
            output_root=tmp_path / "publication" / "rule_source",
            market_db=market_db,
            baseline_root=baseline_root,
            calendar_cache_root=tmp_path / "calendar",
            now=POST_OPEN,
        )
    assert not (tmp_path / "publication").exists()


def test_scheduled_rule_wrapper_creates_preopen_then_reuses_postopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """公開 scheduler 邊界會保留同一 machine bundle 供盤中 Rule consumer。"""

    baseline_root = tmp_path / "baseline"
    _write_baseline(tmp_path)
    _patch_policy_and_calendar_only(monkeypatch)
    market_db = _real_market_db(tmp_path)
    output_root = tmp_path / "publication" / "rule_source"
    monkeypatch.setenv("FORMAL_DAILY_RULE_SOURCE_ROOT", str(output_root))
    monkeypatch.setenv("FORMAL_DAILY_MARKET_DB", str(market_db))
    monkeypatch.setenv("FORMAL_DAILY_RULE_BASELINE_ROOT", str(baseline_root))
    monkeypatch.setenv(
        "FORMAL_DAILY_CALENDAR_CACHE_ROOT",
        str(tmp_path / "calendar"),
    )
    # Public production is repo-output constrained.  This test keeps the
    # scheduler call isolated while retaining that guard in the real entrypoint.
    monkeypatch.setattr(
        producer,
        "_validated_repo_output_root",
        lambda output, _repo: output.expanduser().resolve(),
    )

    monkeypatch.setattr(
        producer,
        "_normalise_observed",
        lambda _value: (PREOPEN, PREOPEN.astimezone(producer._TAIPEI)),
    )
    first_status, first_exit = producer.run_from_environment()
    assert first_exit == 0
    assert first_status["status"] == "rule_source_bundle_created"
    assert first_status["rule_source_phase"] == (
        "preopen_machine_source_prepublication"
    )

    monkeypatch.setattr(
        producer,
        "_normalise_observed",
        lambda _value: (POST_OPEN, POST_OPEN.astimezone(producer._TAIPEI)),
    )
    second_status, second_exit = producer.run_from_environment()
    assert second_exit == 0
    assert second_status["status"] == "rule_source_bundle_reused"
    assert second_status["rule_source_phase"] == "postopen_machine_source_reuse"
    assert second_status["write_performed"] is False
    assert second_status["clock_manifest"] == first_status["clock_manifest"]
    assert second_status["consumer_validation"]["status"] == (
        "machine_revalidation_verified"
    )
    status_path = output_root / "scheduler" / "rule_source_latest_status.json"
    persisted = json.loads(status_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "rule_source_bundle_reused"


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
