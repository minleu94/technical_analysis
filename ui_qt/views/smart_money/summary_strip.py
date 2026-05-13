"""
Summary Strip
Terminal 風格的高資訊密度狀態列，位於 Scanner 上方。
"""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QFrame
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor
from app_module.dtos.flow_signal_dtos import SmartMoneySummaryDTO

class SummaryStrip(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 設置 Terminal 風格背景
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(self.backgroundRole(), QColor("#0f172a")) # 深藍灰背景
        self.setPalette(palette)
        
        self.setFixedHeight(50) # 固定高度 20%
        
        self._setup_ui()
        
    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 0, 15, 0)
        layout.setSpacing(25)
        
        # 建立欄位
        self.lbl_regime = self._create_data_group("REGIME")
        self.lbl_heat = self._create_data_group("MARKET HEAT")
        self.lbl_bull_bear = self._create_data_group("BULL / BEAR")
        self.lbl_abnormal = self._create_data_group("ABNORMAL SIGNALS")
        
        layout.addWidget(self.lbl_regime['group'])
        layout.addWidget(self._create_separator())
        layout.addWidget(self.lbl_heat['group'])
        layout.addWidget(self._create_separator())
        layout.addWidget(self.lbl_bull_bear['group'])
        layout.addWidget(self._create_separator())
        layout.addWidget(self.lbl_abnormal['group'])
        
        layout.addStretch()
        
    def _create_separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        line.setFrameShadow(QFrame.Plain)
        line.setStyleSheet("color: #334155;")
        return line
        
    def _create_data_group(self, title: str) -> dict:
        group = QWidget()
        layout = QHBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        title_lbl = QLabel(title)
        font = QFont("Courier", 9, QFont.Bold)
        title_lbl.setFont(font)
        title_lbl.setStyleSheet("color: #64748b;")
        
        val_lbl = QLabel("--")
        val_font = QFont("Consolas", 11, QFont.Bold)
        val_lbl.setFont(val_font)
        val_lbl.setStyleSheet("color: #f8fafc;")
        
        layout.addWidget(title_lbl)
        layout.addWidget(val_lbl)
        
        return {'group': group, 'val_lbl': val_lbl}

    def update_summary(self, summary: SmartMoneySummaryDTO):
        # 1. Regime
        self.lbl_regime['val_lbl'].setText(summary.market_regime)
        if "Bullish" in summary.market_regime:
            self.lbl_regime['val_lbl'].setStyleSheet("color: #4ade80;")
        elif "Bearish" in summary.market_regime:
            self.lbl_regime['val_lbl'].setStyleSheet("color: #f87171;")
        else:
            self.lbl_regime['val_lbl'].setStyleSheet("color: #f8fafc;")
            
        # 2. Market Heat
        self.lbl_heat['val_lbl'].setText(f"{summary.market_heat_score:.1f}")
        
        # 3. Bull / Bear
        self.lbl_bull_bear['val_lbl'].setText(f"{summary.bullish_stock_count} / {summary.bearish_stock_count}")
        
        # 4. Abnormal
        self.lbl_abnormal['val_lbl'].setText(f"{summary.abnormal_signal_count}")
        if summary.abnormal_signal_count > 10:
            self.lbl_abnormal['val_lbl'].setStyleSheet("color: #fbbf24;") # Warning Yellow
        else:
            self.lbl_abnormal['val_lbl'].setStyleSheet("color: #f8fafc;")
