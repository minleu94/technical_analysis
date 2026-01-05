# 安裝指南

## 📦 安裝依賴

### 方法 1：使用 requirements.txt（推薦）

```bash
pip install -r requirements.txt
```

### 方法 2：使用安裝 notebook

```bash
# 打開 Jupyter Notebook
jupyter notebook install_dependencies.ipynb
```

然後依序執行每個 cell 來安裝套件。

### 方法 3：手動安裝

```bash
# 基本套件
pip install pandas numpy requests

# 技術分析
pip install ta  # 或嘗試安裝 talib（Windows 上較複雜）

# 可視化
pip install matplotlib seaborn

# 其他工具
pip install tqdm yfinance
```

## 🚀 快速開始

### 1. 安裝依賴

```bash
pip install -r requirements.txt
```

### 2. 啟動 UI 應用程式

```bash
python ui_app/main.py
```

## ⚙️ 配置

### 數據路徑配置

數據路徑預設為 `D:/Min/Python/Project/FA_Data/`，可在 `data_module/config.py` 中修改。

### 環境變量（可選）

可以通過環境變量覆蓋數據路徑：
```bash
set DATA_ROOT=your/custom/path
set OUTPUT_ROOT=your/custom/output/path
```

## 🔧 故障排除

### 問題 1：pandas 未安裝

**解決**：
```bash
pip install pandas
```

### 問題 2：talib 安裝失敗（Windows）

**解決**：
- 使用 `ta` 套件替代（已包含在 `talib_compatibility.py`）
- 或參考 `install_dependencies.ipynb` 中的說明

### 問題 3：tkinter 未安裝

**解決**：
- Windows：通常已包含在 Python 安裝中
- Linux：`sudo apt-get install python3-tk`

## 📝 注意事項

1. **Python 版本**：建議使用 Python 3.8 或更高版本
2. **虛擬環境**：可選，但建議使用以隔離依賴
3. **Windows 編碼**：系統已處理 UTF-8 編碼問題

