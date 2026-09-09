from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest

from data_module.ml_storage_capacity import (
    MLStorageCapacityBudget,
    acquire_heavy_chain_reservation,
    release_heavy_chain_reservation,
)
from data_module.pit_sector_machine_publisher import (
    consume_machine_pit_operational_candidate,
    publish_machine_pit_operational_candidate,
)
from data_module.pit_sector_membership_machine import (
    build_machine_pit_publication,
    write_machine_pit_receipt,
)
from scripts import run_daily_ml_allocation_derived_shadow as shadow


TAIPEI = ZoneInfo("Asia/Taipei")
DECISION_AT = datetime(2026, 7, 31, 8, 30, tzinfo=TAIPEI)
MACHINE_DECISION_AT = DECISION_AT.astimezone(ZoneInfo("UTC"))


class _Calendar:
    def __init__(self, states: dict[date, tuple[bool | None, str]]) -> None:
        self.states = states

    def is_official_trading_day(
        self,
        target_date: date,
    ) -> tuple[bool | None, str]:
        return self.states.get(target_date, (None, "calendar_missing"))


def _preflight() -> SimpleNamespace:
    return SimpleNamespace(
        as_dict=lambda: {
            "within_budget": True,
            "stage": "test",
            "free_bytes": 500 * 1024**3,
        }
    )


def _release_fixture(tmp_path: Path) -> SimpleNamespace:
    release_root = tmp_path / "release"
    release_root.mkdir()
    files = {
        "release_manifest.json": b"release-manifest",
        "training_manifest_v2.json": json.dumps(
            {"training_as_of": "2026-07-30T08:30:00+08:00"}
        ).encode("utf-8"),
        "model.joblib": b"model",
        "preprocessor.json": b"preprocessor",
        "calibrator.json": b"calibrator",
    }
    for name, content in files.items():
        (release_root / name).write_bytes(content)
    identity = f"sha256:{'a' * 64}"
    manifest = SimpleNamespace(
        release_identity_hash=identity,
        artifact_file="model.joblib",
        preprocessor=SimpleNamespace(artifact_file="preprocessor.json"),
        calibration=SimpleNamespace(artifact_file="calibrator.json"),
        missing_policy=SimpleNamespace(
            policy_hash=f"sha256:{'b' * 64}",
            policy_id="balanced-v4-operational",
        ),
    )
    return SimpleNamespace(
        release_root=release_root,
        manifest_path=release_root / "release_manifest.json",
        manifest=manifest,
        release_manifest_file_hash=f"sha256:{'c' * 64}",
        release_id="release-test",
        model_id="model-test",
        dataset_id="dataset-test",
        artifact_hash=f"sha256:{'d' * 64}",
    )


def _release_evidence_fixture(release: SimpleNamespace) -> dict[str, object]:
    paths = [
        release.manifest_path,
        release.release_root / "training_manifest_v2.json",
        release.release_root / "model.joblib",
        release.release_root / "preprocessor.json",
        release.release_root / "calibrator.json",
    ]
    required: list[dict[str, object]] = []
    for path in paths:
        item = shadow._stat_evidence(path)
        item["sha256"] = shadow._file_hash(path)
        required.append(item)
    first_observed = "2026-07-31T00:30:00Z"
    return {
        "release_root": str(release.release_root),
        "release_id": release.release_id,
        "release_manifest_file_hash": release.release_manifest_file_hash,
        "release_identity_hash": release.manifest.release_identity_hash,
        "model_id": release.model_id,
        "dataset_id": release.dataset_id,
        "artifact_hash": release.artifact_hash,
        "training_as_of": "2026-07-30T08:30:00+08:00",
        "observed_at": "2026-07-31T08:30:00+08:00",
        "first_observed_at": first_observed,
        "observation_receipt_path": "test-receipt.json",
        "observation_receipt_file_hash": f"sha256:{'e' * 64}",
        "published_at": None,
        "published_time_basis": "not_inferred_from_mtime; use_first_observed_receipt_only",
        "required_file_mtime_diagnostics": [],
        "required_files": required,
    }


