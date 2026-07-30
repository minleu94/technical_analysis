from __future__ import annotations

from datetime import date, datetime
import json
import os
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo

import pytest

from ml_module.allocation_promotion_evidence_builder import (
    AllocationPromotionEvidenceBuildResult,
)
from scripts import run_ml_promotion_evidence_pipeline as pipeline


TAIPEI = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 31, 5, 17, tzinfo=TAIPEI)


class _Calendar:
    def __init__(
        self,
        states: Mapping[date, tuple[bool | None, str]],
    ) -> None:
        self._states = dict(states)

    def is_official_trading_day(
        self,
        target_date: date,
    ) -> tuple[bool | None, str]:
        return self._states.get(target_date, (False, "closed"))


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _with_hash(
    payload: Mapping[str, object],
    *,
    field_name: str,
) -> dict[str, object]:
    result = dict(payload)
    result[field_name] = pipeline._payload_hash(result)
    return result


def test_decision_window_uses_official_calendar_and_strict_t_minus_one() -> None:
    calendar = _Calendar(
        {
            date(2026, 7, 31): (True, "official_open"),
            date(2026, 7, 30): (True, "official_open"),
        }
    )

    decision_at, reason = pipeline._next_official_decision(
        now=NOW,
        calendar=calendar,
    )
    t_minus_one, prior_reason = pipeline._strict_previous_trading_day(
        decision_date=decision_at.date(),
        calendar=calendar,
    )

    assert decision_at == datetime(2026, 7, 31, 8, 30, tzinfo=TAIPEI)
    assert reason == "official_open"
    assert t_minus_one == date(2026, 7, 30)
    assert prior_reason == "official_open"


def test_missing_formal_ooc_is_successful_fail_closed_status(
    tmp_path: Path,
) -> None:
    result = pipeline.run(
        output_root=tmp_path / "output",
        database_path=tmp_path / "twstock.db",
        now=NOW,
        calendar=_Calendar(
            {
                date(2026, 7, 31): (True, "official_open"),
                date(2026, 7, 30): (True, "official_open"),
            }
        ),
    )

    assert result["status"] == "blocked"
    assert result["compatible_evidence_published"] is False
    assert result["formal_oos_allowed"] is False
    assert result["production_blend_alpha_bp"] == 0
    assert result["broker_order_allowed"] is False
    assert "FileNotFoundError" in str(result["blockers"])
    status_path = (
        tmp_path
        / "output"
        / "scheduled"
        / "ml_promotion_evidence"
        / "latest_status.json"
    )
    stored = json.loads(status_path.read_text(encoding="utf-8"))
    status_hash = stored.pop("status_hash")
    assert status_hash == pipeline._payload_hash(stored)


