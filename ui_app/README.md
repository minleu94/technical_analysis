# Tkinter UI 模組（舊版，僅供參考）

⚠️ **注意**：此模組為舊版 Tkinter UI 實作，僅供參考使用。

**當前推薦**：
- 新專案請使用 `ui_qt/`（PySide6/Qt UI）
- 業務邏輯請使用 `app_module/` 中的服務層
- 決策邏輯請使用 `decision_module/` 中的模組

**模組狀態**：
- `main.py`：Tkinter UI 主程式（已更新為使用 `decision_module`）
- 業務邏輯已遷移至 `decision_module/`
- 此模組保留僅為向後兼容與參考用途
