import pytest
import pandas as pd
import numpy as np
from typing import Dict, List, Any

from app_module.recommendation_replay_service import RecommendationReplayService
from app_module.recommendation_portfolio_backtest_service import RecommendationPortfolioBacktestService
from backtest_module.broker_simulator import BrokerSimulator, BrokerConfig, Trade
from backtest_module.performance_metrics import PerformanceAnalyzer


# ==========================================
# 測試案例 1: 推薦 Replay 無未來資料限制 (no-look-ahead)
# ==========================================
def test_recommendation_replay_strict_no_look_ahead():
    """
    驗證 RecommendationReplayService 在進行 replay 時，
    絕對不會讓 provider 取得 as_of_date 之後的未來資料。
    """
    called_dates = []

    def dummy_provider(as_of_data: pd.DataFrame, config: Dict[str, Any], top_n: int) -> List[Dict[str, Any]]:
        # 記錄 provider 實際拿到的最大日期
        called_dates.append(as_of_data["日期"].max())
        return [
            {
                "stock_code": "2330",
                "stock_name": "台積電",
                "total_score": 90.0,
                "factor_scores": {"technical": 90.0},
            }
        ]

    # 構造歷史資料，包含 T 日 (2026-06-01) 與 T+1 日 (2026-06-02)
    history = pd.DataFrame([
        {"日期": "2026-06-01", "證券代號": "2330", "收盤價": 100},
        {"日期": "2026-06-02", "證券代號": "2330", "收盤價": 200},  # 未來的極端跳空
    ])
    history["日期"] = pd.to_datetime(history["日期"])

    service = RecommendationReplayService(provider=dummy_provider)
    
    # 執行 T 日的 replay
    snapshot = service.run_snapshot(
        as_of_date="2026-06-01",
        profile_id="test_profile",
        config={},
        history=history,
        universe=None,
        top_n=1
    )

    # 斷言：provider 拿到的資料中，最大日期必須是 2026-06-01，不能看見 2026-06-02
    assert len(called_dates) == 1
    assert called_dates[0].strftime("%Y-%m-%d") == "2026-06-01"
    assert snapshot.as_of_date == "2026-06-01"


# ==========================================
# 測試案例 2: 推薦組合回測 (Portfolio Backtest) 進出場時間軸對齊與收盤成交斷言
# ==========================================
def test_portfolio_backtest_entry_exit_dates_alignment():
    """
    驗證推薦組合回測的期末持倉 (PeriodHoldingDTO) 對時間軸契約的遵守：
    1. entry_date <= actual_exit_date
    2. rebalance_date == entry_date（斷言收盤價同日成交假設）
    3. 觸發並驗證 idealized research warning 與 metadata
    """
    # 構造兩天的資料，2026-06-01 推薦並進場，2026-06-02 出場
    history = pd.DataFrame([
        {"日期": "2026-06-01", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 100.0},
        {"日期": "2026-06-02", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 110.0},
    ])
    history["日期"] = pd.to_datetime(history["日期"])

    def dummy_provider(as_of_data: pd.DataFrame, config: Dict[str, Any], top_n: int) -> List[Dict[str, Any]]:
        return [
            {
                "stock_code": "2330",
                "stock_name": "台積電",
                "total_score": 90.0,
                "factor_scores": {},
            }
        ]

    service = RecommendationPortfolioBacktestService(provider=dummy_provider)
    
    with pytest.warns(UserWarning) as record:
        result = service.run_portfolio_backtest(
            start_date="2026-06-01",
            end_date="2026-06-02",
            profile_id="test_profile",
            recommendation_config={},
            history=history,
            initial_capital=1000000.0,
            rebalance_frequency="once",
            top_n=1,
            allocation_method="equal_weight",
            holding_days=1,  # 持有 1 天，於第 2 天平倉
        )

    # 驗證拋出 idealized research 警告
    assert len(record) >= 1
    assert "推薦組合回測目前採用「同日收盤訊號同日收盤成交」之理想化研究假設" in str(record[0].message)
    
    # 驗證 metadata 屬性
    assert result.summary["execution_assumption"] == "idealized_same_day_close"

    assert len(result.period_holdings) == 1
    holding = result.period_holdings[0]

    # 1. 驗證進場日小於等於實際出場日
    assert pd.to_datetime(holding.entry_date) <= pd.to_datetime(holding.actual_exit_date)
    
    # 2. 斷言當前的「同日收盤成交」現狀：信號日等於進場日
    assert holding.rebalance_date == holding.entry_date == "2026-06-01"
    assert holding.actual_exit_date == "2026-06-02"
    assert holding.entry_price == 100.0
    assert holding.actual_exit_price == 110.0


