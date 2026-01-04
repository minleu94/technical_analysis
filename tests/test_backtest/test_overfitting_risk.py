"""
Epic 2 MVP-2 過擬合風險提示 - 單元測試

測試範圍：
- calculate_walkforward_degradation() 方法
- calculate_consistency() 方法
- calculate_overfitting_risk() 整合方法
- 風險等級判斷邏輯
"""

import pytest
import sys
from pathlib import Path

# 添加項目根目錄到系統路徑
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from backtest_module.performance_metrics import PerformanceAnalyzer


class TestWalkForwardDegradation:
    """測試 calculate_walkforward_degradation() 方法"""
    
    def setup_method(self):
        """設置測試環境"""
        self.analyzer = PerformanceAnalyzer(risk_free_rate=0.0)
    
    def test_normal_case(self):
        """測試正常情況：訓練期 Sharpe 0.5，測試期 Sharpe 0.3，退化程度應為 0.4"""
        train_perf = {'sharpe_ratio': 0.5, 'total_return': 0.2}
        test_perf = {'sharpe_ratio': 0.3, 'total_return': 0.12}
        
        degradation = self.analyzer.calculate_walkforward_degradation(
            train_perf, test_perf
        )
        
        # 退化程度 = (0.5 - 0.3) / 0.5 = 0.4
        assert abs(degradation - 0.4) < 1e-6, f"預期退化程度 0.4，實際為 {degradation}"
    
    def test_no_degradation(self):
        """測試無退化情況：測試期優於訓練期，應返回 0"""
        train_perf = {'sharpe_ratio': 0.3, 'total_return': 0.12}
        test_perf = {'sharpe_ratio': 0.5, 'total_return': 0.2}
        
        degradation = self.analyzer.calculate_walkforward_degradation(
            train_perf, test_perf
        )
        
        assert degradation == 0.0, f"預期退化程度 0.0（無退化），實際為 {degradation}"
    
    def test_complete_degradation(self):
        """測試完全退化情況：測試期 Sharpe 為 0，應返回 1.0"""
        train_perf = {'sharpe_ratio': 0.5, 'total_return': 0.2}
        test_perf = {'sharpe_ratio': 0.0, 'total_return': 0.0}
        
        degradation = self.analyzer.calculate_walkforward_degradation(
            train_perf, test_perf
        )
        
        assert abs(degradation - 1.0) < 1e-6, f"預期退化程度 1.0（完全退化），實際為 {degradation}"
    
    def test_zero_train_sharpe_uses_total_return(self):
        """測試除零處理：訓練期 Sharpe 為 0，應使用 total_return 計算"""
        train_perf = {'sharpe_ratio': 0.0, 'total_return': 0.2}
        test_perf = {'sharpe_ratio': 0.0, 'total_return': 0.1}
        
        degradation = self.analyzer.calculate_walkforward_degradation(
            train_perf, test_perf
        )
        
        # 退化程度 = (0.2 - 0.1) / 0.2 = 0.5
        assert abs(degradation - 0.5) < 1e-6, f"預期退化程度 0.5，實際為 {degradation}"
    
    def test_zero_train_metric_returns_zero(self):
        """測試訓練期指標為 0 的情況，應返回 0（視為無退化）"""
        train_perf = {'sharpe_ratio': 0.0, 'total_return': 0.0}
        test_perf = {'sharpe_ratio': 0.0, 'total_return': 0.0}
        
        degradation = self.analyzer.calculate_walkforward_degradation(
            train_perf, test_perf
        )
        
        assert degradation == 0.0, f"預期退化程度 0.0（無法計算，視為無退化），實際為 {degradation}"
    
    def test_degradation_clamped_to_one(self):
        """測試退化程度超過 1.0 時，應限制為 1.0"""
        train_perf = {'sharpe_ratio': 0.1, 'total_return': 0.05}
        test_perf = {'sharpe_ratio': -0.5, 'total_return': -0.2}  # 測試期表現為負
        
        degradation = self.analyzer.calculate_walkforward_degradation(
            train_perf, test_perf
        )
        
        # 退化程度 = (0.1 - (-0.5)) / 0.1 = 6.0，但應限制為 1.0
        assert degradation <= 1.0, f"退化程度應限制在 1.0 以內，實際為 {degradation}"


