import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier, GradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, mean_squared_error
from sklearn.preprocessing import StandardScaler

class MLAnalyzer:
    """機器學習模型分析類"""
    
    def __init__(self):
        """初始化機器學習分析器"""
        self.models = {}
        self.scaler = StandardScaler()
        self.feature_columns = None  # 保存訓練時使用的特徵列名
        # 定義列名映射，將中文列名映射到英文列名
        self.column_mapping = {
            # 中文列名 -> 英文列名
            '收盤價': 'Close',
            '開盤價': 'Open',
            '最高價': 'High',
            '最低價': 'Low',
            '成交量': 'Volume',
            '成交股數': 'Volume',
            '漲跌(+/-)': 'Change_Direction',
            '證券名稱': 'Stock_Name'
        }
        # 反向映射，將英文列名映射到中文列名
        self.reverse_mapping = {v: k for k, v in self.column_mapping.items()}
        
    def _get_column_name(self, df, eng_name):
        """獲取對應的列名，優先使用中文列名，如果不存在則使用英文列名
        
        Args:
            df: 數據DataFrame
            eng_name: 英文列名
            
        Returns:
            str: 對應的列名
        """
        # 檢查中文列名是否存在
        if self.reverse_mapping.get(eng_name) in df.columns:
            return self.reverse_mapping.get(eng_name)
        # 檢查英文列名是否存在
        elif eng_name in df.columns:
            return eng_name
        # 都不存在，返回None
        return None
        
    def prepare_features(self, df, feature_cols=None):
        """準備特徵數據
        
        Args:
            df: 數據DataFrame
            feature_cols: 特徵列名列表，如果為None則使用所有數值列
            
        Returns:
            特徵數據
        """
        # 如果沒有指定特徵列，使用訓練時保存的特徵列
        if feature_cols is None and self.feature_columns is not None:
            feature_cols = self.feature_columns
        # 如果仍然沒有特徵列，使用所有數值列
        elif feature_cols is None:
            feature_cols = df.select_dtypes(include=[np.number]).columns.tolist()
            # 排除目標列和其他不需要的列
            exclude_cols = ['Target', 'Target_Binary', 'Signal', 'Position']
            for col in exclude_cols:
                if col in feature_cols:
                    feature_cols.remove(col)
        
        # 確保所有特徵列都存在於DataFrame中
        valid_feature_cols = []
        for col in feature_cols:
            # 檢查原始列名
            if col in df.columns:
                valid_feature_cols.append(col)
            # 檢查中文列名對應的英文列名
            elif col in self.column_mapping and self.column_mapping[col] in df.columns:
                valid_feature_cols.append(self.column_mapping[col])
            # 檢查英文列名對應的中文列名
            elif col in self.reverse_mapping and self.reverse_mapping[col] in df.columns:
                valid_feature_cols.append(self.reverse_mapping[col])
        
        # 如果沒有有效的特徵列，返回空的DataFrame
        if not valid_feature_cols:
            return pd.DataFrame()
            
        # 提取特徵
        X = df[valid_feature_cols].copy()
        
        # 處理缺失值
        X = X.ffill().bfill()
        
        # 如果有訓練時保存的特徵列，確保列名一致
        if self.feature_columns is not None:
            # 創建一個新的DataFrame，只包含訓練時使用的特徵列
            X_aligned = pd.DataFrame(index=X.index)
            for col in self.feature_columns:
                if col in X.columns:
                    X_aligned[col] = X[col]
                else:
                    # 如果缺少某些特徵列，填充為0
                    X_aligned[col] = 0
            X = X_aligned
        
        return X
        
    def prepare_features_targets(self, df, target_col, feature_cols=None, prediction_horizon=1):
        """準備特徵和目標變量
        
        Args:
            df: 數據DataFrame
            target_col: 目標列名
            feature_cols: 特徵列名列表，如果為None則使用所有數值列
            prediction_horizon: 預測時間範圍（天數）
            
        Returns:
            tuple: (X, y) 特徵和目標
        """
        # 創建一個副本以避免SettingWithCopyWarning
        df_copy = df.copy()
        
        if feature_cols is None:
            feature_cols = df_copy.select_dtypes(include=[np.number]).columns.tolist()
            if target_col in feature_cols:
                feature_cols.remove(target_col)
                
        # 創建目標變量（未來n天的價格變動）
        df_copy.loc[:, 'Target'] = df_copy[target_col].shift(-prediction_horizon)
        
        # 對於分類問題，可以創建二元目標（上漲/下跌）
        df_copy.loc[:, 'Target_Binary'] = (df_copy['Target'] > df_copy[target_col]).astype(int)
        
        # 刪除含有NaN的行
        df_clean = df_copy.dropna()
        
        X = df_clean[feature_cols]
        y_reg = df_clean['Target']
        y_cls = df_clean['Target_Binary']
        
        # 保存特徵列名，用於後續預測
        self.feature_columns = feature_cols
        
        return X, y_reg, y_cls
    
    def train_classifier(self, X_train, y_train, model_type='random_forest', **kwargs):
        """訓練分類模型
        
        Args:
            X_train: 訓練特徵
            y_train: 訓練目標
            model_type: 模型類型，'random_forest' 或 'logistic'
            **kwargs: 模型參數
            
        Returns:
            訓練好的模型
        """
        X_scaled = self.scaler.fit_transform(X_train)
        
        if model_type == 'random_forest':
            model = RandomForestClassifier(**kwargs)
        elif model_type == 'logistic':
            model = LogisticRegression(**kwargs)
        else:
            raise ValueError(f"不支持的模型類型: {model_type}")
            
        model.fit(X_scaled, y_train)
        
        # 保存模型
        model_name = f"{model_type}_classifier"
        self.models[model_name] = model
        
        return model
    
    def train_regressor(self, X_train, y_train, model_type='gradient_boosting', **kwargs):
        """訓練回歸模型
        
        Args:
            X_train: 訓練特徵
            y_train: 訓練目標
            model_type: 模型類型，目前只支持 'gradient_boosting'
            **kwargs: 模型參數
            
        Returns:
            訓練好的模型
        """
        X_scaled = self.scaler.fit_transform(X_train)
        
        if model_type == 'gradient_boosting':
            model = GradientBoostingRegressor(**kwargs)
        else:
            raise ValueError(f"不支持的模型類型: {model_type}")
            
        model.fit(X_scaled, y_train)
        
        # 保存模型
        model_name = f"{model_type}_regressor"
        self.models[model_name] = model
        
        return model
    
    def predict(self, X_test, model_name):
        """使用訓練好的模型進行預測
        
        Args:
            X_test: 測試特徵
            model_name: 模型名稱
            
        Returns:
            預測結果
        """
        if model_name not in self.models:
            raise ValueError(f"找不到模型: {model_name}")
        
        try:
            # 確保特徵列名與訓練時一致
            if self.feature_columns is not None:
                # 創建一個新的DataFrame，只包含訓練時使用的特徵列
                X_aligned = pd.DataFrame(index=X_test.index)
                for col in self.feature_columns:
                    if col in X_test.columns:
                        X_aligned[col] = X_test[col]
                    else:
                        # 如果缺少某些特徵列，填充為0
                        X_aligned[col] = 0
                X_test = X_aligned
                
            X_scaled = self.scaler.transform(X_test)
            
            # 進行預測
            predictions = self.models[model_name].predict(X_scaled)
            
            # 確保返回的是一個可以轉換為float的數據類型
            if isinstance(predictions, np.ndarray):
                return predictions
            else:
                # 如果是其他類型，嘗試轉換為numpy數組
                return np.array(predictions)
        except Exception as e:
            print(f"預測時出錯: {str(e)}")
            # 返回一個默認的預測結果，避免程序崩潰
            return np.zeros(len(X_test))
    
    def evaluate_classifier(self, X_test, y_test, model_name):
        """評估分類模型
        
        Args:
            X_test: 測試特徵
            y_test: 測試目標
            model_name: 模型名稱
            
        Returns:
            準確率
        """
        try:
            predictions = self.predict(X_test, model_name)
            return accuracy_score(y_test, predictions)
        except Exception as e:
            print(f"評估分類模型時出錯: {str(e)}")
            return 0.0
    
    def evaluate_regressor(self, X_test, y_test, model_name):
        """評估回歸模型
        
        Args:
            X_test: 測試特徵
            y_test: 測試目標
            model_name: 模型名稱
            
        Returns:
            均方誤差
        """
        try:
            predictions = self.predict(X_test, model_name)
            return mean_squared_error(y_test, predictions)
        except Exception as e:
            print(f"評估回歸模型時出錯: {str(e)}")
            return float('inf') 