from data_module.config import TWStockConfig
from app_module.preset_service import PresetService
from app_module.strategy_version_service import StrategyVersionService


def test_strategy_params_persistence_roundtrip(tmp_path):
    """驗證 Dynamic Quantile 5 個新參數在 PresetService 與 StrategyVersionService 的儲存與載入 Round-trip 一致性"""

    # 1. 建立隔離的測試設定
    data_root = tmp_path / "data"
    output_root = tmp_path / "output"
    data_root.mkdir()
    output_root.mkdir()

    config = TWStockConfig(
        data_root=data_root,
        output_root=output_root,
        profile="test"
    )

    # 2. 準備測試參數 (包含 Dynamic Quantile 的 5 個新參數)
    test_params = {
        "threshold_mode": "quantile",
        "buy_quantile_bp": 8000,
        "sell_quantile_bp": 4000,
        "quantile_warmup_observations": 60,
        "quantile_method": "nearest_rank",
        "buy_confirm_days": 2,
        "sell_confirm_days": 2,
        "cooldown_days": 3
    }

    # 3. 驗證 PresetService
    preset_service = PresetService(config)

    preset_id = preset_service.save_preset(
        name="Quantile Test Preset",
        strategy_id="momentum_aggressive_v1",
        params=test_params,
        meta={"description": "Test dynamic quantile preset"},
        tags=["test", "quantile"]
    )

    loaded_preset = preset_service.load_preset(preset_id)
    assert loaded_preset is not None
    assert loaded_preset.name == "Quantile Test Preset"
    assert loaded_preset.strategy_id == "momentum_aggressive_v1"

    # 驗證 5 個參數完整重現
    assert loaded_preset.params["threshold_mode"] == "quantile"
    assert loaded_preset.params["buy_quantile_bp"] == 8000
    assert loaded_preset.params["sell_quantile_bp"] == 4000
    assert loaded_preset.params["quantile_warmup_observations"] == 60
    assert loaded_preset.params["quantile_method"] == "nearest_rank"
    assert loaded_preset.params["buy_confirm_days"] == 2

    # 4. 驗證 StrategyVersionService
    version_service = StrategyVersionService(config)

    version_id = version_service.create_version(
        strategy_id="momentum_aggressive_v1",
        strategy_version="1.0.0-quantile",
        params=test_params,
        config={"some_indicator_config": True},
        backtest_summary={"sharpe_ratio": 1.5, "total_return": 0.25},
        regime=["Trend"],
        notes="Test dynamic quantile strategy version"
    )

    # 載入所有版本並篩選出來
    versions = version_service.list_versions("momentum_aggressive_v1")
    target_version = next((v for v in versions if v.get("version_id") == version_id), None)

    assert target_version is not None
    assert target_version["notes"] == "Test dynamic quantile strategy version"

    # 載入詳細版本對象
    loaded_version = version_service.get_version(version_id)
    assert loaded_version is not None

    # 驗證 5 個新參數在版本中的一致性
    assert loaded_version.params["threshold_mode"] == "quantile"
    assert loaded_version.params["buy_quantile_bp"] == 8000
    assert loaded_version.params["sell_quantile_bp"] == 4000
    assert loaded_version.params["quantile_warmup_observations"] == 60
    assert loaded_version.params["quantile_method"] == "nearest_rank"
    assert loaded_version.params["buy_confirm_days"] == 2
