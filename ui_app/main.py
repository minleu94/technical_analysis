"""
台股技術分析系統 - 主應用程式
提供圖形化界面進行數據更新、策略選擇和回測
"""

import sys
import os
from pathlib import Path

# 添加項目根目錄到系統路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 設置 UTF-8 編碼
if sys.platform == 'win32':
    import io
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except:
        pass

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, scrolledtext
    from datetime import datetime, timedelta
    import threading
    import pandas as pd
except ImportError as e:
    print(f"錯誤：無法導入必要的模組: {e}")
    print("請確認已安裝: pip install pandas")
    sys.exit(1)

# 導入專案模組
try:
    from data_module.config import TWStockConfig
    from data_module.data_loader import DataLoader
    from backtest_module.strategy_tester import StrategyTester
    from backtest_module.performance_analyzer import PerformanceAnalyzer
    from ui_app.strategies import STRATEGIES
    # from ui_app.strategy_configurator import StrategyConfigurator
    # from ui_app.stock_screener import StockScreener
    # from ui_app.reason_engine import ReasonEngine
    # from ui_app.market_regime_detector import MarketRegimeDetector
    # from ui_app.industry_mapper import IndustryMapper
    from decision_module.strategy_configurator import StrategyConfigurator
    from decision_module.stock_screener import StockScreener
    from decision_module.reason_engine import ReasonEngine
    from decision_module.market_regime_detector import MarketRegimeDetector
    from decision_module.industry_mapper import IndustryMapper
    # 導入應用服務層
    from app_module.recommendation_service import RecommendationService
except ImportError as e:
    print(f"錯誤：無法導入專案模組: {e}")
    print("請確認已安裝所有依賴套件")
    sys.exit(1)

