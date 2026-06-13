import os
import sys
import time
import pytest
from pathlib import Path
from uuid import uuid4
import pandas as pd
from unittest.mock import MagicMock

# 確保 Qt offscreen 運行
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import app_module.strategies  # 確保測試行程 (主行程) 載入並註冊所有內建策略
from data_module.config import TWStockConfig
from app_module.strategy_spec import StrategySpec
from app_module.backtest_service import BacktestService
from app_module.batch_backtest_service import BatchBacktestService
from app_module.backtest_repository import BacktestRunRepository
from app_module.exceptions import BacktestCancelledError


# ==========================================
# 測試專用 Worker 函數 (模組頂層以利 Windows spawn pickle)
# ==========================================
def parallel_test_worker_with_delay(*args, **kwargs):
    import time
    from app_module.batch_backtest_service import _run_batch_backtest_worker
    stock_code = args[1]
    # 讓 2317 延遲，以提供時間給主執行緒取消
    if stock_code == "2317":
        time.sleep(0.4)
    return _run_batch_backtest_worker(*args, **kwargs)


def parallel_test_worker_with_crash(*args, **kwargs):
    import os
    from app_module.batch_backtest_service import _run_batch_backtest_worker
    stock_code = args[1]
    if stock_code == "FORCE_KILL_SUBPROCESS":
        os._exit(1)
    return _run_batch_backtest_worker(*args, **kwargs)


# ==========================================
# 輔助函式：建立測試 Config 與 mock CSV 資料
# ==========================================
def create_test_env(tmp_path: Path):
    config = TWStockConfig(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        profile="unit",
    )
    config.data_root.mkdir(parents=True, exist_ok=True)
    config.output_root.mkdir(parents=True, exist_ok=True)

    # 建立 CSV 價格數據 (stock_data_whole.csv)
    stock_data_file = config.stock_data_file

    # 建立含有 3 檔股票且各有 3 天資料的假資料 (確保可執行完整平倉交易且時間跨度滿 6 個月)
    csv_content = (
        "證券代號,日期,開盤價,最高價,最低價,收盤價,成交股數,成交量\n"
        "2330,20260101,100.0,105.0,95.0,102.0,1000000,1000\n"
        "2330,20260301,102.0,108.0,101.0,106.0,1000000,1000\n"
        "2330,20260630,106.0,110.0,105.0,108.0,1000000,1000\n"
        "2317,20260101,50.0,52.0,49.0,51.0,1000000,1000\n"
        "2317,20260301,51.0,53.0,50.0,52.0,1000000,1000\n"
        "2317,20260630,52.0,54.0,51.0,53.0,1000000,1000\n"
        "3008,20260101,300.0,310.0,290.0,305.0,1000000,1000\n"
        "3008,20260301,305.0,315.0,300.0,310.0,1000000,1000\n"
        "3008,20260630,310.0,320.0,305.0,315.0,1000000,1000\n"
    )
    stock_data_file.write_text(csv_content, encoding="utf-8")

    return config


def get_test_strategy_spec():
    """返回一個已配置的穩健策略 spec，設定極端閾值以在三天內完成 1 次完整平倉交易"""
    return StrategySpec(
        strategy_id="stable_conservative_v1",
        strategy_version="1.0.0",
        name="穩健策略",
        description="",
        regime=[],
        risk_level="low",
        target_type="stock",
        config={
            'params': {
                'buy_score': -100,          # 第一天 TotalScore (0.0) >= -100 觸發買入信號
                'sell_score': 100,          # 第二天 TotalScore (0.0) <= 100 觸發賣出信號 (平倉)
                'buy_confirm_days': 1,
                'sell_confirm_days': 1,
                'cooldown_days': 0
            }
        }
    )