# ==========================================
# 測試案例 3: 單股回測 next_open 時間軸對齊
# ==========================================
def test_broker_simulator_next_open_alignment():
    """
    驗證當 execution_price="next_open" 時的帳務對齊行為：
    1. T 日觸發買入信號後，買入交易尚未執行（延後至 T+1 日開盤執行），
       因此 T 日收盤時持股應為 0，現金與總權益應完全維持 initial_capital (100萬)。
    2. T+1 日早上以開盤價 105 成交，收盤時以 T+1 收盤價 106 計算持倉市值。
    """
    dates = pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-03"])
    signal_frame = pd.DataFrame({
        "開盤價": [100.0, 105.0, 110.0],
        "最高價": [102.0, 107.0, 112.0],
        "最低價": [98.0, 103.0, 108.0],
        "收盤價": [100.0, 106.0, 111.0],
        "成交量": [1000000.0] * 3,
        "signal": [1, 0, -1]  # 6-01 買，6-02 持有，6-03 賣出
    }, index=dates)

    config = BrokerConfig(
        execution_price="next_open",
        slippage_bps=0.0,  # 將滑價調為 0
        fee_bps=0.0,       # 將費率調為 0 (但仍有最低手續費 20 元限制)
        enable_volume_constraint=False,
        sizing_mode="all_in"
    )
    simulator = BrokerSimulator(config)
    trades, equity_curve = simulator.run(signal_frame, initial_capital=1000000.0)

    # 1. 買入交易日應為 T+1 (2026-06-02)，開盤價成交 105.0
    buy_trade = [t for t in trades if t.type == "buy"][0]
    assert buy_trade.date.strftime("%Y-%m-%d") == "2026-06-02"
    assert buy_trade.price == 105.0

    # 100萬資金，在 105 元可買 1000 股的倍數為：int(1000000 / 105 / 1000) * 1000 = 9000 股
    assert buy_trade.shares == 9000
    
    # 2. 驗證權益曲線對齊：
    # - 2026-06-01 (T日)：交易尚未執行，持股 0，總權益維持初始的 100 萬
    assert equity_curve.loc["2026-06-01", "equity"] == 1000000.0
    
    # - 2026-06-02 (T+1日)：持股 9000 股。
    #   現金：1,000,000 - 9,000 * 105 - 20 (最低手續費) = 54,980 元。
    #   市值：9,000 * 106 (T+1日收盤價) = 954,000 元。
    #   總權益：54,980 + 954,000 = 1,008,980 元。
    assert equity_curve.loc["2026-06-02", "equity"] == 1008980.0


# ==========================================
# 測試案例 4: close 模式拋出警告
# ==========================================
def test_broker_simulator_close_warning():
    """
    驗證當 execution_price="close" 時，BrokerSimulator 會發出 UserWarning 提示未來函數假設。
    """
    dates = pd.to_datetime(["2026-06-01", "2026-06-02"])
    signal_frame = pd.DataFrame({
        "收盤價": [100.0, 105.0],
        "signal": [1, 0]
    }, index=dates)

    config = BrokerConfig(
        execution_price="close",
        enable_volume_constraint=False
    )
    simulator = BrokerSimulator(config)

    with pytest.warns(UserWarning) as record:
        simulator.run(signal_frame, initial_capital=1000000.0)

    # 驗證有發出警告且警告字串包含指定內容
    assert len(record) >= 1
    warning_msg = str(record[0].message)
    assert "execution_price='close' 模式隱含「同日收盤訊號同日收盤成交」之理想化假設" in warning_msg


# ==========================================
# 測試案例 5: Benchmark 切片無未來資料
# ==========================================
def test_benchmark_alignment_no_look_ahead():
    """
    驗證 PerformanceAnalyzer 在計算 Buy & Hold 基準報酬率時，
    即使傳入的 DataFrame 包含回測結束日期之後的未來資料，也絕對不會予以讀取或計入報酬。
    """
    dates = pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-03"])
    df = pd.DataFrame({
        "收盤價": [100.0, 110.0, 200.0]  # 2026-06-03 有極端的未來高價
    }, index=dates)

    analyzer = PerformanceAnalyzer()
    
    # 限制回測區間只到 2026-06-02
    res = analyzer.calculate_buy_hold_return(
        df=df,
        start_date="2026-06-01",
        end_date="2026-06-02"
    )

    # 斷言：2026-06-03 的大漲不應被計入。
    # 總報酬應為 (110 - 100) / 100 = 0.10
    assert abs(res["total_return"] - 0.10) < 1e-6
