import json
import time
import requests
import pandas as pd
import logging
from datetime import datetime, date, timezone
from typing import List, Dict, Any, Optional
import io
from decimal import Decimal, ROUND_HALF_UP

logger = logging.getLogger(__name__)

# User-Agent to prevent 403 Forbidden
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
}


def observed_only_availability_fields() -> Dict[str, Any]:
    """官方未提供 publication timestamp 時，只保存本次實際觀測時間。"""
    first_observed_at = datetime.now(timezone.utc).isoformat()
    return {
        "publication_at": None,
        "first_observed_at": first_observed_at,
        "available_at": first_observed_at,
        "available_date": None,
        "quality": "degraded",
    }

def to_roc_date(dt: date) -> str:
    """轉換為民國年格式: YYY/MM/DD"""
    return f"{dt.year - 1911}/{dt.month:02d}/{dt.day:02d}"

def safe_int(val) -> int:
    """安全轉換字串為整數，處理逗號與空值，不依賴 float。"""
    if pd.isna(val) or val is None or val == '':
        return 0
    if isinstance(val, str):
        val = val.replace(',', '').strip()
        if not val or val == 'X':
            return 0
        try:
            return int(Decimal(val).to_integral_value())
        except Exception:
            return 0
    try:
        return int(Decimal(str(val)).to_integral_value())
    except Exception:
        return 0

def safe_request(
    url: str,
    params: Optional[Dict] = None,
    *,
    timeout_seconds: int = 10,
    max_attempts: int = 3,
) -> requests.Response:
    """帶可明確限定逾時與重試次數的安全請求。"""
    if timeout_seconds <= 0 or max_attempts <= 0:
        raise ValueError("timeout_seconds and max_attempts must be positive")
    for attempt in range(max_attempts):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=timeout_seconds)
            if resp.status_code == 200:
                return resp
            message = "正在重試..." if attempt + 1 < max_attempts else "不再重試。"
            logger.warning(f"請求失敗: {url}, 狀態碼: {resp.status_code}, {message}")
        except requests.RequestException as e:
            message = "正在重試..." if attempt + 1 < max_attempts else "不再重試。"
            logger.warning(f"請求例外: {url}, 錯誤: {e}, {message}")
        if attempt + 1 < max_attempts:
            time.sleep(3)
    raise RuntimeError(f"無法取得資料: {url}")


_SECURITY_CODE_FIELD_NAMES = frozenset({"代號", "證券代號", "股票代號"})


def _validate_response_date(payload: Dict[str, Any], expected_date: str) -> None:
    """拒絕交易所回傳其他日期，避免 fallback 成為未來／錯日資料。"""

    response_date = str(payload.get("date", "")).strip().replace("/", "").replace("-", "")
    if response_date and response_date != expected_date:
        raise ValueError(
            f"官方回應日期不符：expected={expected_date}, actual={response_date}"
        )


def _security_table_rows(
    payload: Dict[str, Any],
    *,
    minimum_columns: int,
) -> list[list[Any]]:
    """同時支援舊版 ``aaData`` 與現行 ``tables[].data`` shape。"""

    legacy_rows = payload.get("aaData")
    if isinstance(legacy_rows, list) and legacy_rows:
        return [row for row in legacy_rows if isinstance(row, list)]

    for table in payload.get("tables", []):
        if not isinstance(table, dict):
            continue
        fields = table.get("fields", [])
        rows = table.get("data", [])
        if not isinstance(fields, list) or not isinstance(rows, list) or not rows:
            continue
        first_field = str(fields[0]).strip() if fields else ""
        if (
            len(fields) >= minimum_columns
            and first_field in _SECURITY_CODE_FIELD_NAMES
        ):
            return [row for row in rows if isinstance(row, list)]
    return []

