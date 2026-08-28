import json
from datetime import date
from pathlib import Path

import pytest

from scripts.render_p0_owner_decision_packet import (
    render_owner_decision_packet,
)
from scripts.run_p0_source_evidence_audit import build_p0_source_evidence_audit


def _audit_payload() -> dict:
    payload = build_p0_source_evidence_audit(date(2026, 7, 26))
    assert isinstance(payload, dict)
    return payload


def test_renderer_preserves_group_questions_and_safety_boundary() -> None:
    rendered = render_owner_decision_packet(_audit_payload())

    assert rendered.startswith("# P0 Owner Decision Packet")
    assert rendered.count("## ") == 7  # rules, five groups, plus the safety section
    assert "twse_market_corporate" in rendered
    assert "mops_monthly_quarterly" in rendered
    assert "formal_oos_allowed=false" in rendered
    assert "accepted 或 limited" in rendered
    assert "raw_row" not in rendered


def test_cli_input_boundary_rejects_missing_grouped_packet() -> None:
    payload = _audit_payload()
    payload.pop("grouped_owner_decision_packet")

    with pytest.raises(ValueError, match="grouped owner packet"):
        render_owner_decision_packet(payload)


def test_cli_writes_non_production_markdown_and_rejects_same_input(
    tmp_path: Path,
) -> None:
    source = tmp_path / "audit.json"
    output = tmp_path / "owner-packet.md"
    source.write_text(json.dumps(_audit_payload(), ensure_ascii=False), encoding="utf-8")

    from scripts.render_p0_owner_decision_packet import main

    assert main(["--input", str(source), "--output", str(output)]) == 0
    assert "# P0 Owner Decision Packet" in output.read_text(encoding="utf-8")
    assert main(["--input", str(source), "--output", str(source)]) == 2
