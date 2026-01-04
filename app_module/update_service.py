"""
數據更新服務 (Update Service)
提供數據更新的業務邏輯
"""

import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta


class UpdateService:
    """數據更新服務類"""
    
    def __init__(self, config):
        """初始化數據更新服務
        
        Args:
            config: TWStockConfig 實例
        """
        self.config = config
        self.project_root = Path(__file__).parent.parent
        self.scripts_dir = self.project_root / 'scripts'
    
    def update_daily(
        self, 
        start_date: str, 
        end_date: str,
        delay_seconds: float = 4.0
    ) -> Dict[str, Any]:
        """更新每日股票數據
        
        在指定日期範圍內查找缺失的日期並下載
        
        Args:
            start_date: 開始日期（YYYY-MM-DD）- 用於查找缺失日期的範圍
            end_date: 結束日期（YYYY-MM-DD）- 用於查找缺失日期的範圍
            delay_seconds: 每次請求間隔（秒）
            
        Returns:
            dict: {
                'success': bool,
                'message': str,
                'updated_dates': list[str],
                'failed_dates': list[str]
            }
        """
        import subprocess
        import sys
        import logging
        
        logger = logging.getLogger(__name__)
        
        # ✅ 記錄輸入參數
        logger.info(
            f"[UpdateService] 開始更新每日股票數據: "
            f"start_date={start_date}, end_date={end_date}, delay_seconds={delay_seconds}"
        )
        
        # 調用 batch_update_daily_data.py
        script_path = self.scripts_dir / 'batch_update_daily_data.py'
        logger.debug(f"[UpdateService] 更新腳本路徑: {script_path}")
        if not script_path.exists():
            logger.error(f"[UpdateService] 找不到更新腳本: {script_path}")
            return {
                'success': False,
                'message': f'找不到更新腳本: {script_path}',
                'updated_dates': [],
                'failed_dates': []
            }
        
        try:
            # 執行腳本（腳本內部會檢查文件是否已存在，只下載缺失的）
            result = subprocess.run(
                [sys.executable, str(script_path), 
                 '--start-date', start_date,
                 '--end-date', end_date,
                 '--delay-min', str(delay_seconds),
                 '--delay-max', str(delay_seconds)],
                capture_output=True,
                text=True,
                encoding='utf-8'
            )
            
            if result.returncode == 0:
                # 解析輸出，提取成功和失敗的日期
                output = result.stdout + result.stderr  # 合併 stdout 和 stderr（日誌可能在 stderr）
                updated_dates = []
                failed_dates = []
                skipped_dates = []  # 已存在並跳過的日期
                
                import re
                # ✅ 調試：記錄輸出長度和關鍵行
                logger.debug(f"[UpdateService] 輸出長度: stdout={len(result.stdout)}, stderr={len(result.stderr)}")
                
                # 方法 1：從總結行解析（更可靠）
                # 優先查找 [UPDATE_SUMMARY] 標記的總結行（最可靠）
                # 格式: [UPDATE_SUMMARY] SUCCESS: X days, FAILED: Y days
                summary_match = re.search(r'\[UPDATE_SUMMARY\]\s*SUCCESS[：:]\s*(\d+)\s*days?[，,]\s*FAILED[：:]\s*(\d+)\s*days?', output)
                if summary_match:
                    success_count_from_summary = int(summary_match.group(1))
                    fail_count_from_summary = int(summary_match.group(2))
                    logger.debug(f"[UpdateService] 從 [UPDATE_SUMMARY] 解析: 成功={success_count_from_summary}, 失敗={fail_count_from_summary}")
                else:
                    success_count_from_summary = None
                    fail_count_from_summary = None
                
                # 方法 2：從日誌行解析（備用）
                # 查找 "成功: X 天" 和 "失敗: X 天" 的總結行
                # 支持日誌格式：2026-01-02 02:01:58,598 - __main__ - INFO - 成功: 6 天
                success_match = re.search(r'成功[：:]\s*(\d+)\s*天', output)
                fail_match = re.search(r'失敗[：:]\s*(\d+)\s*天', output)
                
                # 如果沒找到，嘗試查找 "成功 X 天"（沒有冒號）
                if not success_match:
                    success_match = re.search(r'成功\s+(\d+)\s*天', output)
                if not fail_match:
                    fail_match = re.search(r'失敗\s+(\d+)\s*天', output)
                
                # ✅ 調試：記錄匹配結果和實際輸出
                if success_match:
                    logger.debug(f"[UpdateService] 找到成功匹配: {success_match.group(1)}")
                else:
                    # 查找包含 "成功" 或 "失敗" 的行
                    lines_with_keywords = [l for l in output.split('\n') if '成功' in l or '失敗' in l]
                    logger.warning(
                        f"[UpdateService] 未找到成功匹配，"
                        f"包含關鍵詞的行數: {len(lines_with_keywords)}, "
                        f"最後幾行: {lines_with_keywords[-3:] if lines_with_keywords else 'None'}"
                    )
                if fail_match:
                    logger.debug(f"[UpdateService] 找到失敗匹配: {fail_match.group(1)}")
                else:
                    logger.warning(f"[UpdateService] 未找到失敗匹配")
                
                # 方法 2：逐行解析日期（用於獲取具體日期列表）
                lines = output.split('\n')
                for line in lines:
                    # 提取日期（如果行中包含日期）
                    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', line)
                    if not date_match:
                        continue
                    
                    date_str = date_match.group(1)
                    
                    # 檢查是否為成功（更新成功或已存在並跳過）
                    # 使用多種方式匹配，包括 Unicode 字符和轉義序列
                    if ('更新成功' in line or '✓' in line or '\u2713' in line or 
                        '成功' in line and '筆記錄' in line):
                        if date_str not in updated_dates:
                            updated_dates.append(date_str)
                    # 檢查是否為已存在並跳過（也視為成功）
                    elif ('已存在' in line or '⚠' in line or '\u26a0' in line or '跳過' in line):
                        if date_str not in skipped_dates:
                            skipped_dates.append(date_str)
                        if date_str not in updated_dates:
                            updated_dates.append(date_str)  # 已存在也算成功
                    # 檢查是否為失敗
                    elif ('更新失敗' in line or '✗' in line or '\u2717' in line or
                          '失敗' in line and '無法獲取' in line):
                        if date_str not in failed_dates:
                            failed_dates.append(date_str)
                
                # ✅ 如果從總結行解析到數字，使用總結行的數字（更準確）
                if success_match and fail_match:
                    success_count = int(success_match.group(1))
                    fail_count = int(fail_match.group(1))
                    
                    # 如果解析到的日期數量與總結不一致，使用總結的數字
                    if len(updated_dates) != success_count or len(failed_dates) != fail_count:
                        logger.warning(
                            f"[UpdateService] 日期解析不一致: "
                            f"解析到 {len(updated_dates)} 成功/{len(failed_dates)} 失敗, "
                            f"但總結顯示 {success_count} 成功/{fail_count} 失敗"
                        )
                        # 使用總結的數字，但保留已解析的日期列表（如果有的話）
                        if len(updated_dates) == 0:
                            # 如果沒有解析到日期，至少確保數字正確
                            updated_dates = [f"成功_{i+1}" for i in range(success_count)]
                        if len(failed_dates) == 0:
                            failed_dates = [f"失敗_{i+1}" for i in range(fail_count)]
                
                # ✅ 記錄結果（去重）
                updated_dates = list(set(updated_dates))
                failed_dates = list(set(failed_dates))
                skipped_dates = list(set(skipped_dates))
                
                # ✅ 優先使用總結行的數字（如果有的話）
                final_success_count = len(updated_dates)
                final_fail_count = len(failed_dates)
                
                # 優先使用 [UPDATE_SUMMARY] 標記的數字
                if success_count_from_summary is not None and fail_count_from_summary is not None:
                    final_success_count = success_count_from_summary
                    final_fail_count = fail_count_from_summary
                elif success_match and fail_match:
                    final_success_count = int(success_match.group(1))
                    final_fail_count = int(fail_match.group(1))
                
                # 生成訊息
                if skipped_dates:
                    message = f'更新完成：成功 {final_success_count} 天（其中 {len(skipped_dates)} 天已存在並跳過），失敗 {final_fail_count} 天'
                else:
                    message = f'更新完成：成功 {final_success_count} 天，失敗 {final_fail_count} 天'
                
                logger.info(
                    f"[UpdateService] 更新完成: "
                    f"成功 {final_success_count} 天（跳過 {len(skipped_dates)} 天）, 失敗 {final_fail_count} 天"
                )
                return {
                    'success': True,
                    'message': message,
                    'updated_dates': updated_dates if updated_dates else [],  # 保留日期列表（如果解析到）
                    'failed_dates': failed_dates if failed_dates else [],
                    'skipped_dates': skipped_dates
                }
            else:
                # ✅ 記錄錯誤
                logger.error(f"[UpdateService] 更新失敗: {result.stderr}")
                return {
                    'success': False,
                    'message': f'更新失敗：{result.stderr}',
                    'updated_dates': [],
                    'failed_dates': []
                }
        except Exception as e:
            import traceback
            logger.error(f"[UpdateService] 執行更新時發生異常: {str(e)}")
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'message': f'執行更新時發生錯誤：{str(e)}\n{traceback.format_exc()}',
                'updated_dates': [],
                'failed_dates': []
            }
    
    def update_market(
        self, 
        start_date: str, 
        end_date: str
    ) -> Dict[str, Any]:
        """更新大盤指數數據
        
        Args:
            start_date: 開始日期（YYYY-MM-DD）
            end_date: 結束日期（YYYY-MM-DD）
            
        Returns:
            dict: {
                'success': bool,
                'message': str,
                'updated_dates': list[str],
                'failed_dates': list[str]
            }
        """
        import subprocess
        import sys
        import logging
        import traceback
        import re
        
        logger = logging.getLogger(__name__)
        
        # ✅ 記錄輸入參數
        logger.info(
            f"[UpdateService] 開始更新大盤指數數據: "
            f"start_date={start_date}, end_date={end_date}"
        )
        
        try:
            # 動態導入並調用 batch_update_market_index 函數
            import importlib.util
            
            script_path = self.scripts_dir / 'batch_update_market_and_industry_index.py'
            logger.debug(f"[UpdateService] 更新腳本路徑: {script_path}")
            
            if not script_path.exists():
                error_msg = f'找不到更新腳本: {script_path}'
                logger.error(f"[UpdateService] {error_msg}")
                return {
                    'success': False,
                    'message': error_msg,
                    'updated_dates': [],
                    'failed_dates': []
                }
            
            # 動態導入模組
            try:
                spec = importlib.util.spec_from_file_location("batch_update_market_and_industry_index", script_path)
                if spec is None or spec.loader is None:
                    raise ImportError(f"無法創建模組規格: {script_path}")
                
                update_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(update_module)
                logger.debug(f"[UpdateService] 模組導入成功")
            except Exception as e:
                error_msg = f"導入更新模組時發生錯誤: {str(e)}"
                logger.error(f"[UpdateService] {error_msg}")
                logger.error(traceback.format_exc())
                return {
                    'success': False,
                    'message': error_msg,
                    'updated_dates': [],
                    'failed_dates': []
                }
            
            # 檢查函數是否存在
            if not hasattr(update_module, 'batch_update_market_index'):
                error_msg = f"更新模組中找不到 batch_update_market_index 函數"
                logger.error(f"[UpdateService] {error_msg}")
                return {
                    'success': False,
                    'message': error_msg,
                    'updated_dates': [],
                    'failed_dates': []
                }
            
            # 執行更新函數
            logger.info(f"[UpdateService] 開始執行大盤指數更新函數")
            try:
                # ✅ 傳遞 config 給更新函數（如果它支持的話）
                import inspect
                update_func = update_module.batch_update_market_index
                sig = inspect.signature(update_func)
                params = list(sig.parameters.keys())
                
                if 'config' in params:
                    logger.debug(f"[UpdateService] 更新函數支持 config 參數，傳遞配置")
                    result = update_func(start_date=start_date, end_date=end_date, config=self.config)
                else:
                    logger.debug(f"[UpdateService] 更新函數不支持 config 參數，使用默認參數")
                    result = update_func(start_date=start_date, end_date=end_date)
                logger.info(f"[UpdateService] 大盤指數更新函數執行完成")
                
                # 解析結果（函數可能沒有返回值）
                if result is None:
                    # 函數沒有返回值，假設成功
                    return {
                        'success': True,
                        'message': '大盤指數更新完成',
                        'updated_dates': [],
                        'failed_dates': []
                    }
                elif isinstance(result, dict):
                    return {
                        'success': result.get('success', True),
                        'message': result.get('message', '更新完成'),
                        'updated_dates': result.get('updated_dates', []),
                        'failed_dates': result.get('failed_dates', [])
                    }
                else:
                    # 如果返回的不是 dict，假設成功
                    return {
                        'success': True,
                        'message': '大盤指數更新完成',
                        'updated_dates': [],
                        'failed_dates': []
                    }
            except Exception as e:
                error_msg = f"執行大盤指數更新函數時發生錯誤: {str(e)}"
                logger.error(f"[UpdateService] {error_msg}")
                logger.error(traceback.format_exc())
                return {
                    'success': False,
                    'message': error_msg,
                    'updated_dates': [],
                    'failed_dates': []
                }
        
        except Exception as e:
            error_msg = f"更新大盤指數數據時發生異常: {str(e)}"
            logger.error(f"[UpdateService] {error_msg}")
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'message': error_msg,
                'updated_dates': [],
                'failed_dates': []
            }
    
    def update_industry(
        self, 
        start_date: str, 
        end_date: str
    ) -> Dict[str, Any]:
        """更新產業指數數據
        
        Args:
            start_date: 開始日期（YYYY-MM-DD）
            end_date: 結束日期（YYYY-MM-DD）
            
        Returns:
            dict: {
                'success': bool,
                'message': str,
                'updated_dates': list[str],
                'failed_dates': list[str]
            }
        """
        import subprocess
        import sys
        import logging
        import traceback
        import re
        
        logger = logging.getLogger(__name__)
        
        # ✅ 記錄輸入參數
        logger.info(
            f"[UpdateService] 開始更新產業指數數據: "
            f"start_date={start_date}, end_date={end_date}"
        )
        
        try:
            # 動態導入並調用 batch_update_industry_index 函數
            import importlib.util
            
            script_path = self.scripts_dir / 'batch_update_market_and_industry_index.py'
            logger.debug(f"[UpdateService] 更新腳本路徑: {script_path}")
            
            if not script_path.exists():
                error_msg = f'找不到更新腳本: {script_path}'
                logger.error(f"[UpdateService] {error_msg}")
                return {
                    'success': False,
                    'message': error_msg,
                    'updated_dates': [],
                    'failed_dates': []
                }
            
            # 動態導入模組
            try:
                spec = importlib.util.spec_from_file_location("batch_update_market_and_industry_index", script_path)
                if spec is None or spec.loader is None:
                    raise ImportError(f"無法創建模組規格: {script_path}")
                
                update_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(update_module)
                logger.debug(f"[UpdateService] 模組導入成功")
            except Exception as e:
                error_msg = f"導入更新模組時發生錯誤: {str(e)}"
                logger.error(f"[UpdateService] {error_msg}")
                logger.error(traceback.format_exc())
                return {
                    'success': False,
                    'message': error_msg,
                    'updated_dates': [],
                    'failed_dates': []
                }
            
            # 檢查函數是否存在
            if not hasattr(update_module, 'batch_update_industry_index'):
                error_msg = f"更新模組中找不到 batch_update_industry_index 函數"
                logger.error(f"[UpdateService] {error_msg}")
                return {
                    'success': False,
                    'message': error_msg,
                    'updated_dates': [],
                    'failed_dates': []
                }
            
            # 執行更新函數
            logger.info(f"[UpdateService] 開始執行產業指數更新函數")
            try:
                # ✅ 傳遞 config 給更新函數（如果它支持的話）
                import inspect
                update_func = update_module.batch_update_industry_index
                sig = inspect.signature(update_func)
                params = list(sig.parameters.keys())
                
                if 'config' in params:
                    logger.debug(f"[UpdateService] 更新函數支持 config 參數，傳遞配置")
                    result = update_func(start_date=start_date, end_date=end_date, config=self.config)
                else:
                    logger.debug(f"[UpdateService] 更新函數不支持 config 參數，使用默認參數")
                    result = update_func(start_date=start_date, end_date=end_date)
                logger.info(f"[UpdateService] 產業指數更新函數執行完成")
                
                # 解析結果（函數可能沒有返回值）
                if result is None:
                    # 函數沒有返回值，假設成功
                    return {
                        'success': True,
                        'message': '產業指數更新完成',
                        'updated_dates': [],
                        'failed_dates': []
                    }
                elif isinstance(result, dict):
                    return {
                        'success': result.get('success', True),
                        'message': result.get('message', '更新完成'),
                        'updated_dates': result.get('updated_dates', []),
                        'failed_dates': result.get('failed_dates', [])
                    }
                else:
                    # 如果返回的不是 dict，假設成功
                    return {
                        'success': True,
                        'message': '產業指數更新完成',
                        'updated_dates': [],
                        'failed_dates': []
                    }
            except Exception as e:
                error_msg = f"執行產業指數更新函數時發生錯誤: {str(e)}"
                logger.error(f"[UpdateService] {error_msg}")
                logger.error(traceback.format_exc())
                return {
                    'success': False,
                    'message': error_msg,
                    'updated_dates': [],
                    'failed_dates': []
                }
        
        except Exception as e:
            error_msg = f"更新產業指數數據時發生異常: {str(e)}"
            logger.error(f"[UpdateService] {error_msg}")
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'message': error_msg,
                'updated_dates': [],
                'failed_dates': []
            }
    
    def check_data_status(self) -> Dict[str, Any]:
        """檢查數據狀態
        
        Returns:
            dict: {
                'daily_data': {
                    'latest_date': str,
                    'total_records': int,
                    'status': str
                },
                'market_index': {
                    'latest_date': str,
                    'total_records': int,
                    'status': str
                },
                'industry_index': {
                    'latest_date': str,
                    'total_records': int,
                    'status': str
                }
            }
        """
        import pandas as pd
        from datetime import datetime
        import logging
        
        logger = logging.getLogger(__name__)
        
        # ✅ 記錄輸入
        logger.info("[UpdateService] 開始檢查數據狀態")
        
        result = {
            'daily_data': {
                'latest_date': None,
                'total_records': 0,
                'status': 'unknown'
            },
            'market_index': {
                'latest_date': None,
                'total_records': 0,
                'status': 'unknown'
            },
            'industry_index': {
                'latest_date': None,
                'total_records': 0,
                'status': 'unknown'
            }
        }
        
        # 檢查每日股票數據（stock_data_whole.csv）
        stock_file = self.config.stock_data_file
        logger.debug(f"[UpdateService] 檢查每日股票數據文件: {stock_file}")
        if stock_file.exists():
            try:
                # ✅ 記錄文件存在
                logger.debug(f"[UpdateService] 文件存在，開始讀取")
                
                # 計算總記錄數（高效方式：只計算行數，不讀取內容）
                with open(stock_file, 'r', encoding='utf-8-sig') as f:
                    total_records = sum(1 for _ in f) - 1  # 減去標題行
                result['daily_data']['total_records'] = total_records
                
                # ✅ 記錄記錄數
                logger.debug(f"[UpdateService] 每日股票數據總記錄數: {total_records:,}")
                
                # 讀取日期欄位來獲取最新日期
                # 對於大文件，只讀取日期欄位會快很多
                try:
                    # 先檢查是否有日期欄位
                    header_df = pd.read_csv(stock_file, encoding='utf-8-sig', nrows=0)
                    if '日期' not in header_df.columns:
                        result['daily_data']['status'] = 'ok'  # 文件存在但沒有日期欄位
                    else:
                        # 只讀取日期欄位（這樣會快很多，即使文件很大）
                        df_dates = pd.read_csv(
                            stock_file,
                            encoding='utf-8-sig',
                            on_bad_lines='skip',
                            engine='python',
                            usecols=['日期']
                        )
                        df_tail = df_dates
                except Exception as e:
                    # 如果只讀日期欄位失敗，嘗試讀取最後10000行
                    try:
                        if total_records > 10000:
                            # 跳過前面的行，只讀最後10000行
                            skip_rows = list(range(1, total_records - 10000 + 1))
                            df_tail = pd.read_csv(
                                stock_file,
                                encoding='utf-8-sig',
                                on_bad_lines='skip',
                                engine='python',
                                skiprows=skip_rows
                            )
                        else:
                            # 文件不大，直接讀取全部
                            df_tail = pd.read_csv(
                                stock_file,
                                encoding='utf-8-sig',
                                on_bad_lines='skip',
                                engine='python'
                            )
                    except:
                        df_tail = pd.DataFrame()
                
                if '日期' in df_tail.columns and len(df_tail) > 0:
                    # 處理日期欄位
                    df_tail['日期'] = df_tail['日期'].astype(str)
                    valid_dates = df_tail[df_tail['日期'].notna() & (df_tail['日期'] != 'nan') & (df_tail['日期'] != '')]['日期']
                    if len(valid_dates) > 0:
                        # 日期格式可能是 YYYYMMDD，需要轉換
                        latest_date_str = valid_dates.max()
                        try:
                            # 嘗試解析日期
                            if len(latest_date_str) == 8 and latest_date_str.isdigit():
                                # YYYYMMDD 格式
                                latest_date = datetime.strptime(latest_date_str, '%Y%m%d').strftime('%Y-%m-%d')
                            else:
                                # 嘗試其他格式
                                latest_date = pd.to_datetime(latest_date_str, errors='coerce')
                                if pd.notna(latest_date):
                                    latest_date = latest_date.strftime('%Y-%m-%d')
                                else:
                                    latest_date = latest_date_str
                            result['daily_data']['latest_date'] = latest_date
                            result['daily_data']['status'] = 'ok'
                        except:
                            result['daily_data']['latest_date'] = latest_date_str
                            result['daily_data']['status'] = 'ok'
                    else:
                        result['daily_data']['status'] = 'ok'  # 文件存在但沒有有效日期
                else:
                    result['daily_data']['status'] = 'ok'  # 文件存在但沒有日期欄位
            except Exception as e:
                result['daily_data']['status'] = f'error: {str(e)}'
        
        # 檢查大盤指數數據
        market_file = self.config.market_index_file
        logger.debug(f"[UpdateService] 檢查大盤指數文件: {market_file}")
        if market_file.exists():
            try:
                df = pd.read_csv(
                    market_file, 
                    encoding='utf-8-sig', 
                    on_bad_lines='skip', 
                    engine='python'
                )
                result['market_index']['total_records'] = len(df)
                
                if '日期' in df.columns:
                    df['日期'] = df['日期'].astype(str)
                    valid_dates = df[df['日期'].notna() & (df['日期'] != 'nan') & (df['日期'] != '')]['日期']
                    if len(valid_dates) > 0:
                        latest_date = pd.to_datetime(valid_dates, errors='coerce').max()
                        if pd.notna(latest_date):
                            result['market_index']['latest_date'] = latest_date.strftime('%Y-%m-%d')
                            result['market_index']['status'] = 'ok'
                            logger.debug(f"[UpdateService] 大盤指數最新日期: {latest_date.strftime('%Y-%m-%d')}")
            except Exception as e:
                result['market_index']['status'] = f'error: {str(e)}'
                logger.warning(f"[UpdateService] 檢查大盤指數時發生錯誤: {str(e)}")
        else:
            logger.debug(f"[UpdateService] 大盤指數文件不存在: {market_file}")
        
        # 檢查產業指數數據
        industry_file = self.config.industry_index_file
        logger.debug(f"[UpdateService] 檢查產業指數文件: {industry_file}")
        if industry_file.exists():
            try:
                df = pd.read_csv(
                    industry_file, 
                    encoding='utf-8-sig', 
                    on_bad_lines='skip', 
                    engine='python'
                )
                result['industry_index']['total_records'] = len(df)
                
                if '日期' in df.columns:
                    df['日期'] = df['日期'].astype(str)
                    valid_dates = df[df['日期'].notna() & (df['日期'] != 'nan') & (df['日期'] != '')]['日期']
                    if len(valid_dates) > 0:
                        # 處理日期格式（可能是 YYYYMMDD 或其他格式）
                        parsed_dates = []
                        for date_str in valid_dates:
                            try:
                                # 嘗試 YYYYMMDD 格式
                                if len(date_str) == 8 and date_str.isdigit():
                                    parsed_date = datetime.strptime(date_str, '%Y%m%d')
                                else:
                                    # 嘗試其他格式
                                    parsed_date = pd.to_datetime(date_str, errors='coerce')
                                if pd.notna(parsed_date):
                                    parsed_dates.append(parsed_date)
                            except:
                                continue
                        
                        if parsed_dates:
                            latest_date = max(parsed_dates)
                            result['industry_index']['latest_date'] = latest_date.strftime('%Y-%m-%d')
                            result['industry_index']['status'] = 'ok'
                        else:
                            # 如果解析失敗，使用字符串比較（降級方案）
                            latest_date_str = valid_dates.max()
                            result['industry_index']['latest_date'] = latest_date_str
                            result['industry_index']['status'] = 'ok'
            except Exception as e:
                result['industry_index']['status'] = f'error: {str(e)}'
        
        return result
    
    def merge_daily_data(self, force_all: bool = False) -> Dict[str, Any]:
        """合併每日股票數據
        
        將 daily_price/ 目錄中的 CSV 文件合併到 stock_data_whole.csv
        
        Args:
            force_all: 是否強制重新合併所有數據（忽略現有數據）
        
        Returns:
            dict: {
                'success': bool,
                'message': str,
                'merged_files': int,
                'total_records': int
            }
        """
        import pandas as pd
        import shutil
        from datetime import datetime
        import logging
        import traceback
        
        logger = logging.getLogger(__name__)
        
        # ✅ 記錄輸入參數
        logger.info(
            f"[UpdateService] 開始合併每日股票數據: "
            f"force_all={force_all}"
        )
        
        try:
            # 直接調用 merge 腳本的函數
            import sys
            import importlib.util
            
            merge_script = self.project_root / 'scripts' / 'merge_daily_data.py'
            logger.debug(f"[UpdateService] 合併腳本路徑: {merge_script}")
            
            if not merge_script.exists():
                logger.error(f"[UpdateService] 找不到合併腳本: {merge_script}")
                return {
                    'success': False,
                    'message': f'找不到合併腳本: {merge_script}',
                    'merged_files': 0,
                    'total_records': 0
                }
            
            # 動態導入 merge 函數
            logger.debug(f"[UpdateService] 開始動態導入合併模組")
            try:
                spec = importlib.util.spec_from_file_location("merge_daily_data", merge_script)
                if spec is None or spec.loader is None:
                    error_msg = f"無法創建模組規格: {merge_script}"
                    logger.error(f"[UpdateService] {error_msg}")
                    return {
                        'success': False,
                        'message': error_msg,
                        'merged_files': 0,
                        'total_records': 0
                    }
                
                merge_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(merge_module)
                logger.debug(f"[UpdateService] 模組導入成功")
            except Exception as e:
                error_msg = f"導入合併模組時發生錯誤: {str(e)}"
                logger.error(f"[UpdateService] {error_msg}")
                logger.error(traceback.format_exc())
                return {
                    'success': False,
                    'message': error_msg,
                    'merged_files': 0,
                    'total_records': 0
                }
            
            # 檢查函數是否存在
            if not hasattr(merge_module, 'merge_daily_data'):
                error_msg = f"合併模組中找不到 merge_daily_data 函數"
                logger.error(f"[UpdateService] {error_msg}")
                return {
                    'success': False,
                    'message': error_msg,
                    'merged_files': 0,
                    'total_records': 0
                }
            
            # 執行合併函數（傳遞 force_all 參數）
            logger.info(f"[UpdateService] 開始執行合併函數: force_all={force_all}")
            try:
                # ✅ 傳遞 config 給合併函數（如果它支持的話）
                # 先嘗試傳遞 config，如果不支持則只傳 force_all
                import inspect
                merge_func = merge_module.merge_daily_data
                sig = inspect.signature(merge_func)
                params = list(sig.parameters.keys())
                
                if 'config' in params:
                    logger.debug(f"[UpdateService] 合併函數支持 config 參數，傳遞配置")
                    merge_func(force_all=force_all, config=self.config)
                else:
                    logger.debug(f"[UpdateService] 合併函數不支持 config 參數，只傳遞 force_all")
                    merge_func(force_all=force_all)
                
                logger.info(f"[UpdateService] 合併函數執行完成")
            except Exception as e:
                error_msg = f"執行合併函數時發生錯誤: {str(e)}"
                logger.error(f"[UpdateService] {error_msg}")
                logger.error(traceback.format_exc())
                return {
                    'success': False,
                    'message': error_msg,
                    'merged_files': 0,
                    'total_records': 0
                }
            
            # 讀取合併後的數據統計
            stock_file = self.config.stock_data_file
            if stock_file.exists():
                # 計算總記錄數（使用更高效的方式）
                try:
                    df = pd.read_csv(stock_file, encoding='utf-8-sig', nrows=1000)
                    # 讀取文件總行數
                    with open(stock_file, 'r', encoding='utf-8-sig') as f:
                        total_records = sum(1 for _ in f) - 1  # 減去標題行
                    
                    # 獲取最新日期（讀取文件最後幾行，因為最新日期通常在文件末尾）
                    if '日期' in df.columns:
                        try:
                            # 方法1：讀取最後 10000 行來獲取最新日期
                            # 先獲取總行數
                            with open(stock_file, 'r', encoding='utf-8-sig') as f:
                                total_lines = sum(1 for _ in f) - 1  # 減去標題行
                            
                            if total_lines > 0:
                                # 讀取最後 10000 行（或全部，如果總行數少於 10000）
                                skip_rows = max(0, total_lines - 10000)
                                df_tail = pd.read_csv(
                                    stock_file, 
                                    encoding='utf-8-sig', 
                                    usecols=['日期'],
                                    skiprows=range(1, skip_rows + 1)  # 跳過前面的行，保留標題行
                                )
                                
                                if len(df_tail) > 0:
                                    # 轉換日期格式
                                    df_tail['日期'] = df_tail['日期'].astype(str)
                                    valid_dates = df_tail[
                                        df_tail['日期'].notna() & 
                                        (df_tail['日期'] != 'nan') & 
                                        (df_tail['日期'] != '') &
                                        (df_tail['日期'] != 'None')
                                    ]['日期']
                                    
                                    if len(valid_dates) > 0:
                                        # 嘗試解析日期並找到最大值
                                        parsed_dates = []
                                        for date_str in valid_dates:
                                            try:
                                                # 嘗試 YYYYMMDD 格式
                                                if len(date_str) == 8 and date_str.isdigit():
                                                    parsed_dates.append(datetime.strptime(date_str, '%Y%m%d'))
                                                # 嘗試 YYYY-MM-DD 格式
                                                elif len(date_str) == 10 and '-' in date_str:
                                                    parsed_dates.append(datetime.strptime(date_str, '%Y-%m-%d'))
                                                else:
                                                    # 嘗試自動解析
                                                    parsed = pd.to_datetime(date_str, errors='coerce')
                                                    if pd.notna(parsed):
                                                        parsed_dates.append(parsed.to_pydatetime())
                                            except:
                                                continue
                                        
                                        if parsed_dates:
                                            latest_date = max(parsed_dates).strftime('%Y-%m-%d')
                                            message = f'數據合併成功，最新日期：{latest_date}'
                                        else:
                                            # 如果解析失敗，使用字符串比較（降級方案）
                                            latest_date_str = valid_dates.max()
                                            if len(latest_date_str) == 8 and latest_date_str.isdigit():
                                                latest_date = datetime.strptime(latest_date_str, '%Y%m%d').strftime('%Y-%m-%d')
                                            else:
                                                latest_date = latest_date_str
                                            message = f'數據合併成功，最新日期：{latest_date}'
                                    else:
                                        message = '數據合併成功'
                                else:
                                    message = '數據合併成功'
                            else:
                                message = '數據合併成功'
                        except Exception as e:
                            logger.warning(f"[UpdateService] 讀取最新日期時出錯: {str(e)}")
                            message = '數據合併成功'
                    else:
                        message = '數據合併成功'
                    
                    # ✅ 記錄結果
                    logger.info(
                        f"[UpdateService] 合併完成: "
                        f"總記錄數={total_records:,}, 訊息={message}"
                    )
                    return {
                        'success': True,
                        'message': message,
                        'merged_files': 0,  # merge 函數內部會處理，這裡不統計
                        'total_records': total_records
                    }
                except Exception as e:
                    logger.warning(f"[UpdateService] 讀取統計信息時出錯: {str(e)}")
                    return {
                        'success': True,
                        'message': f'數據合併完成（讀取統計信息時出錯：{str(e)}）',
                        'merged_files': 0,
                        'total_records': 0
                    }
            else:
                logger.error(f"[UpdateService] 合併完成但找不到輸出文件: {stock_file}")
                return {
                    'success': False,
                    'message': '合併完成但找不到輸出文件',
                    'merged_files': 0,
                    'total_records': 0
                }
                
        except Exception as e:
            import traceback
            logger.error(f"[UpdateService] 合併過程出錯: {str(e)}")
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'message': f'合併過程出錯：{str(e)}\n{traceback.format_exc()}',
                'merged_files': 0,
                'total_records': 0
            }
    
    def update_broker_branch(
        self,
        start_date: str,
        end_date: str,
        branch_system_keys: Optional[List[str]] = None,
        delay_seconds: float = 4.0,
        force_all: bool = False
    ) -> Dict[str, Any]:
        """更新券商分點資料
        
        Args:
            start_date: 開始日期（YYYY-MM-DD）
            end_date: 結束日期（YYYY-MM-DD）
            branch_system_keys: 要更新的分點列表（None=全部）
            delay_seconds: 請求間隔（秒）
            force_all: 是否強制重新抓取
            
        Returns:
            dict: 更新結果
        """
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(
            f"[UpdateService] 開始更新券商分點資料: "
            f"start_date={start_date}, end_date={end_date}, "
            f"branch_system_keys={branch_system_keys}, force_all={force_all}"
        )
        
        try:
            from app_module.broker_branch_update_service import BrokerBranchUpdateService
            
            service = BrokerBranchUpdateService(self.config)
            result = service.update_broker_branch_data(
                start_date=start_date,
                end_date=end_date,
                branch_system_keys=branch_system_keys,
                delay_seconds=delay_seconds,
                force_all=force_all
            )
            
            logger.info(f"[UpdateService] 券商分點資料更新完成: success={result.get('success', False)}")
            return result
            
        except Exception as e:
            import traceback
            error_msg = f"更新券商分點資料時發生錯誤: {str(e)}"
            logger.error(f"[UpdateService] {error_msg}")
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'message': error_msg,
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
        force_all: bool = False
    ) -> Dict[str, Any]:
        """合併券商分點資料
        
        Args:
            branch_system_keys: 要合併的分點列表（None=全部）
            force_all: 是否強制重新合併
            
        Returns:
            dict: 合併結果
        """
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(
            f"[UpdateService] 開始合併券商分點資料: "
            f"branch_system_keys={branch_system_keys}, force_all={force_all}"
        )
        
        try:
            from app_module.broker_branch_update_service import BrokerBranchUpdateService
            
            service = BrokerBranchUpdateService(self.config)
            result = service.merge_broker_branch_data(
                branch_system_keys=branch_system_keys,
                force_all=force_all
            )
            
            logger.info(f"[UpdateService] 券商分點資料合併完成: success={result.get('success', False)}")
            return result
            
        except Exception as e:
            import traceback
            error_msg = f"合併券商分點資料時發生錯誤: {str(e)}"
            logger.error(f"[UpdateService] {error_msg}")
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'message': error_msg,
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
        """檢查券商分點資料狀態
        
        Args:
            branch_system_keys: 要檢查的分點列表（None=全部）
            
        Returns:
            dict: 狀態字典
        """
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"[UpdateService] 檢查券商分點資料狀態: branch_system_keys={branch_system_keys}")
        
        try:
            from app_module.broker_branch_update_service import BrokerBranchUpdateService
            
            service = BrokerBranchUpdateService(self.config)
            result = service.check_broker_branch_data_status(
                branch_system_keys=branch_system_keys
            )
            
            logger.info(f"[UpdateService] 券商分點資料狀態檢查完成: status={result.get('status', 'unknown')}")
            return result
            
        except Exception as e:
            import traceback
            error_msg = f"檢查券商分點資料狀態時發生錯誤: {str(e)}"
            logger.error(f"[UpdateService] {error_msg}")
            logger.error(traceback.format_exc())
            return {
                'latest_date': None,
                'total_records': 0,
                'date_count': 0,
                'broker_count': 0,
                'date_range': {'start_date': None, 'end_date': None},
                'status': 'error'
            }
    
    def calculate_technical_indicators(
        self,
        target_stock: Optional[str] = None,
        force_all: bool = False,
        start_date: Optional[str] = None,
        progress_callback=None,
        ignore_existing_files: bool = False
    ) -> Dict[str, Any]:
        """計算技術指標
        
        Args:
            target_stock: 要處理的特定股票代號，如為None則處理所有股票
            force_all: 是否強制更新所有數據（忽略日期檢查）
            start_date: 指定開始更新的日期，如為None則自動檢測
            progress_callback: 進度回調函數 (message: str, progress: int) -> None
            ignore_existing_files: 是否忽略現有指標文件，直接覆蓋（用於修復有問題的文件）
            
        Returns:
            dict: {
                'success': bool,
                'message': str,
                'total_stocks': int,
                'success_count': int,
                'fail_count': int,
                'insufficient_data_count': int,
                'updated_stocks': list[str],
                'failed_stocks': list[str],
                'start_date': str,
                'end_date': str
            }
        """
        import sys
        import importlib.util
        import logging
        import traceback
        
        logger = logging.getLogger(__name__)
        
        logger.info(
            f"[UpdateService] 開始計算技術指標: "
            f"target_stock={target_stock}, force_all={force_all}, start_date={start_date}"
        )
        
        if progress_callback:
            progress_callback("初始化技術指標計算器...", 5)
        
        try:
            # 導入技術指標計算模組
            from analysis_module.technical_analysis.technical_indicators import TechnicalIndicatorCalculator
            
            # 創建計算器
            calculator = TechnicalIndicatorCalculator(logger)
            
            if progress_callback:
                progress_callback("讀取股票數據...", 10)
            
            # 讀取股票數據
            import pandas as pd
            stock_data = pd.read_csv(
                self.config.stock_data_file,
                dtype={'證券代號': str},
                low_memory=False
            )
            
            # 只保留正常股票（一般為4位數）
            stock_data = stock_data[stock_data['證券代號'].str.match(r'^\d{4}$')]
            
            # 如果指定了特定股票，只處理該股票
            if target_stock:
                if target_stock not in stock_data['證券代號'].unique():
                    return {
                        'success': False,
                        'message': f'指定的股票 {target_stock} 不存在於股票數據中',
                        'total_stocks': 0,
                        'success_count': 0,
                        'fail_count': 1,
                        'insufficient_data_count': 0,
                        'updated_stocks': [],
                        'failed_stocks': [target_stock],
                        'start_date': '',
                        'end_date': ''
                    }
                stock_data = stock_data[stock_data['證券代號'] == target_stock]
            
            # 檢測起始日期（如果不是強制全部）
            if not force_all and start_date is None:
                # 檢測最新的技術指標日期
                tech_files = list(self.config.technical_dir.glob('*_indicators.csv'))
                detected_start_date = None
                
                if tech_files:
                    # 從前5個文件中抽樣查找最新日期
                    sample_files = tech_files[:5]
                    dates = []
                    
                    for file in sample_files:
                        try:
                            df_sample = pd.read_csv(file)
                            if '日期' in df_sample.columns and not df_sample['日期'].empty:
                                date_col = df_sample['日期']
                                if not pd.api.types.is_string_dtype(date_col):
                                    date_col = date_col.astype(str)
                                dates.append(date_col.max())
                        except Exception:
                            continue
                    
                    if dates:
                        detected_start_date = max(dates)
                        logger.info(f"檢測到最新指標日期: {detected_start_date}")
                
                if detected_start_date:
                    start_date = detected_start_date
                    logger.info(f"將從此日期後開始更新: {start_date}")
                    if progress_callback:
                        progress_callback(f"檢測到最新指標日期: {start_date}", 15)
                else:
                    start_date = None
                    logger.info("未檢測到現有指標文件，將進行全量更新")
                    if progress_callback:
                        progress_callback("未檢測到現有指標文件，將進行全量更新", 15)
            elif force_all:
                start_date = None
                logger.info("強制更新所有數據")
                if progress_callback:
                    progress_callback("強制更新所有數據", 15)
            
            # 批次處理
            grouped = stock_data.groupby('證券代號')
            total_stocks = len(grouped)
            
            if progress_callback:
                progress_callback(f"開始處理 {total_stocks} 支股票的技術指標...", 20)
            
            results = {
                'total_stocks': total_stocks,
                'success_count': 0,
                'fail_count': 0,
                'insufficient_data_count': 0,
                'updated_stocks': [],
                'failed_stocks': [],
                'insufficient_stocks': [],
                'start_date': '',
                'end_date': ''
            }
            
            all_data = []
            min_date = "9999-12-31"
            max_date = "1900-01-01"
            
            # 處理每檔股票
            for idx, (stock_id, group_df) in enumerate(grouped):
                progress = 20 + int((idx / total_stocks) * 70)  # 20% 到 90%
                if progress_callback:
                    progress_callback(f"處理 {stock_id} ({idx+1}/{total_stocks})...", progress)
                
                # 跳過數據量不足的股票
                if len(group_df) < self.config.min_data_days:
                    logger.debug(f"股票 {stock_id} 數據量不足，跳過")
                    results['insufficient_data_count'] += 1
                    results['insufficient_stocks'].append(stock_id)
                    continue
                
                # 記錄日期範圍
                if '日期' in group_df.columns:
                    group_min_date = str(group_df['日期'].min())
                    group_max_date = str(group_df['日期'].max())
                    min_date = min(min_date, group_min_date)
                    max_date = max(max_date, group_max_date)
                
                # 檢查是否需要更新（基於日期）
                if start_date and '日期' in group_df.columns and not force_all:
                    date_col = group_df['日期']
                    if not pd.api.types.is_string_dtype(date_col):
                        date_col = date_col.astype(str)
                    filtered_df = group_df[date_col > start_date]
                    if len(filtered_df) == 0:
                        logger.debug(f"股票 {stock_id} 沒有新數據需要更新")
                        continue
                    group_df = filtered_df
                
                # 計算並保存指標
                try:
                    result = calculator.calculate_and_store_indicators(
                        group_df,
                        stock_id,
                        output_dir=self.config.technical_dir,
                        ignore_existing=ignore_existing_files or force_all
                    )
                    
                    if isinstance(result, pd.DataFrame):
                        all_data.append(result)
                        results['success_count'] += 1
                        results['updated_stocks'].append(stock_id)
                        logger.debug(f"成功處理股票 {stock_id}")
                    else:
                        results['fail_count'] += 1
                        results['failed_stocks'].append(stock_id)
                        logger.warning(f"處理股票 {stock_id} 失敗")
                except Exception as e:
                    logger.error(f"處理股票 {stock_id} 時發生錯誤: {str(e)}")
                    results['fail_count'] += 1
                    results['failed_stocks'].append(stock_id)
            
            # 更新結果日期範圍
            results['start_date'] = min_date if min_date != "9999-12-31" else "未知"
            results['end_date'] = max_date if max_date != "1900-01-01" else "未知"
            
            # 合併並儲存所有結果
            if all_data:
                if progress_callback:
                    progress_callback("合併所有指標數據...", 90)
                
                logger.info("合併所有指標數據...")
                
                # ✅ 數據驗證：檢查每個 DataFrame 的完整性
                valid_data = []
                for idx, df in enumerate(all_data):
                    if df is None or len(df) == 0:
                        logger.warning(f"跳過空數據（索引 {idx}）")
                        continue
                    
                    # 檢查必要欄位
                    required_cols = ['日期', '證券代號']
                    missing_cols = [col for col in required_cols if col not in df.columns]
                    if missing_cols:
                        logger.warning(f"跳過缺少必要欄位 {missing_cols} 的數據（索引 {idx}）")
                        continue
                    
                    # 檢查日期欄位是否有效
                    if '日期' in df.columns:
                        date_col = pd.to_datetime(df['日期'], errors='coerce')
                        valid_dates = date_col.notna().sum()
                        if valid_dates == 0:
                            logger.warning(f"跳過日期欄位無效的數據（索引 {idx}）")
                            continue
                    
                    valid_data.append(df)
                
                if not valid_data:
                    logger.error("沒有有效的數據可以合併！")
                    return {
                        'success': False,
                        'message': '沒有有效的數據可以合併，請檢查技術指標計算結果',
                        **results
                    }
                
                # 合併有效數據
                final_df = pd.concat(valid_data, ignore_index=True)
                
                # ✅ 數據驗證：檢查合併後的數據
                logger.info(f"合併前有效數據數量: {len(valid_data)}")
                logger.info(f"合併後總筆數: {len(final_df):,}")
                logger.info(f"合併後股票數量: {final_df['證券代號'].nunique() if '證券代號' in final_df.columns else 'N/A'}")
                
                # 檢查是否有重複數據
                if '日期' in final_df.columns and '證券代號' in final_df.columns:
                    duplicates = final_df.duplicated(subset=['日期', '證券代號']).sum()
                    if duplicates > 0:
                        logger.warning(f"發現 {duplicates} 筆重複數據（日期+證券代號），將去重")
                        final_df = final_df.drop_duplicates(subset=['日期', '證券代號'], keep='last')
                        logger.info(f"去重後總筆數: {len(final_df):,}")
                
                save_path = self.config.all_stocks_data_file
                
                # 創建備份
                if save_path.exists():
                    logger.info(f"備份現有的整合指標文件: {save_path}")
                    self.config.create_backup(save_path)
                
                # 保存
                final_df.to_csv(save_path, index=False, encoding='utf-8-sig')
                file_size_mb = save_path.stat().st_size / 1024 / 1024
                logger.info(f"已保存整合指標到: {save_path}（檔案大小: {file_size_mb:.2f} MB）")
                
                if progress_callback:
                    progress_callback("技術指標計算完成", 100)
            
            # 生成結果訊息
            message = (
                f"技術指標計算完成：\n"
                f"總處理股票數: {results['total_stocks']}\n"
                f"成功處理數: {results['success_count']}\n"
                f"失敗數: {results['fail_count']}\n"
                f"數據不足股票數: {results['insufficient_data_count']}\n"
                f"處理數據日期範圍: {results['start_date']} 至 {results['end_date']}"
            )
            
            return {
                'success': True,
                'message': message,
                **results
            }
            
        except Exception as e:
            error_msg = f"計算技術指標時發生錯誤: {str(e)}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'message': f"{error_msg}\n{traceback.format_exc()}",
                'total_stocks': 0,
                'success_count': 0,
                'fail_count': 0,
                'insufficient_data_count': 0,
                'updated_stocks': [],
                'failed_stocks': [],
                'start_date': '',
                'end_date': ''
            }

