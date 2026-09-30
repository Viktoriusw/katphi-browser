#!/usr/bin/env python3
"""
Homepage Manager - Gestor de página de inicio personalizable

Características:
- Página de inicio personalizable
- Múltiples opciones: URL específica, página en blanco, motor de búsqueda
- Configuración de nueva pestaña
- Accesos directos a sitios frecuentes
"""

from PySide6.QtCore import QSettings, Signal, QObject
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QLineEdit, QRadioButton, QButtonGroup, QPushButton,
                               QGroupBox, QMessageBox, QCheckBox)


class HomepageManager(QObject):
    """Gestor de página de inicio"""

    # Tipos de página de inicio
    HOME_BLANK = "blank"
    HOME_SEARCH_ENGINE = "search_engine"
    HOME_CUSTOM_URL = "custom_url"
    HOME_NEW_TAB_PAGE = "new_tab_page"

    # Señal emitida cuando cambia la configuración
    homepage_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("Katphi", "Homepage")
        self.parent_window = parent

        # Configuración predeterminada
        self.homepage_type = self.HOME_SEARCH_ENGINE
        self.custom_url = "https://www.google.com"
        self.use_for_new_tabs = True

        # Cargar configuración guardada
        self.load_settings()
    def load_settings(self):
        """Cargar configuración guardada"""
        self.homepage_type = self.settings.value("homepage_type", self.HOME_SEARCH_ENGINE)
        self.custom_url = self.settings.value("custom_url", "https://www.google.com")
        self.use_for_new_tabs = self.settings.value("use_for_new_tabs", True, type=bool)
    def save_settings(self):
        """Guardar configuración"""
        self.settings.setValue("homepage_type", self.homepage_type)
        self.settings.setValue("custom_url", self.custom_url)
        self.settings.setValue("use_for_new_tabs", self.use_for_new_tabs)
        self.settings.sync()
        self.homepage_changed.emit()
    def get_homepage_url(self):
        """
        Obtener URL de página de inicio según configuración

        Returns:
            str: URL de la página de inicio, o None para página en blanco
        """
        if self.homepage_type == self.HOME_BLANK:
            return "about:blank"
        elif self.homepage_type == self.HOME_SEARCH_ENGINE:
            # Usar motor de búsqueda predeterminado
            if hasattr(self.parent_window, 'search_engine_manager') and self.parent_window.search_engine_manager:
                engine = self.parent_window.search_engine_manager.get_default_engine()
                if engine:
                    # Usar la URL base del motor
                    if engine.id == 'google':
                        return "https://www.google.com"
                    elif engine.id == 'duckduckgo':
                        return "https://duckduckgo.com"
                    elif engine.id == 'bing':
                        return "https://www.bing.com"
                    elif engine.id == 'yahoo':
                        return "https://www.yahoo.com"
                    elif engine.id == 'wikipedia':
                        return "https://es.wikipedia.org"
                    elif engine.id == 'youtube':
                        return "https://www.youtube.com"
                    elif engine.id == 'github':
                        return "https://github.com"
                    elif engine.id == 'stackoverflow':
                        return "https://stackoverflow.com"
            return "https://duckduckgo.com"  # Fallback
        elif self.homepage_type == self.HOME_CUSTOM_URL:
            return self.custom_url
        elif self.homepage_type == self.HOME_NEW_TAB_PAGE:
            # Página de nueva pestaña personalizada (futuro)
            return "about:newtab"  # Placeholder
        return "https://duckduckgo.com"  # Fallback
    def get_new_tab_url(self):
        """
        Obtener URL para nuevas pestañas

        Returns:
            str: URL para nuevas pestañas
        """
        if self.use_for_new_tabs:
            return self.get_homepage_url()
        else:
            # Usar motor de búsqueda predeterminado para nuevas pestañas
            if hasattr(self.parent_window, 'search_engine_manager') and self.parent_window.search_engine_manager:
                engine = self.parent_window.search_engine_manager.get_default_engine()
                if engine:
                    if engine.id == 'google':
                        return "https://www.google.com"
                    elif engine.id == 'duckduckgo':
                        return "https://duckduckgo.com"
                    elif engine.id == 'bing':
                        return "https://www.bing.com"
            return "https://duckduckgo.com"


