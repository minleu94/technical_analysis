import pytest
from typing import Dict, Any

def test_recommendation_metadata_exists():
    """確保 recommendation_metadata.py 存在且能被匯入"""
    try:
        from ui_qt.views.recommendation.recommendation_metadata import (
            TECHNICAL_DESCRIPTIONS,
            PATTERN_DESCRIPTIONS,
            TECHNICAL_NAME_MAP,
            PATTERN_NAME_MAP,
            DEFAULT_PROFILES
        )
    except ImportError:
        pytest.fail("無法匯入 recommendation_metadata")

def test_technical_descriptions_integrity():
    from ui_qt.views.recommendation.recommendation_metadata import TECHNICAL_DESCRIPTIONS

    # 至少要有基本的技術指標
    assert 'ma' in TECHNICAL_DESCRIPTIONS
    assert 'rsi' in TECHNICAL_DESCRIPTIONS
    assert 'macd' in TECHNICAL_DESCRIPTIONS

    # 檢查結構
    ma_desc = TECHNICAL_DESCRIPTIONS['ma']
    assert ma_desc['category'] == 'Trend'
    assert 'short_label' in ma_desc
    assert 'tooltip_lines' in ma_desc

def test_pattern_descriptions_integrity():
    from ui_qt.views.recommendation.recommendation_metadata import PATTERN_DESCRIPTIONS

    assert 'w_bottom' in PATTERN_DESCRIPTIONS
    assert 'head_shoulder_bottom' in PATTERN_DESCRIPTIONS

    w_desc = PATTERN_DESCRIPTIONS['w_bottom']
    assert w_desc['category'] == 'Reversal'
    assert 'tooltip_lines' in w_desc

def test_name_mapping_integrity():
    from ui_qt.views.recommendation.recommendation_metadata import TECHNICAL_NAME_MAP, PATTERN_NAME_MAP

    assert TECHNICAL_NAME_MAP['移動平均線'] == 'ma'
    assert TECHNICAL_NAME_MAP['RSI'] == 'rsi'
    assert PATTERN_NAME_MAP['W底'] == 'w_bottom'

def test_default_profiles_integrity():
    from ui_qt.views.recommendation.recommendation_metadata import DEFAULT_PROFILES

    assert 'momentum' in DEFAULT_PROFILES
    assert 'stable' in DEFAULT_PROFILES
    assert 'long_term' in DEFAULT_PROFILES

    momentum = DEFAULT_PROFILES['momentum']
    assert momentum['id'] == 'momentum'
    assert 'config' in momentum
    assert momentum['config']['filters']['industry'] == '全部'
