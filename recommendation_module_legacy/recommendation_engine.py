import pandas as pd
import numpy as np
from datetime import datetime, timedelta

class RecommendationEngine:
    """綜合分析結果生成交易建議"""
    
    def __init__(self, technical_analyzer=None, ml_analyzer=None, math_analyzer=None):
        """初始化推薦引擎
        
        Args:
            technical_analyzer: 技術分析器實例
            ml_analyzer: 機器學習分析器實例
            math_analyzer: 數學分析器實例
        """
        self.technical_analyzer = technical_analyzer
        self.ml_analyzer = ml_analyzer
        self.math_analyzer = math_analyzer
        self.weights = {
            'technical': 0.4,
            'ml': 0.4,
            'math': 0.2
        }
        # 定義列名映射，將中文列名映射到英文列名
        self.column_mapping = {
            # 中文列名 -> 英文列名
            '收盤價': 'Close',
            '開盤價': 'Open',
            '最高價': 'High',
            '最低價': 'Low',
            '成交量': 'Volume',
            '成交股數': 'Volume',
            '日期': 'Date',
            '移動平均線20': 'MA20',
            '移動平均線60': 'MA60',
            '相對強弱指標': 'RSI',
            '平滑異同移動平均線': 'MACD',
            '平滑異同移動平均線信號': 'MACD_Signal',
            '平滑異同移動平均線柱狀': 'MACD_hist',
            '隨機震盪指標K': 'slowk',
            '隨機震盪指標D': 'slowd',
            '時間序列預測': 'TSF',
            '布林帶中軌': 'middleband',
            '布林帶上軌': 'BB_Upper',
            '布林帶下軌': 'BB_Lower',
            '拋物線轉向指標': 'SAR'
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
        
    def set_weights(self, technical=0.4, ml=0.4, math=0.2):
        """設置各分析方法的權重
        
        Args:
            technical: 技術分析權重
            ml: 機器學習分析權重
            math: 數學模型分析權重
        """
        total = technical + ml + math
        self.weights = {
            'technical': technical / total,
            'ml': ml / total,
            'math': math / total
        }
        
    def get_technical_signals(self, df):
        """獲取技術分析信號
        
        Args:
            df: 股票數據DataFrame
            
        Returns:
            技術分析信號 (-1 賣出, 0 持有, 1 買入)
        """
        if self.technical_analyzer is None:
            return pd.Series(0, index=df.index)
            
        signals = pd.Series(0, index=df.index)
        
        # 添加技術指標
        df_tech = df.copy()
        df_tech = self.technical_analyzer.add_momentum_indicators(df_tech)
        df_tech = self.technical_analyzer.add_volatility_indicators(df_tech)
        df_tech = self.technical_analyzer.add_trend_indicators(df_tech)
        
        # 獲取列名
        rsi_col = self._get_column_name(df_tech, 'RSI')
        macd_col = self._get_column_name(df_tech, 'MACD')
        macd_signal_col = self._get_column_name(df_tech, 'MACD_Signal')
        bb_upper_col = self._get_column_name(df_tech, 'BB_Upper')
        bb_middle_col = self._get_column_name(df_tech, 'BB_Middle')
        bb_lower_col = self._get_column_name(df_tech, 'BB_Lower')
        ma20_col = self._get_column_name(df_tech, 'MA20')
        ma60_col = self._get_column_name(df_tech, 'MA60')
        close_col = self._get_column_name(df_tech, 'Close')
        
        # RSI策略
        if rsi_col and rsi_col in df_tech.columns:
            signals.loc[df_tech[rsi_col] < 30] = 1  # 超賣
            signals.loc[df_tech[rsi_col] > 70] = -1  # 超買
            
        # MACD策略
        if macd_col and macd_signal_col and macd_col in df_tech.columns and macd_signal_col in df_tech.columns:
            signals.loc[(df_tech[macd_col] > df_tech[macd_signal_col]) & 
                       (df_tech[macd_col].shift(1) <= df_tech[macd_signal_col].shift(1))] = 1  # 金叉
            signals.loc[(df_tech[macd_col] < df_tech[macd_signal_col]) & 
                       (df_tech[macd_col].shift(1) >= df_tech[macd_signal_col].shift(1))] = -1  # 死叉
            
        # 布林帶策略
        if bb_upper_col and bb_lower_col and close_col and all(col in df_tech.columns for col in [bb_upper_col, bb_lower_col, close_col]):
            signals.loc[df_tech[close_col] < df_tech[bb_lower_col]] = 1  # 價格低於下軌
            signals.loc[df_tech[close_col] > df_tech[bb_upper_col]] = -1  # 價格高於上軌
            
        # 移動平均線策略
        if ma20_col and ma60_col and all(col in df_tech.columns for col in [ma20_col, ma60_col]):
            signals.loc[(df_tech[ma20_col] > df_tech[ma60_col]) & 
                       (df_tech[ma20_col].shift(1) <= df_tech[ma60_col].shift(1))] = 1  # 短期均線上穿長期均線
            signals.loc[(df_tech[ma20_col] < df_tech[ma60_col]) & 
                       (df_tech[ma20_col].shift(1) >= df_tech[ma60_col].shift(1))] = -1  # 短期均線下穿長期均線
            
        return signals
    
    def get_ml_signals(self, df, model_name=None):
        """獲取機器學習模型信號
        
        Args:
            df: 股票數據DataFrame
            model_name: 模型名稱
            
        Returns:
            機器學習信號 (-1 賣出, 0 持有, 1 買入)
        """
        if self.ml_analyzer is None or model_name is None:
            return pd.Series(0, index=df.index)
            
        # 準備特徵
        feature_cols = [col for col in df.columns if col not in ['Target', 'Target_Binary']]
        
        # 獲取目標列名
        close_col = self._get_column_name(df, 'Close')
        if close_col is None:
            return pd.Series(0, index=df.index)
            
        # 預測
        try:
            X_pred = self.ml_analyzer.prepare_features(df, feature_cols)
            
            # 檢查X_pred是否為空
            if X_pred.empty:
                return pd.Series(0, index=df.index)
                
            predictions = self.ml_analyzer.predict(X_pred, model_name)
            
            # 生成信號
            signals = pd.Series(0, index=df.index)
            
            if model_name.endswith('classifier'):
                # 分類模型直接返回買入/賣出信號
                # 將 numpy 數組轉換為 pandas Series
                if isinstance(predictions, np.ndarray):
                    # 確保長度一致
                    if len(predictions) == len(signals):
                        for i in range(len(predictions)):
                            signals.iloc[i] = int(predictions[i])
                    else:
                        # 長度不一致，只使用前面的部分
                        for i in range(min(len(predictions), len(signals))):
                            signals.iloc[i] = int(predictions[i])
                else:
                    # 嘗試轉換為numpy數組
                    try:
                        predictions_array = np.array(predictions)
                        for i in range(min(len(predictions_array), len(signals))):
                            signals.iloc[i] = int(predictions_array[i])
                    except:
                        # 如果轉換失敗，返回原始信號
                        pass
            else:
                # 回歸模型預測價格變化
                if isinstance(predictions, np.ndarray):
                    for i in range(len(df) - 5):
                        if i + 5 < len(predictions):
                            # 預測價格上漲
                            if predictions[i + 5] > df[close_col].iloc[i] * 1.02:
                                signals.iloc[i] = 1
                            # 預測價格下跌
                            elif predictions[i + 5] < df[close_col].iloc[i] * 0.98:
                                signals.iloc[i] = -1
            
            return signals
        except Exception as e:
            print(f"獲取機器學習預測時出錯: {str(e)}")
            return pd.Series(0, index=df.index)
    
    def get_math_signals(self, df):
        """獲取數學模型信號
        
        Args:
            df: 股票數據DataFrame
            
        Returns:
            數學模型信號 (-1 賣出, 0 持有, 1 買入)
        """
        if self.math_analyzer is None:
            return pd.Series(0, index=df.index)
            
        signals = pd.Series(0, index=df.index)
        
        # 獲取收盤價列名
        close_col = self._get_column_name(df, 'Close')
        if close_col is None:
            return signals
            
        try:
            # 檢查時間序列平穩性
            stationarity = self.math_analyzer.check_stationarity(df[close_col])
            
            # 擬合ARIMA模型
            arima_model = self.math_analyzer.fit_arima(df[close_col], order=(5,1,0))
            
            # 檢查模型是否成功擬合
            if arima_model is None:
                return signals
                
            forecast = self.math_analyzer.forecast_arima(steps=5)
            
            # 檢查預測結果是否有效
            if forecast is None or len(forecast) == 0:
                return signals
                
            # 生成信號
            last_price = df[close_col].iloc[-1]
            
            # 確保forecast是數值型
            try:
                forecast_value = float(forecast.iloc[-1] if hasattr(forecast, 'iloc') else forecast[-1])
                if forecast_value > last_price * 1.02:
                    signals.iloc[-5:] = 1  # 預測價格上漲
                elif forecast_value < last_price * 0.98:
                    signals.iloc[-5:] = -1  # 預測價格下跌
            except (TypeError, ValueError):
                # 如果無法轉換為float，使用默認信號
                pass
                
            # 計算波動率
            returns = df[close_col].pct_change().dropna()
            volatility = self.math_analyzer.calculate_volatility(returns, window=20)
            
            # 高波動率時降低信號強度
            if not volatility.empty and volatility.iloc[-1] > 0.02:
                signals = signals * 0.5
                
            return signals
        except Exception as e:
            print(f"獲取數學模型預測時出錯: {str(e)}")
            return signals
    
    def generate_recommendation(self, df):
        """生成綜合建議
        
        Args:
            df: 股票數據DataFrame
            
        Returns:
            建議DataFrame
        """
        # 獲取各類信號
        technical_signals = self.get_technical_signals(df)
        ml_signals = self.get_ml_signals(df, model_name='random_forest_classifier')
        math_signals = self.get_math_signals(df)
        
        # 確保信號長度一致
        min_length = min(len(technical_signals), len(ml_signals), len(math_signals))
        technical_signals = technical_signals.iloc[-min_length:]
        ml_signals = ml_signals.iloc[-min_length:]
        math_signals = math_signals.iloc[-min_length:]
        
        # 加權組合信號
        combined_signals = (
            technical_signals * self.weights['technical'] +
            ml_signals * self.weights['ml'] +
            math_signals * self.weights['math']
        )
        
        # 生成建議
        recommendations = pd.DataFrame({
            'Technical_Signal': technical_signals,
            'ML_Signal': ml_signals,
            'Math_Signal': math_signals,
            'Combined_Signal': combined_signals
        })
        
        # 添加建議類別
        recommendations['Recommendation'] = pd.cut(
            combined_signals,
            bins=[-1.1, -0.3, 0.3, 1.1],
            labels=['賣出', '持有', '買入']
        )
        
        # 添加建議文本
        recommendations['Recommendation_Text'] = recommendations['Recommendation'].apply(self._signal_to_text)
        
        return recommendations
    
    def get_latest_recommendation(self, df, days=5):
        """獲取最近幾天的建議
        
        Args:
            df: 股票數據DataFrame
            days: 天數
            
        Returns:
            最近幾天的建議DataFrame
        """
        recommendations = self.generate_recommendation(df)
        
        # 確保索引是日期類型
        if not isinstance(df.index, pd.DatetimeIndex):
            try:
                # 嘗試獲取日期列
                date_col = self._get_column_name(df, 'Date')
                if date_col and date_col in df.columns:
                    # 將日期列轉換為索引
                    df_copy = df.copy()
                    df_copy.index = pd.to_datetime(df_copy[date_col])
                    recommendations.index = df_copy.index
                else:
                    # 如果沒有日期列，創建一個假的日期索引
                    recommendations.index = pd.date_range(end=datetime.now(), periods=len(recommendations))
            except Exception as e:
                print(f"處理日期索引時出錯: {str(e)}")
                # 創建一個假的日期索引
                recommendations.index = pd.date_range(end=datetime.now(), periods=len(recommendations))
        
        return recommendations.iloc[-days:]
    
    def generate_report(self, ticker, df):
        """生成詳細分析報告
        
        Args:
            ticker: 股票代碼
            df: 數據DataFrame
            
        Returns:
            str: 分析報告
        """
        # 獲取最新數據
        latest_data = df.iloc[-1]
        
        # 獲取收盤價列名
        close_col = self._get_column_name(df, 'Close')
        if close_col is None:
            print("錯誤: 找不到收盤價列，請確保數據中包含'Close'或'收盤價'列")
            return "無法生成報告: 找不到收盤價列"
            
        latest_price = float(latest_data[close_col])
        
        # 獲取最新信號
        try:
            latest_signal = float(self.generate_recommendation(df.iloc[-20:]))
        except:
            latest_signal = 0.0  # 默認為持有
            
        signal_text = self._signal_to_text(latest_signal)
        
        # 獲取技術指標
        rsi = None
        macd = None
        macd_signal = None
        
        if 'RSI' in df.columns:
            rsi = float(latest_data['RSI'])
            
        if 'MACD' in df.columns:
            macd = float(latest_data['MACD'])
            
        if 'MACD_Signal' in df.columns:
            macd_signal = float(latest_data['MACD_Signal'])
        elif 'MACD_signal' in df.columns:
            macd_signal = float(latest_data['MACD_signal'])
            
        # 獲取機器學習預測
        ml_prediction = "無法獲取"
        ml_regression = "無法獲取"
        
        try:
            # 獲取分類預測
            ml_signal = float(self.get_ml_signals(df.iloc[-60:]))
            if ml_signal > 0.5:
                ml_prediction = "上漲"
            elif ml_signal < -0.5:
                ml_prediction = "下跌"
            else:
                ml_prediction = "持平"
                
            # 獲取回歸預測
            if hasattr(self.ml_analyzer, 'regression_model'):
                X_test = self.ml_analyzer.prepare_features(df.iloc[-1:])
                if X_test is not None and len(X_test) > 0:
                    predicted_price = float(self.ml_analyzer.predict(X_test, 'regression')[0])
                    price_change = (predicted_price - latest_price) / latest_price * 100
                    ml_regression = f"{predicted_price:.2f} (變化: {price_change:.2%})"
        except Exception as e:
            print(f"獲取機器學習預測時出錯: {str(e)}")
            
        # 獲取數學模型預測
        math_prediction = "無法獲取"
        volatility = "無法獲取"
        
        try:
            # 計算波動率
            returns = df[close_col].pct_change().dropna()
            vol = float(returns.rolling(window=20).std().iloc[-1] * 100)
            volatility = f"{vol:.2f}%"
            
            # 獲取ARIMA預測
            math_signal = float(self.get_math_signals(df.iloc[-60:]))
            if math_signal > 0.5:
                math_prediction = "上漲"
            elif math_signal < -0.5:
                math_prediction = "下跌"
            else:
                math_prediction = "持平"
        except Exception as e:
            print(f"獲取數學模型預測時出錯: {str(e)}")
            
        # 生成建議
        advice = self._generate_advice(latest_signal, rsi, macd, macd_signal)
        
        # 處理RSI和MACD的解釋文本
        rsi_text = "無法獲取"
        if rsi is not None:
            rsi_text = f"{rsi:.2f} ({self._interpret_rsi(rsi)})"
        
        macd_text = "無法獲取"
        if macd is not None and macd_signal is not None:
            macd_text = f"{macd:.2f}, 信號線: {macd_signal:.2f} ({self._interpret_macd(macd, macd_signal)})"
        
        # 組合報告
        report = f"""
===== {ticker} 股票分析報告 =====

最新價格: {latest_price:.2f}
建議操作: {signal_text}
信號強度: {latest_signal:.2f} (-1 賣出, 0 持有, 1 買入)

技術分析:
- RSI: {rsi_text}
- MACD: {macd_text}

機器學習預測:
- 分類模型預測: {ml_prediction}
- 回歸模型預測: {ml_regression}

數學模型預測:
- 20日波動率: {volatility}

綜合建議:
{advice}
"""
        
        # 保存報告到文件
        try:
            import os
            save_dir = os.path.join("D:", "Min", "Python", "Project", "FA_Data", "test_data")
            if not os.path.exists(save_dir):
                os.makedirs(save_dir)
                
            report_path = os.path.join(save_dir, f"{ticker}_recommendation_report.txt")
            with open(report_path, 'w', encoding='utf-8-sig') as f:
                f.write(report)
                
            print(f"推薦報告已保存至 {report_path}")
        except Exception as e:
            print(f"保存報告時出錯: {str(e)}")
            
        return report
    
    def _signal_to_text(self, signal):
        """將信號轉換為文本
        
        Args:
            signal: 信號值
            
        Returns:
            str: 信號文本
        """
        # 檢查信號類型
        if isinstance(signal, (int, float)):
            # 數值型信號
            if signal > 0.5:
                return "買入 - 市場趨勢向上"
            elif signal < -0.5:
                return "賣出 - 市場趨勢向下"
            else:
                return "持有 - 市場趨勢不明確"
        elif isinstance(signal, str):
            # 字符串型信號
            if signal == '買入':
                return "買入 - 市場趨勢向上"
            elif signal == '賣出':
                return "賣出 - 市場趨勢向下"
            else:
                return "持有 - 市場趨勢不明確"
        else:
            # 其他類型，嘗試轉換為字符串
            try:
                signal_value = float(signal)
                if signal_value > 0.5:
                    return "買入 - 市場趨勢向上"
                elif signal_value < -0.5:
                    return "賣出 - 市場趨勢向下"
                else:
                    return "持有 - 市場趨勢不明確"
            except:
                return "持有 - 無法解析信號"
            
    def _generate_advice(self, signal, rsi=None, macd=None, macd_signal=None):
        """生成詳細建議
        
        Args:
            signal: 信號值
            rsi: RSI值
            macd: MACD值
            macd_signal: MACD信號線值
            
        Returns:
            str: 詳細建議
        """
        # 檢查信號類型並轉換為數值
        try:
            if isinstance(signal, (int, float)):
                signal_value = signal
            elif isinstance(signal, str):
                if signal == '買入':
                    signal_value = 1.0
                elif signal == '賣出':
                    signal_value = -1.0
                else:
                    signal_value = 0.0
            else:
                # 嘗試轉換為浮點數
                signal_value = float(signal)
        except:
            signal_value = 0.0  # 默認為持有
        
        # 根據信號值生成建議
        if signal_value > 0.5:
            advice = "建議買入。技術指標顯示上漲趨勢。"
            
            # 添加RSI分析
            if rsi is not None:
                if rsi < 30:
                    advice += "\n- RSI顯示超賣狀態，支持買入決策。"
                elif rsi > 70:
                    advice += "\n- 注意：RSI顯示超買狀態，可能存在回調風險。"
                    
            # 添加MACD分析
            if macd is not None and macd_signal is not None:
                if macd > macd_signal:
                    advice += "\n- MACD顯示上升趨勢，支持買入決策。"
                else:
                    advice += "\n- 注意：MACD顯示下降趨勢，可能不是最佳買入時機。"
                    
        elif signal_value < -0.5:
            advice = "建議賣出。技術指標顯示下跌趨勢。"
            
            # 添加RSI分析
            if rsi is not None:
                if rsi > 70:
                    advice += "\n- RSI顯示超買狀態，支持賣出決策。"
                elif rsi < 30:
                    advice += "\n- 注意：RSI顯示超賣狀態，可能不是最佳賣出時機。"
                    
            # 添加MACD分析
            if macd is not None and macd_signal is not None:
                if macd < macd_signal:
                    advice += "\n- MACD顯示下降趨勢，支持賣出決策。"
                else:
                    advice += "\n- 注意：MACD顯示上升趨勢，可能不是最佳賣出時機。"
                    
        else:
            advice = "建議持有或觀望。市場趨勢不明確，各指標顯示混合信號。"
            
            # 添加MACD分析
            if macd is not None and macd_signal is not None:
                if macd > macd_signal:
                    advice += "\n- MACD顯示上升趨勢，支持買入決策。"
                else:
                    advice += "\n- MACD顯示下降趨勢，支持賣出決策。"
                    
        return advice 
    
    def _interpret_rsi(self, rsi):
        """解釋RSI指標
        
        Args:
            rsi: RSI值
            
        Returns:
            str: RSI解釋
        """
        if rsi is None:
            return "無法獲取"
        
        if rsi < 30:
            return "超賣"
        elif rsi > 70:
            return "超買"
        else:
            return "中性"
            
    def _interpret_macd(self, macd, macd_signal):
        """解釋MACD指標
        
        Args:
            macd: MACD值
            macd_signal: MACD信號線值
            
        Returns:
            str: MACD解釋
        """
        if macd is None or macd_signal is None:
            return "無法獲取"
        
        if macd > macd_signal:
            return "上升趨勢"
        else:
            return "下降趨勢" 