from typing import Dict, List, Tuple, Any
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
import os

class PatternParameterOptimizer:
    """
    圖形模式參數優化器
    作為PatternAnalyzer的輔助類，用於優化各種圖形模式的識別參數
    """
    
    def __init__(self, pattern_analyzer=None):
        """
        初始化參數優化器
        
        Args:
            pattern_analyzer: PatternAnalyzer實例，用於調用具體的模式識別方法
        """
        self.pattern_analyzer = pattern_analyzer
        self._init_pattern_configs()

    def _init_pattern_configs(self):
        """初始化各種圖形模式的參數配置"""
        # 基礎模式配置
        self.basic_patterns_config = {
            'W底': {
                'params': {
                    'window': [10, 15, 20, 25, 30],
                    'threshold': [0.03, 0.05, 0.08, 0.1],
                    'prominence': [0.3, 0.5, 0.8, 1.0]
                },
                'validation': {
                    'min_pattern_length': 20,
                    'max_pattern_length': 60,
                    'volume_confirm': True
                }
            },
            'V形': {
                'params': {
                    'window': [5, 10, 15, 20],
                    'threshold': [0.02, 0.03, 0.05],
                    'min_drop': [0.05, 0.08, 0.1]
                },
                'validation': {
                    'min_pattern_length': 10,
                    'max_pattern_length': 30,
                    'volume_confirm': True
                }
            }
        }

        # 複合模式配置
        self.compound_patterns_config = {
            '頭肩頂': {
                'params': {
                    'window': [20, 25, 30, 35, 40],
                    'threshold': [0.05, 0.08, 0.1, 0.15],
                    'height_ratio': [0.5, 0.8, 1.0]
                },
                'validation': {
                    'min_pattern_length': 40,
                    'max_pattern_length': 100,
                    'volume_confirm': True
                }
            },
            '頭肩底': {
                'params': {
                    'window': [20, 25, 30, 35, 40],
                    'threshold': [0.05, 0.08, 0.1, 0.15],
                    'height_ratio': [0.5, 0.8, 1.0]
                },
                'validation': {
                    'min_pattern_length': 40,
                    'max_pattern_length': 100,
                    'volume_confirm': True
                }
            }
        }

        # 趨勢模式配置
        self.trend_patterns_config = {
            '三角形': {
                'params': {
                    'window': [20, 25, 30],
                    'threshold': [0.05, 0.08],
                    'min_r_squared': [0.4, 0.5],
                    'min_height_ratio': [0.02, 0.03]
                },
                'validation': {
                    'min_pattern_length': 20,
                    'max_pattern_length': 60,
                    'volume_confirm': True
                }
            },
            '楔形': {
                'params': {
                    'window': [20, 25, 30],
                    'threshold': [0.05, 0.08],
                    'min_r_squared': [0.4, 0.5],
                    'convergence_ratio': [0.02, 0.03]
                },
                'validation': {
                    'min_pattern_length': 20,
                    'max_pattern_length': 60,
                    'volume_confirm': True
                }
            }
        }

    def optimize_pattern_parameters(
        self,
        df: pd.DataFrame,
        pattern_type: str,
        pattern_category: str = None,
        test_size: float = 0.3
    ) -> Tuple[Dict[str, Any], pd.DataFrame]:
        """
        對指定的圖形模式進行參數優化
        
        Args:
            df: 包含價格數據的DataFrame
            pattern_type: 圖形模式類型
            pattern_category: 模式類別（basic/compound/trend），如果為None則自動判斷
            test_size: 測試集比例
        
        Returns:
            最佳參數組合和測試結果DataFrame
        """
        if self.pattern_analyzer is None:
            raise ValueError("未設置PatternAnalyzer實例")

        # 獲取配置
        if pattern_category is None:
            pattern_category = self._get_pattern_category(pattern_type)
        
        config = self._get_pattern_config(pattern_type, pattern_category)
        if config is None:
            raise ValueError(f"未找到{pattern_type}的配置信息")

        # 分割訓練集和測試集
        train_size = int(len(df) * (1 - test_size))
        train_df = df.iloc[:train_size]
        test_df = df.iloc[train_size:]

        # 生成參數組合
        param_combinations = self._generate_param_combinations(config['params'])
        
        # 存儲結果
        results = []
        
        # 測試每個參數組合
        for i, params in enumerate(param_combinations):
            # 在訓練集上識別模式
            train_patterns = self._identify_pattern(train_df, pattern_type, params)
            
            # 在測試集上驗證
            accuracy = self._validate_patterns(test_df, train_patterns)
            
            # 記錄結果
            results.append({
                'combination_id': i + 1,
                'params': params,
                'pattern_count': len(train_patterns),
                'accuracy': accuracy
            })

        # 轉換為DataFrame
        results_df = pd.DataFrame(results)
        
        # 找出最佳參數組合
        best_params = results_df.loc[results_df['accuracy'].idxmax(), 'params']
        
        return best_params, results_df

    def _get_pattern_category(self, pattern_type: str) -> str:
        """根據模式類型判斷其類別"""
        if pattern_type in self.basic_patterns_config:
            return 'basic'
        elif pattern_type in self.compound_patterns_config:
            return 'compound'
        elif pattern_type in self.trend_patterns_config:
            return 'trend'
        else:
            raise ValueError(f"未知的模式類型: {pattern_type}")

    def _get_pattern_config(self, pattern_type: str, category: str) -> Dict:
        """獲取指定模式的配置信息"""
        if category == 'basic':
            return self.basic_patterns_config.get(pattern_type)
        elif category == 'compound':
            return self.compound_patterns_config.get(pattern_type)
        elif category == 'trend':
            return self.trend_patterns_config.get(pattern_type)
        return None

    def _generate_param_combinations(self, param_config: Dict) -> List[Dict]:
        """生成參數組合"""
        param_names = list(param_config.keys())
        param_values = list(param_config.values())
        
        combinations = []
        for values in np.array(np.meshgrid(*param_values)).T.reshape(-1, len(param_values)):
            combination = dict(zip(param_names, values))
            combinations.append(combination)
        
        return combinations

    def _identify_pattern(self, df: pd.DataFrame, pattern_type: str, params: Dict) -> List[Dict]:
        """使用指定參數識別圖形模式"""
        if self.pattern_analyzer is None:
            raise ValueError("未設置PatternAnalyzer實例")
        
        # 調用PatternAnalyzer的相應方法
        return self.pattern_analyzer.identify_pattern(df, pattern_type, params)

    def _validate_patterns(self, df: pd.DataFrame, patterns: List[Dict]) -> float:
        """驗證識別出的模式的準確性"""
        if self.pattern_analyzer is None:
            raise ValueError("未設置PatternAnalyzer實例")
        
        # 調用PatternAnalyzer的評估方法
        return self.pattern_analyzer.evaluate_pattern_accuracy(df, patterns)

    def plot_optimization_results(
        self,
        results_df: pd.DataFrame,
        pattern_type: str,
        save_path: str = None
    ) -> None:
        """
        繪製優化結果圖表
        
        Args:
            results_df: 包含優化結果的DataFrame
            pattern_type: 圖形模式類型
            save_path: 保存路徑
        """
        plt.figure(figsize=(15, 6))

        # 繪製識別數量柱狀圖
        plt.subplot(1, 2, 1)
        plt.bar(results_df['combination_id'], results_df['pattern_count'])
        plt.title(f'{pattern_type}模式識別數量')
        plt.xlabel('參數組合編號')
        plt.ylabel('識別數量')

        # 繪製準確率柱狀圖
        plt.subplot(1, 2, 2)
        plt.bar(results_df['combination_id'], results_df['accuracy'])
        plt.title(f'{pattern_type}模式準確率')
        plt.xlabel('參數組合編號')
        plt.ylabel('準確率 (%)')

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path)
        plt.close()

    def save_results(
        self,
        results_df: pd.DataFrame,
        pattern_type: str,
        best_params: Dict,
        save_dir: str
    ) -> None:
        """
        保存優化結果
        
        Args:
            results_df: 優化結果DataFrame
            pattern_type: 圖形模式類型
            best_params: 最佳參數組合
            save_dir: 保存目錄
        """
        # 創建保存目錄
        os.makedirs(save_dir, exist_ok=True)
        
        # 保存結果到CSV
        results_df.to_csv(
            os.path.join(save_dir, f'{pattern_type}_optimization_results.csv'),
            index=False
        )
        
        # 保存最佳參數
        with open(os.path.join(save_dir, f'{pattern_type}_best_params.txt'), 'w') as f:
            f.write(f"最佳參數組合：\n")
            for param, value in best_params.items():
                f.write(f"{param}: {value}\n")
            f.write(f"\n準確率: {results_df.loc[results_df['accuracy'].idxmax(), 'accuracy']:.2f}%") 