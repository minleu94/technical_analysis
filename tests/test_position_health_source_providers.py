from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import replace
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from app_module.position_health_source_providers import (
    DecimalMetricSourceProvider,
    FrozenRulePolicySourceProvider,
    OfficialCalendarSourceProvider,
    PITConditionSourceProvider,
    PositionThesisRegistryProvider,
    PositionThesisRegistryWriter,
    build_position_health_source_bundle,
)
from app_module.position_health_transition_evaluator import (
    DEFAULT_POLICY_HASH,
    evaluate_baseline_file,
)
from app_module.position_thesis_contract import (
    PositionInvalidationRule,
    PositionThesisContract,
)


DECISION_AT = datetime(2026, 9, 8, 13, 0, tzinfo=timezone.utc)


def _contract(*, position_id: str = "paper:2330:entry-20260901") -> PositionThesisContract:
    return PositionThesisContract(
        position_id=position_id,
        stock_code="2330",
        entry_date="2026-09-01",
        decision_date="2026-09-08",
        available_date="2026-09-07",
        entry_thesis="明確由人工輸入的測試論點",
        holding_horizon_trading_days=20,
        next_review_date="2026-09-30",
        source_trace=("human:review-20260907",),
        invalidation_rules=(
            PositionInvalidationRule(
                metric_id="drawdown_bp",
                operator="gte",
                threshold=Decimal("1200"),
                action="exit",
            ),
        ),
    )


def _write_hashed(path: Path, payload: dict[str, object]) -> None:
    from app_module.position_health_source_providers import _sha256_json

    content = dict(payload)
    content["content_sha256"] = _sha256_json(payload)
    path.write_text(
        json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _canonical_hash(payload: object) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _write_frozen_rule_status(tmp_path: Path) -> Path:
    root = tmp_path / "formal-rule-source"
    bundle = root / "bundle"
    metadata = bundle / "metadata"
    clock = bundle / "clock"
    metadata.mkdir(parents=True)
    clock.mkdir(parents=True)
    policy_hash = "sha256:" + "a" * 64
    source_window_hash = "sha256:" + "b" * 64
    manifest_body: dict[str, object] = {
        "activation_trading_day": "2026-09-08",
        "policy_hash": policy_hash,
        "policy_version": "foreground-owner-bound-v1",
        "strategy_version": "manual-rule-only-daily-rank-v1",
        "schema_version": "prospective-formal-simulated-portfolio-clock.v1",
        "status": "planned",
    }
    manifest = {
        **manifest_body,
        "manifest_hash": _canonical_hash(manifest_body),
    }
    manifest_path = clock / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    owner = {
        "accepted_policy_version": manifest_body["policy_version"],
        "accepted_strategy_version": manifest_body["strategy_version"],
        "broker_order_allowed": False,
        "formal_oos_allowed": False,
        "policy_hash": policy_hash,
        "promotion_eligible": False,
    }
    owner_path = metadata / "owner_acceptance.json"
    owner_path.write_text(json.dumps(owner, sort_keys=True), encoding="utf-8")
    owner_file_hash = "sha256:" + hashlib.sha256(owner_path.read_bytes()).hexdigest()
    receipt = {
        "clock_manifest_hash": manifest["manifest_hash"],
        "owner_acceptance_hash": owner_file_hash,
        "observed_at": "2026-09-08T12:40:00+00:00",
        "source_window_hash": source_window_hash,
        "status": "machine_revalidated_candidate_only",
    }
    receipt_path = metadata / "machine_revalidation_receipt.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
    status = {
        "broker_order_allowed": False,
        "candidate_only": True,
        "clock_manifest": str(manifest_path),
        "clock_manifest_hash": manifest["manifest_hash"],
        "formal_oos_allowed": False,
        "machine_revalidation_receipt": str(receipt_path),
        "observed_at": "2026-09-08T12:45:00+00:00",
        "owner_acceptance": str(owner_path),
        "promotion_eligible": False,
        "schema_version": "prospective-formal-rule-source-machine-revalidation.v3",
        "source_window_hash": source_window_hash,
        "status": "rule_source_bundle_reused",
        "taipei_date": "2026-09-08",
        "writes_formal_controlled_paths": False,
        "writes_market_database": False,
    }
    status_path = root / "scheduler" / "rule_source_latest_status.json"
    status_path.parent.mkdir(parents=True)
    status_path.write_text(json.dumps(status, sort_keys=True), encoding="utf-8")
    return status_path


def _positions() -> list[dict[str, str]]:
    return [
        {
            "position_id": "paper:2330:entry-20260901",
            "entry_lineage_id": "paper:2330:entry-20260901",
            "stock_code": "2330",
            "state": "HEALTHY",
            "entry_lineage_status": "same_snapshot_verified",
        }
    ]


def _writer(path: Path) -> PositionThesisRegistryWriter:
    # The production writer records its real UTC clock.  The test injects a
    # deterministic clock before the decision cutoff so PIT credit cannot be
    # obtained from a late manual entry.
    return PositionThesisRegistryWriter(
        path,
        now_provider=lambda: datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc),
    )


