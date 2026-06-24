import pytest

from qa.full_app_healthcheck.manifest import (
    HealthcheckManifest,
    HealthcheckMode,
    HealthcheckStep,
    RiskLevel,
)
from qa.full_app_healthcheck.safety import validate_non_destructive_manifest
from qa.full_app_healthcheck.default_manifest import build_default_manifest
from scripts.run_full_app_healthcheck import build_action_registry


def test_non_destructive_manifest_rejects_write_step():
    manifest = HealthcheckManifest(
        id="test",
        title="測試",
        modes=(HealthcheckMode.QUICK,),
        steps=(
            HealthcheckStep(
                id="U-WRITE",
                title="不應執行快速更新",
                mode=HealthcheckMode.QUICK,
                workspace="數據更新",
                action="click_quick_update",
                risk=RiskLevel.WRITES_DATA,
            ),
        ),
    )

    with pytest.raises(ValueError, match="非破壞模式禁止"):
        validate_non_destructive_manifest(manifest)


def test_non_destructive_manifest_allows_dialog_cancel_step():
    manifest = HealthcheckManifest(
        id="test",
        title="測試",
        modes=(HealthcheckMode.HIGH_RISK_DRY_RUN,),
        steps=(
            HealthcheckStep(
                id="U-031",
                title="強制合併取消流程",
                mode=HealthcheckMode.HIGH_RISK_DRY_RUN,
                workspace="數據更新",
                action="assert_force_merge_cancel_dialog",
                risk=RiskLevel.HIGH_RISK_CANCEL_ONLY,
            ),
        ),
    )

    validate_non_destructive_manifest(manifest)


def test_default_manifest_contains_all_release_modes():
    manifest = build_default_manifest()

    assert HealthcheckMode.QUICK in manifest.modes
    assert HealthcheckMode.FULL in manifest.modes
    assert manifest.steps_for_mode(HealthcheckMode.QUICK)
    assert manifest.steps_for_mode(HealthcheckMode.FULL)


def test_all_manifest_steps_have_registered_actions():
    manifest = build_default_manifest()
    registry = build_action_registry()
    for step in manifest.steps:
        assert step.action in registry, f"步驟 {step.id} 的 action '{step.action}' 未在 action registry 中註冊！"


def test_all_registered_actions_have_test_coverage():
    import tests.test_full_app_healthcheck_actions as test_actions

    registry = build_action_registry()
    action_test_names = dir(test_actions)

    for action_name in registry:
        expected_test = f"test_{action_name}"
        found = expected_test in action_test_names
        assert found, f"Registered action '{action_name}' is missing test coverage (expected '{expected_test}' to exist in test_actions)!"
