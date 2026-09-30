#!/usr/bin/env python3
"""
Find in Page - Búsqueda en página tipo Chrome/Firefox

Características:
- Búsqueda incremental
- Resaltado de coincidencias
- Navegación entre resultados
- Contador de coincidencias
- Búsqueda case-sensitive opcional
"""

from PySide6.QtWidgets import (QWidget, QHBoxLayout, QLineEdit, QPushButton,
                               QLabel, QCheckBox)
from PySide6.QtCore import Qt, Signal
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtGui import QKeySequence, QShortcut


class FindInPageBar(QWidget):
    """Barra de búsqueda en página estilo Chrome"""

    # Señales
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_match = 0
        self.total_matches = 0
        self.current_page = None
        self.last_search_text = ""

        self.setup_ui()
        self.setup_shortcuts()
        self.hide()  # Oculta por defecto
    def setup_ui(self):
        """Configurar interfaz de usuario"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        # Campo de búsqueda
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar en la página...")
        self.search_input.setFixedWidth(250)
        self.search_input.textChanged.connect(self.on_search_changed)
        self.search_input.returnPressed.connect(self.find_next)
        layout.addWidget(self.search_input)

        # Contador de coincidencias
        self.counter_label = QLabel("0 de 0")
        self.counter_label.setFixedWidth(70)
        self.counter_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.counter_label)

        # Botón anterior
        self.prev_btn = QPushButton("⮝")
        self.prev_btn.setFixedSize(30, 30)
        self.prev_btn.setToolTip("Anterior (Shift+F3)")
        self.prev_btn.clicked.connect(self.find_previous)
        layout.addWidget(self.prev_btn)

        # Botón siguiente
        self.next_btn = QPushButton("⮟")
        self.next_btn.setFixedSize(30, 30)
        self.next_btn.setToolTip("Siguiente (F3)")
        self.next_btn.clicked.connect(self.find_next)
        layout.addWidget(self.next_btn)

        # Checkbox case sensitive
        self.case_checkbox = QCheckBox("Aa")
        self.case_checkbox.setToolTip("Coincidir mayúsculas/minúsculas")
        self.case_checkbox.toggled.connect(self.on_search_changed)
        layout.addWidget(self.case_checkbox)

        # Botón cerrar
        self.close_btn = QPushButton()
        try:
            from ui.core.strip_icons import build_nav_icon
            from PySide6.QtCore import QSize as _QSize
            self.close_btn.setIcon(build_nav_icon("ide_close", None, _QSize(14, 14)))
            self.close_btn.setIconSize(_QSize(14, 14))
        except Exception:
            pass
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setToolTip("Cerrar (Esc)")
        self.close_btn.clicked.connect(self.close_find_bar)
        layout.addWidget(self.close_btn)

        layout.addStretch()

        # Estilo visual
        self.setStyleSheet("""
            FindInPageBar {
                background-color: #f5f5f5;
                border-bottom: 1px solid #d0d0d0;
            }
            QLineEdit {
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 5px 8px;
                background-color: white;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 2px solid #4a90e2;
            }
            QPushButton {
                border: 1px solid #ccc;
                border-radius: 4px;
                background-color: white;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #e8e8e8;
            }
            QPushButton:pressed {
                background-color: #d0d0d0;
            }
            QCheckBox {
                font-weight: bold;
                padding: 5px;
            }
            QLabel {
                color: #666;
                font-size: 12px;
            }
        """)
    def setup_shortcuts(self):
        """Configurar atajos de teclado"""
        # Esc para cerrar
        self.esc_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self.esc_shortcut.activated.connect(self.close_find_bar)

        # F3 para siguiente
        self.f3_shortcut = QShortcut(QKeySequence(Qt.Key_F3), self)
        self.f3_shortcut.activated.connect(self.find_next)

        # Shift+F3 para anterior
        self.shift_f3_shortcut = QShortcut(QKeySequence(Qt.SHIFT | Qt.Key_F3), self)
        self.shift_f3_shortcut.activated.connect(self.find_previous)
    def set_current_page(self, page):
        """Establecer la página actual donde buscar"""
        self.current_page = page
    def on_search_changed(self):
        """Manejar cambio en el texto de búsqueda"""
        search_text = self.search_input.text()

        if not search_text:
            self.counter_label.setText("0 de 0")
            self.search_input.setStyleSheet("")
            if self.current_page:
                # Limpiar búsqueda anterior
                self.current_page.findText("")
            return
        # Solo buscar si el texto cambió
        if search_text != self.last_search_text:
            self.last_search_text = search_text
            self.current_match = 1
            self.find_text(search_text)
    def find_text(self, text, backward=False):
        """Buscar texto en la página"""
        if not self.current_page or not text:
            return
        # Configurar flags de búsqueda
        flags = QWebEnginePage.FindFlag(0)

        if self.case_checkbox.isChecked():
            flags |= QWebEnginePage.FindCaseSensitively
        if backward:
            flags |= QWebEnginePage.FindBackward
        # Ejecutar búsqueda
        self.current_page.findText(text, flags, self.on_find_result)

        # Contar coincidencias totales usando JavaScript
        self.count_matches(text)
    def on_find_result(self, found):
        """Callback cuando se encuentra (o no) el texto"""
        if found:
            self.search_input.setStyleSheet("QLineEdit { background-color: #d4edda; }")
        else:
            if self.search_input.text():  # Solo si hay texto
                self.search_input.setStyleSheet("QLineEdit { background-color: #f8d7da; }")
    def count_matches(self, text):
        """Contar el total de coincidencias usando JavaScript"""
        if not self.current_page:
            return
        # Escapar caracteres especiales en regex
        escaped_text = text.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")

        # JavaScript para contar coincidencias
        js_code = f"""
        (function() {{
            try {{
                var searchText = "{escaped_text}";
                var bodyText = document.body.innerText || document.body.textContent;

                // Flags para regex
                var flags = "g{'i' if not self.case_checkbox.isChecked() else ''}";

                // Escapar caracteres especiales de regex
                var escapedSearch = searchText.replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&');

                var regex = new RegExp(escapedSearch, flags);
                var matches = bodyText.match(regex);

                return matches ? matches.length : 0;
            }} catch(e) {{
                return 0;
            }}
        }})();
        """

        self.current_page.runJavaScript(js_code, self.update_counter)
    def update_counter(self, total):
        """Actualizar el contador de coincidencias"""
        if total is None:
            total = 0
        self.total_matches = total

        if total > 0:
            self.counter_label.setText(f"{self.current_match} de {total}")
        else:
            self.counter_label.setText("0 de 0")
    def find_next(self):
        """Buscar siguiente coincidencia"""
        text = self.search_input.text()
        if not text:
            return
        if self.total_matches > 0:
            self.current_match = min(self.current_match + 1, self.total_matches)
        self.find_text(text, backward=False)
    def find_previous(self):
        """Buscar coincidencia anterior"""
        text = self.search_input.text()
        if not text:
            return
        if self.total_matches > 0:
            self.current_match = max(self.current_match - 1, 1)
        self.find_text(text, backward=True)
    def show_and_focus(self):
        """Mostrar la barra y dar foco al campo de búsqueda"""
        self.show()
        self.search_input.setFocus()
        self.search_input.selectAll()
    def close_find_bar(self):
        """Cerrar la barra de búsqueda"""
        # Limpiar búsqueda
        if self.current_page:
            self.current_page.findText("")
        self.search_input.clear()
        self.counter_label.setText("0 de 0")
        self.current_match = 0
        self.total_matches = 0
        self.last_search_text = ""
        self.hide()
        self.closed.emit()


class FindInPageManager:
    """Gestor de búsqueda en página para múltiples pestañas"""

    def __init__(self, find_bar, tab_manager):
        self.find_bar = find_bar
        self.tab_manager = tab_manager

        # Conectar cambio de pestaña
        if hasattr(tab_manager, 'tabs'):
            tab_manager.tabs.currentChanged.connect(self.on_tab_changed)
    def on_tab_changed(self, index):
        """Actualizar página actual cuando cambia la pestaña"""
        if index >= 0:
            current_tab = self.tab_manager.tabs.widget(index)
            if current_tab and hasattr(current_tab, 'page'):
                self.find_bar.set_current_page(current_tab.page())
    def activate_find(self):
        """Activar búsqueda en la pestaña actual"""
        # Obtener pestaña actual
        current_index = self.tab_manager.tabs.currentIndex()
        if current_index >= 0:
            current_tab = self.tab_manager.tabs.widget(current_index)
            if current_tab and hasattr(current_tab, 'page'):
                self.find_bar.set_current_page(current_tab.page())
                self.find_bar.show_and_focus()
