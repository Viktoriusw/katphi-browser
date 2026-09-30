#!/usr/bin/env python3


"""


Panel de Autenticación Robusto - UI para login y gestión de cuenta


Validación agresiva y feedback claro para el usuario


"""


from PySide6.QtWidgets import (


    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,

    QMessageBox, QDialog, QFormLayout, QCheckBox, QGroupBox, QListWidget,

    QListWidgetItem, QProgressBar, QFrame, QScrollArea, QTabWidget,

    QTextEdit, QSplitter, QSizePolicy, QStackedWidget, QSpacerItem


)


from PySide6.QtCore import Qt, Signal, QTimer, QThread, QPropertyAnimation, QEasingCurve


from PySide6.QtGui import QFont, QIcon, QPixmap, QPalette, QColor, QMovie


from base_panel import BasePanel


from auth_manager import AuthManager, UserCredentials, PluginLicense, AuthResult, AuthError


import webbrowser


import logging
# Logging configurado en main.py
logger = logging.getLogger(__name__)


def _get_login_theme_colors() -> dict:
    """Obtiene colores del ThemeEngine activo para el diálogo de login."""
    try:
        from ui.core.theme_engine import get_theme_engine
        engine = get_theme_engine()
        if engine:
            c = engine.get_theme_data().get("colors", {})
            is_dark = engine.get_current_theme().lower() != "light"
            return {
                "bg": c.get("background", "#2B2D30" if is_dark else "#f5f5f5"),
                "surface": c.get("surface", "#3C3F41" if is_dark else "#ffffff"),
                "text": c.get("primary", "#E8EAED" if is_dark else "#111111"),
                "text_secondary": c.get("secondary", "#9AA0A6" if is_dark else "#555555"),
                "input_bg": c.get("input_background", "#3C3F41" if is_dark else "#ffffff"),
                "input_border": c.get("input_border", "#5F6368" if is_dark else "#d0d0d0"),
                "input_focus": c.get("input_focus", "#8AB4F8" if is_dark else "#0078d4"),
                "accent": c.get("accent", "#8AB4F8" if is_dark else "#0078d4"),
                "login_btn": c.get("login_button", "#8AB4F8" if is_dark else "#3498db"),
                "login_btn_hover": c.get("login_button_hover", "#1A73E8" if is_dark else "#2980b9"),
                "login_btn_pressed": c.get("login_button_pressed", "#174EA6" if is_dark else "#21618c"),
                "border": c.get("border", "#4E5254" if is_dark else "#e0e0e0"),
                "error_bg": c.get("surface", "#3C3F41" if is_dark else "#fff0f0"),
                "error_text": c.get("error", "#F28B82" if is_dark else "#c0392b"),
                "error_border": c.get("error", "#F28B82" if is_dark else "#e74c3c"),
                "is_dark": is_dark,
            }
    except Exception:
        pass
    return {
        "bg": "#f5f5f5", "surface": "#ffffff", "text": "#111111",
        "text_secondary": "#555555", "input_bg": "#ffffff",
        "input_border": "#d0d0d0", "input_focus": "#0078d4",
        "accent": "#0078d4", "login_btn": "#3498db",
        "login_btn_hover": "#2980b9", "login_btn_pressed": "#21618c",
        "border": "#e0e0e0", "error_bg": "#fff0f0",
        "error_text": "#c0392b", "error_border": "#e74c3c", "is_dark": False,
    }


