"""
數據更新服務 (Update Service)
提供數據更新的業務邏輯
"""

import subprocess
import os
import sys
from pathlib import Path
from typing import Dict ,Any ,Optional ,List ,Callable
from datetime import datetime ,timedelta

import app_module.update_data_normalization as update_data_normalization
from app_module.update_service_status_support import compose_sqlite_status_read_model
from app_module.update_daily_output import parse_daily_update_output
from app_module.sqlite_read_only import ReadOnlySQLiteManager
from data_module.market_data_integrity import (
is_valid_daily_price_frame ,
is_weekend_date_key ,
normalize_market_index_frame ,
official_twse_session_exists ,
)
from data_module.phase3c_backfill_runner import configured_candidate_db_path
from data_module.monthly_revenue_snapshot_selection import (
    inspect_monthly_revenue_snapshot,
    select_latest_monthly_revenue_snapshot,
)
from data_module.monthly_revenue_availability_candidate import (
    inspect_monthly_revenue_availability_candidate,
)


def _monthly_revenue_status_today() -> str:
    """回傳月營收可得性狀態使用的本機日期。"""
    return datetime.now().date().isoformat()


def _emit_update_progress(
    callback: Optional[Callable[[str, int], None]],
    message: str,
    percentage: int,
) -> None:
    """將下載觀測回傳給 UI；callback 失敗不得改變資料更新結果。"""
    if callback is None:
        return
    try:
        callback(message, max(0, min(100, int(percentage))))
    except Exception:
        # 進度是觀測邊界，不應因 UI／Qt callback 例外中止背景更新。
        return


def _is_cancel_requested(callback: Optional[Callable[[], bool]]) -> bool:
    """安全讀取合作式取消旗標；取消觀測失敗不應破壞資料更新。"""
    if callback is None:
        return False
    try:
        return bool(callback())
    except Exception:
        return False


