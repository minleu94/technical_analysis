from __future__ import annotations

from datetime import date, datetime
import json
import os
from pathlib import Path
from types import SimpleNamespace
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


def test_status_atomic_write_retries_transient_windows_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "status.json"
    attempts = 0
    real_replace = pipeline.os.replace

    def flaky_replace(source: object, target: object) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("test_windows_replace_lock")
        real_replace(source, target)

    monkeypatch.setattr(pipeline.os, "replace", flaky_replace)
    monkeypatch.setattr(pipeline.time_module, "sleep", lambda _: None)

    pipeline._atomic_write_json(path, {"status": "blocked"})

    assert attempts == 3
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "blocked"


def _write_data_update_status(
    output_root: Path,
    *,
    daily_date: str,
    technical_date: str,
    status: str = "passed",
) -> None:
    _write_json(
        output_root
        / "scheduled"
        / "data_update_quick"
        / "latest_status.json",
        {
            "status": status,
            "steps": [
                {
                    "name": "check_overview_after",
                    "result": {
                        "daily_data": {"latest_date": daily_date},
                        "technical_indicators": {
                            "latest_date": technical_date,
                        },
                    },
                }
            ],
        },
    )


def _with_hash(
    payload: Mapping[str, object],
    *,
    field_name: str,
) -> dict[str, object]:
    result = dict(payload)
    result[field_name] = pipeline._payload_hash(result)
    return result


def _write_official_event_pointer(
    release_root: Path,
) -> tuple[dict[str, str], dict[str, str]]:
    event_root = release_root / "official_market_events"
    run_root = event_root / "runs" / "official-1"
    canonical_path = run_root / "canonical" / "events.jsonl"
    canonical_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_path.write_bytes(b"{\"event\":1}\n")
    canonical_hash = pipeline._file_hash(canonical_path)
    manifest = _with_hash(
        {
            "schema_version": pipeline.OFFICIAL_EVENT_PUBLICATION_SCHEMA_VERSION,
            "status": "formal_source_publication",
            "canonical_events": {
                "path": "canonical/events.jsonl",
                "file_hash": canonical_hash,
            },
        },
        field_name="manifest_hash",
    )
    manifest_path = run_root / "manifest.json"
    _write_json(manifest_path, manifest)
    pointer = {
        "schema_version": pipeline.OFFICIAL_EVENT_POINTER_SCHEMA_VERSION,
        "manifest_path": "runs/official-1/manifest.json",
        "manifest_hash": str(manifest["manifest_hash"]),
        "manifest_file_hash": pipeline._file_hash(manifest_path),
        "canonical_events_hash": canonical_hash,
    }
    _write_json(event_root / "latest_manifest.json", pointer)
    custody = {
        "manifest_hash": str(manifest["manifest_hash"]),
        "manifest_file_hash": pointer["manifest_file_hash"],
        "canonical_events_hash": canonical_hash,
    }
    return pointer, custody


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


