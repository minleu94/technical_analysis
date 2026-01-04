"""
券商分點資料更新服務
負責從 MoneyDJ 抓取券商分點每日買賣資料
"""

import logging
import re
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Callable

import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

try:
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError:
    ChromeDriverManager = None


class BrokerBranchUpdateService:
    """券商分點資料更新服務"""
    
    def __init__(self, config):
        """
        初始化服務
        
        Args:
            config: TWStockConfig 實例
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # 確保目錄存在
        self.config.broker_flow_dir.mkdir(parents=True, exist_ok=True)
        self.config.meta_data_dir.mkdir(parents=True, exist_ok=True)
        
        # Selenium driver（共用，避免重複創建）
        self._driver = None
    
    def _get_chrome_options(self):
        """設置 Chrome 選項"""
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-software-rasterizer')
        options.add_argument('--disable-features=VizDisplayCompositor')
        options.add_argument('--disable-features=NetworkService')
        # 增加穩定性選項
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--disable-infobars')
        options.add_argument('--disable-logging')
        options.add_argument('--log-level=3')  # 只顯示嚴重錯誤
        options.add_argument('--window-size=1920,1080')
        # 增加記憶體和穩定性選項
        options.add_argument('--disable-background-timer-throttling')
        options.add_argument('--disable-backgrounding-occluded-windows')
        options.add_argument('--disable-renderer-backgrounding')
        options.add_argument('--disable-features=TranslateUI')
        options.add_argument('--disable-ipc-flooding-protection')
        # 設置頁面載入策略為 eager（更快，減少崩潰風險）
        options.page_load_strategy = 'eager'
        options.add_experimental_option('excludeSwitches', ['enable-logging', 'enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)
        # 增加穩定性：禁用一些可能導致崩潰的功能
        prefs = {
            'profile.default_content_setting_values': {
                'notifications': 2
            },
            'profile.managed_default_content_settings': {
                'images': 2  # 禁用圖片載入以減少記憶體使用
            }
        }
        options.add_experimental_option('prefs', prefs)
        return options
    
    def _create_driver(self):
        """創建新的 WebDriver 實例"""
        try:
            service = Service()
            options = self._get_chrome_options()
            driver = webdriver.Chrome(service=service, options=options)
            self.logger.info("Selenium driver 已創建")
            return driver
        except Exception as e:
            self.logger.warning(f"創建 driver 時發生錯誤: {str(e)}")
            if ChromeDriverManager:
                try:
                    driver_manager = ChromeDriverManager()
                    driver_path = driver_manager.install()
                    service = Service(executable_path=driver_path)
                    driver = webdriver.Chrome(service=service, options=options)
                    self.logger.info("使用 ChromeDriverManager 創建 driver")
                    return driver
                except Exception as backup_error:
                    self.logger.error(f"備用方法也失敗: {str(backup_error)}")
                    raise
            else:
                raise
    
    def _is_driver_alive(self, driver):
        """檢查 driver 是否還活著"""
        if driver is None:
            return False
        try:
            # 嘗試獲取當前 URL 來檢查 driver 狀態
            _ = driver.current_url
            # 嘗試執行一個簡單的命令
            _ = driver.service.process
            return True
        except Exception:
            return False
    
    def _recreate_driver(self):
        """重新創建 driver（當 driver 崩潰時）"""
        if self._driver:
            try:
                self._driver.quit()
            except Exception as e:
                self.logger.warning(f"關閉舊 driver 時發生錯誤: {str(e)}")
        self._driver = None
        self._driver = self._create_driver()
        self.logger.info("Driver 已重新創建")
    
    @contextmanager
    def _get_driver(self):
        """創建和管理 WebDriver 實例（共用，含自動恢復）"""
        if self._driver is None:
            self._driver = self._create_driver()
        
        # 檢查 driver 是否還活著
        if not self._is_driver_alive(self._driver):
            self.logger.warning("檢測到 driver 已崩潰，嘗試重新創建...")
            self._recreate_driver()
        
        try:
            yield self._driver
        except Exception as e:
            error_msg = str(e)
            # 檢查是否為 driver 崩潰相關錯誤
            if any(keyword in error_msg.lower() for keyword in ['session', 'chrome', 'driver', 'crash', 'disconnected']):
                self.logger.warning(f"Driver 可能已崩潰: {error_msg}，嘗試重新創建...")
                try:
                    self._recreate_driver()
                    # 重新創建後，再次 yield（但這可能不會自動重試，需要調用方處理）
                    yield self._driver
                except Exception as retry_error:
                    self.logger.error(f"重新創建 driver 失敗: {str(retry_error)}")
                    raise
            else:
                raise
    
    def _cleanup_driver(self):
        """清理 driver（任務結束時調用）"""
        if self._driver:
            try:
                self._driver.quit()
                self._driver = None
                self.logger.info("Selenium driver 已關閉")
            except Exception as e:
                self.logger.warning(f"關閉 driver 時發生錯誤: {str(e)}")
    
    def _detect_mojibake(self, text: str) -> bool:
        """
        檢測文字是否包含 mojibake（亂碼）
        
        Args:
            text: 要檢測的文字
            
        Returns:
            是否包含 mojibake
        """
        if not text or not isinstance(text, str):
            return False
        
        # 常見的 mojibake 特徵字符
        mojibake_chars = ['æ', 'Ã', 'â€', 'â€™', 'â€œ', 'â€', 'Ã©', 'Ã¨']
        return any(char in text for char in mojibake_chars)
    
    def _fix_mojibake(self, text: str) -> Optional[str]:
        """
        嘗試修復 mojibake（亂碼）
        
        Args:
            text: 包含 mojibake 的文字
            
        Returns:
            修復後的文字，如果修復失敗則返回 None
        """
        if not text or not isinstance(text, str):
            return None
        
        try:
            # 嘗試：latin1 -> utf-8 解碼
            fixed = text.encode('latin1').decode('utf-8')
            # 檢查修復後是否還有 mojibake
            if not self._detect_mojibake(fixed):
                return fixed
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        
        return None
    
    def _load_branch_registry(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """
        從 registry 載入追蹤分點清單（含自動修復 mojibake）
        
        Args:
            active_only: 是否只載入啟用的分點
            
        Returns:
            分點資訊列表
        """
        registry_file = self.config.broker_branch_registry_file
        
        if not registry_file.exists():
            self.logger.error(f"Registry 檔案不存在: {registry_file}")
            return []
        
        try:
            # 讀取 CSV 時，確保 url_param_b 保持為字串（避免前導零被移除）
            dtype_dict = {
                'url_param_a': str,
                'url_param_b': str,  # 強制為字串，保留前導零
                'branch_system_key': str,
                'branch_broker_code': str,
                'branch_code': str,
                'branch_display_name': str
            }
            df = pd.read_csv(registry_file, encoding='utf-8-sig', dtype=dtype_dict)
            
            # 確保 url_param_b 是字串格式（修復可能的數字轉換問題）
            if 'url_param_b' in df.columns:
                df['url_param_b'] = df['url_param_b'].astype(str)
                # 如果值被轉換為數字（例如 39004100390050），嘗試修復為正確格式
                for idx, row in df.iterrows():
                    url_param_b = str(row.get('url_param_b', ''))
                    branch_key = row.get('branch_system_key', '')
                    # 檢查是否需要補前導零
                    if branch_key == '9A00_9A9P' and url_param_b == '39004100390050':
                        df.at[idx, 'url_param_b'] = '0039004100390050'
                        self.logger.warning(f"修復 {branch_key} 的 url_param_b: 39004100390050 -> 0039004100390050")
                    elif branch_key == '8450_845B' and len(url_param_b) < 16:
                        # 檢查康和永和的 url_param_b
                        expected = '0038003400350042'
                        if url_param_b != expected:
                            df.at[idx, 'url_param_b'] = expected
                            self.logger.warning(f"修復 {branch_key} 的 url_param_b: {url_param_b} -> {expected}")
            
            # 檢查並修復 mojibake
            needs_fix = False
            if 'branch_display_name' in df.columns:
                for idx, row in df.iterrows():
                    display_name = row.get('branch_display_name', '')
                    if display_name and self._detect_mojibake(display_name):
                        fixed = self._fix_mojibake(display_name)
                        if fixed:
                            self.logger.warning(
                                f"檢測到 mojibake 並修復: {display_name} -> {fixed}"
                            )
                            df.at[idx, 'branch_display_name'] = fixed
                            needs_fix = True
                        else:
                            self.logger.warning(
                                f"無法修復 mojibake: {display_name}"
                            )
            
            # 如果有修復，寫回檔案
            if needs_fix or any(df['url_param_b'].astype(str).str.len() < 16):
                self.logger.info("自動修復後寫回 registry 檔案")
                # 備份原檔案
                try:
                    self.config.create_backup(registry_file)
                except Exception as backup_error:
                    self.logger.warning(f"備份失敗，繼續執行: {str(backup_error)}")
                # 寫回（使用 utf-8-sig，確保 url_param_b 為字串）
                df.to_csv(registry_file, index=False, encoding='utf-8-sig')
            
            if active_only:
                df = df[df.get('is_active', True) == True]
            
            branches = df.to_dict('records')
            # 確保所有 url_param_b 都是字串
            for branch in branches:
                if 'url_param_b' in branch:
                    branch['url_param_b'] = str(branch['url_param_b'])
            
            self.logger.info(f"載入 {len(branches)} 個追蹤分點")
            return branches
            
        except Exception as e:
            self.logger.error(f"載入 registry 時發生錯誤: {str(e)}")
            return []
    
    def _build_branch_url(self, branch_info: Dict[str, Any], start_date: str, end_date: str) -> str:
        """
        構建分點資料 URL
        
        Args:
            branch_info: 分點資訊（從 registry 載入）
            start_date: 開始日期（YYYY-MM-DD）
            end_date: 結束日期（YYYY-MM-DD）
            
        Returns:
            URL 字串
        """
        url_param_a = str(branch_info.get('url_param_a', ''))
        url_param_b = str(branch_info.get('url_param_b', ''))
        
        # 確保 url_param_b 格式正確（保留前導零）
        if not url_param_b:
            self.logger.error(f"url_param_b 為空: {branch_info.get('branch_system_key', 'UNKNOWN')}")
            raise ValueError(f"url_param_b 為空: {branch_info.get('branch_system_key', 'UNKNOWN')}")
        
        # 使用 c=B 參數（參考 Crawler.ipynb）
        # 日期範圍：e=開始日期，f=結束日期
        url = (
            f"https://5850web.moneydj.com/z/zg/zgb/zgb0.djhtm"
            f"?a={url_param_a}&b={url_param_b}&c=B&e={start_date}&f={end_date}"
        )
        
        # 記錄 URL 以便調試
        self.logger.debug(f"構建 URL: {url}")
        
        return url
    
    def _parse_counterparty_broker_name(self, text: str) -> Tuple[str, str]:
        """
        解析表格內的「對手券商」名稱
        
        支援的格式：
        1. 標準券商格式：開頭數字/字母數字組合 + 中文名稱（例如："1234元大證券"）
        2. ETF 名稱：純中文或中文+數字（例如："元大台灣50"、"元大高股息"、"富邦科技"）
        3. 特殊格式：股票代號+特殊標識（例如："6643M31"、"7722LINEPAY"）
        4. 純中文：可能是股票名稱（例如："台積電"）
        
        Args:
            text: 原始券商名稱
            
        Returns:
            (counterparty_broker_code, counterparty_broker_name)
        """
        if not text or not isinstance(text, str):
            return ('UNKNOWN', text or '')
        
        text = text.strip()
        if not text:
            return ('UNKNOWN', '')
        
        # 1. 嘗試標準券商格式：開頭的數字或字母數字組合 + 剩餘的中文名稱
        # 例如："1234元大證券"、"9A00永豐證券"
        match = re.match(r'^([\dA-Z]+)([^\dA-Z]+.*)$', text)
        if match:
            code = match.group(1).strip()
            name = match.group(2).strip()
            # 驗證：code 應該至少 2 個字符，name 應該包含中文
            if len(code) >= 2 and any('\u4e00' <= c <= '\u9fff' for c in name):
                return (code, name)
        
        # 2. 檢查是否為 ETF 名稱（常見 ETF 關鍵詞）
        etf_keywords = ['元大', '富邦', '國泰', '中信', '台新', '永豐', '第一', '兆豐', 
                       '台灣50', '高股息', '科技', '金融', '中小', '電子', '傳產', 'ETF']
        if any(keyword in text for keyword in etf_keywords):
            # ETF 使用特殊代碼 'ETF'，名稱保留原樣
            return ('ETF', text)
        
        # 3. 嘗試特殊格式：股票代號+特殊標識（例如："6643M31"、"7722LINEPAY"）
        # 格式：4位數字 + 字母數字組合
        match = re.match(r'^(\d{4})([A-Z0-9]+)$', text)
        if match:
            stock_code = match.group(1)  # 股票代號（4位數字）
            suffix = match.group(2)      # 特殊標識
            # 使用股票代號作為 code，完整名稱作為 name
            return (stock_code, text)
        
        # 4. 檢查是否為純中文（可能是股票名稱）
        if re.match(r'^[\u4e00-\u9fff]+$', text):
            # 純中文可能是股票名稱，使用 'STOCK' 作為代碼
            return ('STOCK', text)
        
        # 5. 嘗試提取開頭的數字部分（可能是股票代號）
        # 例如："6643" 開頭可能是股票代號
        match = re.match(r'^(\d{4,6})', text)
        if match:
            potential_code = match.group(1)
            # 如果後面還有內容，可能是股票代號+名稱
            remaining = text[len(potential_code):].strip()
            if remaining:
                return (potential_code, text)
            else:
                # 只有數字，可能是股票代號
                return (potential_code, text)
        
        # 6. 如果都無法解析，記錄警告並返回 UNKNOWN
        self.logger.debug(f"無法解析對手券商名稱: {text}（已嘗試所有模式）")
        return ('UNKNOWN', text)
    
    def update_broker_branch_data(
        self,
        start_date: str,
        end_date: str,
        branch_system_keys: Optional[List[str]] = None,
        delay_seconds: float = 4.0,
        force_all: bool = False,
        progress_callback: Optional[Callable[[str, int], None]] = None
    ) -> Dict[str, Any]:
        """
        更新券商分點每日買賣資料
        
        Args:
            start_date: 開始日期（YYYY-MM-DD）
            end_date: 結束日期（YYYY-MM-DD）
            branch_system_keys: 要更新的分點列表（None=全部）
            delay_seconds: 請求間隔（秒）
            force_all: 是否強制重新抓取（忽略已存在檔案）
            progress_callback: 進度回調函數 (message: str, progress: int) -> None
            
        Returns:
            更新結果字典
        """
        try:
            # 載入分點 registry
            all_branches = self._load_branch_registry(active_only=True)
            
            if not all_branches:
                return {
                    'success': False,
                    'message': '沒有可用的追蹤分點',
                    'updated_dates': [],
                    'failed_dates': [],
                    'skipped_dates': [],
                    'updated_branches': [],
                    'failed_branches': [],
                    'total_processed': 0,
                    'total_records': 0
                }
            
            # 過濾分點
            if branch_system_keys:
                branches = [b for b in all_branches if b['branch_system_key'] in branch_system_keys]
            else:
                branches = all_branches
            
            if not branches:
                return {
                    'success': False,
                    'message': f'指定的分點不存在: {branch_system_keys}',
                    'updated_dates': [],
                    'failed_dates': [],
                    'skipped_dates': [],
                    'updated_branches': [],
                    'failed_branches': [],
                    'total_processed': 0,
                    'total_records': 0
                }
            
            self.logger.info(f"開始更新 {len(branches)} 個分點的資料: {start_date} 至 {end_date}")
            
            # 生成日期列表（排除週末）
            start = datetime.strptime(start_date, '%Y-%m-%d')
            end = datetime.strptime(end_date, '%Y-%m-%d')
            dates = []
            current = start
            while current <= end:
                if current.weekday() < 5:  # 週一到週五
                    dates.append(current.strftime('%Y-%m-%d'))
                current += timedelta(days=1)
            
            # 初始化結果統計
            updated_dates = []
            failed_dates = []
            skipped_dates = []
            updated_branches = []
            failed_branches = []
            total_records = 0
            
            total_tasks = len(branches) * len(dates)
            completed_tasks = 0
            
            # 使用共用的 driver
            with self._get_driver() as driver:
                # 對每個分點
                for branch_idx, branch_info in enumerate(branches):
                    branch_key = branch_info['branch_system_key']
                    branch_name = branch_info['branch_display_name']
                    
                    if progress_callback:
                        progress_callback(
                            f"處理分點 {branch_name} ({branch_idx+1}/{len(branches)})...",
                            int((completed_tasks / total_tasks) * 100)
                        )
                    
                    # 確保分點目錄存在
                    branch_dir = self.config.broker_flow_dir / branch_key
                    daily_dir = branch_dir / 'daily'
                    daily_dir.mkdir(parents=True, exist_ok=True)
                    
                    branch_success = True
                    branch_records = 0
                    
                    # 對每個日期
                    for date_idx, date_str in enumerate(dates):
                        completed_tasks += 1
                        
                        if progress_callback:
                            progress_callback(
                                f"處理 {branch_name} - {date_str} ({completed_tasks}/{total_tasks})...",
                                int((completed_tasks / total_tasks) * 100)
                            )
                        
                        # 檢查檔案是否已存在
                        daily_file = daily_dir / f"{date_str}.csv"
                        if daily_file.exists() and not force_all:
                            skipped_dates.append(date_str)
                            self.logger.debug(f"跳過已存在檔案: {branch_key}/{date_str}")
                            continue
                        
                        # 重試機制
                        max_retries = 3
                        retry_count = 0
                        success = False
                        tables = None
                        
                        while retry_count < max_retries and not success:
                            try:
                                # 每次重試前都檢查 driver 是否還活著
                                if not self._is_driver_alive(driver):
                                    self.logger.warning(f"Driver 已崩潰，重新創建... (重試 {retry_count + 1}/{max_retries})")
                                    try:
                                        self._recreate_driver()
                                        driver = self._driver  # 更新引用
                                        time.sleep(2)  # 等待 driver 完全初始化
                                    except Exception as recreate_error:
                                        self.logger.error(f"重新創建 driver 失敗: {str(recreate_error)}")
                                        retry_count = max_retries
                                        break
                                
                                # 構建 URL（參考 Crawler.ipynb 和用戶範例）
                                # 要抓取某一天的資料，需要設置日期範圍為前一天到當天
                                # 例如：抓 2025-12-29 的資料，設置 e=2025-12-28&f=2025-12-29
                                date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                                prev_date = (date_obj - timedelta(days=1)).strftime('%Y-%m-%d')
                                url = self._build_branch_url(branch_info, prev_date, date_str)
                                
                                # 抓取資料（設置超時時間）
                                try:
                                    # 設置頁面載入超時（45秒）
                                    driver.set_page_load_timeout(45)
                                    # 設置腳本執行超時（30秒）
                                    driver.set_script_timeout(30)
                                except Exception as timeout_set_error:
                                    self.logger.warning(f"設置超時時間失敗: {str(timeout_set_error)}")
                                    # 繼續嘗試，使用默認超時
                                
                                self.logger.info(f"正在訪問 URL: {url} (重試 {retry_count + 1}/{max_retries})")
                                
                                # 使用 try-except 包裹 get，避免卡住
                                try:
                                    # 記錄開始時間
                                    import time as time_module
                                    start_time = time_module.time()
                                    driver.get(url)
                                    elapsed = time_module.time() - start_time
                                    self.logger.debug(f"頁面載入完成，耗時 {elapsed:.2f} 秒")
                                except Exception as get_error:
                                    error_str = str(get_error)
                                    error_type = type(get_error).__name__
                                    # 如果是超時錯誤，記錄並重新創建 driver
                                    if 'timeout' in error_str.lower() or 'TimeoutException' in error_type:
                                        self.logger.warning(f"頁面載入超時: {error_str[:200]}")
                                        # 嘗試停止頁面載入
                                        try:
                                            driver.execute_script("window.stop();")
                                        except:
                                            pass
                                        raise  # 讓外層處理
                                    else:
                                        self.logger.warning(f"頁面載入錯誤: {error_type}: {error_str[:200]}")
                                        raise  # 其他錯誤也拋出
                                
                                # 等待表格載入（使用更靈活的方式）
                                self.logger.debug(f"等待頁面載入...")
                                
                                # 先等待頁面基本載入（檢查 body 標籤）
                                try:
                                    wait_body = WebDriverWait(driver, 15)
                                    wait_body.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                                    self.logger.debug(f"頁面 body 已載入")
                                except Exception as body_error:
                                    self.logger.warning(f"等待 body 載入超時: {str(body_error)[:100]}")
                                
                                # 額外等待一下，讓 JavaScript 執行
                                time.sleep(2)
                                
                                # 檢查頁面內容
                                try:
                                    page_source = driver.page_source
                                    if not page_source or len(page_source) < 500:
                                        raise Exception("頁面內容過少，可能未正確載入")
                                    
                                    # 獲取頁面標題和 URL 用於診斷
                                    page_title = driver.title if hasattr(driver, 'title') else 'N/A'
                                    current_url = driver.current_url if hasattr(driver, 'current_url') else url
                                    
                                    # 更精確的錯誤檢測：檢查常見的錯誤頁面特徵
                                    has_real_error = False
                                    error_details = []
                                    
                                    # 檢查頁面標題是否包含錯誤關鍵詞
                                    if page_title and any(keyword in page_title.lower() for keyword in ['error', '404', 'not found', '錯誤', '找不到']):
                                        has_real_error = True
                                        error_details.append(f"頁面標題包含錯誤關鍵詞: {page_title}")
                                    
                                    # 檢查頁面內容中是否有明顯的錯誤訊息（排除正常內容）
                                    # 檢查常見的錯誤頁面模式
                                    error_patterns = [
                                        r'404\s+not\s+found',
                                        r'page\s+not\s+found',
                                        r'找不到.*頁面',
                                        r'系統錯誤',
                                        r'伺服器錯誤',
                                        r'server\s+error',
                                        r'access\s+denied',
                                        r'拒絕存取',
                                    ]
                                    
                                    page_lower = page_source.lower()
                                    for pattern in error_patterns:
                                        if re.search(pattern, page_lower, re.IGNORECASE):
                                            has_real_error = True
                                            error_details.append(f"頁面內容匹配錯誤模式: {pattern}")
                                            break
                                    
                                    # 檢查頁面是否過短（可能是錯誤頁面）
                                    if len(page_source) < 2000:
                                        # 如果頁面很短且包含錯誤關鍵詞，可能是錯誤頁面
                                        if any(keyword in page_lower for keyword in ['error', '404', '錯誤', 'not found']):
                                            has_real_error = True
                                            error_details.append("頁面內容過短且包含錯誤關鍵詞")
                                    
                                    # 如果檢測到真實錯誤，記錄詳細信息
                                    if has_real_error:
                                        self.logger.warning(
                                            f"檢測到頁面錯誤: {branch_key}/{date_str}\n"
                                            f"  URL: {current_url}\n"
                                            f"  標題: {page_title}\n"
                                            f"  錯誤詳情: {', '.join(error_details)}\n"
                                            f"  頁面長度: {len(page_source)} 字符"
                                        )
                                    else:
                                        # 如果只是包含 "error" 等關鍵詞但沒有明顯錯誤，只記錄 debug
                                        if 'error' in page_lower or '錯誤' in page_source:
                                            self.logger.debug(
                                                f"頁面包含 'error' 關鍵詞但未檢測到真實錯誤: {branch_key}/{date_str} "
                                                f"(可能是正常內容，如 'error handling')"
                                            )
                                    
                                    # 嘗試等待表格（但不要因為沒有表格就失敗）
                                    try:
                                        wait_table = WebDriverWait(driver, 10)
                                        wait_table.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
                                        self.logger.debug(f"表格已載入: {branch_key}/{date_str}")
                                    except Exception:
                                        # 如果沒有表格，記錄警告但繼續
                                        self.logger.warning(f"頁面已載入但未找到表格，嘗試直接解析: {branch_key}/{date_str}")
                                        
                                except Exception as check_error:
                                    raise Exception(f"無法獲取頁面內容: {str(check_error)}")
                                
                                # 額外等待一下確保頁面完全載入（減少到1秒）
                                time.sleep(1)
                                
                                html = driver.page_source
                                soup = BeautifulSoup(html, 'html.parser')
                                tables = soup.find_all('table')
                                
                                if len(tables) < 15:
                                    self.logger.warning(f"找不到足夠的表格: {branch_key}/{date_str} (表格數: {len(tables)})")
                                    if retry_count < max_retries - 1:
                                        retry_count += 1
                                        time.sleep(delay_seconds * 2)  # 重試時延遲更長
                                        continue
                                    else:
                                        failed_dates.append(date_str)
                                        branch_success = False
                                        time.sleep(delay_seconds)
                                        break
                                
                                success = True
                                
                            except Exception as fetch_error:
                                error_msg = str(fetch_error)
                                error_type = type(fetch_error).__name__
                                
                                # 檢查是否為 driver 相關錯誤（擴展關鍵字列表）
                                is_driver_error = (
                                    any(keyword in error_msg.lower() for keyword in [
                                        'session', 'chrome', 'driver', 'crash', 'disconnected', 
                                        'timeout', 'stacktrace', 'symbols not available', 
                                        'unresolved backtrace', 'webdriver', 'selenium',
                                        'timeoutexception', 'page load', 'navigation timeout'
                                    ]) or
                                    'Message:' in error_msg or
                                    'Stacktrace:' in error_msg or
                                    error_type in ['WebDriverException', 'SessionNotCreatedException', 
                                                   'TimeoutException', 'InvalidSessionIdException',
                                                   'Timeout', 'WebDriverException']
                                )
                                
                                # TimeoutException 特別處理：可能是頁面載入超時或 driver 崩潰
                                if error_type == 'TimeoutException':
                                    is_driver_error = True
                                    self.logger.warning("檢測到 TimeoutException，將重新創建 driver")
                                
                                self.logger.warning(
                                    f"抓取 {branch_key}/{date_str} 時發生錯誤 (重試 {retry_count + 1}/{max_retries}): {error_type}: {error_msg[:200]}"
                                )
                                
                                # 如果是 driver 錯誤，強制檢查並重新創建
                                if is_driver_error:
                                    if retry_count < max_retries - 1:
                                        retry_count += 1
                                        try:
                                            # 強制檢查 driver 狀態
                                            if not self._is_driver_alive(driver):
                                                self.logger.warning("Driver 已確認崩潰，重新創建...")
                                            else:
                                                self.logger.warning("檢測到 driver 錯誤，預防性重新創建...")
                                            
                                            self._recreate_driver()
                                            driver = self._driver  # 更新引用
                                            # 重試前等待更長時間
                                            time.sleep(delay_seconds * 3)
                                        except Exception as recreate_error:
                                            self.logger.error(f"重新創建 driver 失敗: {str(recreate_error)}")
                                            retry_count = max_retries  # 強制退出重試
                                    else:
                                        retry_count += 1
                                else:
                                    # 非 driver 錯誤，直接重試
                                    if retry_count < max_retries - 1:
                                        retry_count += 1
                                        time.sleep(delay_seconds * 2)
                                    else:
                                        retry_count += 1
                        
                        if not success or tables is None:
                            self.logger.error(f"處理 {branch_key}/{date_str} 失敗，已重試 {max_retries} 次")
                            failed_dates.append(date_str)
                            branch_success = False
                            time.sleep(delay_seconds)
                            continue
                        
                        try:
                            # 處理買超資料（表格索引 13）
                            buy_table = tables[13]
                            buy_rows = buy_table.find_all('tr')[2:]
                            buy_data = []
                            
                            for row in buy_rows:
                                cols = row.find_all('td')
                                if len(cols) == 4:
                                    counterparty_name = cols[0].get_text(strip=True)
                                    buy_qty_str = cols[1].get_text(strip=True).replace(',', '')
                                    sell_qty_str = cols[2].get_text(strip=True).replace(',', '')
                                    net_qty_str = cols[3].get_text(strip=True).replace(',', '')
                                    
                                    # 解析對手券商
                                    counterparty_code, counterparty_name_parsed = self._parse_counterparty_broker_name(counterparty_name)
                                    
                                    # 轉換數值（優先 int，失敗才 float）
                                    try:
                                        buy_qty = int(buy_qty_str) if buy_qty_str else 0
                                    except ValueError:
                                        try:
                                            buy_qty = float(buy_qty_str) if buy_qty_str else 0.0
                                            self.logger.warning(f"buy_qty 轉換為 float: {buy_qty_str}")
                                        except:
                                            buy_qty = 0
                                            self.logger.warning(f"buy_qty 轉換失敗: {buy_qty_str}")
                                    
                                    try:
                                        sell_qty = int(sell_qty_str) if sell_qty_str else 0
                                    except ValueError:
                                        try:
                                            sell_qty = float(sell_qty_str) if sell_qty_str else 0.0
                                            self.logger.warning(f"sell_qty 轉換為 float: {sell_qty_str}")
                                        except:
                                            sell_qty = 0
                                            self.logger.warning(f"sell_qty 轉換失敗: {sell_qty_str}")
                                    
                                    try:
                                        net_qty = int(net_qty_str) if net_qty_str else 0
                                    except ValueError:
                                        try:
                                            net_qty = float(net_qty_str) if net_qty_str else 0.0
                                            self.logger.warning(f"net_qty 轉換為 float: {net_qty_str}")
                                        except:
                                            net_qty = 0
                                            self.logger.warning(f"net_qty 轉換失敗: {net_qty_str}")
                                    
                                    buy_data.append({
                                        'date': date_str,
                                        'trade_type': '買超',
                                        'branch_system_key': branch_key,
                                        'branch_broker_code': branch_info['branch_broker_code'],
                                        'branch_code': branch_info['branch_code'],
                                        'branch_display_name': branch_name,
                                        'counterparty_broker_code': counterparty_code,
                                        'counterparty_broker_name': counterparty_name_parsed,
                                        'buy_qty': buy_qty,
                                        'sell_qty': sell_qty,
                                        'net_qty': net_qty
                                    })
                            
                            # 處理賣超資料（表格索引 14）
                            sell_table = tables[14]
                            sell_rows = sell_table.find_all('tr')[2:]
                            sell_data = []
                            
                            for row in sell_rows:
                                cols = row.find_all('td')
                                if len(cols) == 4:
                                    counterparty_name = cols[0].get_text(strip=True)
                                    buy_qty_str = cols[1].get_text(strip=True).replace(',', '')
                                    sell_qty_str = cols[2].get_text(strip=True).replace(',', '')
                                    net_qty_str = cols[3].get_text(strip=True).replace(',', '')
                                    
                                    # 解析對手券商
                                    counterparty_code, counterparty_name_parsed = self._parse_counterparty_broker_name(counterparty_name)
                                    
                                    # 轉換數值
                                    try:
                                        buy_qty = int(buy_qty_str) if buy_qty_str else 0
                                    except ValueError:
                                        try:
                                            buy_qty = float(buy_qty_str) if buy_qty_str else 0.0
                                            self.logger.warning(f"buy_qty 轉換為 float: {buy_qty_str}")
                                        except:
                                            buy_qty = 0
                                    
                                    try:
                                        sell_qty = int(sell_qty_str) if sell_qty_str else 0
                                    except ValueError:
                                        try:
                                            sell_qty = float(sell_qty_str) if sell_qty_str else 0.0
                                            self.logger.warning(f"sell_qty 轉換為 float: {sell_qty_str}")
                                        except:
                                            sell_qty = 0
                                    
                                    try:
                                        net_qty = int(net_qty_str) if net_qty_str else 0
                                    except ValueError:
                                        try:
                                            net_qty = float(net_qty_str) if net_qty_str else 0.0
                                            self.logger.warning(f"net_qty 轉換為 float: {net_qty_str}")
                                        except:
                                            net_qty = 0
                                    
                                    sell_data.append({
                                        'date': date_str,
                                        'trade_type': '賣超',
                                        'branch_system_key': branch_key,
                                        'branch_broker_code': branch_info['branch_broker_code'],
                                        'branch_code': branch_info['branch_code'],
                                        'branch_display_name': branch_name,
                                        'counterparty_broker_code': counterparty_code,
                                        'counterparty_broker_name': counterparty_name_parsed,
                                        'buy_qty': buy_qty,
                                        'sell_qty': sell_qty,
                                        'net_qty': net_qty
                                    })
                            
                            # 合併買超和賣超資料
                            all_data = buy_data + sell_data
                            
                            if all_data:
                                # 保存到 CSV
                                df = pd.DataFrame(all_data)
                                df.to_csv(daily_file, index=False, encoding='utf-8-sig')
                                
                                updated_dates.append(date_str)
                                branch_records += len(all_data)
                                total_records += len(all_data)
                                
                                self.logger.info(
                                    f"成功更新: {branch_key}/{date_str}, "
                                    f"記錄數: {len(all_data)}"
                                )
                            else:
                                self.logger.warning(f"日期 {date_str} 沒有交易數據: {branch_key}")
                                failed_dates.append(date_str)
                                branch_success = False
                            
                            # 延遲
                            time.sleep(delay_seconds)
                            
                        except Exception as e:
                            self.logger.error(f"處理 {branch_key}/{date_str} 時發生錯誤: {str(e)}")
                            failed_dates.append(date_str)
                            branch_success = False
                            time.sleep(delay_seconds)
                    
                    # 記錄分點處理結果
                    if branch_success and branch_records > 0:
                        updated_branches.append(branch_key)
                    elif not branch_success:
                        failed_branches.append(branch_key)
            
            # 清理 driver
            self._cleanup_driver()
            
            # 生成結果訊息
            message = (
                f"更新完成：成功 {len(updated_branches)} 個分點，失敗 {len(failed_branches)} 個分點；"
                f"成功 {len(updated_dates)} 個日期，失敗 {len(failed_dates)} 個日期，"
                f"跳過 {len(skipped_dates)} 個日期；總記錄數: {total_records}"
            )
            
            if progress_callback:
                progress_callback("更新完成", 100)
            
            return {
                'success': True,
                'message': message,
                'updated_dates': list(set(updated_dates)),
                'failed_dates': list(set(failed_dates)),
                'skipped_dates': list(set(skipped_dates)),
                'updated_branches': updated_branches,
                'failed_branches': failed_branches,
                'total_processed': len(dates),
                'total_records': total_records
            }
            
        except Exception as e:
            self.logger.error(f"更新過程中發生錯誤: {str(e)}", exc_info=True)
            self._cleanup_driver()
            return {
                'success': False,
                'message': f"更新失敗: {str(e)}",
                'updated_dates': [],
                'failed_dates': [],
                'skipped_dates': [],
                'updated_branches': [],
                'failed_branches': [],
                'total_processed': 0,
                'total_records': 0
            }
    
    def merge_broker_branch_data(
        self,
        branch_system_keys: Optional[List[str]] = None,
        force_all: bool = False,
        progress_callback: Optional[Callable[[str, int], None]] = None
    ) -> Dict[str, Any]:
        """
        合併每日原始資料到整合元數據檔案
        
        Args:
            branch_system_keys: 要合併的分點列表（None=全部）
            force_all: 是否強制重新合併（忽略現有元數據）
            progress_callback: 進度回調函數
            
        Returns:
            合併結果字典
        """
        try:
            # 載入分點 registry
            all_branches = self._load_branch_registry(active_only=True)
            
            if not all_branches:
                return {
                    'success': False,
                    'message': '沒有可用的追蹤分點',
                    'merged_branches': [],
                    'merged_files': 0,
                    'new_records': 0,
                    'total_records': 0,
                    'date_range': {'start_date': '', 'end_date': ''},
                    'duplicate_records': 0
                }
            
            # 過濾分點
            if branch_system_keys:
                branches = [b for b in all_branches if b['branch_system_key'] in branch_system_keys]
            else:
                branches = all_branches
            
            if not branches:
                return {
                    'success': False,
                    'message': f'指定的分點不存在: {branch_system_keys}',
                    'merged_branches': [],
                    'merged_files': 0,
                    'new_records': 0,
                    'total_records': 0,
                    'date_range': {'start_date': '', 'end_date': ''},
                    'duplicate_records': 0
                }
            
            self.logger.info(f"開始合併 {len(branches)} 個分點的資料")
            
            merged_branches = []
            merged_files = 0
            new_records = 0
            total_records = 0
            all_dates = set()
            
            # 對每個分點
            for branch_idx, branch_info in enumerate(branches):
                branch_key = branch_info['branch_system_key']
                branch_name = branch_info['branch_display_name']
                
                if progress_callback:
                    progress_callback(
                        f"合併分點 {branch_name} ({branch_idx+1}/{len(branches)})...",
                        int((branch_idx / len(branches)) * 100)
                    )
                
                branch_dir = self.config.broker_flow_dir / branch_key
                daily_dir = branch_dir / 'daily'
                meta_dir = branch_dir / 'meta'
                meta_dir.mkdir(parents=True, exist_ok=True)
                
                merged_file = meta_dir / 'merged.csv'
                
                # 讀取現有合併檔案（如果存在）
                existing_dates = set()
                existing_df = None
                
                if merged_file.exists() and not force_all:
                    try:
                        existing_df = pd.read_csv(merged_file, encoding='utf-8-sig')
                        if 'date' in existing_df.columns:
                            existing_dates = set(existing_df['date'].unique())
                        self.logger.info(f"讀取現有合併檔案: {branch_key}, 已有 {len(existing_dates)} 個日期")
                    except Exception as e:
                        self.logger.warning(f"讀取現有合併檔案失敗: {branch_key}, {str(e)}")
                        existing_df = None
                
                # 讀取每日檔案
                daily_files = sorted(daily_dir.glob('*.csv'))
                
                if not daily_files:
                    self.logger.warning(f"沒有每日檔案: {branch_key}")
                    continue
                
                new_data_list = []
                
                for daily_file in daily_files:
                    # 從檔名提取日期
                    date_str = daily_file.stem  # YYYY-MM-DD
                    
                    if date_str in existing_dates and not force_all:
                        continue
                    
                    try:
                        df = pd.read_csv(daily_file, encoding='utf-8-sig')
                        
                        # 驗證必要欄位
                        required_cols = [
                            'date', 'trade_type', 'branch_system_key',
                            'branch_broker_code', 'branch_code', 'branch_display_name',
                            'counterparty_broker_code', 'counterparty_broker_name',
                            'buy_qty', 'sell_qty', 'net_qty'
                        ]
                        
                        missing_cols = [col for col in required_cols if col not in df.columns]
                        if missing_cols:
                            self.logger.warning(
                                f"檔案缺少欄位: {branch_key}/{date_str}, "
                                f"缺少: {missing_cols}"
                            )
                            continue
                        
                        new_data_list.append(df)
                        all_dates.add(date_str)
                        merged_files += 1
                        
                    except Exception as e:
                        self.logger.warning(f"讀取每日檔案失敗: {branch_key}/{date_str}, {str(e)}")
                        continue
                
                if not new_data_list:
                    self.logger.info(f"沒有新資料需要合併: {branch_key}")
                    if existing_df is not None and len(existing_df) > 0:
                        merged_branches.append(branch_key)
                        total_records += len(existing_df)
                    continue
                
                # 合併新資料
                new_df = pd.concat(new_data_list, ignore_index=True)
                new_records += len(new_df)
                
                # 合併新舊資料
                if existing_df is not None and len(existing_df) > 0:
                    final_df = pd.concat([existing_df, new_df], ignore_index=True)
                else:
                    final_df = new_df
                
                # 去重（基於 date + trade_type + counterparty_broker_code）
                before_dedup = len(final_df)
                final_df = final_df.drop_duplicates(
                    subset=['date', 'trade_type', 'counterparty_broker_code'],
                    keep='last'
                )
                after_dedup = len(final_df)
                duplicate_count = before_dedup - after_dedup
                
                # 排序
                final_df = final_df.sort_values(['date', 'trade_type', 'counterparty_broker_code'])
                
                # 備份現有檔案
                if merged_file.exists():
                    self.config.create_backup(merged_file)
                
                # 保存
                final_df.to_csv(merged_file, index=False, encoding='utf-8-sig')
                
                merged_branches.append(branch_key)
                total_records += len(final_df)
                
                self.logger.info(
                    f"合併完成: {branch_key}, "
                    f"新增記錄: {len(new_df)}, "
                    f"總記錄: {len(final_df)}, "
                    f"去重: {duplicate_count}"
                )
            
            # 計算日期範圍
            if all_dates:
                sorted_dates = sorted(all_dates)
                date_range = {
                    'start_date': sorted_dates[0],
                    'end_date': sorted_dates[-1]
                }
            else:
                date_range = {'start_date': '', 'end_date': ''}
            
            # 構建訊息（包含日期範圍）
            if date_range.get('start_date') and date_range.get('end_date'):
                message = (
                    f"合併完成：成功 {len(merged_branches)} 個分點，"
                    f"合併 {merged_files} 個檔案，"
                    f"新增 {new_records} 筆記錄，"
                    f"總記錄 {total_records:,} 筆\n"
                    f"日期範圍：{date_range['start_date']} 至 {date_range['end_date']}"
                )
            else:
                message = (
                    f"合併完成：成功 {len(merged_branches)} 個分點，"
                    f"合併 {merged_files} 個檔案，"
                    f"新增 {new_records} 筆記錄，"
                    f"總記錄 {total_records:,} 筆"
                )
            
            if progress_callback:
                progress_callback("合併完成", 100)
            
            return {
                'success': True,
                'message': message,
                'merged_branches': merged_branches,
                'merged_files': merged_files,
                'new_records': new_records,
                'total_records': total_records,
                'date_range': date_range,
                'duplicate_records': 0  # 已在各分點內去重
            }
            
        except Exception as e:
            self.logger.error(f"合併過程中發生錯誤: {str(e)}", exc_info=True)
            return {
                'success': False,
                'message': f"合併失敗: {str(e)}",
                'merged_branches': [],
                'merged_files': 0,
                'new_records': 0,
                'total_records': 0,
                'date_range': {'start_date': '', 'end_date': ''},
                'duplicate_records': 0
            }
    
    def check_broker_branch_data_status(
        self,
        branch_system_keys: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        檢查券商分點資料狀態
        
        Args:
            branch_system_keys: 要檢查的分點列表（None=全部）
            
        Returns:
            狀態字典
        """
        try:
            # 載入分點 registry
            all_branches = self._load_branch_registry(active_only=True)
            
            if not all_branches:
                return {
                    'latest_date': None,
                    'total_records': 0,
                    'date_count': 0,
                    'broker_count': 0,
                    'date_range': {'start_date': None, 'end_date': None},
                    'status': 'empty'
                }
            
            # 過濾分點
            if branch_system_keys:
                branches = [b for b in all_branches if b['branch_system_key'] in branch_system_keys]
            else:
                branches = all_branches
            
            all_dates = set()
            total_records = 0
            
            for branch_info in branches:
                branch_key = branch_info['branch_system_key']
                branch_dir = self.config.broker_flow_dir / branch_key
                meta_dir = branch_dir / 'meta'
                merged_file = meta_dir / 'merged.csv'
                
                # 優先檢查合併後的檔案（merged.csv）
                if merged_file.exists():
                    try:
                        df = pd.read_csv(merged_file, encoding='utf-8-sig')
                        if 'date' in df.columns:
                            dates = set(df['date'].unique())
                            all_dates.update(dates)
                            total_records += len(df)
                            self.logger.debug(f"從合併檔案讀取: {branch_key}, 日期數: {len(dates)}, 記錄數: {len(df)}")
                    except Exception as e:
                        self.logger.warning(f"讀取合併檔案失敗: {branch_key}, {str(e)}")
                        # 如果合併檔案讀取失敗，降級到檢查 daily 目錄
                        daily_dir = branch_dir / 'daily'
                        daily_files = list(daily_dir.glob('*.csv'))
                        for daily_file in daily_files:
                            try:
                                df = pd.read_csv(daily_file, encoding='utf-8-sig')
                                if 'date' in df.columns:
                                    dates = set(df['date'].unique())
                                    all_dates.update(dates)
                                    total_records += len(df)
                            except:
                                continue
                else:
                    # 如果沒有合併檔案，檢查 daily 目錄
                    daily_dir = branch_dir / 'daily'
                    daily_files = list(daily_dir.glob('*.csv'))
                    for daily_file in daily_files:
                        try:
                            df = pd.read_csv(daily_file, encoding='utf-8-sig')
                            if 'date' in df.columns:
                                dates = set(df['date'].unique())
                                all_dates.update(dates)
                                total_records += len(df)
                        except:
                            continue
            
            if all_dates:
                sorted_dates = sorted(all_dates)
                latest_date = sorted_dates[-1]
                date_range = {
                    'start_date': sorted_dates[0],
                    'end_date': sorted_dates[-1]
                }
                status = 'ok'
            else:
                latest_date = None
                date_range = {'start_date': None, 'end_date': None}
                status = 'empty'
            
            return {
                'latest_date': latest_date,
                'total_records': total_records,
                'date_count': len(all_dates),
                'broker_count': len(branches),
                'date_range': date_range,
                'status': status
            }
            
        except Exception as e:
            self.logger.error(f"檢查狀態時發生錯誤: {str(e)}", exc_info=True)
            return {
                'latest_date': None,
                'total_records': 0,
                'date_count': 0,
                'broker_count': 0,
                'date_range': {'start_date': None, 'end_date': None},
                'status': 'error'
            }

