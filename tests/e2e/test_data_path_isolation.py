"""
端到端測試：數據路徑隔離測試
確保測試環境不會寫入到生產環境的D槽路徑
"""

import pytest
import pandas as pd
from pathlib import Path
import os
import tempfile
import shutil
from unittest.mock import patch, MagicMock

# 添加項目根目錄到系統路徑
import sys
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from data_module.config import TWStockConfig
# from technical_analysis.utils.io_utils import atomic_write_df, safe_write_with_dry_run
from utils.io_utils import atomic_write_df, safe_write_with_dry_run


class TestDataPathIsolation:
    """數據路徑隔離測試類"""
    
    def test_environment_variable_override(self, tmp_path, monkeypatch):
        """測試環境變量覆蓋功能"""
        # 設置環境變量
        test_data_root = tmp_path / "test_data"
        test_output_root = tmp_path / "test_output"
        
        monkeypatch.setenv("DATA_ROOT", str(test_data_root))
        monkeypatch.setenv("OUTPUT_ROOT", str(test_output_root))
        monkeypatch.setenv("PROFILE", "test")
        
        # 創建配置
        config = TWStockConfig()
        
        # 驗證路徑設置
        assert config.data_root == test_data_root / "_test"
        assert config.output_root == test_output_root / "_test"
        assert config.profile == "test"
        
        # 驗證目錄已創建
        assert config.data_root.exists()
        assert config.output_root.exists()
    
    def test_cli_argument_override(self, tmp_path):
        """測試命令行參數覆蓋功能"""
        test_data_root = tmp_path / "cli_data"
        test_output_root = tmp_path / "cli_output"
        
        # 模擬命令行參數
        test_args = [
            "--data-root", str(test_data_root),
            "--output-root", str(test_output_root),
            "--profile", "test"
        ]
        
        config, parsed_args = TWStockConfig.from_args(test_args)
        
        # 驗證路徑設置
        assert config.data_root == test_data_root / "_test"
        assert config.output_root == test_output_root / "_test"
        assert config.profile == "test"
        assert parsed_args.dry_run is False
    
    def test_dry_run_mode(self, tmp_path):
        """測試乾運行模式"""
        test_args = ["--dry-run", "--profile", "test"]
        
        config, parsed_args = TWStockConfig.from_args(test_args)
        
        # 驗證乾運行標誌
        assert parsed_args.dry_run is True
        
        # 測試乾運行寫入
        df = pd.DataFrame({"test": [1, 2, 3]})
        test_path = tmp_path / "test_file.csv"
        
        # 乾運行不應該創建實際檔案
        safe_write_with_dry_run(df, test_path, dry_run=True)
        assert not test_path.exists()
        
        # 正常運行應該創建檔案
        safe_write_with_dry_run(df, test_path, dry_run=False)
        assert test_path.exists()
    
    def test_path_resolution_helpers(self, tmp_path, monkeypatch):
        """測試路徑解析輔助函數"""
        monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))
        monkeypatch.setenv("OUTPUT_ROOT", str(tmp_path / "output"))
        
        config = TWStockConfig()
        
        # 測試resolve_path
        subfolder_path = config.resolve_path("test_subfolder")
        expected_path = config.data_root / "test_subfolder"
        assert subfolder_path == expected_path
        assert subfolder_path.exists()
        
        # 測試resolve_output_path
        output_subfolder_path = config.resolve_output_path("test_output")
        expected_output_path = config.output_root / "test_output"
        assert output_subfolder_path == expected_output_path
        assert output_subfolder_path.exists()
    
    def test_atomic_write_safety(self, tmp_path):
        """測試原子寫入安全性"""
        df = pd.DataFrame({"col1": [1, 2, 3], "col2": ["a", "b", "c"]})
        test_file = tmp_path / "test_atomic.csv"
        
        # 測試原子寫入
        atomic_write_df(df, test_file)
        
        # 驗證檔案存在且內容正確
        assert test_file.exists()
        loaded_df = pd.read_csv(test_file)
        pd.testing.assert_frame_equal(df, loaded_df)
        
        # 驗證沒有臨時檔案殘留
        temp_files = list(tmp_path.glob("*.tmp"))
        assert len(temp_files) == 0
    
    def test_production_path_isolation(self, tmp_path, monkeypatch):
        """測試生產路徑隔離 - 確保不會寫入D槽"""
        # 設置測試環境
        monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))
        monkeypatch.setenv("OUTPUT_ROOT", str(tmp_path / "output"))
        monkeypatch.setenv("PROFILE", "test")
        
        config = TWStockConfig()
        
        # 驗證不會使用D槽路徑
        d_drive_path = Path("D:/Min/Python/Project/FA_Data")
        assert config.data_root != d_drive_path
        assert not str(config.data_root).startswith("D:/")
        assert not str(config.output_root).startswith("D:/")
        
        # 測試寫入到隔離路徑
        df = pd.DataFrame({"test": [1, 2, 3]})
        test_path = config.resolve_path("isolation_test") / "test.csv"
        
        atomic_write_df(df, test_path)
        assert test_path.exists()
        
        # 驗證檔案在隔離路徑中
        assert str(test_path).startswith(str(tmp_path))
    
    def test_backup_functionality(self, tmp_path, monkeypatch):
        """測試備份功能在隔離環境中正常工作"""
        monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))
        monkeypatch.setenv("OUTPUT_ROOT", str(tmp_path / "output"))
        
        config = TWStockConfig()
        
        # 創建測試檔案
        test_file = config.resolve_path("backup_test") / "test.csv"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        
        df = pd.DataFrame({"data": [1, 2, 3]})
        df.to_csv(test_file, index=False)
        
        # 測試備份功能
        backup_path = config.create_backup(test_file)
        assert backup_path is not None
        assert backup_path.exists()
        
        # 驗證備份內容正確
        backup_df = pd.read_csv(backup_path)
        pd.testing.assert_frame_equal(df, backup_df)
    
    def test_config_logging(self, tmp_path, monkeypatch, caplog):
        """測試配置日誌記錄"""
        monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))
        monkeypatch.setenv("OUTPUT_ROOT", str(tmp_path / "output"))
        monkeypatch.setenv("PROFILE", "test")
        
        with caplog.at_level("INFO"):
            config = TWStockConfig()
        
        # 驗證日誌記錄了正確的路徑
        log_messages = [record.message for record in caplog.records]
        assert any("數據根目錄" in msg for msg in log_messages)
        assert any("輸出根目錄" in msg for msg in log_messages)
        assert any("配置檔案" in msg for msg in log_messages)
    
    def test_script_integration(self, tmp_path, monkeypatch):
        """測試腳本整合 - 模擬腳本使用新配置系統"""
        # 設置測試環境
        monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))
        monkeypatch.setenv("OUTPUT_ROOT", str(tmp_path / "output"))
        monkeypatch.setenv("PROFILE", "test")
        
        # 模擬腳本參數
        script_args = ["--dry-run", "--days", "5"]
        
        # 測試配置解析
        config, parsed_args = TWStockConfig.from_args(script_args)
        
        # 驗證配置正確
        assert parsed_args.dry_run is True
        assert config.profile == "test"
        assert str(config.data_root).startswith(str(tmp_path))
        
        # 模擬數據處理
        df = pd.DataFrame({"date": ["2024-01-01", "2024-01-02"], "value": [100, 101]})
        output_path = config.resolve_output_path("test_results") / "data.csv"
        
        # 乾運行模式
        safe_write_with_dry_run(df, output_path, dry_run=parsed_args.dry_run)
        assert not output_path.exists()  # 乾運行不應該創建檔案
        
        # 正常模式
        safe_write_with_dry_run(df, output_path, dry_run=False)
        assert output_path.exists()  # 正常模式應該創建檔案
    
    def test_profile_auto_suffix(self, tmp_path, monkeypatch):
        """測試配置檔案自動後綴功能"""
        base_data_root = tmp_path / "base_data"
        base_output_root = tmp_path / "base_output"
        
        monkeypatch.setenv("DATA_ROOT", str(base_data_root))
        monkeypatch.setenv("OUTPUT_ROOT", str(base_output_root))
        
        # 測試生產環境
        monkeypatch.setenv("PROFILE", "prod")
        config_prod = TWStockConfig()
        assert config_prod.data_root == base_data_root
        assert config_prod.output_root == base_output_root
        
        # 測試測試環境
        monkeypatch.setenv("PROFILE", "test")
        config_test = TWStockConfig()
        assert config_test.data_root == base_data_root / "_test"
        assert config_test.output_root == base_output_root / "_test"
        
        # 測試暫存環境
        monkeypatch.setenv("PROFILE", "staging")
        config_staging = TWStockConfig()
        assert config_staging.data_root == base_data_root
        assert config_staging.output_root == base_output_root