# ==========================================
# 三大法人 (Institutional Flows)
# ==========================================
def fetch_institutional_flows(decision_date: date) -> pd.DataFrame:
    """抓取指定日期的三大法人買賣超 (上市 + 上櫃)"""
    date_ce = decision_date.strftime("%Y%m%d")
    date_roc = to_roc_date(decision_date)

    rows: list[dict[str, Any]] = []
    source_errors: list[str] = []

    # --- TWSE ---
    twse_url = "https://www.twse.com.tw/fund/T86"
    twse_params = {"response": "json", "date": date_ce, "selectType": "ALL"}
    logger.info(f"爬取 TWSE 法人: {twse_url}?date={date_ce}")
    try:
        resp = safe_request(twse_url, twse_params)
        data = resp.json()
        _validate_response_date(data, date_ce)
        if data.get("stat") != "OK" or not data.get("data") or not data.get("fields"):
            raise ValueError("TWSE T86 回應缺少有效 data/fields")
        availability = observed_only_availability_fields()
        fields = data["fields"]
        for row in data["data"]:
            if isinstance(row, list):
                item = dict(zip(fields, row))
                # 證交所欄位名稱可能變動，盡量包容
                fi_buy = safe_int(item.get("外陸資買進股數(不含外資自營商)", 0)) + safe_int(item.get("外資自營商買進股數", 0))
                fi_sell = safe_int(item.get("外陸資賣出股數(不含外資自營商)", 0)) + safe_int(item.get("外資自營商賣出股數", 0))
                fi_net = safe_int(item.get("外陸資買賣超股數(不含外資自營商)", 0)) + safe_int(item.get("外資自營商買賣超股數", 0))

                it_buy = safe_int(item.get("投信買進股數", 0))
                it_sell = safe_int(item.get("投信賣出股數", 0))
                it_net = safe_int(item.get("投信買賣超股數", 0))

                dl_buy = safe_int(item.get("自營商買進股數(自行買賣)", 0)) + safe_int(item.get("自營商買進股數(避險)", 0))
                dl_sell = safe_int(item.get("自營商賣出股數(自行買賣)", 0)) + safe_int(item.get("自營商賣出股數(避險)", 0))
                dl_net = safe_int(item.get("自營商買賣超股數(自行買賣)", 0)) + safe_int(item.get("自營商買賣超股數(避險)", 0))

                stock_code = str(item.get("證券代號") or "").strip()
                if not stock_code:
                    continue
                rows.append({
                    "stock_code": stock_code,
                    "decision_date": decision_date.isoformat(),
                    "source_version": "twse-official-T86",
                    **availability,
                    "foreign_investor_buy": fi_buy,
                    "foreign_investor_sell": fi_sell,
                    "foreign_investor_net": fi_net,
                    "investment_trust_buy": it_buy,
                    "investment_trust_sell": it_sell,
                    "investment_trust_net": it_net,
                    "dealer_buy": dl_buy,
                    "dealer_sell": dl_sell,
                    "dealer_net": dl_net,
                })
    except Exception as e:
        source_errors.append(f"TWSE T86: {type(e).__name__}: {e}")

    time.sleep(3) # 防 Ban

    # --- TPEX ---
    tpex_url = "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php"
    tpex_params = {"l": "zh-tw", "o": "json", "d": date_roc, "se": "AL"}
    logger.info(f"爬取 TPEX 法人: {tpex_url}?d={date_roc}")
    try:
        resp = safe_request(tpex_url, tpex_params)
        data = resp.json()
        _validate_response_date(data, date_ce)
        if str(data.get("stat", "")).lower() != "ok":
            raise ValueError("TPEX 三大法人回應狀態非 ok")
        tpex_rows = _security_table_rows(data, minimum_columns=17)
        if not tpex_rows:
            raise ValueError("TPEX 三大法人回應缺少有效明細 table")
        availability = observed_only_availability_fields()
        for row in tpex_rows:
            if len(row) >= 17:
                try:
                    if len(row) >= 24:
                        # 現行 24 欄：外資小計 8:10、投信 11:13、
                        # 自營商小計 20:22；中間欄位是各子類別。
                        fi_buy = safe_int(row[8])
                        fi_sell = safe_int(row[9])
                        fi_net = safe_int(row[10])
                        it_buy = safe_int(row[11])
                        it_sell = safe_int(row[12])
                        it_net = safe_int(row[13])
                        dl_buy = safe_int(row[20])
                        dl_sell = safe_int(row[21])
                        dl_net = safe_int(row[22])
                    else:
                        # 舊 17 欄：外資與自營商各由兩個子類別相加。
                        fi_buy = safe_int(row[2]) + safe_int(row[5])
                        fi_sell = safe_int(row[3]) + safe_int(row[6])
                        fi_net = safe_int(row[4]) + safe_int(row[7])
                        it_buy = safe_int(row[8])
                        it_sell = safe_int(row[9])
                        it_net = safe_int(row[10])
                        dl_buy = safe_int(row[11]) + safe_int(row[14])
                        dl_sell = safe_int(row[12]) + safe_int(row[15])
                        dl_net = safe_int(row[13]) + safe_int(row[16])

                    stock_code = str(row[0]).strip()
                    if not stock_code:
                        continue
                    rows.append({
                        "stock_code": stock_code,
                        "decision_date": decision_date.isoformat(),
                        "source_version": "tpex-official-3itrade",
                        **availability,
                        "foreign_investor_buy": fi_buy,
                        "foreign_investor_sell": fi_sell,
                        "foreign_investor_net": fi_net,
                        "investment_trust_buy": it_buy,
                        "investment_trust_sell": it_sell,
                        "investment_trust_net": it_net,
                        "dealer_buy": dl_buy,
                        "dealer_sell": dl_sell,
                        "dealer_net": dl_net,
                    })
                except (IndexError, TypeError):
                    continue
    except Exception as e:
        source_errors.append(f"TPEX 3insti: {type(e).__name__}: {e}")

    if source_errors:
        raise RuntimeError("；".join(source_errors))

    return pd.DataFrame(rows)

