"""
券商分點資料更新服務
負責從 MoneyDJ 抓取券商分點每日買賣資料
"""

import logging
import re
import requests
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Callable, Set

import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

try:
    from webdriver_manager.chrome import ChromeDriverManager as _ChromeDriverManager
except ImportError:
    _ChromeDriverManager = None  # type: ignore[assignment,misc]

ChromeDriverManager: Any = _ChromeDriverManager


class BrokerBranchUpdateService:
    """券商分點資料更新服務"""

    DUAL_METRIC_COLUMNS = {
        "buy_lots",
        "sell_lots",
        "net_lots",
        "buy_amount_k_twd",
        "sell_amount_k_twd",
        "net_amount_k_twd",
    }
    MONEYDJ_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/149.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.google.com/",
    }

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

    def _decode_unicode_hex(self, hex_str: str) -> str:
        """
        將 16 進位 Unicode hex 字串轉換成一般字串。
        例如 '0039004100390069' -> '9A9i'

        若長度小於 16 (如 14 或 15 碼) 且皆為十六進位，會自動補足前置零至 16 碼再進行解密。
        """
        if not hex_str or not isinstance(hex_str, str):
            return hex_str

        # 預防性補前導零
        val = hex_str.strip()
        if 12 <= len(val) < 16 and all(c in '0123456789abcdefABCDEF' for c in val):
            val = val.zfill(16)

        if len(val) == 16 and all(c in '0123456789abcdefABCDEF' for c in val):
            try:
                chars = []
                for i in range(0, len(val), 4):
                    code = int(val[i:i+4], 16)
                    chars.append(chr(code))
                return "".join(chars)
            except Exception as e:
                self.logger.debug(f"解密 Unicode hex 失敗: {hex_str}, error: {str(e)}")
        return hex_str

    def _load_branch_registry(
        self,
        active_only: bool = True,
        repair_registry: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        從 registry 載入追蹤分點清單（含自動修復 mojibake、長碼解密與總公司判定）

        Args:
            active_only: 是否只載入啟用的分點
            repair_registry: 是否允許自動修復並寫回 registry；狀態檢查必須保持唯讀

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

            # 確保 url_param_b 是字串格式，並處理長碼解密
            if 'url_param_b' in df.columns:
                df['url_param_b'] = df['url_param_b'].astype(str)
                for idx, row in df.iterrows():
                    url_param_b = str(row.get('url_param_b', ''))
                    # 預防性補足可能丟失的前導零
                    if 12 <= len(url_param_b) < 16 and all(c in '0123456789abcdefABCDEF' for c in url_param_b):
                        url_param_b = url_param_b.zfill(16)
                        df.at[idx, 'url_param_b'] = url_param_b

                    # 對長碼 Unicode hex 進行解密，並將短碼更新至 branch_code 欄位
                    decoded_code = self._decode_unicode_hex(url_param_b)
                    if decoded_code != url_param_b:
                        df.at[idx, 'branch_code'] = decoded_code

            # 檢查並修復 mojibake
            needs_fix = False
            if 'branch_display_name' in df.columns:
                for idx, row in df.iterrows():
                    display_name = row.get('branch_display_name', '')
                    if display_name and self._detect_mojibake(display_name):
                        fixed = self._fix_mojibake(display_name)
                        if fixed:
                            if repair_registry:
                                df.at[idx, 'branch_display_name'] = fixed
                                needs_fix = True
                                self.logger.warning(
                                    f"檢測到 mojibake 並修復: {display_name} -> {fixed}"
                                )
                            else:
                                self.logger.warning(
                                    f"檢測到 mojibake 可修復但本次為唯讀載入: {display_name} -> {fixed}"
                                )
                        else:
                            self.logger.warning(
                                    f"無法修復 mojibake: {display_name}"
                            )

            # 如果有修復，寫回檔案
            if repair_registry and needs_fix:
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
            # 確保所有 url_param_b 都是字串，並注入 is_headquarters 判定與解密 branch_code
            for branch in branches:
                if 'url_param_b' in branch:
                    branch['url_param_b'] = str(branch['url_param_b'])

                # 計算是否為總公司
                broker_code = str(branch.get('branch_broker_code', ''))
                branch_code = str(branch.get('branch_code', ''))
                display_name = str(branch.get('branch_display_name', ''))

                is_head = False
                if broker_code == branch_code:
                    is_head = True
                elif '-' not in display_name and '分公司' not in display_name and '分行' not in display_name:
                    headquarters_keywords = ["證券", "環球", "瑞銀", "麥格理", "野村", "匯豐", "高盛", "摩根士丹利", "摩根大通", "土銀", "大和國泰", "美林", "康和", "凱基"]
                    if any(k in display_name for k in headquarters_keywords):
                        is_head = True

                branch['is_headquarters'] = is_head

            self.logger.info(f"載入 {len(branches)} 個追蹤分點")
            return branches

        except Exception as e:
            self.logger.error(f"載入 registry 時發生錯誤: {str(e)}")
            return []

    def _build_branch_url(
        self,
        branch_info: Dict[str, Any],
        start_date: str,
        end_date: str,
        metric: str = "lots",
    ) -> str:
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

        metric_codes = {
            "lots": "E",
            "amount": "B",
        }
        if metric not in metric_codes:
            raise ValueError(f"不支援的 MoneyDJ 指標: {metric}")

        metric_code = metric_codes[metric]
        # 日期範圍：e=開始日期，f=結束日期
        url = (
            f"https://5850web.moneydj.com/z/zg/zgb/zgb0.djhtm"
            f"?a={url_param_a}&b={url_param_b}&c={metric_code}&e={start_date}&f={end_date}"
        )

        # 記錄 URL 以便調試
        self.logger.debug(f"構建 URL: {url}")

        return url

    def _merge_metric_records(
        self,
        lot_records: List[Dict[str, Any]],
        amount_records: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """依日期、方向與股票代碼合併張數及仟元資料。"""
        merged: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}

        # 1. 處理 lot_records (E-only)
        for record in lot_records:
            key = (
                str(record.get("date", "")),
                str(record.get("trade_type", "")),
                str(record.get("branch_system_key", "")),
                str(record.get("counterparty_broker_code", "")),
            )
            if key not in merged:
                merged[key] = {
                    "date": record.get("date"),
                    "trade_type": record.get("trade_type"),
                    "branch_system_key": record.get("branch_system_key"),
                    "branch_broker_code": record.get("branch_broker_code"),
                    "branch_code": record.get("branch_code"),
                    "branch_display_name": record.get("branch_display_name"),
                    "counterparty_broker_code": record.get("counterparty_broker_code"),
                    "counterparty_broker_name": record.get("counterparty_broker_name"),
                    "buy_lots": record.get("buy_lots"),
                    "sell_lots": record.get("sell_lots"),
                    "net_lots": record.get("net_lots"),
                    "buy_amount_k_twd": None,
                    "sell_amount_k_twd": None,
                    "net_amount_k_twd": None,
                    "lots_observed": True,
                    "amount_observed": False,
                    "lots_rank": record.get("metric_rank"),
                    "amount_rank": None
                }

        # 2. 處理 amount_records (B-only / E-B intersection)
        for record in amount_records:
            key = (
                str(record.get("date", "")),
                str(record.get("trade_type", "")),
                str(record.get("branch_system_key", "")),
                str(record.get("counterparty_broker_code", "")),
            )
            if key not in merged:
                # B-only
                merged[key] = {
                    "date": record.get("date"),
                    "trade_type": record.get("trade_type"),
                    "branch_system_key": record.get("branch_system_key"),
                    "branch_broker_code": record.get("branch_broker_code"),
                    "branch_code": record.get("branch_code"),
                    "branch_display_name": record.get("branch_display_name"),
                    "counterparty_broker_code": record.get("counterparty_broker_code"),
                    "counterparty_broker_name": record.get("counterparty_broker_name"),
                    "buy_lots": None,
                    "sell_lots": None,
                    "net_lots": None,
                    "buy_amount_k_twd": record.get("buy_amount_k_twd"),
                    "sell_amount_k_twd": record.get("sell_amount_k_twd"),
                    "net_amount_k_twd": record.get("net_amount_k_twd"),
                    "lots_observed": False,
                    "amount_observed": True,
                    "lots_rank": None,
                    "amount_rank": record.get("metric_rank")
                }
            else:
                # E/B 交集
                merged[key]["buy_amount_k_twd"] = record.get("buy_amount_k_twd")
                merged[key]["sell_amount_k_twd"] = record.get("sell_amount_k_twd")
                merged[key]["net_amount_k_twd"] = record.get("net_amount_k_twd")
                merged[key]["amount_observed"] = True
                merged[key]["amount_rank"] = record.get("metric_rank")

        return list(merged.values())

    @staticmethod
    def _infer_metric_ranks(df: pd.DataFrame) -> pd.DataFrame:
        """由榜單方向與淨值補齊舊 daily CSV 缺少的 E/B rank。"""
        required = {'date', 'trade_type', 'branch_system_key'}
        if df.empty or not required.issubset(df.columns):
            return df

        result = df.copy()
        metric_specs = (
            ('lots_observed', 'lots_rank', 'net_lots'),
            ('amount_observed', 'amount_rank', 'net_amount_k_twd'),
        )
        group_cols = ['date', 'trade_type', 'branch_system_key']

        for observed_col, rank_col, value_col in metric_specs:
            if observed_col not in result.columns or value_col not in result.columns:
                continue
            if rank_col not in result.columns:
                result[rank_col] = pd.Series([None] * len(result), dtype='Int64')

            observed_mask = result[observed_col].fillna(False).astype(bool)
            missing_rank_mask = pd.to_numeric(result[rank_col], errors='coerce').isna()
            eligible = result[observed_mask & missing_rank_mask & result[value_col].notna()]

            for group_key, group in eligible.groupby(group_cols, dropna=False, sort=False):
                trade_type = str(group_key[1])
                if trade_type not in {'買超', '賣超'}:
                    continue
                ordered_indexes = group.sort_values(
                    value_col,
                    ascending=trade_type == '賣超',
                    kind='stable',
                ).index
                for rank, index in enumerate(ordered_indexes, start=1):
                    result.at[index, rank_col] = rank

            result[rank_col] = pd.to_numeric(result[rank_col], errors='coerce').astype('Int64')

        return result

    def _csv_has_dual_metrics(self, csv_path: Path) -> bool:
        """判斷既有 CSV 是否已具備 E/B 雙指標欄位。"""
        try:
            columns = set(pd.read_csv(csv_path, nrows=0, encoding="utf-8-sig").columns)
        except Exception:
            return False
        return self.DUAL_METRIC_COLUMNS.issubset(columns)

    def _parse_metric_tables(
        self,
        tables: List[Any],
        branch_info: Dict[str, Any],
        date_str: str,
        metric: str,
    ) -> List[Dict[str, Any]]:
        """從 MoneyDJ 頁面辨識買超、賣超表格並轉成明確單位欄位。"""
        header_keyword = {
            "lots": "買進張數",
            "amount": "買進金額",
        }.get(metric)
        value_fields = {
            "lots": ("buy_lots", "sell_lots", "net_lots"),
            "amount": ("buy_amount_k_twd", "sell_amount_k_twd", "net_amount_k_twd"),
        }.get(metric)
        if header_keyword is None or value_fields is None:
            raise ValueError(f"不支援的 MoneyDJ 指標: {metric}")

        def direct_rows(table: Any) -> List[Any]:
            rows = table.find_all("tr", recursive=False)
            if rows:
                return rows
            tbody = table.find("tbody", recursive=False)
            return tbody.find_all("tr", recursive=False) if tbody is not None else []

        data_tables = [
            table
            for table in tables
            if header_keyword in table.get_text(" ", strip=True)
            and len(direct_rows(table)) >= 2
        ]
        records: List[Dict[str, Any]] = []
        for table in data_tables:
            table_text = table.get_text(" ", strip=True)
            trade_type = "賣超" if table_text.startswith("賣超") else "買超"
            rank_counter = 0
            for row in direct_rows(table):
                cols = row.find_all("td")
                if len(cols) != 4:
                    continue

                values: List[int] = []
                for col in cols[1:4]:
                    raw_value = col.get_text(strip=True).replace(",", "")
                    try:
                        values.append(int(raw_value) if raw_value else 0)
                    except ValueError:
                        values = []
                        break
                if len(values) != 3:
                    continue
                rank_counter += 1

                # 優先檢查 Script 標籤中的 GenLink2stk (以獲取真實的股票/ETF 代碼)
                script_text = " ".join(
                    script.get_text(" ", strip=True)
                    for script in cols[0].find_all("script")
                )
                script_match = re.search(
                    r"GenLink2stk\('(?:AS)?([^']+)','([^']+)'\)",
                    script_text,
                )
                if script_match:
                    counterparty_code = script_match.group(1).strip()
                    counterparty_name = script_match.group(2).strip()
                else:
                    counterparty_text = cols[0].get_text(strip=True)
                    counterparty_code, counterparty_name = self._parse_counterparty_broker_name(
                        counterparty_text
                    )
                if counterparty_code == "UNKNOWN":
                    continue

                record = {
                    "date": date_str,
                    "trade_type": trade_type,
                    "branch_system_key": branch_info["branch_system_key"],
                    "branch_broker_code": branch_info["branch_broker_code"],
                    "branch_code": branch_info["branch_code"],
                    "branch_display_name": branch_info["branch_display_name"],
                    "counterparty_broker_code": counterparty_code,
                    "counterparty_broker_name": counterparty_name,
                    "metric_source": metric,
                    "metric_rank": rank_counter,
                }
                record.update(dict(zip(value_fields, values)))
                records.append(record)

        return records

    def _fetch_metric_records(
        self,
        driver: Any,
        branch_info: Dict[str, Any],
        date_str: str,
        metric: str,
        retries: int = 3,
    ) -> List[Dict[str, Any]]:
        """抓取單一 MoneyDJ 指標頁；供同日 E/B 雙頁下載使用。"""
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        prev_date = (date_obj - timedelta(days=1)).strftime("%Y-%m-%d")
        url = self._build_branch_url(branch_info, prev_date, date_str, metric=metric)
        last_error: Optional[Exception] = None

        for attempt in range(retries):
            try:
                driver.get(url)
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.TAG_NAME, "table"))
                )
                soup = BeautifulSoup(driver.page_source, "html.parser")
                records = self._parse_metric_tables(
                    soup.find_all("table"),
                    branch_info,
                    date_str,
                    metric,
                )
                if records:
                    return records
                raise ValueError(f"MoneyDJ {metric} 頁面未解析到交易資料")
            except Exception as exc:
                last_error = exc
                self.logger.warning(
                    "抓取 %s/%s 指標 %s 失敗 (%s/%s): %s",
                    branch_info.get("branch_system_key"),
                    date_str,
                    metric,
                    attempt + 1,
                    retries,
                    exc,
                )
                if attempt + 1 < retries:
                    time.sleep(2)

        raise RuntimeError(
            f"MoneyDJ {metric} 指標抓取失敗: "
            f"{branch_info.get('branch_system_key')}/{date_str}"
        ) from last_error

    def _fetch_metric_records_http(
        self,
        branch_info: Dict[str, Any],
        date_str: str,
        metric: str,
        retries: int = 3,
        timeout: int = 30,
    ) -> List[Dict[str, Any]]:
        """使用 HTTP 直接抓取 MoneyDJ 指標頁，避免 Selenium 額外等待。"""
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        prev_date = (date_obj - timedelta(days=1)).strftime("%Y-%m-%d")
        url = self._build_branch_url(branch_info, prev_date, date_str, metric=metric)
        last_error: Optional[Exception] = None

        for attempt in range(retries):
            try:
                response = requests.get(
                    url,
                    headers=self.MONEYDJ_HEADERS,
                    timeout=timeout,
                )
                response.raise_for_status()
                html = response.content.decode("big5", errors="replace")
                soup = BeautifulSoup(html, "html.parser")
                records = self._parse_metric_tables(
                    soup.find_all("table"),
                    branch_info,
                    date_str,
                    metric,
                )
                if records:
                    return records
                raise RuntimeError(f"MoneyDJ {metric} 頁面未解析到交易資料")
            except Exception as exc:
                last_error = exc
                self.logger.warning(
                    "HTTP 抓取 %s/%s 指標 %s 失敗 (%s/%s): %s",
                    branch_info.get("branch_system_key"),
                    date_str,
                    metric,
                    attempt + 1,
                    retries,
                    exc,
                )
                if attempt + 1 < retries:
                    time.sleep(2)

        raise RuntimeError(
            f"MoneyDJ {metric} HTTP 指標抓取失敗: "
            f"{branch_info.get('branch_system_key')}/{date_str}; {last_error}"
        ) from last_error

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

    def _filter_trade_dates_for_broker_update(
        self,
        dates: List[str],
    ) -> Tuple[List[str], List[str]]:
        """用每日股價日檔或 SQLite 行情證據過濾券商分點更新日期。"""
        if not dates:
            return [], []

        evidence_dates: Set[str] = set()
        evidence_available = False
        date_key_to_iso = {
            datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y%m%d"): date_str
            for date_str in dates
        }
        iso_dates = set(dates)

        for dir_attr in ("daily_price_dir", "tpex_daily_price_dir"):
            daily_dir = getattr(self.config, dir_attr, None)
            if not daily_dir or not Path(daily_dir).exists():
                continue
            daily_dir = Path(daily_dir)
            has_csv = any(daily_dir.glob("*.csv"))
            evidence_available = evidence_available or has_csv
            for date_key, iso_date in date_key_to_iso.items():
                if (
                    (daily_dir / f"{date_key}.csv").exists()
                    or (daily_dir / f"{iso_date}.csv").exists()
                ):
                    evidence_dates.add(iso_date)

        db_file = getattr(self.config, "db_file", None)
        if db_file and Path(db_file).exists():
            try:
                import sqlite3

                with sqlite3.connect(str(db_file)) as conn:
                    cursor = conn.cursor()
                    table_exists = cursor.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_prices'"
                    ).fetchone()
                    if table_exists:
                        has_rows = cursor.execute(
                            "SELECT 1 FROM daily_prices LIMIT 1"
                        ).fetchone()
                        evidence_available = evidence_available or has_rows is not None
                        lookup_values = list(date_key_to_iso.keys()) + dates
                        placeholders = ",".join("?" for _ in lookup_values)
                        rows = cursor.execute(
                            f"SELECT DISTINCT 日期 FROM daily_prices WHERE 日期 IN ({placeholders})",
                            lookup_values,
                        ).fetchall()
                        for (raw_date,) in rows:
                            value = str(raw_date).strip()
                            if value in date_key_to_iso:
                                evidence_dates.add(date_key_to_iso[value])
                            elif value in iso_dates:
                                evidence_dates.add(value)
            except Exception as exc:
                self.logger.warning("券商分點交易日 SQLite 預檢失敗，改用 CSV 證據: %s", exc)

        if not evidence_available:
            self.logger.info("找不到每日行情日曆證據，券商分點更新維持原日期範圍")
            return dates, []

        trade_dates = [date_str for date_str in dates if date_str in evidence_dates]
        non_trading_dates = [date_str for date_str in dates if date_str not in evidence_dates]
        if non_trading_dates:
            self.logger.info(
                "券商分點更新跳過無每日行情證據日期: %s",
                ", ".join(non_trading_dates),
            )
        return trade_dates, non_trading_dates

    def update_broker_branch_data(
        self,
        start_date: str,
        end_date: str,
        branch_system_keys: Optional[List[str]] = None,
        delay_seconds: float = 0.5,
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
            all_branches = self._load_branch_registry(active_only=True, repair_registry=True)

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

            dates, non_trading_dates = self._filter_trade_dates_for_broker_update(dates)

            # 初始化結果統計
            updated_dates = []
            failed_dates = []
            skipped_dates = []
            updated_branches = []
            failed_branches = []
            total_records = 0

            total_tasks = len(branches) * len(dates)
            completed_tasks = 0

            if not dates:
                message = "券商分點更新完成：目標日期皆無交易日行情，已跳過 MoneyDJ 抓取"
                if progress_callback:
                    progress_callback(message, 100)
                return {
                    'success': True,
                    'message': message,
                    'updated_dates': [],
                    'failed_dates': [],
                    'skipped_dates': non_trading_dates,
                    'non_trading_dates': non_trading_dates,
                    'updated_branches': [],
                    'failed_branches': [],
                    'total_processed': 0,
                    'total_records': 0,
                }

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

                    # 檢查檔案是否已存在 (CSV)
                    daily_file = daily_dir / f"{date_str}.csv"
                    if (
                        daily_file.exists()
                        and not force_all
                        and self._csv_has_dual_metrics(daily_file)
                    ):
                        skipped_dates.append(date_str)
                        self.logger.debug(f"跳過已存在檔案(CSV): {branch_key}/{date_str}")
                        continue

                    # 檢查 SQLite 資料庫中是否已存在該日期與分點名稱的資料 (僅在 force_all=False 時)
                    use_sqlite = getattr(self.config, "use_sqlite", False)
                    db_file = getattr(self.config, "db_file", None)
                    if use_sqlite and db_file and db_file.exists() and not force_all:
                        try:
                            import sqlite3
                            sqlite_date = date_str.replace("-", "")

                            with sqlite3.connect(str(db_file)) as conn:
                                cursor = conn.cursor()
                                table_columns = {
                                    row[1]
                                    for row in cursor.execute(
                                        "PRAGMA table_info(broker_flows)"
                                    ).fetchall()
                                }
                                has_dual_schema = {
                                    "買進股數",
                                    "買進金額千元",
                                }.issubset(table_columns)
                                row = None
                                if has_dual_schema:
                                    branch_lookup_names = [
                                        str(branch_info.get('branch_display_name', '')).strip(),
                                        str(branch_key).strip(),
                                    ]
                                    branch_lookup_names = [
                                        name for name in dict.fromkeys(branch_lookup_names) if name
                                    ]
                                    cursor.execute(
                                        f"""
                                        SELECT 1
                                        FROM broker_flows
                                        WHERE 日期 = ?
                                          AND 分點名稱 IN ({",".join("?" for _ in branch_lookup_names)})
                                          AND 買進股數 IS NOT NULL
                                          AND 買進金額千元 IS NOT NULL
                                        LIMIT 1
                                        """,
                                        (sqlite_date, *branch_lookup_names),
                                    )
                                    row = cursor.fetchone()
                                if row is not None:
                                    skipped_dates.append(date_str)
                                    self.logger.debug(f"跳過已存在 SQLite 記錄: {branch_key}/{date_str}")
                                    continue
                        except Exception as sqlite_err:
                            self.logger.warning(f"檢查 SQLite 記錄失敗: {str(sqlite_err)}")

                    max_retries = 3

                    try:
                        try:
                            lot_data = self._fetch_metric_records_http(
                                branch_info,
                                date_str,
                                "lots",
                                retries=max_retries,
                            )
                            amount_data = self._fetch_metric_records_http(
                                branch_info,
                                date_str,
                                "amount",
                                retries=max_retries,
                            )
                        except Exception as http_error:
                            self.logger.warning(
                                "MoneyDJ HTTP fast path 失敗，改用 Selenium fallback: %s/%s: %s",
                                branch_key,
                                date_str,
                                http_error,
                            )
                            with self._get_driver() as driver:
                                lot_data = self._fetch_metric_records(
                                    driver,
                                    branch_info,
                                    date_str,
                                    "lots",
                                    retries=max_retries,
                                )
                                amount_data = self._fetch_metric_records(
                                    driver,
                                    branch_info,
                                    date_str,
                                    "amount",
                                    retries=max_retries,
                                )

                        if not lot_data or not amount_data:
                            raise ValueError("MoneyDJ E/B 雙指標資料不完整")

                        all_data = self._merge_metric_records(lot_data, amount_data)
                        if not all_data:
                            raise ValueError("MoneyDJ E/B 雙指標合併後無資料")

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

                        # 延遲
                        time.sleep(delay_seconds)

                    except Exception as e:
                        self.logger.error(f"處理 {branch_key}/{date_str} 時發生錯誤: {str(e)}")
                        failed_dates.append(date_str)
                        branch_success = False
                        time.sleep(delay_seconds)

                # 記錄分點處理結果
                if branch_success:
                    updated_branches.append(branch_key)
                else:
                    failed_branches.append(branch_key)

            # 清理 driver（只有 Selenium fallback 建立過時才會有作用）
            self._cleanup_driver()

            # 生成結果訊息
            message = (
                f"更新完成：成功 {len(updated_branches)} 個分點，失敗 {len(failed_branches)} 個分點；"
                f"成功 {len(updated_dates)} 個日期，失敗 {len(failed_dates)} 個日期，"
                f"跳過 {len(skipped_dates) + len(non_trading_dates)} 個日期"
                f"（無交易行情 {len(non_trading_dates)} 個）；總記錄數: {total_records}"
            )

            if progress_callback:
                progress_callback("更新完成", 100)

            return {
                'success': True,
                'message': message,
                'updated_dates': list(set(updated_dates)),
                'failed_dates': list(set(failed_dates)),
                'skipped_dates': list(set(skipped_dates + non_trading_dates)),
                'non_trading_dates': non_trading_dates,
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
            all_branches = self._load_branch_registry(active_only=True, repair_registry=True)

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
                        if (
                            'date' in existing_df.columns
                            and self.DUAL_METRIC_COLUMNS.issubset(existing_df.columns)
                        ):
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
                        rename_map = {
                            'buy_qty': 'buy_amount_k_twd',
                            'sell_qty': 'sell_amount_k_twd',
                            'net_qty': 'net_amount_k_twd',
                        }
                        df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
                        required_cols = [
                            'date', 'trade_type', 'branch_system_key',
                            'branch_broker_code', 'branch_code', 'branch_display_name',
                            'counterparty_broker_code', 'counterparty_broker_name',
                            'buy_lots', 'sell_lots', 'net_lots',
                            'buy_amount_k_twd', 'sell_amount_k_twd', 'net_amount_k_twd',
                            'lots_observed', 'amount_observed', 'lots_rank', 'amount_rank'
                        ]
                        for col in required_cols:
                            if col not in df.columns:
                                if col in ['buy_lots', 'sell_lots', 'net_lots', 'buy_amount_k_twd', 'sell_amount_k_twd', 'net_amount_k_twd']:
                                    df[col] = None
                                elif col == 'lots_observed':
                                    if 'buy_lots' in df.columns:
                                        df[col] = df['buy_lots'].notna()
                                    else:
                                        df[col] = False
                                elif col == 'amount_observed':
                                    if 'buy_amount_k_twd' in df.columns:
                                        df[col] = df['buy_amount_k_twd'].notna()
                                    else:
                                        df[col] = False
                                elif col in ['lots_rank', 'amount_rank']:
                                    df[col] = None
                                else:
                                    df[col] = ''
                        df = df[required_cols]

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
                final_df = self._infer_metric_ranks(final_df)
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
            all_branches = self._load_branch_registry(active_only=True, repair_registry=False)

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
                merged_dates = set()
                if merged_file.exists():
                    try:
                        df = pd.read_csv(merged_file, encoding='utf-8-sig')
                        if 'date' in df.columns:
                            merged_dates = set(df['date'].unique())
                            all_dates.update(merged_dates)
                            total_records += len(df)
                            self.logger.debug(f"從合併檔案讀取: {branch_key}, 日期數: {len(merged_dates)}, 記錄數: {len(df)}")
                    except Exception as e:
                        self.logger.warning(f"讀取合併檔案失敗: {branch_key}, {str(e)}")

                # 同時檢查 daily 目錄中尚未合併的檔案
                daily_dir = branch_dir / 'daily'
                if daily_dir.exists():
                    daily_files = list(daily_dir.glob('*.csv'))
                    for daily_file in daily_files:
                        date_str = daily_file.stem
                        # 如果這個日期已經在合併檔案中，就跳過
                        if date_str in merged_dates:
                            continue

                        import re
                        if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
                            all_dates.add(date_str)
                            try:
                                # 快速計算行數 (減去表頭) 作為記錄數
                                with open(daily_file, 'r', encoding='utf-8-sig') as f:
                                    lines = sum(1 for _ in f) - 1
                                if lines > 0:
                                    total_records += lines
                            except Exception:
                                pass

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