class LoginDialog(QDialog):
    """Diálogo de login con validación robusta"""

    login_requested = Signal(str, str)  # email, password

    register_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Katphi - Iniciar Sesión")

        self.setMinimumSize(500, 600)

        self.setModal(True)

        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        # Estado de validación

        self.is_validating = False

        self.validation_attempts = 0

        self.max_attempts = 3

        # Cargar colores del tema activo antes de construir la UI
        self._tc = _get_login_theme_colors()

        self.setup_ui()

        self.setup_styles()

        self.setup_validation()
    def setup_validation(self):
        """Configurar validación en tiempo real"""

        # Timer para validación de email

        self.email_timer = QTimer()

        self.email_timer.setSingleShot(True)

        self.email_timer.timeout.connect(self._validate_email)

        # Conectar señales de validación

        self.email_edit.textChanged.connect(self._on_email_changed)

        self.password_edit.textChanged.connect(self._on_password_changed)
    def _on_email_changed(self):
        """Manejador de cambio en email"""

        self.email_timer.stop()

        self.email_timer.start(500)  # Validar después de 500ms de inactividad
    def _on_password_changed(self):
        """Manejador de cambio en contraseña"""

        self._update_login_button_state()
    def _validate_email(self):
        """Validar identificador de acceso (ID de usuario Katphi o email legacy)"""

        identifier = self.email_edit.text().strip()

        if identifier:
            if " " in identifier or len(identifier) < 3:
                self._show_field_error(self.email_edit, "Introduce tu ID de usuario o email")

                return False
            else:
                self._clear_field_error(self.email_edit)

                return True
        return False
    def _update_login_button_state(self):
        """Actualizar estado del botón de login"""

        email_valid = self._validate_email()

        password_valid = len(self.password_edit.text()) >= 6

        self.login_button.setEnabled(email_valid and password_valid and not self.is_validating)

        if self.is_validating:
            self.login_button.setText("Validando...")
        else:
            self.login_button.setText("Iniciar Sesión")
    def _show_field_error(self, field, message):
        """Mostrar error en un campo"""
        tc = self._tc
        field.setStyleSheet(f"""
            QLineEdit {{
                padding: 12px;
                border: 2px solid {tc['error_border']};
                border-radius: 8px;
                font-size: 14px;
                background-color: {tc['error_bg']};
                color: {tc['text']};
            }}
        """)
    def _clear_field_error(self, field):
        """Limpiar error de un campo"""
        tc = self._tc
        field.setStyleSheet(f"""
            QLineEdit {{
                padding: 12px;
                border: 2px solid {tc['input_border']};
                border-radius: 8px;
                font-size: 14px;
                background-color: {tc['input_bg']};
                color: {tc['text']};
            }}
            QLineEdit:focus {{
                border-color: {tc['input_focus']};
            }}
        """)
    def setup_ui(self):
        layout = QVBoxLayout(self)

        layout.setSpacing(20)

        layout.setContentsMargins(30, 30, 30, 30)

        # Header

        header_layout = QVBoxLayout()

        header_layout.setAlignment(Qt.AlignCenter)

        # Logo/Icon - Use account icon

        logo_label = QLabel()

        logo_label.setAlignment(Qt.AlignCenter)

        logo_label.setPixmap(QPixmap("icons/account.png").scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        logo_label.setStyleSheet("margin-bottom: 10px;")

        header_layout.addWidget(logo_label)

        # Title

        title_label = QLabel("Katphi")

        title_label.setAlignment(Qt.AlignCenter)

        title_label.setFont(QFont("Arial", 24, QFont.Bold))

        title_label.setStyleSheet(f"color: {self._tc['text']}; margin-bottom: 5px;")
        header_layout.addWidget(title_label)

        # Subtitle

        subtitle_label = QLabel("Accede a tus plugins premium")

        subtitle_label.setAlignment(Qt.AlignCenter)

        subtitle_label.setStyleSheet(f"color: {self._tc['text_secondary']}; font-size: 14px;")
        header_layout.addWidget(subtitle_label)

        layout.addLayout(header_layout)

        # Error label (initially hidden)

        self.error_label = QLabel()

        self.error_label.setAlignment(Qt.AlignCenter)

        self.error_label.setWordWrap(True)

        self.error_label.setStyleSheet(f"""

            QLabel {{

                background-color: {self._tc['error_bg']};
                color: {self._tc['error_text']};
                border: 1px solid {self._tc['error_border']};

                border-radius: 6px;

                padding: 10px;

                font-size: 13px;

                margin: 5px 0;
            }}
        """)

        self.error_label.hide()

        layout.addWidget(self.error_label)

        # Form

        form_layout = QFormLayout()

        form_layout.setSpacing(15)

        # Email field

        self.email_edit = QLineEdit()

        self.email_edit.setPlaceholderText("sc_xxxxxxxx")

        form_layout.addRow("ID user Katphi:", self.email_edit)

        # Password field

        self.password_edit = QLineEdit()

        self.password_edit.setEchoMode(QLineEdit.Password)

        self.password_edit.setPlaceholderText("Tu contraseña")

        form_layout.addRow("Contraseña:", self.password_edit)

        # Remember me checkbox

        self.remember_checkbox = QCheckBox("Recordar sesión")

        self.remember_checkbox.setChecked(True)

        form_layout.addRow("", self.remember_checkbox)

        layout.addLayout(form_layout)

        # Buttons

        button_layout = QVBoxLayout()

        button_layout.setSpacing(10)

        # Login button

        self.login_button = QPushButton("Iniciar Sesión")

        self.login_button.setStyleSheet("""

            QPushButton {

                background-color: #3498db;
                color: white;

                border: none;

                padding: 12px;

                border-radius: 8px;

                font-size: 16px;

                font-weight: bold;
            }

            QPushButton:hover {

                background-color: #2980b9;
            }

            QPushButton:pressed {

                background-color: #21618c;
            }

            QPushButton:disabled {

                background-color: #bdc3c7;
            }
        """)

        self.login_button.clicked.connect(self.on_login_clicked)

        button_layout.addWidget(self.login_button)

        # Register button

        self.register_button = QPushButton("Crear Cuenta")

        self.register_button.setStyleSheet("""

            QPushButton {

                background-color: transparent;

                color: #3498db;
                border: 2px solid #3498db;

                padding: 10px;

                border-radius: 8px;

                font-size: 14px;
            }

            QPushButton:hover {

                background-color: #3498db;
                color: white;
            }
        """)

        self.register_button.clicked.connect(self.on_register_clicked)

        button_layout.addWidget(self.register_button)

        # Forgot password link

        forgot_label = QLabel('<a href="#" style="color: #3498db; text-decoration: none;">¿Olvidaste tu contraseña?</a>')

        forgot_label.setAlignment(Qt.AlignCenter)

        forgot_label.linkActivated.connect(self.on_forgot_password)

        button_layout.addWidget(forgot_label)

        layout.addLayout(button_layout)

        # Connect enter key to login

        self.email_edit.returnPressed.connect(self.on_login_clicked)

        self.password_edit.returnPressed.connect(self.on_login_clicked)
    def setup_styles(self):
        """Setup dialog styles according to the active theme"""
        tc = self._tc
        bg = tc["bg"]
        surface = tc["surface"]
        text = tc["text"]
        text_secondary = tc["text_secondary"]
        input_bg = tc["input_bg"]
        input_border = tc["input_border"]
        input_focus = tc["input_focus"]
        login_btn = tc["login_btn"]
        login_btn_hover = tc["login_btn_hover"]
        login_btn_pressed = tc["login_btn_pressed"]
        border = tc["border"]

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {bg};
                border-radius: 12px;
            }}
            QLabel {{
                color: {text};
            }}
            QCheckBox {{
                color: {text};
            }}
            QLineEdit {{
                padding: 12px 16px;
                border: 2px solid {input_border};
                border-radius: 8px;
                font-size: 14px;
                background-color: {input_bg};
                color: {text};
                selection-background-color: {input_focus};
            }}
            QLineEdit:focus {{
                border-color: {input_focus};
                background-color: {surface};
            }}
            QLineEdit:disabled {{
                background-color: {border};
                color: {text_secondary};
            }}
            QPushButton {{
                background-color: {login_btn};
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {login_btn_hover};
            }}
            QPushButton:pressed {{
                background-color: {login_btn_pressed};
            }}
            QPushButton:disabled {{
                background-color: {border};
                color: {text_secondary};
            }}
        """)
    def on_login_clicked(self):
        """Manejador de click en botón de login con validación robusta"""

        email = self.email_edit.text().strip()

        password = self.password_edit.text()

        # Ocultar error previo

        self.error_label.hide()

        # Validación básica

        if not email or not password:
            self._show_error("Por favor, completa todos los campos.")

            return
        if not self._validate_email():
            self._show_error("Por favor, introduce tu ID de usuario o email.")

            return
        if len(password) < 6:
            self._show_error("La contraseña debe tener al menos 6 caracteres.")

            return
        # Verificar límite de intentos

        if self.validation_attempts >= self.max_attempts:
            self._show_error("Demasiados intentos fallidos. Por favor, espera antes de intentar de nuevo.")

            return
        # Configurar estado de validación

        self.is_validating = True

        self.validation_attempts += 1

        self._update_login_button_state()

        # Deshabilitar campos durante validación

        self.email_edit.setEnabled(False)

        self.password_edit.setEnabled(False)

        logger.info(f"Login attempt {self.validation_attempts} for user: {email}")

        # Emitir señal de login de forma asíncrona

        QTimer.singleShot(100, lambda: self.login_requested.emit(email, password))
    def on_register_clicked(self):
        """Handle register button click"""

        self.register_requested.emit()
    def on_forgot_password(self):
        """Handle forgot password link"""

        webbrowser.open("https://katphi.com/auth/recuperar")
    def _show_error(self, message):
        """Mostrar error al usuario en el propio diálogo"""

        self.error_label.setText(message)

        self.error_label.show()

        logger.warning(f"Login error: {message}")
    def _show_success(self, message):
        """Mostrar mensaje de éxito"""

        QMessageBox.information(self, "Éxito", message)

        logger.info(f"Login success: {message}")
    def on_login_success(self):
        """Manejador de login exitoso"""

        # NO mostrar QMessageBox aquí - se muestra en ui.py

        # El diálogo se cierra automáticamente por la señal login_successful

        logger.info("Login successful")

        self.accept()
    def on_login_failed(self, error_message):
        """Manejador de login fallido"""

        # Error se muestra en ui.py, aquí solo reseteamos el formulario

        logger.warning(f"Login failed: {error_message}")

        self._reset_form()
    def handle_login_result(self, success: bool, message: str = ""):
        """Manejar resultado del login de forma asíncrona"""

        # Rehabilitar campos

        self.email_edit.setEnabled(True)

        self.password_edit.setEnabled(True)

        self.is_validating = False

        self._update_login_button_state()

        if success:
            # NO mostrar QMessageBox aquí - se muestra en ui.py

            # El diálogo se cierra automáticamente por la señal login_successful

            logger.info("Login successful, dialog will close automatically")
        else:
            # Solo resetear el formulario, el error se muestra en ui.py

            logger.warning(f"Login failed: {message}")

            # Resetear intentos si es un error de usuario no verificado

            if "no verificado" in message.lower() or "not verified" in message.lower():
                self.validation_attempts = 0

                logger.info("User not verified - resetting attempt counter")
    def _reset_form(self):
        """Resetear formulario después de error"""

        self.is_validating = False

        self.email_edit.setEnabled(True)

        self.password_edit.setEnabled(True)

        self.password_edit.clear()

        self._update_login_button_state()

        # Resetear intentos después de un tiempo

        if self.validation_attempts >= self.max_attempts:
            QTimer.singleShot(300000, self._reset_attempts)  # 5 minutos
    def _reset_attempts(self):
        """Resetear contador de intentos"""

        self.validation_attempts = 0

        logger.info("Login attempts counter reset")
    def reset_login_button(self):
        """Reset login button state"""

        self._reset_form()
    def clear_fields(self):
        """Clear form fields"""

        self.email_edit.clear()

        self.password_edit.clear()

        self._clear_field_error(self.email_edit)

        self._clear_field_error(self.password_edit)

        self.error_label.hide()
    def show_error_in_dialog(self, error_message):
        """Mostrar error directamente en el diálogo (llamado desde ui.py)"""

        self.error_label.setText(error_message)

        self.error_label.show()

        # Rehabilitar campos para reintentar

        self.email_edit.setEnabled(True)

        self.password_edit.setEnabled(True)

        self.is_validating = False

        self._update_login_button_state()


class AccountInfoWidget(QWidget):
    """Widget showing account information and plugin licenses"""

    logout_requested = Signal()

    manage_account_requested = Signal()

    def __init__(self, auth_manager: AuthManager, parent=None):
        super().__init__(parent)

        self.auth_manager = auth_manager

        self.setup_ui()

        self.update_info()
    def setup_ui(self):
        layout = QVBoxLayout(self)

        layout.setSpacing(15)

        # User info section

        user_group = QGroupBox("Información de Cuenta")

        user_layout = QVBoxLayout()

        self.user_email_label = QLabel()

        self.user_email_label.setFont(QFont("Arial", 12, QFont.Bold))

        self.user_email_label.setStyleSheet("color: #2c3e50;")
        user_layout.addWidget(self.user_email_label)

        self.user_id_label = QLabel()

        self.user_id_label.setStyleSheet("color: #7f8c8d; font-size: 11px;")
        user_layout.addWidget(self.user_id_label)

        user_group.setLayout(user_layout)

        layout.addWidget(user_group)

        # Plugin licenses section

        licenses_group = QGroupBox("Plugins Premium")

        licenses_layout = QVBoxLayout()

        self.licenses_list = QListWidget()

        self.licenses_list.setStyleSheet("""

            QListWidget {

                border: 1px solid #ecf0f1;

                border-radius: 5px;

                background-color: white;
            }

            QListWidget::item {

                padding: 10px;

                border-bottom: 1px solid #ecf0f1;
            }

            QListWidget::item:last-child {

                border-bottom: none;
            }
        """)

        licenses_layout.addWidget(self.licenses_list)

        licenses_group.setLayout(licenses_layout)

        layout.addWidget(licenses_group)

        # Buttons

        button_layout = QVBoxLayout()

        button_layout.setSpacing(10)

        # Manage account button

        self.manage_button = QPushButton("Gestionar Cuenta")

        self.manage_button.setStyleSheet("""

            QPushButton {

                background-color: #3498db;
                color: white;

                border: none;

                padding: 10px;

                border-radius: 5px;

                font-size: 14px;
            }

            QPushButton:hover {

                background-color: #2980b9;
            }
        """)

        self.manage_button.clicked.connect(self.on_manage_account)

        button_layout.addWidget(self.manage_button)

        # Logout button

        self.logout_button = QPushButton("Cerrar Sesión")

        self.logout_button.setStyleSheet("""

            QPushButton {

                background-color: #e74c3c;
                color: white;

                border: none;

                padding: 10px;

                border-radius: 5px;

                font-size: 14px;
            }

            QPushButton:hover {

                background-color: #c0392b;
            }
        """)

        self.logout_button.clicked.connect(self.on_logout)

        button_layout.addWidget(self.logout_button)

        layout.addLayout(button_layout)
    def update_info(self):
        """Update account information display"""

        if not self.auth_manager:
            return
        user_info = self.auth_manager.get_user_info()

        if not user_info:
            return
        # Update user info

        self.user_email_label.setText(f"{user_info['email']}")

        self.user_id_label.setText(f"ID: {user_info['user_id']}")

        # Update plugin licenses

        self.licenses_list.clear()

        licensed_plugins = self.auth_manager.get_licensed_plugins()

        if licensed_plugins:
            for plugin_id in licensed_plugins:
                license_info = self.auth_manager.get_plugin_license(plugin_id)

                if license_info:
                    item = QListWidgetItem()

                    item.setText(f"{license_info.plugin_name}")

                    item.setToolTip(f"Plugin ID: {plugin_id}\nDispositivos: {license_info.current_devices}/{license_info.device_limit}")

                    self.licenses_list.addItem(item)
        else:
            item = QListWidgetItem()

            item.setText("No tienes plugins premium activos")

            # QListWidgetItem doesn't support setStyleSheet, use setForeground instead

            from PySide6.QtGui import QColor

            item.setForeground(QColor("#7f8c8d"))

            self.licenses_list.addItem(item)
    def on_manage_account(self):
        """Handle manage account button"""

        webbrowser.open("https://katphi.com/app/dashboard")

        self.manage_account_requested.emit()
    def on_logout(self):
        """Handle logout button"""

        reply = QMessageBox.question(

            self, "Cerrar Sesión",

            "¿Estás seguro de que quieres cerrar sesión?",

            QMessageBox.Yes | QMessageBox.No,

            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.logout_requested.emit()


class AuthPanel(BasePanel):
    """Panel de autenticación principal con validación robusta"""

    def __init__(self, auth_manager: AuthManager, parent=None):
        self.auth_manager = auth_manager

        super().__init__(parent)

        # Diccionario para trackear conexiones de señales y prevenir memory leaks
        self._signal_connections = {}

        # Conectar señales del auth manager y guardar referencias
        auth_manager_id = id(self.auth_manager)
        self._signal_connections[auth_manager_id] = {}

        self._signal_connections[auth_manager_id]['auth_state_changed'] = self.on_auth_state_changed
        self.auth_manager.auth_state_changed.connect(self.on_auth_state_changed)

        self._signal_connections[auth_manager_id]['login_successful'] = self.on_login_successful
        self.auth_manager.login_successful.connect(self.on_login_successful)

        self._signal_connections[auth_manager_id]['login_failed'] = self.on_login_failed
        self.auth_manager.login_failed.connect(self.on_login_failed)

        self._signal_connections[auth_manager_id]['logout_successful'] = self.on_logout_successful
        self.auth_manager.logout_successful.connect(self.on_logout_successful)

        self._signal_connections[auth_manager_id]['plugin_license_changed'] = self.on_plugin_license_changed
        self.auth_manager.plugin_license_changed.connect(self.on_plugin_license_changed)

        self._signal_connections[auth_manager_id]['connection_status_changed'] = self.on_connection_status_changed
        self.auth_manager.connection_status_changed.connect(self.on_connection_status_changed)

        # Timer para actualización de estado

        self.status_timer = QTimer()

        status_timer_connection = self.update_status
        self.status_timer.timeout.connect(status_timer_connection)
        self._signal_connections['status_timer'] = status_timer_connection

        self.status_timer.start(5000)  # Cada 5 segundos

        # setup_ui() ya fue invocado por BasePanel.__init__ → no repetir

        self.update_display()

        self.update_status()
    def setup_ui(self):
        """Setup the authentication panel UI"""

        layout = QVBoxLayout(self)

        layout.setContentsMargins(20, 20, 20, 20)

        layout.setSpacing(20)

        # Header

        header_layout = QHBoxLayout()

        title_label = QLabel("Autenticación")

        title_label.setFont(QFont("Arial", 16, QFont.Bold))

        title_label.setStyleSheet("color: #2c3e50;")
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        # Status indicator

        self.status_label = QLabel("Sin conexión")

        self.status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
        header_layout.addWidget(self.status_label)

        layout.addLayout(header_layout)

        # Main content area

        self.content_stack = QStackedWidget()

        # Login page

        self.login_widget = self.create_login_widget()

        self.content_stack.addWidget(self.login_widget)

        # Account info page

        self.account_widget = AccountInfoWidget(self.auth_manager)

        self.account_widget.logout_requested.connect(self.auth_manager.logout)

        self.content_stack.addWidget(self.account_widget)

        layout.addWidget(self.content_stack)

        # Validation info

        validation_group = QGroupBox("Estado de Validación")

        validation_layout = QVBoxLayout()

        self.validation_status = QLabel("Última validación: Nunca")

        self.validation_status.setStyleSheet("color: #7f8c8d; font-size: 12px;")
        validation_layout.addWidget(self.validation_status)

        # Force validation button

        self.validate_button = QPushButton("Validar Ahora")

        self.validate_button.setStyleSheet("""

            QPushButton {

                background-color: #27ae60;
                color: white;

                border: none;

                padding: 8px;

                border-radius: 5px;

                font-size: 12px;
            }

            QPushButton:hover {

                background-color: #229954;
            }
        """)

        self.validate_button.clicked.connect(self.auth_manager.force_validation)

        validation_layout.addWidget(self.validate_button)

        validation_group.setLayout(validation_layout)

        layout.addWidget(validation_group)
    def create_login_widget(self) -> QWidget:
        """Create the login widget - solo información, el botón está en la toolbar"""

        widget = QWidget()

        layout = QVBoxLayout(widget)

        layout.setAlignment(Qt.AlignCenter)

        layout.setContentsMargins(20, 20, 20, 20)

        # Ícono de cuenta

        icon_label = QLabel()
        try:
            from ui.core.strip_icons import build_nav_icon
            from PySide6.QtCore import QSize
            icon_label.setPixmap(build_nav_icon("account", None, QSize(64, 64)).pixmap(64, 64))
        except Exception:
            pass

        icon_label.setAlignment(Qt.AlignCenter)

        icon_label.setStyleSheet("font-size: 64px; margin-bottom: 20px;")

        layout.addWidget(icon_label)

        # Título

        title_label = QLabel("No has iniciado sesión")

        title_label.setAlignment(Qt.AlignCenter)

        title_label.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 10px;")

        layout.addWidget(title_label)

        # Info text

        info_label = QLabel(

            "Para acceder a plugins premium y funciones avanzadas,\n"

            "haz clic en el botón de cuenta () en la barra superior."
        )

        info_label.setAlignment(Qt.AlignCenter)

        info_label.setWordWrap(True)

        info_label.setStyleSheet("color: #7f8c8d; font-size: 14px; margin-top: 10px;")
        layout.addWidget(info_label)

        layout.addStretch()

        return widget
    # MÉTODOS DE LOGIN ELIMINADOS - El login se maneja desde ui.py con el botón de la toolbar

    # Ya no necesitamos duplicar la funcionalidad de login aquí

    def on_auth_state_changed(self, is_authenticated: bool):
        """Handle authentication state change"""

        self.update_display()
    def on_login_successful(self, credentials: UserCredentials):
        """Handle successful login"""

        logger.info(f"Login successful for: {credentials.email}")

        self.update_display()

        # NO mostrar QMessageBox aquí - se muestra en ui.py
    def on_login_failed(self, error_message: str):
        """Manejador de login fallido con feedback detallado"""

        logger.warning(f"Login failed: {error_message}")

        self.update_display()

        # NO mostrar QMessageBox aquí - se muestra en ui.py
    def on_logout_successful(self):
        """Manejador de logout exitoso"""

        logger.info("User logged out successfully")

        self.update_display()

        QMessageBox.information(self, "Sesión Cerrada", "Has cerrado sesión correctamente.")
    def on_plugin_license_changed(self, plugin_id: str, is_licensed: bool):
        """Manejador de cambio de licencia de plugin"""

        logger.info(f"Plugin {plugin_id} license changed: {is_licensed}")

        self.update_display()
    def on_connection_status_changed(self, is_connected: bool):
        """Manejador de cambio de estado de conexión"""

        status_text = "Conectado" if is_connected else "Sin conexión"

        status_color = "#27ae60" if is_connected else "#e74c3c"

        self.status_label.setText(status_text)

        self.status_label.setStyleSheet(f"color: {status_color}; font-weight: bold;")

        logger.info(f"Connection status changed: {is_connected}")
    def update_status(self):
        """Actualizar estado de la conexión y autenticación"""

        if self.auth_manager:
            auth_status = self.auth_manager.get_auth_status()

            # Actualizar estado de conexión

            is_connected = auth_status.get("is_connected", False)

            is_authenticated = auth_status.get("is_authenticated", False)

            if is_authenticated:
                status_text = "Autenticado"

                status_color = "#27ae60"
            elif is_connected:
                status_text = "Conectado (No autenticado)"

                status_color = "#f39c12"
            else:
                status_text = "Sin conexión"

                status_color = "#e74c3c"
            self.status_label.setText(status_text)

            self.status_label.setStyleSheet(f"color: {status_color}; font-weight: bold;")
    def update_display(self):
        """Actualizar la pantalla basada en el estado de autenticación actual"""

        if not self.auth_manager:
            return
        is_authenticated = self.auth_manager.auth_state.is_authenticated

        if is_authenticated:
            self.content_stack.setCurrentWidget(self.account_widget)

            self.account_widget.update_info()
        else:
            self.content_stack.setCurrentWidget(self.login_widget)
        # Actualizar estado de validación

        if is_authenticated and self.auth_manager.auth_state.last_validation > 0:
            from datetime import datetime

            last_validation = datetime.fromtimestamp(self.auth_manager.auth_state.last_validation)

            self.validation_status.setText(f"Última validación: {last_validation.strftime('%H:%M:%S')}")
        else:
            self.validation_status.setText("Última validación: Nunca")
    def _disconnect_signals(self):
        """Desconectar todas las señales para prevenir memory leaks"""
        try:
            # Desconectar señales del auth_manager
            auth_manager_id = id(self.auth_manager)
            if auth_manager_id in self._signal_connections:
                connections = self._signal_connections[auth_manager_id]

                try:
                    if 'auth_state_changed' in connections:
                        self.auth_manager.auth_state_changed.disconnect(connections['auth_state_changed'])
                except:
                    pass
                try:
                    if 'login_successful' in connections:
                        self.auth_manager.login_successful.disconnect(connections['login_successful'])
                except:
                    pass
                try:
                    if 'login_failed' in connections:
                        self.auth_manager.login_failed.disconnect(connections['login_failed'])
                except:
                    pass
                try:
                    if 'logout_successful' in connections:
                        self.auth_manager.logout_successful.disconnect(connections['logout_successful'])
                except:
                    pass
                try:
                    if 'plugin_license_changed' in connections:
                        self.auth_manager.plugin_license_changed.disconnect(connections['plugin_license_changed'])
                except:
                    pass
                try:
                    if 'connection_status_changed' in connections:
                        self.auth_manager.connection_status_changed.disconnect(connections['connection_status_changed'])
                except:
                    pass
                del self._signal_connections[auth_manager_id]
            # Desconectar timer
            try:
                if 'status_timer' in self._signal_connections:
                    self.status_timer.timeout.disconnect(self._signal_connections['status_timer'])
                    del self._signal_connections['status_timer']
            except:
                pass
            # Detener timer
            if hasattr(self, 'status_timer') and self.status_timer:
                self.status_timer.stop()
        except Exception as e:
            print(f"Error al desconectar señales del AuthPanel: {str(e)}")
    def closeEvent(self, event):
        """Manejar cierre del panel"""
        self._disconnect_signals()
        super().closeEvent(event)
    def __del__(self):
        """Destructor del panel"""
        self._disconnect_signals()