class UpdateService :
    """數據更新服務類"""

    def __init__ (
        self,
        config,
        *,
        monthly_revenue_availability_candidate_path: Optional[str | Path] = None,
    ):
        """初始化數據更新服務

        Args:
            config: TWStockConfig 實例
        """
        self .config =config
        self .project_root =Path (__file__ ).parent .parent
        self .scripts_dir =self .project_root /'scripts'
        self .status_manifest_file =self .config .meta_data_dir /'data_status_manifest.json'
        self .monthly_revenue_source_version ="mops-static-snapshot-monthly-revenue-2026-06-16"
        configured_candidate = (
            monthly_revenue_availability_candidate_path
            if monthly_revenue_availability_candidate_path is not None
            else os.environ.get("MONTHLY_REVENUE_AVAILABILITY_CANDIDATE")
        )
        self.monthly_revenue_availability_candidate_path = (
            Path(configured_candidate).expanduser().resolve()
            if configured_candidate
            else None
        )

    def dry_run_mops_monthly_revenue_backfill (
    self ,
    snapshot_file :Optional [Path ]=None ,
    availability_file :Optional [Path ]=None ,
    source_version :Optional [str ]=None ,
    )->Dict [str ,Any ]:
        """Plan MOPS snapshot monthly revenue backfill without writing SQLite."""
        try :
            from data_module .monthly_revenue_backfill import plan_mops_snapshot_monthly_revenue_backfill

            snapshot_path =self ._resolve_monthly_revenue_snapshot_file (snapshot_file )
            availability_path =Path (availability_file or self .config .monthly_revenue_availability_file )
            version =source_version or self .monthly_revenue_source_version
            plan =plan_mops_snapshot_monthly_revenue_backfill (
            snapshot_file =snapshot_path ,
            availability_file =availability_path ,
            source_version =version ,
            )
            diagnostic_payloads =[diagnostic .to_dict ()for diagnostic in plan .diagnostics ]
            return {
            'success':plan .ready_for_apply ,
            'ready_for_apply':plan .ready_for_apply ,
            'raw_row_count':plan .raw_row_count ,
            'normalized_record_count':len (plan .records ),
            'diagnostic_count':len (plan .diagnostics ),
            'diagnostics':diagnostic_payloads ,
            'snapshot_file':str (snapshot_path ),
            'availability_file':str (availability_path ),
            'source_version':version ,
            'message':(
            f"MOPS 月營收 dry-run 完成：normalized={len(plan.records):,}, diagnostics={len(plan.diagnostics):,}"
            ),
            }
        except Exception as exc :
            return {
            'success':False ,
            'ready_for_apply':False ,
            'raw_row_count':0 ,
            'normalized_record_count':0 ,
            'diagnostic_count':1 ,
            'diagnostics':[{'code':'monthly_revenue.dry_run_error','message':str (exc )}],
            'message':f"MOPS 月營收 dry-run 失敗: {exc}",
            }

    def apply_mops_monthly_revenue_backfill (
    self ,
    snapshot_file :Optional [Path ]=None ,
    availability_file :Optional [Path ]=None ,
    source_version :Optional [str ]=None ,
    )->Dict [str ,Any ]:
        """Apply MOPS snapshot monthly revenue backfill into SQLite."""
        try :
            from data_module .monthly_revenue_backfill import apply_mops_snapshot_monthly_revenue_backfill

            snapshot_path =self ._resolve_monthly_revenue_snapshot_file (snapshot_file )
            availability_path =Path (availability_file or self .config .monthly_revenue_availability_file )
            version =source_version or self .monthly_revenue_source_version
            result =apply_mops_snapshot_monthly_revenue_backfill (
            db_file =self .config .db_file ,
            backup_dir =self .config .meta_data_dir /'backup',
            snapshot_file =snapshot_path ,
            availability_file =availability_path ,
            source_version =version ,
            )
            return {
            'success':result .applied ,
            'applied':result .applied ,
            'inserted_count':result .inserted_count ,
            'ready_for_apply':result .plan .ready_for_apply ,
            'raw_row_count':result .plan .raw_row_count ,
            'normalized_record_count':len (result .plan .records ),
            'diagnostic_count':len (result .plan .diagnostics ),
            'backup_file':str (result .backup_file )if result .backup_file else None ,
            'snapshot_file':str (snapshot_path ),
            'availability_file':str (availability_path ),
            'source_version':version ,
            'message':(
            f"MOPS 月營收已寫入 SQLite：inserted={result.inserted_count:,}"
            if result .applied
            else f"MOPS 月營收未寫入：diagnostics={len(result.plan.diagnostics):,}"
            ),
            }
        except Exception as exc :
            return {
            'success':False ,
            'applied':False ,
            'inserted_count':0 ,
            'message':f"MOPS 月營收寫入失敗: {exc}",
            }

    def _resolve_monthly_revenue_snapshot_file (self ,snapshot_file :Optional [Path ])->Path :
        if snapshot_file :
            path =Path (snapshot_file )
            if not path .exists ():
                raise FileNotFoundError (f"MOPS snapshot 不存在: {path}")
            return path

        snapshot_dir =self .config .output_root /'monthly_revenue_mops_snapshots'
        selected = select_latest_monthly_revenue_snapshot(snapshot_dir)
        if selected is None:
            raise FileNotFoundError (f"找不到 MOPS 月營收 snapshot CSV: {snapshot_dir}")
        return selected

    def sync_source_to_sqlite (
    self ,
    source :str ,
    start_date :Optional [str ]=None ,
    end_date :Optional [str ]=None ,
    cancel_callback :Optional [Callable [[],bool ]]=None ,
    )->Dict [str ,Any ]:
        """將既有 CSV 更新結果同步到 SQLite，保留日常 CSV 輸出行為。"""
        import logging

        logger =logging .getLogger (__name__ )
        if _is_cancel_requested(cancel_callback):
            return {
            'success':False ,
            'cancelled':True ,
            'message':f'{source} SQLite 同步已取消（尚未開始寫入）',
            'source':source ,
            'synced_records':0 ,
            }
        if not getattr (self .config ,'use_sqlite',False ):
            return {
            'success':True ,
            'message':'SQLite 未啟用，略過同步',
            'source':source ,
            'synced_records':0 ,
            'skipped':True ,
            }

        try :
            normalized ={
            'daily':'daily_data',
            'daily_data':'daily_data',
            'daily_price_files':'daily_price_files',
            'market':'market_index',
            'market_index':'market_index',
            'industry':'industry_index',
            'industry_index':'industry_index',
            'broker':'broker_branch',
            'broker_branch':'broker_branch',
            'broker_branch_files':'broker_branch_files',
            }.get (source )
            if normalized is None :
                return {
                'success':False ,
                'message':f'未知 SQLite 同步來源: {source}',
                'source':source ,
                'synced_records':0 ,
                }

            if normalized =='daily_price_files':
                df =self ._load_daily_price_files_for_sqlite (start_date ,end_date )
                table_name ='daily_prices'
                replace_table =False
                delete_date_keys =True
            elif normalized =='daily_data':
                df =self ._load_daily_data_for_sqlite ()
                table_name ='daily_prices'
                replace_table =False
                delete_date_keys =True
            elif normalized =='market_index':
                df =self ._load_csv_for_sqlite (self .config .market_index_file ,require_date =True )
                df =normalize_market_index_frame (df )if not df .empty else df
                table_name ='market_indices'
                replace_table =True
                delete_date_keys =False
            elif normalized =='industry_index':
                df =self ._load_csv_for_sqlite (self .config .industry_index_file ,require_date =True )
                table_name ='industry_indices'
                replace_table =True
                delete_date_keys =False
            elif normalized =='broker_branch_files':
                df =self ._load_broker_branch_files_for_sqlite (start_date ,end_date )
                table_name ='broker_flows'
                replace_table =False
                delete_date_keys =True
            else :
                df =self ._load_broker_branch_csv_for_sqlite ()
                table_name ='broker_flows'
                replace_table =True
                delete_date_keys =False

            if df .empty :
                return {
                'success':True ,
                'message':f'{source} 沒有可同步的 CSV 資料',
                'source':source ,
                'synced_records':0 ,
                }

            if _is_cancel_requested(cancel_callback):
                return {
                'success':False ,
                'cancelled':True ,
                'message':f'{source} SQLite 同步已取消（尚未開始寫入）',
                'source':source ,
                'table':table_name ,
                'synced_records':0 ,
                }

            from data_module .db_manager import DBManager

            db =DBManager (self .config )
            if table_name =='broker_flows':
                db .ensure_broker_flows_trade_type_primary_key ()
            if normalized =='daily_price_files':
                success =self ._upsert_sqlite_rows (db ,table_name ,df )
            elif replace_table :
                success =self ._replace_sqlite_table (db ,table_name ,df )
            elif delete_date_keys :
                success =self ._replace_sqlite_dates (db ,table_name ,df )
            else :
                success =db .write_dataframe (table_name ,df ,if_exists ='append')

            if not success :
                return {
                'success':False ,
                'message':f'{source} 同步 SQLite 失敗',
                'source':source ,
                'synced_records':0 ,
                }

            logger .info ("[UpdateService] %s 已同步 SQLite table %s，共 %s 筆",source ,table_name ,len (df ))
            return {
            'success':True ,
            'message':f'{source} 已同步 SQLite',
            'source':source ,
            'table':table_name ,
            'synced_records':int (len (df )),
            }
        except Exception as e :
            logger .exception ("[UpdateService] 同步 SQLite 失敗: source=%s",source )
            return {
            'success':False ,
            'message':f'{source} 同步 SQLite 時發生錯誤: {e}',
            'source':source ,
            'synced_records':0 ,
            }

    def _create_tpex_daily_price_source (self )->Any :
        from data_module .tpex_daily_price_source import TpexDailyPriceSource

        return TpexDailyPriceSource (self .config .tpex_daily_price_dir )

    def update_tpex_daily_price (
    self ,
    target_date :Optional [str ]=None ,
    start_date :Optional [str ]=None ,
    end_date :Optional [str ]=None ,
    )->Dict [str ,Any ]:
        """更新 TPEX 官方每日收盤行情 CSV。"""
        import logging

        logger =logging .getLogger (__name__ )
        try :
            effective_target =target_date
            if effective_target is None and start_date and end_date :
                date_keys =self ._iter_weekday_date_keys (start_date ,end_date )
                if not date_keys :
                    return {
                    'success':False ,
                    'message':'TPEX daily price request dates invalid: empty trading-date range',
                    'updated_dates':[],
                    'fallback_dates':[],
                    'failed_dates':[],
                    'tpex_rows':0 ,
                    'skipped_rows':0 ,
                    'diagnostic_count':1 ,
                    'source_date':None ,
                    'output_file':None ,
                    }
                effective_target =date_keys [-1 ]

            if effective_target is None :
                return {
                'success':False ,
                'message':'TPEX daily price requires target_date or start_date/end_date',
                'updated_dates':[],
                'fallback_dates':[],
                'failed_dates':[],
                'tpex_rows':0 ,
                'skipped_rows':0 ,
                'diagnostic_count':1 ,
                'source_date':None ,
                'output_file':None ,
                }

            effective_target =self ._date_key (effective_target )
            source =self ._create_tpex_daily_price_source ()
            result =source .update_for_date (effective_target )
            if result .success :
                logger .info (
                "[UpdateService] TPEX daily price saved: request=%s saved=%s rows=%s skipped=%s file=%s",
                effective_target ,
                result .source_date ,
                result .row_count ,
                result .skipped_count ,
                result .output_file ,
                )
                return {
                'success':True ,
                'message':result .message ,
                'updated_dates':[result .source_date or effective_target ]if result .source_date else [effective_target ],
                'fallback_dates':[result .source_date ]if result .source_date and result .source_date !=effective_target else [],
                'failed_dates':[],
                'tpex_rows':int (result .row_count ),
                'skipped_rows':int (result .skipped_count ),
                'diagnostic_count':int (result .diagnostic_count ),
                'source_date':result .source_date ,
                'output_file':str (result .output_file )if result .output_file else None ,
                }

            if result .source_date and result .source_date !=effective_target :
                fallback_result =source .update_for_date (result .source_date )
                if fallback_result .success :
                    logger .info (
                    "[UpdateService] TPEX fallback daily price saved: request=%s saved=%s rows=%s skipped=%s file=%s",
                    effective_target ,
                    fallback_result .source_date ,
                    fallback_result .row_count ,
                    fallback_result .skipped_count ,
                    fallback_result .output_file ,
                    )
                    return {
                    'success':True ,
                    'message':(
                    f"TPEX 回應日 {fallback_result.source_date} 已成功寫入，"
                    f"原請求日期 {effective_target} 無對應資料，已回退為回應日期"
                    ),
                    'updated_dates':[fallback_result .source_date ],
                    'fallback_dates':[fallback_result .source_date ],
                    'failed_dates':[],
                    'tpex_rows':int (fallback_result .row_count ),
                    'skipped_rows':int (fallback_result .skipped_count ),
                    'diagnostic_count':int (fallback_result .diagnostic_count ),
                    'source_date':fallback_result .source_date ,
                    'output_file':str (fallback_result .output_file )if fallback_result .output_file else None ,
                    }

            logger .warning ("[UpdateService] TPEX daily price update failed: %s",result .message )
            return {
            'success':False ,
            'message':result .message ,
            'updated_dates':[],
            'fallback_dates':[],
            'failed_dates':[effective_target ],
            'tpex_rows':0 ,
            'skipped_rows':0 ,
            'diagnostic_count':int (result .diagnostic_count ),
            'source_date':result .source_date ,
            'output_file':None ,
            }
        except Exception as exc :
            logger .exception ("[UpdateService] TPEX daily price update raised")
            return {
            'success':False ,
            'message':f'TPEX daily price update failed: {exc}',
            'updated_dates':[],
            'fallback_dates':[],
            'failed_dates':[self ._date_key (target_date )]if target_date else [],
            'tpex_rows':0 ,
            'skipped_rows':0 ,
            'diagnostic_count':1 ,
            'source_date':None ,
            'output_file':None ,
            }

    def update_tpex_daily_price_range(
        self,
        start_date: str,
        end_date: str,
        delay_seconds: float = 0.0,
        force_refresh: bool = False,
        sync_to_sqlite: bool = False,
        break_on_repeated_source_date: bool = True,
        twse_no_data_dates: Optional[list[str]] = None,
        progress_callback: Optional[Callable[[str, int], None]] = None,
        cancel_callback: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """逐日更新 TPEX 官方收盤行情，會記錄實際回應日並可選擇同步到 SQLite。"""
        import logging
        import time

        logger =logging .getLogger (__name__ )
        try :
            if _is_cancel_requested(cancel_callback):
                return {
                'success':False ,
                'cancelled':True ,
                'message':'TPEX 每日股價區間更新已取消（尚未開始）',
                'requested_dates':[],
                'updated_dates':[],
                'fallback_dates':[],
                'skipped_dates':[],
                'failed_dates':[],
                'warnings':[],
                'tpex_rows':0 ,
                'skipped_rows':0 ,
                'diagnostic_count':0 ,
                'source_dates':[],
                'sync_summary':None ,
                }
            date_keys =self ._iter_weekday_date_keys (start_date ,end_date )
            if not date_keys :
                return {
                'success':False ,
                'message':'TPEX daily price request dates invalid: empty trading-date range',
                'updated_dates':[],
                'fallback_dates':[],
                'skipped_dates':[],
                'failed_dates':[],
                'tpex_rows':0 ,
                'skipped_rows':0 ,
                'diagnostic_count':0 ,
                'source_dates':[],
                }

            source =self ._create_tpex_daily_price_source ()
            _emit_update_progress(
                progress_callback,
                f"TPEX API 準備下載 {len(date_keys)} 個工作日",
                0,
            )
            updated_dates :list [str ]=[]
            fallback_dates :list [str ]=[]
            skipped_dates :list [str ]=[]
            failed_dates :list [str ]=[]
            source_date_seen :set [str ]=set ()
            total_rows =0
            total_skipped_rows =0
            last_source_date :Optional [str ]=None

            def cancelled_result(message: str) -> Dict[str, Any]:
                return {
                'success':False ,
                'cancelled':True ,
                'message':message ,
                'requested_dates':date_keys ,
                'updated_dates':sorted (set (updated_dates )),
                'fallback_dates':sorted (set (fallback_dates )),
                'skipped_dates':sorted (set (skipped_dates )),
                'failed_dates':sorted (set (failed_dates )),
                'warnings':[],
                'tpex_rows':total_rows ,
                'skipped_rows':total_skipped_rows ,
                'diagnostic_count':0 ,
                'source_dates':sorted (set (updated_dates )),
                'sync_summary':None ,
                }

            def sleep_with_cancel(seconds: float) -> bool:
                """以短間隔等待，讓 UI 取消可在日期邊界前被觀察。"""
                if seconds <= 0:
                    return _is_cancel_requested(cancel_callback)
                if cancel_callback is None:
                    time.sleep(seconds)
                    return False
                deadline = time.monotonic() + seconds
                while True:
                    if _is_cancel_requested(cancel_callback):
                        return True
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return _is_cancel_requested(cancel_callback)
                    time.sleep(min(0.1, remaining))

            for idx ,requested_date in enumerate (date_keys ):
                if _is_cancel_requested(cancel_callback):
                    return cancelled_result(f"TPEX 每日股價區間更新已取消（停止於 {requested_date} 前）")
                current_percentage =((idx + 1 ) *100 )//len (date_keys )
                _emit_update_progress(
                    progress_callback,
                    f"TPEX API 下載 {requested_date}（{idx + 1}/{len(date_keys)}）",
                    current_percentage,
                )
                output_file =self .config .tpex_daily_price_dir /f'{requested_date}.csv'
                if not force_refresh and output_file .exists ():
                    skipped_dates .append (requested_date )
                    continue

                result =source .update_for_date (requested_date )
                effective_source_date =result .source_date or requested_date

                if _is_cancel_requested(cancel_callback):
                    return cancelled_result(f"TPEX 每日股價區間更新已取消（已完成 {requested_date}）")

                if result.success:
                    updated_dates.append(effective_source_date)
                    source_date_seen.add(effective_source_date)
                    total_rows += int(result.row_count)
                    if effective_source_date != requested_date:
                        fallback_dates.append(effective_source_date)
                else:
                    twse_skipped = False
                    if twse_no_data_dates:
                        normalized_twse = [self._date_key(d) for d in twse_no_data_dates]
                        twse_skipped = requested_date in normalized_twse

                    if twse_skipped:
                        logger.info(f"[UpdateService] TPEX 缺少 {requested_date} 資料，但 TWSE 已判定為查無資料（如颱風假），標記為 skipped")
                        skipped_dates.append(requested_date)
                    else:
                        failed_dates.append(requested_date)

                if result.source_date and result.source_date != requested_date:
                    fallback_dates .append (result .source_date )
                    if result .source_date not in source_date_seen :
                        fallback_result =source .update_for_date (result .source_date )
                        if _is_cancel_requested(cancel_callback):
                            return cancelled_result(
                                f"TPEX 每日股價區間更新已取消（停止於 fallback {result.source_date}）"
                            )
                        if fallback_result .success :
                            fallback_source_date =fallback_result .source_date or result .source_date
                            updated_dates .append (fallback_source_date )
                            source_date_seen .add (fallback_source_date )
                            total_rows +=int (fallback_result .row_count )
                            effective_source_date =fallback_source_date
                        else :
                            logger .warning (
                            "[UpdateService] TPEX fallback request failed: request=%s fallback=%s message=%s",
                            requested_date ,
                            result .source_date ,
                            fallback_result .message ,
                            )
                    else :
                        total_skipped_rows +=int (result .skipped_count )
                else :
                    total_skipped_rows +=int (result .skipped_count )

                    # 若同樣回應日反覆出現，表示 API 僅能回傳近期/最新日，後續日期會是重複資料
                if result .source_date :
                    if (
                    break_on_repeated_source_date
                    and effective_source_date ==last_source_date
                    and idx >0
                    ):
                        remaining =date_keys [idx +1 :]
                        skipped_dates .extend (remaining )
                        logger .info (
                        "[UpdateService] 偵測到 TPEX 重複回應日 %s，停止向前回補以避免重複下載：remaining=%s",
                        effective_source_date ,
                        len (remaining ),
                        )
                        break
                    last_source_date =effective_source_date

                if delay_seconds >0 and idx <len (date_keys )-1 :
                    if sleep_with_cancel(delay_seconds):
                        return cancelled_result("TPEX 每日股價區間更新已取消（等待下一日期前）")

            unique_updated_dates =sorted (set (updated_dates ))
            sync_summary =None
            if _is_cancel_requested(cancel_callback):
                return cancelled_result("TPEX 每日股價區間更新已取消（尚未同步 SQLite）")
            if sync_to_sqlite and unique_updated_dates :
                sync_start =unique_updated_dates [0 ]
                sync_end =unique_updated_dates [-1 ]
                sync_result =self .sync_source_to_sqlite (
                    "daily_price_files",
                    sync_start,
                    sync_end,
                    cancel_callback=cancel_callback,
                )
                sync_summary ={
                'success':sync_result .get ('success',False ),
                'synced_records':int (sync_result .get ('synced_records',0 )),
                'message':sync_result .get ('message',''),
                'source':sync_result .get ('source','daily_price_files'),
                'table':sync_result .get ('table','daily_prices'),
                }
                if sync_result.get('cancelled'):
                    return cancelled_result("TPEX 每日股價區間更新已取消（SQLite 同步前）")

            updated =len (unique_updated_dates )>0
            unique_failed_dates =sorted (set (failed_dates ))
            warnings =(
            [f"TPEX 每日股價缺少日期：{', '.join(unique_failed_dates)}"]
            if unique_failed_dates
            else []
            )
            has_any_local_data =updated or len (skipped_dates )>0
            _emit_update_progress(
                progress_callback,
                "TPEX API 下載完成，正在整理日期結果",
                100,
            )
            return {
            'success':has_any_local_data and not unique_failed_dates ,
            'message':(
            f"TPEX 每日股價區間更新未完整：缺少日期 {', '.join(unique_failed_dates)}"
            if unique_failed_dates
            else
            'TPEX 每日股價區間更新完成'
            if has_any_local_data
            else 'TPEX 每日股價區間更新失敗：無可寫入日期'
            ),
            'requested_dates':date_keys ,
            'updated_dates':unique_updated_dates ,
            'fallback_dates':sorted (set (fallback_dates )),
            'skipped_dates':sorted (set (skipped_dates )),
            'failed_dates':unique_failed_dates ,
            'warnings':warnings ,
            'tpex_rows':total_rows ,
            'skipped_rows':total_skipped_rows ,
            'diagnostic_count':0 ,
            'source_dates':unique_updated_dates ,
            'sync_summary':sync_summary ,
            }
        except Exception as exc :
            logger .exception ("[UpdateService] TPEX daily price range update failed")
            return {
            'success':False ,
            'message':f'TPEX daily price range update failed: {exc}',
            'requested_dates':[],
            'updated_dates':[],
            'fallback_dates':[],
            'skipped_dates':[],
            'failed_dates':[self ._date_key (start_date )],
            'warnings':[f"TPEX 每日股價缺少日期：{self ._date_key (start_date )}"],
            'tpex_rows':0 ,
            'skipped_rows':0 ,
            'diagnostic_count':1 ,
            'source_dates':[],
            'sync_summary':None ,
            }

    def _iter_weekday_date_keys (self ,start_date :str ,end_date :str )->list [str ]:
        return update_data_normalization .iter_weekday_date_keys (
        start_date ,end_date ,date_key_fn =self ._date_key
        )

    def _load_csv_for_sqlite (self ,path :Path ,require_date :bool =False )->Any :
        import pandas as pd # type: ignore[import-untyped]

        if not path .exists ():
            return pd .DataFrame ()
        df =pd .read_csv (path ,encoding ='utf-8-sig',dtype =self ._sqlite_csv_dtype (),low_memory =False )
        if df .empty :
            return df
        normalized =self ._normalize_sqlite_dates (df )
        if require_date and '日期'not in normalized .columns :
            return pd .DataFrame ()
        return normalized

    def _load_daily_price_files_for_sqlite (
    self ,
    start_date :Optional [str ],
    end_date :Optional [str ],
    )->Any :
        import pandas as pd # type: ignore[import-untyped]

        configured_dirs =[
        getattr (self .config ,'daily_price_dir',None ),
        getattr (self .config ,'tpex_daily_price_dir',None ),
        ]
        daily_dirs :list [Path ]=[]
        for configured_dir in configured_dirs :
            if configured_dir is None :
                continue
            daily_dir =Path (configured_dir )
            if daily_dir .exists ():
                daily_dirs .append (daily_dir )
        if not daily_dirs :
            return pd .DataFrame ()

        start_key =self ._date_key (start_date )if start_date else None
        end_key =self ._date_key (end_date )if end_date else None
        frames =[]
        for daily_dir in daily_dirs :
            for path in sorted (daily_dir .glob ('*.csv')):
                date_key =path .stem
                if start_key and date_key <start_key :
                    continue
                if end_key and date_key >end_key :
                    continue
                df =pd .read_csv (path ,encoding ='utf-8-sig',dtype =self ._sqlite_csv_dtype (),low_memory =False )
                if df .empty :
                    continue
                df =self ._normalize_sqlite_dates (df )
                if not is_valid_daily_price_frame (df ):
                    import logging
                    logging .getLogger (__name__ ).warning (
                    "[UpdateService] skip invalid daily-price CSV schema: %s",path
                    )
                    continue
                if is_weekend_date_key (date_key )and not official_twse_session_exists (date_key ):
                    import logging
                    logging .getLogger (__name__ ).warning (
                    "[UpdateService] daily-price session has no official TWSE evidence; skip file: %s",path
                    )
                    continue
                if '日期'not in df .columns :
                    df .insert (0 ,'日期',date_key )
                frames .append (df )

        if not frames :
            return pd .DataFrame ()
        return self ._normalize_sqlite_dates (pd .concat (frames ,ignore_index =True ))

    def _load_daily_data_for_sqlite (self )->Any :
        import pandas as pd # type: ignore[import-untyped]

        daily_df =self ._load_csv_for_sqlite (self .config .stock_data_file ,require_date =True )
        if daily_df .empty :
            return daily_df

        date_col ='日期'
        code_col ='證券代號'
        frames =[daily_df ]
        date_keys ={
        str (value ).strip ()
        for value in daily_df .get (date_col ,pd .Series (dtype =str )).dropna ().astype (str )
        if str (value ).strip ()
        }

        tpex_daily_dir =getattr (self .config ,'tpex_daily_price_dir',None )
        if tpex_daily_dir is not None :
            tpex_daily_dir =Path (tpex_daily_dir )
            if tpex_daily_dir .exists ()and date_keys :
                for path in sorted (tpex_daily_dir .glob ('*.csv')):
                    date_key =path .stem
                    if date_key not in date_keys :
                        continue
                    tpex_df =pd .read_csv (path ,encoding ='utf-8-sig',dtype =self ._sqlite_csv_dtype (),low_memory =False )
                    if tpex_df .empty :
                        continue
                    tpex_df =self ._normalize_sqlite_dates (tpex_df )
                    if date_col not in tpex_df .columns :
                        tpex_df .insert (0 ,date_col ,date_key )
                    frames .append (tpex_df )

        combined =self ._normalize_sqlite_dates (pd .concat (frames ,ignore_index =True ))
        if date_col in combined .columns and code_col in combined .columns :
            combined =combined .drop_duplicates (subset =[date_col ,code_col ],keep ='last')
        return combined

    def _get_stock_name_to_code_map (self )->Dict [str ,str ]:
        """建立證券名稱到證券代號的對照表，合併 SQLite, CSV 與硬編碼對照"""
        name_to_code ={}

        # 1. Fallback 硬編碼對照表 (兜底)
        fallback_map ={
        '元大台灣50':'0050',
        '元大高股息':'0056',
        '富邦科技':'0052',
        '元大MSCI金融':'0055',
        }
        name_to_code .update (fallback_map )

        # 2. 從 CSV 股票數據中讀取對照
        try :
            stock_data_file =getattr (self .config ,'stock_data_file',None )
            if stock_data_file and stock_data_file .exists ():
                import pandas as pd
                required_cols ={'證券代號','證券名稱'}
                df_csv =pd .read_csv (
                stock_data_file ,
                encoding ='utf-8-sig',
                usecols =lambda col :col in required_cols ,
                dtype ={'證券代號':str ,'證券名稱':str },
                low_memory =False ,
                )
                if '證券代號'in df_csv .columns and '證券名稱'in df_csv .columns :
                    csv_map =df_csv .dropna (subset =['證券代號','證券名稱']).drop_duplicates (subset =['證券名稱'],keep ='last')
                    for _ ,row in csv_map .iterrows ():
                        code =self ._stock_code_key (row ['證券代號'])
                        name =str (row ['證券名稱']).strip ()
                        if code and name and code not in ('ETF','UNKNOWN')and name :
                            name_to_code [name ]=code
        except Exception as e :
            import logging
            logging .getLogger (__name__ ).warning (f"[UpdateService] 從 CSV 建立股票代號映射失敗: {e}")

            # 3. 從 SQLite daily_prices 讀取對照 (最高優先順序，覆蓋前面)
        if getattr (self .config ,'use_sqlite',False ):
            try :
                from data_module .db_manager import DBManager
                db =DBManager (self .config )
                query ="SELECT DISTINCT 證券名稱, 證券代號 FROM daily_prices WHERE 證券名稱 IS NOT NULL AND 證券名稱 != '' AND 證券代號 NOT IN ('ETF', 'UNKNOWN');"
                df_prices =db .execute_query (query )
                for _ ,row in df_prices .iterrows ():
                    name =str (row ['證券名稱']).strip ()
                    code =str (row ['證券代號']).strip ()
                    if name and code :
                        name_to_code [name ]=code
            except Exception as e :
                import logging
                logging .getLogger (__name__ ).warning (f"[UpdateService] 從 SQLite daily_prices 建立股票代號映射失敗: {e}")

        return name_to_code

    def _load_broker_branch_csv_for_sqlite (self )->Any :
        import pandas as pd # type: ignore[import-untyped]

        broker_dir =getattr (self .config ,'broker_flow_dir',None )
        if broker_dir is None or not Path (broker_dir ).exists ():
            return pd .DataFrame ()

        frames =[]
        name_to_code_map =self ._get_stock_name_to_code_map ()
        for path in sorted (Path (broker_dir ).glob ('*/meta/merged.csv')):
            df =pd .read_csv (path ,encoding ='utf-8-sig')
            if df .empty :
                continue
            branch_name =path .parents [1 ].name
            rename_map ={
            'date':'日期',
            'counterparty_broker_code':'證券代號',
            'stock_id':'證券代號',
            'stock_code':'證券代號',
            'counterparty_broker_name':'證券名稱',
            'stock_name':'證券名稱',
            'branch_display_name':'分點名稱',
            'branch_name':'分點名稱',
            'buy_lots':'買進張數',
            'sell_lots':'賣出張數',
            'net_lots':'買賣超張數',
            'buy_amount_k_twd':'買進金額千元',
            'sell_amount_k_twd':'賣出金額千元',
            'net_amount_k_twd':'買賣超金額千元',
            # 2026-06-11 前的 MoneyDJ c=B 資料使用 generic qty 名稱。
            'buy_qty':'買進金額千元',
            'sell_qty':'賣出金額千元',
            'net_qty':'買賣超金額千元',
            }
            df =df .rename (columns ={k :v for k ,v in rename_map .items ()if k in df .columns })
            if '證券代號'in df .columns and '證券名稱'in df .columns :
                df ['證券代號']=df ['證券代號'].astype (str ).str .strip ()
                mask =df ['證券代號'].isin (['ETF','UNKNOWN'])
                if mask .any ():
                    mapped =df .loc [mask ,'證券名稱'].astype (str ).str .strip ().map (name_to_code_map )
                    unmapped =df .loc [mask &mapped .isna (),'證券名稱'].unique ()
                    if len (unmapped )>0 :
                        import logging
                        logging .getLogger (__name__ ).warning (f"[UpdateService] Historical ETF repair found unmapped stock name: {unmapped.tolist()}")
                    df .loc [mask ,'證券代號']=mapped .fillna (df .loc [mask ,'證券代號'])
            if '分點名稱'not in df .columns :
                df ['分點名稱']=branch_name
            frames .append (df )

        if not frames :
            return pd .DataFrame ()
        df_all =pd .concat (frames ,ignore_index =True )
        lot_cols =['買進張數','賣出張數','買賣超張數']
        amount_cols =['買進金額千元','賣出金額千元','買賣超金額千元']

        # 確保 metadata 欄位存在
        metadata_cols =['trade_type','lots_observed','amount_observed','lots_rank','amount_rank']
        for col in metadata_cols :
            if col not in df_all .columns :
                if col =='trade_type':
                    df_all [col ]=None
                elif col =='lots_observed':
                    if 'buy_lots'in df_all .columns :
                        df_all [col ]=df_all ['buy_lots'].notna ()
                    elif '買進張數'in df_all .columns :
                        df_all [col ]=df_all ['買進張數'].notna ()
                    else :
                        df_all [col ]=False
                elif col =='amount_observed':
                    if 'buy_amount_k_twd'in df_all .columns :
                        df_all [col ]=df_all ['buy_amount_k_twd'].notna ()
                    elif '買進金額千元'in df_all .columns :
                        df_all [col ]=df_all ['買進金額千元'].notna ()
                    else :
                        df_all [col ]=False
                else :
                    df_all [col ]=None

                    # 轉換為 Nullable Integer (Int64)
        for col in lot_cols +amount_cols :
            if col in df_all .columns :
                df_all [col ]=pd .to_numeric (df_all [col ],errors ='coerce').astype ('Int64')
            else :
                df_all [col ]=pd .Series ([None ]*len (df_all ),dtype ='Int64')
        df_all =self ._infer_broker_metric_ranks (df_all )

        # 計算股數：只由 observed lots 轉換，非 observed 則保持 <NA>
        df_all ['買進股數']=pd .Series ([None ]*len (df_all ),dtype ='Int64')
        df_all ['賣出股數']=pd .Series ([None ]*len (df_all ),dtype ='Int64')
        df_all ['買賣超股數']=pd .Series ([None ]*len (df_all ),dtype ='Int64')

        lots_mask =df_all ['lots_observed']==True
        df_all .loc [lots_mask ,'買進股數']=df_all .loc [lots_mask ,'買進張數']*1000
        df_all .loc [lots_mask ,'賣出股數']=df_all .loc [lots_mask ,'賣出張數']*1000
        df_all .loc [lots_mask ,'買賣超股數']=df_all .loc [lots_mask ,'買賣超張數']*1000

        # 將非 observed amount 的欄位設為 <NA>
        amount_mask =df_all ['amount_observed']==False
        df_all .loc [amount_mask ,'買進金額千元']=None
        df_all .loc [amount_mask ,'賣出金額千元']=None
        df_all .loc [amount_mask ,'買賣超金額千元']=None

        keep_cols =[
        '日期','分點名稱','證券代號','證券名稱',
        '買進股數','賣出股數','買賣超股數',
        *amount_cols ,
        *metadata_cols
        ]
        for col in keep_cols :
            if col not in df_all .columns :
                df_all [col ]=None
        df_all =df_all [keep_cols ]

        normalized =self ._normalize_sqlite_dates (df_all )
        return self ._deduplicate_and_merge_broker_flows (normalized )

    def _load_broker_branch_files_for_sqlite (
    self ,
    start_date :Optional [str ],
    end_date :Optional [str ]
    )->Any :
        import pandas as pd # type: ignore[import-untyped]

        broker_dir =getattr (self .config ,'broker_flow_dir',None )
        if broker_dir is None or not Path (broker_dir ).exists ():
            return pd .DataFrame ()

        start_key =self ._date_key (start_date )if start_date else None
        end_key =self ._date_key (end_date )if end_date else None
        frames =[]
        name_to_code_map =self ._get_stock_name_to_code_map ()

        # 遍歷所有券商分點的目錄
        for branch_dir in sorted (Path (broker_dir ).glob ('*')):
            if not branch_dir .is_dir ()or branch_dir .name in {'meta','logs'}:
                continue
            daily_dir =branch_dir /'daily'
            if not daily_dir .exists ():
                continue

                # 遍歷該分點的每日 CSV 檔
            for path in sorted (daily_dir .glob ('*.csv')):
                date_key =self ._date_key (path .stem )
                if start_key and date_key <start_key :
                    continue
                if end_key and date_key >end_key :
                    continue

                try :
                    df =pd .read_csv (path ,encoding ='utf-8-sig')
                    if df .empty :
                         continue
                    branch_name =branch_dir .name
                    rename_map ={
                    'date':'日期',
                    'counterparty_broker_code':'證券代號',
                    'stock_id':'證券代號',
                    'stock_code':'證券代號',
                    'counterparty_broker_name':'證券名稱',
                    'stock_name':'證券名稱',
                    'branch_display_name':'分點名稱',
                    'branch_name':'分點名稱',
                    'buy_lots':'買進張數',
                    'sell_lots':'賣出張數',
                    'net_lots':'買賣超張數',
                    'buy_amount_k_twd':'買進金額千元',
                    'sell_amount_k_twd':'賣出金額千元',
                    'net_amount_k_twd':'買賣超金額千元',
                    'buy_qty':'買進金額千元',
                    'sell_qty':'賣出金額千元',
                    'net_qty':'買賣超金額千元',
                    }
                    df =df .rename (columns ={k :v for k ,v in rename_map .items ()if k in df .columns })
                    if '證券代號'in df .columns and '證券名稱'in df .columns :
                        df ['證券代號']=df ['證券代號'].astype (str ).str .strip ()
                        mask =df ['證券代號'].isin (['ETF','UNKNOWN'])
                        if mask .any ():
                            mapped =df .loc [mask ,'證券名稱'].astype (str ).str .strip ().map (name_to_code_map )
                            unmapped =df .loc [mask &mapped .isna (),'證券名稱'].unique ()
                            if len (unmapped )>0 :
                                import logging
                                logging .getLogger (__name__ ).warning (f"[UpdateService] Historical ETF repair found unmapped stock name: {unmapped.tolist()}")
                            df .loc [mask ,'證券代號']=mapped .fillna (df .loc [mask ,'證券代號'])
                    if '分點名稱'not in df .columns :
                        df ['分點名稱']=branch_name
                    if '日期'not in df .columns :
                        df ['日期']=date_key
                    frames .append (df )
                except Exception :
                    continue

        if not frames :
            return pd .DataFrame ()
        df_all =pd .concat (frames ,ignore_index =True )
        lot_cols =['買進張數','賣出張數','買賣超張數']
        amount_cols =['買進金額千元','賣出金額千元','買賣超金額千元']

        # 確保 metadata 欄位存在
        metadata_cols =['trade_type','lots_observed','amount_observed','lots_rank','amount_rank']
        for col in metadata_cols :
            if col not in df_all .columns :
                if col =='trade_type':
                    df_all [col ]=None
                elif col =='lots_observed':
                    if 'buy_lots'in df_all .columns :
                        df_all [col ]=df_all ['buy_lots'].notna ()
                    elif '買進張數'in df_all .columns :
                        df_all [col ]=df_all ['買進張數'].notna ()
                    else :
                        df_all [col ]=False
                elif col =='amount_observed':
                    if 'buy_amount_k_twd'in df_all .columns :
                        df_all [col ]=df_all ['buy_amount_k_twd'].notna ()
                    elif '買進金額千元'in df_all .columns :
                        df_all [col ]=df_all ['買進金額千元'].notna ()
                    else :
                        df_all [col ]=False
                else :
                    df_all [col ]=None

                    # 轉換為 Nullable Integer (Int64)
        for col in lot_cols +amount_cols :
            if col in df_all .columns :
                df_all [col ]=pd .to_numeric (df_all [col ],errors ='coerce').astype ('Int64')
            else :
                df_all [col ]=pd .Series ([None ]*len (df_all ),dtype ='Int64')
        df_all =self ._infer_broker_metric_ranks (df_all )

        # 計算股數：只由 observed lots 轉換，非 observed 則保持 <NA>
        df_all ['買進股數']=pd .Series ([None ]*len (df_all ),dtype ='Int64')
        df_all ['賣出股數']=pd .Series ([None ]*len (df_all ),dtype ='Int64')
        df_all ['買賣超股數']=pd .Series ([None ]*len (df_all ),dtype ='Int64')

        lots_mask =df_all ['lots_observed']==True
        df_all .loc [lots_mask ,'買進股數']=df_all .loc [lots_mask ,'買進張數']*1000
        df_all .loc [lots_mask ,'賣出股數']=df_all .loc [lots_mask ,'賣出張數']*1000
        df_all .loc [lots_mask ,'買賣超股數']=df_all .loc [lots_mask ,'買賣超張數']*1000

        # 將非 observed amount 的欄位設為 <NA>
        amount_mask =df_all ['amount_observed']==False
        df_all .loc [amount_mask ,'買進金額千元']=None
        df_all .loc [amount_mask ,'賣出金額千元']=None
        df_all .loc [amount_mask ,'買賣超金額千元']=None

        keep_cols =[
        '日期','分點名稱','證券代號','證券名稱',
        '買進股數','賣出股數','買賣超股數',
        *amount_cols ,
        *metadata_cols
        ]
        for col in keep_cols :
            if col not in df_all .columns :
                df_all [col ]=None
        df_all =df_all [keep_cols ]

        normalized =self ._normalize_sqlite_dates (df_all )
        return self ._deduplicate_and_merge_broker_flows (normalized )

    @staticmethod
    def _infer_broker_metric_ranks (df :Any )->Any :
        """由 MoneyDJ 榜單方向與淨值補齊缺失 rank，不覆蓋已觀測排名。"""
        import pandas as pd # type: ignore[import-untyped]

        required ={'日期','分點名稱','trade_type'}
        if df .empty or not required .issubset (df .columns ):
            return df

        result =df .copy ()
        metric_specs =(
        ('lots_observed','lots_rank','買賣超張數'),
        ('amount_observed','amount_rank','買賣超金額千元'),
        )
        group_cols =['日期','分點名稱','trade_type']

        for observed_col ,rank_col ,value_col in metric_specs :
            if observed_col not in result .columns or value_col not in result .columns :
                continue
            if rank_col not in result .columns :
                result [rank_col ]=pd .Series ([None ]*len (result ),dtype ='Int64')

            observed_mask =result [observed_col ].fillna (False ).astype (bool )
            missing_rank_mask =pd .to_numeric (result [rank_col ],errors ='coerce').isna ()
            eligible =result [observed_mask &missing_rank_mask &result [value_col ].notna ()]

            for group_key ,group in eligible .groupby (group_cols ,dropna =False ,sort =False ):
                trade_type =str (group_key [2 ])
                if trade_type not in {'買超','賣超'}:
                    continue
                ascending =trade_type =='賣超'
                ordered_indexes =group .sort_values (
                value_col ,
                ascending =ascending ,
                kind ='stable',
                ).index
                for rank ,index in enumerate (ordered_indexes ,start =1 ):
                    result .at [index ,rank_col ]=rank

            result [rank_col ]=pd .to_numeric (result [rank_col ],errors ='coerce').astype ('Int64')

        return result

    def _normalize_sqlite_dates (self ,df :Any )->Any :
        return update_data_normalization .normalize_sqlite_dates (
        df ,date_key_fn =self ._date_key ,stock_code_key_fn =self ._stock_code_key
        )

    @staticmethod
    def _sqlite_csv_dtype ()->Dict [str ,Any ]:
        return update_data_normalization .sqlite_csv_dtype ()

    @staticmethod
    def _stock_code_key (value :Any )->str :
        return update_data_normalization .stock_code_key (value )

    def _deduplicate_and_merge_broker_flows (self ,df :Any )->Any :
        import pandas as pd # type: ignore[import-untyped]

        if df .empty :
            return df

        key_cols =['分點名稱','證券代號','日期']
        if 'trade_type'in df .columns :
            key_cols .append ('trade_type')
        dup_mask =df .duplicated (subset =key_cols ,keep =False )
        if not dup_mask .any ():
            return df

            # 如果 df 中缺少 lots_observed/amount_observed 欄位，自動為其動態推導
        df =df .copy ()
        if 'lots_observed'not in df .columns :
            if 'buy_lots'in df .columns :
                df ['lots_observed']=df ['buy_lots'].notna ()
            elif '買進張數'in df .columns :
                has_amt ='買進金額千元'in df .columns
                amt_zero_or_nan =(df ['買進金額千元'].isna ()|(df ['買進金額千元']==0 ))if has_amt else True
                df ['lots_observed']=df ['買進張數'].notna ()&((df ['買進張數']!=0 )|(df .get ('賣出張數',0 )!=0 )|amt_zero_or_nan )
            elif '買進股數'in df .columns :
                has_amt ='買進金額千元'in df .columns
                amt_zero_or_nan =(df ['買進金額千元'].isna ()|(df ['買進金額千元']==0 ))if has_amt else True
                df ['lots_observed']=df ['買進股數'].notna ()&((df ['買進股數']!=0 )|(df .get ('賣出股數',0 )!=0 )|amt_zero_or_nan )
            else :
                df ['lots_observed']=False

        if 'amount_observed'not in df .columns :
            if 'buy_amount_k_twd'in df .columns :
                df ['amount_observed']=df ['buy_amount_k_twd'].notna ()
            elif '買進金額千元'in df .columns :
                has_lots ='買進張數'in df .columns
                lots_zero_or_nan =(df ['買進張數'].isna ()|(df ['買進張數']==0 ))if has_lots else True
                has_vol ='買進股數'in df .columns
                vol_zero_or_nan =(df ['買進股數'].isna ()|(df ['買進股數']==0 ))if has_vol else True
                df ['amount_observed']=df ['買進金額千元'].notna ()&((df ['買進金額千元']!=0 )|(df .get ('賣出金額千元',0 )!=0 )|(lots_zero_or_nan &vol_zero_or_nan ))
            else :
                df ['amount_observed']=False

        df_clean =df [~dup_mask ]
        df_dup =df [dup_mask ]

        resolved_rows =[]
        numeric_cols =[
        '買進股數','賣出股數','買賣超股數',
        '買進金額千元','賣出金額千元','買賣超金額千元'
        ]

        grouped =df_dup .groupby (key_cols ,as_index =False )
        for key_vals ,group in grouped :
            name_series =group ['證券名稱'].dropna ()
            name_series =name_series [name_series .astype (str ).str .strip ()!='']
            stock_name =name_series .iloc [0 ]if not name_series .empty else ''

            resolved_row ={
            '分點名稱':key_vals [0 ],
            '證券代號':key_vals [1 ],
            '日期':key_vals [2 ],
            '證券名稱':stock_name
            }
            if 'trade_type'in key_cols :
                resolved_row ['trade_type']=key_vals [3 ]

                # 1. 識別與合併 metadata 欄位
            metadata_cols =['lots_observed','amount_observed','lots_rank','amount_rank']
            if 'trade_type'not in key_cols :
                metadata_cols .insert (0 ,'trade_type')
            for m_col in metadata_cols :
                if m_col in group .columns :
                    vals =group [m_col ].dropna ()
                    if not vals .empty :
                        if m_col in ['lots_observed','amount_observed']:
                            resolved_row [m_col ]=bool (vals .any ())
                        elif m_col =='trade_type':
                            unique_values =vals .astype (str ).unique ()
                            if len (unique_values )>1 :
                                raise ValueError (
                                f"唯一鍵衝突於 {key_cols}={key_vals}, trade_type 存在衝突: {unique_values.tolist()}"
                                )
                            resolved_row [m_col ]=unique_values [0 ]
                        else :
                            resolved_row [m_col ]=vals .iloc [0 ]
                    else :
                        resolved_row [m_col ]=False if m_col in ['lots_observed','amount_observed']else None
                else :
                    resolved_row [m_col ]=False if m_col in ['lots_observed','amount_observed']else None

                    # 2. 根據 observed 狀態合併數值
            for col in numeric_cols :
                if col in group .columns :
                    is_lots_col =col in ['買進股數','賣出股數','買賣超股數']
                    is_observed =resolved_row ['lots_observed']if is_lots_col else resolved_row ['amount_observed']

                    if not is_observed :
                        resolved_row [col ]=None
                    else :
                        vals =group [col ].dropna ()
                        non_zeros =vals [vals !=0 ].unique ()
                        if len (non_zeros )>1 :
                            raise ValueError (
                            f"唯一鍵衝突於 {key_cols}={key_vals}, 欄位 '{col}' 存在衝突的非零數值: {non_zeros.tolist()}"
                            )
                        elif len (non_zeros )==1 :
                            resolved_row [col ]=int (non_zeros [0 ])
                        else :
                            resolved_row [col ]=0
                else :
                    resolved_row [col ]=None

            resolved_rows .append (resolved_row )

        df_resolved =pd .DataFrame (resolved_rows )
        # 確保 df_resolved 擁有正確的 columns 及 Nullable Int64 型態
        for col in numeric_cols :
            if col in df .columns :
                df_resolved [col ]=pd .to_numeric (df_resolved [col ],errors ='coerce').astype ('Int64')
        for col in metadata_cols :
            if col in df .columns :
                if col in ['lots_observed','amount_observed']:
                    df_resolved [col ]=df_resolved [col ].astype (bool )
                elif col =='trade_type':
                    df_resolved [col ]=df_resolved [col ].astype ('string')
                else :
                    df_resolved [col ]=pd .to_numeric (df_resolved [col ],errors ='coerce').astype ('Int64')

        df_resolved =df_resolved .reindex (columns =df .columns )
        return pd .concat ([df_clean ,df_resolved ],ignore_index =True )

    def _date_key (self ,value :Any )->str :
        return update_data_normalization .date_key (value )

    def _replace_sqlite_dates (self ,db :Any ,table_name :str ,df :Any )->bool :
        if df .empty :
            return True
        df =self ._normalize_sqlite_dates (df )
        date_col ='日期'if '日期'in df .columns else None
        if date_col is None :
            raise ValueError (f"無法從 DataFrame 提取有效日期進行替換: table={table_name}")
        dates =sorted ({str (v )for v in df [date_col ].dropna ().tolist ()if str (v )})
        if not dates :
            raise ValueError (f"無法從 DataFrame 提取有效日期進行替換: table={table_name}")

        try :
            db .ensure_columns (table_name ,list (df .columns ))
            placeholders =','.join ('?'for _ in dates )
            with db .connect ()as conn :
                conn .execute (f'DELETE FROM {table_name} WHERE "{date_col}" IN ({placeholders});',dates )
                df .to_sql (table_name ,conn ,if_exists ='append',index =False )
            return True
        except Exception as e :
            import logging
            logger =logging .getLogger (__name__ )
            logger .error (f"[UpdateService] _replace_sqlite_dates 失敗: table={table_name}, 錯誤={e}")
            raise

    def _upsert_sqlite_rows (self ,db :Any ,table_name :str ,df :Any )->bool :
        if df .empty :
            return True
        df =self ._normalize_sqlite_dates (df )
        code_col ='證券代號'if '證券代號'in df .columns else None
        date_col ='日期'if '日期'in df .columns else None
        if code_col and date_col :
            df =df .drop_duplicates (subset =[code_col ,date_col ],keep ='last')

        try :
            db .ensure_columns (table_name ,list (df .columns ))
            with db .connect ()as conn :
                table_columns =tuple (row ["name"]for row in conn .execute (f"PRAGMA table_info({table_name});").fetchall ())
                columns =tuple (column for column in df .columns if column in table_columns )
                required_columns =("證券代號","日期")
                missing =[column for column in required_columns if column not in columns ]
                if missing :
                    raise ValueError (f"{table_name} upsert 缺少必要欄位: {missing}")

                quoted_columns =", ".join (f'"{column}"'for column in columns )
                placeholders =", ".join ("?"for _ in columns )
                update_columns =tuple (column for column in columns if column not in required_columns )
                conflict_clause ='ON CONFLICT("證券代號", "日期") DO NOTHING'
                if update_columns :
                    update_clause =", ".join (f'"{column}" = excluded."{column}"'for column in update_columns )
                    conflict_clause =f'ON CONFLICT("證券代號", "日期") DO UPDATE SET {update_clause}'
                sql =f"INSERT INTO {table_name} ({quoted_columns}) VALUES ({placeholders}) {conflict_clause}"
                values =[tuple (row [column ]for column in columns )for row in df [list (columns )].to_dict (orient ='records')]
                conn .executemany (sql ,values )
            return True
        except Exception as e :
            import logging
            logger =logging .getLogger (__name__ )
            logger .error (f"[UpdateService] _upsert_sqlite_rows 失敗: table={table_name}, 錯誤={e}")
            return False

    def _replace_sqlite_table (self ,db :Any ,table_name :str ,df :Any )->bool :
        if df .empty :
            return True

        try :
            db .ensure_columns (table_name ,list (df .columns ))
            with db .connect ()as conn :
                conn .execute (f'DELETE FROM {table_name};')
                df .to_sql (table_name ,conn ,if_exists ='append',index =False )
            return True
        except Exception as e :
            import logging
            logger =logging .getLogger (__name__ )
            logger .error (f"[UpdateService] _replace_sqlite_table 失敗: table={table_name}, 錯誤={e}")
            raise

    def update_daily (
    self ,
    start_date :str ,
    end_date :str ,
    delay_seconds :float =4.0 ,
    progress_callback :Optional [Callable[[str ,int ],None ]]=None ,
    cancel_callback :Optional [Callable[[],bool ]]=None
    )->Dict [str ,Any ]:
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
            'failed_dates': list[str],
            'progress_callback': optional callback receiving (message, percentage)
            'cancelled': optional bool indicating a cooperative cancellation
            }
        """
        import subprocess
        import os
        import sys
        import logging
        import re
        from datetime import datetime ,timedelta
        from data_module .data_loader import DataLoader

        logger =logging .getLogger (__name__ )

        def cancelled_result(message: str) -> Dict [str ,Any ]:
            _emit_update_progress(progress_callback, message, 100)
            return {
            'success':False ,
            'cancelled':True ,
            'message':message ,
            'updated_dates':[] ,
            'failed_dates':[] ,
            }

        if _is_cancel_requested(cancel_callback):
            return cancelled_result("TWSE 每日股價更新已取消（尚未開始）")

        # ✅ 記錄輸入參數
        logger .info (
        f"[UpdateService] 開始更新每日股票數據: "
        f"start_date={start_date}, end_date={end_date}, delay_seconds={delay_seconds}"
        )

        # 調用 batch_update_daily_data.py
        script_path =self .scripts_dir /'batch_update_daily_data.py'
        logger .debug (f"[UpdateService] 更新腳本路徑: {script_path}")
        if not script_path .exists ():
            logger .error (f"[UpdateService] 找不到更新腳本: {script_path}")
            return {
            'success':False ,
            'message':f'找不到更新腳本: {script_path}',
            'updated_dates':[],
            'failed_dates':[]
            }

        try :
        # 先做本地缺漏檢查：若指定區間已完整且檔案皆已存在，直接回報完成，避免重複跑大量日期檢查
            missing_dates :list [str ]=[]
            _emit_update_progress(progress_callback, "檢查 TWSE 每日股價缺漏", 0)
            loader =DataLoader (self .config )
            start_dt =datetime .strptime (start_date ,'%Y-%m-%d')
            end_dt =datetime .strptime (end_date ,'%Y-%m-%d')
            current_dt =start_dt
            while current_dt <=end_dt :
                if _is_cancel_requested(cancel_callback):
                    return cancelled_result("TWSE 每日股價更新已取消（檢查日期缺漏時）")
                if current_dt .weekday ()<5 :
                    trade_date =current_dt .strftime ('%Y-%m-%d')
                    if not loader .get_daily_price_file (trade_date ).exists ():
                        missing_dates .append (trade_date )
                current_dt +=timedelta (days =1 )

            if not missing_dates :
                logger .info ("[UpdateService] 目標區間每日股價檔案皆已存在，跳過 batch 更新")
                _emit_update_progress(
                    progress_callback,
                    "TWSE 每日股價檔案皆已存在，無需 API 下載",
                    100,
                )
                return {
                'success':True ,
                'message':'每日股價檔案已是最新，無需更新',
                'updated_dates':[],
                'failed_dates':[]
                }

                # 僅針對缺漏區段做更新（避免每次都掃整段 2014~現在）
            start_date =missing_dates [0 ]

            # 執行腳本（腳本內部會檢查文件是否已存在，只下載缺失的）
            import tempfile
            from pathlib import Path as _Path

            command =[
            sys .executable ,str (script_path ),
            '--start-date',start_date ,
            '--end-date',end_date ,
            '--delay-min',str (delay_seconds ),
            '--delay-max',str (delay_seconds )]
            cancellation_requested =False
            if progress_callback is None and cancel_callback is None:
                # 無 UI callback 時保留既有 run() 路徑，讓外部 service double／CLI
                # 可以繼續攔截 subprocess.run；有 callback 才啟用逐行進度。
                with tempfile .NamedTemporaryFile (mode ='w+',delete =False ,suffix ='.log',encoding ='utf-8')as output_file :
                    output_path =output_file .name
                    result =subprocess .run (
                    command ,
                    stdout =output_file ,
                    stderr =subprocess .STDOUT ,
                    text =True ,
                    encoding ='utf-8'
                    )
                output_path_obj =_Path (output_path )
                try :
                    output =output_path_obj .read_text (encoding ='utf-8',errors ='ignore')
                except Exception :
                    output =''
                finally :
                    output_path_obj .unlink (missing_ok =True )
                return_code =result .returncode
            else:
                output_path_obj =None
                output_lines :list [str ]=[]
                try :
                    with tempfile .NamedTemporaryFile (mode ='w+',delete =False ,suffix ='.log',encoding ='utf-8')as output_file :
                        output_path =output_file .name
                        output_path_obj =_Path (output_path )
                        process =subprocess .Popen (
                        command ,
                        stdout =subprocess .PIPE ,
                        stderr =subprocess .STDOUT ,
                        text =True ,
                        encoding ='utf-8',
                        errors ='replace',
                        bufsize =1 ,
                        )
                        if process .stdout is not None :
                            for line in iter (process .stdout .readline ,''):
                                output_file .write (line )
                                output_file .flush ()
                                output_lines .append (line )
                                if _is_cancel_requested(cancel_callback):
                                    # batch 腳本可能正在直接寫入 CSV；不強制終止子程序，
                                    # 先完整收尾目前請求，再把結果明確標示為已取消。
                                    cancellation_requested =True
                                match =re .search (
                                r'\[(\d+)/(\d+)\].*?(\d{4}-\d{2}-\d{2})',
                                line ,
                                )
                                if match :
                                    index =int (match .group (1))
                                    total =int (match .group (2))
                                    percentage =(index *100 )//total if total else 0
                                    _emit_update_progress (
                                    progress_callback ,
                                    f"TWSE API 下載 {match .group (3)}（{index}/{total}）",
                                    percentage ,
                                    )
                        return_code =process .wait ()
                        output_file .flush ()
                finally :
                    if output_path_obj is not None :
                        output_path_obj .unlink (missing_ok =True )
                output =''.join (output_lines )

            if cancellation_requested or _is_cancel_requested(cancel_callback):
                return cancelled_result(
                    "TWSE 每日股價更新已取消；目前 API 請求已安全收尾，請重新檢查資料狀態"
                )

            if return_code ==0 :
                parsed_result =parse_daily_update_output (output ,missing_dates )
                _emit_update_progress (
                    progress_callback ,
                    "TWSE API 下載完成，正在解析日期結果",
                    100,
                )
                if parsed_result ["success"]:
                    logger .info ("[UpdateService] 每日股價更新完成: %s",parsed_result ["message"])
                else :
                    logger .warning ("[UpdateService] 每日股價更新失敗: %s",parsed_result ["message"])
                return parsed_result

            logger .error (f"[UpdateService] 更新失敗: {output}")
            _emit_update_progress(progress_callback, "TWSE API 下載程序失敗", 100)
            return {
            'success':False ,
            'message':f'更新失敗：{output}',
            'updated_dates':[],
            'failed_dates':[]
            }
        except Exception as e :
            import traceback
            logger .error (f"[UpdateService] 執行更新時發生異常: {str(e)}")
            logger .error (traceback .format_exc ())
            return {
            'success':False ,
            'message':f'執行更新時發生錯誤：{str(e)}\n{traceback.format_exc()}',
            'updated_dates':[],
            'failed_dates':[]
            }

    def update_market (
    self ,
    start_date :str ,
    end_date :str
    )->Dict [str ,Any ]:
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
        import os
        import sys
        import logging
        import traceback
        import re

        logger =logging .getLogger (__name__ )

        # ✅ 記錄輸入參數
        logger .info (
        f"[UpdateService] 開始更新大盤指數數據: "
        f"start_date={start_date}, end_date={end_date}"
        )

        try :
        # 動態導入並調用 batch_update_market_index 函數
            import importlib .util

            script_path =self .scripts_dir /'batch_update_market_and_industry_index.py'
            logger .debug (f"[UpdateService] 更新腳本路徑: {script_path}")

            if not script_path .exists ():
                error_msg =f'找不到更新腳本: {script_path}'
                logger .error (f"[UpdateService] {error_msg}")
                return {
                'success':False ,
                'message':error_msg ,
                'updated_dates':[],
                'failed_dates':[]
                }

                # 動態導入模組
            try :
                spec =importlib .util .spec_from_file_location ("batch_update_market_and_industry_index",script_path )
                if spec is None or spec .loader is None :
                    raise ImportError (f"無法創建模組規格: {script_path}")

                update_module =importlib .util .module_from_spec (spec )
                spec .loader .exec_module (update_module )
                logger .debug (f"[UpdateService] 模組導入成功")
            except Exception as e :
                error_msg =f"導入更新模組時發生錯誤: {str(e)}"
                logger .error (f"[UpdateService] {error_msg}")
                logger .error (traceback .format_exc ())
                return {
                'success':False ,
                'message':error_msg ,
                'updated_dates':[],
                'failed_dates':[]
                }

                # 檢查函數是否存在
            if not hasattr (update_module ,'batch_update_market_index'):
                error_msg =f"更新模組中找不到 batch_update_market_index 函數"
                logger .error (f"[UpdateService] {error_msg}")
                return {
                'success':False ,
                'message':error_msg ,
                'updated_dates':[],
                'failed_dates':[]
                }

                # 執行更新函數
            logger .info (f"[UpdateService] 開始執行大盤指數更新函數")
            try :
            # ✅ 傳遞 config 給更新函數（如果它支持的話）
                import inspect
                update_func =update_module .batch_update_market_index
                sig =inspect .signature (update_func )
                params =list (sig .parameters .keys ())

                if 'config'in params :
                    logger .debug (f"[UpdateService] 更新函數支持 config 參數，傳遞配置")
                    result =update_func (start_date =start_date ,end_date =end_date ,config =self .config )
                else :
                    logger .debug (f"[UpdateService] 更新函數不支持 config 參數，使用默認參數")
                    result =update_func (start_date =start_date ,end_date =end_date )
                logger .info (f"[UpdateService] 大盤指數更新函數執行完成")

                # 解析結果（函數可能沒有返回值）
                if result is None :
                # 函數沒有返回值，假設成功
                    return {
                    'success':True ,
                    'message':'大盤指數更新完成',
                    'updated_dates':[],
                    'failed_dates':[]
                    }
                elif isinstance (result ,dict ):
                    return {
                    'success':result .get ('success',True ),
                    'message':result .get ('message','更新完成'),
                    'updated_dates':result .get ('updated_dates',[]),
                    'failed_dates':result .get ('failed_dates',[])
                    }
                else :
                # 如果返回的不是 dict，假設成功
                    return {
                    'success':True ,
                    'message':'大盤指數更新完成',
                    'updated_dates':[],
                    'failed_dates':[]
                    }
            except Exception as e :
                error_msg =f"執行大盤指數更新函數時發生錯誤: {str(e)}"
                logger .error (f"[UpdateService] {error_msg}")
                logger .error (traceback .format_exc ())
                return {
                'success':False ,
                'message':error_msg ,
                'updated_dates':[],
                'failed_dates':[]
                }

        except Exception as e :
            error_msg =f"更新大盤指數數據時發生異常: {str(e)}"
            logger .error (f"[UpdateService] {error_msg}")
            logger .error (traceback .format_exc ())
            return {
            'success':False ,
            'message':error_msg ,
            'updated_dates':[],
            'failed_dates':[]
            }

    def update_industry (
    self ,
    start_date :str ,
    end_date :str
    )->Dict [str ,Any ]:
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
        import os
        import sys
        import logging
        import traceback
        import re

        logger =logging .getLogger (__name__ )

        # ✅ 記錄輸入參數
        logger .info (
        f"[UpdateService] 開始更新產業指數數據: "
        f"start_date={start_date}, end_date={end_date}"
        )

        try :
        # 動態導入並調用 batch_update_industry_index 函數
            import importlib .util

            script_path =self .scripts_dir /'batch_update_market_and_industry_index.py'
            logger .debug (f"[UpdateService] 更新腳本路徑: {script_path}")

            if not script_path .exists ():
                error_msg =f'找不到更新腳本: {script_path}'
                logger .error (f"[UpdateService] {error_msg}")
                return {
                'success':False ,
                'message':error_msg ,
                'updated_dates':[],
                'failed_dates':[]
                }

                # 動態導入模組
            try :
                spec =importlib .util .spec_from_file_location ("batch_update_market_and_industry_index",script_path )
                if spec is None or spec .loader is None :
                    raise ImportError (f"無法創建模組規格: {script_path}")

                update_module =importlib .util .module_from_spec (spec )
                spec .loader .exec_module (update_module )
                logger .debug (f"[UpdateService] 模組導入成功")
            except Exception as e :
                error_msg =f"導入更新模組時發生錯誤: {str(e)}"
                logger .error (f"[UpdateService] {error_msg}")
                logger .error (traceback .format_exc ())
                return {
                'success':False ,
                'message':error_msg ,
                'updated_dates':[],
                'failed_dates':[]
                }

                # 檢查函數是否存在
            if not hasattr (update_module ,'batch_update_industry_index'):
                error_msg =f"更新模組中找不到 batch_update_industry_index 函數"
                logger .error (f"[UpdateService] {error_msg}")
                return {
                'success':False ,
                'message':error_msg ,
                'updated_dates':[],
                'failed_dates':[]
                }

                # 執行更新函數
            logger .info (f"[UpdateService] 開始執行產業指數更新函數")
            try :
            # ✅ 傳遞 config 給更新函數（如果它支持的話）
                import inspect
                update_func =update_module .batch_update_industry_index
                sig =inspect .signature (update_func )
                params =list (sig .parameters .keys ())

                if 'config'in params :
                    logger .debug (f"[UpdateService] 更新函數支持 config 參數，傳遞配置")
                    result =update_func (start_date =start_date ,end_date =end_date ,config =self .config )
                else :
                    logger .debug (f"[UpdateService] 更新函數不支持 config 參數，使用默認參數")
                    result =update_func (start_date =start_date ,end_date =end_date )
                logger .info (f"[UpdateService] 產業指數更新函數執行完成")

                # 解析結果（函數可能沒有返回值）
                if result is None :
                    return {
                    'success':True ,
                    'message':'產業指數更新完成',
                    'updated_dates':[],
                    'failed_dates':[]
                    }
                elif isinstance (result ,dict ):
                    return {
                    'success':result .get ('success',True ),
                    'message':result .get ('message','更新完成'),
                    'updated_dates':result .get ('updated_dates',[]),
                    'failed_dates':result .get ('failed_dates',[])
                    }
                else :
                    return {
                    'success':True ,
                    'message':'產業指數更新完成',
                    'updated_dates':[],
                    'failed_dates':[]
                    }
            except Exception as e :
                error_msg =f"執行產業指數更新函數時發生錯誤: {str(e)}"
                logger .error (f"[UpdateService] {error_msg}")
                logger .error (traceback .format_exc ())
                return {
                'success':False ,
                'message':error_msg ,
                'updated_dates':[],
                'failed_dates':[]
                }

        except Exception as e :
            error_msg =f"更新產業指數數據時發生異常: {str(e)}"
            logger .error (f"[UpdateService] {error_msg}")
            logger .error (traceback .format_exc ())
            return {
            'success':False ,
            'message':error_msg ,
            'updated_dates':[],
            'failed_dates':[]
            }

    def _quote_sql_identifier (self ,identifier :str )->str :
        return '"'+str (identifier ).replace ('"','""')+'"'

    def _sqlite_status_db_exists(self) -> bool:
        """確認狀態讀取的 SQLite 已存在；不可為了查狀態建立空 DB。"""
        db_file = getattr(self.config, "db_file", None)
        if not db_file:
            return False
        return Path(str(db_file)).is_file()

    def _sqlite_unavailable_status(self) -> Dict[str, Any]:
        """回傳明確 unavailable payload，讓 UI／一鍵更新不會假裝成功。"""
        db_file = getattr(self.config, "db_file", "")
        return {
            "latest_date": None,
            "total_records": 0,
            "status": "unavailable",
            "message": f"SQLite 資料庫不存在：{db_file}",
        }

    def _sqlite_status_manager(self) -> ReadOnlySQLiteManager:
        """建立狀態查詢專用的 query-only SQLite adapter。"""
        return ReadOnlySQLiteManager(self.config.db_file)

    @staticmethod
    def _annotate_sqlite_read_mode(
        payload: Dict[str, Any],
        db: ReadOnlySQLiteManager,
    ) -> Dict[str, Any]:
        """揭露 Windows lock 下的 immutable snapshot fallback，避免假裝即時。"""
        if db.last_read_mode != "immutable_fallback":
            return payload
        annotated = dict(payload)
        warnings = list(annotated.get("warnings") or annotated.get("quality_warnings") or [])
        warnings.append(
            "SQLite 目前使用 immutable 唯讀快照；可能只反映最後已提交內容，請停止其他寫入後重查"
        )
        annotated["warnings"] = list(dict.fromkeys(str(item) for item in warnings if str(item).strip()))
        annotated["read_mode"] = "immutable_fallback"
        return annotated

    def _first_existing_column (self ,columns :Any ,candidates :list [str ])->Optional [str ]:
        column_set ={str (col )for col in columns }
        for candidate in candidates :
            if candidate in column_set :
                return candidate
        return None

    def _status_from_sqlite (self ,table_name :str )->Dict [str ,Any ]:
        """從 SQLite 資料庫極速獲取指定資料表的狀態"""
        if not self._sqlite_status_db_exists():
            return self._sqlite_unavailable_status()
        try :
            db =self ._sqlite_status_manager ()
            columns =db .get_table_columns (table_name )
            date_column =self ._first_existing_column (
            columns ,
            ['日期','日期','date','Date','trade_date','trading_date'],
            )
            table_sql =self ._quote_sql_identifier (table_name )
            if date_column :
                date_sql =self ._quote_sql_identifier (date_column )
                query =f"SELECT COUNT(*) as count, MAX({date_sql}) as max_date FROM {table_sql};"
            else :
                query =f"SELECT COUNT(*) as count, NULL as max_date FROM {table_sql};"
            df =db .execute_query (query )
            if not df .empty :
                cnt =int (df .iloc [0 ]['count'])
                max_d =df .iloc [0 ]['max_date']

                max_date_str =None
                if max_d :
                    max_d_str =str (max_d )
                    if len (max_d_str )==8 :
                        max_date_str =f"{max_d_str[:4]}-{max_d_str[4:6]}-{max_d_str[6:]}"
                    else :
                        max_date_str =max_d_str

                return self._annotate_sqlite_read_mode({
                'latest_date':max_date_str ,
                'total_records':cnt ,
                'status':'ok'if cnt >0 else 'empty'
                }, db)
            return self._annotate_sqlite_read_mode(
                {'latest_date':None ,'total_records':0 ,'status':'empty'}, db
            )
        except Exception as e :
            import logging
            logging .getLogger (__name__ ).warning (f"[UpdateService] 從 SQLite 獲取表 {table_name} 狀態失敗: {e}")
            return {'latest_date':None ,'total_records':0 ,'status':f'error: {e}'}

    def _monthly_revenue_status_from_sqlite (self )->Dict [str ,Any ]:
        """Read monthly revenue status from the fundamental SQLite table."""
        if not self._sqlite_status_db_exists():
            return self._sqlite_unavailable_status()
        try :
            db =self ._sqlite_status_manager ()
            today =_monthly_revenue_status_today ()
            df =db .execute_query (
            """
                WITH period_availability AS (
                    SELECT
                        period,
                        MAX(available_date) AS fully_available_date
                    FROM fundamental_monthly_revenues
                    GROUP BY period
                )
                SELECT
                    COUNT(*) AS count,
                    MIN(period) AS min_period,
                    MAX(period) AS max_period,
                    MAX(as_of_date) AS max_as_of_date,
                    COUNT(DISTINCT stock_code) AS stock_count,
                    COUNT(DISTINCT period) AS period_count,
                    (SELECT MAX(period) FROM period_availability WHERE fully_available_date <= ?) AS latest_available_period,
                    (SELECT MAX(fully_available_date) FROM period_availability WHERE fully_available_date <= ?) AS latest_available_date,
                    (SELECT MIN(fully_available_date) FROM period_availability WHERE fully_available_date > ?) AS next_available_date,
                    (SELECT COUNT(*) FROM period_availability WHERE fully_available_date > ?) AS pending_period_count
                FROM fundamental_monthly_revenues;
                """,
                (today ,today ,today ,today ),
            )
            if df .empty :
                return {'latest_date':None ,'total_records':0 ,'status':'empty'}

            row =df .iloc [0 ]
            count =int (row ['count']or 0 )
            payload = {
            'latest_date':row ['max_as_of_date']if count else None ,
            'latest_period':row ['max_period']if count else None ,
            'earliest_date':row ['min_period']if count else None ,
            'total_records':count ,
            'stock_count':int (row ['stock_count']or 0 ),
            'period_count':int (row ['period_count']or 0 ),
            'latest_available_period':row ['latest_available_period']if count else None ,
            'latest_available_date':row ['latest_available_date']if count else None ,
            'next_available_date':row ['next_available_date']if count else None ,
            'pending_period_count':int (row ['pending_period_count']or 0 ),
            'status':'ok'if count >0 else 'empty',
            }
            # Snapshot 是數值候選，不是正式 availability 證據；只在唯讀狀態
            # 中揭露較新的候選期別，避免使用者把「已抓到」誤認成「已套用」。
            candidate_path = select_latest_monthly_revenue_snapshot(
                self.config.output_root / 'monthly_revenue_mops_snapshots'
            )
            if candidate_path is not None:
                candidate = inspect_monthly_revenue_snapshot(candidate_path)
                if candidate.latest_period:
                    payload['candidate_latest_period'] = candidate.latest_period
                    payload['candidate_fetch_date'] = candidate.fetch_date
                    payload['candidate_snapshot_file'] = str(candidate.path)
                    imported_period = str(payload.get('latest_period') or '')
                    if not imported_period or candidate.latest_period > imported_period:
                        payload['status'] = 'candidate_available'
                        payload['warnings'] = [
                            '已有較新的 MOPS 月營收數值候選；尚未完成 availability dry-run／正式套用'
                        ]
            availability_candidate_path = self.monthly_revenue_availability_candidate_path
            if availability_candidate_path is not None:
                availability_candidate = inspect_monthly_revenue_availability_candidate(
                    availability_candidate_path,
                    target_file=self.config.monthly_revenue_availability_file,
                )
                payload.update(
                    {
                        'availability_candidate_file': str(availability_candidate.path),
                        'availability_candidate_status': availability_candidate.status,
                        'availability_candidate_row_count': availability_candidate.row_count,
                        'availability_candidate_latest_period': availability_candidate.latest_period,
                        'availability_candidate_latest_available_date': (
                            availability_candidate.latest_available_date
                        ),
                        'availability_candidate_source_versions': list(
                            availability_candidate.source_versions
                        ),
                        'availability_candidate_diagnostic_count': (
                            availability_candidate.diagnostic_count
                        ),
                        'availability_candidate_added_count': availability_candidate.added_count,
                        'availability_candidate_unchanged_count': (
                            availability_candidate.unchanged_count
                        ),
                        'availability_candidate_conflict_count': (
                            availability_candidate.conflict_count
                        ),
                    }
                )
                if availability_candidate.diagnostics:
                    payload['availability_candidate_diagnostics'] = list(
                        availability_candidate.diagnostics
                    )
                candidate_period = availability_candidate.latest_period
                imported_period = str(payload.get('latest_period') or '')
                if candidate_period and (
                    not imported_period or candidate_period > imported_period
                ):
                    payload['status'] = 'candidate_available'
                    raw_warnings = payload.get('warnings')
                    warnings = list(raw_warnings) if isinstance(raw_warnings, list) else []
                    if availability_candidate.status == 'ready_for_merge':
                        warnings.append(
                            '已有較新的公告日／可得日 mapping 候選；尚未合併到正式 mapping'
                        )
                    elif availability_candidate.status == 'conflict':
                        warnings.append(
                            '公告日／可得日 mapping 候選與正式 mapping 有衝突；未自動覆蓋'
                        )
                    elif availability_candidate.status == 'merge_blocked':
                        warnings.append(
                            '公告日／可得日 mapping 候選的 merge preview 受阻；未自動套用'
                        )
                    elif availability_candidate.status in {'invalid', 'error'}:
                        warnings.append(
                            '公告日／可得日 mapping 候選驗證未完成；未自動套用'
                        )
                    payload['warnings'] = list(
                        dict.fromkeys(str(item) for item in warnings if str(item).strip())
                    )
            return self._annotate_sqlite_read_mode(payload, db)
        except Exception as e :
            import logging
            logging .getLogger (__name__ ).warning (f"[UpdateService] 從 SQLite 取得月營收狀態失敗: {e}")
            return {'latest_date':None ,'total_records':0 ,'status':f'error: {e}'}

    def _broker_status_from_sqlite (self )->Dict [str ,Any ]:
        """從 SQLite 資料庫極速獲取券商分點的狀態"""
        if not self._sqlite_status_db_exists():
            return self._sqlite_unavailable_status()
        try :
            db =self ._sqlite_status_manager ()

            columns =db .get_table_columns ("broker_flows")
            has_observed_cols ="lots_observed"in columns and "amount_observed"in columns
            date_column =self ._first_existing_column (columns ,['日期','日期','date','Date'])
            broker_column =self ._first_existing_column (
            columns ,
            ['分點名稱','分點名稱','branch_display_name','branch_name'],
            )
            date_sql =self ._quote_sql_identifier (date_column )if date_column else "NULL"
            broker_sql =self ._quote_sql_identifier (broker_column )if broker_column else "NULL"

            if has_observed_cols :
                query =f"""
                    SELECT
                        COUNT(*) as count,
                        MAX({date_sql}) as max_date,
                        COUNT(DISTINCT {broker_sql}) as broker_count,
                        MIN({date_sql}) as min_date,
                        COUNT(DISTINCT {date_sql}) as date_count,
                        SUM(CASE WHEN lots_observed = 1 AND amount_observed = 1 THEN 1 ELSE 0 END) as dual_cnt,
                        SUM(CASE WHEN lots_observed = 1 AND (amount_observed = 0 OR amount_observed IS NULL) THEN 1 ELSE 0 END) as e_only_cnt,
                        SUM(CASE WHEN (lots_observed = 0 OR lots_observed IS NULL) AND amount_observed = 1 THEN 1 ELSE 0 END) as b_only_cnt
                    FROM broker_flows;
                """
            else :
                query =f"""
                    SELECT
                        COUNT(*) as count,
                        MAX({date_sql}) as max_date,
                        COUNT(DISTINCT {broker_sql}) as broker_count,
                        MIN({date_sql}) as min_date,
                        COUNT(DISTINCT {date_sql}) as date_count
                    FROM broker_flows;
                """

            df =db .execute_query (query )
            if not df .empty :
                cnt =int (df .iloc [0 ]['count']or 0 )
                max_d =df .iloc [0 ]['max_date']
                min_d =df .iloc [0 ]['min_date']
                broker_cnt =int (df .iloc [0 ]['broker_count']or 0 )
                date_cnt =int (df .iloc [0 ]['date_count']or 0 )

                if has_observed_cols :
                    dual_cnt =int (df .iloc [0 ]['dual_cnt']or 0 )
                    e_only_cnt =int (df .iloc [0 ]['e_only_cnt']or 0 )
                    b_only_cnt =int (df .iloc [0 ]['b_only_cnt']or 0 )
                else :
                    dual_cnt =0
                    e_only_cnt =0
                    b_only_cnt =cnt

                def fmt_d (d ):
                    if not d :return None
                    d_str =str (d )
                    return f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:]}"if len (d_str )==8 else d_str

                return self._annotate_sqlite_read_mode({
                'latest_date':fmt_d (max_d ),
                'total_records':cnt ,
                'broker_count':broker_cnt ,
                'date_count':date_cnt ,
                'e_only_count':e_only_cnt ,
                'b_only_count':b_only_cnt ,
                'dual_count':dual_cnt ,
                'date_range':{'start_date':fmt_d (min_d ),'end_date':fmt_d (max_d )},
                'status':'ok'if cnt >0 else 'empty'
                }, db)
            return self._annotate_sqlite_read_mode(
                {'latest_date':None ,'total_records':0 ,'broker_count':0 ,'date_count':0 ,'status':'empty'},
                db,
            )
        except Exception as e :
            import logging
            logging .getLogger (__name__ ).warning (f"[UpdateService] 從 SQLite 獲取券商分點狀態失敗: {e}")
            return {'latest_date':None ,'total_records':0 ,'broker_count':0 ,'date_count':0 ,'status':f'error: {e}'}

    def _technical_status_from_sqlite (self )->Dict [str ,Any ]:
        """從 SQLite 資料庫極速獲取技術指標的狀態"""
        if not self._sqlite_status_db_exists():
            return self._sqlite_unavailable_status()
        try :
            db =self ._sqlite_status_manager ()
            columns =db .get_table_columns ("technical_indicators")
            date_column =self ._first_existing_column (columns ,['日期','日期','date','Date'])
            stock_column =self ._first_existing_column (
            columns ,
            ['證券代號','證券代號','股票代號','stock_id','stock_code'],
            )
            date_sql =self ._quote_sql_identifier (date_column )if date_column else "NULL"
            stock_sql =self ._quote_sql_identifier (stock_column )if stock_column else "NULL"
            if date_column :
                valid_date_filter =(
                f"{date_sql} IS NOT NULL "
                f"AND lower(CAST({date_sql} AS TEXT)) NOT IN ('', 'nan', 'nat', 'none') "
                f"AND (CAST({date_sql} AS TEXT) GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]' "
                f"OR CAST({date_sql} AS TEXT) GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')"
                )
                df =db .execute_query (f"""
                    SELECT
                        COUNT(*) as count,
                        (SELECT MAX({date_sql}) FROM technical_indicators WHERE {valid_date_filter}) as max_date,
                        COUNT(DISTINCT {stock_sql}) as stock_count,
                        (SELECT MIN({date_sql}) FROM technical_indicators WHERE {valid_date_filter}) as min_date
                    FROM technical_indicators;
                """)
            else :
                df =db .execute_query (f"""
                    SELECT
                        COUNT(*) as count,
                        NULL as max_date,
                        COUNT(DISTINCT {stock_sql}) as stock_count,
                        NULL as min_date
                    FROM technical_indicators;
                """)
            if not df .empty :
                cnt =int (df .iloc [0 ]['count'])
                max_d =df .iloc [0 ]['max_date']
                min_d =df .iloc [0 ]['min_date']
                stock_cnt =int (df .iloc [0 ]['stock_count'])

                def fmt_d (d ):
                    if not d :return None
                    d_str =str (d )
                    return f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:]}"if len (d_str )==8 else d_str

                return self._annotate_sqlite_read_mode({
                'latest_date':fmt_d (max_d ),
                'total_records':cnt ,
                'file_count':stock_cnt ,
                'date_range':{'start_date':fmt_d (min_d ),'end_date':fmt_d (max_d )},
                'status':'ok'if cnt >0 else 'empty'
                }, db)
            return self._annotate_sqlite_read_mode(
                {'latest_date':None ,'total_records':0 ,'file_count':0 ,'status':'empty'}, db
            )
        except Exception as e :
            import logging
            logging .getLogger (__name__ ).warning (f"[UpdateService] 從 SQLite 獲取技術指標狀態失敗: {e}")
            return {'latest_date':None ,'total_records':0 ,'file_count':0 ,'status':f'error: {e}'}

    def check_technical_indicator_latest_coverage (self )->Dict [str ,Any ]:
        """Check whether the latest daily price date has matching technical coverage."""
        if not getattr (self .config ,'use_sqlite',False ):
            return {'success':False ,'status':'unavailable','message':'SQLite disabled'}
        if not self._sqlite_status_db_exists():
            return {
                'success':False,
                'status':'unavailable',
                'message':f'SQLite 資料庫不存在：{getattr(self.config, "db_file", "")}',
            }
        try :
            db =self ._sqlite_status_manager ()
            min_days =int (getattr (self .config ,'min_data_days',30 )or 30 )
            query ="""
                WITH latest AS (
                    SELECT MAX("日期") AS latest_date FROM daily_prices
                ),
                eligible(stock_code) AS (
                    SELECT p."證券代號"
                    FROM daily_prices p
                    GROUP BY p."證券代號"
                    HAVING COUNT(*) >= ?
                       AND MAX(p."日期") = (SELECT latest_date FROM latest)
                ),
                covered(stock_code) AS (
                    SELECT DISTINCT t."證券代號"
                    FROM technical_indicators t
                    WHERE t."日期" = (SELECT latest_date FROM latest)
                )
                SELECT
                    (SELECT latest_date FROM latest) AS daily_latest_date,
                    (SELECT MAX("日期") FROM technical_indicators) AS technical_latest_date,
                    (SELECT COUNT(*) FROM daily_prices WHERE "日期" = (SELECT latest_date FROM latest)) AS daily_latest_rows,
                    (SELECT COUNT(*) FROM eligible) AS eligible_stock_count,
                    (SELECT COUNT(*) FROM eligible e JOIN covered c ON c.stock_code = e.stock_code) AS covered_stock_count;
            """
            df =db .execute_query (query ,params =(min_days ,))
            if df .empty :
                return {'success':False ,'status':'empty','message':'technical coverage query returned no rows'}
            row =df .iloc [0 ]
            daily_latest =row ['daily_latest_date']
            technical_latest =row ['technical_latest_date']
            eligible_count =int (row ['eligible_stock_count']or 0 )
            covered_count =int (row ['covered_stock_count']or 0 )
            is_current =bool (
            daily_latest
            and technical_latest
            and str (technical_latest )>=str (daily_latest )
            and covered_count >=eligible_count
            )
            return self._annotate_sqlite_read_mode({
                'success':True ,
                'status':'ok'if is_current else 'lagging',
            'is_current':is_current ,
            'daily_latest_date':daily_latest ,
            'technical_latest_date':technical_latest ,
            'daily_latest_rows':int (row ['daily_latest_rows']or 0 ),
            'eligible_stock_count':eligible_count ,
                'covered_stock_count':covered_count ,
                'missing_stock_count':max (eligible_count -covered_count ,0 ),
            }, db)
        except Exception as e :
            import logging
            logging .getLogger (__name__ ).warning (f"[UpdateService] 技術指標最新日覆蓋檢查失敗: {e}")
            return {'success':False ,'status':f'error: {e}','message':str (e )}

    def check_data_status (self )->Dict [str ,Any ]:
        """檢查數據狀態"""
        import pandas as pd
        from datetime import datetime
        import logging

        logger =logging .getLogger (__name__ )
        logger .info ("[UpdateService] 開始檢查數據狀態")

        # 🌟 如果啟用 SQLite，直接從資料庫極速統計！
        if getattr (self .config ,'use_sqlite',False ):
            try :
                result =compose_sqlite_status_read_model ({
                'daily_data':self ._status_from_sqlite ('daily_prices'),
                'market_index':self ._status_from_sqlite ('market_indices'),
                'industry_index':self ._status_from_sqlite ('industry_indices'),
                'broker_branch':self ._broker_status_from_sqlite (),
                'technical_indicators':self ._technical_status_from_sqlite (),
                'monthly_revenue':self ._monthly_revenue_status_from_sqlite (),
                }, apply_freshness=True)
                logger .info ("[UpdateService] 成功從 SQLite 資料庫極速獲取數據狀態！")
                return result
            except Exception as sql_err :
                logger .warning (f"[UpdateService] 從 SQLite 檢查數據狀態失敗: {sql_err}，將降級為 CSV 檢查...")

        result ={
        'daily_data':{
        'latest_date':None ,
        'total_records':0 ,
        'status':'unknown'
        },
        'market_index':{
        'latest_date':None ,
        'total_records':0 ,
        'status':'unknown'
        },
        'industry_index':{
        'latest_date':None ,
        'total_records':0 ,
        'status':'unknown'
        }
        }

        try :
            result ['daily_data']=self ._status_from_csv_file (self .config .stock_data_file ,'日期')
            result ['market_index']=self ._status_from_csv_file (self .config .market_index_file ,'日期')
            result ['industry_index']=self ._status_from_csv_file (self .config .industry_index_file ,'日期')
            result ['broker_branch']=self .check_broker_branch_data_status ()
            result ['technical_indicators']=self ._check_technical_indicator_status ()
            return result
        except Exception as fast_error :
            logger .warning (f"[UpdateService] 快速狀態檢查失敗，改用舊路徑: {fast_error}")

            # 檢查每日股票數據（stock_data_whole.csv）
        stock_file =self .config .stock_data_file
        logger .debug (f"[UpdateService] 檢查每日股票數據文件: {stock_file}")
        if stock_file .exists ():
            try :
                logger .debug (f"[UpdateService] 文件存在，開始讀取")
                with open (stock_file ,'r',encoding ='utf-8-sig')as f :
                    total_records =sum (1 for _ in f )-1 # 減去標題行
                result ['daily_data']['total_records']=total_records
                logger .debug (f"[UpdateService] 每日股票數據總記錄數: {total_records:,}")

                try :
                    header_df =pd .read_csv (stock_file ,encoding ='utf-8-sig',nrows =0 )
                    if '日期'not in header_df .columns :
                        result ['daily_data']['status']='ok'
                    else :
                        df_dates =pd .read_csv (
                        stock_file ,
                        encoding ='utf-8-sig',
                        on_bad_lines ='skip',
                        engine ='python',
                        usecols =['日期']
                        )
                        df_tail =df_dates
                except Exception as e :
                    try :
                        if total_records >10000 :
                            skip_rows =list (range (1 ,total_records -10000 +1 ))
                            df_tail =pd .read_csv (
                            stock_file ,
                            encoding ='utf-8-sig',
                            on_bad_lines ='skip',
                            engine ='python',
                            skiprows =skip_rows
                            )
                        else :
                            df_tail =pd .read_csv (
                            stock_file ,
                            encoding ='utf-8-sig',
                            on_bad_lines ='skip',
                            engine ='python'
                            )
                    except :
                        df_tail =pd .DataFrame ()

                if '日期'in df_tail .columns and len (df_tail )>0 :
                    df_tail ['日期']=df_tail ['日期'].astype (str )
                    valid_dates =df_tail [df_tail ['日期'].notna ()&(df_tail ['日期']!='nan')&(df_tail ['日期']!='')]['日期']
                    if len (valid_dates )>0 :
                        latest_date_str =valid_dates .max ()
                        try :
                            if len (latest_date_str )==8 and latest_date_str .isdigit ():
                                latest_date =datetime .strptime (latest_date_str ,'%Y%m%d').strftime ('%Y-%m-%d')
                            else :
                                latest_date =pd .to_datetime (latest_date_str ,errors ='coerce')
                                if pd .notna (latest_date ):
                                    latest_date =latest_date .strftime ('%Y-%m-%d')
                                else :
                                    latest_date =latest_date_str
                            result ['daily_data']['latest_date']=latest_date
                            result ['daily_data']['status']='ok'
                        except :
                            result ['daily_data']['latest_date']=latest_date_str
                            result ['daily_data']['status']='ok'
                    else :
                        result ['daily_data']['status']='ok'
                else :
                    result ['daily_data']['status']='ok'
            except Exception as e :
                result ['daily_data']['status']=f'error: {str(e)}'

                # 檢查大盤指數數據
        market_file =self .config .market_index_file
        logger .debug (f"[UpdateService] 檢查大盤指數文件: {market_file}")
        if market_file .exists ():
            try :
                df =pd .read_csv (
                market_file ,
                encoding ='utf-8-sig',
                on_bad_lines ='skip',
                engine ='python'
                )
                result ['market_index']['total_records']=len (df )

                if '日期'in df .columns :
                    df ['日期']=df ['日期'].astype (str )
                    valid_dates =df [df ['日期'].notna ()&(df ['日期']!='nan')&(df ['日期']!='')]['日期']
                    if len (valid_dates )>0 :
                        latest_date =pd .to_datetime (valid_dates ,errors ='coerce').max ()
                        if pd .notna (latest_date ):
                            result ['market_index']['latest_date']=latest_date .strftime ('%Y-%m-%d')
                            result ['market_index']['status']='ok'
                            logger .debug (f"[UpdateService] 大盤指數最新日期: {latest_date.strftime('%Y-%m-%d')}")
            except Exception as e :
                result ['market_index']['status']=f'error: {str(e)}'
                logger .warning (f"[UpdateService] 檢查大盤指數時發生錯誤: {str(e)}")
        else :
            logger .debug (f"[UpdateService] 大盤指數文件不存在: {market_file}")

            # 檢查產業指數數據
        industry_file =self .config .industry_index_file
        logger .debug (f"[UpdateService] 檢查產業指數文件: {industry_file}")
        if industry_file .exists ():
            try :
                df =pd .read_csv (
                industry_file ,
                encoding ='utf-8-sig',
                on_bad_lines ='skip',
                engine ='python'
                )
                result ['industry_index']['total_records']=len (df )

                if '日期'in df .columns :
                    df ['日期']=df ['日期'].astype (str )
                    valid_dates =df [df ['日期'].notna ()&(df ['日期']!='nan')&(df ['日期']!='')]['日期']
                    if len (valid_dates )>0 :
                        parsed_dates =[]
                        for date_str in valid_dates :
                            try :
                                if len (date_str )==8 and date_str .isdigit ():
                                    parsed_date =datetime .strptime (date_str ,'%Y%m%d')
                                else :
                                    parsed_date =pd .to_datetime (date_str ,errors ='coerce')
                                if pd .notna (parsed_date ):
                                    parsed_dates .append (parsed_date )
                            except :
                                continue

                        if parsed_dates :
                            latest_industry_date =max (parsed_dates )
                            result ['industry_index']['latest_date']=latest_industry_date .strftime ('%Y-%m-%d')
                            result ['industry_index']['status']='ok'
                        else :
                            latest_date_str =valid_dates .max ()
                            result ['industry_index']['latest_date']=latest_date_str
                            result ['industry_index']['status']='ok'
            except Exception as e :
                result ['industry_index']['status']=f'error: {str(e)}'

        result ['broker_branch']=self .check_broker_branch_data_status ()
        result ['technical_indicators']=self ._check_technical_indicator_status ()

        return result

    def check_data_overview (self )->Dict [str ,Any ]:
        """取得全部資料頁使用的輕量狀態摘要，不執行深度檢查或自動修復"""
        # 🌟 如果啟用 SQLite，直接從資料庫極速統計！
        if getattr (self .config ,'use_sqlite',False ):
            try :
                overview =compose_sqlite_status_read_model ({
                'daily_data':self ._status_from_sqlite ('daily_prices'),
                'market_index':self ._status_from_sqlite ('market_indices'),
                'industry_index':self ._status_from_sqlite ('industry_indices'),
                'broker_branch':self ._broker_status_from_sqlite (),
                'technical_indicators':self ._technical_status_from_sqlite (),
                'monthly_revenue':self ._monthly_revenue_status_from_sqlite (),
                },is_overview =True ,apply_freshness =True )
                return overview
            except Exception as sql_err :
                import logging
                logging .getLogger (__name__ ).warning (f"[UpdateService] 從 SQLite check_data_overview 失敗: {sql_err}")

        manifest =self ._read_data_status_manifest ()
        sources =manifest .get ('sources',{})

        overview ={
        'daily_data':self ._overview_csv_status ('daily_data',self .config .stock_data_file ,'日期',sources ),
        'market_index':self ._overview_csv_status ('market_index',self .config .market_index_file ,'日期',sources ),
        'industry_index':self ._overview_csv_status ('industry_index',self .config .industry_index_file ,'日期',sources ),
        'broker_branch':self ._overview_broker_branch_status (sources ),
        'technical_indicators':self ._overview_technical_status (sources ),
        'monthly_revenue':sources .get ('monthly_revenue',{
        'latest_date':None ,
        'total_records':0 ,
        'status':'sqlite only',
        }),
        }
        return overview

    def check_source_detail (self ,source :str )->Dict [str ,Any ]:
        """取得單一資料來源的詳細狀態，供切入 subtab 或手動檢查使用"""
        source_map ={
        'daily':'daily_data',
        'daily_data':'daily_data',
        'market':'market_index',
        'market_index':'market_index',
        'industry':'industry_index',
        'industry_index':'industry_index',
        'broker_branch':'broker_branch',
        'technical':'technical_indicators',
        'technical_indicators':'technical_indicators',
        'monthly_revenue':'monthly_revenue',
        }
        normalized =source_map .get (source )
        if normalized is None :
            return {'latest_date':None ,'total_records':0 ,'status':f'unknown source: {source}'}

            # 🌟 如果啟用 SQLite，直接從資料庫極速統計！
        if getattr (self .config ,'use_sqlite',False ):
            try :
                if normalized =='daily_data':
                    detail =self ._status_from_sqlite ('daily_prices')
                elif normalized =='market_index':
                    detail =self ._status_from_sqlite ('market_indices')
                elif normalized =='industry_index':
                    detail =self ._status_from_sqlite ('industry_indices')
                elif normalized =='broker_branch':
                    detail =self ._broker_status_from_sqlite ()
                elif normalized =='technical_indicators':
                    detail =self ._technical_status_from_sqlite ()
                else :
                    detail =self ._monthly_revenue_status_from_sqlite ()
                if normalized in {"market_index", "industry_index", "technical_indicators"}:
                    # 單一詳情也必須以同一份 daily reference 判定落後，
                    # 避免 overview 與下鑽頁出現 split-brain 狀態。
                    reference = self ._status_from_sqlite ("daily_prices")
                    detail = compose_sqlite_status_read_model(
                        {"daily_data": reference, normalized: detail},
                        apply_freshness=True,
                    ).get(normalized, detail)
                self ._update_data_status_manifest (normalized ,detail )
                return detail
            except Exception as sql_err :
                import logging
                logging .getLogger (__name__ ).warning (f"[UpdateService] 從 SQLite check_source_detail 失敗: {sql_err}")

        if normalized =='daily_data':
            detail =self ._status_from_csv_file (self .config .stock_data_file ,'日期')
        elif normalized =='market_index':
            detail =self ._status_from_csv_file (self .config .market_index_file ,'日期')
        elif normalized =='industry_index':
            detail =self ._status_from_csv_file (self .config .industry_index_file ,'日期')
        elif normalized =='broker_branch':
            detail =self .check_broker_branch_data_status ()
        elif normalized =='technical_indicators':
            detail =self ._check_technical_indicator_status ()
        else :
            detail ={'latest_date':None ,'total_records':0 ,'status':'sqlite only'}

        self ._update_data_status_manifest (normalized ,detail )
        return detail

    def _read_data_status_manifest (self )->Dict [str ,Any ]:
        """讀取資料狀態 manifest，格式錯誤時回傳空 manifest"""
        import json

        if not self .status_manifest_file .exists ():
            return {'sources':{}}
        try :
            with open (self .status_manifest_file ,'r',encoding ='utf-8')as f :
                data =json .load (f )
            if not isinstance (data ,dict ):
                return {'sources':{}}
            data .setdefault ('sources',{})
            return data
        except Exception :
            return {'sources':{}}

    def _write_data_status_manifest (self ,manifest :Dict [str ,Any ])->None :
        """寫入資料狀態 manifest"""
        import json

        self .status_manifest_file .parent .mkdir (parents =True ,exist_ok =True )
        with open (self .status_manifest_file ,'w',encoding ='utf-8')as f :
            json .dump (manifest ,f ,ensure_ascii =False ,indent =2 )

    def _update_data_status_manifest (self ,source :str ,status :Dict [str ,Any ])->None :
        """更新單一資料來源的 manifest 摘要"""
        from datetime import datetime

        manifest =self ._read_data_status_manifest ()
        manifest .setdefault ('sources',{})
        manifest ['sources'][source ]={
        **status ,
        'checked_at':datetime .now ().isoformat (timespec ='seconds'),
        }
        manifest ['updated_at']=datetime .now ().isoformat (timespec ='seconds')
        self ._write_data_status_manifest (manifest )

    def _overview_csv_status (
    self ,
    source :str ,
    path :Path ,
    date_column :str ,
    manifest_sources :Dict [str ,Any ],
    )->Dict [str ,Any ]:
        """取得單一 CSV 的輕量 overview，避免完整掃描大檔"""
        from datetime import datetime

        cached =manifest_sources .get (source ,{})
        status ={
        'latest_date':cached .get ('latest_date'),
        'total_records':cached .get ('total_records',0 ),
        'status':cached .get ('status','unknown'),
        'file_size_mb':0.0 ,
        'modified_at':None ,
        'checked_at':cached .get ('checked_at'),
        'is_overview':True ,
        }
        if not path .exists ():
            status ['status']='missing'
            return status

        stat =path .stat ()
        status ['file_size_mb']=round (stat .st_size /1024 /1024 ,2 )
        status ['modified_at']=datetime .fromtimestamp (stat .st_mtime ).isoformat (timespec ='seconds')

        summary =self ._tail_csv_date_summary (path ,date_column )
        if summary .get ('latest_date'):
            status ['latest_date']=summary ['latest_date']
        if status ['status']in {'unknown','missing'}:
            status ['status']='summary'
        return status

    def _overview_broker_branch_status (self ,manifest_sources :Dict [str ,Any ])->Dict [str ,Any ]:
        """取得券商分點輕量 overview，不載入 BrokerBranchUpdateService"""
        import pandas as pd

        cached =manifest_sources .get ('broker_branch',{})
        status ={
        'latest_date':cached .get ('latest_date'),
        'total_records':cached .get ('total_records',0 ),
        'broker_count':cached .get ('broker_count',0 ),
        'status':cached .get ('status','unknown'),
        'checked_at':cached .get ('checked_at'),
        'is_overview':True ,
        }

        registry_file =self .config .broker_branch_registry_file
        if not registry_file .exists ():
            status ['status']='missing'
            return status

        try :
            registry =pd .read_csv (registry_file ,encoding ='utf-8-sig')
            if 'is_active'in registry .columns :
                registry =registry [registry ['is_active']==True ]
            status ['broker_count']=len (registry )
        except Exception :
            status ['status']='registry_error'
            return status

        latest_dates =[]
        for branch_dir in self .config .broker_flow_dir .glob ('*'):
            merged_file =branch_dir /'meta'/'merged.csv'
            if not merged_file .exists ():
                continue
            summary =self ._tail_csv_date_summary (merged_file ,'date')
            if summary .get ('latest_date'):
                latest_dates .append (summary ['latest_date'])

        if latest_dates :
            status ['latest_date']=max (latest_dates )
            status ['status']='summary'
        elif status ['status']=='unknown':
            status ['status']='empty'
        return status

    def _overview_technical_status (self ,manifest_sources :Dict [str ,Any ])->Dict [str ,Any ]:
        """取得技術指標輕量 overview"""
        cached =manifest_sources .get ('technical_indicators',{})
        status ={
        'latest_date':cached .get ('latest_date'),
        'total_records':cached .get ('total_records',0 ),
        'file_count':0 ,
        'status':cached .get ('status','unknown'),
        'checked_at':cached .get ('checked_at'),
        'is_overview':True ,
        }
        tech_dir =self .config .technical_dir
        status ['file_count']=len (list (tech_dir .glob ('*_indicators.csv')))if tech_dir .exists ()else 0
        if self .config .all_stocks_data_file .exists ():
            summary =self ._tail_csv_date_summary (self .config .all_stocks_data_file ,'日期')
            if summary .get ('latest_date'):
                status ['latest_date']=summary ['latest_date']
            if status ['status']in {'unknown','missing'}:
                status ['status']='summary'
        elif status ['file_count']:
            status ['status']='summary'
        else :
            status ['status']='missing'
        return status

    def _tail_csv_date_summary (self ,path :Path ,date_column :str ,tail_rows :int =300 )->Dict [str ,Any ]:
        """只讀取 CSV 尾端少量日期欄位，供 overview 使用"""
        from collections import deque
        import csv
        import pandas as pd

        latest_date =None
        if not path .exists ():
            return {'latest_date':None }

        tail :deque [str ]=deque (maxlen =tail_rows )
        try :
            with open (path ,'r',encoding ='utf-8-sig',newline ='')as f :
                reader =csv .reader (f )
                header =next (reader ,None )
                if not header or date_column not in header :
                    return {'latest_date':None }
                date_idx =header .index (date_column )
                for row in reader :
                    if len (row )>date_idx and row [date_idx ]:
                        tail .append (row [date_idx ])
            dates =[date for date in tail if date and date !='nan']
            if dates :
                parsed =pd .to_datetime (dates ,errors ='coerce')
                parsed =parsed [pd .notna (parsed )]
                if len (parsed )>0 :
                    latest_date =parsed .max ().strftime ('%Y-%m-%d')
                else :
                    latest_date =max (dates )
            return {'latest_date':latest_date }
        except Exception :
            return {'latest_date':None }

    def _check_technical_indicator_status (self )->Dict [str ,Any ]:
        """快速檢查技術指標彙整檔與個股指標檔狀態"""
        import logging

        logger =logging .getLogger (__name__ )
        status :Dict [str ,Any ]={
        'latest_date':None ,
        'total_records':0 ,
        'file_count':0 ,
        'date_range':{'start_date':None ,'end_date':None },
        'status':'unknown'
        }

        try :
            tech_dir =self .config .technical_dir
            tech_files =list (tech_dir .glob ('*_indicators.csv'))if tech_dir .exists ()else []
            status ['file_count']=len (tech_files )

            all_file =self .config .all_stocks_data_file
            dates =[]
            if all_file .exists ():
                summary =self ._summarize_csv_file (all_file ,'日期')
                status ['total_records']=summary ['total_records']
                if summary ['latest_date']:
                    dates .append (summary ['latest_date'])
                if summary ['start_date']:
                    status ['date_range']['start_date']=summary ['start_date']

            if not dates and tech_files :
                for file in tech_files [:20 ]:
                    summary =self ._summarize_csv_file (file ,'日期')
                    if summary ['latest_date']:
                        dates .append (summary ['latest_date'])

            valid_dates =[d for d in dates if d and d !='nan']
            if valid_dates :
                import pandas as pd

                parsed =pd .to_datetime (valid_dates ,errors ='coerce')
                parsed =parsed [pd .notna (parsed )]
                if len (parsed )>0 :
                    start_date =status ['date_range']['start_date']or parsed .min ().strftime ('%Y-%m-%d')
                    end_date =parsed .max ().strftime ('%Y-%m-%d')
                    status ['latest_date']=end_date
                    status ['date_range']={'start_date':start_date ,'end_date':end_date }
                    status ['status']='ok'
                else :
                    status ['latest_date']=max (valid_dates )
                    status ['status']='ok'
            elif tech_files or all_file .exists ():
                status ['status']='empty'
            else :
                status ['status']='missing'

            return status
        except Exception as e :
            logger .warning (f"[UpdateService] 檢查技術指標狀態失敗: {e}")
            status ['status']=f'error: {str(e)}'
            return status

    def _status_from_csv_file (self ,path :Path ,date_column :str )->Dict [str ,Any ]:
        """以快速摘要產生一般 CSV 資料狀態"""
        summary =self ._summarize_csv_file (path ,date_column )
        status ={
        'latest_date':summary ['latest_date'],
        'total_records':summary ['total_records'],
        'status':'unknown'
        }
        if not path .exists ():
            status ['status']='missing'
        elif summary ['total_records']==0 :
            status ['status']='empty'
        else :
            status ['status']='ok'
        return status

    def _summarize_csv_file (self ,path :Path ,date_column :str ,tail_rows :int =5000 )->Dict [str ,Any ]:
        """以低記憶體方式取得 CSV 行數與尾端日期摘要"""
        from collections import deque
        import csv
        import pandas as pd

        summary ={
        'total_records':0 ,
        'start_date':None ,
        'latest_date':None ,
        }
        if not path .exists ():
            return summary

        tail :deque [str ]=deque (maxlen =tail_rows )
        total_records =0
        start_date =None
        latest_date =None
        try :
            with open (path ,'r',encoding ='utf-8-sig',newline ='')as f :
                reader =csv .reader (f )
                header =next (reader ,None )
                if not header or date_column not in header :
                    return {
                    'total_records':0 ,
                    'start_date':None ,
                    'latest_date':None ,
                    }
                date_idx =header .index (date_column )
                for row in reader :
                    total_records +=1
                    if len (row )>date_idx and row [date_idx ]:
                        if start_date is None :
                            start_date =row [date_idx ]
                        tail .append (row [date_idx ])

            dates =[date for date in tail if date and date !='nan']
            if dates :
                parsed =pd .to_datetime (dates ,errors ='coerce')
                parsed =parsed [pd .notna (parsed )]
                if len (parsed )>0 :
                    latest_date =parsed .max ().strftime ('%Y-%m-%d')
                    if start_date :
                        start =pd .to_datetime (start_date ,errors ='coerce')
                        if pd .notna (start ):
                            start_date =start .strftime ('%Y-%m-%d')
                else :
                    latest_date =max (dates )
            return {
            'total_records':total_records ,
            'start_date':start_date ,
            'latest_date':latest_date ,
            }
        except Exception :
            return summary

    def merge_daily_data (
    self ,
    force_all :bool =False ,
    cancel_callback :Optional [Callable[[],bool ]]=None,
    progress_callback :Optional [Callable[[str, int], None]]=None
    )->Dict [str ,Any ]:
        """合併每日股票數據

        將 daily_price/ 目錄中的 CSV 文件合併到 stock_data_whole.csv

        Args:
            force_all: 是否強制重新合併所有數據（忽略現有數據）
            cancel_callback: 合作式取消回調；在檔案／讀取批次／寫入批次邊界停止
            progress_callback: 可選的 (訊息, 百分比) 回調；只報告安全操作進度

        Returns:
            dict: {
                'success': bool,
                'message': str,
                'merged_files': int,
                'total_records': int,
                'cancelled': optional bool indicating cooperative cancellation
            }
        """
        import pandas as pd
        import shutil
        from datetime import datetime
        import logging
        import traceback

        logger =logging .getLogger (__name__ )

        _emit_update_progress(progress_callback, "準備合併每日資料", 0)

        # ✅ 記錄輸入參數
        logger .info (
        f"[UpdateService] 開始合併每日股票數據: "
        f"force_all={force_all}"
        )

        if _is_cancel_requested(cancel_callback):
            return {
            'success':False ,
            'cancelled':True ,
            'message':'每日資料合併已取消（尚未開始）',
            'merged_files':0 ,
            'total_records':0
            }

        try :
        # 直接調用 merge 腳本的函數
            import os
            import sys
            import importlib .util

            merge_script =self .project_root /'scripts'/'merge_daily_data.py'
            logger .debug (f"[UpdateService] 合併腳本路徑: {merge_script}")

            if not merge_script .exists ():
                logger .error (f"[UpdateService] 找不到合併腳本: {merge_script}")
                return {
                'success':False ,
                'message':f'找不到合併腳本: {merge_script}',
                'merged_files':0 ,
                'total_records':0
                }

                # 動態導入 merge 函數
            logger .debug (f"[UpdateService] 開始動態導入合併模組")
            try :
                spec =importlib .util .spec_from_file_location ("merge_daily_data",merge_script )
                if spec is None or spec .loader is None :
                    error_msg =f"無法創建模組規格: {merge_script}"
                    logger .error (f"[UpdateService] {error_msg}")
                    return {
                    'success':False ,
                    'message':error_msg ,
                    'merged_files':0 ,
                    'total_records':0
                    }

                merge_module =importlib .util .module_from_spec (spec )
                spec .loader .exec_module (merge_module )
                logger .debug (f"[UpdateService] 模組導入成功")
            except Exception as e :
                error_msg =f"導入合併模組時發生錯誤: {str(e)}"
                logger .error (f"[UpdateService] {error_msg}")
                logger .error (traceback .format_exc ())
                return {
                'success':False ,
                'message':error_msg ,
                'merged_files':0 ,
                'total_records':0
                }

                # 檢查函數是否存在
            if not hasattr (merge_module ,'merge_daily_data'):
                error_msg =f"合併模組中找不到 merge_daily_data 函數"
                logger .error (f"[UpdateService] {error_msg}")
                return {
                'success':False ,
                'message':error_msg ,
                'merged_files':0 ,
                'total_records':0
                }

                # 執行合併函數（傳遞 force_all 參數）
            logger .info (f"[UpdateService] 開始執行合併函數: force_all={force_all}")
            try :
            # ✅ 傳遞 config 給合併函數（如果它支持的話）
            # 先嘗試傳遞 config，如果不支持則只傳 force_all
                import inspect
                merge_func =merge_module .merge_daily_data
                sig =inspect .signature (merge_func )
                params =list (sig .parameters .keys ())
                merge_kwargs: dict[str, Any] ={'force_all':force_all}
                if 'config'in params :
                    merge_kwargs ['config']=self .config
                if 'cancel_callback'in params and cancel_callback is not None:
                    merge_kwargs ['cancel_callback']=cancel_callback
                if (
                    progress_callback is not None
                    and (
                        'progress_callback' in params
                        or any(
                            parameter.kind is inspect.Parameter.VAR_KEYWORD
                            for parameter in sig.parameters.values()
                        )
                    )
                ):
                    merge_kwargs['progress_callback'] = progress_callback

                if 'config'in params :
                    logger .debug (f"[UpdateService] 合併函數支持 config 參數，傳遞配置")
                    merge_result =merge_func (**merge_kwargs )
                else :
                    logger .debug (f"[UpdateService] 合併函數不支持 config 參數，只傳遞 force_all")
                    merge_result =merge_func (**merge_kwargs )

                if isinstance (merge_result ,dict )and merge_result .get ('cancelled'):
                    return merge_result

                # 目前合併腳本已回傳原子提交後的統計；直接沿用可避免
                # 再次完整掃描輸出檔，並讓取消旗標不必等待 line-count。
                if (
                    isinstance(merge_result, dict)
                    and merge_result.get("success") is True
                    and "total_records" in merge_result
                ):
                    return merge_result

                logger .info (f"[UpdateService] 合併函數執行完成")
            except Exception as e :
                error_msg =f"執行合併函數時發生錯誤: {str(e)}"
                logger .error (f"[UpdateService] {error_msg}")
                logger .error (traceback .format_exc ())
                return {
                'success':False ,
                'message':error_msg ,
                'merged_files':0 ,
                'total_records':0
                }

                # 讀取合併後的數據統計
            stock_file =self .config .stock_data_file
            if stock_file .exists ():
            # 計算總記錄數（使用更高效的方式）
                try :
                    df =pd .read_csv (stock_file ,encoding ='utf-8-sig',nrows =1000 )
                    # 讀取文件總行數
                    with open (stock_file ,'r',encoding ='utf-8-sig')as f :
                        total_records =sum (1 for _ in f )-1 # 減去標題行

                        # 獲取最新日期（讀取文件最後幾行，因為最新日期通常在文件末尾）
                    if '日期'in df .columns :
                        try :
                        # 方法1：讀取最後 10000 行來獲取最新日期
                        # 先獲取總行數
                            with open (stock_file ,'r',encoding ='utf-8-sig')as f :
                                total_lines =sum (1 for _ in f )-1 # 減去標題行

                            if total_lines >0 :
                            # 讀取最後 10000 行（或全部，如果總行數少於 10000）
                                skip_rows =max (0 ,total_lines -10000 )
                                df_tail =pd .read_csv (
                                stock_file ,
                                encoding ='utf-8-sig',
                                usecols =['日期'],
                                skiprows =range (1 ,skip_rows +1 )# 跳過前面的行，保留標題行
                                )

                                if len (df_tail )>0 :
                                # 轉換日期格式
                                    df_tail ['日期']=df_tail ['日期'].astype (str )
                                    valid_dates =df_tail [
                                    df_tail ['日期'].notna ()&
                                    (df_tail ['日期']!='nan')&
                                    (df_tail ['日期']!='')&
                                    (df_tail ['日期']!='None')
                                    ]['日期']

                                    if len (valid_dates )>0 :
                                    # 嘗試解析日期並找到最大值
                                        parsed_dates =[]
                                        for date_str in valid_dates :
                                            try :
                                            # 嘗試 YYYYMMDD 格式
                                                if len (date_str )==8 and date_str .isdigit ():
                                                    parsed_dates .append (datetime .strptime (date_str ,'%Y%m%d'))
                                                    # 嘗試 YYYY-MM-DD 格式
                                                elif len (date_str )==10 and '-'in date_str :
                                                    parsed_dates .append (datetime .strptime (date_str ,'%Y-%m-%d'))
                                                else :
                                                # 嘗試自動解析
                                                    parsed =pd .to_datetime (date_str ,errors ='coerce')
                                                    if pd .notna (parsed ):
                                                        parsed_dates .append (parsed .to_pydatetime ())
                                            except :
                                                continue

                                        if parsed_dates :
                                            latest_date =max (parsed_dates ).strftime ('%Y-%m-%d')
                                            message =f'數據合併成功，最新日期：{latest_date}'
                                        else :
                                        # 如果解析失敗，使用字符串比較（降級方案）
                                            latest_date_str =valid_dates .max ()
                                            if len (latest_date_str )==8 and latest_date_str .isdigit ():
                                                latest_date =datetime .strptime (latest_date_str ,'%Y%m%d').strftime ('%Y-%m-%d')
                                            else :
                                                latest_date =latest_date_str
                                            message =f'數據合併成功，最新日期：{latest_date}'
                                    else :
                                        message ='數據合併成功'
                                else :
                                    message ='數據合併成功'
                            else :
                                message ='數據合併成功'
                        except Exception as e :
                            logger .warning (f"[UpdateService] 讀取最新日期時出錯: {str(e)}")
                            message ='數據合併成功'
                    else :
                        message ='數據合併成功'

                        # ✅ 記錄結果
                    logger .info (
                    f"[UpdateService] 合併完成: "
                    f"總記錄數={total_records:,}, 訊息={message}"
                    )
                    return {
                    'success':True ,
                    'message':message ,
                    'merged_files':0 ,# merge 函數內部會處理，這裡不統計
                    'total_records':total_records
                    }
                except Exception as e :
                    logger .warning (f"[UpdateService] 讀取統計信息時出錯: {str(e)}")
                    return {
                    'success':True ,
                    'message':f'數據合併完成（讀取統計信息時出錯：{str(e)}）',
                    'merged_files':0 ,
                    'total_records':0
                    }
            else :
                logger .error (f"[UpdateService] 合併完成但找不到輸出文件: {stock_file}")
                return {
                'success':False ,
                'message':'合併完成但找不到輸出文件',
                'merged_files':0 ,
                'total_records':0
                }

        except Exception as e :
            import traceback
            logger .error (f"[UpdateService] 合併過程出錯: {str(e)}")
            logger .error (traceback .format_exc ())
            return {
            'success':False ,
            'message':f'合併過程出錯：{str(e)}\n{traceback.format_exc()}',
            'merged_files':0 ,
            'total_records':0
            }

    def update_broker_branch (
    self ,
    start_date :str ,
    end_date :str ,
    branch_system_keys :Optional [List [str ]]=None ,
    delay_seconds :float =0.5 ,
    force_all :bool =False ,
    progress_callback =None ,
    cancel_callback :Optional [Callable[[],bool ]]=None
    )->Dict [str ,Any ]:
        """更新券商分點資料

        Args:
            start_date: 開始日期（YYYY-MM-DD）
            end_date: 結束日期（YYYY-MM-DD）
            branch_system_keys: 要更新的分點列表（None=全部）
            delay_seconds: 請求間隔（秒）
            force_all: 是否強制重新抓取
            progress_callback: 進度回調函數

        Returns:
            dict: 更新結果
        """
        import logging
        logger =logging .getLogger (__name__ )

        logger .info (
        f"[UpdateService] 開始更新券商分點資料: "
        f"start_date={start_date}, end_date={end_date}, "
        f"branch_system_keys={branch_system_keys}, force_all={force_all}"
        )

        try :
            from app_module .broker_branch_update_service import BrokerBranchUpdateService

            service =BrokerBranchUpdateService (self .config )
            result =service .update_broker_branch_data (
            start_date =start_date ,
            end_date =end_date ,
            branch_system_keys =branch_system_keys ,
            delay_seconds =delay_seconds ,
            force_all =force_all ,
            progress_callback =progress_callback ,
            cancel_callback =cancel_callback
            )

            logger .info (f"[UpdateService] 券商分點資料更新完成: success={result.get('success', False)}")
            return result

        except Exception as e :
            import traceback
            error_msg =f"更新券商分點資料時發生錯誤: {str(e)}"
            logger .error (f"[UpdateService] {error_msg}")
            logger .error (traceback .format_exc ())
            return {
            'success':False ,
            'message':error_msg ,
            'updated_dates':[],
            'failed_dates':[],
            'skipped_dates':[],
            'non_trading_dates':[],
            'updated_branches':[],
            'failed_branches':[],
            'total_processed':0 ,
            'total_records':0
            }

    def merge_broker_branch_data (
    self ,
    branch_system_keys :Optional [List [str ]]=None ,
    force_all :bool =False ,
    cancel_callback :Optional [Callable[[],bool ]]=None,
    progress_callback :Optional [Callable[[str, int], None]]=None
    )->Dict [str ,Any ]:
        """合併券商分點資料

        Args:
            branch_system_keys: 要合併的分點列表（None=全部）
            force_all: 是否強制重新合併
            progress_callback: 可選的 (訊息, 百分比) 回調
            cancel_callback: 合作式取消回調；在分點／檔案邊界停止

        Returns:
            dict: 合併結果
        """
        import logging
        logger =logging .getLogger (__name__ )

        logger .info (
        f"[UpdateService] 開始合併券商分點資料: "
        f"branch_system_keys={branch_system_keys}, force_all={force_all}"
        )

        try :
            from app_module .broker_branch_update_service import BrokerBranchUpdateService

            service =BrokerBranchUpdateService (self .config )
            result =service .merge_broker_branch_data (
            branch_system_keys =branch_system_keys ,
            force_all =force_all ,
            progress_callback =progress_callback ,
            cancel_callback =cancel_callback
            )

            logger .info (f"[UpdateService] 券商分點資料合併完成: success={result.get('success', False)}")
            return result

        except Exception as e :
            import traceback
            error_msg =f"合併券商分點資料時發生錯誤: {str(e)}"
            logger .error (f"[UpdateService] {error_msg}")
            logger .error (traceback .format_exc ())
            return {
            'success':False ,
            'message':error_msg ,
            'merged_branches':[],
            'merged_files':0 ,
            'new_records':0 ,
            'total_records':0 ,
            'date_range':{'start_date':'','end_date':''},
            'duplicate_records':0
            }

    def check_broker_branch_data_status (
    self ,
    branch_system_keys :Optional [List [str ]]=None
    )->Dict [str ,Any ]:
        """檢查券商分點資料狀態

        Args:
            branch_system_keys: 要檢查的分點列表（None=全部）

        Returns:
            dict: 狀態字典
        """
        import logging
        logger =logging .getLogger (__name__ )

        logger .info (f"[UpdateService] 檢查券商分點資料狀態: branch_system_keys={branch_system_keys}")

        try :
            from app_module .broker_branch_update_service import BrokerBranchUpdateService

            service =BrokerBranchUpdateService (self .config )
            result =service .check_broker_branch_data_status (
            branch_system_keys =branch_system_keys
            )

            logger .info (f"[UpdateService] 券商分點資料狀態檢查完成: status={result.get('status', 'unknown')}")
            return result

        except Exception as e :
            import traceback
            error_msg =f"檢查券商分點資料狀態時發生錯誤: {str(e)}"
            logger .error (f"[UpdateService] {error_msg}")
            logger .error (traceback .format_exc ())
            return {
            'latest_date':None ,
            'total_records':0 ,
            'date_count':0 ,
            'broker_count':0 ,
            'date_range':{'start_date':None ,'end_date':None },
            'status':'error'
            }

    def _get_indicator_latest_date (self ,indicator_file :Path )->Optional [str ]:
        """取得單一技術指標檔的最新日期"""
        if not indicator_file .exists ():
            return None

        try :
            import pandas as pd

            df_dates =pd .read_csv (
            indicator_file ,
            encoding ='utf-8-sig',
            usecols =['日期'],
            on_bad_lines ='skip',
            engine ='python'
            )
            if df_dates .empty :
                return None

            parsed =pd .to_datetime (df_dates ['日期'],errors ='coerce')
            parsed =parsed [pd .notna (parsed )]
            if len (parsed )==0 :
                return None

            return parsed .max ().strftime ('%Y-%m-%d')
        except Exception :
            return None

    def _run_technical_indicator_process_pool(
        self,
        *,
        calculator,
        tasks: List[tuple[str, Any]],
        ignore_existing: bool,
        max_workers: int,
        max_in_flight: Optional[int],
        max_retries: int,
        cancel_callback: Optional[Callable[[], bool]],
        progress_callback,
        logger,
    ) -> Dict[str, Any]:
        """執行受控技術指標 worker，並由父程序逐股保存結果。

        ``tasks`` 已由 ``calculate_technical_indicators`` 完成日期與 warm-up
        判斷，因此這裡不重新篩資料。worker 回傳的 DataFrame 只在記憶體中
        傳回，所有 CSV／SQLite 寫入仍走既有 calculator 與後續整合 writer。
        """
        from app_module.technical_indicator_process_pool import (
            run_bounded_indicator_pool,
        )
        import pandas as pd

        pool = run_bounded_indicator_pool(
            tasks,
            max_workers=max_workers,
            max_in_flight=max_in_flight,
            max_retries=max_retries,
            cancel_callback=cancel_callback,
            logger=logger,
        )
        raw_results = pool.get("results", {})
        successful: List[str] = []
        failed: List[str] = list(pool.get("failed_ids", []))
        stored: List[Any] = []

        total = len(tasks)
        for index, (stock_id, group_df) in enumerate(tasks, start=1):
            if _is_cancel_requested(cancel_callback):
                break
            precomputed = raw_results.get(stock_id)
            if not isinstance(precomputed, pd.DataFrame) or precomputed.empty:
                if stock_id not in failed:
                    failed.append(stock_id)
                continue
            if progress_callback:
                progress_callback(
                    f"process-pool 父程序寫入 {stock_id} ({index}/{total})...",
                    20 + int((index / max(total, 1)) * 70),
                )
            try:
                result = calculator.calculate_and_store_indicators(
                    group_df,
                    stock_id,
                    output_dir=self.config.technical_dir,
                    ignore_existing=ignore_existing,
                    precomputed_result=precomputed,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("process-pool 父程序保存股票 %s 失敗: %s", stock_id, exc)
                result = None
            if isinstance(result, pd.DataFrame):
                stored.append(result)
                successful.append(stock_id)
            elif stock_id not in failed:
                failed.append(stock_id)

        cancelled = _is_cancel_requested(cancel_callback) or pool.get("status") == "cancelled"
        unique_failed = list(dict.fromkeys(str(stock_id) for stock_id in failed))
        summary = {
            key: value
            for key, value in pool.items()
            if key != "results"
        }
        summary["parent_single_writer"] = True
        summary["parent_written_stock_count"] = len(stored)
        summary["parent_write_failed_count"] = len(unique_failed)
        summary["cancelled"] = cancelled
        summary["production_worker_enabled"] = True
        return {
            "report": summary,
            "all_data": stored,
            "success_count": len(successful),
            "updated_stocks": successful,
            "fail_count": len(unique_failed),
            "failed_stocks": unique_failed,
            "cancelled": cancelled,
        }

    def calculate_technical_indicators (
    self ,
    target_stock :Optional [str ]=None ,
    force_all :bool =False ,
    start_date :Optional [str ]=None ,
    progress_callback =None ,
    cancel_callback :Optional [Callable[[],bool ]]=None ,
    ignore_existing_files :bool =False ,
    incremental_lookback_days :int =120 ,
    technical_process_pool :Optional [bool ]=None ,
    technical_process_pool_workers :Optional [int ]=None ,
    technical_process_pool_max_in_flight :Optional [int ]=None ,
    technical_process_pool_max_retries :Optional [int ]=None
    )->Dict [str ,Any ]:
        """計算技術指標

        Args:
            target_stock: 要處理的特定股票代號，如為None則處理所有股票
            force_all: 是否強制更新所有數據（忽略日期檢查）
            start_date: 指定開始更新的日期，如為None則自動檢測
            progress_callback: 進度回調函數 (message: str, progress: int) -> None
            cancel_callback: 合作式取消回調；只在安全邊界停止後續計算／寫入
            ignore_existing_files: 是否忽略現有指標文件，直接覆蓋（用於修復有問題的文件）
            incremental_lookback_days: 增量更新時往前回補的交易日數，避免技術指標缺少歷史序列
            technical_process_pool: 明確覆寫 process-pool feature flag；預設讀取 config，且預設關閉
            technical_process_pool_workers: process-pool worker 上限；僅在 feature flag 開啟時使用
            technical_process_pool_max_in_flight: parent queue 的最大 in-flight 任務數
            technical_process_pool_max_retries: 單一股票 worker 失敗時的有限重試次數

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
        import os
        import sys
        import importlib .util
        import logging
        import traceback

        logger =logging .getLogger (__name__ )

        process_pool_enabled = (
            bool(getattr(self.config, "technical_process_pool_enabled", False))
            if technical_process_pool is None
            else bool(technical_process_pool)
        )
        process_pool_workers = int(
            technical_process_pool_workers
            if technical_process_pool_workers is not None
            else getattr(self.config, "technical_process_pool_workers", 2)
        )
        process_pool_max_in_flight = (
            technical_process_pool_max_in_flight
            if technical_process_pool_max_in_flight is not None
            else getattr(self.config, "technical_process_pool_max_in_flight", 4)
        )
        process_pool_max_retries = int(
            technical_process_pool_max_retries
            if technical_process_pool_max_retries is not None
            else getattr(self.config, "technical_process_pool_max_retries", 1)
        )

        logger .info (
        f"[UpdateService] 開始計算技術指標: "
        f"target_stock={target_stock}, force_all={force_all}, start_date={start_date}, "
        f"process_pool_enabled={process_pool_enabled}"
        )

        if _is_cancel_requested(cancel_callback):
            return {
            'success':False ,
            'cancelled':True ,
            'message':'技術指標計算已取消（尚未開始）',
            'total_stocks':0 ,
            'success_count':0 ,
            'fail_count':0 ,
            'insufficient_data_count':0 ,
            'updated_stocks':[] ,
            'failed_stocks':[] ,
            'start_date':'',
            'end_date':''
            }

        if progress_callback :
            progress_callback ("初始化技術指標計算器...",5 )

        try :
        # 導入技術指標計算模組
            from analysis_module .technical_analysis .technical_indicators import TechnicalIndicatorCalculator

            # 創建計算器
            calculator =TechnicalIndicatorCalculator (logger )

            if progress_callback :
                progress_callback ("讀取股票數據...",10 )

                # 讀取股票數據
            import pandas as pd
            if getattr (self .config ,'use_sqlite',False ):
                try :
                    from data_module .db_manager import DBManager
                    db =DBManager (self .config )
                    logger .info ("優先從 SQLite 載入價格數據進行技術指標計算...")
                    table_info_df =db .execute_query ("PRAGMA table_info(daily_prices);")
                    table_columns =[str (v ).strip ()for v in table_info_df ["name"]]if not table_info_df .empty else []
                    date_column ="日期"
                    stock_column ="股票代號"
                    for candidate in ("日期","date","trade_date","trading_date","Date"):
                        if candidate in table_columns :
                            date_column =candidate
                            break
                    for candidate in ("證券代號","股票代號","stock_code","stock_id"):
                        if candidate in table_columns :
                            stock_column =candidate
                            break
                    stock_data =db .execute_query (
                    f'SELECT * FROM daily_prices ORDER BY "{date_column}" ASC, "{stock_column}" ASC;'
                    )
                    if not stock_data .empty :
                    # 確保日期與代號為字串型態，與後續邏輯一致
                        if date_column in stock_data .columns :
                            stock_data [date_column ]=stock_data [date_column ].astype (str )
                        if stock_column in stock_data .columns :
                            stock_data [stock_column ]=stock_data [stock_column ].astype (str ).str .strip ()
                            # 將欄位型態轉換以相容原有業務邏輯
                        numeric_cols =['成交股數','成交筆數','成交金額','開盤價','最高價','最低價','收盤價','漲跌價差',
                        '最後揭示買價','最後揭示買量','最後揭示賣價','最後揭示賣量','本益比']
                        for col in numeric_cols :
                            if col in stock_data .columns :
                                stock_data [col ]=pd .to_numeric (stock_data [col ],errors ='coerce')
                    else :
                        logger .warning ("SQLite daily_prices 表為空，降級讀取 CSV...")
                        stock_data =pd .read_csv (self .config .stock_data_file ,dtype ={'證券代號':str },low_memory =False )
                except Exception as sql_err :
                    logger .warning (f"從 SQLite 載入價格數據失敗: {sql_err}，降級讀取 CSV...")
                    stock_data =pd .read_csv (self .config .stock_data_file ,dtype ={'證券代號':str },low_memory =False )
            else :
                stock_data =pd .read_csv (self .config .stock_data_file ,dtype ={'證券代號':str },low_memory =False )

            stock_code_column =next (
            (col for col in ('證券代號','股票代號','證券代號','stock_id','stock_code')if col in stock_data .columns ),
            None ,
            )
            if stock_code_column is None :
                stock_code_candidates =[c for c in stock_data .columns if '代號'in str (c )]
                stock_code_column =stock_code_candidates [0 ]if stock_code_candidates else None
            if stock_code_column is None :
                return {
                'success':False ,
                'message':'技術指標計算失敗：找不到可用的股票代碼文桩',
                'total_stocks':0 ,
                'success_count':0 ,
                'fail_count':1 ,
                'insufficient_data_count':0 ,
                'updated_stocks':[],
                'failed_stocks':[target_stock ]if target_stock else [],
                'start_date':'',
                'end_date':''
                }

            stock_data =stock_data .copy ()
            stock_data [stock_code_column ]=stock_data [stock_code_column ].astype (str ).str .strip ()
            stock_data =stock_data [stock_data [stock_code_column ].str .match (r'^\d{4}$')]

            # 如果指定了特定股票，只處理該股票
            if target_stock :
                if target_stock not in stock_data [stock_code_column ].unique ():
                    return {
                    'success':False ,
                    'message':f'指定的股票 {target_stock} 不存在於股票數據中',
                    'total_stocks':0 ,
                    'success_count':0 ,
                    'fail_count':1 ,
                    'insufficient_data_count':0 ,
                    'updated_stocks':[],
                    'failed_stocks':[target_stock ],
                    'start_date':'',
                    'end_date':''
                    }
                stock_data =stock_data [stock_data [stock_code_column ]==target_stock ]

            auto_incremental =not force_all and start_date is None
            if auto_incremental :
                logger .info (
                f"使用智慧增量技術指標計算，回看 {incremental_lookback_days} 個交易日"
                )
                if progress_callback :
                    progress_callback (
                    f"使用智慧增量模式，回看 {incremental_lookback_days} 個交易日",
                    15
                    )
            elif force_all :
                start_date =None
                logger .info ("強制更新所有數據")
                if progress_callback :
                    progress_callback ("強制更新所有數據",15 )

                    # 批次處理
            grouped =stock_data .groupby (stock_code_column )
            total_stocks =len (grouped )

            if _is_cancel_requested(cancel_callback):
                return {
                'success':False ,
                'cancelled':True ,
                'message':'技術指標計算已取消（完成資料載入後）',
                'total_stocks':total_stocks ,
                'success_count':0 ,
                'fail_count':0 ,
                'insufficient_data_count':0 ,
                'updated_stocks':[] ,
                'failed_stocks':[] ,
                'start_date':'',
                'end_date':''
                }

            if progress_callback :
                progress_callback (f"開始處理 {total_stocks} 支股票的技術指標...",20 )

            results :Dict [str ,Any ]={
            'total_stocks':total_stocks ,
            'success_count':0 ,
            'fail_count':0 ,
            'insufficient_data_count':0 ,
            'updated_stocks':[],
            'failed_stocks':[],
            'insufficient_stocks':[],
            'start_date':'',
            'end_date':'',
            'technical_process_pool': {
                'enabled': process_pool_enabled,
                'production_worker_enabled': process_pool_enabled,
                'parent_single_writer': True,
            },
            }

            all_data =[]
            pending_process_pool_tasks :List [tuple[str ,pd .DataFrame ]]=[]
            min_date ="9999-12-31"
            max_date ="1900-01-01"

            # 處理每檔股票
            for idx ,(stock_id ,group_df )in enumerate (grouped ):
                if _is_cancel_requested(cancel_callback):
                    results ['start_date']=min_date if min_date !="9999-12-31"else "未知"
                    results ['end_date']=max_date if max_date !="1900-01-01"else "未知"
                    return {
                    'success':False ,
                    'cancelled':True ,
                    'message':f'技術指標計算已取消（停止於 {stock_id} 前）',
                    **results
                    }
                progress =20 +int ((idx /total_stocks )*70 )# 20% 到 90%
                if progress_callback :
                    progress_callback (f"處理 {stock_id} ({idx+1}/{total_stocks})...",progress )

                group_df =group_df .copy ()
                for legacy_col ,canonical_col in (
                ('日期','日期'),
                ('證券代號','證券代號'),
                ):
                    if legacy_col ==canonical_col :
                        continue
                    if legacy_col in group_df .columns and canonical_col in group_df .columns :
                        group_df =group_df .drop (columns =[legacy_col ])
                    elif legacy_col in group_df .columns :
                        group_df =group_df .rename (columns ={legacy_col :canonical_col })

                        # 跳過數據量不足的股票
                if len (group_df )<self .config .min_data_days :
                    logger .debug (f"股票 {stock_id} 數據量不足，跳過")
                    results ['insufficient_data_count']+=1
                    results ['insufficient_stocks'].append (stock_id )
                    continue

                group_date_column ='日期'if '日期'in group_df .columns else (
                '日期'if '日期'in group_df .columns else None
                )

                # 記錄日期範圍
                if group_date_column :
                    group_min_date =str (group_df [group_date_column ].min ())
                    group_max_date =str (group_df [group_date_column ].max ())
                    min_date =min (min_date ,group_min_date )
                    max_date =max (max_date ,group_max_date )

                    # 檢查是否需要更新（基於日期）
                if auto_incremental and group_date_column :
                    indicator_file =self .config .technical_dir /f'{stock_id}_indicators.csv'
                    existing_latest_date =self ._get_indicator_latest_date (indicator_file )
                    if existing_latest_date and not ignore_existing_files :
                        date_col =group_df [group_date_column ]
                        if not pd .api .types .is_string_dtype (date_col ):
                            date_col =date_col .astype (str )
                        normalized_dates =pd .to_datetime (date_col ,errors ='coerce')
                        latest_ts =pd .to_datetime (existing_latest_date ,errors ='coerce')
                        if pd .notna (latest_ts ):
                            has_new_data =(normalized_dates >latest_ts ).any ()
                            if not has_new_data :
                                logger .debug (f"股票 {stock_id} 沒有新數據需要更新")
                                continue

                            sorted_dates =(
                            pd .Series (normalized_dates .dropna ().unique ())
                            .sort_values ()
                            .reset_index (drop =True )
                            )
                            previous_dates =sorted_dates [sorted_dates <=latest_ts ]
                            if len (previous_dates )>0 :
                                warmup_index =max (len (previous_dates )-incremental_lookback_days ,0 )
                                warmup_start =previous_dates .iloc [warmup_index ]
                            else :
                                warmup_start =sorted_dates .iloc [0 ]
                            group_df =group_df [normalized_dates >=warmup_start ]
                            logger .debug (
                            f"股票 {stock_id} 智慧增量從 {warmup_start.strftime('%Y-%m-%d')} 重新計算"
                            )
                    else :
                        logger .debug (f"股票 {stock_id} 無既有指標檔，使用完整股價序列計算")
                elif start_date and group_date_column and not force_all :
                    date_col =group_df [group_date_column ]
                    if not pd .api .types .is_string_dtype (date_col ):
                        date_col =date_col .astype (str )
                    filtered_df =group_df [date_col >start_date ]
                    if len (filtered_df )==0 :
                        logger .debug (f"股票 {stock_id} 沒有新數據需要更新")
                        continue
                    group_df =filtered_df

                    # 計算並保存指標
                if _is_cancel_requested(cancel_callback):
                    results ['start_date']=min_date if min_date !="9999-12-31"else "未知"
                    results ['end_date']=max_date if max_date !="1900-01-01"else "未知"
                    return {
                    'success':False ,
                    'cancelled':True ,
                    'message':f'技術指標計算已取消（尚未處理 {stock_id}）',
                    **results
                    }
                if process_pool_enabled:
                    # 日期／增量 warm-up 已在父程序決定；worker 只接收這個
                    # 精確 frame 做純計算，之後仍由父程序逐股寫入。
                    pending_process_pool_tasks.append((str(stock_id), group_df.copy()))
                    continue
                try :
                    result =calculator .calculate_and_store_indicators (
                    group_df ,
                    stock_id ,
                    output_dir =self .config .technical_dir ,
                    ignore_existing =ignore_existing_files or force_all
                    )

                    if isinstance (result ,pd .DataFrame ):
                        all_data .append (result )
                        results ['success_count']+=1
                        results ['updated_stocks'].append (stock_id )
                        logger .debug (f"成功處理股票 {stock_id}")
                    else :
                        results ['fail_count']+=1
                        results ['failed_stocks'].append (stock_id )
                        logger .warning (f"處理股票 {stock_id} 失敗")
                    if _is_cancel_requested(cancel_callback):
                        results ['start_date']=min_date if min_date !="9999-12-31"else "未知"
                        results ['end_date']=max_date if max_date !="1900-01-01"else "未知"
                        return {
                        'success':False ,
                        'cancelled':True ,
                        'message':f'技術指標計算已取消（已完成 {stock_id}）',
                        **results
                        }
                except Exception as e :
                    logger .error (f"處理股票 {stock_id} 時發生錯誤: {str(e)}")
                    results ['fail_count']+=1
                    results ['failed_stocks'].append (stock_id )

                    if _is_cancel_requested(cancel_callback):
                        results ['start_date']=min_date if min_date !="9999-12-31"else "未知"
                        results ['end_date']=max_date if max_date !="1900-01-01"else "未知"
                        return {
                        'success':False ,
                        'cancelled':True ,
                        'message':f'技術指標計算已取消（處理 {stock_id} 後）',
                        **results
                        }

                    # 更新結果日期範圍
            process_pool_report = None
            if process_pool_enabled and pending_process_pool_tasks:
                process_pool_result = self._run_technical_indicator_process_pool(
                    calculator=calculator,
                    tasks=pending_process_pool_tasks,
                    ignore_existing=ignore_existing_files or force_all,
                    max_workers=process_pool_workers,
                    max_in_flight=process_pool_max_in_flight,
                    max_retries=process_pool_max_retries,
                    cancel_callback=cancel_callback,
                    progress_callback=progress_callback,
                    logger=logger,
                )
                process_pool_report = process_pool_result["report"]
                results["technical_process_pool"] = process_pool_report
                all_data.extend(process_pool_result["all_data"])
                results["success_count"] += process_pool_result["success_count"]
                results["updated_stocks"].extend(process_pool_result["updated_stocks"])
                results["fail_count"] += process_pool_result["fail_count"]
                results["failed_stocks"].extend(process_pool_result["failed_stocks"])
                if process_pool_result["cancelled"]:
                    results ['start_date']=min_date if min_date !="9999-12-31"else "未知"
                    results ['end_date']=max_date if max_date !="1900-01-01"else "未知"
                    return {
                    'success':False ,
                    'cancelled':True ,
                    'message':'技術指標 process-pool 計算已取消（已停止後續合併）',
                    **results
                    }
            results ['start_date']=min_date if min_date !="9999-12-31"else "未知"
            results ['end_date']=max_date if max_date !="1900-01-01"else "未知"

            if _is_cancel_requested(cancel_callback):
                return {
                'success':False ,
                'cancelled':True ,
                'message':'技術指標計算已取消（尚未合併輸出）',
                **results
                }

            # 合併並儲存所有結果
            if all_data :
                if progress_callback :
                    progress_callback ("合併所有指標數據...",90 )

                logger .info ("合併所有指標數據...")

                if _is_cancel_requested(cancel_callback):
                    return {
                    'success':False ,
                    'cancelled':True ,
                    'message':'技術指標計算已取消（合併前）',
                    **results
                    }

                # ✅ 數據驗證：檢查每個 DataFrame 的完整性
                valid_data =[]
                for idx ,df in enumerate (all_data ):
                    if df is None or len (df )==0 :
                        logger .warning (f"跳過空數據（索引 {idx}）")
                        continue

                    df =df .rename (columns ={
                    '日期':'日期',
                    '證券代號':'證券代號',
                    })
                    df =df .loc [:,~df .columns .duplicated (keep ='last')]

                    # 檢查必要欄位
                    required_cols =['日期','證券代號']
                    missing_cols =[col for col in required_cols if col not in df .columns ]
                    if missing_cols :
                        logger .warning (f"跳過缺少必要欄位 {missing_cols} 的數據（索引 {idx}）")
                        continue

                        # 檢查日期欄位是否有效
                    if '日期'in df .columns :
                        date_col =pd .to_datetime (df ['日期'],errors ='coerce')
                        valid_dates =date_col .notna ().sum ()
                        if valid_dates ==0 :
                            logger .warning (f"跳過日期欄位無效的數據（索引 {idx}）")
                            continue

                    valid_data .append (df )

                if not valid_data :
                    logger .error ("沒有有效的數據可以合併！")
                    return {
                    'success':False ,
                    'message':'沒有有效的數據可以合併，請檢查技術指標計算結果',
                    **results
                    }

                    # 合併有效數據
                final_df =pd .concat (valid_data ,ignore_index =True )

                # ✅ 數據驗證：檢查合併後的數據
                logger .info (f"合併前有效數據數量: {len(valid_data)}")
                logger .info (f"合併後總筆數: {len(final_df):,}")
                logger .info (f"合併後股票數量: {final_df['證券代號'].nunique() if '證券代號' in final_df.columns else 'N/A'}")

                # 檢查是否有重複數據
                if '日期'in final_df .columns and '證券代號'in final_df .columns :
                    duplicates =final_df .duplicated (subset =['日期','證券代號']).sum ()
                    if duplicates >0 :
                        logger .warning (f"發現 {duplicates} 筆重複數據（日期+證券代號），將去重")
                        final_df =final_df .drop_duplicates (subset =['日期','證券代號'],keep ='last')
                        logger .info (f"去重後總筆數: {len(final_df):,}")

                save_path =self .config .all_stocks_data_file
                skip_csv_save =getattr (self .config ,'use_sqlite',False )and auto_incremental

                if _is_cancel_requested(cancel_callback):
                    return {
                    'success':False ,
                    'cancelled':True ,
                    'message':'技術指標計算已取消（寫入整合輸出前）',
                    **results
                    }

                if not skip_csv_save :
                # 創建備份
                    if save_path .exists ():
                        logger .info (f"備份現有的整合指標文件: {save_path}")
                        self .config .create_backup (save_path )

                        # 保存
                    final_df .to_csv (save_path ,index =False ,encoding ='utf-8-sig')
                    file_size_mb =save_path .stat ().st_size /1024 /1024
                    logger .info (f"已保存整合指標到: {save_path}（檔案大小: {file_size_mb:.2f} MB）")
                else :
                    logger .info ("智慧增量模式且啟用 SQLite，跳過大型 all_stocks_data.csv 合併重寫，直接使用增量寫入 SQLite。")

                    # 🌟 如果啟用 SQLite，同步將指標寫入 SQLite technical_indicators 表中
                if getattr (self .config ,'use_sqlite',False ):
                    if _is_cancel_requested(cancel_callback):
                        return {
                        'success':False ,
                        'cancelled':True ,
                        'message':'技術指標計算已取消（尚未寫入 SQLite）',
                        **results
                        }
                    logger .info ("檢測到啟用 SQLite，開始同步寫入資料庫 technical_indicators 表...")
                    if progress_callback :
                        progress_callback ("正在將指標寫入 SQLite 資料庫...",95 )
                    try :
                        from data_module .db_manager import DBManager
                        db =DBManager (self .config )

                        df_db =final_df .copy ()
                        df_db =df_db .rename (columns ={
                        '日期':'日期',
                        '證券代號':'證券代號',
                        })
                        df_db =df_db .loc [:,~df_db .columns .duplicated (keep ='last')]
                        # 統一日期與代號格式
                        df_db ['日期']=df_db ['日期'].apply (lambda x :str (x ).replace ('-','').replace ('/',''))
                        df_db ['證券代號']=df_db ['證券代號'].astype (str ).str .zfill (4 )

                        # 剔除價格與重複欄位以防止重複儲存
                        cols_to_drop =[c for c in ['證券名稱','開盤價','最高價','最低價','收盤價','成交股數','成交量']if c in df_db .columns ]
                        if cols_to_drop :
                            df_db =df_db .drop (columns =cols_to_drop )

                            # 確保 non-PK 欄位為數值型
                        for col in df_db .columns :
                            if col not in ['日期','證券代號']:
                                df_db [col ]=pd .to_numeric (df_db [col ],errors ='coerce')

                                # 判斷是否為增量更新
                        if auto_incremental :
                            logger .info ("智慧增量模式下，僅刪除並更新變更的技術指標記錄...")
                            with db .connect ()as conn :
                                conn .executemany (
                                "DELETE FROM technical_indicators WHERE 證券代號 = ? AND 日期 = ?;",
                                df_db [['證券代號','日期']].values .tolist ()
                                )
                            success =db .write_dataframe ('technical_indicators',df_db ,if_exists ='append')
                        else :
                        # 全量模式下，清空現有 table 進行全新全量寫入
                            logger .info ("全量模式下，清空 technical_indicators 表後全新寫入...")
                            with db .connect ()as conn :
                                conn .execute ("DELETE FROM technical_indicators;")
                            success =db .write_dataframe ('technical_indicators',df_db ,if_exists ='append')
                        if success :
                            logger .info ("技術指標成功批次寫入 SQLite 資料庫！")
                        else :
                            logger .error ("技術指標寫入 SQLite 失敗！")
                    except Exception as sql_err :
                        logger .error (f"技術指標同步寫入 SQLite 時發生錯誤: {sql_err}")

                if progress_callback :
                    progress_callback ("技術指標計算完成",100 )

                    # 生成結果訊息
            message =(
            f"技術指標計算完成：\n"
            f"總處理股票數: {results['total_stocks']}\n"
            f"成功處理數: {results['success_count']}\n"
            f"失敗數: {results['fail_count']}\n"
            f"數據不足股票數: {results['insufficient_data_count']}\n"
            f"處理數據日期範圍: {results['start_date']} 至 {results['end_date']}"
            )

            process_pool_failed = bool(
                process_pool_report
                and process_pool_report.get("status") in {"failed", "partial"}
            )
            return {
            'success':not process_pool_failed ,
            'message':message ,
            **results
            }

        except Exception as e :
            error_msg =f"計算技術指標時發生錯誤: {str(e)}"
            logger .error (error_msg )
            logger .error (traceback .format_exc ())
            return {
            'success':False ,
            'message':f"{error_msg}\n{traceback.format_exc()}",
            'total_stocks':0 ,
            'success_count':0 ,
            'fail_count':0 ,
            'insufficient_data_count':0 ,
            'updated_stocks':[],
            'failed_stocks':[],
            'start_date':'',
            'end_date':''
            }

    def export_table_to_csv (
    self ,
    table_name :str ,
    target_path :Path ,
    start_date :Optional [str ]=None ,
    end_date :Optional [str ]=None ,
    cancel_callback :Optional [Callable[[],bool ]]=None,
    progress_callback :Optional [Callable[[str, int], None]]=None
    )->Dict [str ,Any ]:
        """從 SQLite 匯出指定表和日期範圍的資料至 CSV

        Args:
            table_name: SQLite 表名
            target_path: 匯出的 CSV 檔案路徑
            start_date: 開始日期（YYYYMMDD 或 YYYY-MM-DD）
            end_date: 結束日期（YYYYMMDD 或 YYYY-MM-DD）
            cancel_callback: 合作式取消回調；在查詢／寫檔安全邊界停止
            progress_callback: 可選的 (訊息, 百分比) 回調；以查詢總筆數估算進度
        """
        import logging
        import os
        import re
        import tempfile

        logger = logging.getLogger(__name__)
        destination = Path(target_path)

        _emit_update_progress(progress_callback, f"準備匯出 {table_name}", 0)

        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name or ""):
            return {
                "success": False,
                "message": f"不允許匯出未知或不安全的 SQLite table：{table_name!r}",
            }

        if _is_cancel_requested(cancel_callback):
            return {
            'success':False ,
            'cancelled':True ,
            'message':f'{table_name} 匯出已取消（尚未開始）'
            }

        try:
            # 匯出屬於讀取既有資料後建立新檔，不能因查詢而建構可寫
            # DBManager（那會初始化 schema／WAL）。
            db = ReadOnlySQLiteManager(self.config.db_file)

            query = f'SELECT * FROM "{table_name}"'
            conditions: list[str] = []
            params: list[Any] = []

            if start_date:
                s_date = self._date_key(start_date)
                if s_date:
                    conditions.append('"日期" >= ?')
                    params.append(s_date)
            if end_date:
                e_date = self._date_key(end_date)
                if e_date:
                    conditions.append('"日期" <= ?')
                    params.append(e_date)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += ' ORDER BY "日期" ASC;'

            logger.info(
                "[UpdateService] 開始從 SQLite 匯出 %s 到 %s，查詢: %s，參數: %s",
                table_name,
                destination,
                query,
                params,
            )

            total_expected: int | None = None
            try:
                count_query = f'SELECT COUNT(*) AS "_total" FROM "{table_name}"'
                if conditions:
                    count_query += " WHERE " + " AND ".join(conditions)
                count_df = db.execute_query(count_query, tuple(params))
                if not count_df.empty:
                    total_expected = max(0, int(count_df.iloc[0]["_total"]))
            except Exception:
                logger.debug("無法取得匯出總筆數，改用無總數進度", exc_info=True)
            _emit_update_progress(
                progress_callback,
                f"開始讀取 {table_name}（預估 {total_expected:,} 筆）"
                if total_expected is not None
                else f"開始讀取 {table_name}（總筆數待讀取）",
                5,
            )

            chunks = db.iter_query(query, tuple(params), chunksize=10_000)
            total_records = 0
            chunk_index = 0
            temp_path: Path | None = None
            temp_fd: int | None = None
            temp_stream: Any = None
            try:
                for chunk in chunks:
                    if _is_cancel_requested(cancel_callback):
                        return {
                            "success": False,
                            "cancelled": True,
                            "processed_records": total_records,
                            "target_preserved": True,
                            "message": f"{table_name} 匯出已取消（停在資料批次邊界，原目標檔保留）",
                        }
                    if chunk.empty:
                        continue

                    chunk_index += 1

                    if "日期" in chunk.columns:
                        chunk = chunk.copy()
                        chunk["日期"] = chunk["日期"].apply(
                            lambda value: (
                                f"{str(value)[:4]}-{str(value)[4:6]}-{str(value)[6:]}"
                                if len(str(value)) == 8
                                else str(value)
                            )
                        )

                    if temp_path is None:
                        if _is_cancel_requested(cancel_callback):
                            return {
                                "success": False,
                                "cancelled": True,
                                "processed_records": total_records,
                                "target_preserved": True,
                                "message": f"{table_name} 匯出已取消（尚未建立暫存檔）",
                            }
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        temp_fd, temp_name = tempfile.mkstemp(
                            prefix=f".{destination.name}.",
                            suffix=".part",
                            dir=str(destination.parent),
                        )
                        temp_path = Path(temp_name)
                        temp_stream = os.fdopen(
                            temp_fd,
                            "w",
                            encoding="utf-8-sig",
                            newline="",
                        )
                        temp_fd = None

                    chunk.to_csv(
                        temp_stream,
                        index=False,
                        header=total_records == 0,
                    )
                    total_records += len(chunk)
                    temp_stream.flush()
                    if total_expected and total_expected > 0:
                        percentage = min(95, 10 + (total_records * 85 // total_expected))
                    else:
                        percentage = min(90, 10 + chunk_index * 5)
                    _emit_update_progress(
                        progress_callback,
                        f"匯出 {table_name}：已處理 {total_records:,} 筆",
                        percentage,
                    )
                    if _is_cancel_requested(cancel_callback):
                        return {
                            "success": False,
                            "cancelled": True,
                            "processed_records": total_records,
                            "target_preserved": True,
                            "message": f"{table_name} 匯出已取消（已完成一批，原目標檔保留）",
                        }

                if total_records == 0:
                    return {
                        "success": False,
                        "message": "沒有符合條件的資料可供匯出",
                        "read_mode": db.last_read_mode,
                    }
                if _is_cancel_requested(cancel_callback):
                    return {
                        "success": False,
                        "cancelled": True,
                        "processed_records": total_records,
                        "target_preserved": True,
                        "message": f"{table_name} 匯出已取消（尚未提交目標檔）",
                    }

                if temp_stream is not None:
                    temp_stream.flush()
                    temp_stream.close()
                    temp_stream = None
                if temp_path is None:
                    raise RuntimeError("匯出未建立暫存檔")
                os.replace(str(temp_path), str(destination))
                temp_path = None
                logger.info("[UpdateService] 成功匯出 %s 筆資料至 %s", total_records, destination)
                _emit_update_progress(progress_callback, f"{table_name} 匯出完成", 100)
                return {
                    "success": True,
                    "message": f"成功匯出 {total_records:,} 筆資料至 {destination.name}",
                    "total_records": total_records,
                    "file_path": str(destination),
                    "read_mode": db.last_read_mode,
                }
            finally:
                if temp_stream is not None:
                    temp_stream.close()
                if temp_fd is not None:
                    os.close(temp_fd)
                if temp_path is not None and temp_path.exists():
                    temp_path.unlink()

        except Exception as e:
            logger .exception (f"[UpdateService] 匯出 {table_name} 失敗")
            return {
            'success':False ,
            'message':f'匯出失敗：{str(e)}'
            }

    def check_decision_data_status(self) -> Dict[str, Any]:
        """讀取明確設定的 candidate DB 狀態；不將正式 DB 偽裝為候選資料。"""
        candidate_db = configured_candidate_db_path()
        tables = {
            "institutional_flow": ("institutional_flows", "institutional"),
            "credit_transaction": ("credit_transactions", "credit"),
            "tdcc_shareholding": ("tdcc_shareholding", "tdcc"),
        }

        def empty_info() -> Dict[str, Any]:
            return {
                "total_records": 0,
                "earliest_date": "無",
                "latest_date": "無",
                "coverage_pct": "無 checkpoint",
                "distinct_dates": 0,
            }

        def inspect_candidate(table_name: str, source: str) -> Dict[str, Any]:
            if candidate_db is None or not candidate_db.exists():
                return empty_info()
            try:
                import sqlite3
                read_only_uri = (
                    f"file:{candidate_db.resolve().as_posix()}?mode=ro"
                )
                with sqlite3.connect(read_only_uri, uri=True) as conn:
                    conn.execute("PRAGMA query_only=ON")
                    row = conn.execute(
                        f"SELECT COUNT(*), MIN(decision_date), MAX(decision_date), "
                        f"COUNT(DISTINCT decision_date) FROM {table_name}"
                    ).fetchone()
                    if row is None or int(row[0]) == 0:
                        return empty_info()
                    try:
                        success_count, attempted_count = conn.execute(
                            """
                            SELECT
                                COUNT(DISTINCT CASE WHEN status = 'SUCCESS' THEN decision_date END),
                                COUNT(DISTINCT CASE WHEN status IN ('SUCCESS', 'FAILED_RETRYABLE') THEN decision_date END)
                            FROM phase3c_backfill_checkpoints WHERE source = ?
                            """,
                            (source,),
                        ).fetchone()
                    except sqlite3.OperationalError:
                        success_count, attempted_count = 0, 0
                    coverage = (
                        f"{(int(success_count) / int(attempted_count) * 100):.1f}%"
                        if attempted_count
                        else "無 checkpoint"
                    )
                    return {
                        "total_records": int(row[0]),
                        "earliest_date": row[1] or "無",
                        "latest_date": row[2] or "無",
                        "coverage_pct": coverage,
                        "distinct_dates": int(row[3]),
                    }
            except Exception:
                return empty_info()

        result: Dict[str, Any] = {}
        for key, (table_name, source) in tables.items():
            info = inspect_candidate(table_name, source)
            has_candidate = info["total_records"] > 0
            result[key] = {
                "candidate_db_exists": candidate_db is not None and candidate_db.exists(),
                "candidate_db_path": str(candidate_db) if candidate_db else "未設定 PHASE3C_CANDIDATE_DB_PATH",
                **info,
                "quality_pit_status": "PROVENANCE_TRACKED" if has_candidate else "UNAVAILABLE",
                "status": (
                    "CANDIDATE_AVAILABLE"
                    if has_candidate
                    else "BLOCKED_NO_HISTORICAL_ENDPOINT"
                    if source == "tdcc"
                    else "MISSING"
                ),
                "disclaimer": "候選研究資料，不參與評分或投資決策",
                "formal_records": 0,
                "candidate_records": info["total_records"],
            }
        return result