def _writer_at(path: Path, recorded_at: datetime) -> PositionThesisRegistryWriter:
    return PositionThesisRegistryWriter(path, now_provider=lambda: recorded_at)


def test_thesis_registry_writer_and_provider_bind_version_time_and_lineage(
    tmp_path: Path,
) -> None:
    registry = tmp_path / "derived" / "thesis_registry.json"
    contract = _contract()
    written = _writer(registry).append(
        contract=contract,
        entry_lineage_id=contract.position_id,
        version_id="thesis-2330-v1",
        authored_by="reviewer:test",
        authored_at="2026-09-07T16:00:00+08:00",
        available_at="2026-09-07T16:05:00+08:00",
    )
    assert written["status"] == "written"
    result = PositionThesisRegistryProvider(registry).read_for_positions(
        _positions(),
        decision_date="2026-09-08",
        decision_at=DECISION_AT,
    )
    assert result.blockers == ()
    assert result.missing == ()
    assert result.values[_positions()[0]["position_id"]] == contract
    assert result.provenance["file_sha256"].startswith("sha256:")

    repeated = _writer(registry).append(
        contract=contract,
        entry_lineage_id=contract.position_id,
        version_id="thesis-2330-v1",
        authored_by="reviewer:test",
        authored_at="2026-09-07T16:00:00+08:00",
        available_at="2026-09-07T16:05:00+08:00",
    )
    assert repeated["status"] == "idempotent"


def test_thesis_registry_retry_ignores_clock_only_recorded_at_change(
    tmp_path: Path,
) -> None:
    registry = tmp_path / "thesis.json"
    contract = _contract()
    first = _writer_at(registry, datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)).append(
        contract=contract,
        entry_lineage_id=contract.position_id,
        version_id="thesis-2330-v1",
        authored_by="reviewer:test",
        authored_at="2026-09-07T16:00:00+08:00",
        available_at="2026-09-07T16:05:00+08:00",
    )
    before = registry.read_bytes()
    repeated = _writer_at(
        registry,
        datetime(2026, 9, 8, 12, 0, 1, tzinfo=timezone.utc),
    ).append(
        contract=contract,
        entry_lineage_id=contract.position_id,
        version_id="thesis-2330-v1",
        authored_by="reviewer:test",
        authored_at="2026-09-07T16:00:00+08:00",
        available_at="2026-09-07T16:05:00+08:00",
    )
    assert repeated["status"] == "idempotent"
    assert repeated["record_sha256"] == first["record_sha256"]
    assert repeated["recorded_at"] == "2026-09-08T12:00:00+00:00"
    assert registry.read_bytes() == before

    conflict = replace(contract, entry_thesis="不同的人工論點")
    with pytest.raises(ValueError, match="thesis_registry_version_conflict"):
        _writer_at(
            registry,
            datetime(2026, 9, 8, 12, 0, 2, tzinfo=timezone.utc),
        ).append(
            contract=conflict,
            entry_lineage_id=contract.position_id,
            version_id="thesis-2330-v1",
            authored_by="reviewer:test",
            authored_at="2026-09-07T16:00:00+08:00",
            available_at="2026-09-07T16:05:00+08:00",
        )
    assert registry.read_bytes() == before


def test_thesis_provider_does_not_match_stock_code_without_lineage(tmp_path: Path) -> None:
    registry = tmp_path / "thesis.json"
    contract = _contract()
    _writer(registry).append(
        contract=contract,
        entry_lineage_id=contract.position_id,
        version_id="thesis-2330-v1",
        authored_by="reviewer:test",
        authored_at="2026-09-07T16:00:00+08:00",
        available_at="2026-09-07T16:05:00+08:00",
    )
    result = PositionThesisRegistryProvider(registry).read_for_positions(
        [{"stock_code": "2330"}],
        decision_date="2026-09-08",
        decision_at=DECISION_AT,
    )
    assert result.values["2330"] is None
    assert "position_lineage_missing:2330" in result.warnings


