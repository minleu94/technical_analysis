from __future__ import annotations

import json
from pathlib import Path

from app_module.evidence_pipeline_runner import EvidencePipelineRunner, write_pipeline_report
from app_module.evidence_pipeline_runner_dtos import EvidencePipelineRunRequest
from tests.test_evidence_pipeline_runner import _config, _seed_recommendation
from tests.test_evidence_pipeline_smoke import _seed_market_db


def test_markdown_report_contains_required_sections_and_boundaries(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_market_db(config)
    result_id = _seed_recommendation(config)
    summary = EvidencePipelineRunner(config).run(
        EvidencePipelineRunRequest(
            decision_date="2026-07-01",
            sources=("recommendation",),
            result_id=result_id,
            windows=(5,),
        )
    )
    path = tmp_path / "report.md"

    write_pipeline_report(summary, path)

    text = path.read_text(encoding="utf-8")
    assert "Run Metadata" in text
    assert "Step Summary" in text
    assert "Evidence Boundary" in text
    assert "Close-to-close forward return is research evidence only" in text
    lowered = text.lower()
    for forbidden in ("buy", "sell", "target price", "fair price", "high confidence"):
        assert forbidden not in lowered


def test_json_report_is_deterministic_and_keeps_numeric_counts(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_market_db(config)
    result_id = _seed_recommendation(config)
    summary = EvidencePipelineRunner(config).run(
        EvidencePipelineRunRequest(
            decision_date="2026-07-01",
            sources=("recommendation",),
            result_id=result_id,
            windows=(5,),
        )
    )
    path = tmp_path / "report.json"

    write_pipeline_report(summary, path)
    first = path.read_text(encoding="utf-8")
    write_pipeline_report(summary, path)
    second = path.read_text(encoding="utf-8")

    assert first == second
    payload = json.loads(first)
    assert isinstance(payload["events_seen"], int)
    assert payload["scheduler_readiness_after"] != "production_ready"
