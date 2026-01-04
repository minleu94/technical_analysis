import unittest
import sys
from pathlib import Path

# 添加項目根目錄到 Python 路徑
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

# 導入測試模塊
from test_data_module import TestDataModule

def run_tests():
    """運行所有測試"""
    # 創建測試套件
    suite = unittest.TestLoader().loadTestsFromTestCase(TestDataModule)
    
    # 運行測試
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # 返回測試結果
    return result.wasSuccessful()

if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1) 