def test_thesis_registry_lock_preserves_two_concurrent_records_and_history(
    tmp_path: Path,
) -> None:
    registry = tmp_path / "thesis.json"
    first = _contract(position_id="paper:2330:entry-a")
    second = _contract(position_id="paper:2330:entry-b")

    def append_one(contract: PositionThesisContract, version: str) -> dict[str, object]:
        return _writer(registry).append(
            contract=contract,
            entry_lineage_id=contract.position_id,
            version_id=version,
            authored_by="reviewer:test",
            authored_at="2026-09-07T16:00:00+08:00",
            available_at="2026-09-07T16:05:00+08:00",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda item: append_one(*item),
                ((first, "thesis-a-v1"), (second, "thesis-b-v1")),
            )
        )
    assert {item["status"] for item in results} == {"written"}
    payload = json.loads(registry.read_text(encoding="utf-8"))
    assert len(payload["records"]) == 2
    before = registry.read_bytes()
    conflicting = replace(first, entry_thesis="不同的人工論點")
    with pytest.raises(ValueError, match="version_conflict|effective_version_conflict"):
        append_one(conflicting, "thesis-a-v1")
    assert registry.read_bytes() == before


def test_thesis_registry_lock_preserves_two_subprocess_records(tmp_path: Path) -> None:
    registry = tmp_path / "thesis.json"
    first = _contract(position_id="paper:2330:subprocess-a")
    second = _contract(position_id="paper:2330:subprocess-b")
    child = textwrap.dedent(
        """
        import json
        import sys
        from app_module.position_health_source_providers import PositionThesisRegistryWriter
        from app_module.position_thesis_contract import PositionThesisContract

        path, payload, version = sys.argv[1:]
        contract = PositionThesisContract.from_dict(json.loads(payload))
        result = PositionThesisRegistryWriter(path).append(
            contract=contract,
            entry_lineage_id=contract.position_id,
            version_id=version,
            authored_by="reviewer:subprocess",
            authored_at="2026-09-07T16:00:00+08:00",
            available_at="2026-09-07T16:05:00+08:00",
        )
        print(json.dumps(result, sort_keys=True))
        """
    )
    child_env = os.environ.copy()
    repo_root = str(Path.cwd())
    child_env["PYTHONPATH"] = os.pathsep.join(
        item for item in (repo_root, child_env.get("PYTHONPATH", "")) if item
    )
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                child,
                str(registry),
                json.dumps(contract.to_dict(), ensure_ascii=False),
                version,
            ],
            cwd=repo_root,
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for contract, version in (
            (first, "thesis-subprocess-a-v1"),
            (second, "thesis-subprocess-b-v1"),
        )
    ]
    results: list[tuple[int, str, str]] = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        results.append((process.returncode, stdout, stderr))
    assert all(code == 0 for code, _, _ in results), results
    assert all(json.loads(stdout)["status"] == "written" for _, stdout, _ in results)
    payload = json.loads(registry.read_text(encoding="utf-8"))
    assert {
        str(record["version_id"]) for record in payload["records"]
    } == {"thesis-subprocess-a-v1", "thesis-subprocess-b-v1"}
    assert not registry.with_name("thesis.json.lock").exists()


def test_aborted_registry_replace_preserves_history_and_releases_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = tmp_path / "thesis.json"
    existing = _contract()
    _writer(registry).append(
        contract=existing,
        entry_lineage_id=existing.position_id,
        version_id="thesis-existing-v1",
        authored_by="reviewer:test",
        authored_at="2026-09-07T16:00:00+08:00",
        available_at="2026-09-07T16:05:00+08:00",
    )
    before = registry.read_bytes()

    def abort_before_replace(path: Path, payload: object) -> None:
        temporary = path.with_name(".interrupted-registry.tmp")
        try:
            temporary.write_text("partial", encoding="utf-8")
            raise KeyboardInterrupt("simulated_process_interruption")
        finally:
            temporary.unlink(missing_ok=True)

    monkeypatch.setattr(
        "app_module.position_health_source_providers._atomic_write_json",
        abort_before_replace,
    )
    incoming = replace(existing, position_id="paper:2330:entry-new")
    with pytest.raises(KeyboardInterrupt, match="simulated_process_interruption"):
        _writer_at(
            registry,
            datetime(2026, 9, 8, 12, 0, 1, tzinfo=timezone.utc),
        ).append(
            contract=incoming,
            entry_lineage_id=incoming.position_id,
            version_id="thesis-new-v1",
            authored_by="reviewer:test",
            authored_at="2026-09-07T16:00:00+08:00",
            available_at="2026-09-07T16:05:00+08:00",
        )
    assert registry.read_bytes() == before
    assert not registry.with_name("thesis.json.lock").exists()
    assert not (tmp_path / ".interrupted-registry.tmp").exists()


