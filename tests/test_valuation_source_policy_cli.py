from __future__ import annotations

from scripts.inspect_valuation_source_policy import main


def test_valuation_source_policy_cli_reports_pending_pb_ps(capsys):
    assert main([]) == 0

    output = capsys.readouterr().out
    assert "ready_metrics: pe" in output
    assert "pending_metrics: pb, ps" in output
    assert "valuation_source_policy.pb_source_pending" in output
    assert "valuation_source_policy.ps_source_pending" in output
