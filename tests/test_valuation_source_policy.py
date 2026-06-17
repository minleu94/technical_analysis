from __future__ import annotations

from data_module.valuation_source_policy import inspect_valuation_source_policy


def test_valuation_source_policy_marks_pe_ready_and_pb_ps_pending():
    result = inspect_valuation_source_policy()

    assert result.ready_metrics == ("pe",)
    assert result.pending_metrics == ("pb", "ps")
    codes = {diagnostic.code for diagnostic in result.diagnostics}
    assert "valuation_source_policy.pb_source_pending" in codes
    assert "valuation_source_policy.ps_source_pending" in codes
    assert result.scoring_engine_connected is False


def test_valuation_source_policy_markdown_is_user_auditable():
    result = inspect_valuation_source_policy()
    markdown = result.to_markdown()

    assert "ready_metrics: pe" in markdown
    assert "pending_metrics: pb, ps" in markdown
    assert "scoring_engine_connected: false" in markdown
