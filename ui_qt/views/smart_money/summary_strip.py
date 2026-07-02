"""
Summary Strip
精緻的玻璃擬態卡片式狀態面板，位於 Scanner 上方。
已中文化標題與狀態呈現，並已調大字體以提升易讀性。
"""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor
from app_module.dtos.flow_signal_dtos import SmartMoneySummaryDTO

class SummaryStrip(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 設置透明背景，讓卡片疊加在主佈局上
        self.setAutoFillBackground(False)
        self.setFixedHeight(75) # 調高至 75px 以容納卡片與內縮 padding
        
        # 套用卡片全域樣式 (玻璃擬態微光邊框與懸停亮化)
        self.setStyleSheet("""
            QFrame#CardFrame {
                background-color: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(30, 41, 59, 0.45), 
                    stop:1 rgba(15, 23, 42, 0.6)
                );
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 10px;
            }
            QFrame#CardFrame:hover {
                background-color: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(51, 65, 85, 0.55), 
                    stop:1 rgba(30, 41, 59, 0.65)
                );
                border: 1px solid rgba(255, 255, 255, 0.16);
            }
        """)
        
        self._setup_ui()
        
    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 8, 15, 8)
        layout.setSpacing(15)
        
        # 建立卡片元件 (中文化標題且精簡字詞)
        self.lbl_regime = self._create_card("", "市場趨勢")
        self.lbl_heat = self._create_card("🔥", "熱度")
        self.lbl_bull_bear = self._create_card("⚔️", "多空個股數")
        self.lbl_abnormal = self._create_card("🚨", "異常警示")
        
        layout.addWidget(self.lbl_regime['card'])
        layout.addWidget(self.lbl_heat['card'])
        layout.addWidget(self.lbl_bull_bear['card'])
        layout.addWidget(self.lbl_abnormal['card'])
        
        layout.addStretch()
        
    def _create_card(self, icon: str, title: str) -> dict:
        card = QFrame()
        card.setObjectName("CardFrame")
        
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(15, 10, 15, 10)
        card_layout.setSpacing(12)
        
        # 左側微型圖示
        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet("font-size: 18px;")
        icon_lbl.setAlignment(Qt.AlignCenter)
        
        # 右側文字排版 (標題在上，數值在下)
        text_container = QWidget()
        text_layout = QVBoxLayout(text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        
        title_lbl = QLabel(title)
        # 字體大小由 9px 放大至 11px
        title_lbl.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: bold; font-family: 'Microsoft JhengHei', 'Segoe UI', Arial;")
        
        val_lbl = QLabel("--")
        # 數值字體大小由 13px 放大至 15px
        val_lbl.setStyleSheet("color: #f8fafc; font-size: 15px; font-weight: bold; font-family: Consolas, Monaco;")
        
        text_layout.addWidget(title_lbl)
        text_layout.addWidget(val_lbl)
        
        card_layout.addWidget(icon_lbl)
        card_layout.addWidget(text_container)
        
        card.setFixedHeight(56)
        
        return {'card': card, 'val_lbl': val_lbl}

    def update_summary(self, summary: SmartMoneySummaryDTO):
        # 1. Regime (多空多語對照翻譯)
        regime_text = summary.market_regime
        if "Bullish" in regime_text:
            display_text = "偏多流向 (Bullish)"
            style = "color: #10b981; font-size: 15px; font-weight: bold; font-family: 'Microsoft JhengHei', Consolas;"
        elif "Bearish" in regime_text:
            display_text = "偏空流向 (Bearish)"
            style = "color: #f43f5e; font-size: 15px; font-weight: bold; font-family: 'Microsoft JhengHei', Consolas;"
        else:
            display_text = "中性整理 (Neutral)"
            style = "color: #f8fafc; font-size: 15px; font-weight: bold; font-family: 'Microsoft JhengHei', Consolas;"
            
        self.lbl_regime['val_lbl'].setText(display_text)
        self.lbl_regime['val_lbl'].setStyleSheet(style)
            
        # 2. Market Heat
        self.lbl_heat['val_lbl'].setText(f"{summary.market_heat_score:.1f}%")
        if summary.market_heat_score >= 70:
            self.lbl_heat['val_lbl'].setStyleSheet("color: #fb923c; font-size: 15px; font-weight: bold; font-family: Consolas;")
        elif summary.market_heat_score <= 30:
            self.lbl_heat['val_lbl'].setStyleSheet("color: #60a5fa; font-size: 15px; font-weight: bold; font-family: Consolas;")
        else:
            self.lbl_heat['val_lbl'].setStyleSheet("color: #f8fafc; font-size: 15px; font-weight: bold; font-family: Consolas;")
        
        # 3. Bull / Bear
        self.lbl_bull_bear['val_lbl'].setText(f"{summary.bullish_stock_count} 家偏多 🐂 / {summary.bearish_stock_count} 家偏空 🐻")
        # 字體放大
        self.lbl_bull_bear['val_lbl'].setStyleSheet("color: #f8fafc; font-size: 13px; font-weight: bold; font-family: 'Microsoft JhengHei', Consolas;")
        
        # 4. Abnormal (主力異常警示)
        self.lbl_abnormal['val_lbl'].setText(f"{summary.abnormal_signal_count} 個")
        if summary.abnormal_signal_count > 10:
            self.lbl_abnormal['val_lbl'].setStyleSheet("color: #fbbf24; font-size: 15px; font-weight: bold; font-family: 'Microsoft JhengHei', Consolas;") # Alert Yellow
        else:
            self.lbl_abnormal['val_lbl'].setStyleSheet("color: #f8fafc; font-size: 15px; font-weight: bold; font-family: 'Microsoft JhengHei', Consolas;")
