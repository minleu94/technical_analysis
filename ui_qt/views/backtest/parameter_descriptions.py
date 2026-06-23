"""
回測視圖參數說明資料結構（集中管理）
"""

PARAMETER_DESCRIPTIONS = {
    # 策略參數
    'buy_score': {
        'tooltip_lines': [
            '最低進場分數門檻。',
            '當策略分數連續達到此值以上時，才允許產生買入訊號。',
            '系統角色：進場濾波機制，避免在分數不足時進場。'
        ]
    },
    'sell_score': {
        'tooltip_lines': [
            '最高出場分數門檻。',
            '當策略分數連續低於此值時，才允許產生賣出訊號。',
            '系統角色：出場濾波機制，避免在分數仍高時過早出場。'
        ]
    },
    'buy_confirm_days': {
        'tooltip_lines': [
            '買入確認天數。',
            '策略分數必須連續 N 天達到 buy_score 以上，才真正產生買入訊號。',
            '系統角色：確認機制，減少假訊號和頻繁進出場。'
        ]
    },
    'sell_confirm_days': {
        'tooltip_lines': [
            '賣出確認天數。',
            '策略分數必須連續 N 天低於 sell_score，才真正產生賣出訊號。',
            '系統角色：確認機制，減少假訊號和頻繁進出場。'
        ]
    },
    'cooldown_days': {
        'tooltip_lines': [
            '每次交易後的冷卻期。',
            '在冷卻期間內，即使訊號再次出現，也不允許反向或重新進場。',
            '系統角色：保護機制，避免過度交易和情緒化決策。'
        ]
    },
    'buy_threshold': {
        'tooltip_lines': [
            '最低進場門檻。',
            '當策略分數或指標達到此值以上時，才允許產生買入訊號。',
            '系統角色：進場門檻設定。'
        ]
    },
    'sell_threshold': {
        'tooltip_lines': [
            '最高出場門檻。',
            '當策略分數或指標低於此值時，才允許產生賣出訊號。',
            '系統角色：出場門檻設定。'
        ]
    },
    'confirm_days': {
        'tooltip_lines': [
            '確認天數。',
            '策略分數或指標必須連續 N 天達到閾值，才真正產生訊號。',
            '系統角色：確認機制，減少假訊號和頻繁進出場。'
        ]
    },
    # 回測執行設定
    'execution_price': {
        'tooltip_lines': [
            '定義回測中實際成交使用的價格。',
            'next_open：使用下一根 K 棒的開盤價（較保守，避免偷看未來）。',
            'close：使用當根 K 棒的收盤價（較接近理想化即時成交）。',
            '系統角色：影響回測的樂觀/保守程度，next_open 較保守。'
        ]
    },
    # 停損停利
    'stop_profit_mode': {
        'tooltip_lines': [
            '停損停利模式選擇。',
            '百分比模式：使用固定百分比作為停損停利門檻。',
            'ATR 倍數模式：使用 ATR（平均真實波幅）的倍數，相對波動而非固定百分比。',
            '系統角色：事後風控機制，不是交易訊號來源。'
        ]
    },
    'stop_loss_pct': {
        'tooltip_lines': [
            '停損百分比。',
            '當持倉虧損達到此百分比時，強制平倉。',
            '系統角色：事後風控，保護資金，不產生交易訊號。',
            '設定為 0 表示關閉停損功能。'
        ]
    },
    'take_profit_pct': {
        'tooltip_lines': [
            '停利百分比。',
            '當持倉獲利達到此百分比時，強制平倉。',
            '系統角色：事後風控，鎖定獲利，不產生交易訊號。',
            '設定為 0 表示關閉停利功能。'
        ]
    },
    'stop_loss_atr': {
        'tooltip_lines': [
            '停損 ATR 倍數。',
            '當持倉虧損達到 ATR × 此倍數時，強制平倉。',
            'ATR 模式：根據股票波動性動態調整，而非固定百分比。',
            '系統角色：事後風控，相對波動的風險控制。',
            '設定為 0 表示關閉停損功能。'
        ]
    },
    'take_profit_atr': {
        'tooltip_lines': [
            '停利 ATR 倍數。',
            '當持倉獲利達到 ATR × 此倍數時，強制平倉。',
            'ATR 模式：根據股票波動性動態調整，而非固定百分比。',
            '系統角色：事後風控，相對波動的獲利鎖定。',
            '設定為 0 表示關閉停利功能。'
        ]
    },
    # 部位與資金管理
    'sizing_mode': {
        'tooltip_lines': [
            '部位大小計算模式。',
            '全倉：使用所有可用資金。',
            '固定金額：每次使用固定金額。',
            '風險百分比：根據風險百分比計算部位大小。',
            '系統角色：決定「有訊號時，下多少單」，不產生交易訊號。'
        ]
    },
    'fixed_amount': {
        'tooltip_lines': [
            '固定金額模式下的每次交易金額。',
            '每次進場時使用此固定金額，不受可用資金影響。',
            '系統角色：部位大小控制，不產生交易訊號。'
        ]
    },
    'risk_pct': {
        'tooltip_lines': [
            '風險百分比模式下的風險比例。',
            '根據此百分比和停損距離計算每次交易的部位大小。',
            '系統角色：部位大小控制，確保每次交易風險一致。'
        ]
    },
    'max_positions': {
        'tooltip_lines': [
            '最多同時持有的部位數量。',
            '當達到此數量時，即使有新訊號也不會進場。',
            '系統角色：部位管理限制，不產生交易訊號。',
            '設定為 0 表示無限制；設定為 1 表示最多同時持有 1 檔。'
        ]
    },
    'position_sizing': {
        'tooltip_lines': [
            '多部位時的加權分配方式。',
            '等權重：所有部位平均分配資金。',
            '分數加權：根據策略分數分配資金. ',
            '波動調整：根據波動性調整分配。',
            '系統角色：多部位資金分配，不產生交易訊號。'
        ]
    },
    'allow_pyramid': {
        'tooltip_lines': [
            '允許金字塔式建倉（加碼）。',
            '啟用後，在已有持倉的情況下，如果訊號再次出現，可以加碼。',
            '系統角色：部位管理選項，不產生交易訊號。'
        ]
    },
    'allow_reentry': {
        'tooltip_lines': [
            '允許重新進場。',
            '啟用後，在出場後可以重新進場。',
            '系統角色：部位管理選項，不產生交易訊號。'
        ]
    },
    'reentry_cooldown_days': {
        'tooltip_lines': [
            '重新進場的冷卻天數。',
            '出場後必須等待此天數，才能重新進場。',
            '系統角色：保護機制，避免頻繁進出場。'
        ]
    },
    # 市場限制
    'enable_limit': {
        'tooltip_lines': [
            '啟用漲跌停限制。',
            '當股票漲停或跌停時，不允許進場或出場。',
            '系統角色：可行性約束，可能導致「訊號存在但交易被跳過」。'
        ]
    },
    'enable_volume': {
        'tooltip_lines': [
            '啟用成交量約束。',
            '當成交量不足時，不允許進場或出場。',
            '系統角色：可行性約束，模擬實際交易中的流動性限制。'
        ]
    },
    'max_participation': {
        'tooltip_lines': [
            '最大參與率。',
            '單次交易不得超過該股票當日成交量的此百分比。',
            '系統角色：可行性約束，模擬大額交易對市場的影響。',
            '可能導致「訊號存在但交易被跳過」。'
        ]
    },
    # 分數門檻
    'threshold_mode': {
        'tooltip_lines': [
            '固定門檻會使用 buy_score / sell_score 這類絕對分數判斷訊號。',
            '百分位排名會用決策日前可見的歷史分數分布產生動態門檻，避免偷看未來資料。',
            '百分位排名不一定比較容易交易；若暖機資料不足，系統會等待足夠觀測數。'
        ]
    },
    'buy_quantile_bp': {
        'tooltip_lines': [
            '百分位排名模式下的買進門檻，單位為基點。',
            '8000 代表約第 80 百分位：分數需高於多數歷史觀測才會進場。',
            '數值越高通常越嚴格，交易次數可能越少。'
        ]
    },
    'sell_quantile_bp': {
        'tooltip_lines': [
            '百分位排名模式下的賣出門檻，單位為基點。',
            '4000 代表約第 40 百分位：分數轉弱到此區間時可能出場。',
            '需搭配停損、停利與持有天數一起判讀。'
        ]
    },
    'quantile_warmup_observations': {
        'tooltip_lines': [
            '百分位門檻開始計算前需要累積的歷史觀測數。',
            '目前固定為 60 個交易日，避免用太短樣本產生不穩定門檻。',
            '暖機期間即使分數看似達標，也可能不產生交易。'
        ]
    },
    'quantile_method': {
        'tooltip_lines': [
            '百分位門檻的計算方式。',
            '最近名次法會直接使用排序後最接近的歷史觀測值，較容易追溯。',
            '此參數只影響動態門檻計算，不會自行產生買賣訊號。'
        ]
    },
    # Optimization / Walk-forward
    'optimization_objective': {
        'tooltip_lines': [
            '參數最佳化的目標指標。',
            '夏普比率：風險調整後報酬率。',
            '年化報酬率：年度化總報酬率。',
            'CAGR-MDD權衡：綜合考慮成長率和最大回撤。',
            '系統角色：Grid Search 的優化目標，不是回測本身。'
        ]
    },
    'walkforward_mode': {
        'tooltip_lines': [
            'Walk-forward 驗證模式。',
            'Train-Test Split：將資料分成訓練集和測試集。',
            'Walk-forward：滾動窗口驗證，防止過擬合。',
            '系統角色：防止 overfitting 的驗證方式，不是回測本身。'
        ]
    },
    # 資金與成本設定
    'capital': {
        'tooltip_lines': [
            '回測初始資金。',
            '用於計算報酬率、最大回撤等績效指標。',
            '系統角色：回測計算的基準資金。',
            '台股整股限制：買進股數會向下取整為 1000 股倍數；若資金不足以買一張，該筆交易可能被拒絕並導致 0 交易。'
        ]
    },
    'fee_bps': {
        'tooltip_lines': [
            '手續費（基點，1 bps = 0.01%）。',
            '每次買賣交易時扣除的手續費。',
            '系統角色：模擬實際交易成本，影響淨報酬率。',
            '可設為 0 進行敏感度分析。'
        ]
    },
    'slippage_bps': {
        'tooltip_lines': [
            '滑價（基點，1 bps = 0.01%）。',
            '模擬實際成交價格與預期價格的偏差。',
            '系統角色：模擬實際交易中的價格滑動，影響淨報酬率。',
            '可設為 0 進行敏感度分析。'
        ]
    }
}

