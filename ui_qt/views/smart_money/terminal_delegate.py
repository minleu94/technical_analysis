"""
Terminal Delegate
純 Qt 原生繪圖實作：無 WebView, 無大量元件，極致低 CPU/RAM 佔用。
負責繪製 Row Intensity, Pill Badges, Inline Sparkline 與 Text Hierarchy。
已優化：漸層折線/面積圖、多彩語意標籤與左側精緻色彩指示條。
"""

from PySide6.QtWidgets import QStyledItemDelegate, QStyle
from PySide6.QtCore import Qt, QRect, QRectF, QPointF, QEvent
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPainterPath, QLinearGradient
from ui_qt.views.smart_money.terminal_table_model import ROLE_INTENSITY, ROLE_SPARKLINE, ROLE_BADGES, ROLE_SCORE

class TerminalScannerDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.chart_type = 'bar'  # 'line', 'bar', 'area'
        
        # 色彩常數 (高質感 Slate + Emerald + Rose 配色)
        self.color_bg_buy_strong = QColor("#062f21")  # 深翡翠綠 (強度 3)
        self.color_bg_buy_med = QColor("#042318")     # (強度 2)
        self.color_bg_buy_weak = QColor("#021710")    # (強度 1)
        
        self.color_bg_sell_strong = QColor("#3f0c15") # 深玫瑰紅 (強度 -3)
        self.color_bg_sell_med = QColor("#2d060c")    # (強度 -2)
        self.color_bg_sell_weak = QColor("#1f0308")   # (強度 -1)
        
        self.color_text_normal = QColor("#e2e8f0")    # Slate 200
        self.color_text_faded = QColor("#64748b")     # Slate 500
        self.color_text_highlight = QColor("#ffffff") # Pure White
        
        self.color_badge_bg = QColor("#1e293b")
        self.color_badge_text = QColor("#cbd5e1")
        
        self.color_sparkline_pos = QColor("#10b981")  # 亮綠 (Emerald 500)
        self.color_sparkline_neg = QColor("#f43f5e")  # 亮紅 (Rose 500)
        self.color_sparkline_base = QColor("#475569") # Slate 600
        self.color_border_line = QColor("#1e293b")    # Slate 800 行底線

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        
        rect = option.rect
        painter.setClipRect(rect)
        
        # 1. 取得自定義資料
        intensity = index.data(ROLE_INTENSITY) or 0
        score = index.data(ROLE_SCORE) or 0.0
        col = index.column()
        
        # 2. 繪製 Row Intensity (背景) 與選中高亮
        self._draw_background(painter, rect, intensity, option.state & QStyle.State_Selected, col)
        
        # 3. 分欄繪製
        if col == 6:
            # Badges Column
            badges = index.data(ROLE_BADGES)
            if badges:
                self._draw_badges(painter, rect, badges)
        elif col == 7:
            # Sparkline Column
            sparkline_data = index.data(ROLE_SPARKLINE)
            if sparkline_data:
                self._draw_sparkline(painter, rect, sparkline_data)
        else:
            # 預設文字 Column
            text = str(index.data(Qt.DisplayRole) or "")
            self._draw_text(painter, rect, text, score, index.data(Qt.TextAlignmentRole))
            
        # 4. 繪製細微的水平格線
        painter.setPen(self.color_border_line)
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        
        painter.restore()

    def _draw_background(self, painter: QPainter, rect: QRect, intensity: int, is_selected: bool, column: int):
        bg_color = None
        
        if intensity == 3: bg_color = self.color_bg_buy_strong
        elif intensity == 2: bg_color = self.color_bg_buy_med
        elif intensity == 1: bg_color = self.color_bg_buy_weak
        elif intensity == -1: bg_color = self.color_bg_sell_weak
        elif intensity == -2: bg_color = self.color_bg_sell_med
        elif intensity == -3: bg_color = self.color_bg_sell_strong
        
        # 選中狀態下，背景亮化
        if is_selected:
            if bg_color:
                bg_color = bg_color.lighter(130)
            else:
                bg_color = QColor("#1e293b") # Slate 800
                
        if bg_color:
            painter.fillRect(rect, bg_color)
            
        # 在最左側 (第一欄) 繪製一條精緻的垂直色彩提示條
        if column == 0 and intensity != 0:
            bar_color = self.color_sparkline_pos if intensity > 0 else self.color_sparkline_neg
            indicator_rect = QRect(rect.x(), rect.y() + 2, 4, rect.height() - 4)
            painter.fillRect(indicator_rect, bar_color)
            
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
        
        # 留白邊距 10px
        text_rect = rect.adjusted(10, 0, -10, 0)
        elided_text = painter.fontMetrics().elidedText(text, Qt.ElideRight, text_rect.width())
        painter.drawText(text_rect, alignment, elided_text)

    def _draw_badges(self, painter: QPainter, rect: QRect, badges: list):
        if not badges: return
        
        font = painter.font()
        font.setPointSize(max(8, font.pointSize() - 1))
        font.setBold(True)
        painter.setFont(font)
        fm = painter.fontMetrics()
        
        x_offset = rect.x() + 10
        y_center = rect.y() + rect.height() // 2
        
        for badge_text in badges:
            text_width = fm.horizontalAdvance(badge_text)
            badge_width = text_width + 14
            badge_height = fm.height() + 6
            
            badge_rect = QRect(
                x_offset,
                y_center - badge_height // 2,
                badge_width,
                badge_height
            )
            
            # 若超出範圍則截斷不畫
            if badge_rect.right() > rect.right():
                break
                
            # 依據文字內容，語意化指派顏色
            text_upper = badge_text.upper()
            if any(k in text_upper for k in ["BUY", "吸籌", "買超", "強勢"]):
                bg_color = QColor("#064e3b") # 淡綠背景
                bg_color.setAlpha(180)
                fg_color = QColor("#34d399") # 亮綠字體
            elif any(k in text_upper for k in ["SELL", "出貨", "賣超", "弱勢"]):
                bg_color = QColor("#4c0519") # 淡紅背景
                bg_color.setAlpha(180)
                fg_color = QColor("#fb7185") # 亮紅字體
            elif any(k in text_upper for k in ["STRONG", "強大"]):
                bg_color = QColor("#581c87") # 淡紫背景
                bg_color.setAlpha(180)
                fg_color = QColor("#c084fc") # 亮紫字體
            elif any(k in text_upper for k in ["MED", "中等"]):
                bg_color = QColor("#78350f") # 淡橘背景
                bg_color.setAlpha(180)
                fg_color = QColor("#fbbf24") # 亮橘字體
            else:
                bg_color = QColor("#1e293b") # 預設 Slate 800
                fg_color = QColor("#cbd5e1") # Slate 300
                
            # 畫背景
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(bg_color))
            painter.drawRoundedRect(badge_rect, 4, 4) # 精緻小圓角
            
            # 畫文字
            painter.setPen(fg_color)
            painter.drawText(badge_rect, Qt.AlignCenter, badge_text)
            
            x_offset += badge_width + 6

    def _draw_sparkline(self, painter: QPainter, rect: QRect, data: list):
        if not data or len(data) < 2:
            return
            
        # 在欄位內用固定最大繪圖寬度，避免 5 根 bar 隨欄寬被拉太開。
        draw_rect = rect.adjusted(14, 8, -10, -8)
        
        max_val = max(data)
        min_val = min(data)
        val_range = max_val - min_val
        if val_range == 0: val_range = 1.0
        
        # 繪製基準線 (Zero line)
        y_zero = draw_rect.bottom()
        if max_val > 0 and min_val < 0:
            y_zero = draw_rect.top() + (max_val / val_range) * draw_rect.height()
            painter.setPen(QPen(self.color_border_line, 1, Qt.DashLine))
            painter.drawLine(draw_rect.left(), int(y_zero), draw_rect.right(), int(y_zero))
        
        # 計算點位。bar chart 使用緊湊繪圖區，line/area 仍使用可用寬度。
        points = []
        chart_width = draw_rect.width()
        if self.chart_type == 'bar':
            chart_width = min(draw_rect.width(), max(84.0, (len(data) - 1) * 30.0))
        x_step = chart_width / max(1, len(data) - 1)
        for i, val in enumerate(data):
            x = draw_rect.left() + i * x_step
            normalized = (val - min_val) / val_range
            y = draw_rect.bottom() - (normalized * draw_rect.height())
            points.append((x, y, val))
            
        # 決定主線條顏色 (看最後一天的趨勢)
        pen_color = self.color_sparkline_base
        if data[-1] > 0:
            pen_color = self.color_sparkline_pos
        elif data[-1] < 0:
            pen_color = self.color_sparkline_neg
            
        if self.chart_type == 'bar':
            # Bar Chart (Histogram)
            painter.setPen(Qt.NoPen)
            bar_width = min(14.0, max(2.0, x_step * 0.48))
            
            for x, y, val in points:
                color = self.color_sparkline_pos if val > 0 else self.color_sparkline_neg if val < 0 else self.color_sparkline_base
                painter.setBrush(QBrush(color))
                
                # 計算 bar 的矩形 (從零軸出發)
                if val >= 0:
                    bar_rect = QRectF(x - bar_width/2, y, bar_width, y_zero - y)
                else:
                    bar_rect = QRectF(x - bar_width/2, y_zero, bar_width, y - y_zero)
                
                # 若數值太小，保證至少 1px 高度
                if bar_rect.height() < 1:
                    bar_rect.setHeight(1)
                    if val >= 0:
                        bar_rect.moveTop(y_zero - 1)
                
                # 繪製帶圓角的微型直方圖
                painter.drawRoundedRect(bar_rect, 1.5, 1.5)
                
        else:
            # Line or Area Chart
            pen = QPen(pen_color, 2)
            pen.setJoinStyle(Qt.RoundJoin)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            
            path = QPainterPath(QPointF(points[0][0], points[0][1]))
            for p in points[1:]:
                path.lineTo(QPointF(p[0], p[1]))
                
            if self.chart_type == 'area':
                # 畫實線邊框
                painter.drawPath(path)
                
                # 建立封閉的面積路徑
                area_path = QPainterPath(path)
                area_path.lineTo(QPointF(points[-1][0], y_zero))
                area_path.lineTo(QPointF(points[0][0], y_zero))
                area_path.closeSubpath()
                
                # 建立垂直線性漸層，從主色漸變為透明
                gradient = QLinearGradient(0, draw_rect.top(), 0, draw_rect.bottom())
                color_start = QColor(pen_color)
                color_start.setAlpha(80) # 頂部不透明度 30%
                color_end = QColor(pen_color)
                color_end.setAlpha(5)   # 底部趨近透明
                
                gradient.setColorAt(0.0, color_start)
                gradient.setColorAt(1.0, color_end)
                
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(gradient))
                painter.drawPath(area_path)
            else:
                # 一般 Line Chart
                painter.drawPath(path)

    def helpEvent(self, event, view, option, index):
        from PySide6.QtWidgets import QToolTip
        if event and event.type() == QEvent.ToolTip:
            tooltip = index.data(Qt.ToolTipRole)
            if tooltip:
                QToolTip.showText(event.globalPos(), tooltip, view)
                return True
        return super().helpEvent(event, view, option, index)
