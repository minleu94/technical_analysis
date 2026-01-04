"""
原子寫入工具模組
提供安全的檔案寫入功能，避免寫入過程中的數據損壞
"""

from pathlib import Path
import pandas as pd
import logging
from typing import Union, Optional

logger = logging.getLogger(__name__)

def atomic_write_df(df: pd.DataFrame, path: Path, **kwargs) -> None:
    """
    原子寫入DataFrame到CSV檔案
    
    Args:
        df: 要寫入的DataFrame
        path: 目標檔案路徑
        **kwargs: 傳遞給to_csv的額外參數
    """
    try:
        # 確保父目錄存在
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # 創建臨時檔案
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        
        # 寫入臨時檔案
        df.to_csv(tmp_path, index=False, **kwargs)
        
        # 原子性移動檔案
        tmp_path.replace(path)
        
        logger.info(f"成功原子寫入檔案: {path}")
        
    except Exception as e:
        # 清理臨時檔案
        if tmp_path.exists():
            tmp_path.unlink()
        logger.error(f"原子寫入失敗: {path}, 錯誤: {str(e)}")
        raise

def atomic_write_parquet(df: pd.DataFrame, path: Path, **kwargs) -> None:
    """
    原子寫入DataFrame到Parquet檔案
    
    Args:
        df: 要寫入的DataFrame
        path: 目標檔案路徑
        **kwargs: 傳遞給to_parquet的額外參數
    """
    try:
        # 確保父目錄存在
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # 創建臨時檔案
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        
        # 寫入臨時檔案
        df.to_parquet(tmp_path, index=False, **kwargs)
        
        # 原子性移動檔案
        tmp_path.replace(path)
        
        logger.info(f"成功原子寫入Parquet檔案: {path}")
        
    except Exception as e:
        # 清理臨時檔案
        if tmp_path.exists():
            tmp_path.unlink()
        logger.error(f"原子寫入Parquet失敗: {path}, 錯誤: {str(e)}")
        raise

def atomic_write_json(data: Union[dict, list], path: Path, **kwargs) -> None:
    """
    原子寫入JSON資料到檔案
    
    Args:
        data: 要寫入的JSON資料
        path: 目標檔案路徑
        **kwargs: 傳遞給json.dump的額外參數
    """
    import json
    
    try:
        # 確保父目錄存在
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # 創建臨時檔案
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        
        # 寫入臨時檔案
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, **kwargs)
        
        # 原子性移動檔案
        tmp_path.replace(path)
        
        logger.info(f"成功原子寫入JSON檔案: {path}")
        
    except Exception as e:
        # 清理臨時檔案
        if tmp_path.exists():
            tmp_path.unlink()
        logger.error(f"原子寫入JSON失敗: {path}, 錯誤: {str(e)}")
        raise

def safe_write_with_dry_run(df: pd.DataFrame, path: Path, dry_run: bool = False, 
                           file_format: str = 'csv', **kwargs) -> None:
    """
    安全的寫入函數，支持乾運行模式
    
    Args:
        df: 要寫入的DataFrame
        path: 目標檔案路徑
        dry_run: 是否為乾運行模式
        file_format: 檔案格式 ('csv', 'parquet', 'json')
        **kwargs: 傳遞給寫入函數的額外參數
    """
    if dry_run:
        print(f"[DRY-RUN] 將寫入 {file_format.upper()} 檔案到: {path}")
        print(f"[DRY-RUN] 資料形狀: {df.shape}")
        if hasattr(df, 'columns'):
            print(f"[DRY-RUN] 欄位: {list(df.columns)}")
        return
    
    # 根據格式選擇寫入函數
    if file_format.lower() == 'csv':
        atomic_write_df(df, path, **kwargs)
    elif file_format.lower() == 'parquet':
        atomic_write_parquet(df, path, **kwargs)
    elif file_format.lower() == 'json':
        atomic_write_json(df, path, **kwargs)
    else:
        raise ValueError(f"不支持的檔案格式: {file_format}")

def backup_existing_file(path: Path, backup_dir: Optional[Path] = None) -> Optional[Path]:
    """
    備份現有檔案
    
    Args:
        path: 要備份的檔案路徑
        backup_dir: 備份目錄，如果為None則使用原檔案目錄下的backup子目錄
        
    Returns:
        備份檔案路徑，如果原檔案不存在則返回None
    """
    if not path.exists():
        return None
        
    try:
        if backup_dir is None:
            backup_dir = path.parent / 'backup'
        
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成備份檔案名
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{path.stem}_{timestamp}{path.suffix}"
        
        # 複製檔案
        import shutil
        shutil.copy2(path, backup_path)
        
        logger.info(f"已備份檔案: {path} -> {backup_path}")
        return backup_path
        
    except Exception as e:
        logger.error(f"備份檔案失敗: {path}, 錯誤: {str(e)}")
        return None
