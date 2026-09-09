from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import shutil
from zoneinfo import ZoneInfo

import pytest

import data_module.formal_rule_source_producer as formal_rule_source_producer

from data_module.formal_common_identity import (
    FormalCommonIdentityError,
    build_formal_common_identity_manifest,
    read_formal_common_identity_manifest,
    write_immutable_formal_common_identity_manifest,
    _read_and_validate_receipt,
)
from data_module.formal_daily_input_producer import (
    DailyFormalInputPaths,
    _produce_formal_ledger_candidate,
    _produce_rule_candidate,
)
from data_module.formal_controlled_handoff import build_formal_controlled_handoff_plan
from data_module.prospective_formal_clock import (
    file_sha256,
    load_clock_manifest_for_capture,
    payload_hash,
)
from tests.test_formal_daily_input_producer import (
    _AdjacentTradingCalendar,
    _candidate_paths,
    _paper_sources,
)
from tests.test_prospective_rule_only_decision import _clock, _market_db
from tests.test_formal_pit_sector_publisher import _ready_handoff
from data_module.formal_pit_sector_publisher import publish_formal_pit_sector_sidecar
from scripts import inspect_ml_formal_input_readiness


TAIPEI = ZoneInfo("Asia/Taipei")
LEDGER_INPUT = "causal_non_cash_portfolio_ledger"
RULE_INPUT = "formal_rule_champion_snapshot_history"


def _machine_rule_source(
    tmp_path: Path,
    *,
    clock_path: Path,
    symbols_path: Path,
    acceptance_path: Path,
    market_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, object, dict[str, object]]:
    """建立可由 daily producer 精確重播的 machine Rule source bundle。"""

    baseline_bundle = tmp_path / "rule-baseline" / "clock-20260817"
    baseline_clock = baseline_bundle / "clock" / "manifest.json"
    baseline_owner = baseline_bundle / "metadata" / "owner_acceptance.json"
    baseline_symbols = baseline_bundle / "metadata" / "universe_symbols.json"
    baseline_clock.parent.mkdir(parents=True)
    baseline_owner.parent.mkdir(parents=True)
    shutil.copyfile(clock_path, baseline_clock)
    shutil.copyfile(acceptance_path, baseline_owner)
    shutil.copyfile(symbols_path, baseline_symbols)

    monkeypatch.setattr(
        formal_rule_source_producer,
        "_official_calendar_evidence",
        lambda **_kwargs: {
            "schema_version": "official-trading-calendar-evidence.v1",
            "date": "2026-08-17",
            "is_trading_day": True,
            "reason_code": "twse_holiday_schedule_open",
            "source": "TWSE holidaySchedule; TPEX mktCalendar",
            "source_hash": "sha256:" + "c" * 64,
        },
    )
    captured = formal_rule_source_producer.produce_current_rule_source_bundle(
        output_root=tmp_path / "rule-source-publication",
        market_db=market_path,
        baseline_root=baseline_bundle.parent,
        calendar_cache_root=tmp_path / "calendar-cache",
        now=datetime(2026, 8, 17, 8, 0, tzinfo=TAIPEI),
    )
    bundle_path = Path(str(captured["bundle_root"])).resolve()
    machine_clock_path = Path(str(captured["clock_manifest"])).resolve()
    machine_clock = load_clock_manifest_for_capture(
        machine_clock_path,
        now=datetime(2026, 8, 19, 9, 5, tzinfo=TAIPEI),
    )
    source_window = formal_rule_source_producer.load_verified_rule_source_window(
        bundle_path,
        market_db=market_path,
        observed=datetime(2026, 8, 19, 9, 5, tzinfo=TAIPEI),
    )
    lineage: dict[str, object] = {
        "clock_id": machine_clock.clock_id,
        "clock_manifest_hash": machine_clock.manifest_hash,
        "activation_trading_day": machine_clock.activation_trading_day.isoformat(),
        "universe_hash": machine_clock.payload["universe_hash"],
        "source_window_hash": source_window.source_hash,
        "policy_hash": machine_clock.payload["policy_hash"],
        "source_bundle_path": str(bundle_path),
    }
    return (
        machine_clock_path,
        bundle_path,
        machine_clock,
        lineage,
    )


