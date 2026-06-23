from decimal import Decimal
import json

from app_module.recommendation_profile_service import RecommendationProfileService


class FakeConfig:
    def __init__(self, root):
        self.root = root

    def resolve_output_path(self, relative_path):
        return self.root / relative_path


class FakeStrategyVersionService:
    def __init__(self, versions):
        self._versions = versions

    def list_versions(self):
        return list(self._versions)


def _builtin_profiles():
    return {
        "momentum": {
            "name": "暴衝策略",
            "version": "1.0.0",
            "description": "偏向趨勢與動能的內建 profile",
            "regime": ["Trend", "Breakout"],
            "regime_not_suitable": ["Reversion"],
            "risk_warning": {"volatility": "高"},
            "config": {
                "signals": {"weights": {"pattern": 2500, "technical": 5500, "volume": 2000}},
                "filters": {"price_change_min": Decimal("2.50")},
            },
        }
    }


def test_profile_options_include_source_labels_and_gate_passed_strategy_versions(tmp_path):
    service = RecommendationProfileService(
        FakeConfig(tmp_path),
        builtin_profiles=_builtin_profiles(),
        strategy_version_service=FakeStrategyVersionService(
            [
                {
                    "version_id": "version_validated",
                    "strategy_id": "breakout_lab",
                    "strategy_version": "1.2.0",
                    "validation_status": "validated",
                    "profile_id": "breakout_profile",
                    "profile_version": "1.2.0",
                    "regime": ["Breakout"],
                    "config": {"signals": {"weights": {"pattern": 3000, "technical": 4500, "volume": 2500}}},
                },
                {
                    "version_id": "version_pending",
                    "strategy_id": "pending_lab",
                    "strategy_version": "0.1.0",
                    "validation_status": "pending",
                    "regime": ["Trend"],
                    "config": {},
                },
                {
                    "version_id": "version_disabled",
                    "strategy_id": "disabled_lab",
                    "strategy_version": "2.0.0",
                    "validation_status": "validated",
                    "profile_enabled": False,
                    "regime": ["Reversion"],
                    "config": {},
                },
            ]
        ),
    )

    service.save_custom_profile(
        name="低波動自訂",
        description="測試用自訂 profile",
        config={"signals": {"weights": {"pattern": 3000, "technical": 5000, "volume": 2000}}},
        applicable_regimes=["Reversion"],
    )

    labels = [profile.display_label for profile in service.list_profiles()]

    assert "內建｜暴衝策略" in labels
    assert "自訂｜低波動自訂" in labels
    assert "策略版本｜breakout_lab v1.2.0" in labels
    assert all("pending_lab" not in label for label in labels)
    assert all("disabled_lab" not in label for label in labels)


def test_custom_profile_json_roundtrip_preserves_decimal_and_bp_without_float(tmp_path):
    service = RecommendationProfileService(FakeConfig(tmp_path), builtin_profiles=_builtin_profiles())

    saved = service.save_custom_profile(
        name="精度測試",
        description="保留 Decimal 與 bp 權重",
        config={
            "signals": {"weights": {"pattern": 3333, "technical": 4444, "volume": 2223}},
            "filters": {
                "price_change_min": Decimal("1.10"),
                "stop_loss_pct": Decimal("5.25"),
            },
        },
        applicable_regimes=["Trend"],
    )

    raw = json.loads((tmp_path / "recommendation" / "profiles" / "custom_profiles.json").read_text(encoding="utf-8"))
    raw_profile = raw["profiles"][0]
    weights = raw_profile["config"]["signals"]["weights"]
    filters = raw_profile["config"]["filters"]

    assert weights == {"pattern": 3333, "technical": 4444, "volume": 2223}
    assert filters["price_change_min"] == "1.10"
    assert filters["stop_loss_pct"] == "5.25"

    loaded = {profile.profile_id: profile for profile in service.list_custom_profiles()}[saved.profile_id]

    assert loaded.validation_label == "自訂，未經回測驗證"
    assert not isinstance(loaded.config["filters"]["price_change_min"], float)
    assert loaded.config["signals"]["weights"]["technical"] == 4444


def test_regime_compatibility_discloses_effect_without_excluding_results(tmp_path):
    service = RecommendationProfileService(FakeConfig(tmp_path), builtin_profiles=_builtin_profiles())
    profile = service.list_profiles()[0]

    match = service.evaluate_regime_compatibility(profile, "Trend")
    mismatch = service.evaluate_regime_compatibility(profile, "Reversion")
    neutral = service.evaluate_regime_compatibility(profile, None)

    assert match.status == "match"
    assert match.score_effect == "bonus"
    assert match.excludes_results is False
    assert mismatch.status == "mismatch"
    assert mismatch.score_effect == "penalty"
    assert mismatch.excludes_results is False
    assert neutral.status == "neutral"
    assert neutral.score_effect == "no_bonus"
    assert neutral.excludes_results is False
