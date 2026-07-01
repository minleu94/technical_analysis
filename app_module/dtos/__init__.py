"""
數據傳輸對象 (Data Transfer Objects)
定義服務層的輸入輸出結構
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum
import pandas as pd

from app_module.dtos.portfolio_dtos import (
    JournalEntryDTO,
    PortfolioDTO,
    PositionDTO,
    TradeDTO,
)


class ValidationStatus(Enum):
    """驗證狀態（Phase 3.5 SOP 護欄）"""
    PASS = "PASS"  # 符合 SOP，無問題
    WARNING = "WARNING"  # 有警告但不阻擋
    FAIL = "FAIL"  # 不符合 SOP，禁止 Promote


@dataclass
class RecommendationDTO:
    """股票推薦數據傳輸對象"""
    stock_code: str
    stock_name: str
    close_price: float
    price_change: float  # 漲幅百分比
    total_score: float
    indicator_score: float
    pattern_score: float
    volume_score: float
    recommendation_reasons: str
    industry: str
    regime_match: bool
    
    # 追溯元數據
    score_percentile_bp: Optional[int] = None
    eligible_universe_size: Optional[int] = None
    eligible_universe_date: Optional[str] = None
    ranking_method: Optional[str] = None
    threshold_mode: str = "fixed"
    
    def to_dict(self) -> dict:
        """轉換為字典"""
        result = {
            '證券代號': self.stock_code,
            '證券名稱': self.stock_name,
            '收盤價': self.close_price,
            '漲幅%': self.price_change,
            '總分': self.total_score,
            '指標分': self.indicator_score,
            '圖形分': self.pattern_score,
            '成交量分': self.volume_score,
            '推薦理由': self.recommendation_reasons,
            '產業': self.industry,
            'Regime匹配': '是' if self.regime_match else '否',
            'score_percentile_bp': self.score_percentile_bp,
            'eligible_universe_size': self.eligible_universe_size,
            'eligible_universe_date': self.eligible_universe_date,
            'ranking_method': self.ranking_method,
            'threshold_mode': self.threshold_mode
        }
        if self.threshold_mode == "quantile":
            result['百分位'] = f"{self.score_percentile_bp / 100:.2f}%" if self.score_percentile_bp is not None else "N/A"
            result['母體數'] = self.eligible_universe_size if self.eligible_universe_size is not None else "N/A"
            result['排名日期'] = self.eligible_universe_date if self.eligible_universe_date is not None else "N/A"
            result['排名方法'] = self.ranking_method if self.ranking_method is not None else "N/A"
            result['門檻模式'] = '百分位'
        return result

    @classmethod
    def from_dict(cls, data: dict) -> 'RecommendationDTO':
        """從字典還原 RecommendationDTO，支援英文與舊有中文 key，並確保對歷史欄位的相容性"""
        stock_code = data.get('stock_code', data.get('證券代號', ''))
        stock_name = data.get('stock_name', data.get('證券名稱', ''))
        close_price = data.get('close_price', data.get('收盤價', 0.0))
        price_change = data.get('price_change', data.get('漲幅%', 0.0))
        total_score = data.get('total_score', data.get('總分', 0.0))
        indicator_score = data.get('indicator_score', data.get('指標分', 0.0))
        pattern_score = data.get('pattern_score', data.get('圖形分', 0.0))
        volume_score = data.get('volume_score', data.get('成交量分', 0.0))
        recommendation_reasons = data.get('recommendation_reasons', data.get('推薦理由', ''))
        industry = data.get('industry', data.get('產業', ''))
        
        regime_match_val = data.get('regime_match', data.get('Regime匹配', False))
        if isinstance(regime_match_val, str):
            regime_match = (regime_match_val == '是')
        else:
            regime_match = bool(regime_match_val)
            
        score_percentile_bp = data.get('score_percentile_bp')
        eligible_universe_size = data.get('eligible_universe_size')
        eligible_universe_date = data.get('eligible_universe_date')
        ranking_method = data.get('ranking_method')
        threshold_mode = data.get('threshold_mode', 'fixed')
        
        return cls(
            stock_code=str(stock_code),
            stock_name=str(stock_name),
            close_price=float(close_price),
            price_change=float(price_change),
            total_score=float(total_score),
            indicator_score=float(indicator_score),
            pattern_score=float(pattern_score),
            volume_score=float(volume_score),
            recommendation_reasons=str(recommendation_reasons),
            industry=str(industry),
            regime_match=regime_match,
            score_percentile_bp=score_percentile_bp,
            eligible_universe_size=eligible_universe_size,
            eligible_universe_date=eligible_universe_date,
            ranking_method=ranking_method,
            threshold_mode=threshold_mode
        )


@dataclass
class RegimeResultDTO:
    """市場狀態檢測結果"""
    regime: str  # 'Trend', 'Reversion', 'Breakout'
    confidence: float  # 0-1
    details: Dict[str, Any]
    regime_name_cn: str  # 中文名稱
    
    def to_dict(self) -> dict:
        """轉換為字典"""
        return {
            'regime': self.regime,
            'regime_name_cn': self.regime_name_cn,
            'confidence': self.confidence,
            'details': self.details
        }


@dataclass
class RecommendationResultDTO:
    """推薦結果數據傳輸對象（固定欄位，可保存、可追溯）"""
    result_id: str  # 結果ID（唯一標識）
    result_name: str  # 結果名稱
    config: Dict[str, Any]  # 策略配置（完整配置）
    recommendations: List[RecommendationDTO]  # 推薦股票列表
    regime: Optional[str] = None  # 市場狀態
    created_at: Optional[str] = None  # 創建時間
    notes: str = ""  # 備註

    excluded_candidates_json: List[Dict[str, Any]] = field(default_factory=list)
    why_not_payload_json: List[Dict[str, Any]] = field(default_factory=list)
    liquidity_gate_payload_json: List[Dict[str, Any]] = field(default_factory=list)
    exclusion_quality: Optional[str] = None
    exclusion_warnings_json: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """轉換為字典"""
        return {
            'result_id': self.result_id,
            'result_name': self.result_name,
            'config': self.config,
            'recommendations': [rec.to_dict() for rec in self.recommendations],
            'regime': self.regime,
            'created_at': self.created_at,
            'notes': self.notes,
            'excluded_candidates_json': self.excluded_candidates_json,
            'why_not_payload_json': self.why_not_payload_json,
            'liquidity_gate_payload_json': self.liquidity_gate_payload_json,
            'exclusion_quality': self.exclusion_quality,
            'exclusion_warnings_json': self.exclusion_warnings_json
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'RecommendationResultDTO':
        """從字典創建對象"""
        recommendations = [
            RecommendationDTO.from_dict(rec) if isinstance(rec, dict) else rec
            for rec in data.get('recommendations', [])
        ]
        return cls(
            result_id=data.get('result_id', ''),
            result_name=data.get('result_name', ''),
            config=data.get('config', {}),
            recommendations=recommendations,
            regime=data.get('regime'),
            created_at=data.get('created_at'),
            notes=data.get('notes', ''),
            excluded_candidates_json=list(data.get('excluded_candidates_json') or []),
            why_not_payload_json=list(data.get('why_not_payload_json') or []),
            liquidity_gate_payload_json=list(data.get('liquidity_gate_payload_json') or []),
            exclusion_quality=data.get('exclusion_quality'),
            exclusion_warnings_json=[str(item) for item in (data.get('exclusion_warnings_json') or [])]
        )


@dataclass
class BacktestReportDTO:
    """回測報告數據傳輸對象"""
    total_return: float
    annual_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    expectancy: float  # 期望值（平均報酬）
    details: Dict[str, Any]
    baseline_comparison: Optional[Dict[str, Any]] = None  # Baseline 對比結果
    overfitting_risk: Optional[Dict[str, Any]] = None  # 過擬合風險評估結果
    
    # ========== Phase 3.5 SOP 護欄欄位 ==========
    changed_layers: List[str] = field(default_factory=list)  # 記錄本次研究中被修改的層級
    validation_status: ValidationStatus = ValidationStatus.PASS  # 驗證狀態
    sample_insufficient_flags: Dict[str, bool] = field(default_factory=dict)  # 樣本不足標記
    validation_messages: List[str] = field(default_factory=list)  # 驗證訊息（用於 UI 顯示）
    
    def to_dict(self) -> dict:
        """轉換為字典"""
        result = {
            '總報酬率': self.total_return,
            '年化報酬率': self.annual_return,
            '夏普比率': self.sharpe_ratio,
            '最大回撤': self.max_drawdown,
            '勝率': self.win_rate,
            '總交易次數': self.total_trades,
            '期望值': self.expectancy,
            '詳細信息': self.details
        }
        if self.baseline_comparison:
            result['Baseline對比'] = self.baseline_comparison
        if self.overfitting_risk:
            result['過擬合風險'] = self.overfitting_risk
        
        # Phase 3.5 SOP 護欄欄位
        result['changed_layers'] = self.changed_layers
        result['validation_status'] = self.validation_status.value
        result['sample_insufficient_flags'] = self.sample_insufficient_flags
        result['validation_messages'] = self.validation_messages
        
        return result