# ==========================================
# 測試案例 1: UUID run_id 唯一性與 DB 不覆寫驗證
# ==========================================
def test_uuid_run_id_and_db_uniqueness(tmp_path):
    config = create_test_env(tmp_path)

    # 初始化服務與資料庫
    backtest_service = BacktestService(config)
    run_repo = BacktestRunRepository(config)
    batch_service = BatchBacktestService(backtest_service, run_repo)

    strategy_spec = get_test_strategy_spec()

    # 執行並行批次回測 (股票數 3 檔，大於門檻 2)
    batch_result = batch_service.run_batch_backtest(
        stock_codes=["2330", "2317", "3008"],
        start_date="2026-01-01",
        end_date="2026-06-30",
        strategy_spec=strategy_spec,
        save_runs=True,
        parallel_threshold=2,
        max_workers=2
    )

    # 斷言 3 檔皆成功
    assert len(batch_result.stock_results) == 3
    for res in batch_result.stock_results:
        assert res.success is True
        assert res.run_id is not None
        # 斷言 run_id 格式包含 UUID 的部分特徵或唯一性
        assert "run_" in res.run_id

    # 驗證 3 檔的 run_id 互不相同
    run_ids = [res.run_id for res in batch_result.stock_results]
    assert len(set(run_ids)) == 3

    # 查詢資料庫，斷言 SQLite 中確實存在這 3 筆獨立紀錄
    all_runs = run_repo.list_runs()
    db_run_ids = [r['run_id'] for r in all_runs]

    for rid in run_ids:
        assert rid in db_run_ids


# ==========================================
# 測試案例 2: 安全軟取消與 running futures 結束測試
# ==========================================
def test_cooperative_soft_cancellation(tmp_path):
    config = create_test_env(tmp_path)

    backtest_service = BacktestService(config)
    run_repo = BacktestRunRepository(config)
    batch_service = BatchBacktestService(backtest_service, run_repo, worker_callable=parallel_test_worker_with_delay)

    strategy_spec = get_test_strategy_spec()

    # 設置取消控制旗標
    cancel_flag = False

    def check_cancel():
        return cancel_flag

    # 進度回調：當完成第一檔時，立即觸發 cancel_flag
    def progress_callback(current, total, code, message):
        nonlocal cancel_flag
        if current >= 1:
            cancel_flag = True

    # 執行批次回測，提供時間給主行程取消
    with pytest.raises(BacktestCancelledError):
        batch_service.run_batch_backtest(
            stock_codes=["2330", "2317", "3008"],
            start_date="2026-01-01",
            end_date="2026-06-30",
            strategy_spec=strategy_spec,
            save_runs=True,
            progress_callback=progress_callback,
            check_cancel=check_cancel,
            parallel_threshold=2,
            max_workers=2
        )

    # 驗證取消後的 DB 狀態：最多只有取消生效前完成的數量 (通常為 1 或 2，絕對小於 3)
    all_runs = run_repo.list_runs()
    assert len(all_runs) < 3


# ==========================================
# 測試案例 3: 自適應循序分流測試
# ==========================================
def test_adaptive_fallback(tmp_path):
    config = create_test_env(tmp_path)
    backtest_service = BacktestService(config)
    run_repo = BacktestRunRepository(config)
    batch_service = BatchBacktestService(backtest_service, run_repo)

    strategy_spec = get_test_strategy_spec()

    # 案例 A: 股票數為 3 檔，但 parallel_threshold=5 (未達門檻，走循序)
    # 我們可以透過 Mock 回調來檢查
    mock_callback = MagicMock()
    batch_service.run_batch_backtest(
        stock_codes=["2330", "2317", "3008"],
        start_date="2026-01-01",
        end_date="2026-06-30",
        strategy_spec=strategy_spec,
        save_runs=True,
        progress_callback=mock_callback,
        parallel_threshold=5
    )

    # 驗證 callback 有被調用
    assert mock_callback.call_count == 3
    # 驗證循序執行下的訊息包含 "(循序)"
    for call in mock_callback.call_args_list:
        assert "(循序)" in call[0][3]


# ==========================================
# 測試案例 4: 例外與非法股票處理測試
# ==========================================
def test_invalid_stock_handling(tmp_path):
    config = create_test_env(tmp_path)
    backtest_service = BacktestService(config)
    run_repo = BacktestRunRepository(config)
    batch_service = BatchBacktestService(backtest_service, run_repo)

    strategy_spec = get_test_strategy_spec()

    # 我們傳入一個不存在的股票代號 "9999" (會拋出資料不足/無法載入) 以及兩個合法的股票
    batch_result = batch_service.run_batch_backtest(
        stock_codes=["2330", "9999", "2317"],
        start_date="2026-01-01",
        end_date="2026-06-30",
        strategy_spec=strategy_spec,
        save_runs=True,
        parallel_threshold=2,
        max_workers=2
    )

    # 主行程沒有 crash 且正常返回結果
    assert len(batch_result.stock_results) == 3
    results_dict = {res.stock_code: res for res in batch_result.stock_results}

    # 驗證合法的成功
    assert results_dict["2330"].success is True
    assert results_dict["2317"].success is True

    # 驗證非法的失敗，且有正確錯誤原因而不使主線程卡死
    assert results_dict["9999"].success is False
    assert "無法載入股票數據" in results_dict["9999"].error_reason


