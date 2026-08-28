import pandas as pd
from pathlib import Path
import logging
from datetime import datetime
import shutil
import os
import tempfile
import argparse
import sys
from typing import Callable, Iterator

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.backup_retention import create_retained_backup

# 設置日誌
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def merge_daily_data(
    force_all: bool = False,
    config=None,
    cancel_callback=None,
    progress_callback: Callable[[str, int], None] | None = None,
):
    """合併每日股票數據
    
    Args:
        force_all: 是否強制重新合併所有數據
        config: TWStockConfig 實例（可選），如果提供則使用配置中的路徑
        cancel_callback: 合作式取消回調；在檔案／讀取批次／寫入批次邊界停止，不截斷輸出檔
        progress_callback: 可選的 (訊息, 百分比) 回調；不影響資料寫入邊界
    """
    # ✅ 確保 datetime 在函數內部可用（避免 UnboundLocalError）
    from datetime import datetime as dt_module
    datetime = dt_module

    def is_cancel_requested():
        if cancel_callback is None:
            return False
        try:
            return bool(cancel_callback())
        except Exception:
            return False

    def emit_progress(message: str, percentage: int) -> None:
        """向 UI 報告可理解的階段進度；回調失敗不得中斷合併。"""

        if progress_callback is None:
            return
        try:
            progress_callback(str(message), max(0, min(100, int(percentage))))
        except Exception:
            logger.debug("每日資料合併進度回調失敗", exc_info=True)

    def iter_file_chunks(file_path: Path) -> Iterator[pd.DataFrame]:
        """逐批讀取 CSV，並在取消或例外離開時釋放 pandas reader。"""

        reader = pd.read_csv(
            file_path,
            encoding='utf-8-sig',
            chunksize=50_000,
        )
        try:
            yield from reader
        finally:
            close_reader = getattr(reader, "close", None)
            if callable(close_reader):
                close_reader()

    emit_progress("準備合併每日資料", 0)

    if is_cancel_requested():
        return {
            'success': False,
            'cancelled': True,
            'message': '每日資料合併已取消（尚未開始）',
            'merged_files': 0,
            'total_records': 0,
        }
    
    # 設置路徑
    if config is not None:
        # 使用配置中的路徑
        base_dir = Path(getattr(config, "data_root", getattr(config, "data_dir")))
        daily_price_dir = base_dir / "daily_price"
        tpex_daily_price_dir = Path(getattr(config, "tpex_daily_price_dir", base_dir / "daily_price_tpex"))
        meta_data_dir = base_dir / "meta_data"
        output_file = config.stock_data_file
        backup_dir = meta_data_dir / "backup"
        logger.info(f"使用配置路徑: base_dir={base_dir}")
    else:
        # 降級方案：使用硬編碼路徑（向後兼容）
        base_dir = Path("D:/Min/Python/Project/FA_Data")
        daily_price_dir = base_dir / "daily_price"
        tpex_daily_price_dir = base_dir / "daily_price_tpex"
        meta_data_dir = base_dir / "meta_data"
        output_file = meta_data_dir / "stock_data_whole.csv"
        backup_dir = meta_data_dir / "backup"
        logger.warning(f"未提供 config，使用硬編碼路徑: base_dir={base_dir}")
    
    try:
        emit_progress("檢查每日資料來源", 5)
        # 確保至少一個日價來源目錄存在
        source_dirs = [daily_price_dir]
        if tpex_daily_price_dir.exists():
            source_dirs.append(tpex_daily_price_dir)
        if not any(source_dir.exists() for source_dir in source_dirs):
            raise FileNotFoundError(f"找不到目錄：{daily_price_dir} 或 {tpex_daily_price_dir}")
        
        # 先讀取既有輸入並判斷是否真的需要提交；備份延後到確認
        # 有新資料、即將原子替換整合檔前，讓 no-op 不產生任何備份副作用。
        last_date = None
        existing_record_count = 0
        backup_file: Path | None = None
        if output_file.exists():
            if not force_all:
                # 讀取現有數據（僅在非強制模式下）
                emit_progress("讀取既有每日整合檔", 8)
                existing_df = pd.read_csv(output_file, encoding='utf-8-sig', low_memory=False)
                existing_record_count = len(existing_df)
                # ✅ 修復：確保日期格式正確（YYYYMMDD 字符串）
                max_date = existing_df['日期'].max()
                import numpy as np
                if hasattr(max_date, 'item'):
                    max_date_val = max_date.item()
                else:
                    max_date_val = max_date
                
                if isinstance(max_date_val, (int, float, np.integer, np.floating)):
                    # 如果是數字，轉換為 YYYYMMDD 字符串
                    last_date = str(int(max_date_val))
                    # 確保是8位數
                    if len(last_date) == 8:
                        pass  # 已經是正確格式
                    elif len(last_date) == 6:
                        # 可能是 YYMMDD，需要補年份
                        last_date = '20' + last_date
                    else:
                        # 嘗試轉換為日期再格式化
                        try:
                            date_str = str(int(max_date))
                            if len(date_str) == 8:
                                last_date = date_str
                            else:
                                # 嘗試解析為日期
                                if len(date_str) == 6:
                                    dt = datetime.strptime(date_str, '%y%m%d')
                                else:
                                    dt = datetime.fromtimestamp(max_date / 1000) if max_date > 1000000000 else datetime.fromtimestamp(max_date)
                                last_date = dt.strftime('%Y%m%d')
                        except:
                            last_date = str(int(max_date)).zfill(8)
                elif isinstance(max_date, str):
                    # 如果是字符串，確保是 YYYYMMDD 格式
                    last_date = max_date.replace('-', '').replace('/', '')
                    if len(last_date) != 8:
                        # 嘗試解析日期
                        try:
                            dt = pd.to_datetime(max_date)
                            last_date = dt.strftime('%Y%m%d')
                        except:
                            last_date = max_date
                else:
                    # 其他類型，嘗試轉換
                    try:
                        dt = pd.to_datetime(max_date)
                        last_date = dt.strftime('%Y%m%d')
                    except:
                        last_date = str(max_date).replace('-', '').replace('/', '')
                
                # 確保是8位數字符串
                if len(last_date) != 8 or not last_date.isdigit():
                    logger.warning(f"日期格式異常: {last_date}，嘗試修復...")
                    try:
                        dt = pd.to_datetime(str(max_date))
                        last_date = dt.strftime('%Y%m%d')
                    except:
                        logger.error(f"無法修復日期格式: {last_date}，將使用強制模式")
                        force_all = True
                        last_date = None
                
                logger.info(f"已讀取現有數據，最後更新日期為: {last_date} (原始值: {max_date}, 類型: {type(max_date)})")
            else:
                logger.info("強制模式：將重新合併所有數據")
        
        # 獲取所有CSV文件（TWSE + TPEX）
        if is_cancel_requested():
            return {
                'success': False,
                'cancelled': True,
                'message': '每日資料合併已取消（尚未掃描檔案）',
                'merged_files': 0,
                'total_records': 0,
            }
        all_csv_files: list[Path] = []
        for source_dir in source_dirs:
            if source_dir.exists():
                all_csv_files.extend(source_dir.glob("*.csv"))
        emit_progress(f"掃描到 {len(all_csv_files)} 個每日 CSV", 10)
        if not all_csv_files:
            raise FileNotFoundError(f"在 {daily_price_dir} 或 {tpex_daily_price_dir} 中找不到CSV文件")
        
        # 如果有最後更新日期且非強制模式，只處理新的文件
        if last_date and not force_all:
            # ✅ 修復：確保文件名也是正確格式，並正確比較
            csv_files = []
            for f in all_csv_files:
                file_stem = str(f.stem)
                # 確保文件名是8位數
                if len(file_stem) == 8 and file_stem.isdigit():
                    if file_stem > last_date:
                        csv_files.append(f)
                else:
                    logger.warning(f"文件名格式異常，跳過: {f.name} (stem: {file_stem})")
            
            if not csv_files:
                # 獲取最新文件名用於日誌
                valid_files = [str(f.stem) for f in all_csv_files if len(str(f.stem)) == 8 and str(f.stem).isdigit()]
                latest_file = max(valid_files) if valid_files else 'N/A'
                logger.info(f"沒有新的數據需要更新 (最後日期: {last_date}, 最新文件: {latest_file})")
                no_op_date = last_date or latest_file
                no_op_message = (
                    f"沒有新資料需要合併；目前整合檔已是最新"
                    f"（最新日期：{no_op_date or '未知'}）"
                )
                emit_progress(no_op_message, 100)
                return {
                    'success': True,
                    'cancelled': False,
                    'no_op': True,
                    'message': no_op_message,
                    'merged_files': 0,
                    'total_records': existing_record_count,
                    'latest_date': str(no_op_date) if no_op_date else '',
                    'output_file': str(output_file),
                }
            logger.info(f"找到 {len(csv_files)} 個需要處理的新CSV文件 (最後日期: {last_date})")
        else:
            csv_files = all_csv_files
            if force_all:
                logger.info(f"強制模式：找到 {len(csv_files)} 個CSV文件，將全部重新合併")
            else:
                logger.info(f"找到 {len(csv_files)} 個CSV文件")

        total_files = max(1, len(csv_files))
        emit_progress(f"準備讀取 {len(csv_files)} 個每日 CSV", 15)
        
        # 讀取並合併所有文件
        all_data = []
        if last_date and not force_all:
            all_data.append(existing_df)  # 如果有現有數據且非強制模式，先加入
            
        for file_index, file in enumerate(csv_files, start=1):
            if is_cancel_requested():
                return {
                    'success': False,
                    'cancelled': True,
                    'message': f'每日資料合併已取消（停止於 {file.name} 前）',
                    'merged_files': len(all_data),
                    'total_records': sum(len(item) for item in all_data),
                }
            try:
                # 從文件名獲取日期
                date = file.stem

                # 逐批讀取單一 CSV，讓大型單檔也能在安全邊界觀測取消；
                # 只有整個檔案讀完才加入 all_data，避免半個檔案被誤當成
                # 已完成輸入。最終整合檔仍只會在原子替換前一次提交。
                file_chunks: list[pd.DataFrame] = []
                for chunk_index, chunk in enumerate(
                    iter_file_chunks(file),
                    start=1,
                ):
                    if is_cancel_requested():
                        return {
                            'success': False,
                            'cancelled': True,
                            'message': (
                                f'每日資料合併已取消（停止於 {file.name} '
                                f'第 {chunk_index} 個讀取批次前）'
                            ),
                            'merged_files': len(all_data),
                            'total_records': sum(len(item) for item in all_data),
                        }

                    if chunk.empty:
                        continue

                    # 添加日期列並確保證券代號是 4 位數字串。
                    chunk['日期'] = date
                    chunk['證券代號'] = chunk['證券代號'].astype(str).str.zfill(4)
                    file_chunks.append(chunk)
                    emit_progress(
                        f"讀取每日檔案 {file.name} 批次 {chunk_index} "
                        f"({file_index}/{total_files})",
                        20 + (file_index * 45 // total_files),
                    )

                    if is_cancel_requested():
                        return {
                            'success': False,
                            'cancelled': True,
                            'message': (
                                f'每日資料合併已取消（已讀取 {file.name} '
                                f'第 {chunk_index} 個批次，尚未提交）'
                            ),
                            'merged_files': len(all_data),
                            'total_records': sum(len(item) for item in all_data),
                        }

                if file_chunks:
                    all_data.extend(file_chunks)
                logger.info(f"成功讀取 {file.name}（{len(file_chunks)} 個批次）")
                emit_progress(
                    f"讀取每日檔案 {file.name} 完成 ({file_index}/{total_files})",
                    20 + (file_index * 45 // total_files),
                )
                
            except Exception as e:
                logger.error(f"處理文件 {file.name} 時出錯: {str(e)}")
                emit_progress(
                    f"跳過無法讀取的檔案 {file.name} ({file_index}/{total_files})",
                    20 + (file_index * 45 // total_files),
                )
                continue
        
        if not all_data:
            raise ValueError("沒有成功讀取任何數據")
        
        # 合併所有數據
        merged_data = pd.concat(all_data, ignore_index=True)
        
        # 確保日期欄位是字符串格式（YYYYMMDD）
        merged_data['日期'] = merged_data['日期'].astype(str)
        
        # 重新排序列，把日期放在前面
        columns = ['日期', '證券代號', '證券名稱', '成交股數', '成交筆數', '成交金額', 
                  '開盤價', '最高價', '最低價', '收盤價', '漲跌(+/-)', '漲跌價差', 
                  '最後揭示買價', '最後揭示買量', '最後揭示賣價', '最後揭示賣量', '本益比']
        # 只保留存在的欄位
        available_columns = [col for col in columns if col in merged_data.columns]
        merged_data = merged_data[available_columns]
        
        # 按日期和證券代號排序（日期作為字符串排序）
        merged_data = merged_data.sort_values(['日期', '證券代號'])
        
        # 移除重複數據
        merged_data = merged_data.drop_duplicates(subset=['日期', '證券代號'], keep='last')
        emit_progress("完成排序與去重，準備寫入整合檔", 70)
        
        # 保存合併後的數據。先以同目錄暫存檔逐批寫入，再原子替換目標；
        # 取消或寫入例外不會留下半份 stock_data_whole.csv。
        if is_cancel_requested():
            return {
                'success': False,
                'cancelled': True,
                'message': '每日資料合併已取消（尚未寫入整合檔）',
                'merged_files': len(csv_files),
                'total_records': len(merged_data),
            }

        if output_file.exists():
            emit_progress("建立既有整合檔備份", 71)
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_file = create_retained_backup(output_file, backup_dir)
            if backup_file is None:
                raise FileNotFoundError(output_file)
            logger.info(f"已創建備份文件: {backup_file}")

        output_file.parent.mkdir(parents=True, exist_ok=True)
        temporary_fd, temporary_name = tempfile.mkstemp(
            prefix=f'.{output_file.name}.',
            suffix='.part',
            dir=str(output_file.parent),
        )
        temporary_path: Path | None = Path(temporary_name)
        try:
            temporary_stream = os.fdopen(
                temporary_fd,
                'w',
                encoding='utf-8-sig',
                newline='',
            )
            temporary_fd = -1
            with temporary_stream:
                if merged_data.empty:
                    merged_data.to_csv(temporary_stream, index=False, header=True)
                else:
                    total_chunks = max(1, (len(merged_data) + 49_999) // 50_000)
                    for chunk_index, start in enumerate(range(0, len(merged_data), 50_000), start=1):
                        if is_cancel_requested():
                            return {
                                'success': False,
                                'cancelled': True,
                                'message': '每日資料合併已取消（整合檔尚未提交）',
                                'merged_files': len(csv_files),
                                'total_records': len(merged_data),
                            }
                        chunk = merged_data.iloc[start:start + 50_000]
                        chunk.to_csv(
                            temporary_stream,
                            index=False,
                            header=start == 0,
                        )
                        temporary_stream.flush()
                        emit_progress(
                            f"寫入每日整合檔 ({chunk_index}/{total_chunks})",
                            75 + (chunk_index * 23 // total_chunks),
                        )
                        if is_cancel_requested():
                            return {
                                'success': False,
                                'cancelled': True,
                                'message': '每日資料合併已取消（整合檔尚未提交）',
                                'merged_files': len(csv_files),
                                'total_records': len(merged_data),
                            }

            if is_cancel_requested():
                return {
                    'success': False,
                    'cancelled': True,
                    'message': '每日資料合併已取消（整合檔尚未提交）',
                    'merged_files': len(csv_files),
                    'total_records': len(merged_data),
                }
            os.replace(str(temporary_path), str(output_file))
            temporary_path = None
        finally:
            if temporary_fd >= 0:
                os.close(temporary_fd)
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
        logger.info(f"成功保存合併後的數據到 {output_file}")
        
        # 顯示數據統計
        logger.info(f"合併後的數據形狀: {merged_data.shape}")
        # 日期範圍（使用字符串排序）
        date_min = merged_data['日期'].min()
        date_max = merged_data['日期'].max()
        logger.info(f"日期範圍: {date_min} 到 {date_max}")
        logger.info(f"總共包含 {merged_data['證券代號'].nunique()} 個不同的證券代號")
        emit_progress("每日資料合併完成", 100)
        return {
            'success': True,
            'cancelled': False,
            'message': f'每日資料合併完成：{len(merged_data):,} 筆',
            'merged_files': len(csv_files),
            'total_records': len(merged_data),
            'latest_date': str(date_max),
            'output_file': str(output_file),
        }
        
    except Exception as e:
        import traceback
        error_msg = f"處理過程中出錯: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        # 如果發生錯誤，嘗試恢復備份
        backup_file_obj = locals().get("backup_file")
        output_file_obj = locals().get("output_file")
        if isinstance(backup_file_obj, Path) and isinstance(output_file_obj, Path) and backup_file_obj.exists() and output_file_obj.exists():
            try:
                shutil.copy2(backup_file_obj, output_file_obj)
                logger.info("已恢復備份文件")
            except Exception as restore_error:
                logger.error(f"恢復備份文件時出錯: {str(restore_error)}")
        # 重新拋出異常，讓調用者知道出錯了
        raise

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='合併每日股票數據')
    parser.add_argument('--force-all', action='store_true', 
                       help='強制重新合併所有數據，忽略現有數據')
    args = parser.parse_args()
    
    merge_daily_data(force_all=args.force_all) 
