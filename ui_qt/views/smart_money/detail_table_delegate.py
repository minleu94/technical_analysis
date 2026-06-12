"""
Detail Table Delegate
專門用於渲染分點明細表格 (Detail Table) 的 QStyledItemDelegate。
為「淨買賣超」提供直觀的雙向水平長條圖，以亮麗色彩輔助視覺決策。
"""

import pandas as pd
from PySide6.QtWidgets import QStyledItemDelegate, QStyle
from PySide6.QtCore import Qt, QRect, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont

class DetailTableDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        # 精選 HSL 調和配色，高飽和度但溫和
        self.color_pos_bar = QColor("#059669")  # 翡翠綠 (Emerald 600)
        self.color_neg_bar = QColor("#e11d48")  # 玫瑰紅 (Rose 600)
        self.color_pos_text = QColor("#34d399") # 亮綠 (Emerald 400)
        self.color_neg_text = QColor("#fb7185") # 亮紅 (Rose 400)
        self.color_text_normal = QColor("#f1f5f9") # Slate 100
        self.color_bg_selected = QColor("#1e293b") # Slate 800
        self.color_border_line = QColor("#1e293b") # 分隔線

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = option.rect
        model = index.model()

        # 1. 繪製背景 (Selected 高亮或底線)
        if option.state & QStyle.State_Selected:
            painter.fillRect(rect, self.color_bg_selected)
        else:
            # 畫底部分隔線，提升表格層次感
            painter.setPen(self.color_border_line)
            painter.drawLine(rect.bottomLeft(), rect.bottomRight())

        col_name = ""
        if hasattr(model, '_visible_columns') and index.column() < len(model._visible_columns):
            col_name = model._visible_columns[index.column()]

        # 2. 判斷欄位並繪製
        if col_name == '淨買賣超' and hasattr(model, '_dataframe'):
            df = model._dataframe
            row_idx = index.row()
            if 0 <= row_idx < len(df):
                raw_val = df.iloc[row_idx, df.columns.get_loc(col_name)]
                val = 0.0
                raw_val_str = str(raw_val)
                try:
                    clean_str = raw_val_str.replace(",", "").replace("*(估)", "").replace("不可用", "0")
                    val = float(clean_str)
                except (ValueError, TypeError):
                    val = 0.0

                # 計算該列最大絕對值以進行比例分配
                max_abs_val = 1.0
                try:
                    numeric_series = pd.to_numeric(
                        df[col_name].astype(str).str.replace(",", "").str.replace("*(估)", "").str.replace("不可用", "0"),
                        errors='coerce'
                    ).fillna(0).abs()
                    max_abs_val = numeric_series.max()
                except Exception:
                    max_abs_val = 1.0

                if pd.isna(max_abs_val) or max_abs_val == 0:
                    max_abs_val = 1.0

                # 繪製雙向水平長條圖
                self._draw_bidirectional_bar(painter, rect, val, max_abs_val, raw_val_str)
        else:
            # 預設文字繪製
            text = str(index.data(Qt.DisplayRole) or "")
            alignment = index.data(Qt.TextAlignmentRole)
            if not alignment:
                alignment = Qt.AlignLeft | Qt.AlignVCenter

            # 根據欄位類別調整文字顏色
            if col_name in ['買進張數', '賣出張數']:
                painter.setPen(QColor("#94a3b8")) # 次要文字 Slate 400
            else:
                painter.setPen(self.color_text_normal)

            font = painter.font()
            if col_name == '分點名稱':
                font.setBold(True)
            painter.setFont(font)

            # 保留左右 10px padding 避免貼邊
            text_rect = rect.adjusted(10, 0, -10, 0)
            painter.drawText(text_rect, alignment, text)

        painter.restore()

    def _draw_bidirectional_bar(self, painter: QPainter, rect: QRect, val: float, max_val: float, raw_val_str: str = ""):
        # 內縮高度，讓 Bar 呈現精緻的置中藥丸形狀
        draw_rect = rect.adjusted(10, 8, -10, -8)
        center_x = draw_rect.left() + draw_rect.width() / 2

        # 限制極大比值為 1.0
        ratio = min(1.0, abs(val) / max_val)
        bar_w = (draw_rect.width() / 2) * ratio

        painter.setPen(Qt.NoPen)
        if val > 0:
            # 買超：中線向右延伸
            bar_rect = QRectF(center_x, draw_rect.top(), bar_w, draw_rect.height())
            fill_color = QColor(self.color_pos_bar)
            fill_color.setAlpha(60) # 35% 不透明度
            painter.setBrush(QBrush(fill_color))
            painter.drawRoundedRect(bar_rect, 4, 4)

            painter.setPen(self.color_pos_text)
        elif val < 0:
            # 賣超：中線向左延伸
            bar_rect = QRectF(center_x - bar_w, draw_rect.top(), bar_w, draw_rect.height())
            fill_color = QColor(self.color_neg_bar)
            fill_color.setAlpha(60)
            painter.setBrush(QBrush(fill_color))
            painter.drawRoundedRect(bar_rect, 4, 4)

            painter.setPen(self.color_neg_text)
        else:
            # 0: 畫一條灰色虛線
            painter.setPen(QPen(QColor("#475569"), 1, Qt.DashLine))
            painter.drawLine(int(center_x), draw_rect.top(), int(center_x), draw_rect.bottom())
            painter.setPen(self.color_text_normal)

        # 數值文字
        if raw_val_str:
            formatted_val = raw_val_str
        else:
            formatted_val = f"{val:+,}" if val != 0 else "0"

        text_rect = rect.adjusted(10, 0, -10, 0)
        # 對齊靠右
        painter.drawText(text_rect, Qt.AlignRight | Qt.AlignVCenter, formatted_val)
