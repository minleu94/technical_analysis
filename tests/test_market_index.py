import pandas as pd
import yfinance as yf
import finmind
from finmind.data import Data
from datetime import datetime, timedelta
import logging

# 載入環境變數（從 .env 檔案）
try:
    from dotenv import load_dotenv
    load_dotenv()  # 載入 .env 檔案中的環境變數
except ImportError:
    # 如果沒有安裝 python-dotenv，只從系統環境變數讀取
    pass

# 設定 FinMind API token（從環境變數讀取）
import os
FINMIND_TOKEN = os.environ.get('FINMIND_TOKEN', '')  # 請在 .env 檔案中設定 FINMIND_TOKEN
if not FINMIND_TOKEN:
    import pytest
    pytest.skip("需要設定環境變數 FINMIND_TOKEN 才能執行此測試", allow_module_level=True)

# 設定日誌
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 設定日期範圍（最近 45 天）
end_date = datetime.today()
start_date = end_date - timedelta(days=45)
start_date_str = start_date.strftime('%Y-%m-%d')
end_date_str = end_date.strftime('%Y-%m-%d')
logger.info(f"日期範圍: {start_date_str} 至 {end_date_str}")

def get_market_index_yfinance():
    """使用 yfinance 抓取大盤指數數據"""
    try:
        df = yf.download('^TWII', start=start_date_str, end=end_date_str, progress=False)
        if not df.empty:
            logger.info("成功從 yfinance 獲取數據")
            return df
        else:
            logger.warning("yfinance 返回空數據")
            return None
    except Exception as e:
        logger.error(f"從 yfinance 獲取數據失敗: {str(e)}")
        return None

def get_market_index_finmind():
    """使用 FinMind 抓取大盤指數數據"""
    try:
        finmind.login(FINMIND_TOKEN)
        finmind_data = Data()
        df = finmind_data.taiwan_stock_index_daily(
            stock_id="TAIEX",
            start_date=start_date_str,
            end_date=end_date_str
        )
        if not df.empty:
            logger.info("成功從 FinMind 獲取數據")
            return df
        else:
            logger.warning("FinMind 返回空數據")
            return None
    except Exception as e:
        logger.error(f"從 FinMind 獲取數據失敗: {str(e)}")
        return None

# 先試 yfinance，失敗就換 finmind
df = get_market_index_yfinance()
if df is None:
    logger.info("yfinance 失敗，嘗試使用 FinMind...")
    df = get_market_index_finmind()

if df is not None:
    print("成功獲取大盤指數數據：")
    print(df.head())
else:
    print("無法從任何資料源獲取大盤指數數據") 