class TestConsistency:
    """測試 calculate_consistency() 方法"""
    
    def setup_method(self):
        """設置測試環境"""
        self.analyzer = PerformanceAnalyzer(risk_free_rate=0.0)
    
    def test_normal_case(self):
        """測試正常情況：3 個 Fold，Sharpe 分別為 0.5, 0.6, 0.4，計算標準差"""
        fold_performances = [
            {'sharpe_ratio': 0.5, 'total_return': 0.2},
            {'sharpe_ratio': 0.6, 'total_return': 0.24},
            {'sharpe_ratio': 0.4, 'total_return': 0.16}
        ]
        
        consistency = self.analyzer.calculate_consistency(fold_performances)
        
        # 標準差應該 > 0（因為有變化）
        assert consistency is not None, "一致性應有值"
        assert consistency >= 0.0, f"一致性應 >= 0，實際為 {consistency}"
        assert consistency <= 1.0, f"一致性應 <= 1.0，實際為 {consistency}"
    
    def test_perfect_consistency(self):
        """測試完全一致情況：所有 Fold Sharpe 相同，應返回接近 0"""
        fold_performances = [
            {'sharpe_ratio': 0.5, 'total_return': 0.2},
            {'sharpe_ratio': 0.5, 'total_return': 0.2},
            {'sharpe_ratio': 0.5, 'total_return': 0.2}
        ]
        
        consistency = self.analyzer.calculate_consistency(fold_performances)
        
        # 標準差應該為 0（完全一致）
        assert consistency is not None, "一致性應有值"
        assert abs(consistency - 0.0) < 1e-6, f"完全一致時一致性應為 0，實際為 {consistency}"
    
    def test_insufficient_folds(self):
        """測試 Fold 數量不足：只有 1 個 Fold，應返回 None"""
        fold_performances = [
            {'sharpe_ratio': 0.5, 'total_return': 0.2}
        ]
        
        consistency = self.analyzer.calculate_consistency(fold_performances)
        
        assert consistency is None, "Fold 數量不足時應返回 None"
    
    def test_empty_list(self):
        """測試空列表：應返回 None"""
        fold_performances = []
        
        consistency = self.analyzer.calculate_consistency(fold_performances)
        
        assert consistency is None, "空列表時應返回 None"
    
    def test_uses_total_return_when_all_sharpe_zero(self):
        """測試所有 Sharpe 為 0 時，使用 total_return 計算"""
        fold_performances = [
            {'sharpe_ratio': 0.0, 'total_return': 0.2},
            {'sharpe_ratio': 0.0, 'total_return': 0.3},
            {'sharpe_ratio': 0.0, 'total_return': 0.1}
        ]
        
        consistency = self.analyzer.calculate_consistency(fold_performances)
        
        assert consistency is not None, "應使用 total_return 計算一致性"
        assert consistency >= 0.0, f"一致性應 >= 0，實際為 {consistency}"


