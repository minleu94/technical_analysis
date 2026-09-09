from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts import run_daily_ml_allocation_derived_shadow as derived
from scripts import run_daily_ml_allocation_orchestration as orchestration


TAIPEI = ZoneInfo("Asia/Taipei")
DECISION_AT = datetime(2026, 9, 8, 8, 30, tzinfo=TAIPEI)
DEADLINE_AT = datetime(2026, 9, 8, 8, 35, tzinfo=TAIPEI)
OPERATIONAL_HASH = "sha256:" + ("a" * 64)


def test_derived_parser_exposes_exact_forward_contract() -> None:
    args = derived.build_parser().parse_args(
        [
            "--mode",
            derived.FORWARD_MODE,
            "--natural-forward-deadline-at",
            DEADLINE_AT.isoformat(),
            "--pit-machine-operational-publication",
            "operational.json",
            "--pit-machine-operational-publication-file-hash",
            OPERATIONAL_HASH,
        ]
    )

    assert args.natural_forward_deadline_at == DEADLINE_AT.isoformat()
    assert args.pit_machine_operational_publication_file_hash == (
        OPERATIONAL_HASH
    )


def test_orchestration_main_forwards_contract_without_catch_up(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "status": "passed_rule_only",
            "orchestration_status": "completed",
        }

    monkeypatch.setattr(orchestration, "run", fake_run)
    monkeypatch.setattr(
        orchestration,
        "_promotion_trust_configuration",
        lambda **_: ({}, (), None),
    )

    code = orchestration.main(
        [
            "--database",
            str(tmp_path / "twstock.db"),
            "--output-root",
            str(tmp_path / "output"),
            "--decision-at",
            DECISION_AT.isoformat(),
            "--natural-forward-deadline-at",
            DEADLINE_AT.isoformat(),
            "--pit-machine-operational-publication",
            str(tmp_path / "operational.json"),
            "--pit-machine-operational-publication-file-hash",
            OPERATIONAL_HASH,
        ]
    )

    assert code == 0
    assert captured["natural_forward_deadline_at"] == DEADLINE_AT
    assert captured["pit_machine_operational_publication_file_hash"] == (
        OPERATIONAL_HASH
    )
    assert captured["decision_selection_mode"] == "requested"
    output = json.loads(capsys.readouterr().out)
    assert output["orchestration_status"] == "completed"


def test_derived_main_emits_daily_orchestration_payload_at_stdout(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    daily_payload = {
        "status": "passed_rule_only",
        "orchestration_status": "completed",
        "natural_forward_completion_clock": {
            "post_inference_completed_at": "2026-09-08T00:34:00+00:00",
            "observation_emitted_at": "2026-09-08T00:34:01+00:00",
            "within_forward_completion_window": True,
            "within_forward_emission_window": True,
        },
    }

    def fake_run(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "status": "completed",
            "daily_orchestration": daily_payload,
            "record_path": str(tmp_path / "record.json"),
        }

    monkeypatch.setattr(derived, "run", fake_run)

    code = derived.main(
        [
            "--mode",
            derived.FORWARD_MODE,
            "--decision-at",
            DECISION_AT.isoformat(),
            "--natural-forward-deadline-at",
            DEADLINE_AT.isoformat(),
            "--pit-machine-operational-publication-file-hash",
            OPERATIONAL_HASH,
        ]
    )

    assert code == 0
    assert captured["natural_forward_deadline_at"] == DEADLINE_AT
    assert captured["pit_machine_operational_publication_file_hash"] == (
        OPERATIONAL_HASH
    )
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "completed"
    assert output["daily_orchestration"] == daily_payload
    assert output["record_path"] == str(tmp_path / "record.json")
