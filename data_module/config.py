from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import shutil
import os
import argparse
import sys
import re

@dataclass
class TWStockConfig:
    """台股數據分析核心配置"""
    
    # 基礎路徑配置 - 支持環境變量和CLI覆蓋
    data_root: Path = field(default_factory=lambda: Path(
        os.environ.get('DATA_ROOT', 'D:/Min/Python/Project/FA_Data')
    ))
    output_root: Path = field(default_factory=lambda: Path(
        os.environ.get('OUTPUT_ROOT', 'D:/Min/Python/Project/FA_Data/output')
    ))
    profile: str = field(default_factory=lambda: os.environ.get('PROFILE', 'prod'))
    
    # 保持向後兼容的base_dir屬性
    base_dir: Path = None
    
    # 數據目錄
    data_dir: Path = None
    daily_price_dir: Path = None 
    meta_data_dir: Path = None
    technical_dir: Path = None
    log_dir: Path = None  # 新增日誌目錄
    
    # 關鍵檔案路徑
    market_index_file: Path = None
    industry_index_file: Path = None
    stock_data_file: Path = None
    all_stocks_data_file: Path = None  # 新增整合性數據文件
    broker_flow_dir: Path = None  # 券商分點資料目錄
    broker_branch_registry_file: Path = None  # 分點 registry 檔案
    
    # 數據參數
    default_start_date: str = "2014-01-01"
    backup_keep_days: int = 7
    min_data_days: int = 30
    
    # API請求配置
    request_timeout: int = 30
    max_retries: int = 3
    retry_delay: int = 5
    
    def __post_init__(self):
        """初始化衍生屬性"""
        # 處理路徑覆蓋邏輯
        self._resolve_paths()
        
        # 設定數據目錄
        self.data_dir = self.data_root
        self.daily_price_dir = self.data_dir / 'daily_price'
        self.meta_data_dir = self.data_dir / 'meta_data'
        self.technical_dir = self.data_dir / 'technical_analysis'
        self.log_dir = self.data_dir / 'logs'
        
        # 設定關鍵檔案路徑
        self.market_index_file = self.meta_data_dir / 'market_index.csv'
        self.industry_index_file = self.meta_data_dir / 'industry_index.csv'
        self.stock_data_file = self.meta_data_dir / 'stock_data_whole.csv'
        self.all_stocks_data_file = self.meta_data_dir / 'all_stocks_data.csv'
        self.broker_flow_dir = self.data_dir / 'broker_flow'
        self.broker_branch_registry_file = self.meta_data_dir / 'broker_branch_registry.csv'
        
        # 確保所需目錄存在
        self._ensure_directories()
        
        # 創建備份目錄
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        # 設置日誌
        self._setup_logging()
        
        # 記錄最終解析的路徑
        self.logger.info(f"數據根目錄: {self.data_root}")
        self.logger.info(f"輸出根目錄: {self.output_root}")
        self.logger.info(f"配置檔案: {self.profile}")
    
    def _resolve_paths(self):
        """解析路徑覆蓋邏輯"""
        # 確保路徑是Path對象
        if isinstance(self.data_root, str):
            self.data_root = Path(self.data_root)
        if isinstance(self.output_root, str):
            self.output_root = Path(self.output_root)
            
        # 如果是測試環境，自動添加_test後綴
        if self.profile == "test":
            self.data_root = self.data_root / "_test"
            self.output_root = self.output_root / "_test"
            
        # 保持向後兼容
        self.base_dir = self.data_root
        
        # 輸出基礎路徑信息（使用 logger 避免編碼和 I/O 問題）
        try:
            logger = logging.getLogger(__name__)
            logger.info(f"數據目錄設置為: {self.data_root}")
            logger.info(f"輸出目錄設置為: {self.output_root}")
            logger.info(f"配置檔案: {self.profile}")
        except (UnicodeEncodeError, ValueError, OSError) as e:
            # 如果遇到編碼或 I/O 問題（例如標準輸出已關閉），使用 logger 或靜默處理
            try:
                logger = logging.getLogger(__name__)
                logger.debug(f"Data directory: {self.data_root}")
                logger.debug(f"Output directory: {self.output_root}")
                logger.debug(f"Profile: {self.profile}")
            except:
                # 如果連 logger 都失敗，靜默處理（避免在動態導入時崩潰）
                pass
    
    def resolve_path(self, subfolder: str) -> Path:
        """解析子資料夾路徑並創建目錄"""
        path = self.data_root / subfolder
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def resolve_output_path(self, subfolder: str) -> Path:
        """解析輸出子資料夾路徑並創建目錄"""
        path = self.output_root / subfolder
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def _ensure_directories(self):
        """確保所需目錄結構存在"""
        directories = [
            self.daily_price_dir,
            self.meta_data_dir,
            self.technical_dir,
            self.backup_dir,
            self.log_dir  # 新增日誌目錄
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
    
    @property
    def backup_dir(self) -> Path:
        """備份目錄路徑"""
        return self.meta_data_dir / 'backup'
    
    def get_technical_file(self, stock_id: str) -> Path:
        """取得特定股票的技術分析檔案路徑"""
        return self.technical_dir / f'{stock_id}_indicators.csv'
    
    def get_daily_price_file(self, date: str) -> Path:
        """取得特定日期的價格檔案路徑
        
        Args:
            date: 日期字串，格式為 YYYY-MM-DD 或 YYYYMMDD
        """
        # 轉換日期格式為 YYYYMMDD
        if re.match(r'^\d{4}-\d{2}-\d{2}$', date):
            # YYYY-MM-DD 格式，轉換為 YYYYMMDD
            date_obj = datetime.strptime(date, '%Y-%m-%d')
            date_str = date_obj.strftime('%Y%m%d')
        elif re.match(r'^\d{8}$', date):
            # 已經是 YYYYMMDD 格式
            date_str = date
        else:
            # 其他格式，嘗試解析
            try:
                date_obj = datetime.strptime(date, '%Y-%m-%d')
                date_str = date_obj.strftime('%Y%m%d')
            except:
                date_str = date.replace('-', '')  # 簡單移除連字符
        
        return self.daily_price_dir / f'{date_str}.csv'
    
    def _cleanup_old_backups(self, file_prefix: str):
        """清理超過保留天數的備份文件"""
        cutoff_time = datetime.now() - timedelta(days=self.backup_keep_days)
        for backup_file in self.backup_dir.glob(f"{file_prefix}_*"):
            try:
                file_time = datetime.fromtimestamp(backup_file.stat().st_mtime)
                if file_time < cutoff_time:
                    backup_file.unlink()
            except Exception:
                continue
    
    def _setup_logging(self):
        """設置日誌"""
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        
        # 創建文件處理器
        file_handler = logging.FileHandler(
            self.log_dir / "config.log",
            encoding='utf-8'
        )
        file_handler.setLevel(logging.INFO)
        
        # 創建控制台處理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # 設置格式
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        # 添加處理器
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
    
    def create_backup(self, source_file: Path, backup_file: Path = None):
        """創建文件備份"""
        try:
            if not source_file.exists():
                return
                
            if backup_file is None:
                # 使用時間戳創建備份文件名
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_file = self.backup_dir / f"{source_file.stem}_{timestamp}{source_file.suffix}"
            
            # 創建備份
            shutil.copy2(source_file, backup_file)
            self.logger.info(f"已創建備份文件: {backup_file}")
            
            # 清理舊備份
            self._cleanup_old_backups(source_file.stem)
            
        except Exception as e:
            self.logger.error(f"創建備份時發生錯誤: {str(e)}")
    
    def restore_backup(self, backup_file: Path, target_file: Path):
        """從備份文件恢復"""
        try:
            if not backup_file.exists():
                self.logger.error(f"備份文件不存在: {backup_file}")
                return False
                
            shutil.copy2(backup_file, target_file)
            self.logger.info(f"已從備份文件 {backup_file} 恢復到 {target_file}")
            return True
            
        except Exception as e:
            self.logger.error(f"恢復備份時發生錯誤: {str(e)}")
            return False

    @classmethod
    def from_args(cls, args=None):
        """從命令行參數創建配置實例"""
        if args is None:
            args = sys.argv[1:]
            
        parser = argparse.ArgumentParser(description='台股技術分析系統配置')
        parser.add_argument("--data-root", type=str, help="覆蓋數據根目錄路徑")
        parser.add_argument("--output-root", type=str, help="覆蓋輸出根目錄路徑")
        parser.add_argument("--profile", type=str, default="prod", 
                           choices=["prod", "staging", "test"], help="配置檔案")
        parser.add_argument("--dry-run", action="store_true", help="乾運行模式，不實際寫入檔案")
        
        parsed_args = parser.parse_args(args)
        
        # 創建配置實例，優先使用命令行參數
        config_kwargs = {}
        if parsed_args.data_root:
            config_kwargs['data_root'] = Path(parsed_args.data_root)
        if parsed_args.output_root:
            config_kwargs['output_root'] = Path(parsed_args.output_root)
        if parsed_args.profile:
            config_kwargs['profile'] = parsed_args.profile
            
        return cls(**config_kwargs), parsed_args 