class TestOverfittingRisk:
    """測試 calculate_overfitting_risk() 整合方法"""
    
    def setup_method(self):
        """設置測試環境"""
        self.analyzer = PerformanceAnalyzer(risk_free_rate=0.0)
    
    def test_complete_data(self):
        """測試完整資料：所有指標都可計算"""
        result = self.analyzer.calculate_overfitting_risk(
            degradation=0.5,  # 高退化
            consistency_std=0.6,  # 高不一致
            parameter_sensitivity=0.35  # 高敏感性
        )
        
        assert result['risk_level'] == 'high', f"預期高風險，實際為 {result['risk_level']}"
        assert result['risk_score'] >= 4.0, f"風險分數應 >= 4.0，實際為 {result['risk_score']}"
        assert len(result['warnings']) > 0, "應有警告訊息"
        assert len(result['recommendations']) > 0, "應有改善建議"
        assert len(result['missing_data']) == 0, "不應有缺少的資料"
    
    def test_partial_data(self):
        """測試部分資料：只有 Walk-Forward 結果，沒有最佳化結果"""
        result = self.analyzer.calculate_overfitting_risk(
            degradation=0.3,
            consistency_std=0.4,
            parameter_sensitivity=None
        )
        
        assert result['risk_level'] in ['low', 'medium', 'high'], f"風險等級應為 low/medium/high，實際為 {result['risk_level']}"
        assert '參數最佳化結果' in result['missing_data'], "應標註缺少參數最佳化結果"
        assert len(result['warnings']) >= 0, "可能有警告訊息"
    
    def test_no_data(self):
        """測試無資料：沒有任何資料，應返回低風險但標註 missing_data"""
        result = self.analyzer.calculate_overfitting_risk(
            degradation=None,
            consistency_std=None,
            parameter_sensitivity=None
        )
        
        assert result['risk_level'] == 'low', "無資料時應返回低風險"
        assert result['risk_score'] == 0.0, "無資料時風險分數應為 0"
        assert len(result['missing_data']) == 3, "應標註所有缺少的資料"
        assert 'Walk-Forward 結果' in result['missing_data']
        assert 'Walk-Forward 多個 Fold 結果' in result['missing_data']
        assert '參數最佳化結果' in result['missing_data']
    
    def test_high_risk(self):
        """測試高風險情況：所有指標都超標，應返回高風險"""
        result = self.analyzer.calculate_overfitting_risk(
            degradation=0.5,  # >= 0.40，+2 分
            consistency_std=0.6,  # >= 0.50，+2 分
            parameter_sensitivity=0.35  # >= 0.30，+2 分
        )
        
        assert result['risk_level'] == 'high', f"預期高風險，實際為 {result['risk_level']}"
        assert result['risk_score'] >= 4.0, f"風險分數應 >= 4.0，實際為 {result['risk_score']}"
        assert any('高' in w for w in result['warnings']), "應有高風險警告"
    
    def test_medium_risk(self):
        """測試中風險情況：部分指標超標，應返回中風險"""
        result = self.analyzer.calculate_overfitting_risk(
            degradation=0.25,  # >= 0.20，+1 分
            consistency_std=0.35,  # >= 0.30，+1 分
            parameter_sensitivity=None
        )
        
        assert result['risk_level'] == 'medium', f"預期中風險，實際為 {result['risk_level']}"
        assert 2.0 <= result['risk_score'] < 4.0, f"風險分數應在 2.0-4.0 之間，實際為 {result['risk_score']}"
    
    def test_low_risk(self):
        """測試低風險情況：所有指標都在可接受範圍內，應返回低風險"""
        result = self.analyzer.calculate_overfitting_risk(
            degradation=0.1,  # < 0.20，+0 分
            consistency_std=0.2,  # < 0.30，+0 分
            parameter_sensitivity=0.1  # < 0.15，+0 分
        )
        
        assert result['risk_level'] == 'low', f"預期低風險，實際為 {result['risk_level']}"
        assert result['risk_score'] < 2.0, f"風險分數應 < 2.0，實際為 {result['risk_score']}"
    
    def test_risk_score_boundary(self):
        """測試風險分數邊界值"""
        # 測試風險分數 = 2.0（中風險邊界）
        result = self.analyzer.calculate_overfitting_risk(
            degradation=0.2,  # = 0.20，+1 分
            consistency_std=0.3,  # = 0.30，+1 分
            parameter_sensitivity=None
        )
        
        assert result['risk_level'] == 'medium', f"風險分數 2.0 應為中風險，實際為 {result['risk_level']}"
        
        # 測試風險分數 = 4.0（高風險邊界）
        result = self.analyzer.calculate_overfitting_risk(
            degradation=0.4,  # = 0.40，+2 分
            consistency_std=0.5,  # = 0.50，+2 分
            parameter_sensitivity=None
        )
        
        assert result['risk_level'] == 'high', f"風險分數 4.0 應為高風險，實際為 {result['risk_level']}"
    
    def test_warnings_generation(self):
        """測試警告訊息生成"""
        result = self.analyzer.calculate_overfitting_risk(
            degradation=0.45,  # >= 0.40，應有高風險警告
            consistency_std=0.35,  # >= 0.30，應有中等警告
            parameter_sensitivity=0.2  # >= 0.15，應有中等警告
        )
        
        # 檢查警告訊息是否包含關鍵詞
        warning_text = ' '.join(result['warnings'])
        assert '退化' in warning_text or '過高' in warning_text, "應有退化相關警告"
        assert '一致性' in warning_text, "應有一致性相關警告"
        assert '參數敏感性' in warning_text, "應有參數敏感性相關警告"
    
    def test_recommendations_generation(self):
        """測試改善建議生成"""
        # 高風險情況
        result = self.analyzer.calculate_overfitting_risk(
            degradation=0.5,
            consistency_std=0.6,
            parameter_sensitivity=0.35
        )
        
        recommendations_text = ' '.join(result['recommendations'])
        assert '過擬合風險較高' in recommendations_text, "高風險時應有相應建議"
        assert '增加訓練樣本' in recommendations_text or '簡化策略' in recommendations_text, "應有具體改善建議"
        
        # 低風險情況
        result = self.analyzer.calculate_overfitting_risk(
            degradation=0.1,
            consistency_std=0.2,
            parameter_sensitivity=0.1
        )
        
        recommendations_text = ' '.join(result['recommendations'])
        assert '過擬合風險較低' in recommendations_text, "低風險時應有相應建議"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