def test_end_to_end_isolation(tmp_path, monkeypatch):
    """端到端隔離測試 - 確保整個流程不會觸及D槽"""
    # 設置完全隔離的環境
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "isolated_data"))
    monkeypatch.setenv("OUTPUT_ROOT", str(tmp_path / "isolated_output"))
    monkeypatch.setenv("PROFILE", "test")
    
    # 創建配置
    config = TWStockConfig()
    
    # 驗證隔離
    assert not str(config.data_root).startswith("D:/")
    assert not str(config.output_root).startswith("D:/")
    
    # 模擬完整的數據處理流程
    test_data = pd.DataFrame({
        "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
        "open": [100, 101, 102],
        "high": [105, 106, 107],
        "low": [98, 99, 100],
        "close": [103, 104, 105],
        "volume": [1000, 1100, 1200]
    })
    
    # 測試各種路徑解析
    data_path = config.resolve_path("daily_price")
    output_path = config.resolve_output_path("reports")
    
    # 測試原子寫入
    test_file = data_path / "test_data.csv"
    atomic_write_df(test_data, test_file)
    
    # 驗證檔案在隔離環境中
    assert test_file.exists()
    assert str(test_file).startswith(str(tmp_path))
    
    # 驗證沒有D槽路徑被創建
    all_paths = [str(p) for p in tmp_path.rglob("*") if p.is_file()]
    d_drive_paths = [p for p in all_paths if p.startswith("D:/")]
    assert len(d_drive_paths) == 0, f"發現D槽路徑: {d_drive_paths}"
    
    # 測試乾運行模式
    dry_run_file = output_path / "dry_run_test.csv"
    safe_write_with_dry_run(test_data, dry_run_file, dry_run=True)
    assert not dry_run_file.exists()
    
    # 正常寫入
    safe_write_with_dry_run(test_data, dry_run_file, dry_run=False)
    assert dry_run_file.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