class HomepageSettingsDialog(QDialog):
    """Diálogo de configuración de página de inicio"""

    def __init__(self, homepage_manager, parent=None):
        super().__init__(parent)
        self.homepage_manager = homepage_manager

        self.setWindowTitle("Configuración de página de inicio")
        self.setMinimumSize(550, 400)

        self.setup_ui()
        self.load_current_settings()
    def setup_ui(self):
        """Configurar interfaz"""
        layout = QVBoxLayout(self)

        # Título
        title = QLabel("Página de inicio y nuevas pestañas")
        title.setStyleSheet("font-size: 14px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)

        # Grupo: Página de inicio
        home_group = QGroupBox("Página de inicio")
        home_layout = QVBoxLayout()

        # Grupo de botones de radio
        self.button_group = QButtonGroup()

        # Opción 1: Página en blanco
        self.blank_radio = QRadioButton("Página en blanco")
        self.button_group.addButton(self.blank_radio, 0)
        home_layout.addWidget(self.blank_radio)

        # Opción 2: Motor de búsqueda predeterminado
        self.search_engine_radio = QRadioButton("Motor de búsqueda predeterminado")
        self.button_group.addButton(self.search_engine_radio, 1)
        home_layout.addWidget(self.search_engine_radio)

        # Info sobre motor actual
        if hasattr(self.homepage_manager.parent_window, 'search_engine_manager'):
            engine = self.homepage_manager.parent_window.search_engine_manager.get_default_engine()
            if engine:
                engine_info = QLabel(f"    Actual: {engine.name}")
                engine_info.setStyleSheet("color: #666; font-size: 11px; margin-left: 24px;")
                home_layout.addWidget(engine_info)
        # Opción 3: URL personalizada
        self.custom_radio = QRadioButton("URL personalizada:")
        self.button_group.addButton(self.custom_radio, 2)
        home_layout.addWidget(self.custom_radio)

        # Campo de URL personalizada
        custom_url_layout = QHBoxLayout()
        custom_url_layout.addSpacing(24)
        self.custom_url_input = QLineEdit()
        self.custom_url_input.setPlaceholderText("https://www.ejemplo.com")
        self.custom_url_input.textChanged.connect(self.on_custom_url_changed)
        custom_url_layout.addWidget(self.custom_url_input)
        home_layout.addLayout(custom_url_layout)

        # Botón: Usar página actual
        use_current_btn = QPushButton("Usar página actual")
        use_current_btn.clicked.connect(self.use_current_page)
        use_current_btn.setMaximumWidth(180)
        use_current_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 12px;
                border-radius: 4px;
                background-color: #f0f0f0;
                border: 1px solid #ccc;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
        """)
        current_btn_layout = QHBoxLayout()
        current_btn_layout.addSpacing(24)
        current_btn_layout.addWidget(use_current_btn)
        current_btn_layout.addStretch()
        home_layout.addLayout(current_btn_layout)

        home_group.setLayout(home_layout)
        layout.addWidget(home_group)

        # Grupo: Nuevas pestañas
        new_tab_group = QGroupBox("Nuevas pestañas")
        new_tab_layout = QVBoxLayout()

        self.use_for_new_tabs_check = QCheckBox("Usar página de inicio para nuevas pestañas")
        self.use_for_new_tabs_check.setChecked(True)
        new_tab_layout.addWidget(self.use_for_new_tabs_check)

        info_label = QLabel(
            "Si está desactivado, las nuevas pestañas usarán el motor de búsqueda predeterminado."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #666; font-size: 11px; margin-top: 5px;")
        new_tab_layout.addWidget(info_label)

        new_tab_group.setLayout(new_tab_layout)
        layout.addWidget(new_tab_group)

        # Información adicional
        tip_label = QLabel(
            "Consejo: Puedes cambiar el motor de búsqueda predeterminado en Ajustes > Búsqueda"
        )
        tip_label.setWordWrap(True)
        tip_label.setStyleSheet("color: #0066cc; font-size: 11px; margin-top: 10px; padding: 8px; background-color: #f0f7ff; border-radius: 4px;")
        layout.addWidget(tip_label)

        layout.addStretch()

        # Botones
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Guardar")
        save_btn.clicked.connect(self.save_settings)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #0066cc;
                color: white;
                padding: 6px 20px;
                border-radius: 4px;
                border: none;
            }
            QPushButton:hover {
                background-color: #0052a3;
            }
        """)
        buttons_layout.addWidget(save_btn)

        layout.addLayout(buttons_layout)
    def load_current_settings(self):
        """Cargar configuración actual"""
        # Seleccionar radio button según tipo
        if self.homepage_manager.homepage_type == HomepageManager.HOME_BLANK:
            self.blank_radio.setChecked(True)
        elif self.homepage_manager.homepage_type == HomepageManager.HOME_SEARCH_ENGINE:
            self.search_engine_radio.setChecked(True)
        elif self.homepage_manager.homepage_type == HomepageManager.HOME_CUSTOM_URL:
            self.custom_radio.setChecked(True)
        # Cargar URL personalizada
        self.custom_url_input.setText(self.homepage_manager.custom_url)

        # Cargar configuración de nuevas pestañas
        self.use_for_new_tabs_check.setChecked(self.homepage_manager.use_for_new_tabs)
    def on_custom_url_changed(self, text):
        """Al cambiar la URL personalizada, seleccionar automáticamente el radio"""
        if text.strip():
            self.custom_radio.setChecked(True)
    def use_current_page(self):
        """Usar la página actual como página de inicio"""
        try:
            parent = self.parent()
            if parent and hasattr(parent, 'tab_manager'):
                current_tab = parent.tab_manager.tabs.currentWidget()
                if current_tab:
                    current_url = current_tab.url().toString()
                    if current_url and current_url != "about:blank":
                        self.custom_url_input.setText(current_url)
                        self.custom_radio.setChecked(True)
                        QMessageBox.information(
                            self,
                            "Página actual seleccionada",
                            f"Página de inicio configurada a:\n{current_url}"
                        )
                        return
            QMessageBox.warning(
                self,
                "Sin página actual",
                "No hay una página válida en la pestaña actual."
            )
        except Exception as e:
            print(f"[Homepage] Error using current page: {e}")
            QMessageBox.warning(
                self,
                "Error",
                "No se pudo usar la página actual."
            )
    def save_settings(self):
        """Guardar configuración"""
        # Determinar tipo seleccionado
        if self.blank_radio.isChecked():
            self.homepage_manager.homepage_type = HomepageManager.HOME_BLANK
        elif self.search_engine_radio.isChecked():
            self.homepage_manager.homepage_type = HomepageManager.HOME_SEARCH_ENGINE
        elif self.custom_radio.isChecked():
            self.homepage_manager.homepage_type = HomepageManager.HOME_CUSTOM_URL
            # Validar URL personalizada
            custom_url = self.custom_url_input.text().strip()
            if not custom_url:
                QMessageBox.warning(
                    self,
                    "URL vacía",
                    "Por favor, ingresa una URL personalizada."
                )
                return
            self.homepage_manager.custom_url = custom_url
        # Guardar configuración de nuevas pestañas
        self.homepage_manager.use_for_new_tabs = self.use_for_new_tabs_check.isChecked()

        # Guardar en settings
        self.homepage_manager.save_settings()

        QMessageBox.information(
            self,
            "Configuración guardada",
            "La página de inicio ha sido configurada correctamente.\n\n"
            "Los cambios se aplicarán en las nuevas pestañas que abras."
        )

        self.accept()
