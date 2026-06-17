from __future__ import annotations

from scripts.inspect_valuation_source_policy import main


def test_valuation_source_policy_cli_reports_guarded_pb_ps(capsys):
    assert main([]) == 0

    output = capsys.readouterr().out
    assert "ready_metrics: pe, pb, ps" in output
    assert "pending_metrics: none" in output
    assert "valuation_source_policy.pb_external_source_required" in output
    assert "valuation_source_policy.ps_external_source_required" in output
