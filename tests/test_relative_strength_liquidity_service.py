from datetime import date, timedelta
import pandas as pd
from app_module.decision_desk_dtos import DecisionDeskQuality
from app_module.relative_strength_liquidity_service import RelativeStrengthLiquidityService


class FakeProvider:
    def __init__(self, frame):
        self.frame = frame

    def fetch(self, as_of_date: date):
        return self.frame


def test_relative_strength_liquidity_service_ranks_strength_and_low_liquidity():
    # Construct 21 trading days for 3 symbols
    # We want 2330 to be top_strength, 2454 to be medium, 1101 to be weak and low_liquidity
    base_date = date(2026, 5, 10)
    data = []
    
    # 2330: price goes from 100 to 121 (21% gain)
    # 2454: price goes from 200 to 220 (10% gain)
    # 1101: price goes from 50 to 45 (10% loss), and very low volume
    for i in range(22): # 22 days to ensure len(history) >= 21
        current_date = (base_date + timedelta(days=i)).strftime("%Y-%m-%d")
        
        # 2330
        close_2330 = 100 + i
        data.append({"日期": current_date, "證券代號": "2330", "收盤價": str(close_2330), "成交股數": "1000000"})
        
        # 2454
        close_2454 = 200 + i
        data.append({"日期": current_date, "證券代號": "2454", "收盤價": str(close_2454), "成交股數": "500000"})
        
        # 1101
        close_1101 = 50 - (i * 0.25)
        data.append({"日期": current_date, "證券代號": "1101", "收盤價": str(close_1101), "成交股數": "100"}) # 100 * 50 = 5000 (very low turnover)

    frame = pd.DataFrame(data)
    # Target date is the last day
    target_date = base_date + timedelta(days=21)
    
    service = RelativeStrengthLiquidityService(
        FakeProvider(frame),
        top_n=2,
        min_avg_turnover=20_000_000, # 20M
    )

    snapshot = service.build_snapshot(target_date)

    assert snapshot.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.top_strength_codes == ("2330", "2454")
    assert snapshot.weak_strength_codes == ("1101",)
    assert snapshot.low_liquidity_codes == ("1101",)
    
    ranking = snapshot.meta["ranking"]
    assert ranking[0]["stock_code"] == "2330"
    # strength_20d_bp: 2330: (121 - 101) / 101 * 10000 = 19.8% * 10000 = 1980 bp
    # strength_5d_bp: 2330: (121 - 116) / 116 * 10000 = 431 bp
    assert ranking[0]["strength_20d_bp"] > 0
    assert ranking[0]["strength_5d_bp"] > 0


def test_relative_strength_liquidity_service_marks_degraded_when_history_is_insufficient():
    # Only 10 days of history
    base_date = date(2026, 5, 10)
    data = []
    for i in range(10):
        current_date = (base_date + timedelta(days=i)).strftime("%Y-%m-%d")
        data.append({"日期": current_date, "證券代號": "2330", "收盤價": "100", "成交股數": "100000"})
        data.append({"日期": current_date, "證券代號": "1101", "收盤價": "50", "成交股數": "1000"})

    frame = pd.DataFrame(data)
    target_date = base_date + timedelta(days=9)
    service = RelativeStrengthLiquidityService(FakeProvider(frame), top_n=3)

    snapshot = service.build_snapshot(target_date)

    assert snapshot.quality == DecisionDeskQuality.DEGRADED
    assert snapshot.top_strength_codes == ()
    assert "relative_strength_liquidity_insufficient_history" in snapshot.warnings


def test_relative_strength_liquidity_service_missing_when_frame_has_only_future_dates():
    frame = pd.DataFrame(
        [
            {"日期": "2026-06-16", "證券代號": "2330", "收盤價": "120", "成交股數": "10000000"},
        ]
    )
    service = RelativeStrengthLiquidityService(FakeProvider(frame), top_n=3)

    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.MISSING
    assert snapshot.warnings == ("relative_strength_liquidity_missing",)
