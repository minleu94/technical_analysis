import pytest

from qa.full_app_healthcheck.manifest import HealthcheckManifest, HealthcheckMode, HealthcheckStep, RiskLevel
from qa.full_app_healthcheck.runner import HealthcheckRunner
from scripts.run_full_app_healthcheck import parse_args


def test_runner_dispatches_registered_action(tmp_path):
    calls = []

    def fake_action(context, step):
        calls.append((context["name"], step.id))
        return {"message": "ok"}

    manifest = HealthcheckManifest(
        id="test",
        title="測試",
        modes=(HealthcheckMode.QUICK,),
        steps=(
            HealthcheckStep(
                id="S-001",
                title="測試步驟",
                mode=HealthcheckMode.QUICK,
                workspace="測試",
                action="fake_action",
                risk=RiskLevel.UI_ONLY,
            ),
        ),
    )
    runner = HealthcheckRunner(
        manifest=manifest,
        actions={"fake_action": fake_action},
        context={"name": "ctx"},
        output_dir=tmp_path,
    )

    result = runner.run(HealthcheckMode.QUICK)

    assert calls == [("ctx", "S-001")]
    assert result.status == "passed"
    assert result.steps[0].status == "passed"


def test_full_app_healthcheck_cli_parse_mode_and_output():
    args = parse_args(["--mode", "full", "--output-dir", "out", "--fail-fast"])

    assert args.mode == "full"
    assert args.output_dir == "out"
    assert args.fail_fast is True
