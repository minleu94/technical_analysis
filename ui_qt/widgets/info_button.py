"""
資訊按鈕元件
提供可重用的「i」圖標按鈕和資訊對話框
"""

from PySide6.QtWidgets import (
    QPushButton, QDialog, QVBoxLayout, QHBoxLayout, 
    QLabel, QTextEdit, QScrollArea, QWidget, QFrame
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QIcon
from typing import Dict, List, Optional

from ui_qt.tab_info_config import get_tab_info


class InfoDialog(QDialog):
    """資訊對話框"""
    
    def __init__(self, tab_key: str, parent=None):
        """
        初始化資訊對話框
        
        Args:
            tab_key: Tab 的 key（例如 "update", "recommendation"）
            parent: 父窗口
        """
        super().__init__(parent)
        self.tab_key = tab_key
        self._setup_ui()
    
    def _setup_ui(self):
        """設置 UI"""
        self.setWindowTitle("頁面說明")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        self.setMaximumWidth(700)
        self.setMaximumHeight(600)
        
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # 獲取說明內容
        info = get_tab_info(self.tab_key)
        
        # 標題
        title_label = QLabel(info.get("title", "頁面說明"))
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        main_layout.addWidget(title_label)
        
        # 可滾動區域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(15)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        
        # 【這一頁在做什麼】
        what_frame = self._create_section(
            "這一頁在做什麼",
            info.get("what", "")
        )
        scroll_layout.addWidget(what_frame)
        
        # 【你通常怎麼用它】
        how_to_use = info.get("how_to_use", [])
        if how_to_use:
            how_frame = self._create_section(
                "你通常怎麼用它",
                self._format_list(how_to_use)
            )
            scroll_layout.addWidget(how_frame)
        
        # 【常見誤解 / 不該拿來做什麼】
        misconceptions = info.get("misconceptions", [])
        if misconceptions:
            mis_frame = self._create_section(
                "常見誤解 / 不該拿來做什麼",
                self._format_list(misconceptions)
            )
            scroll_layout.addWidget(mis_frame)
        
        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll)
        
        # 關閉按鈕
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        close_btn = QPushButton("關閉")
        close_btn.setMinimumWidth(100)
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)
        main_layout.addLayout(button_layout)
    
    def _create_section(self, title: str, content: str) -> QFrame:
        """
        創建一個說明區塊
        
        Args:
            title: 區塊標題
            content: 區塊內容
        
        Returns:
            QFrame 元件
        """
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setStyleSheet("""
            QFrame {
                background-color: #f5f5f5;
                border: 1px solid #ddd;
                border-radius: 5px;
                padding: 10px;
            }
        """)
        
        layout = QVBoxLayout(frame)
        layout.setSpacing(8)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # 標題
        title_label = QLabel(title)
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #333;")
        layout.addWidget(title_label)
        
        # 內容
        content_label = QLabel(content)
        content_label.setWordWrap(True)
        content_label.setStyleSheet("color: #666; line-height: 1.6;")
        layout.addWidget(content_label)
        
        return frame
    
    def _format_list(self, items: List[str]) -> str:
        """
        將列表格式化為文字
        
        Args:
            items: 列表項目
        
        Returns:
            格式化後的字串
        """
        formatted = []
        for i, item in enumerate(items, 1):
            formatted.append(f"{i}. {item}")
        return "\n".join(formatted)


class InfoButton(QPushButton):
    """資訊按鈕"""
    
    def __init__(self, tab_key: str, parent=None):
        """
        初始化資訊按鈕
        
        Args:
            tab_key: Tab 的 key（例如 "update", "recommendation"）
            parent: 父窗口
        """
        super().__init__(parent)
        self.tab_key = tab_key
        
        # 設置按鈕樣式
        self.setText("i")
        self.setToolTip("點擊查看頁面說明")
        self.setFixedSize(24, 24)
        
        # 設置字體
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        self.setFont(font)
        
        # 設置樣式（低干擾、hover 才高亮）
        self.setStyleSheet("""
            QPushButton {
                background-color: #e0e0e0;
                color: #666;
                border: 1px solid #ccc;
                border-radius: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4CAF50;
                color: white;
                border: 1px solid #4CAF50;
            }
            QPushButton:pressed {
                background-color: #45a049;
            }
        """)
        
        # 連接點擊事件
        self.clicked.connect(self._show_info)
    
    def _show_info(self):
        """顯示資訊對話框"""
        dialog = InfoDialog(self.tab_key, self.parent())
        dialog.exec()