def test_pit_and_decimal_providers_accept_only_hash_bound_pit_inputs(tmp_path: Path) -> None:
    condition_path = tmp_path / "condition.json"
    _write_hashed(
        condition_path,
        {
            "schema_version": "position-health-condition-source.v1",
            "source_id": "paper-condition:test",
            "source_snapshot_hash": "sha256:" + "1" * 64,
            "as_of_date": "2026-09-08",
            "available_at": "2026-09-08T08:20:00+08:00",
            "positions": [
                {
                    "position_id": "paper:2330:entry-20260901",
                    "entry_lineage_id": "paper:2330:entry-20260901",
                    "stock_code": "2330",
                    "quality": "verified",
                    "result": {
                        "status": "valid",
                        "label": "仍符合",
                        "source_label": "test",
                        "current_regime": "Trend",
                        "current_total_score": "12.0",
                        "reasons": ["regime_stable"],
                        "details": {"score_change": "0.0"},
                    },
                    "current_snapshot": {
                        "current_regime": "Trend",
                        "current_total_score": "12.0",
                        "current_price": "100.00",
                    },
                }
            ],
        },
    )
    condition = PITConditionSourceProvider(condition_path).read_for_positions(
        _positions(),
        decision_date="2026-09-08",
        decision_at=DECISION_AT,
        observed_at=DECISION_AT,
    )
    assert condition.blockers == ()
    assert condition.missing == ()
    observation = condition.values[_positions()[0]["position_id"]]
    assert observation.source_snapshot_hash == "sha256:" + "1" * 64
    assert observation.current_snapshot.current_total_score == Decimal("12.0")

    metrics_path = tmp_path / "metrics.json"
    _write_hashed(
        metrics_path,
        {
            "schema_version": "position-health-metrics-source.v1",
            "source_id": "paper-metric:test",
            "source_snapshot_hash": "sha256:" + "2" * 64,
            "available_at": "2026-09-08T08:20:00+08:00",
            "metrics": [
                {
                    "position_id": "paper:2330:entry-20260901",
                    "entry_lineage_id": "paper:2330:entry-20260901",
                    "stock_code": "2330",
                    "metric_id": "drawdown_bp",
                    "value": "-100.00",
                    "available_date": "2026-09-08",
                }
            ],
        },
    )
    metrics = DecimalMetricSourceProvider(metrics_path).read_for_positions(
        _positions(),
        decision_date="2026-09-08",
        decision_at=DECISION_AT,
        observed_at=DECISION_AT,
    )
    assert metrics.blockers == ()
    assert metrics.values["paper:2330:entry-20260901"][0].value == Decimal("-100.00")


def test_source_providers_reject_future_or_float_metric_inputs(tmp_path: Path) -> None:
    condition_path = tmp_path / "future_condition.json"
    _write_hashed(
        condition_path,
        {
            "schema_version": "position-health-condition-source.v1",
            "source_id": "paper-condition:test",
            "source_snapshot_hash": "sha256:" + "1" * 64,
            "as_of_date": "2026-09-08",
            "available_at": "2026-09-08T22:00:00+08:00",
            "positions": [],
        },
    )
    future = PITConditionSourceProvider(condition_path).read_for_positions(
        _positions(),
        decision_date="2026-09-08",
        decision_at=DECISION_AT,
        observed_at=DECISION_AT,
    )
    assert future.blockers and "available_at_future" in future.blockers[0]

    metrics_path = tmp_path / "float_metric.json"
    _write_hashed(
        metrics_path,
        {
            "schema_version": "position-health-metrics-source.v1",
            "source_id": "paper-metric:test",
            "source_snapshot_hash": "sha256:" + "2" * 64,
            "available_at": "2026-09-08T08:20:00+08:00",
            "metrics": [
                {
                    "position_id": "paper:2330:entry-20260901",
                    "entry_lineage_id": "paper:2330:entry-20260901",
                    "stock_code": "2330",
                    "metric_id": "drawdown_bp",
                    "value": 1.5,
                    "available_date": "2026-09-08",
                }
            ],
        },
    )
    malformed = DecimalMetricSourceProvider(metrics_path).read_for_positions(
        _positions(),
        decision_date="2026-09-08",
        decision_at=DECISION_AT,
        observed_at=DECISION_AT,
    )
    assert malformed.blockers and "value_must_be_decimal_text" in malformed.blockers[0]


