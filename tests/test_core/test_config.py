import pytest
from pathlib import Path
import shutil
from data_module.config import DataConfig

class TestDataConfig:
    """測試數據配置類"""
    
    def test_config_initialization(self, test_data_dir):
        """測試配置初始化"""
        config = DataConfig(base_dir=test_data_dir)
        assert config.base_dir == test_data_dir
        assert config.data_dir == test_data_dir
        assert config.daily_price_dir == test_data_dir / 'daily_price'
        assert config.meta_data_dir == test_data_dir / 'meta_data'
        assert config.technical_dir == test_data_dir / 'technical_analysis'
    
    def test_directory_creation(self, test_data_dir):
        """測試目錄創建"""
        config = DataConfig(base_dir=test_data_dir)
        assert config.daily_price_dir.exists()
        assert config.meta_data_dir.exists()
        assert config.technical_dir.exists()
        assert config.backup_dir.exists()
    
    def test_backup_mechanism(self, test_data_dir):
        """測試備份機制"""
        config = DataConfig(base_dir=test_data_dir)
        
        # 創建測試文件
        test_file = test_data_dir / "test.csv"
        test_file.write_text("test data")
        
        # 創建備份
        backup_file = config.create_backup(test_file)
        assert backup_file.exists()
        assert backup_file.name.startswith("test_")
        assert backup_file.name.endswith(".csv")
        
        # 測試備份清理
        config._cleanup_old_backups("test")
        # 這裡可以添加更多的備份清理測試 