PARAMETER_DISPLAY_NAMES = {
    # 策略參數
    'buy_threshold': '買入閾值',
    'sell_threshold': '賣出閾值',
    'confirm_days': '買入確認天數',
    'buy_score': '買入分數門檻',
    'sell_score': '賣出分數門檻',
    'threshold_mode': '門檻模式',
    'buy_quantile_bp': '買進百分位基點',
    'sell_quantile_bp': '賣出百分位基點',
    'quantile_warmup_observations': '百分位暖機觀測數',
    'quantile_method': '百分位計算方法',
    'buy_confirm_days': '買入確認天數',
    'sell_confirm_days': '賣出確認天數',
    'cooldown_days': '交易冷卻天數',
    
    # 指標/其他策略參數
    'ma_period': 'MA週期',
    'rsi_period': 'RSI週期',
    'macd_fast': 'MACD快線週期',
    'macd_slow': 'MACD慢線週期',
    'macd_signal': 'MACD訊號線週期',
    'kd_period': 'KD週期',
    'bollinger_period': '布林通道週期',
    'bollinger_dev': '布林通道標準差',
    
    # 資金與回測執行設定
    'capital': '初始資金',
    'fee_bps': '手續費 (bps)',
    'slippage_bps': '滑價 (bps)',
    'execution_price': '成交價格模式',
    
    # 停損停利
    'stop_profit_mode': '停損停利模式',
    'stop_loss_pct': '百分比停損 (%)',
    'take_profit_pct': '百分比停利 (%)',
    'stop_loss_atr': 'ATR停損倍數',
    'take_profit_atr': 'ATR停利倍數',
    
    # 部位管理
    'sizing_mode': '部位計算模式',
    'fixed_amount': '固定交易金額',
    'risk_pct': '風險百分比 (%)',
    'max_positions': '最大持倉數量',
    'position_sizing': '資金分配方式',
    'allow_pyramid': '允許加碼 (金字塔)',
    'allow_reentry': '允許重新進場',
    'reentry_cooldown_days': '重新進場冷卻天數',
    
    # 市場限制
    'enable_limit': '啟用漲跌停限制',
    'enable_volume': '啟用成交量限制',
    'max_participation': '最大參與率 (%)',
    
    # 最佳化相關
    'optimization_objective': '最佳化目標',
    'walkforward_mode': '驗證模式'
}