def test_official_calendar_provider_reads_verified_cache_without_network() -> None:
    result = OfficialCalendarSourceProvider(
        calendar_cache_path=Path("output/paper_execution_eod_replay/calendar_cache")
    ).read_range(
        start_date="2026-09-07",
        end_date="2026-09-08",
        decision_at=DECISION_AT,
        observed_at=DECISION_AT,
    )
    assert result.blockers == ()
    assert result.values["trading_dates"] == ("2026-09-07", "2026-09-08")
    assert result.provenance["years"][2026]["cache_file_sha256"].startswith("sha256:")


def test_bundle_reports_missing_human_sources_but_keeps_real_calendar() -> None:
    bundle = build_position_health_source_bundle(
        positions=_positions(),
        decision_date="2026-09-08",
        decision_at=DECISION_AT,
        observed_at=DECISION_AT,
        calendar_cache_path=Path("output/paper_execution_eod_replay/calendar_cache"),
    )
    assert bundle.blockers == ()
    assert bundle.trading_dates == ("2026-09-08",)
    assert bundle.thesis_by_position == {}
    assert "thesis_registry_not_configured" in bundle.warnings


def test_evaluator_end_to_end_consumes_verified_sources_and_persists_proposal(
    tmp_path: Path,
) -> None:
    registry = tmp_path / "thesis.json"
    contract = _contract()
    _writer(registry).append(
        contract=contract,
        entry_lineage_id=contract.position_id,
        version_id="thesis-2330-v1",
        authored_by="reviewer:test",
        authored_at="2026-09-07T16:00:00+08:00",
        available_at="2026-09-07T16:05:00+08:00",
    )
    condition = tmp_path / "condition.json"
    _write_hashed(
        condition,
        {
            "schema_version": "position-health-condition-source.v1",
            "source_id": "paper-condition:test",
            "source_snapshot_hash": "sha256:" + "1" * 64,
            "as_of_date": "2026-09-08",
            "available_at": "2026-09-08T08:20:00+08:00",
            "positions": [
                {
                    "position_id": contract.position_id,
                    "entry_lineage_id": contract.position_id,
                    "stock_code": "2330",
                    "quality": "verified",
                    "result": {
                        "status": "valid",
                        "label": "仍符合",
                        "source_label": "test",
                        "reasons": ["regime_stable"],
                        "details": {},
                    },
                    "current_snapshot": {
                        "current_regime": "Trend",
                        "current_total_score": "12.0",
                        "current_price": "100.00",
                    },
                }
            ],
        },
    )
    metrics = tmp_path / "metrics.json"
    _write_hashed(
        metrics,
        {
            "schema_version": "position-health-metrics-source.v1",
            "source_id": "paper-metric:test",
            "source_snapshot_hash": "sha256:" + "2" * 64,
            "available_at": "2026-09-08T08:20:00+08:00",
            "metrics": [
                {
                    "position_id": contract.position_id,
                    "entry_lineage_id": contract.position_id,
                    "stock_code": "2330",
                    "metric_id": "drawdown_bp",
                    "value": "-100.00",
                    "available_date": "2026-09-08",
                }
            ],
        },
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "schema_version": "position-health-baseline.v1",
                "source_snapshot_id": "paper-main-20260908",
                "source_snapshot_rows_sha256": "sha256:" + "3" * 64,
                "decision_date": "2026-09-08",
                "as_of_date": "2026-09-08",
                "positions": _positions(),
            }
        ),
        encoding="utf-8",
    )
    result = evaluate_baseline_file(
        baseline_path=baseline,
        output_dir=tmp_path / "evaluation",
        observed_at=DECISION_AT,
        transition_repository_path=tmp_path / "evaluation" / "proposals.sqlite",
        thesis_registry_path=registry,
        condition_source_path=condition,
        metrics_source_path=metrics,
        calendar_cache_path=Path("output/paper_execution_eod_replay/calendar_cache"),
    )
    assert result["status"] == "passed"
    assert result["positions"][0]["proposed_state"] == "HEALTHY"
    assert result["positions"][0]["transition_event"]["persistence"] == "written"
    assert result["provenance"]["thesis"]["status"] == "verified"
    assert result["provenance"]["official_calendar"]["status"] == "verified"


