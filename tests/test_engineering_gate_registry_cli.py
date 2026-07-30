import json
from pathlib import Path

from scripts.manage_engineering_gate_registry import main


def _payload(revision: int = 1) -> dict[str, object]:
    return {
        "item_id": "evidence:weekly-history",
        "revision": revision,
        "category": "waiting_for_time",
        "title": "Accumulate weekly evidence history",
        "status": "waiting",
        "owner": "evidence-owner",
        "earliest_validation_date": "2026-08-01",
        "progress_bp": 3333,
        "required_artifacts": ["weekly-history.json"],
        "validation_commands": ["python inspect.py"],
        "completion_rules": ["three observed weeks"],
        "prohibited_actions": ["do not synthesize elapsed time"],
        "notes": "1/3 weeks",
        "completion_evidence": [],
    }


def test_cli_appends_and_lists_latest_revision(tmp_path: Path, capsys) -> None:
    db = tmp_path / "control.sqlite"
    source = tmp_path / "gate.json"
    source.write_text(json.dumps(_payload()), encoding="utf-8")

    assert main(["--db", str(db), "append", "--input", str(source)]) == 0
    _ = capsys.readouterr()
    assert main(["--db", str(db), "list-latest"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["item_id"] == "evidence:weekly-history"
    assert payload[0]["revision"] == 1


def test_cli_duplicate_revision_fails_without_overwrite(tmp_path: Path, capsys) -> None:
    db = tmp_path / "control.sqlite"
    source = tmp_path / "gate.json"
    source.write_text(json.dumps(_payload()), encoding="utf-8")
    assert main(["--db", str(db), "append", "--input", str(source)]) == 0
    _ = capsys.readouterr()
    assert main(["--db", str(db), "append", "--input", str(source)]) == 2


def test_cli_history_preserves_revisions(tmp_path: Path, capsys) -> None:
    db = tmp_path / "control.sqlite"
    for revision in (1, 2):
        source = tmp_path / f"gate-{revision}.json"
        source.write_text(json.dumps(_payload(revision)), encoding="utf-8")
        assert main(["--db", str(db), "append", "--input", str(source)]) == 0
        _ = capsys.readouterr()
    assert main(["--db", str(db), "history", "--item-id", "evidence:weekly-history"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [item["revision"] for item in payload] == [1, 2]


def test_cli_appends_json_array_atomically(tmp_path: Path, capsys) -> None:
    db = tmp_path / "control.sqlite"
    source = tmp_path / "gates.json"
    second = _payload()
    second["item_id"] = "paper:elapsed-observation"
    source.write_text(json.dumps([_payload(), second]), encoding="utf-8")

    assert main(["--db", str(db), "append", "--input", str(source)]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert [item["item_id"] for item in payload] == [
        "evidence:weekly-history",
        "paper:elapsed-observation",
    ]
