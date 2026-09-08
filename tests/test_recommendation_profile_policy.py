from __future__ import annotations

from pathlib import Path
from typing import Any

from app_module.recommendation_profile_service import RecommendationProfileService


class FakeConfig:
    def __init__(self, root: Path) -> None:
        self.root = root

    def resolve_output_path(self, relative_path: str) -> Path:
        return self.root / relative_path


def _service(tmp_path: Path, *, risk_levels: bool = True) -> RecommendationProfileService:
    momentum: dict[str, Any] = {
        "name": "高風險",
        "description": "trend momentum",
        "regime": ["Trend", "Breakout"],
        "config": {},
    }
    long_term: dict[str, Any] = {
        "name": "中風險",
        "description": "trend long term",
        "regime": ["Trend", "Breakout"],
        "config": {},
    }
    if risk_levels:
        momentum["risk_level"] = "high"
        long_term["risk_level"] = "medium"
    return RecommendationProfileService(
        FakeConfig(tmp_path),
        builtin_profiles={"momentum": momentum, "long_term": long_term},
    )


def test_missing_risk_budget_chooses_lowest_declared_risk_for_research(tmp_path: Path) -> None:
    service = _service(tmp_path)

    suggestion = service.suggest_profile_for_regime("Trend")

    assert suggestion.profile_id == "long_term"
    assert suggestion.status == "suggested_research"
    assert suggestion.reason_code == "conservative_research_suggestion"
    assert suggestion.risk_level == "medium"
    assert "不代表個人適配" in suggestion.reason


def test_selected_user_profile_is_preserved_without_confidence_promotion(tmp_path: Path) -> None:
    service = _service(tmp_path)

    suggestion = service.suggest_profile_for_regime(
        "Trend",
        selected_profile_id="momentum",
    )

    assert suggestion.profile_id == "momentum"
    assert suggestion.status == "user_selected"
    assert suggestion.reason_code == "user_profile_preserved"
    assert suggestion.risk_level == "high"
    assert "信心" in suggestion.reason
    assert "不推定個人適配" in suggestion.reason


def test_selected_high_risk_profile_is_blocked_by_low_risk_budget(tmp_path: Path) -> None:
    service = _service(tmp_path)

    suggestion = service.suggest_profile_for_regime(
        "Trend",
        selected_profile_id="momentum",
        risk_budget="low",
    )

    assert suggestion.profile_id == "momentum"
    assert suggestion.status == "blocked"
    assert suggestion.reason_code == "selected_profile_exceeds_risk_budget"
    assert suggestion.risk_level == "high"


def test_invalid_budget_blocks_selected_profile_without_replacing_it(tmp_path: Path) -> None:
    service = _service(tmp_path)

    suggestion = service.suggest_profile_for_regime(
        "Trend",
        selected_profile_id="momentum",
        risk_budget="not-a-policy-level",
    )

    assert suggestion.profile_id == "momentum"
    assert suggestion.status == "blocked"
    assert suggestion.reason_code == "invalid_risk_budget"


def test_selected_profile_without_risk_policy_requires_budget_block(tmp_path: Path) -> None:
    service = _service(tmp_path, risk_levels=False)

    preserved = service.suggest_profile_for_regime(
        "Trend",
        selected_profile_id="momentum",
    )
    blocked = service.suggest_profile_for_regime(
        "Trend",
        selected_profile_id="momentum",
        risk_budget="low",
    )

    assert preserved.profile_id == "momentum"
    assert preserved.status == "user_selected"
    assert "不推定個人適配" in preserved.reason
    assert blocked.profile_id == "momentum"
    assert blocked.status == "blocked"
    assert blocked.reason_code == "selected_profile_risk_policy_unavailable"


def test_selected_profile_regime_mismatch_is_explicitly_incompatible(tmp_path: Path) -> None:
    service = _service(tmp_path)

    suggestion = service.suggest_profile_for_regime(
        "Reversion",
        selected_profile_id="momentum",
    )

    assert suggestion.profile_id == "momentum"
    assert suggestion.status == "incompatible"
    assert suggestion.reason_code == "selected_profile_regime_mismatch"


def test_unknown_risk_policy_blocks_automatic_research_suggestion(tmp_path: Path) -> None:
    service = _service(tmp_path, risk_levels=False)

    suggestion = service.suggest_profile_for_regime("Trend")

    assert suggestion.profile_id is None
    assert suggestion.status == "blocked"
    assert suggestion.reason_code == "risk_policy_unavailable"


def test_risk_budget_is_a_constraint_and_never_derived_from_regime_confidence(tmp_path: Path) -> None:
    service = _service(tmp_path)

    low_budget = service.suggest_profile_for_regime("Trend", risk_budget="low")
    invalid_budget = service.suggest_profile_for_regime("Trend", risk_budget="certain")

    assert low_budget.profile_id is None
    assert low_budget.reason_code == "risk_budget_has_no_compatible_profile"
    assert invalid_budget.profile_id is None
    assert invalid_budget.reason_code == "invalid_risk_budget"


def test_unknown_regime_does_not_guess_a_profile(tmp_path: Path) -> None:
    service = _service(tmp_path)

    suggestion = service.suggest_profile_for_regime("Unknown")

    assert suggestion.profile_id is None
    assert suggestion.reason_code == "no_compatible_profile"