def test_automatic_selection_catches_up_when_upstream_t_minus_one_is_stale(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    _write_data_update_status(
        output_root,
        daily_date="2026-07-31",
        technical_date="2026-07-31",
    )
    now = datetime(2026, 8, 1, 11, 33, tzinfo=TAIPEI)
    calendar = _Calendar(
        {
            date(2026, 8, 3): (True, "official_open"),
            date(2026, 8, 1): (True, "official_open"),
            date(2026, 7, 31): (True, "official_open"),
        }
    )

    selection = pipeline._select_decision(
        output_root=output_root,
        calendar=calendar,
        now=now,
    )

    assert selection.requested_decision_at == datetime(
        2026, 8, 3, 8, 30, tzinfo=TAIPEI
    )
    assert selection.decision_at == datetime(
        2026, 8, 1, 8, 30, tzinfo=TAIPEI
    )
    assert selection.strict_t_minus_one == date(2026, 7, 31)
    assert selection.mode == "automatic_catch_up"
    assert selection.selection_reason == (
        "upstream_strict_t_minus_one_not_ready"
    )
    assert len(selection.attempts) == 2


def test_automatic_selection_keeps_next_decision_when_t_minus_one_is_ready(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    _write_data_update_status(
        output_root,
        daily_date="2026-08-01",
        technical_date="2026-08-01",
    )
    now = datetime(2026, 8, 1, 20, 17, tzinfo=TAIPEI)
    calendar = _Calendar(
        {
            date(2026, 8, 3): (True, "official_open"),
            date(2026, 8, 1): (True, "official_open"),
        }
    )

    selection = pipeline._select_decision(
        output_root=output_root,
        calendar=calendar,
        now=now,
    )

    assert selection.decision_at == selection.requested_decision_at
    assert selection.decision_at == datetime(
        2026, 8, 3, 8, 30, tzinfo=TAIPEI
    )
    assert selection.strict_t_minus_one == date(2026, 8, 1)
    assert selection.mode == "requested"
    assert selection.selection_reason == (
        "upstream_strict_t_minus_one_available"
    )


def test_selection_blocks_when_upstream_status_is_missing(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        RuntimeError,
        match="upstream_data_update_proof_missing:status_file_missing",
    ):
        pipeline._select_decision(
            output_root=tmp_path / "output",
            calendar=_Calendar(
                {
                    date(2026, 8, 3): (True, "official_open"),
                    date(2026, 8, 1): (True, "official_open"),
                }
            ),
            now=datetime(2026, 8, 1, 11, 33, tzinfo=TAIPEI),
        )


def test_selection_blocks_when_upstream_status_is_not_passed(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    _write_data_update_status(
        output_root,
        daily_date="2026-08-01",
        technical_date="2026-08-01",
        status="failed",
    )

    with pytest.raises(
        RuntimeError,
        match="upstream_data_update_proof_not_passed:status=failed",
    ):
        pipeline._select_decision(
            output_root=output_root,
            calendar=_Calendar(
                {
                    date(2026, 8, 3): (True, "official_open"),
                    date(2026, 8, 1): (True, "official_open"),
                }
            ),
            now=datetime(2026, 8, 1, 11, 33, tzinfo=TAIPEI),
        )


def test_selection_blocks_when_upstream_status_has_future_core_date(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    _write_data_update_status(
        output_root,
        daily_date="2026-08-04",
        technical_date="2026-08-04",
    )

    with pytest.raises(
        RuntimeError,
        match="upstream_data_update_proof_future_date",
    ):
        pipeline._select_decision(
            output_root=output_root,
            calendar=_Calendar(
                {
                    date(2026, 8, 3): (True, "official_open"),
                    date(2026, 8, 1): (True, "official_open"),
                }
            ),
            now=datetime(2026, 8, 1, 11, 33, tzinfo=TAIPEI),
        )


def test_missing_formal_ooc_is_successful_fail_closed_status(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    _write_data_update_status(
        output_root,
        daily_date="2026-07-31",
        technical_date="2026-07-31",
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
    assert stored["upstream_data_update_proof_state"] == "ready"
    assert stored["upstream_data_update_proof_reason"] == "passed"
    status_hash = stored.pop("status_hash")
    assert status_hash == pipeline._payload_hash(stored)


def test_replay_run_id_includes_immutable_namespace_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    training_path = tmp_path / "training.json"
    training_path.write_bytes(b"training-custody")
    captured: list[str] = []

    def fake_replay(request: object) -> SimpleNamespace:
        captured.append(str(getattr(request, "replay_run_id")))
        return SimpleNamespace(
            status="blocked",
            blockers=("formal_ooc_dataset_full_market_not_ready",),
        )

    monkeypatch.setattr(
        pipeline,
        "build_allocation_oos_portfolio_replay",
        fake_replay,
    )

    with pytest.raises(RuntimeError, match="formal_oos_primary_replay_blocked"):
        pipeline._build_replays(
            release_root=tmp_path / "release",
            training_manifest_path=training_path,
            decision_at=datetime(2026, 7, 31, 8, 30, tzinfo=TAIPEI),
        )

    assert captured == [
        (
            "primary-"
            f"{pipeline.REPLAY_SCHEMA_VERSION}-"
            f"{pipeline.REPLAY_RUN_ID_REVISION}-"
            f"{pipeline._file_hash(training_path)[7:23]}-20260731"
        )
    ]


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


def test_ooc_store_must_match_current_official_event_custody(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "release_v4"
    _, custody = _write_official_event_pointer(release_root)
    store = {"corporate_action_custody": custody}

    pipeline._validate_current_official_event_custody(
        release_root=release_root,
        store=store,
    )

    stale = dict(store)
    stale["corporate_action_custody"] = {
        **custody,
        "canonical_events_hash": f"sha256:{'0' * 64}",
    }
    with pytest.raises(
        ValueError,
        match="formal_ooc_corporate_action_custody_stale:canonical_events_hash",
    ):
        pipeline._validate_current_official_event_custody(
            release_root=release_root,
            store=stale,
        )


def test_ooc_store_allows_same_canonical_timeline_republished_envelope(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "release_v4"
    _, custody = _write_official_event_pointer(release_root)
    republished = {
        "corporate_action_custody": {
            **custody,
            "manifest_hash": f"sha256:{'a' * 64}",
            "manifest_file_hash": f"sha256:{'b' * 64}",
        }
    }

    pipeline._validate_current_official_event_custody(
        release_root=release_root,
        store=republished,
    )


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
    _write_data_update_status(
        output_root,
        daily_date="2026-07-31",
        technical_date="2026-07-31",
    )
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
