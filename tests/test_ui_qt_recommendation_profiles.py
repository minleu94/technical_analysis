import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QBoxLayout

from app_module.dtos import RegimeResultDTO
from app_module.recommendation_profile_service import (
    RecommendationProfileService,
    RegimeProfileSuggestion,
)
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


def test_builtin_profile_description_shows_weights_filters_and_patterns(tmp_path):
    _app()
    view = RecommendationView(
        recommendation_service=FakeRecommendationService(),
        regime_service=FakeRegimeService(),
        config=None,
    )

    index = view.profile_combo.findData("momentum")
    assert index >= 0
    view.profile_combo.setCurrentIndex(index)

    text = view.profile_desc_label.text()
    assert "型態" in text
    assert "技術" in text
    assert "量能" in text
    assert "主要篩選" in text
    assert "漲幅" in text
    assert "成交量" in text
    assert "旗形" in text


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


def test_regime_confidence_does_not_promote_high_risk_profile(tmp_path):
    _app()
    view = RecommendationView(
        recommendation_service=FakeRecommendationService(),
        regime_service=FakeRegimeService(),
        config=None,
    )

    # Trend has both momentum (high) and long_term (medium).  A high detector
    # confidence must not turn into a high-risk profile recommendation.
    assert view.suggested_profile_id == "long_term"
    text = view.regime_suggestion_label.text()
    assert "Regime 判讀信心：77%" in view.regime_label.text()
    assert "不代表獲利機率或風險預算" in view.regime_label.text()
    assert "Regime 判讀信心 77%" in text
    assert "不代表獲利機率" in text
    assert "未提供風險預算" in text
    assert "不代表個人適配" in text
    assert "風險等級：</b>medium" in text

    view._suggest_profile_for_regime("Trend", 0.01)
    assert view.suggested_profile_id == "long_term"


def test_explicit_profile_selection_is_preserved_when_regime_is_refreshed(tmp_path):
    _app()
    view = RecommendationView(
        recommendation_service=FakeRecommendationService(),
        regime_service=FakeRegimeService(),
        config=None,
    )
    index = view.profile_combo.findData("momentum")
    assert index >= 0
    view.profile_combo.setCurrentIndex(index)

    view._suggest_profile_for_regime("Trend", 0.99)

    assert view.current_profile == "momentum"
    assert view.suggested_profile_id == "momentum"
    assert "沿用使用者已選 Profile" in view.regime_suggestion_label.text()


def test_ui_does_not_present_blocked_selected_profile_as_policy_pass(tmp_path, monkeypatch):
    _app()
    view = RecommendationView(
        recommendation_service=FakeRecommendationService(),
        regime_service=FakeRegimeService(),
        config=None,
    )
    index = view.profile_combo.findData("momentum")
    assert index >= 0
    view.profile_combo.setCurrentIndex(index)

    monkeypatch.setattr(
        view.profile_service,
        "suggest_profile_for_regime",
        lambda *_args, **_kwargs: RegimeProfileSuggestion(
            profile_id="momentum",
            status="blocked",
            reason_code="selected_profile_exceeds_risk_budget",
            reason="目前選擇超過風險預算；不會自動換用另一個 Profile。",
            risk_level="high",
        ),
    )
    view._suggest_profile_for_regime("Trend", 0.99)

    text = view.regime_suggestion_label.text()
    assert "目前選擇（policy 未通過）" in text
    assert "目前選擇超過風險預算" in text
    assert view.apply_suggestion_btn.isHidden()


def test_recommendation_view_reflows_config_and_result_for_narrow_research() -> None:
    _app()
    view = RecommendationView(
        recommendation_service=FakeRecommendationService(),
        regime_service=FakeRegimeService(),
        config=None,
    )
    view.show()
    _app().processEvents()

    view.resize(1366, 768)
    assert view.main_splitter.orientation() == Qt.Horizontal
    assert view.result_title_layout.direction() == QBoxLayout.LeftToRight

    view.resize(390, 844)
    assert view.main_splitter.orientation() == Qt.Vertical
    assert view.result_title_layout.direction() == QBoxLayout.TopToBottom
    assert view.config_scroll.minimumWidth() == 0
    assert view.result_panel.minimumWidth() == 0
    assert view.research_context_label.text().startswith("研究上下文：尚未執行")
