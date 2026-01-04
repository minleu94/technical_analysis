"""
大盤指數視圖
顯示市場狀態檢測結果
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QTextEdit, QGroupBox, QSplitter,
    QScrollArea, QFrame
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from typing import Optional, Dict, Any

from app_module.regime_service import RegimeService
from app_module.dtos import RegimeResultDTO
from ui_qt.widgets.info_button import InfoButton


# ============================================================================
# 顏色常數定義（集中管理）- 深色主題優化
# ============================================================================
# 背景色（深色主題）
COLOR_BG_DARK = "#1e1e1e"        # 深色背景（主畫面）
COLOR_BG_DARKER = "#121212"      # 更深背景（可選）

# 市場狀態分類色（Tag Color）- 僅用於狀態名稱文字
COLOR_TAG_TREND = "#2e7d32"      # 深綠（趨勢追蹤）
COLOR_TAG_REVERSION = "#f57c00"  # 橙（均值回歸）
COLOR_TAG_BREAKOUT = "#1976d2"   # 藍（突破準備）
COLOR_TAG_DEFAULT = "#888888"    # 淺灰（無法判斷，深色主題下需更亮）

# 信心度顏色（深色主題下使用接近白色，確保可讀性）
COLOR_CONF_HIGH = "#ffffff"      # 白色（高信心度，加粗顯示）
COLOR_CONF_MEDIUM = "#e0e0e0"    # 接近白色（中信心度）
COLOR_CONF_LOW = "#cccccc"        # 淺灰（低信心度）

# 文字顏色（深色主題）
COLOR_TEXT_PRIMARY = "#ffffff"   # 主要文字（白色）
COLOR_TEXT_SECONDARY = "#cccccc" # 次要文字（淺灰）
COLOR_TEXT_TERTIARY = "#999999"  # 第三級文字（中灰）
COLOR_TEXT_TITLE = "#bbbbbb"     # 標題文字（淺灰）

# 分隔線顏色（深色主題）
COLOR_BORDER = "#444444"         # 分隔線（深灰）


class MarketRegimeView(QWidget):
    """大盤指數視圖"""
    
    def __init__(self, regime_service: RegimeService, parent=None):
        """初始化大盤指數視圖
        
        Args:
            regime_service: 市場狀態服務實例
            parent: 父窗口
        """
        super().__init__(parent)
        self.regime_service = regime_service
        
        self._setup_ui()
        # 不自動計算，等待用戶點擊「檢測市場狀態」按鈕
    
    def _setup_ui(self):
        """設置 UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)  # 減少間距
        main_layout.setContentsMargins(10, 10, 10, 10)  # 減少邊距
        
        # 標題列（標題 + InfoButton）
        title_layout = QHBoxLayout()
        title = QLabel("大盤指數")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        title_layout.addWidget(title)
        title_layout.addStretch()
        info_btn = InfoButton("market_regime", self)
        title_layout.addWidget(info_btn)
        main_layout.addLayout(title_layout)
        
        # 檢測按鈕
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        detect_btn = QPushButton("檢測市場狀態")
        detect_btn.setMinimumHeight(35)  # 稍微減小按鈕高度
        detect_btn.clicked.connect(self._detect_regime)
        button_layout.addWidget(detect_btn)
        
        button_layout.addStretch()
        main_layout.addLayout(button_layout)
        
        # 使用垂直分割器來分割市場狀態和策略建議（50/50）
        splitter = QSplitter(Qt.Vertical)
        
        # 上半部分：市場狀態顯示（三層資訊架構）
        status_group = QGroupBox("市場狀態")
        status_group.setStyleSheet(f"""
            QGroupBox {{
                background-color: {COLOR_BG_DARK};
                border: 1px solid {COLOR_BORDER};
                border-radius: 5px;
                margin-top: 8px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                color: {COLOR_TEXT_TITLE};
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }}
        """)
        status_layout = QVBoxLayout()
        status_layout.setContentsMargins(16, 12, 16, 14)  # 縮小 top margin，減少留白
        status_layout.setSpacing(15)
        
        # Layer 1 + Layer 2: 並排顯示（水平配置，60:40 比例）
        layer1_2_container = QWidget()
        layer1_2_layout = QHBoxLayout()
        layer1_2_layout.setContentsMargins(0, 0, 0, 0)
        layer1_2_layout.setSpacing(25)  # 增加間距
        
        # Layer 1: 市場結論層（Decision Layer）- 左側 60%
        layer1_widget = QWidget()
        layer1_widget.setStyleSheet(f"background-color: {COLOR_BG_DARK};")
        layer1_layout = QVBoxLayout()
        layer1_layout.setContentsMargins(0, 0, 0, 0)
        layer1_layout.setSpacing(8)  # 減少間距，讓信心度緊貼市場狀態
        
        # 移除"市場結論"標題，或降級為極小的標籤（視覺上幾乎不可見）
        # 市場狀態名稱是唯一視覺錨點
        self.layer1_title = QLabel("")  # 隱藏標題，不搶視覺焦點
        layer1_layout.addWidget(self.layer1_title)
        self.layer1_title.hide()  # 完全隱藏
        
        # 市場狀態（唯一視覺錨點 - 最大字級、粗體、分類色）
        self.layer1_status = QLabel("尚未檢測")
        status_font = QFont()
        status_font.setPointSize(24)  # 增大字級，成為唯一主角
        status_font.setBold(True)
        self.layer1_status.setFont(status_font)
        self.layer1_status.setStyleSheet(f"color: {COLOR_TAG_DEFAULT}; padding: 0; margin: 0;")
        layer1_layout.addWidget(self.layer1_status)
        
        # 信心度（緊貼市場狀態，作為修飾語，不獨立成段）
        self.layer1_confidence = QLabel("")
        self.layer1_confidence.setTextFormat(Qt.RichText)  # 支持 HTML 格式
        confidence_font = QFont()
        confidence_font.setPointSize(11)  # 比市場狀態小，但清晰可見
        confidence_font.setBold(False)  # 不加粗，降低視覺權重
        self.layer1_confidence.setFont(confidence_font)
        self.layer1_confidence.setStyleSheet("padding: 2px 0 0 0; margin: 0;")  # 緊貼上方
        layer1_layout.addWidget(self.layer1_confidence)
        
        # 簡短描述（視覺降級，作為輔助資訊）
        self.layer1_description = QLabel("")
        self.layer1_description.setWordWrap(True)
        desc_font = QFont()
        desc_font.setPointSize(10)
        self.layer1_description.setFont(desc_font)
        self.layer1_description.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; padding-top: 12px; line-height: 1.4;")  # 增加與上方間距
        layer1_layout.addWidget(self.layer1_description)
        
        layer1_layout.addStretch()
        layer1_widget.setLayout(layer1_layout)
        layer1_2_layout.addWidget(layer1_widget, 3)  # stretch factor = 3 (60%)
        
        # Layer 2: 判斷摘要層（Explanation Summary）- 右側 40%
        layer2_widget = QWidget()
        layer2_widget.setStyleSheet(f"background-color: {COLOR_BG_DARK};")
        layer2_layout = QVBoxLayout()
        layer2_layout.setContentsMargins(0, 0, 0, 0)
        layer2_layout.setSpacing(8)  # 減少間距，視覺降級
        
        # 標題：判斷摘要（視覺降級，存在感降低）
        layer2_title = QLabel("判斷摘要")
        layer2_title_font = QFont()
        layer2_title_font.setPointSize(9)  # 比市場狀態標題更小
        layer2_title_font.setBold(False)  # 不加粗
        layer2_title.setFont(layer2_title_font)
        layer2_title.setStyleSheet(f"color: {COLOR_TEXT_TERTIARY}; padding-bottom: 8px; border-bottom: 1px solid {COLOR_BORDER};")
        layer2_layout.addWidget(layer2_title)
        
        # 判斷摘要內容（字級比市場結論小，行距略小）
        self.layer2_label = QLabel("")
        self.layer2_label.setWordWrap(True)
        self.layer2_label.setAlignment(Qt.AlignTop)
        self.layer2_label.setTextFormat(Qt.RichText)  # 支持 HTML 格式
        summary_font = QFont()
        summary_font.setPointSize(9)  # 比市場結論小一級
        self.layer2_label.setFont(summary_font)
        self.layer2_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; line-height: 1.4; padding: 0;")  # 減少 padding
        self.layer2_label.setText("點擊「檢測市場狀態」按鈕查看判斷摘要")
        layer2_layout.addWidget(self.layer2_label)
        
        layer2_layout.addStretch()
        layer2_widget.setLayout(layer2_layout)
        layer1_2_layout.addWidget(layer2_widget, 2)  # stretch factor = 2 (40%)
        
        layer1_2_container.setLayout(layer1_2_layout)
        status_layout.addWidget(layer1_2_container)
        
        # Layer 3: 技術細節層（Advanced / Research Layer）- 可折疊
        layer3_group = QGroupBox("技術細節（收合）")  # 初始狀態顯示「收合」
        layer3_group.setCheckable(True)
        layer3_group.setChecked(False)  # 預設收合
        layer3_group.toggled.connect(self._on_layer3_toggled)
        layer3_group.setStyleSheet(f"""
            QGroupBox {{
                background-color: {COLOR_BG_DARK};
                border: 1px solid {COLOR_BORDER};
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 20px;
            }}
            QGroupBox::title {{
                color: {COLOR_TEXT_TITLE};
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }}
            QGroupBox::indicator {{
                width: 16px;
                height: 16px;
            }}
            QGroupBox::indicator:unchecked {{
                border: 2px solid {COLOR_TEXT_SECONDARY};
                background-color: {COLOR_BG_DARK};
                border-radius: 3px;
            }}
            QGroupBox::indicator:checked {{
                border: 2px solid {COLOR_TAG_TREND};
                background-color: {COLOR_TAG_TREND};
                border-radius: 3px;
            }}
        """)
        layer3_layout = QVBoxLayout()
        layer3_layout.setContentsMargins(15, 25, 15, 15)  # 增加 top margin，避免標題貼邊
        layer3_layout.setSpacing(8)
        
        # 不使用 ScrollArea，直接使用 Widget（內容不多，可以並排顯示）
        self.layer3_content = QWidget()
        # 改用 QHBoxLayout 來並排顯示 GroupBox
        self.layer3_layout = QHBoxLayout()
        self.layer3_layout.setContentsMargins(0, 0, 0, 0)
        self.layer3_layout.setSpacing(10)  # GroupBox 之間的間距
        self.layer3_content.setLayout(self.layer3_layout)
        
        layer3_layout.addWidget(self.layer3_content)
        layer3_group.setLayout(layer3_layout)
        status_layout.addWidget(layer3_group)
        
        # 保存 layer3_group 的引用，以便控制顯示/隱藏
        self.layer3_group = layer3_group
        # 初始狀態：收合
        self.layer3_content.hide()
        
        status_group.setLayout(status_layout)
        splitter.addWidget(status_group)
        
        # 下半部分：策略建議（深色主題，移除白底）
        strategy_group = QGroupBox("策略建議")
        strategy_group.setStyleSheet(f"""
            QGroupBox {{
                background-color: {COLOR_BG_DARK};
                border: 1px solid {COLOR_BORDER};
                border-radius: 5px;
                margin-top: 8px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                color: {COLOR_TEXT_TITLE};
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }}
        """)
        strategy_layout = QVBoxLayout()
        strategy_layout.setContentsMargins(16, 12, 16, 14)  # 縮小 top margin，減少留白
        strategy_layout.setSpacing(12)
        self.strategy_text = QTextEdit()
        self.strategy_text.setReadOnly(True)
        self.strategy_text.setPlaceholderText("根據市場狀態自動顯示策略建議")
        # 深色主題樣式：深色背景，淺色文字
        strategy_font = QFont()
        strategy_font.setPointSize(10)
        self.strategy_text.setFont(strategy_font)
        self.strategy_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLOR_BG_DARK};
                color: {COLOR_TEXT_SECONDARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: 3px;
                padding: 10px;
                line-height: 1.6;
            }}
        """)
        strategy_layout.addWidget(self.strategy_text)
        strategy_group.setLayout(strategy_layout)
        splitter.addWidget(strategy_group)
        
        # 設置分割器比例為 50/50
        splitter.setSizes([1, 1])  # 使用相對比例，會自動適應視窗大小
        
        main_layout.addWidget(splitter, 1)  # 設置 stretch factor 為 1，讓分割器可以隨視窗縮放
    
    def _detect_regime(self):
        """檢測市場狀態"""
        try:
            regime_result: RegimeResultDTO = self.regime_service.detect_regime()
            
            # 更新三層資訊
            self._update_layer1(regime_result)
            self._update_layer2(regime_result)
            self._update_layer3(regime_result)
            
            # 顯示策略建議（使用 HTML 格式以支持標題高亮，深色主題）
            strategy_config = self.regime_service.get_strategy_config(regime_result.regime)
            if strategy_config:
                # 使用 HTML 格式，標題使用更亮的顏色（移除「當前市場狀態」，因為已在上方顯示）
                strategy_html = f"<div style='color: {COLOR_TEXT_SECONDARY}; line-height: 1.6;'>"
                strategy_html += f"<span style='color: {COLOR_TEXT_PRIMARY}; font-weight: bold;'>建議策略配置：</span><br/>"
                
                # 技術指標
                technical = strategy_config.get('technical', {})
                if technical.get('momentum', {}).get('enabled'):
                    strategy_html += "  • 動量指標：RSI、MACD<br/>"
                if technical.get('trend', {}).get('enabled'):
                    strategy_html += "  • 趨勢指標：ADX、移動平均線<br/>"
                
                # 圖形模式
                patterns = strategy_config.get('patterns', {}).get('selected', [])
                if patterns:
                    strategy_html += f"  • 圖形模式：{', '.join(patterns)}<br/>"
                
                # 信號組合
                signals = strategy_config.get('signals', {})
                volume_conditions = signals.get('volume_conditions', [])
                if volume_conditions:
                    strategy_html += f"  • 成交量條件：{', '.join(volume_conditions)}<br/>"
                
                strategy_html += "</div>"
                self.strategy_text.setHtml(strategy_html)
            else:
                self.strategy_text.setHtml(f"<div style='color: {COLOR_TEXT_SECONDARY};'>無法獲取策略建議</div>")
            
        except Exception as e:
            # 錯誤狀態：使用預設灰色，深色主題下確保可讀性
            self.layer1_status.setText("檢測失敗")
            self.layer1_status.setStyleSheet(f"color: {COLOR_TAG_DEFAULT}; padding: 5px 0;")
            self.layer1_confidence.setText("")
            self.layer1_description.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; padding-top: 5px; line-height: 1.4;")
            self.layer1_description.setText(f"錯誤：{str(e)}")
            self.layer2_label.setText("")
            self._clear_layer3()
            self.strategy_text.setPlainText("")
    
    def _update_layer1(self, regime_result: RegimeResultDTO):
        """更新 Layer 1：市場結論層（禁止技術指標名詞）
        
        顏色語意規則：
        - 市場狀態：使用分類色（Tag Color），僅用於狀態名稱文字
        - 信心度：使用中性色（Neutral Color），不使用情緒色（紅綠黃）
        """
        # 市場狀態（分類色 - 僅用於狀態名稱文字）
        regime = regime_result.regime
        regime_name = regime_result.regime_name_cn
        self.layer1_status.setText(regime_name)
        
        # 根據 regime 類型設置分類色（僅用於狀態名稱）
        if regime == 'Trend':
            status_color = COLOR_TAG_TREND
        elif regime == 'Breakout':
            status_color = COLOR_TAG_BREAKOUT
        elif regime == 'Reversion':
            status_color = COLOR_TAG_REVERSION
        else:
            status_color = COLOR_TAG_DEFAULT
        
        # 分類色僅套用在狀態名稱文字
        self.layer1_status.setStyleSheet(f"color: {status_color}; padding: 5px 0;")
        
        # 信心度（緊貼市場狀態，作為修飾語，視覺上服從市場狀態）
        confidence_pct = regime_result.confidence * 100
        if confidence_pct >= 80:
            # 高信心度：接近白色（但字重降低，不搶市場狀態的焦點）
            conf_color = COLOR_CONF_HIGH
            conf_level = "高"
        elif confidence_pct >= 60:
            # 中信心度：接近白色
            conf_color = COLOR_CONF_MEDIUM
            conf_level = "中"
        else:
            # 低信心度：淺灰
            conf_color = COLOR_CONF_LOW
            conf_level = "低"
        
        # 信心度顯示：緊貼市場狀態，作為修飾語存在
        # 格式：(信心度 82% 高) - 視覺上服從市場狀態名稱
        confidence_text = (
            f"<span style='color: {conf_color};'>"
            f"（信心度 {confidence_pct:.0f}% {conf_level}）</span>"
        )
        self.layer1_confidence.setText(confidence_text)
        
        # 簡短描述（根據 regime 和 confidence 生成，不使用技術指標名詞）
        # 描述文字使用標準文字顏色，不使用分類色或情緒色
        description = self._generate_layer1_description(regime_result)
        self.layer1_description.setText(description)
    
    def _generate_layer1_description(self, regime_result: RegimeResultDTO) -> str:
        """生成 Layer 1 的簡短描述（不使用技術指標名詞）"""
        regime = regime_result.regime
        confidence = regime_result.confidence
        details = regime_result.details
        
        if regime == 'Trend':
            if confidence >= 0.8:
                return "市場呈現明確的趨勢方向，動能強勁，適合順勢操作。"
            elif confidence >= 0.65:
                return "市場具備趨勢結構，但動能尚未完全展開，需謹慎評估。"
            else:
                return "市場有趨勢跡象，但強度不足，建議等待更明確的信號。"
        
        elif regime == 'Breakout':
            if confidence >= 0.7:
                return "市場波動率壓縮，價格在區間內整理，可能醞釀突破。"
            else:
                return "市場處於整理階段，但突破條件尚未完全成熟。"
        
        elif regime == 'Reversion':
            if confidence >= 0.7:
                return "市場處於盤整狀態，價格偏離後可能回歸均值。"
            else:
                return "市場缺乏明確方向，呈現震盪整理格局。"
        
        else:
            return "市場狀態不明確，建議保持觀望。"
    
    def _update_layer2(self, regime_result: RegimeResultDTO):
        """更新 Layer 2：判斷摘要層（人類可讀的語句，隱約對應指標）"""
        summary_lines = []
        regime = regime_result.regime
        details = regime_result.details
        
        if regime == 'Trend':
            # 價格結構
            if details.get('close_above_ma60', False):
                summary_lines.append("• 價格位於中長期均線之上 → 偏多結構")
            else:
                summary_lines.append("• 價格位於中長期均線之下 → 偏空結構")
            
            # 趨勢方向
            if details.get('ma20_slope_positive', False):
                summary_lines.append("• 短期均線維持上升 → 趨勢方向成立")
            else:
                summary_lines.append("• 短期均線走平或下降 → 趨勢方向不明確")
            
            # 動能強弱
            structure_score = details.get('structure_score', 0)
            strength_score = details.get('strength_score', 0)
            if structure_score >= 0.67 and strength_score >= 0.7:
                summary_lines.append("• 動能強勁且結構完整 → 強趨勢")
            elif structure_score >= 0.67:
                summary_lines.append("• 結構完整但動能未顯著擴張 → 中等趨勢")
            else:
                summary_lines.append("• 動能存在但結構不完整 → 弱趨勢")
        
        elif regime == 'Breakout':
            if details.get('bandwidth_compressed', False):
                summary_lines.append("• 波動率明顯壓縮 → 醞釀突破")
            else:
                summary_lines.append("• 波動率未明顯壓縮 → 突破條件不足")
            
            if details.get('price_in_range', False):
                summary_lines.append("• 價格在區間內整理 → 等待方向選擇")
            else:
                summary_lines.append("• 價格偏離區間 → 可能已開始突破")
            
            if details.get('adx_low', False):
                summary_lines.append("• 趨勢強度較低 → 適合突破策略")
            else:
                summary_lines.append("• 趨勢強度較高 → 可能已形成趨勢")
        
        elif regime == 'Reversion':
            if details.get('price_in_range', False):
                summary_lines.append("• 價格在均線區間內 → 盤整結構")
            else:
                summary_lines.append("• 價格偏離均線區間 → 可能回歸")
            
            if details.get('adx_low', False):
                summary_lines.append("• 趨勢強度較低 → 適合均值回歸策略")
            else:
                summary_lines.append("• 趨勢強度較高 → 回歸條件不足")
            
            if details.get('rsi_oversold', False) or details.get('rsi_overbought', False):
                summary_lines.append("• 動能指標顯示極端值 → 可能回歸")
            else:
                summary_lines.append("• 動能指標未達極端 → 回歸動力不足")
        
        if not summary_lines:
            summary_lines.append("• 判斷依據不足，建議參考技術細節")
        
        # 使用 QLabel 顯示（改用 HTML 格式以支持更好的排版）
        summary_html = "<div style='line-height: 1.6;'>" + "<br/>".join(summary_lines) + "</div>"
        self.layer2_label.setText(summary_html)
    
    def _update_layer3(self, regime_result: RegimeResultDTO):
        """更新 Layer 3：技術細節層（所有指標與數值）"""
        # 清除舊內容
        self._clear_layer3()
        
        details = regime_result.details
        
        # 指標名稱映射（統一顯示名稱，避免重複）
        indicator_map = {
            'close': '收盤價',
            'ma20': '20日均線',
            'ma60': '60日均線',
            'ma20_slope': 'MA20斜率',
            'adx': 'ADX',
            'adx_value': 'ADX數值',
            'adx_contribution': 'ADX貢獻度',
            'plus_di': '+DI',
            'minus_di': '-DI',
            'atr': 'ATR',
            'trend_distance': '趨勢距離(ATR標準化)',
            'distance_contribution': '距離貢獻度',
            'structure_score': '結構分',
            'strength_score': '強度分',
            'trend_confidence': '趨勢信心度',
            'bb_bandwidth': '布林帶寬度',
            'rsi': 'RSI',
            'reversion_score': '回歸分數',
            'breakout_score': '突破分數',
        }
        
        # 條件名稱映射
        condition_map = {
            'close_above_ma60': '價格高於60日均線',
            'ma20_slope_positive': 'MA20斜率為正',
            'plus_di_above_minus_di': '+DI高於-DI',
            'bandwidth_compressed': '波動率壓縮',
            'price_in_range': '價格在區間內',
            'adx_low': 'ADX較低',
            'volume_expanding': '成交量放大',
            'rsi_oversold': 'RSI超賣',
            'rsi_overbought': 'RSI超買',
            'price_deviation': '價格偏離',
        }
        
        # GroupBox 通用樣式（深色主題）
        groupbox_style = f"""
            QGroupBox {{
                background-color: {COLOR_BG_DARK};
                border: 1px solid {COLOR_BORDER};
                border-radius: 3px;
                margin-top: 8px;
                padding-top: 12px;
            }}
            QGroupBox::title {{
                color: {COLOR_TEXT_TITLE};
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 5px;
            }}
        """
        
        # 分類顯示（並排顯示，使用 stretch factor 讓寬度平均分配）
        # 1. 價格與均線
        price_group = QGroupBox("價格與均線")
        price_group.setStyleSheet(groupbox_style)
        price_group.setMinimumWidth(150)  # 設置最小寬度
        price_layout = QVBoxLayout()
        price_layout.setContentsMargins(8, 8, 8, 8)
        for key in ['close', 'ma20', 'ma60', 'ma20_slope']:
            if key in details:
                label = QLabel(f"{indicator_map.get(key, key)}: {self._format_value(details[key])}")
                label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
                price_layout.addWidget(label)
        price_group.setLayout(price_layout)
        self.layer3_layout.addWidget(price_group, 1)  # stretch factor = 1
        
        # 2. 趨勢指標
        trend_group = QGroupBox("趨勢指標")
        trend_group.setStyleSheet(groupbox_style)
        trend_group.setMinimumWidth(150)
        trend_layout = QVBoxLayout()
        trend_layout.setContentsMargins(8, 8, 8, 8)
        for key in ['adx', 'adx_value', 'adx_contribution', 'plus_di', 'minus_di', 'atr']:
            if key in details:
                label = QLabel(f"{indicator_map.get(key, key)}: {self._format_value(details[key])}")
                label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
                trend_layout.addWidget(label)
        trend_group.setLayout(trend_layout)
        self.layer3_layout.addWidget(trend_group, 1)
        
        # 3. 評分與貢獻
        score_group = QGroupBox("評分與貢獻")
        score_group.setStyleSheet(groupbox_style)
        score_group.setMinimumWidth(150)
        score_layout = QVBoxLayout()
        score_layout.setContentsMargins(8, 8, 8, 8)
        for key in ['structure_score', 'strength_score', 'trend_confidence', 
                    'trend_distance', 'distance_contribution', 'reversion_score', 'breakout_score']:
            if key in details:
                label = QLabel(f"{indicator_map.get(key, key)}: {self._format_value(details[key])}")
                label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
                score_layout.addWidget(label)
        score_group.setLayout(score_layout)
        self.layer3_layout.addWidget(score_group, 1)
        
        # 4. 其他指標
        other_group = QGroupBox("其他指標")
        other_group.setStyleSheet(groupbox_style)
        other_group.setMinimumWidth(150)
        other_layout = QVBoxLayout()
        other_layout.setContentsMargins(8, 8, 8, 8)
        has_other_indicators = False
        for key in ['bb_bandwidth', 'rsi']:
            if key in details and details[key] is not None:
                label = QLabel(f"{indicator_map.get(key, key)}: {self._format_value(details[key])}")
                label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
                other_layout.addWidget(label)
                has_other_indicators = True
        
        # 如果沒有其他指標，顯示提示訊息
        if not has_other_indicators:
            hint_label = QLabel("此市場狀態下無其他指標")
            hint_label.setStyleSheet(f"color: {COLOR_TEXT_TERTIARY}; font-style: italic;")
            other_layout.addWidget(hint_label)
        
        other_group.setLayout(other_layout)
        self.layer3_layout.addWidget(other_group, 1)
        
        # 5. 判斷條件
        condition_group = QGroupBox("判斷條件")
        condition_group.setStyleSheet(groupbox_style)
        condition_group.setMinimumWidth(180)  # 判斷條件文字較長，設置稍大的最小寬度
        condition_layout = QVBoxLayout()
        condition_layout.setContentsMargins(8, 8, 8, 8)
        has_conditions = False
        for key, value in details.items():
            if isinstance(value, bool) and key in condition_map:
                status = "✓" if value else "✗"
                status_color = COLOR_CONF_HIGH if value else COLOR_TEXT_TERTIARY
                label = QLabel(f"<span style='color: {status_color};'>{status}</span> {condition_map.get(key, key)}")
                label.setTextFormat(Qt.RichText)
                label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
                condition_layout.addWidget(label)
                has_conditions = True
        
        # 如果沒有判斷條件，顯示提示訊息
        if not has_conditions:
            hint_label = QLabel("此市場狀態下無判斷條件")
            hint_label.setStyleSheet(f"color: {COLOR_TEXT_TERTIARY}; font-style: italic;")
            condition_layout.addWidget(hint_label)
        
        condition_group.setLayout(condition_layout)
        self.layer3_layout.addWidget(condition_group, 1)
        
        # 6. 原始資料（未映射的欄位）
        raw_keys = [k for k in details.keys() 
                   if k not in indicator_map and k not in condition_map 
                   and k not in ['error', 'default']]
        if raw_keys:
            raw_group = QGroupBox("原始資料")
            raw_group.setStyleSheet(groupbox_style)
            raw_group.setMinimumWidth(150)
            raw_layout = QVBoxLayout()
            raw_layout.setContentsMargins(8, 8, 8, 8)
            for key in raw_keys:
                label = QLabel(f"{key}: {self._format_value(details[key])}")
                label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
                raw_layout.addWidget(label)
            raw_group.setLayout(raw_layout)
            self.layer3_layout.addWidget(raw_group, 1)
        
        # 添加 stretch，讓 GroupBox 靠左對齊
        self.layer3_layout.addStretch()
    
    def _format_value(self, value: Any) -> str:
        """格式化數值顯示"""
        if isinstance(value, bool):
            return "是" if value else "否"
        elif isinstance(value, float):
            if abs(value) < 0.01:
                return f"{value:.4f}"
            elif abs(value) < 1:
                return f"{value:.3f}"
            else:
                return f"{value:.2f}"
        elif value is None:
            return "N/A"
        else:
            return str(value)
    
    def _clear_layer3(self):
        """清除 Layer 3 的內容"""
        while self.layer3_layout.count():
            item = self.layer3_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
    
    def _on_layer3_toggled(self, checked: bool):
        """Layer 3 折疊/展開切換"""
        # 更新標題文字，讓狀態一目了然
        if checked:
            self.layer3_group.setTitle("技術細節（已展開）")
        else:
            self.layer3_group.setTitle("技術細節（收合）")
        self._update_layer3_visibility()
    
    def _update_layer3_visibility(self):
        """更新 Layer 3 的可見性"""
        if self.layer3_group.isChecked():
            self.layer3_content.show()
        else:
            self.layer3_content.hide()

