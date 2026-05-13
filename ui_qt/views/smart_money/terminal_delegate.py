"""
Terminal Delegate
純 Qt 原生繪圖實作：無 WebView, 無大量元件，極致低 CPU/RAM 佔用。
負責繪製 Row Intensity, Pill Badges, Inline Sparkline 與 Text Hierarchy。
"""

from PySide6.QtWidgets import QStyledItemDelegate, QStyle
from PySide6.QtCore import Qt, QRect, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPainterPath
from ui_qt.views.smart_money.terminal_table_model import ROLE_INTENSITY, ROLE_SPARKLINE, ROLE_BADGES, ROLE_SCORE

class TerminalScannerDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 色彩常數 (Terminal 風格)
        self.color_bg_buy_strong = QColor("#1a3322")  # 淡暗綠
        self.color_bg_buy_med = QColor("#152419")
        self.color_bg_buy_weak = QColor("#0d1710")
        
        self.color_bg_sell_strong = QColor("#331a1a") # 淡暗紅
        self.color_bg_sell_med = QColor("#241515")
        self.color_bg_sell_weak = QColor("#170d0d")
        
        self.color_text_normal = QColor("#d0d0d0")
        self.color_text_faded = QColor("#606060")
        self.color_text_highlight = QColor("#ffffff")
        
        self.color_badge_bg = QColor("#2d3748") # Pill Tag 背景
        self.color_badge_text = QColor("#e2e8f0") # Pill Tag 文字
        
        self.color_sparkline_pos = QColor("#4ade80") # 亮綠
        self.color_sparkline_neg = QColor("#f87171") # 亮紅
        self.color_sparkline_base = QColor("#4b5563")

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        
        rect = option.rect
        
        # 1. 取得自定義資料
        intensity = index.data(ROLE_INTENSITY) or 0
        score = index.data(ROLE_SCORE) or 0.0
        
        # 2. 繪製 Row Intensity (背景)
        self._draw_background(painter, rect, intensity, option.state & QStyle.State_Selected)
        
        col = index.column()
        
        # 3. 分欄繪製
        if col == 4:
            # Badges Column
            badges = index.data(ROLE_BADGES)
            if badges:
                self._draw_badges(painter, rect, badges)
        elif col == 5:
            # Sparkline Column
            sparkline_data = index.data(ROLE_SPARKLINE)
            if sparkline_data:
                self._draw_sparkline(painter, rect, sparkline_data)
        else:
            # 預設文字 Column
            text = str(index.data(Qt.DisplayRole) or "")
            self._draw_text(painter, rect, text, score, index.data(Qt.TextAlignmentRole))
            
        painter.restore()

    def _draw_background(self, painter: QPainter, rect: QRect, intensity: int, is_selected: bool):
        bg_color = None
        
        if intensity == 3: bg_color = self.color_bg_buy_strong
        elif intensity == 2: bg_color = self.color_bg_buy_med
        elif intensity == 1: bg_color = self.color_bg_buy_weak
        elif intensity == -1: bg_color = self.color_bg_sell_weak
        elif intensity == -2: bg_color = self.color_bg_sell_med
        elif intensity == -3: bg_color = self.color_bg_sell_strong
        
        if is_selected:
            # 若被選中，疊加一層半透明高光
            if bg_color:
                bg_color = bg_color.lighter(130)
            else:
                bg_color = QColor("#2a3545")
                
        if bg_color:
            painter.fillRect(rect, bg_color)
            
    def _draw_text(self, painter: QPainter, rect: QRect, text: str, score: float, alignment):
        if not alignment:
            alignment = Qt.AlignLeft | Qt.AlignVCenter
            
        font = painter.font()
        # 建立視覺階層
        if score >= 50:
            font.setBold(True)
            painter.setPen(self.color_text_highlight)
        elif score <= 10:
            font.setBold(False)
            painter.setPen(self.color_text_faded)
        else:
            font.setBold(False)
            painter.setPen(self.color_text_normal)
            
        painter.setFont(font)
        
        # 留白邊距
        text_rect = rect.adjusted(5, 0, -5, 0)
        painter.drawText(text_rect, alignment, text)

    def _draw_badges(self, painter: QPainter, rect: QRect, badges: list):
        if not badges: return
        
        font = painter.font()
        font.setPointSize(max(7, font.pointSize() - 2))
        painter.setFont(font)
        fm = painter.fontMetrics()
        
        x_offset = rect.x() + 5
        y_center = rect.y() + rect.height() // 2
        
        for badge_text in badges:
            text_width = fm.horizontalAdvance(badge_text)
            badge_width = text_width + 12
            badge_height = fm.height() + 4
            
            badge_rect = QRect(
                x_offset,
                y_center - badge_height // 2,
                badge_width,
                badge_height
            )
            
            # 若超出範圍則截斷不畫
            if badge_rect.right() > rect.right():
                break
                
            # 畫背景
            painter.setPen(Qt.NoPen)
            painter.setBrush(self.color_badge_bg)
            painter.drawRoundedRect(badge_rect, badge_height//2, badge_height//2)
            
            # 畫文字
            painter.setPen(self.color_badge_text)
            painter.drawText(badge_rect, Qt.AlignCenter, badge_text)
            
            x_offset += badge_width + 5

    def _draw_sparkline(self, painter: QPainter, rect: QRect, data: list):
        if not data or len(data) < 2:
            return
            
        # 在保留 Padding 的區域內繪圖
        draw_rect = rect.adjusted(5, 8, -5, -8)
        
        max_val = max(data)
        min_val = min(data)
        val_range = max_val - min_val
        if val_range == 0: val_range = 1
        
        # 繪製基準線 (Zero line)
        y_zero = draw_rect.bottom()
        if max_val > 0 and min_val < 0:
            y_zero = draw_rect.top() + (max_val / val_range) * draw_rect.height()
            painter.setPen(QPen(self.color_sparkline_base, 1, Qt.DashLine))
            painter.drawLine(draw_rect.left(), int(y_zero), draw_rect.right(), int(y_zero))
        
        # 計算點位
        points = []
        x_step = draw_rect.width() / (len(data) - 1)
        for i, val in enumerate(data):
            x = draw_rect.left() + i * x_step
            # 將數值映射到高度 (數值越大，Y越小)
            normalized = (val - min_val) / val_range
            y = draw_rect.bottom() - (normalized * draw_rect.height())
            points.append(QPointF(x, y))
            
        # 決定顏色 (看最後一天的趨勢)
        pen_color = self.color_sparkline_base
        if data[-1] > 0:
            pen_color = self.color_sparkline_pos
        elif data[-1] < 0:
            pen_color = self.color_sparkline_neg
            
        pen = QPen(pen_color, 2)
        pen.setJoinStyle(Qt.RoundJoin)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        
        # 使用 QPainterPath 繪製連續線條
        path = QPainterPath(points[0])
        for p in points[1:]:
            path.lineTo(p)
            
        painter.drawPath(path)
