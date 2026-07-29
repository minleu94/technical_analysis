from __future__ import annotations

from scripts.capture_external_evidence_manual import main


def test_cli_defaults_to_dry_run(tmp_path, capsys) -> None:
    exit_code = main(["--db", str(tmp_path / "evidence.sqlite")])

    assert exit_code == 0
    assert "write_performed=false" in capsys.readouterr().out


def test_cli_rejects_non_shadow_output_root(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "--db",
            str(tmp_path / "evidence.sqlite"),
            "--output-root",
            str(tmp_path / "formal-data"),
            "--confirm",
            "append-external-evidence",
        ]
    )

    assert exit_code == 2
    assert "shadow" in capsys.readouterr().out


def test_cli_rejects_capture_without_manual_observed_declaration(tmp_path, capsys) -> None:
    artifact = tmp_path / "snapshot.json"
    artifact.write_text('{"capture_kind":"historical_replay"}', encoding="utf-8")

    exit_code = main(
        [
            "--db", str(tmp_path / "evidence.sqlite"), "--snapshot-json", str(artifact),
            "--confirm", "append-external-evidence",
        ]
    )

    assert exit_code == 2
    assert "manual_observed" in capsys.readouterr().out


def test_cli_rejects_snapshot_without_hash_addressed_decision_output(tmp_path, capsys) -> None:
    artifact = tmp_path / "snapshot.json"
    artifact.write_text(
        '{"capture_kind":"manual_observed","parent_artifact_ids":["lane:20260729"]}',
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--db", str(tmp_path / "evidence.sqlite"), "--snapshot-json", str(artifact),
            "--confirm", "append-external-evidence",
        ]
    )

    assert exit_code == 2
    assert "decision_output_lineage_missing" in capsys.readouterr().out