def test_evaluator_blocks_before_persisting_when_condition_source_is_future(
    tmp_path: Path,
) -> None:
    condition = tmp_path / "future.json"
    _write_hashed(
        condition,
        {
            "schema_version": "position-health-condition-source.v1",
            "source_id": "paper-condition:test",
            "source_snapshot_hash": "sha256:" + "1" * 64,
            "as_of_date": "2026-09-08",
            "available_at": "2026-09-08T22:00:00+08:00",
            "positions": [],
        },
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "source_snapshot_id": "paper-main-20260908",
                "source_snapshot_rows_sha256": "sha256:" + "3" * 64,
                "decision_date": "2026-09-08",
                "positions": _positions(),
            }
        ),
        encoding="utf-8",
    )
    result = evaluate_baseline_file(
        baseline_path=baseline,
        output_dir=tmp_path / "evaluation",
        observed_at=DECISION_AT,
        thesis_registry_path=tmp_path / "missing-thesis.json",
        condition_source_path=condition,
        metrics_source_path=tmp_path / "missing-metrics.json",
    )
    assert result["status"] == "blocked"
    assert any("pit_condition_source_available_at_future" in item for item in result["blockers"])
    assert result["positions"] == []


def test_frozen_rule_policy_provider_verifies_machine_policy_without_thesis(
    tmp_path: Path,
) -> None:
    status_path = _write_frozen_rule_status(tmp_path)
    result = FrozenRulePolicySourceProvider(status_path).read(
        decision_date="2026-09-08",
        decision_at=DECISION_AT,
        observed_at=DECISION_AT,
    )
    assert result.blockers == ()
    assert result.missing == ()
    assert result.values["policy_hash"] == "sha256:" + "a" * 64
    assert result.provenance["status"] == "verified"
    assert result.provenance["position_thesis_policy_status"] == "missing"
    assert "frozen_rule_policy_machine_only" in result.warnings
    assert "position_thesis_policy_not_supplied_by_formal_rule" in result.warnings


def test_frozen_rule_policy_provider_rejects_future_status_receipt(
    tmp_path: Path,
) -> None:
    status_path = _write_frozen_rule_status(tmp_path)
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["observed_at"] = "2026-09-08T13:01:00+00:00"
    status_path.write_text(json.dumps(status, sort_keys=True), encoding="utf-8")
    result = FrozenRulePolicySourceProvider(status_path).read(
        decision_date="2026-09-08",
        decision_at=DECISION_AT,
        observed_at=DECISION_AT,
    )
    assert result.values == {}
    assert result.blockers
    assert "frozen_rule_policy_source_observed_at_future" in result.blockers[0]


def test_source_bundle_keeps_health_policy_identity_separate_from_rule_policy(
    tmp_path: Path,
) -> None:
    status_path = _write_frozen_rule_status(tmp_path)
    bundle = build_position_health_source_bundle(
        positions=_positions(),
        decision_date="2026-09-08",
        decision_at=DECISION_AT,
        observed_at=DECISION_AT,
        policy_source_path=status_path,
    )
    assert bundle.blockers == ()
    assert bundle.provenance["policy"]["status"] == "verified"
    assert bundle.provenance["policy"]["policy_hash"] == "sha256:" + "a" * 64
    # The Rule ranking hash is provenance only; the Health transition policy
    # remains the evaluator's own identity.
    assert "frozen_rule_policy_machine_only" in bundle.warnings


def test_evaluator_keeps_health_policy_hash_when_rule_source_is_present(
    tmp_path: Path,
) -> None:
    status_path = _write_frozen_rule_status(tmp_path)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "decision_date": "2026-09-08",
                "positions": [
                    {
                        "position_id": "paper:2330:entry-a",
                        "entry_lineage_id": "paper:2330:entry-a",
                        "entry_lineage_status": "same_snapshot_verified",
                        "stock_code": "2330",
                        "state": "WATCH",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = evaluate_baseline_file(
        baseline_path=baseline,
        output_dir=tmp_path / "evaluation",
        observed_at=DECISION_AT,
        policy_source_path=status_path,
    )
    assert result["policy_hash"] == DEFAULT_POLICY_HASH
    assert result["provenance"]["policy"]["policy_hash"] == "sha256:" + "a" * 64
    assert result["status"] == "degraded"
