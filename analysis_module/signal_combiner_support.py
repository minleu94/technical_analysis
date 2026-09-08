"""兩個歷史 SignalCombiner 的共用分析流程；不承擔回測或可靠性政策。"""


class SignalCombinationMixin:
    """保留子類的分析器與可靠性 hook，避免兩套相同流程各自漂移。"""

    def analyze_combined_signals(self, df, pattern_types=None, technical_indicators=None, volume_conditions=None):
        """分析組合信號

        Args:
            df: 數據DataFrame
            pattern_types: 要識別的形態類型列表，例如 ['W底', '頭肩頂', '頭肩底']
            technical_indicators: 要計算的技術指標列表，例如 ['momentum', 'volatility', 'trend']
            volume_conditions: 要檢查的交易量條件列表，例如 ['increasing', 'decreasing', 'spike']

        Returns:
            DataFrame: 包含組合信號的DataFrame
        """
        df_result = df.copy()

        # 識別形態
        patterns_found = {}
        if pattern_types:
            for pattern_type in pattern_types:
                patterns_found[pattern_type] = self.pattern_analyzer.identify_pattern(df, pattern_type)

        # 計算技術指標
        if technical_indicators:
            if 'momentum' in technical_indicators:
                df_result = self.technical_analyzer.add_momentum_indicators(df_result)
            if 'volatility' in technical_indicators:
                df_result = self.technical_analyzer.add_volatility_indicators(df_result)
            if 'trend' in technical_indicators:
                df_result = self.technical_analyzer.add_trend_indicators(df_result)

        # 分析交易量
        if volume_conditions:
            df_result = self._analyze_volume(df_result, volume_conditions)

        # 組合信號
        signals = self._combine_signals(df_result, patterns_found)

        # 評估信號可靠性
        signals = self._evaluate_signal_reliability(signals)

        return signals

    def _analyze_volume(self, df, volume_conditions):
        """分析交易量

        Args:
            df: 數據DataFrame
            volume_conditions: 要檢查的交易量條件列表

        Returns:
            DataFrame: 添加交易量分析結果的DataFrame
        """
        df_result = df.copy()
        volume_col = self._get_column_name(df, 'Volume')

        if not volume_col:
            print("警告: 找不到交易量列")
            return df_result

        # 計算交易量的移動平均
        df_result['Volume_MA5'] = df[volume_col].rolling(window=5).mean()
        df_result['Volume_MA20'] = df[volume_col].rolling(window=20).mean()

        # 檢查交易量是否增加
        df_result['Volume_Increasing'] = (df[volume_col] > df_result['Volume_MA5']).astype(int)

        # 檢查交易量是否減少
        df_result['Volume_Decreasing'] = (df[volume_col] < df_result['Volume_MA5']).astype(int)

        # 檢查交易量是否出現尖峰
        df_result['Volume_Spike'] = ((df[volume_col] / df_result['Volume_MA5']) > 2).astype(int)

        return df_result

    def _combine_signals(self, df, patterns):
        """組合不同來源的信號

        Args:
            df: 數據DataFrame
            patterns: 識別出的形態字典，格式為 {形態類型: [(開始索引, 結束索引), ...]}

        Returns:
            DataFrame: 包含組合信號的DataFrame
        """
        df_result = df.copy()

        # 創建信號列
        df_result['Pattern_Signal'] = 0  # 0表示無信號，1表示看漲信號，-1表示看跌信號

        # 添加形態信號
        for pattern_type, pattern_positions in patterns.items():
            for start_idx, end_idx in pattern_positions:
                # 根據形態類型設置信號
                if pattern_type in ['W底', '頭肩底']:
                    # 看漲形態
                    df_result.loc[end_idx, 'Pattern_Signal'] = 1
                elif pattern_type in ['頭肩頂']:
                    # 看跌形態
                    df_result.loc[end_idx, 'Pattern_Signal'] = -1

        # 添加技術指標信號
        df_result['Technical_Signal'] = 0

        # RSI信號
        if 'RSI' in df_result.columns:
            # RSI < 30 表示超賣，看漲信號
            df_result.loc[df_result['RSI'] < 30, 'Technical_Signal'] = 1
            # RSI > 70 表示超買，看跌信號
            df_result.loc[df_result['RSI'] > 70, 'Technical_Signal'] = -1

        # MACD信號
        if all(col in df_result.columns for col in ['MACD', 'MACD_Signal']):
            # MACD上穿信號線，看漲信號
            df_result['MACD_Crossover'] = ((df_result['MACD'] > df_result['MACD_Signal']) &
                                          (df_result['MACD'].shift(1) <= df_result['MACD_Signal'].shift(1))).astype(int)
            # MACD下穿信號線，看跌信號
            df_result['MACD_Crossunder'] = ((df_result['MACD'] < df_result['MACD_Signal']) &
                                           (df_result['MACD'].shift(1) >= df_result['MACD_Signal'].shift(1))).astype(int)

            df_result.loc[df_result['MACD_Crossover'] == 1, 'Technical_Signal'] = 1
            df_result.loc[df_result['MACD_Crossunder'] == 1, 'Technical_Signal'] = -1

        # 布林帶信號
        if all(col in df_result.columns for col in ['BB_Upper', 'BB_Middle', 'BB_Lower']):
            close_col = self._get_column_name(df, 'Close')
            if close_col:
                # 價格觸及下軌，看漲信號
                df_result.loc[df_result[close_col] <= df_result['BB_Lower'], 'Technical_Signal'] = 1
                # 價格觸及上軌，看跌信號
                df_result.loc[df_result[close_col] >= df_result['BB_Upper'], 'Technical_Signal'] = -1

        # 添加交易量信號
        df_result['Volume_Signal'] = 0

        if 'Volume_Spike' in df_result.columns and 'Pattern_Signal' in df_result.columns:
            # 形態確認點的交易量出現尖峰，增強信號
            df_result.loc[(df_result['Pattern_Signal'] != 0) & (df_result['Volume_Spike'] == 1), 'Volume_Signal'] = df_result['Pattern_Signal']

        # 組合所有信號
        df_result['Combined_Signal'] = 0

        # 當形態信號和技術指標信號一致時，產生強信號
        df_result.loc[(df_result['Pattern_Signal'] == 1) & (df_result['Technical_Signal'] == 1), 'Combined_Signal'] = 2  # 強看漲信號
        df_result.loc[(df_result['Pattern_Signal'] == -1) & (df_result['Technical_Signal'] == -1), 'Combined_Signal'] = -2  # 強看跌信號

        # 當只有一種信號時，產生弱信號
        df_result.loc[(df_result['Pattern_Signal'] == 1) & (df_result['Combined_Signal'] == 0), 'Combined_Signal'] = 1  # 弱看漲信號
        df_result.loc[(df_result['Pattern_Signal'] == -1) & (df_result['Combined_Signal'] == 0), 'Combined_Signal'] = -1  # 弱看跌信號
        df_result.loc[(df_result['Technical_Signal'] == 1) & (df_result['Combined_Signal'] == 0), 'Combined_Signal'] = 1  # 弱看漲信號
        df_result.loc[(df_result['Technical_Signal'] == -1) & (df_result['Combined_Signal'] == 0), 'Combined_Signal'] = -1  # 弱看跌信號

        # 當交易量信號確認時，進一步增強信號
        df_result.loc[(df_result['Combined_Signal'] > 0) & (df_result['Volume_Signal'] > 0), 'Combined_Signal'] += 1
        df_result.loc[(df_result['Combined_Signal'] < 0) & (df_result['Volume_Signal'] < 0), 'Combined_Signal'] -= 1

        return df_result
