from datetime import datetime


from PySide6.QtWidgets import (QDialog, QVBoxLayout, QListWidget, QLabel, QWidget, 
                              QLineEdit, QHBoxLayout, QPushButton, QListWidgetItem)
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt


class HistoryManager:
    def __init__(self):
        self.history = []
    def record_history(self, url):
        self.history.append({"url": url.toString(), "timestamp": datetime.now()})
    def show_history(self, tab_manager):
        dialog = QDialog()

        dialog.setWindowTitle("History")

        dialog.resize(600, 400)

        layout = QVBoxLayout()

        label = QLabel("History:")

        layout.addWidget(label)

        history_list = QListWidget()

        for entry in self.history:
            history_list.addItem(f"{entry['url']} - {entry['timestamp']}")
        history_list.itemClicked.connect(lambda item: tab_manager.add_new_tab(item.text().split(' - ')[0]))

        layout.addWidget(history_list)


from PySide6.QtCore import Qt


class HistoryManager:
    def __init__(self):
        self.history = []
    def record_history(self, url):
        self.history.append({"url": url.toString(), "timestamp": datetime.now()})
    def show_history(self, tab_manager):
        dialog = QDialog()

        dialog.setWindowTitle("History")

        dialog.resize(600, 400)

        layout = QVBoxLayout()

        label = QLabel("History:")

        layout.addWidget(label)

        history_list = QListWidget()

        for entry in self.history:
            history_list.addItem(f"{entry['url']} - {entry['timestamp']}")
        history_list.itemClicked.connect(lambda item: tab_manager.add_new_tab(item.text().split(' - ')[0]))

        layout.addWidget(history_list)

        dialog.setLayout(layout)

        dialog.exec_()
    def clear_history(self):
        """Limpiar todo el historial de navegación"""
        self.history.clear()
        print("[HistoryManager] Historial limpiado")


class HistoryPanel(QWidget):
    """Panel de historial para la barra lateral"""

    def __init__(self, history_manager, tab_manager, parent=None):
        super().__init__(parent)
        self.history_manager = history_manager
        self.tab_manager = tab_manager
        self.setup_ui()
        self.refresh_history()
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header_layout = QHBoxLayout()
        title = QLabel("Historial")
        title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        header_layout.addWidget(title)

        clear_btn = QPushButton()
        try:
            from ui.core.strip_icons import build_nav_icon
            from PySide6.QtCore import QSize as _QSize
            clear_btn.setIcon(build_nav_icon("ide_trash", None, _QSize(16, 16)))
            clear_btn.setIconSize(_QSize(16, 16))
        except Exception:
            pass
        clear_btn.setToolTip("Limpiar historial")
        clear_btn.setFixedSize(30, 30)
        clear_btn.clicked.connect(self.clear_history)
        header_layout.addWidget(clear_btn)
        layout.addLayout(header_layout)

        # Search
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar en el historial...")
        self.search_input.textChanged.connect(self.filter_history)
        layout.addWidget(self.search_input)

        # List
        self.history_list = QListWidget()
        self.history_list.itemClicked.connect(self.open_history_item)
        layout.addWidget(self.history_list)
    def refresh_history(self):
        """Recargar lista completa"""
        self.history_list.clear()
        # Mostrar más recientes primero
        for entry in reversed(self.history_manager.history):
            self.add_item(entry)
    def add_item(self, entry):
        url = entry['url']
        timestamp = entry['timestamp'].strftime("%H:%M - %d/%m")

        item_text = f"{url}\n{timestamp}"
        item = QListWidgetItem(item_text)
        item.setData(Qt.UserRole, url)
        self.history_list.addItem(item)
    def filter_history(self, text):
        text = text.lower()
        for i in range(self.history_list.count()):
            item = self.history_list.item(i)
            url = item.data(Qt.UserRole).lower()
            item.setHidden(text not in url)
    def open_history_item(self, item):
        url = item.data(Qt.UserRole)
        self.show_url_in_tab(url)
    def show_url_in_tab(self, url):
        self.tab_manager.add_new_tab(url)
    def clear_history(self):
        self.history_manager.clear_history()
        self.refresh_history()
