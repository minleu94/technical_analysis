"""
Phase 3.5 SOP 驗證器
強制符合研究 SOP 流程的護欄邏輯
"""

from typing import Dict, List, Any, Optional
from datetime import datetime
import pandas as pd
from app_module.dtos import ValidationStatus


class SOPValidator:
    """Phase 3.5 SOP 驗證器"""
    
    def __init__(self):
        """初始化驗證器"""
        pass
    
    def validate_backtest_result(
        self,
        total_trades: int,
        start_date: str,
        end_date: str,
        walkforward_results: Optional[List] = None,
        changed_layers: Optional[List[str]] = None,
        walkforward_executed: bool = False
    ) -> Dict[str, Any]:
        """
        驗證回測結果是否符合 Phase 3.5 SOP
        
        Args:
            total_trades: 總交易次數
            start_date: 開始日期
            end_date: 結束日期
            walkforward_results: Walk-Forward 結果列表（可選）
            changed_layers: 本次研究中被修改的層級（可選）
            walkforward_executed: 是否已執行 Walk-Forward 驗證
        
        Returns:
            驗證結果字典：
            {
                'validation_status': ValidationStatus,
                'sample_insufficient_flags': Dict[str, bool],
                'validation_messages': List[str],
                'can_promote': bool
            }
        """
        messages = []
        insufficient_flags = {}
        
        # ========== 檢查 1：樣本不足 ==========
        
        # 1.1 交易次數不足
        if total_trades < 10:
            insufficient_flags['trade_count'] = True
            messages.append(f"⚠️ 樣本不足：交易次數僅 {total_trades} 次，無法可靠判斷策略有效性。")
            messages.append("   建議：擴大回測期間範圍、降低 buy_score 或 sell_score 閾值、檢查選股清單是否合適")
        else:
            insufficient_flags['trade_count'] = False
        
        # 1.2 回測期間過短
        try:
            start_dt = pd.to_datetime(start_date)
            end_dt = pd.to_datetime(end_date)
            days = (end_dt - start_dt).days
            
            if days < 90:  # 少於 3 個月
                insufficient_flags['period_too_short'] = True
                messages.append(f"⚠️ 樣本不足：回測期間僅 {days} 天，無法充分驗證策略穩健性。")
                messages.append("   建議：至少回測 6 個月以上的數據")
            else:
                insufficient_flags['period_too_short'] = False
        except Exception:
            insufficient_flags['period_too_short'] = False
        
        # 1.3 Walk-Forward Fold 數量不足
        if walkforward_results is not None:
            fold_count = len(walkforward_results)
            if fold_count < 3:
                insufficient_flags['wf_fold_insufficient'] = True
                messages.append(f"⚠️ 樣本不足：Walk-Forward 僅有 {fold_count} 個 Fold，無法可靠評估策略穩健性。")
                messages.append("   建議：擴大回測期間範圍、調整訓練期/測試期長度，確保至少 3 個 Fold")
            else:
                insufficient_flags['wf_fold_insufficient'] = False
        else:
            insufficient_flags['wf_fold_insufficient'] = False
        
        # ========== 檢查 2：層級變更警告 ==========
        
        if changed_layers and len(changed_layers) > 1:
            messages.append(f"⚠️ 警告：本次研究同時修改了多個層級（{', '.join(changed_layers)}）")
            messages.append("   建議：一次只修改一個層級，確保變更可歸因")
        
        # ========== 檢查 3：Walk-Forward 驗證警告 ==========
        
        if not walkforward_executed:
            messages.append("⚠️ 警告：尚未執行 Walk-Forward 驗證，無法評估穩健性")
            messages.append("   建議：執行 Walk-Forward 驗證以確認策略穩健性")
        
        # ========== 判斷驗證狀態 ==========
        
        validation_status = self._determine_validation_status(
            insufficient_flags=insufficient_flags,
            changed_layers=changed_layers,
            walkforward_executed=walkforward_executed
        )
        
        # ========== 判斷是否可以 Promote ==========
        
        can_promote = (validation_status != ValidationStatus.FAIL)
        
        return {
            'validation_status': validation_status,
            'sample_insufficient_flags': insufficient_flags,
            'validation_messages': messages,
            'can_promote': can_promote
        }
    
    def _determine_validation_status(
        self,
        insufficient_flags: Dict[str, bool],
        changed_layers: Optional[List[str]],
        walkforward_executed: bool
    ) -> ValidationStatus:
        """
        判斷驗證狀態
        
        Args:
            insufficient_flags: 樣本不足標記
            changed_layers: 本次研究中被修改的層級
            walkforward_executed: 是否已執行 Walk-Forward 驗證
        
        Returns:
            ValidationStatus
        """
        # FAIL：樣本不足（任一條件觸發）
        if any(insufficient_flags.values()):
            return ValidationStatus.FAIL
        
        # WARNING：同時修改超過一個層級或未執行 Walk-Forward
        if (changed_layers and len(changed_layers) > 1) or not walkforward_executed:
            return ValidationStatus.WARNING
        
        # PASS：符合 SOP，無問題
        return ValidationStatus.PASS
    
    def check_overfitting_risk(
        self,
        overfitting_risk: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        檢查過擬合風險（根據 Phase 3.5 SOP）
        
        Args:
            overfitting_risk: 過擬合風險評估結果
        
        Returns:
            檢查結果字典：
            {
                'risk_level': str,  # 'low', 'medium', 'high'
                'can_promote': bool,
                'messages': List[str]
            }
        """
        messages = []
        
        if overfitting_risk is None:
            return {
                'risk_level': 'unknown',
                'can_promote': True,
                'messages': ['無過擬合風險評估結果']
            }
        
        risk_level = overfitting_risk.get('risk_level', 'unknown')
        
        # 根據 Phase 3.5 SOP：高風險必須退回調整
        if risk_level == 'high':
            can_promote = False
            messages.append("❌ 過擬合風險等級：高風險")
            messages.append("   必須退回調整，不能進入 Phase 4")
            messages.append("   建議：重新進行參數最佳化，但必須配合 Walk-Forward 驗證")
        elif risk_level == 'medium':
            can_promote = True
            messages.append("⚠️ 過擬合風險等級：中風險")
            messages.append("   可以繼續，但建議進一步驗證")
        elif risk_level == 'low':
            can_promote = True
            messages.append("✅ 過擬合風險等級：低風險")
        else:
            can_promote = True
            messages.append(f"ℹ️ 過擬合風險等級：{risk_level}")
        
        return {
            'risk_level': risk_level,
            'can_promote': can_promote,
            'messages': messages
        }
    
    def check_baseline_comparison(
        self,
        baseline_comparison: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        檢查 Baseline 對比（根據 Phase 3.5 SOP）
        
        Args:
            baseline_comparison: Baseline 對比結果
        
        Returns:
            檢查結果字典：
            {
                'is_better_than_baseline': bool,
                'messages': List[str]
            }
        """
        messages = []
        
        if baseline_comparison is None:
            return {
                'is_better_than_baseline': True,  # 預設通過（無法判斷）
                'messages': ['無 Baseline 對比結果']
            }
        
        # 檢查策略是否優於 Baseline（至少總報酬率或 Sharpe Ratio 優於基準）
        is_better = baseline_comparison.get('is_better', False)
        
        if is_better:
            messages.append("✅ 策略表現優於 Buy & Hold")
        else:
            messages.append("❌ 策略表現不如 Buy & Hold")
            messages.append("   建議：調整 Score 層級或 Execution 層級，或考慮更換策略")
        
        return {
            'is_better_than_baseline': is_better,
            'messages': messages
        }
    
    def calculate_behavior_health_score(
        self,
        total_trades: int,
        avg_holding_days: float,
        strategy_type: str = "short_term"  # "short_term", "medium_term", "long_term"
    ) -> Dict[str, Any]:
        """
        計算行為健康分數（根據 Phase 3.5 SOP）
        
        Args:
            total_trades: 總交易次數
            avg_holding_days: 平均持有天數
            strategy_type: 策略類型
        
        Returns:
            行為健康分數字典：
            {
                'trade_count_ok': bool,
                'holding_days_ok': bool,
                'messages': List[str]
            }
        """
        messages = []
        
        # 檢查交易次數
        trade_count_ok = (10 <= total_trades <= 100)
        if not trade_count_ok:
            if total_trades < 10:
                messages.append(f"❌ 交易次數過少（{total_trades} 次），信號不足")
            else:
                messages.append(f"⚠️ 交易次數過多（{total_trades} 次），可能過度交易")
        else:
            messages.append(f"✅ 交易次數合理（{total_trades} 次）")
        
        # 檢查平均持有天數
        expected_ranges = {
            "short_term": (3, 10),
            "medium_term": (10, 30),
            "long_term": (30, 1000)
        }
        
        min_days, max_days = expected_ranges.get(strategy_type, (3, 30))
        holding_days_ok = (min_days <= avg_holding_days <= max_days)
        
        if not holding_days_ok:
            messages.append(f"⚠️ 平均持有天數（{avg_holding_days:.1f} 天）不符合 {strategy_type} 策略預期")
        else:
            messages.append(f"✅ 平均持有天數合理（{avg_holding_days:.1f} 天）")
        
        return {
            'trade_count_ok': trade_count_ok,
            'holding_days_ok': holding_days_ok,
            'messages': messages
        }
