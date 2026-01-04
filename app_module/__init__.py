"""
應用服務層 (Application Service Layer)
提供統一的業務邏輯接口，供 UI（Tkinter/Qt/Web/CLI）調用
"""

from app_module.recommendation_service import RecommendationService
from app_module.screening_service import ScreeningService
from app_module.regime_service import RegimeService
from app_module.update_service import UpdateService
from app_module.backtest_service import BacktestService
from app_module.dtos import (
    RecommendationDTO,
    RecommendationResultDTO,
    RegimeResultDTO, 
    BacktestReportDTO
)

__all__ = [
    'RecommendationService',
    'ScreeningService',
    'RegimeService',
    'UpdateService',
    'BacktestService',
    'RecommendationDTO',
    'RecommendationResultDTO',
    'RegimeResultDTO',
    'BacktestReportDTO',
]

