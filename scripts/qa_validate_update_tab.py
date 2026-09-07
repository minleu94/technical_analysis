"""
Data Update Tab QA 驗證腳本
自動檢查與測試數據更新功能是否正確、穩定、可回歸
"""

import sys
import os
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import traceback
import logging
import tempfile
import sqlite3
from typing import List, Dict, Any, Optional

# 添加專案根目錄到路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from data_module.config import TWStockConfig
from data_module.fundamental_schema import apply_fundamental_schema
from app_module.update_service import UpdateService

# 設置日誌
log_dir = project_root / 'output' / 'qa' / 'update_tab'
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / 'RUN_LOG.txt', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# 測試日期範圍（使用最近的日期，避免下載太多數據）
TEST_DATE_RANGE = {
    'start': (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
    'end': datetime.now().strftime("%Y-%m-%d")
}


def _isolated_config(root: Path) -> TWStockConfig:
    """建立本腳本專用的雙根隔離設定，避免 QA 觸碰正式資料。"""

    config = TWStockConfig(
        data_root=root / "data",
        output_root=root / "artifacts",
        profile="qa",
    )
    config.use_sqlite = True
    config.min_data_days = 5
    config.technical_process_pool_enabled = False
    return config


def _seed_isolated_fixture(config: TWStockConfig) -> None:
    """寫入最小離線 fixture，覆蓋價格、指數與分點來源。"""

    dates = pd.bdate_range("2026-07-01", periods=12)
    daily_rows: list[dict[str, Any]] = []
    market_rows: list[dict[str, Any]] = []
    industry_rows: list[dict[str, Any]] = []
    for timestamp in dates:
        date_key = timestamp.strftime("%Y%m%d")
        close = 100 + int(timestamp.day)
        daily_rows.append(
            {
                "日期": date_key,
                "證券代號": "2330",
                "證券名稱": "台積電",
                "成交股數": 1000,
                "成交筆數": 10,
                "成交金額": 100000,
                "開盤價": close - 1,
                "最高價": close + 1,
                "最低價": close - 2,
                "收盤價": close,
                "漲跌": "+",
                "漲跌價差": 1,
                "最後揭示買價": close - 1,
                "最後揭示買量": 10,
                "最後揭示賣價": close + 1,
                "最後揭示賣量": 10,
                "本益比": 20,
            }
        )
        market_rows.append(
            {"日期": date_key, "收盤價": 20000 + int(timestamp.day)}
        )
        industry_rows.append(
            {
                "日期": date_key,
                "產業別": "半導體業",
                "收盤指數": 1000 + int(timestamp.day),
            }
        )

    for row in daily_rows:
        pd.DataFrame([row]).to_csv(
            config.daily_price_dir / f"{row['日期']}.csv",
            index=False,
            encoding="utf-8-sig",
        )
    pd.DataFrame(market_rows).to_csv(
        config.market_index_file, index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(industry_rows).to_csv(
        config.industry_index_file, index=False, encoding="utf-8-sig"
    )

    broker_daily = config.broker_flow_dir / "9200_1234" / "daily"
    broker_daily.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "date": dates[-1].strftime("%Y%m%d"),
                "trade_type": "買超",
                "counterparty_broker_code": "2330",
                "counterparty_broker_name": "台積電",
                "buy_lots": 10,
                "sell_lots": 1,
                "net_lots": 9,
                "branch_display_name": "測試分點",
            }
        ]
    ).to_csv(
        broker_daily / f"{dates[-1].strftime('%Y%m%d')}.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # 狀態摘要也會讀取月營收表；在隔離 SQLite 建立一筆中性 fixture，
    # 使缺少該可選表時明確呈現為 unavailable，而非把 schema 缺件誤判成 QA 通過。
    with sqlite3.connect(config.db_file) as conn:
        apply_fundamental_schema(conn)
        conn.execute(
            """
            INSERT OR REPLACE INTO fundamental_monthly_revenues(
                stock_code, period, as_of_date, announced_date, available_date,
                revenue, source, source_version, quality
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "2330",
                "2026-06",
                "2026-06-30",
                "2026-07-10",
                "2026-07-16",
                "1000000",
                "qa.fixture",
                "qa.fixture.v1",
                "observed",
            ),
        )


def _close_isolated_file_handlers(root: Path) -> None:
    """關閉指向隔離根的檔案 logger，讓 Windows 可安全清理暫存根。"""

    resolved_root = root.resolve()
    loggers = [logging.getLogger()]
    loggers.extend(
        value
        for value in logging.Logger.manager.loggerDict.values()
        if isinstance(value, logging.Logger)
    )
    for logger in loggers:
        for handler in list(logger.handlers):
            filename = getattr(handler, "baseFilename", None)
            if not filename:
                continue
            try:
                is_isolated = Path(filename).resolve().is_relative_to(resolved_root)
            except (OSError, ValueError):
                is_isolated = False
            if is_isolated:
                logger.removeHandler(handler)
                handler.close()


def validate_closed_loop_fixture(config: TWStockConfig, result: "ValidationResult") -> None:
    """以離線 fixture 驗證同步、SQLite 落地與指標單一寫入者。"""

    service = UpdateService(config)
    try:
        daily = service.sync_source_to_sqlite("daily_price_files")
        market = service.sync_source_to_sqlite("market_index")
        industry = service.sync_source_to_sqlite("industry_index")
        broker = service.sync_source_to_sqlite("broker_branch_files")
        if not all(item.get("success") for item in (daily, market, industry, broker)):
            result.add_fail(
                "closed_loop_sqlite_sync",
                "離線 fixture 同步未完整成功",
                evidence={"daily": daily, "market": market, "industry": industry, "broker": broker},
                issue_type="logic_errors",
            )
            return
        result.add_pass(
            "closed_loop_sqlite_sync",
            evidence={
                "daily_records": daily.get("synced_records"),
                "market_records": market.get("synced_records"),
                "industry_records": industry.get("synced_records"),
                "broker_records": broker.get("synced_records"),
            },
        )

        indicators = service.calculate_technical_indicators(force_all=True)
        if not indicators.get("success"):
            result.add_fail(
                "closed_loop_technical_indicators",
                str(indicators.get("message") or "技術指標計算失敗"),
                evidence=indicators,
                issue_type="logic_errors",
            )
            return
        status = service.check_data_status()
        technical = status.get("technical_indicators", {})
        if technical.get("status") not in {"ok", "current"}:
            result.add_fail(
                "closed_loop_technical_status",
                f"技術指標狀態未完成：{technical.get('status')}",
                evidence=technical,
                issue_type="data_quality",
            )
            return
        result.add_pass(
            "closed_loop_technical_indicators",
            evidence={
                "success_count": indicators.get("success_count"),
                "status": technical,
                "parent_single_writer": indicators.get("technical_process_pool", {}).get(
                    "parent_single_writer"
                ),
            },
        )
    except Exception as exc:
        result.add_fail(
            "closed_loop_fixture_exception",
            str(exc),
            traceback.format_exc(),
            issue_type="logic_errors",
        )


class ValidationResult:
    """驗證結果記錄"""
    def __init__(self):
        self.passed = []
        self.failed = []
        self.skipped = []
        self.evidence = {}
        self.issues = {
            'logic_errors': [],
            'contract_violations': [],
            'data_quality': [],
            'ui_service_mismatch': [],
        }
    
    def add_pass(self, feature, evidence=None):
        self.passed.append(feature)
        if evidence:
            self.evidence[feature] = evidence
    
    def add_fail(self, feature, error, evidence=None, issue_type='logic_errors'):
        self.failed.append({
            'feature': feature,
            'error': error,
            'evidence': evidence,
            'issue_type': issue_type
        })
        if issue_type in self.issues:
            self.issues[issue_type].append({
                'feature': feature,
                'error': error,
                'evidence': evidence
            })
    
    def add_skip(self, feature, reason):
        self.skipped.append({
            'feature': feature,
            'reason': reason
        })


def validate_service_layer(config, result: ValidationResult):
    """驗證 Service 層（不啟動 UI）"""
    logger.info("=" * 80)
    logger.info("驗證 Service 層")
    logger.info("=" * 80)
    
    try:
        update_service = UpdateService(config)
        
        # 測試 1: check_data_status
        logger.info("\n[Service Test] check_data_status")
        try:
            status = update_service.check_data_status()
            
            logger.info(f"  返回類型: {type(status)}")
            logger.info(f"  返回內容: {json.dumps(status, ensure_ascii=False, indent=2, default=str)}")
            
            # 驗證返回結構
            if not isinstance(status, dict):
                result.add_fail(
                    'check_data_status_ReturnType',
                    f"返回類型錯誤: {type(status)}, 期望 dict",
                    issue_type='contract_violations'
                )
            else:
                # 檢查必要欄位
                expected_keys = ['daily_data', 'market_index', 'industry_index']
                missing_keys = [key for key in expected_keys if key not in status]
                if missing_keys:
                    result.add_fail(
                        'check_data_status_MissingKeys',
                        f"缺少必要欄位: {missing_keys}",
                        evidence={'available_keys': list(status.keys())},
                        issue_type='contract_violations'
                    )
                else:
                    # 驗證每個數據類型的結構
                    for key in expected_keys:
                        data_info = status.get(key, {})
                        if not isinstance(data_info, dict):
                            result.add_fail(
                                f'check_data_status_{key}_Type',
                                f"{key} 類型錯誤: {type(data_info)}, 期望 dict",
                                issue_type='contract_violations'
                            )
                        else:
                            # 檢查必要欄位
                            required_fields = ['latest_date', 'total_records', 'status']
                            missing_fields = [f for f in required_fields if f not in data_info]
                            if missing_fields:
                                result.add_fail(
                                    f'check_data_status_{key}_MissingFields',
                                    f"{key} 缺少欄位: {missing_fields}",
                                    evidence={'available_fields': list(data_info.keys())},
                                    issue_type='contract_violations'
                                )
                            else:
                                result.add_pass(f'check_data_status_{key}', {
                                    'latest_date': data_info.get('latest_date'),
                                    'total_records': data_info.get('total_records'),
                                    'status': data_info.get('status')
                                })
                    
                    result.add_pass('check_data_status_Service', {
                        'status': status
                    })
        
        except Exception as e:
            result.add_fail(
                'check_data_status_Exception',
                str(e),
                traceback.format_exc(),
                issue_type='logic_errors'
            )
        
        # 測試 2: update_daily（不實際下載，只測試接口）
        logger.info("\n[Service Test] update_daily (接口測試)")
        try:
            # 檢查方法是否存在
            if not hasattr(update_service, 'update_daily'):
                result.add_fail(
                    'update_daily_MethodMissing',
                    "update_daily 方法不存在",
                    issue_type='contract_violations'
                )
            else:
                # 檢查方法簽名
                import inspect
                sig = inspect.signature(update_service.update_daily)
                params = list(sig.parameters.keys())
                expected_params = ['start_date', 'end_date']
                missing_params = [p for p in expected_params if p not in params]
                if missing_params:
                    result.add_fail(
                        'update_daily_MissingParams',
                        f"缺少必要參數: {missing_params}",
                        evidence={'available_params': params},
                        issue_type='contract_violations'
                    )
                else:
                    result.add_pass('update_daily_Interface', {
                        'parameters': params
                    })
                    
                    # 測試調用（使用很小的日期範圍，避免實際下載）
                    # 注意：這裡只測試接口，不實際執行下載
                    logger.info("  ⚠️ 跳過實際下載測試（避免下載大量數據）")
                    result.add_skip(
                        'update_daily_Execution',
                        "跳過實際下載測試（避免下載大量數據）"
                    )
        
        except Exception as e:
            result.add_fail(
                'update_daily_Exception',
                str(e),
                traceback.format_exc(),
                issue_type='logic_errors'
            )
        
        # 測試 3: update_market（接口測試）
        logger.info("\n[Service Test] update_market (接口測試)")
        try:
            if not hasattr(update_service, 'update_market'):
                result.add_fail(
                    'update_market_MethodMissing',
                    "update_market 方法不存在",
                    issue_type='contract_violations'
                )
            else:
                import inspect
                sig = inspect.signature(update_service.update_market)
                params = list(sig.parameters.keys())
                result.add_pass('update_market_Interface', {
                    'parameters': params
                })
                result.add_skip(
                    'update_market_Execution',
                    "跳過實際下載測試（避免下載大量數據）"
                )
        
        except Exception as e:
            result.add_fail(
                'update_market_Exception',
                str(e),
                traceback.format_exc(),
                issue_type='logic_errors'
            )
        
        # 測試 4: update_industry（接口測試）
        logger.info("\n[Service Test] update_industry (接口測試)")
        try:
            if not hasattr(update_service, 'update_industry'):
                result.add_fail(
                    'update_industry_MethodMissing',
                    "update_industry 方法不存在",
                    issue_type='contract_violations'
                )
            else:
                import inspect
                sig = inspect.signature(update_service.update_industry)
                params = list(sig.parameters.keys())
                result.add_pass('update_industry_Interface', {
                    'parameters': params
                })
                result.add_skip(
                    'update_industry_Execution',
                    "跳過實際下載測試（避免下載大量數據）"
                )
        
        except Exception as e:
            result.add_fail(
                'update_industry_Exception',
                str(e),
                traceback.format_exc(),
                issue_type='logic_errors'
            )
        
        # 測試 5: merge_daily_data（接口測試）
        logger.info("\n[Service Test] merge_daily_data (接口測試)")
        try:
            if not hasattr(update_service, 'merge_daily_data'):
                result.add_fail(
                    'merge_daily_data_MethodMissing',
                    "merge_daily_data 方法不存在",
                    issue_type='contract_violations'
                )
            else:
                import inspect
                sig = inspect.signature(update_service.merge_daily_data)
                params = list(sig.parameters.keys())
                result.add_pass('merge_daily_data_Interface', {
                    'parameters': params
                })
                
                # 測試調用（增量合併，不實際執行）
                logger.info("  ⚠️ 跳過實際合併測試（避免修改數據）")
                result.add_skip(
                    'merge_daily_data_Execution',
                    "跳過實際合併測試（避免修改數據）"
                )
        
        except Exception as e:
            result.add_fail(
                'merge_daily_data_Exception',
                str(e),
                traceback.format_exc(),
                issue_type='logic_errors'
            )
        
    except Exception as e:
        logger.error(f"Service 層驗證失敗: {e}")
        logger.error(traceback.format_exc())
        result.add_fail('Service_Layer_Setup', str(e), traceback.format_exc())


def validate_ui_service_contract(result: ValidationResult, config: TWStockConfig):
    """驗證 UI 與 Service 的 Contract"""
    logger.info("=" * 80)
    logger.info("驗證 UI ↔ Service Contract")
    logger.info("=" * 80)
    
    try:
        # 讀取 UI 代碼，檢查使用的欄位
        ui_file = project_root / 'ui_qt' / 'views' / 'update_view.py'
        if not ui_file.exists():
            result.add_skip('UI_Contract_Check', "找不到 UI 文件")
            return
        
        ui_code = ui_file.read_text(encoding='utf-8')
        
        # 檢查 UI 中調用的方法
        ui_called_methods = []
        if 'update_service.update_daily' in ui_code:
            ui_called_methods.append('update_daily')
        if 'update_service.update_market' in ui_code:
            ui_called_methods.append('update_market')
        if 'update_service.update_industry' in ui_code:
            ui_called_methods.append('update_industry')
        if 'update_service.merge_daily_data' in ui_code:
            ui_called_methods.append('merge_daily_data')
        if 'update_service.check_data_status' in ui_code:
            ui_called_methods.append('check_data_status')
        
        # 驗證這些方法在 Service 中是否存在
        from app_module.update_service import UpdateService
        service = UpdateService(config)
        
        missing_methods = []
        for method_name in ui_called_methods:
            if not hasattr(service, method_name):
                missing_methods.append(method_name)
        
        if missing_methods:
            result.add_fail(
                'UI_Contract_MissingMethods',
                f"UI 調用的方法在 Service 中不存在: {missing_methods}",
                evidence={'ui_called_methods': ui_called_methods},
                issue_type='contract_violations'
            )
        else:
            result.add_pass('UI_Contract_Methods', {
                'ui_called_methods': ui_called_methods,
                'service_methods': [m for m in dir(service) if not m.startswith('_')]
            })
        
        # 檢查 UI 期望的返回結構
        # UI 期望 check_data_status 返回 dict，包含 daily_data, market_index, industry_index
        if 'check_data_status' in ui_called_methods:
            # 檢查 UI 如何使用返回結果
            if 'status.get(' in ui_code or 'status[' in ui_code:
                # UI 期望 status 是 dict
                result.add_pass('UI_Contract_check_data_status_Type', {
                    'expected_type': 'dict'
                })
        
        # 檢查 update_daily 返回結構
        if 'update_daily' in ui_called_methods:
            # UI 期望返回 dict，包含 success, message, updated_dates, failed_dates
            if 'result.get(\'success\'' in ui_code or 'result.get(\'updated_dates\'' in ui_code:
                result.add_pass('UI_Contract_update_daily_ReturnType', {
                    'expected_fields': ['success', 'message', 'updated_dates', 'failed_dates']
                })
        
        # 檢查 merge_daily_data 返回結構
        if 'merge_daily_data' in ui_called_methods:
            # UI 期望返回 dict，包含 success, message, total_records, merged_files
            if 'result.get(\'success\'' in ui_code or 'result.get(\'total_records\'' in ui_code:
                result.add_pass('UI_Contract_merge_daily_data_ReturnType', {
                    'expected_fields': ['success', 'message', 'total_records', 'merged_files']
                })
        
    except Exception as e:
        logger.error(f"UI Contract 驗證失敗: {e}")
        logger.error(traceback.format_exc())
        result.add_fail('UI_Contract_Check', str(e), traceback.format_exc())


def validate_data_status_logic(config, result: ValidationResult):
    """驗證數據狀態檢查邏輯"""
    logger.info("=" * 80)
    logger.info("驗證數據狀態檢查邏輯")
    logger.info("=" * 80)
    
    try:
        update_service = UpdateService(config)
        
        # 執行 check_data_status
        status = update_service.check_data_status()

        core_sources = {
            'daily_data',
            'market_index',
            'industry_index',
            'broker_branch',
            'technical_indicators',
        }

        # 驗證數據狀態的合理性
        for key, data_info in status.items():
            if isinstance(data_info, dict):
                latest_date = data_info.get('latest_date')
                total_records = data_info.get('total_records', 0)
                status_str = data_info.get('status', 'unknown')
                normalized_status = str(status_str or '').strip().lower()

                # 狀態檢查本身若回傳錯誤，必須讓 QA 失敗；不能因為
                # total_records=0 仍是合法數字，就把缺表／連線錯誤算成通過。
                if normalized_status.startswith((
                    'error', 'failed', 'failure', 'exception',
                )):
                    result.add_fail(
                        f'{key}_Status',
                        f"資料狀態檢查回傳錯誤：{status_str}",
                        evidence={'status': status_str, 'latest_date': latest_date},
                        issue_type='data_quality',
                    )
                elif key in core_sources and normalized_status in {
                    'missing', 'empty', 'unavailable',
                }:
                    result.add_fail(
                        f'{key}_Availability',
                        f"核心資料源不可用：{status_str}",
                        evidence={'status': status_str, 'latest_date': latest_date},
                        issue_type='data_quality',
                    )
                
                # 檢查 latest_date 格式
                if latest_date and latest_date != '未知':
                    try:
                        # 嘗試解析日期
                        datetime.strptime(str(latest_date), "%Y-%m-%d")
                        result.add_pass(f'{key}_DateFormat', {
                            'latest_date': latest_date
                        })
                    except (ValueError, TypeError):
                        result.add_fail(
                            f'{key}_DateFormat',
                            f"日期格式錯誤: {latest_date}",
                            evidence={'latest_date': latest_date},
                            issue_type='data_quality'
                        )
                
                # 檢查 total_records 類型
                if not isinstance(total_records, (int, float)):
                    result.add_fail(
                        f'{key}_TotalRecordsType',
                        f"total_records 類型錯誤: {type(total_records)}, 期望 int 或 float",
                        evidence={'total_records': total_records},
                        issue_type='data_quality'
                    )
                elif total_records < 0:
                    result.add_fail(
                        f'{key}_TotalRecordsNegative',
                        f"total_records 為負數: {total_records}",
                        evidence={'total_records': total_records},
                        issue_type='data_quality'
                    )
                else:
                    result.add_pass(f'{key}_TotalRecords', {
                        'total_records': total_records
                    })

        # 核心資料源若落後每日股價，應被標示為 freshness 問題，而不是
        # 只要表內有資料就算正常。這裡只比較可解析的交易日，避免干擾
        # 月營收等不同粒度資料源。
        daily_info = status.get('daily_data', {})
        daily_latest = daily_info.get('latest_date') if isinstance(daily_info, dict) else None
        if daily_latest:
            try:
                daily_dt = pd.to_datetime(str(daily_latest), errors='raise')
            except (TypeError, ValueError):
                daily_dt = None
            if daily_dt is not None:
                for key in core_sources - {'daily_data'}:
                    data_info = status.get(key, {})
                    if not isinstance(data_info, dict):
                        continue
                    latest = data_info.get('latest_date')
                    if not latest:
                        continue
                    try:
                        latest_dt = pd.to_datetime(str(latest), errors='raise')
                    except (TypeError, ValueError):
                        continue
                    if latest_dt < daily_dt and not str(data_info.get('status', '')).lower().startswith('error'):
                        result.add_fail(
                            f'{key}_Freshness',
                            f"{key} 最新日 {latest} 落後每日股價 {daily_latest}",
                            evidence={'source_latest_date': latest, 'daily_latest_date': daily_latest},
                            issue_type='data_quality',
                        )
        
    except Exception as e:
        logger.error(f"數據狀態檢查邏輯驗證失敗: {e}")
        logger.error(traceback.format_exc())
        result.add_fail('Data_Status_Logic', str(e), traceback.format_exc())


def generate_report(result: ValidationResult) -> str:
    """生成 Markdown 報告"""
    report_lines = [
        "# Data Update Tab 驗證報告",
        "",
        f"**生成時間**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 📊 測試摘要",
        "",
        f"- ✅ **通過**: {len(result.passed)} 項",
        f"- ❌ **失敗**: {len(result.failed)} 項",
        f"- ⏭️ **跳過**: {len(result.skipped)} 項",
        "",
        "## ✅ 通過項目",
        ""
    ]
    
    if result.passed:
        for feature in result.passed:
            report_lines.append(f"- {feature}")
            if feature in result.evidence:
                evidence = result.evidence[feature]
                if isinstance(evidence, dict):
                    report_lines.append(f"  - 證據: {json.dumps(evidence, ensure_ascii=False, indent=2, default=str)}")
    else:
        report_lines.append("無")
    
    report_lines.extend([
        "",
        "## ❌ 失敗項目",
        ""
    ])
    
    if result.failed:
        for fail in result.failed:
            report_lines.append(f"### {fail['feature']}")
            report_lines.append(f"**錯誤**: {fail['error']}")
            report_lines.append(f"**問題類型**: {fail.get('issue_type', 'unknown')}")
            if fail.get('evidence'):
                report_lines.append(f"**證據**:")
                report_lines.append(f"```json")
                report_lines.append(json.dumps(fail['evidence'], ensure_ascii=False, indent=2, default=str))
                report_lines.append(f"```")
            report_lines.append("")
    else:
        report_lines.append("無")
    
    report_lines.extend([
        "",
        "## ⏭️ 跳過項目",
        ""
    ])
    
    if result.skipped:
        for skip in result.skipped:
            report_lines.append(f"- **{skip['feature']}**: {skip['reason']}")
    else:
        report_lines.append("無")
    
    report_lines.extend([
        "",
        "## 🔍 問題分類",
        ""
    ])
    
    for issue_type, issues in result.issues.items():
        if issues:
            report_lines.append(f"### {issue_type}")
            for issue in issues:
                report_lines.append(f"- **{issue['feature']}**: {issue['error']}")
            report_lines.append("")
    
    report_lines.extend([
        "",
        "## 🚨 阻擋 Release 的問題",
        ""
    ])
    
    blockers = []
    for fail in result.failed:
        issue_type = fail.get('issue_type', 'unknown')
        if issue_type in ['contract_violations', 'logic_errors']:
            blockers.append(fail)
    
    if blockers:
        for blocker in blockers:
            report_lines.append(f"- **{blocker['feature']}**: {blocker['error']}")
    else:
        report_lines.append("無阻擋問題")
    
    report_lines.extend([
        "",
        "## 📝 建議",
        "",
        "### 可全自動驗證（✅ QA script 可 cover）",
        "- Service 層測試",
        "- 方法接口驗證",
        "- 返回結構驗證",
        "- 數據狀態檢查邏輯",
        "",
        "### 需啟動 Qt 但可自動化（⚠️ pytest-qt / QTest）",
        "- UI 組件初始化",
        "- 按鈕點擊事件",
        "- 進度條更新",
        "- 日誌顯示",
        "",
        "### 必須人工檢查（👀 純視覺/UX）",
        "- UI 布局",
        "- 按鈕樣式",
        "- 進度條動畫",
        "- 錯誤訊息顯示",
        ""
    ])
    
    return "\n".join(report_lines)


def main():
    """主函數"""
    logger.info("=" * 80)
    logger.info("Data Update Tab QA 驗證")
    logger.info("=" * 80)
    
    result = ValidationResult()
    
    try:
        # 所有可寫入資料都落在暫存雙根；不讀取、不修改正式資料根目錄。
        with tempfile.TemporaryDirectory(prefix="task-loop-01-qa-") as sandbox:
            sandbox_root = Path(sandbox)
            config = _isolated_config(sandbox_root)
            _seed_isolated_fixture(config)

            try:
                # 先驗證離線資料取得、SQLite 落地與技術指標單一寫入者，
                # 再驗證 service/UI contract 與狀態判讀，避免空資料誤報通過。
                validate_closed_loop_fixture(config, result)
                validate_service_layer(config, result)
                validate_ui_service_contract(result, config)
                validate_data_status_logic(config, result)
            finally:
                _close_isolated_file_handlers(sandbox_root)
        
    except Exception as e:
        logger.error(f"驗證過程發生錯誤: {e}")
        logger.error(traceback.format_exc())
        result.add_fail('Main_Exception', str(e), traceback.format_exc())
    
    # 生成報告
    report = generate_report(result)
    report_file = log_dir / 'VALIDATION_REPORT.md'
    report_file.write_text(report, encoding='utf-8')
    logger.info(f"\n報告已保存至: {report_file}")
    
    # 控制台摘要
    logger.info("\n" + "=" * 80)
    logger.info("驗證摘要")
    logger.info("=" * 80)
    logger.info(f"通過: {len(result.passed)}")
    logger.info(f"失敗: {len(result.failed)}")
    logger.info(f"跳過: {len(result.skipped)}")
    logger.info(f"\n詳細報告: {report_file}")
    
    # 返回退出碼
    if result.failed:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

