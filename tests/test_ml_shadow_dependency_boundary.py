from pathlib import Path

from ml_module.shadow_boundary_guard import MLShadowBoundaryGuard


ROOT = Path(__file__).resolve().parents[1]


def test_repository_respects_ml_shadow_dependency_boundary() -> None:
    report = MLShadowBoundaryGuard(ROOT).inspect()

    assert report.violations == ()
    assert report.shadow_only is True


def test_guard_detects_production_import_of_ml_module(tmp_path: Path) -> None:
    (tmp_path / "app_module").mkdir()
    (tmp_path / "ml_module").mkdir()
    (tmp_path / "app_module" / "bad.py").write_text(
        "from ml_module.boosted_challengers import BoostedShadowChallengerTrainer\n",
        encoding="utf-8",
    )

    report = MLShadowBoundaryGuard(tmp_path).inspect()

    assert any("production_imports_ml_module" in item for item in report.violations)


def test_guard_detects_ml_import_of_production_decision_path(tmp_path: Path) -> None:
    (tmp_path / "ml_module").mkdir()
    (tmp_path / "ml_module" / "bad.py").write_text(
        "from decision_module.scoring import ScoringEngine\n", encoding="utf-8"
    )

    report = MLShadowBoundaryGuard(tmp_path).inspect()

    assert any("ml_imports_production_path" in item for item in report.violations)


def test_guard_detects_true_production_flag(tmp_path: Path) -> None:
    (tmp_path / "ml_module").mkdir()
    (tmp_path / "ml_module" / "bad.py").write_text(
        "production_eligible = True\n", encoding="utf-8"
    )

    report = MLShadowBoundaryGuard(tmp_path).inspect()

    assert any("forbidden_true_flag" in item for item in report.violations)