def _machine_operational_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """建立真正由 controlled publisher 簽章的 current-day candidate。"""

    monkeypatch.setenv(
        "RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY",
        "test-controlled-key",
    )
    monkeypatch.setenv(
        "RULE_CHAMPION_CONTROLLED_STORE_ID",
        "machine-pit-wrapper-test-store",
    )
    machine_output = tmp_path / "machine"
    machine_output.mkdir()
    publication = build_machine_pit_publication(
        raw_payloads={
            "twse": json.dumps(
                [
                    {
                        "公司代號": "1101",
                        "產業別": "01",
                        "出表日期": "20260731",
                    }
                ],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            "tpex": json.dumps(
                [
                    {
                        "SecuritiesCompanyCode": "5501",
                        "SecuritiesIndustryCode": "03",
                        "Date": "2026-07-31",
                    }
                ],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
        },
        output_dir=machine_output,
        captured_at=datetime(2026, 7, 31, 0, 0, tzinfo=ZoneInfo("UTC")),
        now=datetime(2026, 7, 31, 0, 10, tzinfo=ZoneInfo("UTC")),
    )
    receipt_path = tmp_path / "machine-receipt.json"
    write_machine_pit_receipt(
        publication.publication_path,
        receipt_path=receipt_path,
        now=datetime(2026, 7, 31, 0, 20, tzinfo=ZoneInfo("UTC")),
    )
    operational_path = tmp_path / "machine-operational.json"
    publish_machine_pit_operational_candidate(
        receipt_path,
        output_path=operational_path,
        decision_at=MACHINE_DECISION_AT,
        now=datetime(2026, 7, 31, 0, 40, tzinfo=ZoneInfo("UTC")),
    )
    return operational_path


def test_release_receipt_preserves_first_observation_across_capture_times(
    tmp_path: Path,
) -> None:
    release = _release_fixture(tmp_path)
    output_root = tmp_path / "output"

    first = shadow._release_evidence(
        release_root=release.release_root,
        release=cast(Any, release),
        output_root=output_root,
        capture_at=datetime(2026, 7, 31, 8, 20, tzinfo=TAIPEI),
    )
    second = shadow._release_evidence(
        release_root=release.release_root,
        release=cast(Any, release),
        output_root=output_root,
        capture_at=datetime(2026, 7, 31, 9, 0, tzinfo=TAIPEI),
    )

    assert first["first_observed_at"] == "2026-07-31T08:20:00.000000+08:00"
    assert second["first_observed_at"] == first["first_observed_at"]
    receipt_path = Path(str(second["observation_receipt_path"]))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["observed_at"] == first["first_observed_at"]
    assert shadow._file_hash(receipt_path) == second[
        "observation_receipt_file_hash"
    ]


def test_select_natural_decision_rejects_invalid_clock_and_unknown_calendar() -> None:
    invalid = shadow._select_natural_decision(
        calendar=_Calendar({date(2026, 7, 31): (True, "open")} ),
        now=datetime(2026, 7, 31, 9, 0, tzinfo=TAIPEI),
        requested_decision_at="2026-07-31T09:00:00+08:00",
    )
    assert invalid["status"] == "blocked_invalid_decision_at"

    unknown = shadow._select_natural_decision(
        calendar=_Calendar({}),
        now=datetime(2026, 7, 31, 9, 0, tzinfo=TAIPEI),
        requested_decision_at=None,
    )
    assert unknown["status"] == "blocked_calendar_unknown"


def test_forward_late_capture_is_blocked_before_daily_consumer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _release_fixture(tmp_path)
    database = tmp_path / "twstock.db"
    paper = tmp_path / "paper.sqlite"
    late_machine_path = tmp_path / "late-machine-operational.json"
    database.write_bytes(b"readonly-db")
    paper.write_bytes(b"readonly-paper")
    late_machine_path.write_bytes(b"candidate-arrived-after-window")
    monkeypatch.setattr(shadow, "preflight_capacity", lambda **_: _preflight())
    monkeypatch.setattr(
        shadow.AllocationReleaseAdapter,
        "load",
        lambda _self, _root: release,
    )
    monkeypatch.setattr(
        shadow,
        "_release_evidence",
        lambda **_: _release_evidence_fixture(release),
    )
    monkeypatch.setattr(
        shadow.daily,
        "run",
        lambda **_: pytest.fail("forward-late capture must not call daily"),
    )

    result = shadow.run(
        database_path=database,
        output_root=tmp_path / "output",
        release_root=release.release_root,
        paper_state_db_path=paper,
        mode=shadow.FORWARD_MODE,
        decision_at="2026-07-31T08:30:00+08:00",
        now=datetime(2026, 7, 31, 10, 0, tzinfo=TAIPEI),
        calendar=_Calendar(
            {
                date(2026, 7, 31): (True, "open"),
                date(2026, 7, 30): (True, "open"),
            }
        ),
        pit_machine_operational_path=late_machine_path,
        lock_path=tmp_path / "shared.lock",
    )

    payload = cast(dict[str, Any], result)
    assert payload["status"] == "blocked_forward_decision_window"
    assert cast(dict[str, Any], payload["decision_clock"])[
        "within_forward_window"
    ] is False
    assert cast(dict[str, Any], payload["production_boundaries"])[
        "production_blend_alpha_bp"
    ] == 0


def test_research_capture_delegates_with_bounded_budget_and_rule_comparison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _release_fixture(tmp_path)
    database = tmp_path / "twstock.db"
    paper = tmp_path / "paper.sqlite"
    database.write_bytes(b"readonly-db")
    paper.write_bytes(b"readonly-paper")
    output_root = tmp_path / "output"
    machine_path = _machine_operational_candidate(tmp_path, monkeypatch)
    observation_path = (
        output_root
        / "scheduled"
        / "ml_allocation_copilot"
        / "shadow.json"
    )
    observation_path.parent.mkdir(parents=True)
    observation_path.write_text(
        json.dumps(
            {
                "record_hash": f"sha256:{'f' * 64}",
                "lanes": [
                    {
                        "alpha_bp": 0,
                        "lane_hash": f"sha256:{'1' * 64}",
                        "estimated_cost": "0",
                        "turnover_bp": 0,
                        "constraint_violation_count": 0,
                        "research_only": True,
                    },
                    {
                        "alpha_bp": 2000,
                        "lane_hash": f"sha256:{'2' * 64}",
                        "estimated_cost": "1.2",
                        "turnover_bp": 10,
                        "constraint_violation_count": 0,
                        "research_only": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(shadow, "preflight_capacity", lambda **_: _preflight())
    monkeypatch.setattr(
        shadow.AllocationReleaseAdapter,
        "load",
        lambda _self, _root: release,
    )
    monkeypatch.setattr(
        shadow,
        "_release_evidence",
        lambda **_: _release_evidence_fixture(release),
    )
    monkeypatch.setattr(
        shadow,
        "_source_date_evidence",
        lambda **_: {
            "status": "completed",
            "latest_date_by_table": {
                "daily_prices": "20260904",
                "technical_indicators": "20260904",
                "market_indices": "20260904",
                "industry_indices": "20260904",
            },
            "symbol_latest_date": {"1101": "20260904"},
            "strict_t_minus_one_rows_by_symbol": {"1101": 1},
        },
    )
    captured: dict[str, Any] = {}

    def fake_daily_run(**kwargs: Any) -> dict[str, object]:
        captured.update(kwargs)
        machine_readback = consume_machine_pit_operational_candidate(
            Path(kwargs["pit_machine_operational_path"]),
            decision_at=kwargs["decision_at"],
            now=kwargs["decision_at"],
        )
        captured["machine_readback"] = machine_readback
        return {
            "status": "passed_rule_only",
            "orchestration_status": "completed",
            "shadow_observation_recorded": True,
            "shadow_observation_path": str(observation_path),
            "strict_t_minus_one": "2026-07-30",
            "production_blend_alpha_bp": 0,
            "formal_oos_allowed": False,
            "broker_order_allowed": False,
        }

    monkeypatch.setattr(shadow.daily, "run", fake_daily_run)
    result = shadow.run(
        database_path=database,
        output_root=output_root,
        release_root=release.release_root,
        paper_state_db_path=paper,
        mode=shadow.RESEARCH_MODE,
        now=datetime(2026, 7, 31, 10, 0, tzinfo=TAIPEI),
        calendar=_Calendar(
            {
                date(2026, 7, 31): (True, "open"),
                date(2026, 7, 30): (True, "open"),
            }
        ),
        pit_machine_operational_path=machine_path,
        lock_path=tmp_path / "shared.lock",
    )

    payload = cast(dict[str, Any], result)
    assert payload["status"] == "completed"
    assert payload["mode"] == shadow.RESEARCH_MODE
    assert cast(dict[str, Any], payload["release"])[
        "available_before_decision"
    ] is True
    assert cast(dict[str, Any], payload["decision_clock"])[
        "research_late_capture"
    ] is True
    cost_performance = cast(dict[str, Any], payload["cost_performance"])
    rule_comparison = cast(dict[str, Any], cost_performance["rule_comparison"])
    rule_lane = cast(dict[str, Any], rule_comparison["rule_lane"])
    assert rule_lane["alpha_bp"] == 0
    assert cast(dict[str, Any], cost_performance["equal_weight_comparison"])[
        "status"
    ] == "deferred"
    assert captured["pit_machine_operational_path"] == machine_path.resolve()
    machine_readback = cast(dict[str, Any], captured["machine_readback"])
    assert machine_readback["status"] == "machine_verified"
    assert machine_readback["available_at"] == "2026-07-31T00:00:00+00:00"
    assert machine_readback["effective_from"] == "2026-07-31"
    assert machine_readback["candidate_only"] is True
    assert machine_readback["formal_oos_allowed"] is False
    assert machine_readback["production_action_allowed"] is False
    budget = captured["capacity_budget"]
    assert isinstance(budget, MLStorageCapacityBudget)
    assert budget.persistent_new_bytes_budget is not None
    assert budget.persistent_new_bytes_budget < 256 * 1024**2
    assert budget.temporary_peak_bytes_budget == 256 * 1024**2
    assert budget.safety_reserve_bytes == 200 * 1024**3
    source = cast(dict[str, Any], payload["source"])
    assert cast(dict[str, Any], source["database"])["unchanged"] is True
    assert cast(dict[str, Any], source["paper_state_db"])["unchanged"] is True
    assert cast(dict[str, Any], source["release_manifest"])["unchanged"] is True
    capacity = cast(dict[str, Any], payload["capacity"])
    assert capacity["temporary_peak_bytes_observed"] is None
    assert capacity["within_temporary_budget"] is None
    baseline = int(capacity["persistent_existing_bytes_before_run"])
    assert shadow.directory_size_bytes(output_root) - baseline == int(
        capacity["persistent_new_bytes_observed"]
    )

    recovered = acquire_heavy_chain_reservation(tmp_path / "shared.lock")
    assert recovered is not None
    release_heavy_chain_reservation(recovered)


def test_research_capture_forwards_exact_archive_contract_to_daily(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _release_fixture(tmp_path)
    database = tmp_path / "twstock.db"
    paper = tmp_path / "paper.sqlite"
    database.write_bytes(b"readonly-db")
    paper.write_bytes(b"readonly-paper")
    output_root = tmp_path / "output"
    archive_root = tmp_path / "pit_candidate_archive"
    archive_root.mkdir()
    manifest = archive_root / "2026-07-30" / "archive-key" / "archive_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("frozen-manifest", encoding="utf-8")
    frozen_hash = shadow._file_hash(manifest)
    monkeypatch.setattr(shadow, "preflight_capacity", lambda **_: _preflight())
    monkeypatch.setattr(
        shadow.AllocationReleaseAdapter,
        "load",
        lambda _self, _root: release,
    )
    monkeypatch.setattr(
        shadow,
        "_release_evidence",
        lambda **_: _release_evidence_fixture(release),
    )
    monkeypatch.setattr(
        shadow,
        "_source_date_evidence",
        lambda **_: {"status": "completed", "strict_t_minus_one_rows_by_symbol": {}},
    )
    captured: dict[str, Any] = {}

    def fake_daily_run(**kwargs: Any) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "status": "passed_rule_only",
            "orchestration_status": "completed",
            "shadow_observation_recorded": True,
            "strict_t_minus_one": "2026-07-30",
            "production_blend_alpha_bp": 0,
            "formal_oos_allowed": False,
            "broker_order_allowed": False,
        }

    monkeypatch.setattr(shadow.daily, "run", fake_daily_run)
    result = shadow.run(
        database_path=database,
        output_root=output_root,
        release_root=release.release_root,
        paper_state_db_path=paper,
        mode=shadow.RESEARCH_MODE,
        now=datetime(2026, 7, 31, 10, 0, tzinfo=TAIPEI),
        calendar=_Calendar(
            {
                date(2026, 7, 31): (True, "open"),
                date(2026, 7, 30): (True, "open"),
            }
        ),
        pit_machine_archive_root=archive_root,
        pit_machine_archive_manifest=manifest,
        pit_machine_archive_manifest_file_hash=frozen_hash,
        lock_path=tmp_path / "shared.lock",
    )

    assert cast(dict[str, Any], result)["status"] == "completed"
    assert captured["pit_machine_operational_path"] is None
    assert captured["pit_machine_archive_root"] == archive_root.resolve()
    assert captured["pit_machine_archive_manifest"] == manifest.resolve()
    assert captured["pit_machine_archive_manifest_file_hash"] == frozen_hash


def test_missing_paper_input_is_persisted_without_daily_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _release_fixture(tmp_path)
    database = tmp_path / "twstock.db"
    database.write_bytes(b"readonly-db")
    monkeypatch.setattr(shadow, "preflight_capacity", lambda **_: _preflight())
    monkeypatch.setattr(
        shadow.AllocationReleaseAdapter,
        "load",
        lambda _self, _root: release,
    )
    monkeypatch.setattr(
        shadow,
        "_release_evidence",
        lambda **_: _release_evidence_fixture(release),
    )
    monkeypatch.setattr(
        shadow.daily,
        "run",
        lambda **_: pytest.fail("missing input must stop before daily"),
    )

    result = shadow.run(
        database_path=database,
        output_root=tmp_path / "output",
        release_root=release.release_root,
        paper_state_db_path=tmp_path / "missing-paper.sqlite",
        now=datetime(2026, 7, 31, 10, 0, tzinfo=TAIPEI),
        calendar=_Calendar(
            {
                date(2026, 7, 31): (True, "open"),
                date(2026, 7, 30): (True, "open"),
            }
        ),
        lock_path=tmp_path / "shared.lock",
    )

    payload = cast(dict[str, Any], result)
    assert payload["status"] == "blocked_missing_input"
    assert "paper_state_db" in cast(list[str], payload["missing_inputs"])
    assert Path(str(payload["record_path"])).is_file()


def test_main_preserves_outer_block_when_inner_orchestration_completed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        shadow,
        "run",
        lambda **_: {
            "status": "blocked_capacity_post_run",
            "daily_orchestration": {
                "status": "passed_rule_only",
                "orchestration_status": "completed",
                "natural_forward_completion_clock": {
                    "within_forward_completion_window": True,
                },
            },
        },
    )

    assert shadow.main([]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked_capacity_post_run"
    assert payload["daily_orchestration"]["orchestration_status"] == (
        "completed"
    )