class TradingAnalysisApp:
    """台股技術分析主應用程式"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("台股技術分析系統")
        self.root.geometry("1400x800")
        
        # 配置現代化樣式
        self._setup_styles()
        
        # 初始化配置
        self.config = TWStockConfig()
        self.data_loader = DataLoader(self.config)
        # 保留原有實例以保持向後兼容（UI 層仍可直接使用）
        self.strategy_configurator = StrategyConfigurator()
        self.industry_mapper = IndustryMapper(self.config)  # 先初始化，因為 StockScreener 需要它
        self.stock_screener = StockScreener(self.config, self.industry_mapper)
        self.reason_engine = ReasonEngine()
        self.regime_detector = MarketRegimeDetector(self.config)
        # 新增：應用服務層
        self.recommendation_service = RecommendationService(self.config)
        
        # 當前市場狀態
        self.current_regime = None
        
        # 策略配置狀態
        self.strategy_config = {
            'technical': {
                'momentum': {'enabled': False, 'rsi': {}, 'macd': {}, 'kd': {}},
                'volatility': {'enabled': False, 'bollinger': {}, 'atr': {}},
                'trend': {'enabled': False, 'adx': {}, 'ma': {}}
            },
            'patterns': {'selected': []},
            'signals': {
                'technical_indicators': [],
                'volume_conditions': [],
                'weights': {'pattern': 0.3, 'technical': 0.5, 'volume': 0.2}
            },
            'filters': {}
        }
        
        # 創建界面
        self.create_widgets()
    
    def _setup_styles(self):
        """設置深色主題專業金融界面樣式"""
        style = ttk.Style()
        
        # 使用深色主題
        try:
            style.theme_use('clam')
        except:
            pass
        
        # 深色主題配色方案
        self.dark_bg = '#1a1a1a'  # 主背景（深灰黑）
        self.dark_panel = '#252525'  # 面板背景（稍亮）
        self.dark_border = '#333333'  # 邊框
        self.accent_blue = '#0d6efd'  # 強調藍色
        self.accent_gold = '#ffd700'  # 金色強調
        self.text_primary = '#ffffff'  # 主要文字（白色）
        self.text_secondary = '#b0b0b0'  # 次要文字（淺灰）
        self.text_positive = '#00ff88'  # 正數（綠色）
        self.text_negative = '#ff4444'  # 負數（紅色）
        self.hover_bg = '#2d2d2d'  # 懸停背景
        
        # 設置根窗口背景
        self.root.configure(bg=self.dark_bg)
        
        # 配置 Notebook 樣式（深色）
        style.configure('TNotebook', 
                       background=self.dark_bg, 
                       borderwidth=0)
        style.configure('TNotebook.Tab', 
                        padding=[20, 12], 
                        font=('Microsoft YaHei UI', 10, 'bold'),
                        background=self.dark_panel,
                        foreground=self.text_secondary,
                        borderwidth=0)
        style.map('TNotebook.Tab',
                  background=[('selected', self.dark_panel), ('!selected', self.dark_bg)],
                  foreground=[('selected', self.accent_blue), ('!selected', self.text_secondary)],
                  expand=[('selected', [1, 1, 1, 0])])
        
        # 配置 LabelFrame 樣式（深色）
        style.configure('TLabelframe', 
                       background=self.dark_panel,
                       borderwidth=1,
                       relief='flat',
                       bordercolor=self.dark_border)
        style.configure('TLabelframe.Label',
                       font=('Microsoft YaHei UI', 10, 'bold'),
                       foreground=self.text_primary,
                       background=self.dark_panel)
        
        # 配置 Treeview 樣式（深色金融風格）
        style.configure('Treeview',
                       background=self.dark_panel,
                       foreground=self.text_primary,
                       fieldbackground=self.dark_panel,
                       font=('Consolas', 9),  # 等寬字體更專業
                       rowheight=28,
                       borderwidth=0)
        style.configure('Treeview.Heading',
                       background='#1e1e1e',
                       foreground=self.text_primary,
                       font=('Microsoft YaHei UI', 9, 'bold'),
                       relief='flat',
                       borderwidth=0,
                       padding=[5, 8])
        style.map('Treeview.Heading',
                  background=[('active', '#2a2a2a')])
        style.map('Treeview',
                  background=[('selected', self.accent_blue)],
                  foreground=[('selected', self.text_primary)])
        
        # 配置 Button 樣式（深色）
        style.configure('TButton',
                       font=('Microsoft YaHei UI', 9),
                       padding=[12, 6],
                       background=self.dark_panel,
                       foreground=self.text_primary,
                       borderwidth=1,
                       relief='flat')
        style.map('TButton',
                  background=[('active', self.accent_blue), ('!active', self.dark_panel)],
                  foreground=[('active', self.text_primary), ('!active', self.text_primary)],
                  bordercolor=[('active', self.accent_blue), ('!active', self.dark_border)])
        
        # 配置 Entry 和 Spinbox 樣式（深色）
        style.configure('TEntry',
                       fieldbackground='#1e1e1e',
                       foreground=self.text_primary,
                       borderwidth=1,
                       relief='flat',
                       bordercolor=self.dark_border,
                       font=('Consolas', 9))
        style.map('TEntry',
                  bordercolor=[('focus', self.accent_blue)])
        style.configure('TSpinbox',
                       fieldbackground='#1e1e1e',
                       foreground=self.text_primary,
                       borderwidth=1,
                       relief='flat',
                       bordercolor=self.dark_border,
                       font=('Consolas', 9))
        style.map('TSpinbox',
                  bordercolor=[('focus', self.accent_blue)])
        
        # 配置 Combobox 樣式（深色）
        style.configure('TCombobox',
                       fieldbackground='#1e1e1e',
                       foreground=self.text_primary,
                       borderwidth=1,
                       relief='flat',
                       bordercolor=self.dark_border,
                       font=('Microsoft YaHei UI', 9))
        style.map('TCombobox',
                  bordercolor=[('focus', self.accent_blue)])
        
        # 配置 Label 樣式（深色）
        style.configure('TLabel',
                       background=self.dark_panel,
                       foreground=self.text_primary,
                       font=('Microsoft YaHei UI', 9))
        
        # 配置 Radiobutton 和 Checkbutton 樣式（深色）
        style.configure('TRadiobutton',
                       background=self.dark_panel,
                       foreground=self.text_primary,
                       font=('Microsoft YaHei UI', 9))
        style.configure('TCheckbutton',
                       background=self.dark_panel,
                       foreground=self.text_primary,
                       font=('Microsoft YaHei UI', 9))
        
        # 配置 Scrollbar 樣式（深色）
        style.configure('TScrollbar',
                       background=self.dark_panel,
                       troughcolor=self.dark_bg,
                       borderwidth=0,
                       arrowcolor=self.text_secondary,
                       darkcolor=self.dark_panel,
                       lightcolor=self.dark_panel)
        style.map('TScrollbar',
                  background=[('active', self.dark_border)])
        
        # 配置 Scale 樣式（深色）
        style.configure('TScale',
                       background=self.dark_panel,
                       troughcolor='#1e1e1e',
                       borderwidth=0,
                       sliderthickness=15)
    
    def create_widgets(self):
        """創建界面組件"""
        # 設置窗口背景色（深色）
        self.root.configure(bg=self.dark_bg)
        
        # 創建主容器
        main_container = tk.Frame(self.root, bg=self.dark_bg)
        main_container.pack(fill=tk.BOTH, expand=True)
        
        # 創建 Notebook（標籤頁）
        notebook = ttk.Notebook(main_container)
        notebook.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
        
        # 標籤頁 1: 數據更新
        self.data_update_frame = tk.Frame(notebook, bg=self.dark_bg)
        notebook.add(self.data_update_frame, text="數據更新")
        self.create_data_update_tab()
        
        # 標籤頁 2: 策略選擇
        self.strategy_frame = tk.Frame(notebook, bg=self.dark_bg)
        notebook.add(self.strategy_frame, text="策略選擇")
        self.create_strategy_tab()
        
        # 標籤頁 3: 回測
        self.backtest_frame = tk.Frame(notebook, bg=self.dark_bg)
        notebook.add(self.backtest_frame, text="回測")
        self.create_backtest_tab()
        
    def create_data_update_tab(self):
        """創建數據更新標籤頁"""
        # 標題
        title_label = ttk.Label(
            self.data_update_frame, 
            text="數據更新", 
            font=('Microsoft YaHei UI', 14, 'bold'),
            foreground='#2c3e50'
        )
        title_label.pack(pady=15)
        
        # 更新類型選擇
        type_frame = ttk.LabelFrame(self.data_update_frame, text="更新類型", padding=10)
        type_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.update_type = tk.StringVar(value="daily")
        ttk.Radiobutton(
            type_frame, 
            text="每日股票數據", 
            variable=self.update_type, 
            value="daily"
        ).pack(side=tk.LEFT, padx=10)
        
        ttk.Radiobutton(
            type_frame, 
            text="大盤指數數據", 
            variable=self.update_type, 
            value="market"
        ).pack(side=tk.LEFT, padx=10)
        
        ttk.Radiobutton(
            type_frame, 
            text="產業指數數據", 
            variable=self.update_type, 
            value="industry"
        ).pack(side=tk.LEFT, padx=10)
        
        # 日期選擇
        date_frame = ttk.LabelFrame(self.data_update_frame, text="更新日期範圍", padding=12)
        date_frame.pack(fill=tk.X, padx=10, pady=8)
        
        ttk.Label(date_frame, text="開始日期:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.start_date_entry = ttk.Entry(date_frame, width=15)
        self.start_date_entry.grid(row=0, column=1, padx=5, pady=5)
        self.start_date_entry.insert(0, (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"))
        
        ttk.Label(date_frame, text="結束日期:").grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        self.end_date_entry = ttk.Entry(date_frame, width=15)
        self.end_date_entry.grid(row=0, column=3, padx=5, pady=5)
        self.end_date_entry.insert(0, datetime.now().strftime("%Y-%m-%d"))
        
        ttk.Button(
            date_frame, 
            text="使用今天", 
            command=lambda: self.end_date_entry.delete(0, tk.END) or self.end_date_entry.insert(0, datetime.now().strftime("%Y-%m-%d"))
        ).grid(row=0, column=4, padx=5, pady=5)
        
        # 更新按鈕
        button_frame = tk.Frame(self.data_update_frame, bg=self.dark_bg)
        button_frame.pack(fill=tk.X, padx=12, pady=10)
        
        self.update_button = ttk.Button(
            button_frame, 
            text="開始更新", 
            command=self.start_data_update
        )
        self.update_button.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            button_frame, 
            text="檢查數據狀態", 
            command=self.check_data_status
        ).pack(side=tk.LEFT, padx=5)
        
        # 日誌顯示區域（深色主題）
        log_frame = ttk.LabelFrame(self.data_update_frame, text="更新日誌", padding=15)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)
        
        self.update_log = scrolledtext.ScrolledText(
            log_frame, 
            height=15, 
            wrap=tk.WORD,
            bg='#1e1e1e',
            fg=self.text_primary,
            font=('Consolas', 9),
            insertbackground=self.text_primary,
            selectbackground=self.accent_blue,
            selectforeground=self.text_primary,
            borderwidth=1,
            relief='flat'
        )
        self.update_log.pack(fill=tk.BOTH, expand=True)
        
    def create_strategy_tab(self):
        """創建策略配置標籤頁（升級版）"""
        # 設置背景色
        self.strategy_frame.configure(bg=self.dark_bg)
        
        # 標題（深色主題）
        title_label = tk.Label(
            self.strategy_frame, 
            text="策略配置與股票推薦", 
            font=('Microsoft YaHei UI', 16, 'bold'),
            foreground=self.text_primary,
            bg=self.dark_bg
        )
        title_label.pack(pady=20)
        
        # 創建內部 Notebook 來組織配置選項
        config_notebook = ttk.Notebook(self.strategy_frame)
        config_notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 標籤頁 1: 強勢股/產業
        strong_tab = tk.Frame(config_notebook, bg=self.dark_bg)
        config_notebook.add(strong_tab, text="強勢股/產業")
        self.create_strong_stocks_tab(strong_tab)
        
        # 標籤頁 2: 技術指標配置
        tech_tab = tk.Frame(config_notebook, bg=self.dark_bg)
        config_notebook.add(tech_tab, text="技術指標")
        self.create_technical_indicators_tab(tech_tab)
        
        # 標籤頁 3: 圖形模式
        pattern_tab = tk.Frame(config_notebook, bg=self.dark_bg)
        config_notebook.add(pattern_tab, text="圖形模式")
        self.create_pattern_tab(pattern_tab)
        
        # 標籤頁 4: 信號組合
        signal_tab = tk.Frame(config_notebook, bg=self.dark_bg)
        config_notebook.add(signal_tab, text="信號組合")
        self.create_signal_combination_tab(signal_tab)
        
        # 標籤頁 5: 篩選條件
        filter_tab = tk.Frame(config_notebook, bg=self.dark_bg)
        config_notebook.add(filter_tab, text="篩選條件")
        self.create_filter_tab(filter_tab)
        
        # 標籤頁 6: 策略結果
        result_tab = tk.Frame(config_notebook, bg=self.dark_bg)
        config_notebook.add(result_tab, text="推薦結果")
        self.create_result_tab(result_tab)
        
        # 執行按鈕
        button_frame = tk.Frame(self.strategy_frame, bg=self.dark_bg)
        button_frame.pack(fill=tk.X, padx=12, pady=10)
        
        ttk.Button(
            button_frame,
            text="執行策略分析",
            command=self.execute_strategy_analysis
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            button_frame,
            text="清除配置",
            command=self.clear_strategy_config
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            button_frame,
            text="保存策略配置",
            command=self.save_strategy_config
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            button_frame,
            text="載入策略配置",
            command=self.load_strategy_config
        ).pack(side=tk.LEFT, padx=5)
    
    def create_strong_stocks_tab(self, parent):
        """創建強勢股/產業標籤頁（三列布局，類似專業金融界面）"""
        # parent 已經是 tk.Frame，背景色已在創建時設置
        
        # 頂部控制欄
        top_control_frame = tk.Frame(parent, bg=self.dark_panel, height=50)
        top_control_frame.pack(fill=tk.X, padx=12, pady=(10, 8))
        top_control_frame.pack_propagate(False)
        
        # 時間範圍選擇
        ttk.Label(top_control_frame, text="時間範圍:", font=('Microsoft YaHei UI', 9)).pack(side=tk.LEFT, padx=(10, 5))
        self.strong_period_var = tk.StringVar(value="day")
        period_frame = tk.Frame(top_control_frame, bg=self.dark_panel)
        period_frame.pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(period_frame, text="本日", variable=self.strong_period_var, value="day").pack(side=tk.LEFT, padx=3)
        ttk.Radiobutton(period_frame, text="本周", variable=self.strong_period_var, value="week").pack(side=tk.LEFT, padx=3)
        
        # 顯示數量
        ttk.Label(top_control_frame, text="顯示數量:", font=('Microsoft YaHei UI', 9)).pack(side=tk.LEFT, padx=(20, 5))
        self.strong_top_n_var = tk.StringVar(value="20")
        ttk.Spinbox(top_control_frame, from_=5, to=100, textvariable=self.strong_top_n_var, width=8).pack(side=tk.LEFT, padx=5)
        
        # 三列主容器
        main_columns_frame = tk.Frame(parent, bg=self.dark_bg)
        main_columns_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)
        
        # 第一列：強勢股
        column1_frame = tk.Frame(main_columns_frame, bg=self.dark_panel, relief=tk.FLAT, bd=1)
        column1_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        
        # 標題和搜索欄
        col1_header = tk.Frame(column1_frame, bg='#1e1e1e', height=60)
        col1_header.pack(fill=tk.X)
        col1_header.pack_propagate(False)
        
        title1 = tk.Label(col1_header, text="強勢個股", font=('Microsoft YaHei UI', 11, 'bold'), 
                         bg='#1e1e1e', fg=self.text_primary)
        title1.pack(side=tk.LEFT, padx=10, pady=8)
        
        # 查詢按鈕（不使用搜索框，直接查詢）
        query_btn1 = ttk.Button(col1_header, text="查詢", command=self.query_strong_stocks)
        query_btn1.pack(side=tk.RIGHT, padx=10, pady=8)
        
        # 強勢股表格（增加推薦理由列）
        list_frame1 = tk.Frame(column1_frame, bg=self.dark_panel)
        list_frame1.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        columns1 = ('排名', '代號', '名稱', '收盤價', '漲幅%', '評分', '推薦理由')
        self.strong_stocks_tree = ttk.Treeview(list_frame1, columns=columns1, show='headings', height=15)
        
        column_widths1 = {'排名': 50, '代號': 70, '名稱': 100, '收盤價': 75, '漲幅%': 70, '評分': 60, '推薦理由': 300}
        for col in columns1:
            self.strong_stocks_tree.heading(col, text=col, anchor='center')
            self.strong_stocks_tree.column(col, width=column_widths1.get(col, 80), anchor='center', minwidth=40, stretch=False)
        
        scrollbar1 = ttk.Scrollbar(list_frame1, orient=tk.VERTICAL, command=self.strong_stocks_tree.yview)
        self.strong_stocks_tree.configure(yscrollcommand=scrollbar1.set)
        self.strong_stocks_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar1.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 第二列：大盤指數
        column2_frame = tk.Frame(main_columns_frame, bg=self.dark_panel, relief=tk.FLAT, bd=1)
        column2_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=3)
        
        col2_header = tk.Frame(column2_frame, bg='#1e1e1e', height=60)
        col2_header.pack(fill=tk.X)
        col2_header.pack_propagate(False)
        
        title2 = tk.Label(col2_header, text="大盤指數", font=('Microsoft YaHei UI', 11, 'bold'), 
                         bg='#1e1e1e', fg=self.text_primary)
        title2.pack(side=tk.LEFT, padx=10, pady=8)
        
        # 檢測市場狀態按鈕
        detect_btn = ttk.Button(col2_header, text="檢測市場狀態", command=self.detect_market_regime)
        detect_btn.pack(side=tk.RIGHT, padx=10, pady=8)
        
        # 大盤指數表格（顯示市場狀態信息）
        market_info_frame = tk.Frame(column2_frame, bg=self.dark_panel)
        market_info_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.market_info_text = tk.Text(market_info_frame, bg='#1e1e1e', fg=self.text_primary, 
                                        font=('Consolas', 9), wrap=tk.WORD, relief=tk.FLAT, bd=0)
        self.market_info_text.pack(fill=tk.BOTH, expand=True)
        self.market_info_text.insert('1.0', '點擊「檢測市場狀態」按鈕查看大盤信息')
        self.market_info_text.config(state=tk.DISABLED)
        
        # 第三列：產業指數
        column3_frame = tk.Frame(main_columns_frame, bg=self.dark_panel, relief=tk.FLAT, bd=1)
        column3_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))
        
        col3_header = tk.Frame(column3_frame, bg='#1e1e1e', height=60)
        col3_header.pack(fill=tk.X)
        col3_header.pack_propagate(False)
        
        title3 = tk.Label(col3_header, text="產業指數", font=('Microsoft YaHei UI', 11, 'bold'), 
                         bg='#1e1e1e', fg=self.text_primary)
        title3.pack(side=tk.LEFT, padx=10, pady=8)
        
        # 查詢按鈕
        query_btn3 = ttk.Button(col3_header, text="查詢", command=self.query_strong_industries)
        query_btn3.pack(side=tk.RIGHT, padx=10, pady=8)
        
        # 產業指數表格
        industry_list_frame = tk.Frame(column3_frame, bg=self.dark_panel)
        industry_list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        industry_columns = ('排名', '指數名稱', '收盤指數', '漲幅%')
        self.strong_industries_tree = ttk.Treeview(industry_list_frame, columns=industry_columns, show='headings', height=15)
        
        industry_column_widths = {'排名': 50, '指數名稱': 120, '收盤指數': 80, '漲幅%': 70}
        for col in industry_columns:
            self.strong_industries_tree.heading(col, text=col, anchor='center')
            self.strong_industries_tree.column(col, width=industry_column_widths.get(col, 100), anchor='center', minwidth=40, stretch=False)
        
        scrollbar3 = ttk.Scrollbar(industry_list_frame, orient=tk.VERTICAL, command=self.strong_industries_tree.yview)
        self.strong_industries_tree.configure(yscrollcommand=scrollbar3.set)
        self.strong_industries_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar3.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 添加評分說明標籤
        score_info_frame = tk.Frame(parent, bg=self.dark_bg)
        score_info_frame.pack(fill=tk.X, padx=12, pady=(5, 0))
        
        score_info_text = (
            "評分標準：評分 = 漲幅權重 × 漲幅% + 成交量權重 × 成交量變化率% "
            "（按評分降序排列）"
        )
        score_info_label = tk.Label(
            score_info_frame, 
            text=score_info_text,
            font=('Microsoft YaHei UI', 8),
            foreground=self.text_secondary,
            bg=self.dark_bg,
            justify=tk.LEFT
        )
        score_info_label.pack(side=tk.LEFT, padx=5)
    
    def create_technical_indicators_tab(self, parent):
        """創建技術指標配置標籤頁"""
        # parent 已經是 tk.Frame，背景色已在創建時設置
        
        # 動量指標區塊
        momentum_frame = ttk.LabelFrame(parent, text="動量指標", padding=12)
        momentum_frame.pack(fill=tk.X, padx=12, pady=8)
        
        self.momentum_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            momentum_frame,
            text="啟用動量指標",
            variable=self.momentum_enabled,
            command=lambda: self._update_config('technical', 'momentum', 'enabled', self.momentum_enabled.get())
        ).pack(anchor=tk.W)
        
        # RSI
        rsi_frame = ttk.Frame(momentum_frame)
        rsi_frame.pack(fill=tk.X, pady=2)
        self.rsi_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(rsi_frame, text="RSI", variable=self.rsi_enabled).pack(side=tk.LEFT, padx=5)
        ttk.Label(rsi_frame, text="週期:").pack(side=tk.LEFT, padx=5)
        self.rsi_period_var = tk.StringVar(value="14")
        ttk.Spinbox(rsi_frame, from_=5, to=50, textvariable=self.rsi_period_var, width=10).pack(side=tk.LEFT, padx=5)
        
        # MACD
        macd_frame = ttk.Frame(momentum_frame)
        macd_frame.pack(fill=tk.X, pady=2)
        self.macd_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(macd_frame, text="MACD", variable=self.macd_enabled).pack(side=tk.LEFT, padx=5)
        ttk.Label(macd_frame, text="快:").pack(side=tk.LEFT, padx=5)
        self.macd_fast_var = tk.StringVar(value="12")
        ttk.Spinbox(macd_frame, from_=5, to=50, textvariable=self.macd_fast_var, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Label(macd_frame, text="慢:").pack(side=tk.LEFT, padx=5)
        self.macd_slow_var = tk.StringVar(value="26")
        ttk.Spinbox(macd_frame, from_=10, to=100, textvariable=self.macd_slow_var, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Label(macd_frame, text="信號:").pack(side=tk.LEFT, padx=5)
        self.macd_signal_var = tk.StringVar(value="9")
        ttk.Spinbox(macd_frame, from_=5, to=30, textvariable=self.macd_signal_var, width=8).pack(side=tk.LEFT, padx=2)
        
        # KD
        kd_frame = ttk.Frame(momentum_frame)
        kd_frame.pack(fill=tk.X, pady=2)
        self.kd_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(kd_frame, text="KD", variable=self.kd_enabled).pack(side=tk.LEFT, padx=5)
        
        # 波動率指標區塊
        volatility_frame = ttk.LabelFrame(parent, text="波動率指標", padding=10)
        volatility_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.volatility_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            volatility_frame,
            text="啟用波動率指標",
            variable=self.volatility_enabled,
            command=lambda: self._update_config('technical', 'volatility', 'enabled', self.volatility_enabled.get())
        ).pack(anchor=tk.W)
        
        # 布林通道
        bb_frame = ttk.Frame(volatility_frame)
        bb_frame.pack(fill=tk.X, pady=2)
        self.bb_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(bb_frame, text="布林通道", variable=self.bb_enabled).pack(side=tk.LEFT, padx=5)
        ttk.Label(bb_frame, text="週期:").pack(side=tk.LEFT, padx=5)
        self.bb_window_var = tk.StringVar(value="20")
        ttk.Spinbox(bb_frame, from_=5, to=100, textvariable=self.bb_window_var, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Label(bb_frame, text="標準差:").pack(side=tk.LEFT, padx=5)
        self.bb_std_var = tk.StringVar(value="2.0")
        ttk.Spinbox(bb_frame, from_=1.0, to=5.0, increment=0.1, textvariable=self.bb_std_var, width=10).pack(side=tk.LEFT, padx=2)
        
        # ATR
        atr_frame = ttk.Frame(volatility_frame)
        atr_frame.pack(fill=tk.X, pady=2)
        self.atr_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(atr_frame, text="ATR", variable=self.atr_enabled).pack(side=tk.LEFT, padx=5)
        ttk.Label(atr_frame, text="週期:").pack(side=tk.LEFT, padx=5)
        self.atr_period_var = tk.StringVar(value="14")
        ttk.Spinbox(atr_frame, from_=5, to=50, textvariable=self.atr_period_var, width=10).pack(side=tk.LEFT, padx=2)
        
        # 趨勢指標區塊
        trend_frame = ttk.LabelFrame(parent, text="趨勢指標", padding=10)
        trend_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.trend_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            trend_frame,
            text="啟用趨勢指標",
            variable=self.trend_enabled,
            command=lambda: self._update_config('technical', 'trend', 'enabled', self.trend_enabled.get())
        ).pack(anchor=tk.W)
        
        # ADX
        adx_frame = ttk.Frame(trend_frame)
        adx_frame.pack(fill=tk.X, pady=2)
        self.adx_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(adx_frame, text="ADX", variable=self.adx_enabled).pack(side=tk.LEFT, padx=5)
        ttk.Label(adx_frame, text="週期:").pack(side=tk.LEFT, padx=5)
        self.adx_period_var = tk.StringVar(value="14")
        ttk.Spinbox(adx_frame, from_=5, to=50, textvariable=self.adx_period_var, width=10).pack(side=tk.LEFT, padx=2)
        
        # 均線系統
        ma_frame = ttk.Frame(trend_frame)
        ma_frame.pack(fill=tk.X, pady=2)
        self.ma_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(ma_frame, text="均線系統", variable=self.ma_enabled).pack(side=tk.LEFT, padx=5)
        ttk.Label(ma_frame, text="週期:").pack(side=tk.LEFT, padx=5)
        self.ma_windows_var = tk.StringVar(value="5,10,20,60")
        ttk.Entry(ma_frame, textvariable=self.ma_windows_var, width=20).pack(side=tk.LEFT, padx=2)
        ttk.Label(ma_frame, text="(用逗號分隔)", font=("Arial", 8)).pack(side=tk.LEFT, padx=2)
    
    def create_pattern_tab(self, parent):
        """創建圖形模式標籤頁"""
        # parent 已經是 tk.Frame，背景色已在創建時設置
        
        # 說明
        desc_label = tk.Label(
            parent,
            text="選擇要識別的圖形模式（可多選）",
            font=('Microsoft YaHei UI', 10),
            foreground=self.text_secondary,
            bg=self.dark_bg
        )
        desc_label.pack(pady=10)
        
        # 圖形模式選擇區塊
        pattern_frame = ttk.LabelFrame(parent, text="圖形模式", padding=12)
        pattern_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)
        
        # 使用 Checkbutton 選擇圖形模式
        self.pattern_vars = {}
        available_patterns = [
            'W底', '頭肩頂', '頭肩底', '雙頂', '雙底',
            '三角形', '旗形', 'V形反轉', '圓頂', '圓底', '矩形', '楔形'
        ]
        
        # 分兩列顯示
        left_frame = tk.Frame(pattern_frame, bg=self.dark_panel)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        
        right_frame = tk.Frame(pattern_frame, bg=self.dark_panel)
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        
        for i, pattern in enumerate(available_patterns):
            var = tk.BooleanVar(value=False)
            self.pattern_vars[pattern] = var
            frame = left_frame if i < len(available_patterns) // 2 else right_frame
            ttk.Checkbutton(
                frame,
                text=pattern,
                variable=var
            ).pack(anchor=tk.W, padx=5, pady=2)
        
        # 全選/全不選按鈕
        button_frame = tk.Frame(pattern_frame, bg=self.dark_panel)
        button_frame.pack(fill=tk.X, pady=5)
        
        ttk.Button(
            button_frame,
            text="全選",
            command=lambda: [var.set(True) for var in self.pattern_vars.values()]
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            button_frame,
            text="全不選",
            command=lambda: [var.set(False) for var in self.pattern_vars.values()]
        ).pack(side=tk.LEFT, padx=5)
    
    def create_signal_combination_tab(self, parent):
        """創建信號組合標籤頁"""
        # parent 已經是 tk.Frame，背景色已在創建時設置
        
        # 技術指標選擇
        tech_frame = ttk.LabelFrame(parent, text="技術指標信號", padding=12)
        tech_frame.pack(fill=tk.X, padx=12, pady=8)
        
        self.tech_signal_vars = {
            'momentum': tk.BooleanVar(value=False),
            'volatility': tk.BooleanVar(value=False),
            'trend': tk.BooleanVar(value=False)
        }
        
        ttk.Checkbutton(tech_frame, text="動量指標", variable=self.tech_signal_vars['momentum']).pack(anchor=tk.W, padx=5, pady=2)
        ttk.Checkbutton(tech_frame, text="波動率指標", variable=self.tech_signal_vars['volatility']).pack(anchor=tk.W, padx=5, pady=2)
        ttk.Checkbutton(tech_frame, text="趨勢指標", variable=self.tech_signal_vars['trend']).pack(anchor=tk.W, padx=5, pady=2)
        
        # 成交量條件
        volume_frame = ttk.LabelFrame(parent, text="成交量條件", padding=12)
        volume_frame.pack(fill=tk.X, padx=12, pady=8)
        
        self.volume_condition_vars = {
            'increasing': tk.BooleanVar(value=False),
            'decreasing': tk.BooleanVar(value=False),
            'spike': tk.BooleanVar(value=False)
        }
        
        ttk.Checkbutton(volume_frame, text="成交量增加", variable=self.volume_condition_vars['increasing']).pack(anchor=tk.W, padx=5, pady=2)
        ttk.Checkbutton(volume_frame, text="成交量減少", variable=self.volume_condition_vars['decreasing']).pack(anchor=tk.W, padx=5, pady=2)
        ttk.Checkbutton(volume_frame, text="成交量尖峰", variable=self.volume_condition_vars['spike']).pack(anchor=tk.W, padx=5, pady=2)
        
        # 權重設置
        weight_frame = ttk.LabelFrame(parent, text="信號權重設置", padding=12)
        weight_frame.pack(fill=tk.X, padx=12, pady=8)
        
        ttk.Label(weight_frame, text="圖形模式權重:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.pattern_weight_var = tk.StringVar(value="30")
        ttk.Scale(weight_frame, from_=0, to=100, orient=tk.HORIZONTAL, variable=self.pattern_weight_var, length=200).grid(row=0, column=1, padx=5)
        ttk.Label(weight_frame, textvariable=self.pattern_weight_var).grid(row=0, column=2, padx=5)
        
        ttk.Label(weight_frame, text="技術指標權重:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        self.technical_weight_var = tk.StringVar(value="50")
        ttk.Scale(weight_frame, from_=0, to=100, orient=tk.HORIZONTAL, variable=self.technical_weight_var, length=200).grid(row=1, column=1, padx=5)
        ttk.Label(weight_frame, textvariable=self.technical_weight_var).grid(row=1, column=2, padx=5)
        
        ttk.Label(weight_frame, text="成交量權重:").grid(row=2, column=0, padx=5, pady=5, sticky=tk.W)
        self.volume_weight_var = tk.StringVar(value="20")
        ttk.Scale(weight_frame, from_=0, to=100, orient=tk.HORIZONTAL, variable=self.volume_weight_var, length=200).grid(row=2, column=1, padx=5)
        ttk.Label(weight_frame, textvariable=self.volume_weight_var).grid(row=2, column=2, padx=5)
    
    def create_filter_tab(self, parent):
        """創建篩選條件標籤頁"""
        # parent 已經是 tk.Frame，背景色已在創建時設置
        
        # 漲幅篩選
        price_frame = ttk.LabelFrame(parent, text="漲幅篩選", padding=12)
        price_frame.pack(fill=tk.X, padx=12, pady=8)
        
        ttk.Label(price_frame, text="最小漲幅(%):").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.price_change_min_var = tk.StringVar(value="0")
        ttk.Spinbox(price_frame, from_=-50, to=100, textvariable=self.price_change_min_var, width=15).grid(row=0, column=1, padx=5)
        
        ttk.Label(price_frame, text="最大漲幅(%):").grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        self.price_change_max_var = tk.StringVar(value="100")
        ttk.Spinbox(price_frame, from_=-50, to=100, textvariable=self.price_change_max_var, width=15).grid(row=0, column=3, padx=5)
        
        # 成交量篩選
        volume_filter_frame = ttk.LabelFrame(parent, text="成交量篩選", padding=12)
        volume_filter_frame.pack(fill=tk.X, padx=12, pady=8)
        
        ttk.Label(volume_filter_frame, text="最小成交量比率:").grid(row=0, column=0, padx=8, pady=8, sticky=tk.W)
        self.volume_ratio_min_var = tk.StringVar(value="1.0")
        ttk.Spinbox(volume_filter_frame, from_=0.1, to=10.0, increment=0.1, textvariable=self.volume_ratio_min_var, width=12).grid(row=0, column=1, padx=8)
        
        # RSI 篩選
        rsi_filter_frame = ttk.LabelFrame(parent, text="RSI 篩選", padding=12)
        rsi_filter_frame.pack(fill=tk.X, padx=12, pady=8)
        
        ttk.Label(rsi_filter_frame, text="RSI 最小值:").grid(row=0, column=0, padx=8, pady=8, sticky=tk.W)
        self.rsi_min_var = tk.StringVar(value="0")
        ttk.Spinbox(rsi_filter_frame, from_=0, to=100, textvariable=self.rsi_min_var, width=12).grid(row=0, column=1, padx=8)
        
        ttk.Label(rsi_filter_frame, text="RSI 最大值:").grid(row=0, column=2, padx=8, pady=8, sticky=tk.W)
        self.rsi_max_var = tk.StringVar(value="100")
        ttk.Spinbox(rsi_filter_frame, from_=0, to=100, textvariable=self.rsi_max_var, width=12).grid(row=0, column=3, padx=8)
        
        # 其他篩選條件
        other_frame = ttk.LabelFrame(parent, text="其他篩選條件", padding=12)
        other_frame.pack(fill=tk.X, padx=12, pady=8)
        
        ttk.Label(other_frame, text="最小市值（可選）:").grid(row=0, column=0, padx=8, pady=8, sticky=tk.W)
        self.market_cap_min_var = tk.StringVar(value="")
        ttk.Entry(other_frame, textvariable=self.market_cap_min_var, width=12).grid(row=0, column=1, padx=8)
        
        ttk.Label(other_frame, text="最大市值（可選）:").grid(row=0, column=2, padx=8, pady=8, sticky=tk.W)
        self.market_cap_max_var = tk.StringVar(value="")
        ttk.Entry(other_frame, textvariable=self.market_cap_max_var, width=12).grid(row=0, column=3, padx=8)
        
        # 產業篩選
        industry_filter_frame = ttk.LabelFrame(parent, text="產業篩選", padding=12)
        industry_filter_frame.pack(fill=tk.X, padx=12, pady=8)
        
        ttk.Label(industry_filter_frame, text="產業類別:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.industry_filter_var = tk.StringVar(value="全部")
        
        # 獲取所有產業類別
        all_industries = ["全部"] + self.industry_mapper.get_all_industries()
        industry_combo = ttk.Combobox(
            industry_filter_frame,
            textvariable=self.industry_filter_var,
            values=all_industries,
            width=30,
            state='readonly'
        )
        industry_combo.grid(row=0, column=1, padx=5, sticky=tk.W)
        
        ttk.Label(industry_filter_frame, text="（選擇特定產業只分析該產業的股票）").grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
    
    def create_result_tab(self, parent):
        """創建推薦結果標籤頁"""
        # 結果顯示區域
        result_frame = ttk.LabelFrame(parent, text="策略推薦結果", padding=10)
        result_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 使用 Treeview 顯示推薦股票（增加分數詳情和產業欄位）
        columns = ('排名', '證券代號', '證券名稱', '產業', '收盤價', '漲幅%', '總分', '指標分', '圖形分', '成交量分', '推薦理由')
        self.recommendation_tree = ttk.Treeview(result_frame, columns=columns, show='headings', height=15)
        
        # 優化列寬：根據內容和重要性設置
        recommendation_column_widths = {
            '排名': 60,
            '證券代號': 80,
            '證券名稱': 100,
            '產業': 120,
            '收盤價': 80,
            '漲幅%': 80,
            '總分': 70,
            '指標分': 70,
            '圖形分': 70,
            '成交量分': 80,
            '推薦理由': 400  # 推薦理由需要更多空間
        }
        
        for col in columns:
            self.recommendation_tree.heading(col, text=col, anchor='center')
            self.recommendation_tree.column(col, width=recommendation_column_widths.get(col, 100), anchor='center', minwidth=50)
        
        scrollbar_result = ttk.Scrollbar(result_frame, orient=tk.VERTICAL, command=self.recommendation_tree.yview)
        self.recommendation_tree.configure(yscrollcommand=scrollbar_result.set)
        
        # 包裝在 Frame 中以便設置背景
        tree_container = tk.Frame(result_frame, bg=self.dark_panel)
        tree_container.pack(fill=tk.BOTH, expand=True)
        
        self.recommendation_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 2), in_=tree_container)
        scrollbar_result.pack(side=tk.RIGHT, fill=tk.Y, in_=tree_container)
        
        # 選擇股票功能
        select_frame = ttk.LabelFrame(parent, text="我的選股", padding=10)
        select_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(select_frame, text="已選擇股票:").pack(side=tk.LEFT, padx=5)
        self.selected_stocks_var = tk.StringVar(value="")
        ttk.Entry(select_frame, textvariable=self.selected_stocks_var, width=50).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            select_frame,
            text="從推薦列表選擇",
            command=self.select_from_recommendations
        ).pack(side=tk.LEFT, padx=5)
        
        # 綁定雙擊事件選擇股票
        self.recommendation_tree.bind('<Double-1>', self.on_stock_double_click)
    
    def _update_config(self, category, subcategory, key, value):
        """更新策略配置"""
        if category not in self.strategy_config:
            self.strategy_config[category] = {}
        if subcategory not in self.strategy_config[category]:
            self.strategy_config[category][subcategory] = {}
        self.strategy_config[category][subcategory][key] = value
    
    def query_strong_stocks(self):
        """查詢強勢股"""
        try:
            period = self.strong_period_var.get()
            top_n = int(self.strong_top_n_var.get())
            
            # 清空現有結果
            for item in self.strong_stocks_tree.get_children():
                self.strong_stocks_tree.delete(item)
            
            # 查詢強勢股
            result = self.stock_screener.get_strong_stocks(period=period, top_n=top_n)
            
            # 處理新的返回格式（元組：DataFrame, universe_count）
            if isinstance(result, tuple):
                df, universe_count = result
            else:
                # 向後兼容：如果返回的是舊格式（只有 DataFrame）
                df = result
            
            if len(df) == 0:
                messagebox.showinfo("提示", "沒有找到強勢股數據")
                return
            
            # 確保按評分降序排序（stock_screener 已經排序，這裡再次確認）
            df = df.sort_values('評分', ascending=False).reset_index(drop=True)
            df['排名'] = range(1, len(df) + 1)
            
            # 顯示結果（包含推薦理由，優化格式）
            for idx, row in df.iterrows():
                # 格式化數值，讓顯示更整齊
                price_change = row.get('漲幅%', 0)
                score = row.get('評分', 0)
                
                # 漲幅顯示正負號和百分號
                if price_change > 0:
                    price_str = f"+{price_change:.2f}%"
                elif price_change < 0:
                    price_str = f"{price_change:.2f}%"
                else:
                    price_str = "0.00%"
                
                values = (
                    str(row.get('排名', '')),
                    str(row.get('證券代號', '')),
                    str(row.get('證券名稱', '')),
                    f"{row.get('收盤價', 0):.2f}",
                    price_str,
                    f"{score:.2f}",
                    str(row.get('推薦理由', '符合強勢股條件'))
                )
                self.strong_stocks_tree.insert('', tk.END, values=values)
        except Exception as e:
            messagebox.showerror("錯誤", f"查詢強勢股失敗: {str(e)}")
    
    def query_strong_industries(self):
        """查詢強勢產業"""
        try:
            period = self.strong_period_var.get()
            top_n = int(self.strong_top_n_var.get())
            
            # 清空現有結果
            for item in self.strong_industries_tree.get_children():
                self.strong_industries_tree.delete(item)
            
            # 查詢強勢產業
            df = self.stock_screener.get_strong_industries(period=period, top_n=top_n)
            
            if len(df) == 0:
                messagebox.showinfo("提示", "沒有找到強勢產業數據")
                return
            
            # 顯示結果
            for idx, row in df.iterrows():
                values = (
                    row.get('排名', ''),
                    row.get('指數名稱', ''),
                    f"{row.get('收盤指數', 0):.2f}",
                    f"{row.get('漲幅%', 0):.2f}"
                )
                self.strong_industries_tree.insert('', tk.END, values=values)
        except Exception as e:
            messagebox.showerror("錯誤", f"查詢強勢產業失敗: {str(e)}")
    
    def execute_strategy_analysis(self):
        """執行策略分析（在背景執行）"""
        # 檢測市場狀態
        regime_result = self.regime_detector.detect_regime()
        self.current_regime = regime_result.get('regime', 'Trend')
        regime_confidence = regime_result.get('confidence', 0.5)
        
        # 更新UI顯示市場狀態
        regime_name_map = {
            'Trend': '趨勢追蹤',
            'Reversion': '均值回歸',
            'Breakout': '突破準備'
        }
        regime_name = regime_name_map.get(self.current_regime, self.current_regime)
        self.regime_label.config(
            text=f"市場狀態：{regime_name} (信心度: {regime_confidence:.0%})",
            foreground="green" if regime_confidence > 0.7 else "orange"
        )
        
        # 收集配置（如果用戶沒有手動配置，使用 Regime 對應的策略）
        config = self._collect_strategy_config()
        
        # 如果用戶沒有啟用任何指標，使用 Regime 預設配置
        if not self._has_user_config(config):
            regime_config = self.regime_detector.get_strategy_config(self.current_regime)
            config = self._merge_configs(config, regime_config)
        
        # 添加 Regime 信息到配置
        config['regime'] = self.current_regime
        config['regime_confidence'] = regime_confidence
        
        # 清空現有結果
        for item in self.recommendation_tree.get_children():
            self.recommendation_tree.delete(item)
        
        # 在背景執行分析（使用 service 層）
        thread = threading.Thread(
            target=self._execute_strategy_analysis_thread,
            args=(config,),
            daemon=True
        )
        thread.start()
    
    def detect_market_regime(self):
        """檢測市場狀態（手動觸發）"""
        try:
            regime_result = self.regime_detector.detect_regime()
            self.current_regime = regime_result.get('regime', 'Trend')
            regime_confidence = regime_result.get('confidence', 0.5)
            details = regime_result.get('details', {})
            
            regime_name_map = {
                'Trend': '趨勢追蹤',
                'Reversion': '均值回歸',
                'Breakout': '突破準備'
            }
            regime_name = regime_name_map.get(self.current_regime, self.current_regime)
            
            # 信心度說明
            confidence_explanation = self._get_confidence_explanation(self.current_regime, details, regime_confidence)
            
            # 更新市場信息顯示
            detail_text = f"市場狀態：{regime_name}\n"
            detail_text += f"信心度：{regime_confidence:.0%}\n"
            detail_text += f"信心度說明：{confidence_explanation}\n\n"
            detail_text += "判斷依據：\n"
            
            # 將英文 key 轉換為中文
            key_map = {
                'close': '收盤價',
                'ma20': '20日均線',
                'ma60': '60日均線',
                'atr': '平均真實波幅(ATR)',
                'atr_convergence': 'ATR收斂',
                'price_near_range': '價格接近區間',
                'adx': 'ADX指標',
                'ma20_trend': 'MA20趨勢向上',
                'in_range': '價格在區間內',
                'default': '預設狀態'
            }
            
            for key, value in details.items():
                if key != 'error' and key != 'default':
                    chinese_key = key_map.get(key, key)
                    if isinstance(value, bool):
                        chinese_value = '是' if value else '否'
                        detail_text += f"  {chinese_key}：{chinese_value}\n"
                    elif isinstance(value, float):
                        detail_text += f"  {chinese_key}：{value:.2f}\n"
                    else:
                        detail_text += f"  {chinese_key}：{value}\n"
            
            # 更新 Text 控件顯示
            self.market_info_text.config(state=tk.NORMAL)
            self.market_info_text.delete('1.0', tk.END)
            self.market_info_text.insert('1.0', detail_text)
            self.market_info_text.config(state=tk.DISABLED)
            
            # 顯示彈窗提示
            messagebox.showinfo("市場狀態檢測", f"市場狀態：{regime_name}\n信心度：{regime_confidence:.0%}")
            
        except Exception as e:
            messagebox.showerror("錯誤", f"檢測市場狀態失敗: {str(e)}")
            # 更新顯示錯誤信息
            self.market_info_text.config(state=tk.NORMAL)
            self.market_info_text.delete('1.0', tk.END)
            self.market_info_text.insert('1.0', f'檢測失敗：{str(e)}')
            self.market_info_text.config(state=tk.DISABLED)
    
    def _get_confidence_explanation(self, regime, details, confidence):
        """獲取信心度說明
        
        Args:
            regime: 市場狀態 ('Trend', 'Reversion', 'Breakout')
            details: 詳細判斷依據
            confidence: 信心度 (0-1)
            
        Returns:
            str: 信心度說明文字
        """
        if regime == 'Trend':
            # 趨勢追蹤：基礎 0.8，如果 close > ma20 則 0.9
            if confidence >= 0.9:
                return "收盤價高於20日均線，趨勢明確"
            elif confidence >= 0.8:
                return "收盤價高於60日均線且MA20上彎，趨勢確立"
            else:
                return "部分趨勢條件滿足"
        
        elif regime == 'Breakout':
            # 突破準備：基礎 0.7，如果 atr_convergence 和 price_near_range 都為 True 則 0.85
            if confidence >= 0.85:
                return "ATR收斂且價格接近關鍵區間，突破信號強"
            elif confidence >= 0.7:
                return "ATR收斂或價格接近區間，具備突破條件"
            else:
                return "部分突破條件滿足"
        
        elif regime == 'Reversion':
            # 均值回歸：基礎 0.75，如果 adx < 15 則 0.85
            if confidence >= 0.85:
                return "ADX指標低於15，盤整特徵明顯"
            elif confidence >= 0.75:
                return "價格在均線區間內震盪，適合均值回歸"
            else:
                return "部分回歸條件滿足"
        
        else:
            return "預設狀態"
    
    def _has_user_config(self, config: dict) -> bool:
        """檢查用戶是否有手動配置"""
        tech_config = config.get('technical', {})
        patterns = config.get('patterns', {}).get('selected', [])
        
        # 檢查是否有啟用的指標
        has_indicators = (
            tech_config.get('momentum', {}).get('enabled', False) or
            tech_config.get('volatility', {}).get('enabled', False) or
            tech_config.get('trend', {}).get('enabled', False)
        )
        
        # 檢查是否有選擇圖形模式
        has_patterns = len(patterns) > 0
        
        return has_indicators or has_patterns
    
    def _merge_configs(self, user_config: dict, regime_config: dict) -> dict:
        """合併用戶配置和 Regime 配置（用戶配置優先）"""
        merged = regime_config.copy()
        
        # 如果用戶有配置，保留用戶配置
        tech_config = user_config.get('technical', {})
        if self._has_user_config(user_config):
            merged['technical'] = tech_config
        
        patterns = user_config.get('patterns', {}).get('selected', [])
        if len(patterns) > 0:
            merged['patterns'] = user_config['patterns']
        
        return merged
    
    def _execute_strategy_analysis_thread(self, config):
        """執行策略分析線程（使用 service 層）"""
        try:
            # 使用 recommendation_service 執行推薦
            recommendations = self.recommendation_service.run_recommendation(
                config=config,
                max_stocks=200,
                top_n=50
            )
            
            # 轉換為 UI 顯示格式
            all_recommendations = []
            for rec in recommendations:
                all_recommendations.append({
                    '證券代號': rec.stock_code,
                    '證券名稱': rec.stock_name,
                    '產業': rec.industry,
                    '收盤價': rec.close_price,
                    '漲幅%': rec.price_change,
                    '總分': rec.total_score,
                    '指標分': rec.indicator_score,
                    '圖形分': rec.pattern_score,
                    '成交量分': rec.volume_score,
                    '推薦理由': rec.recommendation_reasons,
                })
            
            # 更新 UI（在 UI 線程中執行）
            if len(all_recommendations) == 0:
                self.root.after(0, lambda: messagebox.showinfo("提示", "沒有找到符合條件的股票"))
            else:
                self.root.after(0, lambda: self._display_recommendations(all_recommendations))
                self.root.after(0, lambda: messagebox.showinfo("完成", f"策略分析完成，找到 {len(all_recommendations)} 支符合條件的股票"))
            return
            
        except Exception as e:
            import traceback
            error_msg = f"執行策略分析失敗: {str(e)}\n{traceback.format_exc()}"
            self.root.after(0, lambda: messagebox.showerror("錯誤", error_msg))
            return
            # 讀取股票數據
            stock_data_file = self.config.stock_data_file
            if not stock_data_file.exists():
                self.root.after(0, lambda: messagebox.showerror("錯誤", "找不到股票數據文件"))
                return
            
            # 讀取最新數據（最近60天，確保有足夠數據計算技術指標）
            df = pd.read_csv(stock_data_file, encoding='utf-8-sig', on_bad_lines='skip', engine='python', nrows=500000)
            df['日期'] = pd.to_datetime(df['日期'], errors='coerce')
            df = df[df['日期'].notna()]
            
            if len(df) == 0:
                messagebox.showerror("錯誤", "沒有找到股票數據")
                return
            
            latest_date = df['日期'].max()
            # 取最近60天的數據
            df = df[df['日期'] >= (latest_date - pd.Timedelta(days=60))]
            
            if len(df) == 0:
                messagebox.showerror("錯誤", "沒有找到足夠的歷史數據")
                return
            
            # 按股票分組處理
            if '證券代號' in df.columns:
                stock_col = '證券代號'
            elif '股票代號' in df.columns:
                stock_col = '股票代號'
                df['證券代號'] = df['股票代號']
                stock_col = '證券代號'
            else:
                messagebox.showerror("錯誤", "找不到股票代號欄位")
                return
            
            # 確保有證券名稱欄位
            if '證券名稱' not in df.columns:
                if '股票名稱' in df.columns:
                    df['證券名稱'] = df['股票名稱']
                else:
                    df['證券名稱'] = df['證券代號']
            
            # 清空現有結果
            for item in self.recommendation_tree.get_children():
                self.recommendation_tree.delete(item)
            
            # 應用產業篩選（在處理前先篩選股票）
            industry_filter = config.get('filters', {}).get('industry', '全部')
            stocks = df[stock_col].unique()[:200]  # 限制處理前200支股票以提升速度
            
            if industry_filter and industry_filter != '全部':
                # 篩選出屬於指定產業的股票
                filtered_stocks = self.industry_mapper.filter_stocks_by_industry(
                    [str(s) for s in stocks],
                    industry_filter
                )
                stocks = [s for s in stocks if str(s) in filtered_stocks]
                if len(stocks) == 0:
                    self.root.after(0, lambda: messagebox.showinfo("提示", f"在選定的股票中沒有找到屬於「{industry_filter}」產業的股票"))
                    return
            
            # 對每支股票執行策略分析
            all_recommendations = []
            
            # 顯示開始訊息（在UI線程中執行）
            self.root.after(0, lambda: self._clear_and_show_progress(f"開始分析 {len(stocks)} 支股票..."))
            
            for idx, stock_code in enumerate(stocks):
                stock_df = df[df[stock_col] == stock_code].copy()
                stock_df = stock_df.sort_values('日期').reset_index(drop=True)
                
                # 確保至少有20筆數據才能計算技術指標
                if len(stock_df) < 20:
                    continue
                
                try:
                    # 生成推薦
                    result_df = self.strategy_configurator.generate_recommendations(stock_df, config)
                    
                    if len(result_df) > 0:
                        latest_row = result_df.iloc[-1]
                        
                        # 獲取收盤價
                        close_col = None
                        for col in ['收盤價', 'Close', 'close']:
                            if col in latest_row.index:
                                close_col = col
                                break
                        
                        # 計算漲幅（與前一日比較）
                        price_change = 0
                        if len(stock_df) >= 2 and close_col:
                            prev_price = stock_df.iloc[-2].get(close_col, 0)
                            curr_price = latest_row.get(close_col, 0)
                            if prev_price > 0:
                                price_change = (curr_price - prev_price) / prev_price * 100
                        
                        # 獲取股票所屬產業
                        stock_industries = self.industry_mapper.get_stock_industries(stock_code)
                        industry_display = ', '.join(stock_industries[:2]) if stock_industries else '未知'
                        if len(stock_industries) > 2:
                            industry_display += '...'
                        
                        # 生成推薦理由（包含市場狀態和產業信息）
                        reasons = self.reason_engine.generate_reasons(latest_row, config)
                        
                        # 添加產業表現理由
                        if stock_industries:
                            for industry in stock_industries[:1]:  # 只取第一個產業
                                industry_perf = self.industry_mapper.get_industry_performance(industry)
                                if industry_perf:
                                    industry_change = industry_perf.get('漲跌百分比', 0)
                                    if isinstance(industry_change, str):
                                        try:
                                            industry_change = float(industry_change.replace('%', ''))
                                        except:
                                            industry_change = 0
                                    
                                    if industry_change > 0:
                                        reasons.append({
                                            'tag': f'{industry}指數上漲',
                                            'evidence': f'{industry}類指數漲幅 {industry_change:.2f}%',
                                            'score_contrib': min(industry_change * 0.5, 10)
                                        })
                        
                        reason_text = self.reason_engine.format_reason_text(reasons, max_reasons=3)
                        
                        # 使用 FinalScore（含 Regime Match Factor）作為排序依據
                        final_score = latest_row.get('FinalScore', latest_row.get('TotalScore', latest_row.get('綜合評分', 0)))
                        
                        all_recommendations.append({
                            '證券代號': stock_code,
                            '證券名稱': latest_row.get('證券名稱', stock_df.iloc[-1].get('證券名稱', stock_code)),
                            '產業': industry_display,
                            '收盤價': latest_row.get(close_col, stock_df.iloc[-1].get(close_col, 0)) if close_col else 0,
                            '漲幅%': price_change,
                            '總分': final_score,
                            '指標分': latest_row.get('IndicatorScore', 0),
                            '圖形分': latest_row.get('PatternScore', 0),
                            '成交量分': latest_row.get('VolumeScore', 0),
                            '推薦理由': reason_text,
                            'stock_industries': stock_industries,  # 保存產業列表供篩選使用
                            'reasons_detail': reasons  # 保存詳細理由供後續使用
                        })
                except Exception as e:
                    continue
                
                # 每處理50支股票更新一次進度（可選，避免UI卡頓）
                # if (idx + 1) % 50 == 0:
                #     pass  # 可以添加進度條更新
            
            # 排序並顯示
            if len(all_recommendations) == 0:
                self.root.after(0, lambda: messagebox.showinfo("提示", "沒有找到符合條件的股票"))
                return
            
            # 應用產業篩選
            industry_filter = config.get('filters', {}).get('industry', '全部')
            if industry_filter and industry_filter != '全部':
                filtered_recommendations = []
                for rec in all_recommendations:
                    stock_industries = rec.get('stock_industries', [])
                    if industry_filter in stock_industries:
                        filtered_recommendations.append(rec)
                all_recommendations = filtered_recommendations
            
            # 應用產業篩選
            industry_filter = config.get('filters', {}).get('industry', '全部')
            if industry_filter and industry_filter != '全部':
                filtered_recommendations = []
                for rec in all_recommendations:
                    stock_industries = rec.get('stock_industries', [])
                    if industry_filter in stock_industries:
                        filtered_recommendations.append(rec)
                all_recommendations = filtered_recommendations
            
            # 按總分排序（使用 FinalScore）
            all_recommendations.sort(key=lambda x: x.get('總分', 0), reverse=True)
            
            # 顯示結果（在UI線程中執行）
            self.root.after(0, lambda: self._display_recommendations(all_recommendations[:50]))
            
            self.root.after(0, lambda: messagebox.showinfo("完成", f"策略分析完成，找到 {len(all_recommendations)} 支符合條件的股票"))
            
        except Exception as e:
            import traceback
            error_msg = f"執行策略分析失敗: {str(e)}\n{traceback.format_exc()}"
            self.root.after(0, lambda: messagebox.showerror("錯誤", error_msg))
    
    def _collect_strategy_config(self):
        """收集策略配置"""
        config = {
            'technical': {
                'momentum': {
                    'enabled': self.momentum_enabled.get(),
                    'rsi': {
                        'enabled': self.rsi_enabled.get(),
                        'period': int(self.rsi_period_var.get())
                    },
                    'macd': {
                        'enabled': self.macd_enabled.get(),
                        'fast': int(self.macd_fast_var.get()),
                        'slow': int(self.macd_slow_var.get()),
                        'signal': int(self.macd_signal_var.get())
                    },
                    'kd': {
                        'enabled': self.kd_enabled.get()
                    }
                },
                'volatility': {
                    'enabled': self.volatility_enabled.get(),
                    'bollinger': {
                        'enabled': self.bb_enabled.get(),
                        'window': int(self.bb_window_var.get()),
                        'std': float(self.bb_std_var.get())
                    },
                    'atr': {
                        'enabled': self.atr_enabled.get(),
                        'period': int(self.atr_period_var.get())
                    }
                },
                'trend': {
                    'enabled': self.trend_enabled.get(),
                    'adx': {
                        'enabled': self.adx_enabled.get(),
                        'period': int(self.adx_period_var.get())
                    },
                    'ma': {
                        'enabled': self.ma_enabled.get(),
                        'windows': [int(x) for x in self.ma_windows_var.get().split(',')]
                    }
                }
            },
            'patterns': {
                'selected': [pattern for pattern, var in self.pattern_vars.items() if var.get()]
            },
            'signals': {
                'technical_indicators': [
                    key for key, var in self.tech_signal_vars.items() if var.get()
                ],
                'volume_conditions': [
                    key for key, var in self.volume_condition_vars.items() if var.get()
                ],
                'weights': {
                    'pattern': float(self.pattern_weight_var.get()) / 100,
                    'technical': float(self.technical_weight_var.get()) / 100,
                    'volume': float(self.volume_weight_var.get()) / 100
                }
            },
            'filters': {
                'price_change_min': float(self.price_change_min_var.get()),
                'price_change_max': float(self.price_change_max_var.get()),
                'volume_ratio_min': float(self.volume_ratio_min_var.get()),
                'rsi_min': float(self.rsi_min_var.get()),
                'rsi_max': float(self.rsi_max_var.get()),
                'industry': self.industry_filter_var.get() if hasattr(self, 'industry_filter_var') else '全部'
            }
        }
        
        if self.market_cap_min_var.get():
            config['filters']['market_cap_min'] = float(self.market_cap_min_var.get())
        if self.market_cap_max_var.get():
            config['filters']['market_cap_max'] = float(self.market_cap_max_var.get())
        
        return config
    
    def _clear_and_show_progress(self, message):
        """清空結果並顯示進度"""
        for item in self.recommendation_tree.get_children():
            self.recommendation_tree.delete(item)
        # 可以添加進度顯示（可選）
    
    def _display_recommendations(self, recommendations):
        """顯示推薦結果（使用統一打分模型的分數，包含產業信息，優化格式，深色主題）"""
        # 先清空現有結果
        for item in self.recommendation_tree.get_children():
            self.recommendation_tree.delete(item)
        
        # 顯示推薦結果
        for idx, rec in enumerate(recommendations, 1):
            # 處理分數顯示
            total_score = rec.get('總分', rec.get('綜合評分', 0))
            indicator_score = rec.get('指標分', 0)
            pattern_score = rec.get('圖形分', 0)
            volume_score = rec.get('成交量分', 0)
            
            # 格式化數值（帶正負號和百分號）
            price_change = rec.get('漲幅%', 0)
            if price_change > 0:
                price_str = f"+{price_change:.2f}%"
            elif price_change < 0:
                price_str = f"{price_change:.2f}%"
            else:
                price_str = "0.00%"
            
            values = (
                str(idx),
                str(rec['證券代號']),
                str(rec['證券名稱']),
                str(rec.get('產業', '未知')),
                f"{rec['收盤價']:.2f}",
                price_str,
                f"{total_score:.1f}" if pd.notna(total_score) and total_score > 0 else "0.0",
                f"{indicator_score:.1f}" if pd.notna(indicator_score) and indicator_score > 0 else "0.0",
                f"{pattern_score:.1f}" if pd.notna(pattern_score) and pattern_score > 0 else "0.0",
                f"{volume_score:.1f}" if pd.notna(volume_score) and volume_score > 0 else "0.0",
                str(rec.get('推薦理由', '符合策略條件'))
            )
            self.recommendation_tree.insert('', tk.END, values=values)
    
    def _generate_recommendation_reason(self, row):
        """生成推薦理由"""
        reasons = []
        
        # 檢查 RSI
        rsi_val = None
        for col in ['RSI', 'rsi', 'RSI_14']:
            if col in row.index:
                rsi_val = row[col]
                break
        
        if rsi_val is not None and pd.notna(rsi_val):
            if rsi_val < 30:
                reasons.append("RSI超賣")
            elif rsi_val > 70:
                reasons.append("RSI超買")
        
        # 檢查 MACD
        macd_val = None
        macd_signal_val = None
        for col in ['MACD', 'macd']:
            if col in row.index:
                macd_val = row[col]
                break
        for col in ['MACD_Signal', 'macd_signal', 'Signal']:
            if col in row.index:
                macd_signal_val = row[col]
                break
        
        if macd_val is not None and macd_signal_val is not None:
            if pd.notna(macd_val) and pd.notna(macd_signal_val):
                if macd_val > macd_signal_val:
                    reasons.append("MACD金叉")
        
        # 檢查漲幅
        change_val = None
        for col in ['漲幅%', '漲跌幅', 'ChangePercent']:
            if col in row.index:
                change_val = row[col]
                break
        
        if change_val is not None and pd.notna(change_val):
            if change_val > 5:
                reasons.append("漲幅強勁")
            elif change_val < -5:
                reasons.append("跌幅較大")
        
        # 檢查成交量
        volume_change = None
        for col in ['成交量變化率%', 'Volume_Change', 'volume_ratio']:
            if col in row.index:
                volume_change = row[col]
                break
        
        if volume_change is not None and pd.notna(volume_change):
            if volume_change > 50:
                reasons.append("成交量放大")
        
        # 檢查圖形模式
        if 'Pattern_Signal' in row.index:
            pattern_signal = row['Pattern_Signal']
            if pd.notna(pattern_signal) and pattern_signal > 0:
                reasons.append("看漲形態")
        
        return "、".join(reasons) if reasons else "符合策略條件"
    
    def on_stock_double_click(self, event):
        """雙擊股票時添加到選股列表"""
        selection = self.recommendation_tree.selection()
        if selection:
            item = self.recommendation_tree.item(selection[0])
            stock_code = item['values'][1]  # 證券代號在第2列
            
            current = self.selected_stocks_var.get()
            if current:
                stocks = current.split(',')
                if stock_code not in stocks:
                    stocks.append(stock_code)
                    self.selected_stocks_var.set(','.join(stocks))
            else:
                self.selected_stocks_var.set(stock_code)
    
    def select_from_recommendations(self):
        """從推薦列表選擇股票"""
        selection = self.recommendation_tree.selection()
        if not selection:
            messagebox.showinfo("提示", "請先選擇要加入的股票")
            return
        
        selected_stocks = []
        for item_id in selection:
            item = self.recommendation_tree.item(item_id)
            stock_code = item['values'][1]
            selected_stocks.append(stock_code)
        
        current = self.selected_stocks_var.get()
        if current:
            stocks = current.split(',')
            stocks.extend([s for s in selected_stocks if s not in stocks])
            self.selected_stocks_var.set(','.join(stocks))
        else:
            self.selected_stocks_var.set(','.join(selected_stocks))
    
    def clear_strategy_config(self):
        """清除策略配置"""
        # 重置所有配置變數
        self.momentum_enabled.set(False)
        self.volatility_enabled.set(False)
        self.trend_enabled.set(False)
        self.rsi_enabled.set(False)
        self.macd_enabled.set(False)
        self.kd_enabled.set(False)
        self.bb_enabled.set(False)
        self.atr_enabled.set(False)
        self.adx_enabled.set(False)
        self.ma_enabled.set(False)
        
        for var in self.pattern_vars.values():
            var.set(False)
        
        for var in self.tech_signal_vars.values():
            var.set(False)
        
        for var in self.volume_condition_vars.values():
            var.set(False)
        
        # 清空結果
        for item in self.recommendation_tree.get_children():
            self.recommendation_tree.delete(item)
        
        self.selected_stocks_var.set("")
        messagebox.showinfo("完成", "策略配置已清除")
    
    def save_strategy_config(self):
        """保存策略配置"""
        import json
        from tkinter import filedialog
        
        config = self._collect_strategy_config()
        
        filename = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
                messagebox.showinfo("完成", f"策略配置已保存到: {filename}")
            except Exception as e:
                messagebox.showerror("錯誤", f"保存失敗: {str(e)}")
    
    def load_strategy_config(self):
        """載入策略配置"""
        import json
        from tkinter import filedialog
        
        filename = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if filename:
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                # 載入配置到UI
                # TODO: 實現配置載入邏輯
                messagebox.showinfo("完成", f"策略配置已載入: {filename}")
            except Exception as e:
                messagebox.showerror("錯誤", f"載入失敗: {str(e)}")
        
    def create_backtest_tab(self):
        """創建回測標籤頁"""
        # 標題
        title_label = ttk.Label(
            self.backtest_frame, 
            text="策略回測", 
            font=("Arial", 16, "bold")
        )
        title_label.pack(pady=10)
        
        # 回測設置
        settings_frame = ttk.LabelFrame(self.backtest_frame, text="回測設置", padding=10)
        settings_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # 股票代號
        ttk.Label(settings_frame, text="股票代號:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.stock_code_entry = ttk.Entry(settings_frame, width=15)
        self.stock_code_entry.grid(row=0, column=1, padx=5, pady=5)
        self.stock_code_entry.insert(0, "2330")
        
        # 日期範圍
        ttk.Label(settings_frame, text="開始日期:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        self.backtest_start_entry = ttk.Entry(settings_frame, width=15)
        self.backtest_start_entry.grid(row=1, column=1, padx=5, pady=5)
        self.backtest_start_entry.insert(0, (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"))
        
        ttk.Label(settings_frame, text="結束日期:").grid(row=1, column=2, padx=5, pady=5, sticky=tk.W)
        self.backtest_end_entry = ttk.Entry(settings_frame, width=15)
        self.backtest_end_entry.grid(row=1, column=3, padx=5, pady=5)
        self.backtest_end_entry.insert(0, datetime.now().strftime("%Y-%m-%d"))
        
        # 初始資金
        ttk.Label(settings_frame, text="初始資金:").grid(row=2, column=0, padx=5, pady=5, sticky=tk.W)
        self.initial_capital_entry = ttk.Entry(settings_frame, width=15)
        self.initial_capital_entry.grid(row=2, column=1, padx=5, pady=5)
        self.initial_capital_entry.insert(0, "100000")
        
        # 策略選擇
        ttk.Label(settings_frame, text="策略:").grid(row=3, column=0, padx=5, pady=5, sticky=tk.W)
        self.backtest_strategy_var = tk.StringVar(value="移動平均線策略")
        strategy_combo = ttk.Combobox(settings_frame, textvariable=self.backtest_strategy_var, width=20)
        strategy_combo['values'] = list(STRATEGIES.keys())
        strategy_combo.grid(row=3, column=1, padx=5, pady=5)
        
        # 執行回測按鈕
        button_frame = ttk.Frame(self.backtest_frame)
        button_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(
            button_frame, 
            text="執行回測", 
            command=self.start_backtest
        ).pack(side=tk.LEFT, padx=5)
        
        # 回測結果顯示區域
        result_frame = ttk.LabelFrame(self.backtest_frame, text="回測結果", padding=10)
        result_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.backtest_result = scrolledtext.ScrolledText(result_frame, height=15, wrap=tk.WORD)
        self.backtest_result.pack(fill=tk.BOTH, expand=True)
        
    def start_data_update(self):
        """開始數據更新（在背景執行）"""
        update_type = self.update_type.get()
        start_date = self.start_date_entry.get()
        end_date = self.end_date_entry.get()
        
        # 驗證日期格式
        try:
            datetime.strptime(start_date, "%Y-%m-%d")
            datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("錯誤", "日期格式錯誤，請使用 YYYY-MM-DD 格式")
            return
        
        # 禁用按鈕
        self.update_button.config(state=tk.DISABLED)
        self.update_log.delete(1.0, tk.END)
        self.update_log.insert(tk.END, f"開始更新 {update_type} 數據...\n")
        
        # 在背景執行更新
        thread = threading.Thread(
            target=self._update_data_thread,
            args=(update_type, start_date, end_date),
            daemon=True
        )
        thread.start()
        
    def _update_data_thread(self, update_type, start_date, end_date):
        """數據更新線程"""
        try:
            if update_type == "daily":
                # 使用批量更新腳本
                from scripts.batch_update_daily_data import batch_update_daily_data
                batch_update_daily_data(start_date, end_date)
            elif update_type == "market":
                from scripts.batch_update_market_and_industry_index import batch_update_market_index
                batch_update_market_index(start_date, end_date)
            elif update_type == "industry":
                from scripts.batch_update_market_and_industry_index import batch_update_industry_index
                batch_update_industry_index(start_date, end_date)
            
            self.root.after(0, lambda: self._update_complete("更新完成！"))
        except Exception as e:
            self.root.after(0, lambda: self._update_complete(f"更新失敗: {str(e)}"))
    
    def _update_complete(self, message):
        """更新完成回調"""
        self.update_log.insert(tk.END, f"{message}\n")
        self.update_button.config(state=tk.NORMAL)
        messagebox.showinfo("完成", message)
    
    def check_data_status(self):
        """檢查數據狀態"""
        try:
            status_text = "數據狀態檢查:\n"
            status_text += "=" * 50 + "\n"
            
            # 檢查每日數據
            daily_dir = self.config.daily_price_dir
            daily_files = list(daily_dir.glob("*.csv"))
            status_text += f"每日數據文件數: {len(daily_files)}\n"
            if daily_files:
                latest = max(daily_files, key=lambda f: f.stem)
                status_text += f"最新日期: {latest.stem}\n"
            
            # 檢查大盤數據
            if self.config.market_index_file.exists():
                try:
                    df = pd.read_csv(self.config.market_index_file, encoding='utf-8-sig', on_bad_lines='skip', engine='python')
                    status_text += f"大盤數據筆數: {len(df)}\n"
                    if '日期' in df.columns:
                        # 處理日期欄位，過濾掉無效值
                        df['日期'] = df['日期'].astype(str)
                        valid_dates = df[df['日期'].notna() & (df['日期'] != 'nan') & (df['日期'] != '')]['日期']
                        if len(valid_dates) > 0:
                            status_text += f"大盤最新日期: {valid_dates.max()}\n"
                except Exception as e:
                    status_text += f"讀取大盤數據時發生錯誤: {str(e)}\n"
            
            # 檢查產業數據
            if self.config.industry_index_file.exists():
                try:
                    df = pd.read_csv(self.config.industry_index_file, encoding='utf-8-sig', on_bad_lines='skip', engine='python')
                    status_text += f"產業數據筆數: {len(df)}\n"
                    if '日期' in df.columns:
                        # 處理日期欄位，過濾掉無效值
                        df['日期'] = df['日期'].astype(str)
                        valid_dates = df[df['日期'].notna() & (df['日期'] != 'nan') & (df['日期'] != '')]['日期']
                        if len(valid_dates) > 0:
                            status_text += f"產業最新日期: {valid_dates.max()}\n"
                except Exception as e:
                    status_text += f"讀取產業數據時發生錯誤: {str(e)}\n"
            
            # 檢查整合數據
            if self.config.stock_data_file.exists():
                try:
                    df = pd.read_csv(self.config.stock_data_file, encoding='utf-8-sig', on_bad_lines='skip', engine='python', nrows=1000)
                    status_text += f"整合數據文件存在\n"
                    if '日期' in df.columns:
                        df['日期'] = df['日期'].astype(str)
                        valid_dates = df[df['日期'].notna() & (df['日期'] != 'nan') & (df['日期'] != '')]['日期']
                        if len(valid_dates) > 0:
                            status_text += f"整合數據樣本日期範圍: {valid_dates.min()} 到 {valid_dates.max()}\n"
                except Exception as e:
                    status_text += f"讀取整合數據時發生錯誤: {str(e)}\n"
            
            status_text += "\n檢查完成！"
            self.update_log.delete(1.0, tk.END)
            self.update_log.insert(tk.END, status_text)
        except Exception as e:
            import traceback
            error_msg = f"檢查數據狀態時發生錯誤: {str(e)}\n{traceback.format_exc()}"
            messagebox.showerror("錯誤", error_msg)
    
    def start_backtest(self):
        """開始回測"""
        stock_code = self.stock_code_entry.get()
        start_date = self.backtest_start_entry.get()
        end_date = self.backtest_end_entry.get()
        initial_capital = self.initial_capital_entry.get()
        strategy_name = self.backtest_strategy_var.get()
        
        # 驗證輸入
        try:
            initial_capital = float(initial_capital)
            datetime.strptime(start_date, "%Y-%m-%d")
            datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError as e:
            messagebox.showerror("錯誤", f"輸入格式錯誤: {str(e)}")
            return
        
        # 執行回測（在背景執行）
        self.backtest_result.delete(1.0, tk.END)
        self.backtest_result.insert(tk.END, f"開始回測 {stock_code}...\n")
        
        thread = threading.Thread(
            target=self._backtest_thread,
            args=(stock_code, start_date, end_date, initial_capital, strategy_name),
            daemon=True
        )
        thread.start()
    
    def _backtest_thread(self, stock_code, start_date, end_date, initial_capital, strategy_name):
        """回測線程"""
        try:
            self.root.after(0, lambda: self.backtest_result.insert(tk.END, f"開始回測 {stock_code}...\n"))
            
            # 加載股票數據
            # 從 stock_data_whole.csv 中篩選該股票的數據
            stock_data_file = self.config.stock_data_file
            if not stock_data_file.exists():
                self.root.after(0, lambda: self.backtest_result.insert(tk.END, f"錯誤: 找不到股票數據文件\n"))
                return
            
            # 讀取數據
            df = pd.read_csv(stock_data_file, encoding='utf-8-sig', on_bad_lines='skip', engine='python')
            
            # 篩選股票代號和日期範圍
            if '股票代號' in df.columns:
                df = df[df['股票代號'] == stock_code]
            elif '代號' in df.columns:
                df = df[df['代號'] == stock_code]
            else:
                self.root.after(0, lambda: self.backtest_result.insert(tk.END, f"錯誤: 找不到股票代號欄位\n"))
                return
            
            if '日期' in df.columns:
                df['日期'] = pd.to_datetime(df['日期'], errors='coerce')
                df = df[(df['日期'] >= start_date) & (df['日期'] <= end_date)]
                df = df.set_index('日期').sort_index()
            else:
                self.root.after(0, lambda: self.backtest_result.insert(tk.END, f"錯誤: 找不到日期欄位\n"))
                return
            
            if len(df) == 0:
                self.root.after(0, lambda: self.backtest_result.insert(tk.END, f"錯誤: 沒有找到符合條件的數據\n"))
                return
            
            # 加載技術指標數據（如果存在）
            tech_file = self.config.get_technical_file(stock_code)
            if tech_file.exists():
                try:
                    tech_df = pd.read_csv(tech_file, encoding='utf-8-sig', on_bad_lines='skip', engine='python')
                    if '日期' in tech_df.columns:
                        tech_df['日期'] = pd.to_datetime(tech_df['日期'], errors='coerce')
                        tech_df = tech_df.set_index('日期').sort_index()
                        # 合併技術指標數據
                        df = df.join(tech_df, how='left')
                except:
                    pass
            
            # 獲取策略函數
            if strategy_name not in STRATEGIES:
                self.root.after(0, lambda: self.backtest_result.insert(tk.END, f"錯誤: 找不到策略 {strategy_name}\n"))
                return
            
            strategy_func = STRATEGIES[strategy_name]["func"]
            
            # 執行回測
            tester = StrategyTester(initial_capital=float(initial_capital))
            backtest_results = tester.run_backtest(df, strategy_func)
            
            # 計算績效指標
            portfolio_returns = tester.portfolio_value['Total_Value'].pct_change().dropna()
            close_col = tester._get_column_name(df, 'Close')
            if close_col:
                benchmark_returns = df[close_col].pct_change().dropna()
                analyzer = PerformanceAnalyzer(portfolio_returns, benchmark_returns)
                performance_report = analyzer.generate_performance_report()
            else:
                analyzer = PerformanceAnalyzer(portfolio_returns)
                performance_report = analyzer.generate_performance_report()
            
            # 顯示結果
            result_text = f"\n{'='*50}\n"
            result_text += f"回測結果\n"
            result_text += f"{'='*50}\n"
            result_text += f"股票代號: {stock_code}\n"
            result_text += f"日期範圍: {start_date} 到 {end_date}\n"
            result_text += f"初始資金: {initial_capital:,.0f}\n"
            result_text += f"最終資金: {tester.portfolio_value['Total_Value'].iloc[-1]:,.2f}\n"
            result_text += f"總收益率: {(tester.portfolio_value['Total_Value'].iloc[-1] / float(initial_capital) - 1) * 100:.2f}%\n"
            result_text += f"策略: {strategy_name}\n"
            result_text += f"交易次數: {len(tester.trades)}\n"
            result_text += f"\n績效指標:\n"
            for key, value in performance_report.items():
                if isinstance(value, (int, float)):
                    result_text += f"  {key}: {value:.4f}\n"
                else:
                    result_text += f"  {key}: {value}\n"
            
            self.root.after(0, lambda: self.backtest_result.insert(tk.END, result_text))
            
        except Exception as e:
            import traceback
            error_msg = f"回測失敗: {str(e)}\n{traceback.format_exc()}\n"
            self.root.after(0, lambda: self.backtest_result.insert(tk.END, error_msg))

def main():
    """主函數"""
    root = tk.Tk()
    app = TradingAnalysisApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()

