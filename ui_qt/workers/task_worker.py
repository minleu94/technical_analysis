"""
統一背景任務 Worker
用於執行長時間運行的任務（推薦、回測、更新資料等）
"""

from PySide6.QtCore import QThread, Signal, QObject
from typing import Callable, Any, Dict, Optional
import traceback
from app_module.exceptions import BacktestCancelledError


class TaskWorker(QThread):
    """通用背景任務 Worker

    使用方式：
        worker = TaskWorker(task_function, arg1, arg2, kwarg1=value1)
        worker.finished.connect(on_finished)
        worker.error.connect(on_error)
        worker.progress.connect(on_progress)
        worker.cancelled.connect(on_cancelled)
        worker.start()
    """

    # 信號定義
    started = Signal()  # 任務開始
    finished = Signal(object)  # 任務完成，傳遞結果
    error = Signal(str)  # 任務出錯，傳遞錯誤信息
    progress = Signal(str, int)  # 進度更新 (message, percentage)
    cancelled = Signal()  # 任務被取消

    def __init__(
        self,
        task_function: Callable,
        *args,
        **kwargs
    ):
        """初始化 Worker

        Args:
            task_function: 要執行的函數
            *args: 位置參數
            **kwargs: 關鍵字參數
        """
        super().__init__()
        self.task_function = task_function
        self.args = args
        self.kwargs = kwargs
        self._is_cancelled = False

    def run(self):
        """執行任務（在背景線程中運行）"""
        try:
            self.started.emit()

            # ✅ 檢查是否已取消
            if self._is_cancelled:
                self.cancelled.emit()
                return

            # 執行任務函數
            result = self.task_function(*self.args, **self.kwargs)

            # ✅ 再次檢查是否已取消（任務執行期間可能被取消）
            if self._is_cancelled:
                self.cancelled.emit()
            else:
                self.finished.emit(result)

        except BacktestCancelledError:
            self.cancelled.emit()
        except Exception as e:
            # ✅ 確保錯誤信號被發送，除非線程被取消
            if not self._is_cancelled:
                error_msg = f"{str(e)}\n{traceback.format_exc()}"
                self.error.emit(error_msg)
            else:
                self.cancelled.emit()

    def cancel(self, cooperative: bool = False, wait: bool = True):
        """取消任務

        Args:
            cooperative: 是否為合作式軟取消。
                - True: 僅設置取消標記，不調用 terminate()。適合已對接 cooperative cancellation 檢查的任務（如回測、參數掃描）。
                - False: [警告: Legacy Fallback] 會直接呼叫 QThread.terminate() 強行終止執行緒。
                         此方法為防回歸的舊有頁面（Update, Recommendation, SQLite Inspector）相容手段，
                         有造成 Mutex 死鎖、SQLite 資源鎖定或未釋放資源的潛在風險。後續應逐步改造為合作式取消。
            wait: 是否在呼叫取消後同步等待執行緒結束。
        """
        self._is_cancelled = True
        if cooperative:
            if wait:
                self.wait()
        else:
            self.terminate()
            self.wait()


class ProgressTaskWorker(QThread):
    """支持進度報告的任務 Worker

    任務函數需要接受一個 progress_callback 參數：
        def my_task(arg1, arg2, progress_callback=None):
            progress_callback("開始處理...", 0)
            # ... 處理邏輯
            progress_callback("處理中...", 50)
            # ... 更多處理
            progress_callback("完成", 100)
            return result
    """

    # 信號定義
    started = Signal()
    finished = Signal(object)
    error = Signal(str)
    progress = Signal(str, int)  # (message, percentage)
    cancelled = Signal()  # 任務被取消

    def __init__(
        self,
        task_function: Callable,
        *args,
        **kwargs
    ):
        """初始化 Worker

        Args:
            task_function: 要執行的函數（需要接受 progress_callback 參數）
            *args: 位置參數
            **kwargs: 關鍵字參數
        """
        super().__init__()
        self.task_function = task_function
        self.args = args
        self.kwargs = kwargs
        self._is_cancelled = False

    def _progress_callback(self, message: str, percentage: int):
        """進度回調函數"""
        if not self._is_cancelled:
            self.progress.emit(message, percentage)

    def run(self):
        """執行任務"""
        try:
            self.started.emit()

            # ✅ 檢查是否已取消
            if self._is_cancelled:
                self.cancelled.emit()
                return

            # 將 progress_callback 添加到 kwargs
            kwargs_with_progress = {**self.kwargs, 'progress_callback': self._progress_callback}

            # 執行任務函數
            result = self.task_function(*self.args, **kwargs_with_progress)

            if self._is_cancelled:
                self.cancelled.emit()
            else:
                self.finished.emit(result)

        except BacktestCancelledError:
            self.cancelled.emit()
        except Exception as e:
            if not self._is_cancelled:
                error_msg = f"{str(e)}\n{traceback.format_exc()}"
                self.error.emit(error_msg)
            else:
                self.cancelled.emit()

    def cancel(self, cooperative: bool = False, wait: bool = True):
        """取消任務

        Args:
            cooperative: 是否為合作式軟取消。
                - True: 僅設置取消標記，不調用 terminate()。適合已對接 cooperative cancellation 檢查的任務（如回測、參數掃描）。
                - False: [警告: Legacy Fallback] 會直接呼叫 QThread.terminate() 強行終止執行緒。
                         此方法為防回歸的舊有頁面（Update, Recommendation, SQLite Inspector）相容手段，
                         有造成 Mutex 死鎖、SQLite 資源鎖定或未釋放資源的潛在風險。後續應逐步改造為合作式取消。
            wait: 是否在呼叫取消後同步等待執行緒結束。
        """
        self._is_cancelled = True
        if cooperative:
            if wait:
                self.wait()
        else:
            self.terminate()
            self.wait()


