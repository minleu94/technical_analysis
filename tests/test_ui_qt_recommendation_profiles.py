import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app_module.dtos import RegimeResultDTO
from app_module.recommendation_profile_service import RecommendationProfileService
from ui_qt.views.recommendation_view import RecommendationView


class FakeConfig:
    def __init__(self, root):
        self.root = root

    def resolve_output_path(self, relative_path):
        return self.root / relative_path


class FakeRecommendationService:
    pass


class FakeRegimeService:
    def detect_regime(self):
        return RegimeResultDTO(
            regime="Trend",
            confidence=0.77,
            regime_name_cn="趨勢追蹤",
            details={"source": "market_regime_detector", "as_of_date": "2026-06-16", "score": 72},
        )

    def get_strategy_config(self, regime):
        return {"regime": regime}


class FakeStrategyVersionService:
    def list_versions(self):
        return [
            {
                "version_id": "version_breakout",
                "strategy_id": "breakout_lab",
                "strategy_version": "1.2.0",
                "validation_status": "validated",
                "profile_id": "breakout_profile",
                "profile_version": "1.2.0",
                "regime": ["Breakout"],
                "config": {"signals": {"weights": {"pattern": 3000, "technical": 4500, "volume": 2500}}},
            }
        ]


def _app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


def _combo_labels(combo):
    return [combo.itemText(index) for index in range(combo.count())]


def test_recommendation_profile_combo_shows_builtin_custom_and_strategy_sources(tmp_path):
    _app()
    profile_service = RecommendationProfileService(
        FakeConfig(tmp_path),
        builtin_profiles=None,
        strategy_version_service=FakeStrategyVersionService(),
    )
    profile_service.save_custom_profile(
        name="我的自訂",
        description="使用者保存的 profile",
        config={"signals": {"weights": {"pattern": 3000, "technical": 5000, "volume": 2000}}},
        applicable_regimes=["Trend"],
    )

    view = RecommendationView(
        recommendation_service=FakeRecommendationService(),
        regime_service=FakeRegimeService(),
        config=None,
        profile_service=profile_service,
    )

    labels = _combo_labels(view.profile_combo)

    assert any(label.startswith("內建｜") for label in labels)
    assert "自訂｜我的自訂" in labels
    assert "策略版本｜breakout_lab v1.2.0" in labels
    assert view.strategy_tendency_group.title() == "目前策略傾向摘要"


def test_selected_profile_explains_regime_compatibility_and_custom_validation(tmp_path):
    _app()
    profile_service = RecommendationProfileService(FakeConfig(tmp_path), builtin_profiles=None)
    custom = profile_service.save_custom_profile(
        name="趨勢自訂",
        description="使用者保存的趨勢 profile",
        config={"signals": {"weights": {"pattern": 3000, "technical": 5000, "volume": 2000}}},
        applicable_regimes=["Trend"],
    )
    view = RecommendationView(
        recommendation_service=FakeRecommendationService(),
        regime_service=FakeRegimeService(),
        config=None,
        profile_service=profile_service,
    )

    index = view.profile_combo.findData(custom.profile_id)
    assert index >= 0
    view.profile_combo.setCurrentIndex(index)

    text = view.profile_desc_label.text()
    assert "自訂，未經回測驗證" in text
    assert "目前 Regime" in text
    assert "適用 Regime" in text
    assert "match" in text
    assert "分數影響" in text
    assert "bonus" in text


def test_view_can_save_current_settings_as_custom_profile(tmp_path):
    _app()
    profile_service = RecommendationProfileService(FakeConfig(tmp_path), builtin_profiles=None)
    view = RecommendationView(
        recommendation_service=FakeRecommendationService(),
        regime_service=FakeRegimeService(),
        config=None,
        profile_service=profile_service,
    )

    saved = view.save_custom_profile_from_current_config("盤整觀察")

    assert saved.validation_label == "自訂，未經回測驗證"
    assert "自訂｜盤整觀察" in _combo_labels(view.profile_combo)
