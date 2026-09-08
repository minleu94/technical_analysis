from __future__ import annotations

from datetime import datetime
from pathlib import Path

import scripts.publish_formal_pit_sector_sidecar as cli


def test_public_cli_passes_one_real_current_clock_to_publisher(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    observed: dict[str, object] = {}

    def fake_publish(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return {
            "status": "blocked",
            "formal_ready": False,
            "candidate_only": True,
            "blockers": ["cutoff"],
        }

    monkeypatch.setattr(cli, "publish_formal_pit_sector_sidecar", fake_publish)
    started = datetime.now().astimezone()
    result = cli.main(
        [
            "--handoff-path",
            str(tmp_path / "handoff.json"),
            "--denominator-path",
            str(tmp_path / "denominator.json"),
            "--publication-root",
            str(tmp_path / "publication"),
        ]
    )
    finished = datetime.now().astimezone()

    assert result == 2
    decision = observed["decision_at"]
    now = observed["now"]
    assert isinstance(decision, datetime)
    assert isinstance(now, datetime)
    assert decision == now
    assert started <= decision.astimezone(started.tzinfo) <= finished
    assert '"status": "blocked"' in capsys.readouterr().out


def test_public_cli_returns_nonzero_for_missing_evidence(
    tmp_path: Path,
    capsys,
) -> None:
    result = cli.main(
        [
            "--handoff-path",
            str(tmp_path / "missing-handoff.json"),
            "--denominator-path",
            str(tmp_path / "missing-denominator.json"),
            "--publication-root",
            str(tmp_path / "publication"),
        ]
    )

    assert result == 2
    output = capsys.readouterr().out
    assert '"status": "blocked"' in output
