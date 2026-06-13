"""
應用程式自訂例外 (Application Custom Exceptions)
"""

class BacktestCancelledError(Exception):
    """回測任務被使用者取消時拋出的例外"""
    pass
