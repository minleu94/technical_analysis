import pytest

from qa.full_app_healthcheck.command_advisor import (
    advise_feature_commands,
    render_feature_command_advice_markdown,
)
from qa.full_app_healthcheck.manifest import HealthcheckMode, RiskLevel


def _joined_commands(advice) -> list[str]:
    return [" ".join(command.argv) for command in advice.commands]


def test_command_advisor_returns_quick_feature_commands_and_report_contract():
    advice = advise_feature_commands("update")
    commands = _joined_commands(advice)

    assert advice.feature_id == "update_view"
    assert advice.recommended_mode == HealthcheckMode.QUICK
    assert advice.risk_level == RiskLevel.UI_ONLY
    assert any("scripts\\run_full_app_healthcheck.py --mode quick" in command for command in commands)
    assert any("tests/test_ui_qt_update_view_workbench.py" in command for command in commands)
    assert not any("ui_qt/main.py" in command or "MainWindow" in command for command in commands)
    assert "REPORT.md" in advice.expected_report
    assert "result.json" in advice.expected_report
    assert all(command.non_destructive for command in advice.commands)


def test_command_advisor_promotes_full_only_feature_to_full_mode_with_warning():
    advice = advise_feature_commands("market regime", preferred_mode=HealthcheckMode.QUICK)
    commands = _joined_commands(advice)

    assert advice.feature_id == "market_regime"
    assert advice.recommended_mode == HealthcheckMode.FULL
    assert any("Quick Mode" in warning for warning in advice.warnings)
    assert any("tests/test_ui_qt_market_regime_view.py" in command for command in commands)
    assert any("--mode full" in command for command in commands)
    assert not any("high-risk-dry-run" in command for command in commands)


def test_command_advisor_rejects_unknown_feature_with_known_feature_hint():
    with pytest.raises(ValueError) as excinfo:
        advise_feature_commands("not a feature")

    message = str(excinfo.value)
    assert "Unknown healthcheck feature" in message
    assert "update_view" in message
    assert "decision_desk" in message


def test_command_advisor_markdown_is_paste_ready():
    markdown = render_feature_command_advice_markdown(
        advise_feature_commands("decision desk")
    )

    assert "## Feature QA Command Advice" in markdown
    assert "Daily Decision Desk" in markdown
    assert "- Recommended Mode: `quick`" in markdown
    assert "- Risk: `ui-only`" in markdown
    assert "```powershell" in markdown
    assert "tests/test_ui_qt_decision_desk_view.py" in markdown
    assert "Expected Report" in markdown