# ==========================================
# 信用交易 (Credit Transactions)
# ==========================================
def fetch_credit_transactions(decision_date: date) -> pd.DataFrame:
    """抓取指定日期的信用交易/融資券 (上市 + 上櫃)"""
    date_ce = decision_date.strftime("%Y%m%d")
    date_roc = to_roc_date(decision_date)

    rows: list[dict[str, Any]] = []
    source_errors: list[str] = []

    # --- TWSE ---
    twse_url = "https://www.twse.com.tw/exchangeReport/MI_MARGN"
    twse_params = {"response": "json", "date": date_ce, "selectType": "ALL"}
    logger.info(f"爬取 TWSE 融資券: {twse_url}?date={date_ce}")
    try:
        resp = safe_request(twse_url, twse_params)
        data = resp.json()

        _validate_response_date(data, date_ce)
        if data.get("stat") != "OK":
            raise ValueError("TWSE MI_MARGN 回應狀態非 OK")
        twse_rows = _security_table_rows(data, minimum_columns=13)
        if not twse_rows:
            raise ValueError("TWSE MI_MARGN 回應缺少有效明細 table")
        availability = observed_only_availability_fields()
        for row in twse_rows:
            if len(row) < 13:
                continue
            stock_code = str(row[0]).strip()
            if not stock_code:
                continue
            rows.append({
                "stock_code": stock_code,
                "decision_date": decision_date.isoformat(),
                "source_version": "twse-official-MI_MARGN",
                **availability,
                "margin_purchase": safe_int(row[2]),
                "margin_balance": safe_int(row[6]),
                "short_sale": safe_int(row[9]),
                "short_balance": safe_int(row[12]),
                "financing": None,
                "securities_lending": None,
            })
    except Exception as e:
        source_errors.append(f"TWSE MI_MARGN: {type(e).__name__}: {e}")

    time.sleep(3) # 防 Ban

    # --- TPEX ---
    tpex_url = "https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php"
    tpex_params = {"l": "zh-tw", "o": "json", "d": date_roc}
    logger.info(f"爬取 TPEX 融資券: {tpex_url}?d={date_roc}")
    try:
        resp = safe_request(tpex_url, tpex_params)
        data = resp.json()

        _validate_response_date(data, date_ce)
        if str(data.get("stat", "")).lower() != "ok":
            raise ValueError("TPEX 信用交易回應狀態非 ok")
        # 現行明細至少要含至「券餘額」(index 14)，避免誤選摘要表。
        tpex_rows = _security_table_rows(data, minimum_columns=15)
        if not tpex_rows:
            raise ValueError("TPEX 信用交易回應缺少有效明細 table")
        availability = observed_only_availability_fields()
        for row in tpex_rows:
            if len(row) >= 15:
                try:
                    stock_code = str(row[0]).strip()
                    if not stock_code:
                        continue
                    rows.append({
                        "stock_code": stock_code,
                        "decision_date": decision_date.isoformat(),
                        "source_version": "tpex-official-margin_bal",
                        **availability,
                        "margin_purchase": safe_int(row[3]),
                        "margin_balance": safe_int(row[6]),
                        "short_sale": safe_int(row[11]),
                        "short_balance": safe_int(row[14]),
                        "financing": None,
                        "securities_lending": None,
                    })
                except (IndexError, TypeError):
                    continue
    except Exception as e:
        source_errors.append(f"TPEX margin: {type(e).__name__}: {e}")

    if source_errors:
        raise RuntimeError("；".join(source_errors))

    return pd.DataFrame(rows)