def _write_generic_receipt(
    path: Path,
    *,
    input_name: str,
    result: dict[str, object],
    observed: datetime,
) -> Path:
    body: dict[str, object] = {
        "schema_version": "formal-input-daily-source-receipt.v1",
        "input": input_name,
        "producer": "test.formal_common_identity",
        "observed_at": observed.isoformat(),
        "result": result,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "writes_formal_controlled_paths": False,
        "historical_backfill_claimed": False,
    }
    path.write_text(
        json.dumps({**body, "receipt_hash": payload_hash(body)}),
        encoding="utf-8",
    )
    return path


def _common_clock(clock_path: Path, observed: datetime) -> dict[str, object]:
    clock = load_clock_manifest_for_capture(clock_path, now=observed)
    return {
        "path": str(clock_path.resolve()),
        "file_hash": file_sha256(clock_path),
        "clock_id": clock.clock_id,
        "clock_manifest_hash": clock.manifest_hash,
        "activation_trading_day": clock.activation_trading_day.isoformat(),
        "policy_hash": clock.payload["policy_hash"],
        "universe_hash": clock.payload["universe_hash"],
        "scope": "cumulative_portfolio_state",
    }


def test_generic_receipt_rejects_future_observation_and_missing_source_binding(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    observed = datetime(2026, 9, 8, 10, 0, tzinfo=ZoneInfo("UTC"))
    receipt = _write_generic_receipt(
        tmp_path / "receipt.json",
        input_name=LEDGER_INPUT,
        result={
            "manifest_path": str(source.resolve()),
            "file_hash": file_sha256(source),
            "consumer_verified": True,
        },
        observed=datetime(2099, 1, 1, tzinfo=ZoneInfo("UTC")),
    )

    with pytest.raises(
        FormalCommonIdentityError,
        match="receipt observed_at is after observed",
    ):
        _read_and_validate_receipt(
            receipt,
            input_name=LEDGER_INPUT,
            source_path=source,
            observed=observed,
        )


def test_real_ledger_receipt_rejects_valid_source_b_with_stale_source_hash(
    tmp_path: Path,
) -> None:
    clock_path, _symbols_path, _acceptance_path, _ = _clock(tmp_path)
    snapshots_path, fills_path = _paper_sources(tmp_path)
    paths = _candidate_paths(
        tmp_path,
        clock_path=clock_path,
        snapshots_path=snapshots_path,
        fills_path=fills_path,
    )
    paths.output_root.mkdir(parents=True)
    observed = datetime(2026, 8, 19, 9, 5, tzinfo=TAIPEI)
    result = _produce_formal_ledger_candidate(
        paths=paths,
        output_root=paths.output_root,
        observed=observed,
        calendar=_AdjacentTradingCalendar(tmp_path / "calendar.sqlite"),
    )
    source_a = Path(str(result["manifest_path"])).resolve()
    source_b = tmp_path / "valid-source-b" / "manifest.json"
    source_b.parent.mkdir()
    shutil.copyfile(source_a, source_b)
    shutil.copyfile(
        source_a.parent / "portfolio_ledger.sqlite",
        source_b.parent / "portfolio_ledger.sqlite",
    )
    # The ledger consumer accepts insignificant JSON whitespace, so B remains
    # a valid formal ledger while its source file bytes (and file hash) differ.
    source_b.write_bytes(source_b.read_bytes() + b"\n")
    from data_module.formal_portfolio_ledger import load_formal_portfolio_state_ledger

    load_formal_portfolio_state_ledger(source_b)

    original_receipt = json.loads(
        Path(str(result["receipt_path"])).read_text(encoding="utf-8")
    )
    swapped_result = dict(original_receipt["result"])
    swapped_result["manifest_path"] = str(source_b.resolve())
    swapped_receipt_body = dict(original_receipt)
    swapped_receipt_body["result"] = swapped_result
    swapped_receipt_body.pop("receipt_hash", None)
    swapped_receipt = tmp_path / "swapped-receipt.json"
    swapped_receipt.write_text(
        json.dumps(
            {
                **swapped_receipt_body,
                "receipt_hash": payload_hash(swapped_receipt_body),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        FormalCommonIdentityError,
        match="manifest_file_hash does not match source file",
    ):
        _read_and_validate_receipt(
            swapped_receipt,
            input_name=LEDGER_INPUT,
            source_path=source_b,
            observed=observed,
            common_clock=_common_clock(clock_path, observed),
        )


def test_real_ledger_receipt_binds_recorded_portfolio_clock_fields(
    tmp_path: Path,
) -> None:
    clock_path, _symbols_path, _acceptance_path, _ = _clock(tmp_path)
    snapshots_path, fills_path = _paper_sources(tmp_path)
    paths = _candidate_paths(
        tmp_path,
        clock_path=clock_path,
        snapshots_path=snapshots_path,
        fills_path=fills_path,
    )
    paths.output_root.mkdir(parents=True)
    observed = datetime(2026, 8, 19, 9, 5, tzinfo=TAIPEI)
    result = _produce_formal_ledger_candidate(
        paths=paths,
        output_root=paths.output_root,
        observed=observed,
        calendar=_AdjacentTradingCalendar(tmp_path / "calendar.sqlite"),
    )
    receipt_payload = json.loads(
        Path(str(result["receipt_path"])).read_text(encoding="utf-8")
    )
    receipt_payload["result"]["portfolio_clock_id"] = "clock:wrong-valid-clock"
    receipt_body = dict(receipt_payload)
    receipt_body.pop("receipt_hash", None)
    wrong_receipt = tmp_path / "wrong-clock-receipt.json"
    wrong_receipt.write_text(
        json.dumps(
            {**receipt_body, "receipt_hash": payload_hash(receipt_body)}
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        FormalCommonIdentityError,
        match="portfolio_clock_id does not match common portfolio clock",
    ):
        _read_and_validate_receipt(
            wrong_receipt,
            input_name=LEDGER_INPUT,
            source_path=Path(str(result["manifest_path"])),
            observed=observed,
            common_clock=_common_clock(clock_path, observed),
        )


def test_real_rule_receipt_binds_daily_clock_and_source_window_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock_path, symbols_path, acceptance_path, _ = _clock(tmp_path)
    market_path = _market_db(tmp_path)
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY", "test-key")
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_ID", "controlled-store:test")
    output_root = tmp_path / "rule-output"
    development_root = tmp_path / "technical_analysis_development_output"
    output_root.mkdir()
    development_root.mkdir()
    observed = datetime(2026, 8, 19, 9, 5, tzinfo=TAIPEI)
    (
        machine_clock_path,
        _machine_bundle_path,
        machine_clock,
        lineage,
    ) = _machine_rule_source(
        tmp_path,
        clock_path=clock_path,
        symbols_path=symbols_path,
        acceptance_path=acceptance_path,
        market_path=market_path,
        monkeypatch=monkeypatch,
    )
    lineage = {
        **lineage,
    }
    paths = DailyFormalInputPaths(
        output_root=output_root,
        development_output_root=development_root,
        market_db=market_path,
        clock_manifest=machine_clock_path,
        universe_symbols=Path(
            str(
                _machine_bundle_path
                / "metadata"
                / "universe_symbols.json"
            )
        ),
        owner_acceptance=Path(
            str(
                _machine_bundle_path
                / "metadata"
                / "owner_acceptance.json"
            )
        ),
    )
    result = _produce_rule_candidate(
        paths=paths,
        output_root=output_root,
        clock=machine_clock,
        now=observed,
        daily_rule_lineage=lineage,
    )
    evidence = _read_and_validate_receipt(
        Path(str(result["receipt_path"])),
        input_name=RULE_INPUT,
        source_path=Path(str(result["formal_manifest_path"])),
        observed=observed,
        daily_rule_lineage=lineage,
    )

    assert evidence["source_file_hash"] == file_sha256(
        Path(str(result["formal_manifest_path"]))
    )
    assert evidence["daily_rule_binding"] == {
        "clock_id": lineage["clock_id"],
        "clock_manifest_hash": lineage["clock_manifest_hash"],
        "activation_trading_day": lineage["activation_trading_day"],
        "universe_hash": lineage["universe_hash"],
        "source_window_hash": lineage["source_window_hash"],
        "policy_hash": lineage["policy_hash"],
    }


def test_real_three_source_identity_replays_through_exact_consumers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """三個 producer receipt 以同一組 exact source 建立並重讀 identity。"""

    clock_path, symbols_path, acceptance_path, _ = _clock(tmp_path)
    market_path = _market_db(tmp_path)
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY", "test-key")
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_ID", "controlled-store:test")
    observed = datetime(2026, 9, 8, 2, 0, tzinfo=ZoneInfo("UTC"))
    decision = datetime(2026, 8, 19, 9, 5, tzinfo=TAIPEI)

    (
        machine_clock_path,
        machine_bundle_path,
        machine_clock,
        rule_lineage,
    ) = _machine_rule_source(
        tmp_path,
        clock_path=clock_path,
        symbols_path=symbols_path,
        acceptance_path=acceptance_path,
        market_path=market_path,
        monkeypatch=monkeypatch,
    )

    snapshots_path, fills_path = _paper_sources(tmp_path / "ledger")
    ledger_paths = _candidate_paths(
        tmp_path / "ledger",
        clock_path=machine_clock_path,
        snapshots_path=snapshots_path,
        fills_path=fills_path,
    )
    ledger_paths.output_root.mkdir(parents=True)
    ledger_result = _produce_formal_ledger_candidate(
        paths=ledger_paths,
        output_root=ledger_paths.output_root,
        observed=decision,
        calendar=_AdjacentTradingCalendar(tmp_path / "ledger-calendar.sqlite"),
    )

    rule_output = tmp_path / "rule-output"
    rule_development = tmp_path / "technical_analysis_development_output"
    rule_output.mkdir()
    rule_development.mkdir()
    rule_result = _produce_rule_candidate(
        paths=DailyFormalInputPaths(
            output_root=rule_output,
            development_output_root=rule_development,
            market_db=market_path,
            clock_manifest=machine_clock_path,
            universe_symbols=machine_bundle_path / "metadata" / "universe_symbols.json",
            owner_acceptance=machine_bundle_path / "metadata" / "owner_acceptance.json",
        ),
        output_root=rule_output,
        clock=machine_clock,
        now=decision,
        daily_rule_lineage=rule_lineage,
    )

    pit_root = tmp_path / "pit"
    pit_root.mkdir()
    _archive_root, handoff_path, denominator_path, pit_decision, _candidate_root = (
        _ready_handoff(pit_root, monkeypatch, decision_hour=9)
    )
    pit_result = publish_formal_pit_sector_sidecar(
        handoff_path=handoff_path,
        denominator_path=denominator_path,
        publication_root=tmp_path / "pit-formal",
        decision_at=pit_decision,
        now=pit_decision,
    )
    assert pit_result["formal_ready"] is True
    # The PIT fixture uses its own controlled store for its upstream archive;
    # the Rule consumer must read the Rule receipt under the Rule store that
    # produced the source.
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY", "test-key")
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_ID", "controlled-store:test")

    source_paths = {
        "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH": Path(
            str(ledger_result["manifest_path"])
        ),
        "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH": Path(
            str(rule_result["formal_manifest_path"])
        ),
        "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH": Path(
            str(pit_result["sidecar_path"])
        ),
    }
    receipt_paths = {
        "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH": Path(
            str(ledger_result["receipt_path"])
        ),
        "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH": Path(
            str(rule_result["receipt_path"])
        ),
        "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH": Path(
            str(pit_result["receipt_path"])
        ),
    }
    identity = build_formal_common_identity_manifest(
        source_paths=source_paths,
        source_receipt_paths=receipt_paths,
        portfolio_clock_manifest=machine_clock_path,
        market_db=market_path,
        output_root=tmp_path / "identity-consumer",
        development_output_root=tmp_path / "technical_analysis_development_output-identity",
        training_as_of=observed.isoformat(),
        observed=observed,
        daily_rule_lineage=rule_lineage,
    )
    identity_path = tmp_path / "identity.json"
    write_immutable_formal_common_identity_manifest(identity_path, identity)
    replay = read_formal_common_identity_manifest(
        identity_path,
        source_paths=source_paths,
        portfolio_clock_manifest=machine_clock_path,
        market_db=market_path,
        output_root=tmp_path / "identity-consumer",
        development_output_root=tmp_path / "identity-development",
        training_as_of=observed.isoformat(),
        observed=observed,
        verify_consumers=True,
    )

    assert replay["formal_ready_input_count"] == 3
    assert replay["formal_consumer_compatible_count"] == 3
    assert replay["candidate_only"] is True
    assert replay["promotion_eligible"] is False

    handoff = build_formal_controlled_handoff_plan(
        market_db=market_path,
        training_as_of=observed.isoformat(),
        output_root=tmp_path / "handoff-consumer",
        development_output_root=tmp_path / "handoff-development",
        now=observed,
        environment={
            **{
                name: str(tmp_path / "stale-current" / f"{index}.json")
                for index, name in enumerate(
                    (
                        "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH",
                        "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH",
                        "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH",
                    )
                )
            },
            "RULE_CHAMPION_CONTROLLED_STORE_ID": "controlled-store:test",
            "RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY": "test-key",
        },
        platform_name="posix",
        proposed_paths=source_paths,
        proposed_clock_manifest=machine_clock_path,
        proposed_identity_manifest=identity_path,
    )
    assert handoff["status"] == "ready_for_root_review"
    proposed = handoff["proposed_controlled_configuration"]
    assert isinstance(proposed, dict)
    assert proposed["blockers"] == []
    identity_evidence = proposed["identity_evidence"]
    assert isinstance(identity_evidence, dict)
    assert identity_evidence["status"] == "producer_and_consumer_verified"

    # The operational Formal inspector must consume the exact producer
    # artifacts above, rather than merely trusting the common identity flags.
    # Keep this in the isolated fixture root so the deployed v6 environment is
    # never changed by the test process.
    for environment_name, source_path in source_paths.items():
        monkeypatch.setenv(environment_name, str(source_path))
    inspector_report = inspect_ml_formal_input_readiness.build_readiness_report(
        output_root=tmp_path / "pit-formal",
        training_as_of=observed.isoformat(),
    )
    assert inspector_report["ready_input_ratio"] == "3/3"
    assert inspector_report["ready_input_count"] == 3
    assert inspector_report["formal_oos_allowed"] is False
    assert all(
        item["state"] == "ready"
        for item in inspector_report["inputs"]
    )

    # A missing source path must remain visible to the inspector even after a
    # valid common identity was previously built; no self-authored identity
    # can turn this into a 3/3 result.
    monkeypatch.setenv(
        "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH",
        str(tmp_path / "missing-ledger-manifest.json"),
    )
    missing_source_report = inspect_ml_formal_input_readiness.build_readiness_report(
        output_root=tmp_path / "pit-formal",
        training_as_of=observed.isoformat(),
    )
    assert missing_source_report["ready_input_ratio"] != "3/3"
    missing_ledger = missing_source_report["inputs"][0]
    assert missing_ledger["state"] == "missing"

    future_identity = dict(identity)
    future_identity["observed_at"] = "2099-01-01T00:00:00+00:00"
    future_identity_body = dict(future_identity)
    future_identity_body.pop("identity_hash", None)
    future_identity["identity_hash"] = payload_hash(future_identity_body)
    future_identity_path = tmp_path / "future-identity.json"
    write_immutable_formal_common_identity_manifest(
        future_identity_path,
        future_identity,
    )
    with pytest.raises(
        FormalCommonIdentityError,
        match="common identity observed_at is after observed",
    ):
        read_formal_common_identity_manifest(
            future_identity_path,
            observed=observed,
            verify_consumers=False,
        )

    # The common identity must be a projection of the loaded portfolio clock,
    # rather than a caller-supplied policy/universe label.  Keep the rest of
    # the identity and receipts intact so this reaches the clock projection
    # check before any consumer is rerun.
    for field, expected_error in (
        ("policy_hash", "common policy hash does not match clock"),
        ("universe_hash", "common universe hash does not match clock"),
    ):
        mismatched_identity = json.loads(identity_path.read_text(encoding="utf-8"))
        mismatched_common = dict(mismatched_identity["common_portfolio_clock"])
        mismatched_common[field] = "sha256:" + "e" * 64
        mismatched_identity["common_portfolio_clock"] = mismatched_common
        mismatched_body = dict(mismatched_identity)
        mismatched_body.pop("identity_hash", None)
        mismatched_identity["identity_hash"] = payload_hash(mismatched_body)
        mismatched_path = tmp_path / f"mismatched-common-{field}.json"
        write_immutable_formal_common_identity_manifest(
            mismatched_path,
            mismatched_identity,
        )
        with pytest.raises(FormalCommonIdentityError, match=expected_error):
            read_formal_common_identity_manifest(
                mismatched_path,
                source_paths=source_paths,
                portfolio_clock_manifest=machine_clock_path,
                market_db=market_path,
                output_root=tmp_path / "handoff-consumer",
                development_output_root=tmp_path / "handoff-development",
                training_as_of=observed.isoformat(),
                observed=observed,
                verify_consumers=False,
            )

    # B is accepted by the formal ledger consumer, but the identity still
    # carries a receipt for A.  A path swap must therefore fail at the receipt
    # binding boundary before any controlled handoff can be considered.
    source_a = source_paths["BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH"]
    source_b = tmp_path / "valid-ledger-b" / "manifest.json"
    source_b.parent.mkdir()
    shutil.copyfile(source_a, source_b)
    shutil.copyfile(
        source_a.parent / "portfolio_ledger.sqlite",
        source_b.parent / "portfolio_ledger.sqlite",
    )
    source_b.write_bytes(source_b.read_bytes() + b"\n")
    from data_module.formal_portfolio_ledger import load_formal_portfolio_state_ledger

    load_formal_portfolio_state_ledger(source_b)
    swapped_identity = json.loads(identity_path.read_text(encoding="utf-8"))
    swapped_entries = dict(swapped_identity["entries"])
    ledger_entry = dict(swapped_entries["BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH"])
    ledger_entry["path"] = str(source_b.resolve())
    ledger_entry["path_hash"] = payload_hash(
        {
            "env_name": "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH",
            "path": str(source_b.resolve()),
        }
    )
    ledger_entry["file_hash"] = file_sha256(source_b)
    swapped_entries["BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH"] = ledger_entry
    swapped_identity["entries"] = swapped_entries
    swapped_readback = dict(swapped_identity["consumer_readback"])
    swapped_ledger_readback = dict(
        swapped_readback["causal_non_cash_portfolio_ledger"]
    )
    swapped_ledger_readback["path"] = str(source_b.resolve())
    swapped_ledger_readback["file_hash"] = file_sha256(source_b)
    swapped_readback["causal_non_cash_portfolio_ledger"] = swapped_ledger_readback
    swapped_identity["consumer_readback"] = swapped_readback
    swapped_identity_body = dict(swapped_identity)
    swapped_identity_body.pop("identity_hash", None)
    swapped_identity["identity_hash"] = payload_hash(swapped_identity_body)
    swapped_identity_path = tmp_path / "swapped-identity.json"
    write_immutable_formal_common_identity_manifest(
        swapped_identity_path,
        swapped_identity,
    )
    swapped_sources = dict(source_paths)
    swapped_sources["BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH"] = source_b
    with pytest.raises(
        FormalCommonIdentityError,
        match="receipt source path mismatch",
    ):
        read_formal_common_identity_manifest(
            swapped_identity_path,
            source_paths=swapped_sources,
            portfolio_clock_manifest=machine_clock_path,
            market_db=market_path,
            output_root=tmp_path / "handoff-consumer",
            development_output_root=tmp_path / "handoff-development",
            training_as_of=observed.isoformat(),
            observed=observed,
            verify_consumers=False,
        )

    original_ledger_receipt = json.loads(
        receipt_paths["BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH"].read_text(
            encoding="utf-8"
        )
    )
    wrong_clock_receipt = dict(original_ledger_receipt)
    wrong_clock_result = dict(wrong_clock_receipt["result"])
    wrong_clock_result["portfolio_clock_id"] = "clock:valid-but-wrong"
    wrong_clock_receipt["result"] = wrong_clock_result
    wrong_clock_receipt.pop("receipt_hash", None)
    wrong_clock_receipt["receipt_hash"] = payload_hash(wrong_clock_receipt)
    wrong_clock_receipt_path = tmp_path / "wrong-clock-receipt.json"
    wrong_clock_receipt_path.write_text(
        json.dumps(wrong_clock_receipt),
        encoding="utf-8",
    )
    wrong_clock_identity = json.loads(identity_path.read_text(encoding="utf-8"))
    wrong_clock_entries = dict(wrong_clock_identity["entries"])
    wrong_clock_entry = dict(
        wrong_clock_entries["BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH"]
    )
    wrong_clock_entry["receipt_path"] = str(wrong_clock_receipt_path.resolve())
    wrong_clock_entry["receipt_file_hash"] = file_sha256(wrong_clock_receipt_path)
    wrong_clock_entry["receipt_hash"] = wrong_clock_receipt["receipt_hash"]
    wrong_clock_entries["BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH"] = wrong_clock_entry
    wrong_clock_identity["entries"] = wrong_clock_entries
    wrong_clock_identity_body = dict(wrong_clock_identity)
    wrong_clock_identity_body.pop("identity_hash", None)
    wrong_clock_identity["identity_hash"] = payload_hash(wrong_clock_identity_body)
    wrong_clock_identity_path = tmp_path / "wrong-clock-identity.json"
    write_immutable_formal_common_identity_manifest(
        wrong_clock_identity_path,
        wrong_clock_identity,
    )
    with pytest.raises(
        FormalCommonIdentityError,
        match="portfolio_clock_id does not match common portfolio clock",
    ):
        read_formal_common_identity_manifest(
            wrong_clock_identity_path,
            source_paths=source_paths,
            portfolio_clock_manifest=machine_clock_path,
            market_db=market_path,
            output_root=tmp_path / "handoff-consumer",
            development_output_root=tmp_path / "handoff-development",
            training_as_of=observed.isoformat(),
            observed=observed,
            verify_consumers=False,
        )
