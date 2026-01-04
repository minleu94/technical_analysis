#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
測試所有券商分點的一天資料抓取
參考 Crawler.ipynb 的邏輯
"""

import sys
import io
import logging
from pathlib import Path
from datetime import datetime, timedelta

# 設置 UTF-8 編碼以支持中文輸出（Windows）
if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except:
        pass  # 如果已經設置過，忽略錯誤

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

def test_all_branches_one_day():
    """測試所有分點的一天資料"""
    logger.info("=" * 80)
    logger.info("測試：下載所有券商分點的一天資料")
    logger.info("=" * 80)
    
    service = None
    try:
        # 初始化配置
        logger.info("初始化配置...")
        config = TWStockConfig()
        
        # 創建服務
        logger.info("創建服務...")
        service = BrokerBranchUpdateService(config)
        
        # 計算測試日期（最近一個交易日）
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)  # 往前推7天
        
        # 調整到最近的交易日
        while start_date.weekday() >= 5:  # 跳過週末
            start_date -= timedelta(days=1)
        
        # 只測試一個日期
        test_date = start_date.strftime('%Y-%m-%d')
        
        logger.info(f"測試日期: {test_date}")
        logger.info("開始執行更新（測試所有分點）...")
        
        # 進度回調
        def progress_callback(message: str, progress: int):
            logger.info(f"[進度 {progress}%] {message}")
        
        # 測試所有分點（強制重新抓取）
        result = service.update_broker_branch_data(
            start_date=test_date,
            end_date=test_date,
            branch_system_keys=None,  # 全部
            delay_seconds=4.0,
            force_all=True,  # 強制重新抓取，確保測試
            progress_callback=progress_callback
        )
        
        logger.info("=" * 80)
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
        logger.info("=" * 80)
        
        # 詳細檢查每個分點
        logger.info("\n各分點詳細結果:")
        for branch_key in result.get('updated_branches', []):
            logger.info(f"  ✅ {branch_key}: 成功")
        
        for branch_key in result.get('failed_branches', []):
            logger.error(f"  ❌ {branch_key}: 失敗")
        
        # 檢查結果
        total_branches = len(result.get('updated_branches', [])) + len(result.get('failed_branches', []))
        success_branches = len(result.get('updated_branches', []))
        
        if result.get('success', False) and success_branches == total_branches:
            logger.info(f"\n✅ 測試通過：所有 {success_branches} 個分點都成功下載資料")
        elif success_branches > 0:
            logger.warning(f"\n⚠️ 部分成功：{success_branches}/{total_branches} 個分點成功")
        else:
            logger.error("\n❌ 測試失敗：沒有分點成功下載資料")
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
    test_all_branches_one_day()

