#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
測試券商分點資料更新功能（10天記錄）
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta

# 添加專案根目錄到路徑
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from data_module.config import TWStockConfig
from app_module.broker_branch_update_service import BrokerBranchUpdateService

# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

def test_10_days():
    """測試下載10天的記錄"""
    logger.info("=" * 60)
    logger.info("開始測試：下載10天券商分點資料")
    logger.info("=" * 60)
    
    service = None
    try:
        # 初始化配置
        logger.info("初始化配置...")
        config = TWStockConfig()
        
        # 創建服務
        logger.info("創建服務...")
        service = BrokerBranchUpdateService(config)
        
        # 計算日期範圍（最近10個交易日）
        logger.info("計算日期範圍...")
        end_date = datetime.now()
        start_date = end_date - timedelta(days=20)  # 往前推20天以確保有10個交易日
        
        # 調整到最近的交易日
        while start_date.weekday() >= 5:  # 跳過週末
            start_date -= timedelta(days=1)
        
        start_date_str = start_date.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')
        
        logger.info(f"日期範圍: {start_date_str} 至 {end_date_str}")
        logger.info("開始執行更新（這可能需要一些時間，請耐心等待）...")
        
        # 進度回調
        def progress_callback(message: str, progress: int):
            logger.info(f"[進度 {progress}%] {message}")
        
        # 先測試一個分點，避免卡住太久
        logger.info("先測試單一分點（永豐竹北）...")
        test_branch = ['9A00_9A9P']  # 永豐竹北
        
        result = service.update_broker_branch_data(
            start_date=start_date_str,
            end_date=end_date_str,
            branch_system_keys=test_branch,  # 先測試一個分點
            delay_seconds=4.0,  # 適當的延遲時間
            force_all=False,  # 不強制重新抓取
            progress_callback=progress_callback
        )
        
        logger.info("單一分點測試完成")
        
        # 如果單一分點成功，再測試全部
        if result.get('success', False) and len(result.get('updated_dates', [])) > 0:
            logger.info("單一分點測試成功，繼續測試全部分點...")
            result = service.update_broker_branch_data(
                start_date=start_date_str,
                end_date=end_date_str,
                branch_system_keys=None,  # 全部
                delay_seconds=4.0,
                force_all=False,
                progress_callback=progress_callback
            )
        else:
            logger.warning("單一分點測試未完全成功，但繼續顯示結果...")
        
        logger.info("=" * 60)
        logger.info("更新結果:")
        logger.info(f"  成功: {result.get('success', False)}")
        logger.info(f"  訊息: {result.get('message', 'N/A')}")
        logger.info(f"  成功更新的分點: {result.get('updated_branches', [])}")
        logger.info(f"  失敗的分點: {result.get('failed_branches', [])}")
        logger.info(f"  成功更新的日期數: {len(result.get('updated_dates', []))}")
        logger.info(f"  失敗的日期數: {len(result.get('failed_dates', []))}")
        logger.info(f"  跳過的日期數: {len(result.get('skipped_dates', []))}")
        logger.info(f"  總處理數: {result.get('total_processed', 0)}")
        logger.info(f"  總記錄數: {result.get('total_records', 0)}")
        logger.info("=" * 60)
        
        # 檢查結果
        if result.get('success', False):
            total_dates = len(result.get('updated_dates', [])) + len(result.get('failed_dates', []))
            if total_dates >= 10:
                logger.info("✅ 測試通過：成功下載至少10天的記錄")
            else:
                logger.warning(f"⚠️ 警告：只下載了 {total_dates} 天的記錄（預期至少10天）")
        else:
            logger.error("❌ 測試失敗：更新未成功")
            if result.get('failed_dates'):
                logger.error(f"失敗的日期: {result.get('failed_dates', [])}")
        
        return result
        
    except KeyboardInterrupt:
        logger.warning("用戶中斷測試")
        return None
    except Exception as e:
        logger.error(f"❌ 測試過程中發生錯誤: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None
    
    finally:
        # 清理 driver
        if service:
            try:
                logger.info("正在清理 driver...")
                service._cleanup_driver()
                logger.info("Driver 已清理")
            except Exception as e:
                logger.warning(f"清理 driver 時發生錯誤: {str(e)}")

if __name__ == "__main__":
    test_10_days()