# ==========================================
# TDCC 集保庫存 (Shareholding Tiers)
# ==========================================
def _fetch_tdcc_shareholding(expected_date: Optional[date]) -> pd.DataFrame:
    """抓取最新一週集保資料；可選擇要求資料日與指定日期一致。"""
    url = "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5"
    logger.info(f"爬取 TDCC 集保庫存: {url}")
    try:
        resp = safe_request(url)
        resp.encoding = 'utf-8'

        df_raw = pd.read_csv(io.StringIO(resp.text))

        if df_raw.empty or "資料日期" not in df_raw.columns:
            return pd.DataFrame()

        payload_dates = {
            str(value).strip()
            for value in df_raw["資料日期"].dropna().tolist()
        }
        if len(payload_dates) != 1:
            raise ValueError("TDCC payload 必須只有一個明確資料日期")
        latest_date_str = next(iter(payload_dates))
        try:
            data_date = datetime.strptime(latest_date_str, "%Y%m%d").date()
        except ValueError as exc:
            raise ValueError(f"TDCC payload 資料日期格式無效: {latest_date_str}") from exc

        if expected_date is not None and data_date != expected_date:
            logger.warning(
                f"TDCC 最新資料日期為 {data_date}，與 decision_date {expected_date} 不符，略過。"
            )
            return pd.DataFrame()

        grouped = df_raw.groupby("證券代號")
        rows: list[dict[str, Any]] = []
        availability = observed_only_availability_fields()

        for stock_code, group in grouped:
            ratio_col = [col for col in group.columns if '比例' in col]
            if not ratio_col:
                continue
            ratio_col_name = ratio_col[0]

            # 使用 Decimal 計算比例避免浮點數誤差，然後轉換為 bp
            def sum_ratios(df_subset):
                total = Decimal('0')
                for val in df_subset[ratio_col_name]:
                    try:
                        total += Decimal(str(val))
                    except Exception:
                        pass
                return total

            large_holder_ratio = sum_ratios(group[group["持股分級"] == 15])
            retail_holder_ratio = sum_ratios(group[group["持股分級"] <= 5])

            large_bp = int((large_holder_ratio * Decimal('100')).to_integral_value(rounding=ROUND_HALF_UP))
            retail_bp = int((retail_holder_ratio * Decimal('100')).to_integral_value(rounding=ROUND_HALF_UP))
            disp_bp = retail_bp - large_bp

            rows.append({
                "stock_code": str(stock_code),
                "decision_date": data_date.isoformat(),
                "source_version": "tdcc-official-od-1-5",
                **availability,
                "shareholding_tiers": "weekly_distribution_available",
                "large_holder_ratio_bp": large_bp,
                "retail_holder_ratio_bp": retail_bp,
                "dispersion_index_bp": disp_bp,
            })

        return pd.DataFrame(rows)
    except Exception as e:
        logger.error(f"TDCC 集保庫存爬取失敗: {e}")
        return pd.DataFrame()


def fetch_tdcc_shareholding(decision_date: date) -> pd.DataFrame:
    """相容既有日期式呼叫；資料日不同時維持 fail-closed。"""

    return _fetch_tdcc_shareholding(decision_date)


def fetch_latest_tdcc_shareholding() -> pd.DataFrame:
    """唯讀取得官方最新週 snapshot，資料日一律採 payload 自帶日期。"""

    return _fetch_tdcc_shareholding(None)