# ==========================================
# 測試案例 5: 真正的 BrokenProcessPool 處理測試
# ==========================================
def test_broken_process_pool_handling(tmp_path):
    config = create_test_env(tmp_path)
    backtest_service = BacktestService(config)
    run_repo = BacktestRunRepository(config)
    batch_service = BatchBacktestService(backtest_service, run_repo, worker_callable=parallel_test_worker_with_crash)

    strategy_spec = get_test_strategy_spec()

    # 傳入 "FORCE_KILL_SUBPROCESS" 模擬子進程異常突發退出 (os._exit)，這會損壞進程池
    batch_result = batch_service.run_batch_backtest(
        stock_codes=["2330", "FORCE_KILL_SUBPROCESS", "2317"],
        start_date="2026-01-01",
        end_date="2026-06-30",
        strategy_spec=strategy_spec,
        save_runs=True,
        parallel_threshold=2,
        max_workers=2
    )

    # 驗證主線程優雅捕獲 BrokenProcessPool 錯誤，且不會卡死
    assert len(batch_result.stock_results) == 3
    results_dict = {res.stock_code: res for res in batch_result.stock_results}

    # "FORCE_KILL_SUBPROCESS" 必然失敗
    assert results_dict["FORCE_KILL_SUBPROCESS"].success is False
    assert results_dict["FORCE_KILL_SUBPROCESS"].error_reason is not None


# ==========================================
# 測試案例 6: max_workers=None 的真實 UI 並行路徑測試
# ==========================================
def test_parallel_max_workers_none(tmp_path):
    config = create_test_env(tmp_path)
    backtest_service = BacktestService(config)
    run_repo = BacktestRunRepository(config)
    batch_service = BatchBacktestService(backtest_service, run_repo)

    strategy_spec = get_test_strategy_spec()

    # 執行並行批次回測，設定 max_workers=None 模擬 UI 路徑，覆蓋 UnboundLocalError 缺陷
    batch_result = batch_service.run_batch_backtest(
        stock_codes=["2330", "2317"],
        start_date="2026-01-01",
        end_date="2026-06-30",
        strategy_spec=strategy_spec,
        save_runs=False,
        parallel_threshold=2,
        max_workers=None
    )

    assert len(batch_result.stock_results) == 2
    for res in batch_result.stock_results:
        assert res.success is True


# ==========================================
# 測試案例 7: 結果一致性測試
# ==========================================
def test_result_consistency(tmp_path):
    config = create_test_env(tmp_path)
    backtest_service = BacktestService(config)
    run_repo = BacktestRunRepository(config)
    batch_service = BatchBacktestService(backtest_service, run_repo)

    strategy_spec = get_test_strategy_spec()

    # 1. 執行並行路徑
    parallel_res = batch_service.run_batch_backtest(
        stock_codes=["2330", "2317"],
        start_date="2026-01-01",
        end_date="2026-06-30",
        strategy_spec=strategy_spec,
        save_runs=False,
        parallel_threshold=2,
        max_workers=2
    )

    # 2. 執行循序路徑
    sequential_res = batch_service.run_batch_backtest(
        stock_codes=["2330", "2317"],
        start_date="2026-01-01",
        end_date="2026-06-30",
        strategy_spec=strategy_spec,
        save_runs=False,
        parallel_threshold=999 # 強制走循序
    )

    # 比較結果 metrics 100% 一致
    p_dict = {r.stock_code: r for r in parallel_res.stock_results}
    s_dict = {r.stock_code: r for r in sequential_res.stock_results}

    for code in ["2330", "2317"]:
        assert p_dict[code].success == s_dict[code].success
        assert p_dict[code].cagr == s_dict[code].cagr
        assert p_dict[code].sharpe == s_dict[code].sharpe
        assert p_dict[code].mdd == s_dict[code].mdd
        assert p_dict[code].total_trades == s_dict[code].total_trades