def test_training_pointer_discovers_only_hash_bound_store(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "release_v4"
    training_root = (
        release_root
        / "portfolio_ml_direct_ooc_training_production_v4_v5"
    )
    run_root = training_root / "runs" / "training-1"
    store_path = release_root / "store" / "runs" / "store-1" / "manifest.json"
    store = _with_hash(
        {
            "schema_version": pipeline.STORE_SCHEMA_VERSION,
            "status": "complete",
        },
        field_name="manifest_hash",
    )
    _write_json(store_path, store)
    training = _with_hash(
        {
            "schema_version": pipeline.TRAINING_SCHEMA_VERSION,
            "status": "complete",
            "run_id": "training-1",
            "formal_source_only": True,
            "research_shadow_included": False,
            "store_manifest_path": os.path.relpath(
                store_path,
                run_root,
            ).replace("\\", "/"),
            "store_manifest_file_hash": pipeline._file_hash(store_path),
        },
        field_name="manifest_hash",
    )
    training_path = run_root / "manifest.json"
    _write_json(training_path, training)
    _write_json(
        training_root / "latest_manifest.json",
        {
            "schema_version": pipeline.TRAINING_POINTER_SCHEMA_VERSION,
            "manifest_path": "runs/training-1/manifest.json",
            "manifest_hash": training["manifest_hash"],
        },
    )

    discovered_training, discovered_store, run_id = (
        pipeline._discover_training_and_store(
            release_root=release_root,
        )
    )

    assert discovered_training == training_path.resolve()
    assert discovered_store == store_path.resolve()
    assert run_id == "training-1"


def test_replay_discovery_requires_complete_pointer_and_physical_hash(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "release_v4"
    replay_root = (
        release_root
        / "ml_allocation_oos_replay_production_v4"
        / "primary"
    )
    replay = {
        "schema_version": pipeline.REPLAY_SCHEMA_VERSION,
        "status": "complete",
        "replay_run_id": "primary-1",
        "replay_result_hash": f"sha256:{'a' * 64}",
    }
    replay_path = replay_root / "runs" / "primary-1" / "replay.json"
    _write_json(replay_path, replay)
    pointer_path = replay_root / "latest_replay.json"
    _write_json(
        pointer_path,
        {
            "schema_version": pipeline.REPLAY_POINTER_SCHEMA_VERSION,
            "status": "complete",
            "replay_path": str(replay_path.resolve()),
            "replay_file_hash": pipeline._file_hash(replay_path),
            "replay_result_hash": replay["replay_result_hash"],
            "replay_run_id": replay["replay_run_id"],
        },
    )

    assert pipeline._discover_replay(
        release_root=release_root,
        lane="primary",
    ) == (
        replay_path.resolve(),
        replay["replay_result_hash"],
        replay["replay_run_id"],
    )

    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["replay_file_hash"] = f"sha256:{'b' * 64}"
    _write_json(pointer_path, pointer)
    with pytest.raises(ValueError, match="physical hash mismatch"):
        pipeline._discover_replay(
            release_root=release_root,
            lane="primary",
        )


def test_published_builder_result_is_exposed_but_never_self_authorized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "output"
    release_root = output_root / "release_v4"
    custody_root = release_root / "custody"
    custody_root.mkdir(parents=True)
    training = custody_root / "training.json"
    dataset = custody_root / "dataset.json"
    replay_a = custody_root / "replay-a.json"
    replay_b = custody_root / "replay-b.json"
    reference = custody_root / "reference.json"
    metrics = custody_root / "metrics.json"
    shadow_db = (
        output_root
        / "scheduled"
        / "ml_allocation_copilot"
        / "shadow_evidence_collector"
        / "shadow_evidence.sqlite"
    )
    for path in (
        training,
        dataset,
        replay_a,
        replay_b,
        reference,
        metrics,
        shadow_db,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"{}")
    latest_pointer = (
        release_root
        / "ml_allocation_promotion_evidence"
        / "latest_pointer.json"
    )
    latest_pointer.parent.mkdir(parents=True)
    latest_pointer.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        pipeline,
        "_discover_training_and_store",
        lambda **_kwargs: (training, dataset, "training-1"),
    )
    monkeypatch.setattr(
        pipeline,
        "_build_replays",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        pipeline,
        "_discover_replay",
        lambda *, lane, **_kwargs: (
            replay_a if lane == "primary" else replay_b,
            f"sha256:{'a' * 64}",
            f"{lane}-run",
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_discover_reference",
        lambda **_kwargs: (reference, pipeline._file_hash(reference)),
    )
    monkeypatch.setattr(
        pipeline,
        "_discover_reference_metrics",
        lambda **_kwargs: metrics,
    )
    captured: dict[str, object] = {}

    def fake_builder(request: object) -> AllocationPromotionEvidenceBuildResult:
        captured["request"] = request
        return AllocationPromotionEvidenceBuildResult(
            status="published",
            decision_at="2026-07-31T08:30:00+08:00",
            as_of_date="2026-07-30",
            blockers=(),
            publication_id="publication-1",
            publication_hash=f"sha256:{'b' * 64}",
            evidence_hash=f"sha256:{'c' * 64}",
            pointer_hash=f"sha256:{'d' * 64}",
            latest_pointer_path=latest_pointer,
        )

    monkeypatch.setattr(
        pipeline,
        "build_compatible_allocation_promotion_evidence",
        fake_builder,
    )

    result = pipeline.run(
        output_root=output_root,
        database_path=tmp_path / "twstock.db",
        now=NOW,
        calendar=_Calendar(
            {
                date(2026, 7, 31): (True, "official_open"),
                date(2026, 7, 30): (True, "official_open"),
            }
        ),
    )

    assert result["status"] == "published"
    assert result["compatible_evidence_published"] is True
    assert result["authority_required"] is True
    assert result["authorization_artifact_created"] is False
    assert result["formal_oos_allowed"] is False
    assert result["production_blend_alpha_bp"] == 0
    assert result["broker_order_allowed"] is False
    request = captured["request"]
    assert getattr(request, "as_of_date") == date(2026, 7, 30)
    assert getattr(request, "shadow_sidecar_database_path") == (
        shadow_db.resolve()
    )
