from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_cli_module():
    script_path = ROOT / "scripts" / "train_ml_allocation_out_of_core.py"
    spec = importlib.util.spec_from_file_location(
        "test_train_ml_allocation_out_of_core_profile_cli",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _base_args() -> list[str]:
    return [
        "--store-manifest",
        "store.json",
        "--output-dir",
        "output",
        "--profile",
        "minimal_linear_shadow",
    ]


def test_minimal_linear_shadow_requires_one_explicit_horizon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_cli_module()

    class _UnexpectedService:
        def __init__(self) -> None:
            raise AssertionError("training service must not start")

    monkeypatch.setattr(module, "AllocationOutOfCoreTrainingService", _UnexpectedService)

    with pytest.raises(SystemExit, match="恰好一個 --horizon"):
        module.main(_base_args() + ["--algorithm", "ridge_logistic"])


def test_minimal_linear_shadow_rejects_hgb_mixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_cli_module()

    class _UnexpectedService:
        def __init__(self) -> None:
            raise AssertionError("training service must not start")

    monkeypatch.setattr(module, "AllocationOutOfCoreTrainingService", _UnexpectedService)

    with pytest.raises(SystemExit, match="只允許 --algorithm ridge_logistic"):
        module.main(
            _base_args()
            + [
                "--algorithm",
                "ridge_logistic",
                "--algorithm",
                "hist_gradient_boosting",
                "--horizon",
                "20",
            ]
        )


def test_minimal_linear_shadow_passes_profile_and_complexity_policy(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_cli_module()
    captured: dict[str, object] = {}

    class _Publication:
        run_id = "run-test"
        manifest_path = Path("output/manifest.json")
        manifest_hash = "sha256:" + ("a" * 64)
        manifest_file_hash = "sha256:" + ("b" * 64)
        base_expert_count = 1
        meta_fold_count = 1
        formal_oos_allowed = False
        production_alpha_bp = 0

    class _RecordingService:
        def train(self, request: object) -> _Publication:
            captured["request"] = request
            return _Publication()

    monkeypatch.setattr(module, "AllocationOutOfCoreTrainingService", _RecordingService)
    monkeypatch.setattr(
        module,
        "build_allocation_oos_replay_inputs",
        lambda _: SimpleNamespace(
            status="blocked",
            blockers=("fixture_only",),
            manifest_path=None,
            manifest_hash=None,
        ),
    )

    exit_code = module.main(
        _base_args()
        + [
            "--algorithm",
            "ridge_logistic",
            "--horizon",
            "20",
        ]
    )

    assert exit_code == 0
    request = captured["request"]
    assert request.algorithms == ("ridge_logistic",)
    assert request.horizons == (20,)
    assert request.training_profile == "minimal_linear_shadow"
    assert request.profile == "minimal_linear_shadow"
    assert request.complexity_policy == {
        "algorithm_count": 1,
        "horizon_count": 1,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
    }

    summary = json.loads(capsys.readouterr().out)
    assert summary["training_profile"] == "minimal_linear_shadow"
    assert summary["complexity_policy"] == request.complexity_policy
    assert summary["formal_oos_allowed"] is False
    assert summary["production_alpha_bp"] == 0
