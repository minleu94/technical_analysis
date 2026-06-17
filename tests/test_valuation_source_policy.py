from __future__ import annotations

from data_module.valuation_source_policy import inspect_valuation_source_policy


def test_valuation_source_policy_marks_pe_pb_ps_ready_with_guarded_sources():
    result = inspect_valuation_source_policy()

    assert result.ready_metrics == ("pe", "pb", "ps")
    assert result.pending_metrics == ()
    codes = {diagnostic.code for diagnostic in result.diagnostics}
    assert "valuation_source_policy.pb_external_source_required" in codes
    assert "valuation_source_policy.ps_external_source_required" in codes
    assert result.scoring_engine_connected is False


def test_valuation_source_policy_markdown_is_user_auditable():
    result = inspect_valuation_source_policy()
    markdown = result.to_markdown()

    assert "ready_metrics: pe, pb, ps" in markdown
    assert "pending_metrics: none" in markdown
    assert "scoring_engine_connected: false" in markdown
