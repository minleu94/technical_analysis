"""
推薦引擎模組（舊版，已棄用）

⚠️ 警告：此模組已棄用，請使用 app_module.recommendation_service.RecommendationService 替代。

此模組保留僅為向後兼容，新專案請勿使用。
"""

import warnings

# 發出棄用警告
warnings.warn(
    "recommendation_module 已棄用，請使用 app_module.recommendation_service.RecommendationService 替代。"
    "此模組將在未來版本中移除。",
    DeprecationWarning,
    stacklevel=2
)

from .recommendation_engine import RecommendationEngine

__all__ = ['RecommendationEngine']
