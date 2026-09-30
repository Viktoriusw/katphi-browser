#!/usr/bin/env python3
"""
Network Interceptor - Sistema avanzado de interceptación de peticiones HTTP

Características:
- Interceptar y modificar peticiones HTTP/HTTPS
- Cambiar User-Agent dinámicamente
- Bloquear URLs con patrones (regex, wildcards)
- Modificar headers (DNT, Referer, etc.)
- Logging de peticiones
- Configuración persistente en SQLite
"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QComboBox, QCheckBox, QListWidget, QLineEdit,
                               QGroupBox, QTextEdit, QMessageBox, QTabWidget, QWidget,
                               QListWidgetItem, QSpinBox, QTableWidget, QTableWidgetItem,
                               QHeaderView, QDialogButtonBox)
from PySide6.QtCore import QObject, Signal, QUrl, Qt, QStandardPaths
from PySide6.QtWebEngineCore import QWebEngineUrlRequestInterceptor, QWebEngineUrlRequestInfo
import sqlite3
import os
import re
from datetime import datetime
from pathlib import Path


class NetworkInterceptor(QWebEngineUrlRequestInterceptor):
    """Interceptor de peticiones de red"""

    # Señales
    request_intercepted = Signal(str, str)  # URL, método
    request_blocked = Signal(str)  # URL bloqueada

    # User-Agents predefinidos
    USER_AGENTS = {
        'Chrome': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
        'Firefox': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0',
        'Brave': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Brave/136',
        'Safari': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Safari/605.1.15',
        'Edge': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0',
        'Android': 'Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.6478.122 Mobile Safari/537.36',
        'iOS': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Mobile/15E148 Safari/604.1',
        'Custom': ''
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.tor_mode = False

        # Configuración
        self.config_db = self._get_config_db_path()
        self._init_database()

        # Cargar configuración
        self.load_configuration()

        # Estado
        self.request_count = 0
        self.blocked_count = 0
        self.request_log = []
        self.max_log_size = 1000
    def _get_config_db_path(self):
        """Obtiene la ruta de la base de datos de configuración"""
        app_data = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        config_dir = os.path.join(app_data, "Katphi", "Network")
        os.makedirs(config_dir, exist_ok=True)
        return os.path.join(config_dir, "network_config.db")
    def _init_database(self):
        """Inicializa la base de datos de configuración"""
        conn = sqlite3.connect(self.config_db)
        cursor = conn.cursor()

        # Tabla de configuración
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')

        # Tabla de URLs bloqueadas
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS blocked_urls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern TEXT UNIQUE,
                type TEXT,
                enabled INTEGER DEFAULT 1,
                created_at TEXT
            )
        ''')

        # Tabla de headers personalizados
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS custom_headers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                value TEXT,
                enabled INTEGER DEFAULT 1
            )
        ''')

        # Tabla de log de peticiones (opcional, para debugging)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS request_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT,
                method TEXT,
                timestamp TEXT,
                blocked INTEGER DEFAULT 0
            )
        ''')

        conn.commit()
        conn.close()
    def load_configuration(self):
        """Cargar configuración desde la base de datos"""
        conn = sqlite3.connect(self.config_db)
        cursor = conn.cursor()

        # Cargar User-Agent
        cursor.execute("SELECT value FROM config WHERE key = 'user_agent_type'")
        row = cursor.fetchone()
        self.user_agent_type = row[0] if row else 'Chrome'

        cursor.execute("SELECT value FROM config WHERE key = 'custom_user_agent'")
        row = cursor.fetchone()
        self.custom_user_agent = row[0] if row else ''

        # Cargar opciones de headers
        cursor.execute("SELECT value FROM config WHERE key = 'enable_dnt'")
        row = cursor.fetchone()
        self.enable_dnt = row[0] == '1' if row else True

        cursor.execute("SELECT value FROM config WHERE key = 'block_referer'")
        row = cursor.fetchone()
        self.block_referer = row[0] == '1' if row else False

        cursor.execute("SELECT value FROM config WHERE key = 'enable_logging'")
        row = cursor.fetchone()
        self.enable_logging = row[0] == '1' if row else False

        # Cargar URLs bloqueadas
        cursor.execute("SELECT pattern, type FROM blocked_urls WHERE enabled = 1")
        self.blocked_patterns = []
        for pattern, pattern_type in cursor.fetchall():
            self.blocked_patterns.append({
                'pattern': pattern,
                'type': pattern_type,
                'compiled': self._compile_pattern(pattern, pattern_type)
            })
        # Cargar headers personalizados
        cursor.execute("SELECT name, value FROM custom_headers WHERE enabled = 1")
        self.custom_headers = {name: value for name, value in cursor.fetchall()}

        conn.close()
    def _compile_pattern(self, pattern, pattern_type):
        """Compilar patrón según el tipo"""
        try:
            if pattern_type == 'regex':
                return re.compile(pattern)
            elif pattern_type == 'wildcard':
                # Convertir wildcard a regex
                regex_pattern = pattern.replace('.', r'\.')
                regex_pattern = regex_pattern.replace('*', '.*')
                regex_pattern = regex_pattern.replace('?', '.')
                return re.compile(regex_pattern)
            else:  # exact
                return pattern
        except Exception as e:
            print(f"[WARNING] Error compiling pattern '{pattern}': {e}")
            return None
    def save_configuration(self):
        """Guardar configuración en la base de datos"""
        conn = sqlite3.connect(self.config_db)
        cursor = conn.cursor()

        # Guardar configuración básica
        config_items = [
            ('user_agent_type', self.user_agent_type),
            ('custom_user_agent', self.custom_user_agent),
            ('enable_dnt', '1' if self.enable_dnt else '0'),
            ('block_referer', '1' if self.block_referer else '0'),
            ('enable_logging', '1' if self.enable_logging else '0')
        ]

        for key, value in config_items:
            cursor.execute('''
                INSERT OR REPLACE INTO config (key, value)
                VALUES (?, ?)
            ''', (key, value))
        conn.commit()
        conn.close()
    def interceptRequest(self, info: QWebEngineUrlRequestInfo):
        """
        Interceptar y modificar peticiones HTTP

        Args:
            info: Información de la petición
        """
        # Bloqueo WebRTC en modo Tor
        if getattr(self, 'tor_mode', False):
            url = info.requestUrl().toString()
            if any(p in url for p in ('stun:', 'turn:', 'stuns:', 'turns:')):
                info.block(True)
                return
        url = info.requestUrl().toString()
        method = info.requestMethod().data().decode('utf-8')

        # Incrementar contador
        self.request_count += 1

        # Verificar si la URL debe ser bloqueada
        if self._should_block_url(url):
            info.block(True)
            self.blocked_count += 1
            self.request_blocked.emit(url)

            if self.enable_logging:
                self._log_request(url, method, blocked=True)
            print(f"[BLOCKED] {method} {url}")
            return
        # Modificar User-Agent
        user_agent = self._get_user_agent()
        if user_agent:
            info.setHttpHeader(b'User-Agent', user_agent.encode('utf-8'))
            # Debug: mostrar solo para la primera petición de cada página
            if 'text/html' in url or self.request_count % 100 == 1:
                print(f"[UA] Applying User-Agent ({self.user_agent_type}): {user_agent[:80]}...")
        # Agregar/modificar headers
        if self.enable_dnt:
            info.setHttpHeader(b'DNT', b'1')
        # No bloquear Referer en peticiones de medios: CDNs de vídeo (phncdn, etc.)
        # requieren Referer para servir contenido; si se elimina → 403 → MediaError UNKNOWN_ERROR
        if self.block_referer:
            try:
                rt = info.resourceType()
                media_type = getattr(
                    QWebEngineUrlRequestInfo.ResourceType, 'ResourceTypeMedia',
                    getattr(QWebEngineUrlRequestInfo.ResourceType, 'Media', None)
                )
                xhr_type = getattr(
                    QWebEngineUrlRequestInfo.ResourceType, 'ResourceTypeXmlHttpRequest',
                    getattr(QWebEngineUrlRequestInfo.ResourceType, 'XmlHttpRequest', None)
                )
                is_media = media_type and rt == media_type
                is_media_xhr = xhr_type and rt == xhr_type and self._is_media_url(url)
                if not (is_media or is_media_xhr):
                    info.setHttpHeader(b'Referer', b'')
            except Exception:
                info.setHttpHeader(b'Referer', b'')
        # Headers personalizados
        for header_name, header_value in self.custom_headers.items():
            info.setHttpHeader(header_name.encode('utf-8'), header_value.encode('utf-8'))
        # Logging
        if self.enable_logging:
            self._log_request(url, method, blocked=False)
        # Emitir señal
        self.request_intercepted.emit(url, method)
    def _is_media_url(self, url: str) -> bool:
        """Indica si la URL parece ser de contenido multimedia (vídeo/audio)."""
        url_lower = url.lower()
        media_ext = ('.mp4', '.m3u8', '.ts', '.webm', '.mpd', '.m4s', '.m4a', '.mp3', '.ogg', '.flv')
        media_hints = (
            'phncdn', 'googlevideo', '/video/', '/media/', '/stream/', 'cloudfront',
            'akamaized', 'akamai', 'fastly.net', 'vimeocdn', 'vod.vimeo',
            'jtvnw.net', 'twitchsvc', 'twitchusercontent',
            'tiktokcdn', 'muscdn.com', 'tiktok.com/video',
            'video.twimg', 'twimg.com/ext_tw',
            'nflxvideo', 'nflximg',
            'brightcove.net', 'jwpltx', 'jwplatform',
            'fbcdn.net', 'cdninstagram', 'fbsbx.com',
            'dailymotionakam', 'dmcdn.net',
            'b-cdn.net', 'bunnycdn',
            'amazonaws.com/video', 'amazonaws.com/media',
        )
        return any(ext in url_lower for ext in media_ext) or any(h in url_lower for h in media_hints)
    def _should_block_url(self, url):
        """Verificar si una URL debe ser bloqueada"""

        # WHITELIST: Dominios críticos que NUNCA deben bloquearse
        WHITELIST_DOMAINS = [
            'google.com',
            'gstatic.com',
            'googleapis.com',
            'recaptcha.net',
            'googleusercontent.com',
            'phncdn.com',
            'challenges.cloudflare.com',
            'cloudflare.com',
            'cloudflareinsights.com',
            # CDNs de vídeo — necesarios para reproducción en sitios distintos de YouTube
            'googlevideo.com',
            'akamaized.net',
            'akamaihd.net',
            'akamaistream.net',
            'fastly.net',
            'vimeocdn.com',
            'vimeo.com',
            'jtvnw.net',
            'twitchsvc.net',
            'twitchusercontent.com',
            'tiktokcdn.com',
            'muscdn.com',
            'video.twimg.com',
            'nflxvideo.net',
            'nflximg.net',
            'brightcove.net',
            'jwplatform.com',
            'jwpsrv.com',
            'fbcdn.net',
            'cdninstagram.com',
            'fbsbx.com',
            'dailymotionakam.com',
            'dmcdn.net',
            'b-cdn.net',
            'bunnycdn.com',
        ]

        # Verificar si la URL pertenece a un dominio en whitelist
        for domain in WHITELIST_DOMAINS:
            if domain in url:
                return False  # NO bloquear - dominio en whitelist
        # Continuar con la lógica de bloqueo normal
        for pattern_info in self.blocked_patterns:
            pattern = pattern_info['compiled']
            pattern_type = pattern_info['type']

            if pattern is None:
                continue
            try:
                if pattern_type == 'exact':
                    if url == pattern:
                        return True
                else:  # regex or wildcard (ambos compilados como regex)
                    if pattern.search(url):
                        return True
            except Exception as e:
                print(f"[WARNING] Error matching pattern: {e}")
                continue
        return False
    def _get_user_agent(self):
        """Obtener el User-Agent configurado"""
        if self.user_agent_type == 'Custom':
            return self.custom_user_agent if self.custom_user_agent else self.USER_AGENTS['Chrome']
        else:
            return self.USER_AGENTS.get(self.user_agent_type, self.USER_AGENTS['Chrome'])
    def _log_request(self, url, method, blocked=False):
        """Registrar petición en el log"""
        log_entry = {
            'url': url,
            'method': method,
            'timestamp': datetime.now().isoformat(),
            'blocked': blocked
        }

        self.request_log.append(log_entry)

        # Limitar tamaño del log en memoria
        if len(self.request_log) > self.max_log_size:
            self.request_log = self.request_log[-self.max_log_size:]
        # Opcionalmente guardar en base de datos
        # (desactivado por defecto para no llenar la BD)
        # self._save_log_to_db(log_entry)
    def _save_log_to_db(self, log_entry):
        """Guardar entrada de log en la base de datos"""
        try:
            conn = sqlite3.connect(self.config_db)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT INTO request_log (url, method, timestamp, blocked)
                VALUES (?, ?, ?, ?)
            ''', (log_entry['url'], log_entry['method'], log_entry['timestamp'],
                  1 if log_entry['blocked'] else 0))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[WARNING] Error saving log to database: {e}")
    def add_blocked_pattern(self, pattern, pattern_type='wildcard'):
        """Agregar patrón de bloqueo"""
        try:
            conn = sqlite3.connect(self.config_db)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT OR REPLACE INTO blocked_urls (pattern, type, enabled, created_at)
                VALUES (?, ?, 1, ?)
            ''', (pattern, pattern_type, datetime.now().isoformat()))

            conn.commit()
            conn.close()

            # Recargar configuración
            self.load_configuration()
            return True
        except Exception as e:
            print(f"[ERROR] Error adding blocked pattern: {e}")
            return False
    def remove_blocked_pattern(self, pattern):
        """Eliminar patrón de bloqueo"""
        try:
            conn = sqlite3.connect(self.config_db)
            cursor = conn.cursor()

            cursor.execute('DELETE FROM blocked_urls WHERE pattern = ?', (pattern,))

            conn.commit()
            conn.close()

            # Recargar configuración
            self.load_configuration()
            return True
        except Exception as e:
            print(f"[ERROR] Error removing blocked pattern: {e}")
            return False
    def get_blocked_patterns(self):
        """Obtener lista de patrones bloqueados"""
        conn = sqlite3.connect(self.config_db)
        cursor = conn.cursor()

        cursor.execute("SELECT pattern, type, enabled FROM blocked_urls ORDER BY created_at DESC")
        patterns = [{'pattern': p, 'type': t, 'enabled': bool(e)}
                   for p, t, e in cursor.fetchall()]
        conn.close()
        return patterns
    def get_stats(self):
        """Obtener estadísticas del interceptor"""
        return {
            'total_requests': self.request_count,
            'blocked_requests': self.blocked_count,
            'blocked_percentage': (self.blocked_count / self.request_count * 100) if self.request_count > 0 else 0,
            'user_agent': self.user_agent_type,
            'patterns_count': len(self.blocked_patterns)
        }
    def clear_log(self):
        """Limpiar log de peticiones"""
        self.request_log = []
    def reset_stats(self):
        """Resetear estadísticas"""
        self.request_count = 0
        self.blocked_count = 0


class NetworkSettingsDialog(QDialog):
    """Diálogo de configuración de red e interceptación"""

    def __init__(self, network_interceptor, parent=None):
        super().__init__(parent)
        self.interceptor = network_interceptor

        self.setWindowTitle("Configuración de Red")
        self.setModal(True)
        self.setMinimumSize(700, 500)

        self.setup_ui()
        self.load_current_settings()
    def setup_ui(self):
        """Configurar interfaz del diálogo"""
        layout = QVBoxLayout(self)

        # Título
        title = QLabel("Configuración de Red e Interceptación")
        title.setStyleSheet("font-size: 16px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)

        # Tabs para organizar configuración
        tabs = QTabWidget()

        # Tab 1: User-Agent
        ua_tab = self.create_user_agent_tab()
        tabs.addTab(ua_tab, "User-Agent")

        # Tab 2: Bloqueo de URLs
        block_tab = self.create_blocking_tab()
        tabs.addTab(block_tab, "Bloqueo de URLs")

        # Tab 3: Headers
        headers_tab = self.create_headers_tab()
        tabs.addTab(headers_tab, "Headers HTTP")

        # Tab 4: Estadísticas
        stats_tab = self.create_stats_tab()
        tabs.addTab(stats_tab, "Estadísticas")

        layout.addWidget(tabs)

        # Botones
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply
        )
        buttons.accepted.connect(self.accept_settings)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self.apply_settings)
        layout.addWidget(buttons)
    def create_user_agent_tab(self):
        """Crear tab de configuración de User-Agent"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Selector de User-Agent
        ua_group = QGroupBox("Seleccionar User-Agent")
        ua_layout = QVBoxLayout()

        self.ua_combo = QComboBox()
        self.ua_combo.addItems([
            'Chrome (Windows)',
            'Firefox (Windows)',
            'Brave (Windows)',
            'Safari (macOS)',
            'Edge (Windows)',
            'Android (Mobile)',
            'iOS (iPhone)',
            'Custom (Personalizado)'
        ])
        self.ua_combo.currentTextChanged.connect(self.on_ua_changed)
        ua_layout.addWidget(QLabel("User-Agent predefinido:"))
        ua_layout.addWidget(self.ua_combo)

        # User-Agent ACTIVO en el navegador (el que se está usando ahora)
        ua_layout.addWidget(QLabel("\nUser-Agent ACTIVO (en uso ahora):"))
        self.ua_active = QTextEdit()
        self.ua_active.setReadOnly(True)
        self.ua_active.setMaximumHeight(60)
        self.ua_active.setStyleSheet("background-color: #e8f5e9; font-family: monospace; font-size: 10px; border: 2px solid #4caf50;")
        ua_layout.addWidget(self.ua_active)

        # Preview del User-Agent seleccionado (el que se aplicará)
        ua_layout.addWidget(QLabel("\nPreview del User-Agent seleccionado:"))
        self.ua_preview = QTextEdit()
        self.ua_preview.setReadOnly(True)
        self.ua_preview.setMaximumHeight(60)
        self.ua_preview.setStyleSheet("background-color: #fff3e0; font-family: monospace; font-size: 10px; border: 2px solid #ff9800;")
        ua_layout.addWidget(self.ua_preview)

        # Custom User-Agent
        self.custom_ua_input = QLineEdit()
        self.custom_ua_input.setPlaceholderText("Ingresa un User-Agent personalizado...")
        self.custom_ua_input.setEnabled(False)
        self.custom_ua_input.textChanged.connect(self.update_ua_preview)
        ua_layout.addWidget(QLabel("\nUser-Agent personalizado:"))
        ua_layout.addWidget(self.custom_ua_input)

        ua_group.setLayout(ua_layout)
        layout.addWidget(ua_group)

        # Info
        info_label = QLabel(
            "Tip: Cambiar el User-Agent puede ayudar a acceder a sitios que bloquean "
            "ciertos navegadores o para testing de compatibilidad."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #666; font-size: 11px; margin-top: 10px;")
        layout.addWidget(info_label)

        layout.addStretch()
        return widget
    def create_blocking_tab(self):
        """Crear tab de bloqueo de URLs"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Lista de URLs bloqueadas
        block_group = QGroupBox("URLs y Patrones Bloqueados")
        block_layout = QVBoxLayout()

        self.blocked_list = QListWidget()
        self.blocked_list.setSelectionMode(QListWidget.SingleSelection)
        block_layout.addWidget(self.blocked_list)

        # Botones de gestión
        btn_layout = QHBoxLayout()

        add_btn = QPushButton("Agregar")
        add_btn.clicked.connect(self.add_block_pattern)
        btn_layout.addWidget(add_btn)

        remove_btn = QPushButton("Eliminar")
        remove_btn.clicked.connect(self.remove_block_pattern)
        btn_layout.addWidget(remove_btn)

        btn_layout.addStretch()

        block_layout.addLayout(btn_layout)
        block_group.setLayout(block_layout)
        layout.addWidget(block_group)

        # Tipo de patrón
        pattern_group = QGroupBox("Agregar Nuevo Patrón")
        pattern_layout = QVBoxLayout()

        self.pattern_input = QLineEdit()
        self.pattern_input.setPlaceholderText("Ej: *.doubleclick.net o https://ads.example.com/*")
        pattern_layout.addWidget(QLabel("Patrón o URL:"))
        pattern_layout.addWidget(self.pattern_input)

        self.pattern_type_combo = QComboBox()
        self.pattern_type_combo.addItems(['Wildcard (* y ?)', 'Regex (Expresión regular)', 'Exacta'])
        pattern_layout.addWidget(QLabel("Tipo de patrón:"))
        pattern_layout.addWidget(self.pattern_type_combo)

        quick_add_btn = QPushButton("Agregar Patrón")
        quick_add_btn.clicked.connect(self.quick_add_pattern)
        pattern_layout.addWidget(quick_add_btn)

        pattern_group.setLayout(pattern_layout)
        layout.addWidget(pattern_group)

        # Ejemplos
        examples_label = QLabel(
            "Ejemplos:\n"
            "• Wildcard: *.ads.com, *tracker*, https://example.com/ads/*\n"
            "• Regex: ^https?://.*\\.ads\\..*$\n"
            "• Exacta: https://evil.com/malware.js"
        )
        examples_label.setWordWrap(True)
        examples_label.setStyleSheet("color: #666; font-size: 10px; margin-top: 10px; background-color: #f9f9f9; padding: 8px; border-radius: 4px;")
        layout.addWidget(examples_label)

        layout.addStretch()
        return widget
    def create_headers_tab(self):
        """Crear tab de configuración de headers"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Headers automáticos
        auto_group = QGroupBox("Headers Automáticos")
        auto_layout = QVBoxLayout()

        self.dnt_check = QCheckBox("Enviar header 'Do Not Track' (DNT: 1)")
        self.dnt_check.setChecked(True)
        auto_layout.addWidget(self.dnt_check)

        self.referer_check = QCheckBox("Bloquear Referer (privacidad)")
        auto_layout.addWidget(self.referer_check)

        auto_group.setLayout(auto_layout)
        layout.addWidget(auto_group)

        # Logging
        log_group = QGroupBox("Registro de Peticiones")
        log_layout = QVBoxLayout()

        self.logging_check = QCheckBox("Habilitar logging de peticiones HTTP (para debugging)")
        log_layout.addWidget(self.logging_check)

        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        layout.addStretch()
        return widget
    def create_stats_tab(self):
        """Crear tab de estadísticas"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Estadísticas
        stats_group = QGroupBox("Estadísticas de Interceptación")
        stats_layout = QVBoxLayout()

        self.stats_text = QTextEdit()
        self.stats_text.setReadOnly(True)
        self.stats_text.setMaximumHeight(200)
        stats_layout.addWidget(self.stats_text)

        # Botón para actualizar stats
        refresh_btn = QPushButton("Actualizar Estadísticas")
        refresh_btn.clicked.connect(self.update_stats)
        stats_layout.addWidget(refresh_btn)

        # Botón para resetear stats
        reset_btn = QPushButton("Resetear Estadísticas")
        reset_btn.clicked.connect(self.reset_stats)
        stats_layout.addWidget(reset_btn)

        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)

        layout.addStretch()
        return widget
    def load_current_settings(self):
        """Cargar configuración actual"""
        # User-Agent
        ua_type = self.interceptor.user_agent_type
        ua_map = {
            'Chrome': 0,
            'Firefox': 1,
            'Brave': 2,
            'Safari': 3,
            'Edge': 4,
            'Android': 5,
            'iOS': 6,
            'Custom': 7
        }
        self.ua_combo.setCurrentIndex(ua_map.get(ua_type, 0))

        if ua_type == 'Custom':
            self.custom_ua_input.setText(self.interceptor.custom_user_agent)
        # Mostrar User-Agent ACTIVO (el que está en uso ahora)
        active_ua = self.interceptor._get_user_agent()
        self.ua_active.setText(f"{active_ua}\n\n(Tipo: {ua_type})")

        # Headers
        self.dnt_check.setChecked(self.interceptor.enable_dnt)
        self.referer_check.setChecked(self.interceptor.block_referer)
        self.logging_check.setChecked(self.interceptor.enable_logging)

        # Patrones bloqueados
        self.refresh_blocked_list()

        # Estadísticas
        self.update_stats()

        # Update preview
        self.update_ua_preview()
    def refresh_blocked_list(self):
        """Refrescar lista de patrones bloqueados"""
        self.blocked_list.clear()
        patterns = self.interceptor.get_blocked_patterns()

        for pattern_info in patterns:
            pattern = pattern_info['pattern']
            pattern_type = pattern_info['type']
            item_text = f"{pattern} [{pattern_type}]"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, pattern)
            self.blocked_list.addItem(item)
    def on_ua_changed(self, text):
        """Cuando cambia la selección de User-Agent"""
        is_custom = 'Custom' in text
        self.custom_ua_input.setEnabled(is_custom)
        self.update_ua_preview()
    def update_ua_preview(self):
        """Actualizar preview del User-Agent"""
        selected = self.ua_combo.currentText()

        if 'Custom' in selected:
            ua = self.custom_ua_input.text() or "(vacío - se usará Chrome por defecto)"
        else:
            # Mapear el texto del combo al tipo de UA
            ua_map = {
                'Chrome (Windows)': 'Chrome',
                'Firefox (Windows)': 'Firefox',
                'Brave (Windows)': 'Brave',
                'Safari (macOS)': 'Safari',
                'Edge (Windows)': 'Edge',
                'Android (Mobile)': 'Android',
                'iOS (iPhone)': 'iOS',
            }
            ua_key = ua_map.get(selected, 'Chrome')
            ua = NetworkInterceptor.USER_AGENTS.get(ua_key, '')
        self.ua_preview.setText(ua)
    def add_block_pattern(self):
        """Agregar patrón de bloqueo desde input"""
        self.quick_add_pattern()
    def quick_add_pattern(self):
        """Agregar patrón rápidamente"""
        pattern = self.pattern_input.text().strip()

        if not pattern:
            QMessageBox.warning(self, "Patrón vacío", "Por favor ingresa un patrón o URL.")
            return
        # Determinar tipo
        type_text = self.pattern_type_combo.currentText()
        if 'Wildcard' in type_text:
            pattern_type = 'wildcard'
        elif 'Regex' in type_text:
            pattern_type = 'regex'
        else:
            pattern_type = 'exact'
        # Agregar al interceptor
        if self.interceptor.add_blocked_pattern(pattern, pattern_type):
            self.pattern_input.clear()
            self.refresh_blocked_list()
            QMessageBox.information(self, "Patrón agregado",
                                  f"El patrón '{pattern}' ha sido agregado.")
        else:
            QMessageBox.critical(self, "Error",
                               "No se pudo agregar el patrón.")
    def remove_block_pattern(self):
        """Eliminar patrón seleccionado"""
        current_item = self.blocked_list.currentItem()
        if not current_item:
            return
        pattern = current_item.data(Qt.UserRole)

        reply = QMessageBox.question(
            self,
            "Eliminar patrón",
            f"¿Eliminar el patrón '{pattern}'?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            if self.interceptor.remove_blocked_pattern(pattern):
                self.refresh_blocked_list()
                QMessageBox.information(self, "Patrón eliminado",
                                      f"El patrón '{pattern}' ha sido eliminado.")
    def update_stats(self):
        """Actualizar estadísticas"""
        stats = self.interceptor.get_stats()

        stats_text = f"""
Estadísticas de Interceptación

Total de peticiones: {stats['total_requests']:,}
Peticiones bloqueadas: {stats['blocked_requests']:,}
Porcentaje bloqueado: {stats['blocked_percentage']:.2f}%

User-Agent actual: {stats['user_agent']}
Patrones de bloqueo activos: {stats['patterns_count']}
        """

        self.stats_text.setText(stats_text.strip())
    def reset_stats(self):
        """Resetear estadísticas"""
        reply = QMessageBox.question(
            self,
            "Resetear estadísticas",
            "¿Estás seguro de resetear las estadísticas?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.interceptor.reset_stats()
            self.update_stats()
            QMessageBox.information(self, "Estadísticas reseteadas",
                                  "Las estadísticas han sido reseteadas.")
    def apply_settings(self):
        """Aplicar configuración sin cerrar"""
        self.save_settings()

        # Actualizar el User-Agent ACTIVO para reflejar el cambio guardado
        active_ua = self.interceptor._get_user_agent()
        self.ua_active.setText(f"{active_ua}\n\n(Tipo: {self.interceptor.user_agent_type})")

        # Actualizar el preview
        self.update_ua_preview()

        # NUEVO: Actualizar el perfil global con el nuevo User-Agent
        if hasattr(self.parent(), 'update_global_user_agent'):
            success = self.parent().update_global_user_agent()
            if success:
                print(f"[UA-APPLY] ✓ Global User-Agent profile updated successfully")
            else:
                print(f"[UA-APPLY] Failed to update global User-Agent profile")
        # AUTOMÁTICO: Cerrar todas las pestañas y abrir una nueva con el User-Agent actualizado
        if hasattr(self.parent(), 'tab_manager') and self.parent().tab_manager:
            try:
                tab_manager = self.parent().tab_manager

                # Cerrar todas las pestañas actuales
                while tab_manager.tabs.count() > 0:
                    tab_manager.tabs.removeTab(0)
                # Abrir una nueva pestaña con el User-Agent actualizado
                tab_manager.add_new_tab()

                print(f"[UA-REFRESH] All tabs closed and new tab opened with updated User-Agent: {self.interceptor.user_agent_type}")

                QMessageBox.information(self, "User-Agent actualizado",
                                      f"User-Agent cambiado a: {self.interceptor.user_agent_type}\n\n"
                                      f"Se han cerrado todas las pestañas y se ha abierto una nueva\n"
                                      f"con el User-Agent actualizado.\n\n"
                                      f"Puedes verificarlo en:\n"
                                      f"https://www.whatismybrowser.com/detect/what-is-my-user-agent")
            except Exception as e:
                print(f"[ERROR] Could not refresh tabs: {e}")
                QMessageBox.warning(self, "Configuración aplicada",
                                  "Los cambios han sido aplicados.\n\n"
                                  "Por favor, cierra y abre las pestañas manualmente.")
        else:
            QMessageBox.information(self, "Configuración aplicada",
                                  "Los cambios han sido aplicados correctamente.\n\n"
                                  "Cierra las pestañas actuales y abre nuevas\n"
                                  "para que el nuevo User-Agent se aplique.")
    def accept_settings(self):
        """Guardar y cerrar"""
        self.save_settings()
        self.accept()
    def save_settings(self):
        """Guardar configuración"""
        # User-Agent
        selected = self.ua_combo.currentText()
        ua_map = {
            'Chrome (Windows)': 'Chrome',
            'Firefox (Windows)': 'Firefox',
            'Brave (Windows)': 'Brave',
            'Safari (macOS)': 'Safari',
            'Edge (Windows)': 'Edge',
            'Android (Mobile)': 'Android',
            'iOS (iPhone)': 'iOS',
            'Custom (Personalizado)': 'Custom'
        }

        self.interceptor.user_agent_type = ua_map.get(selected, 'Chrome')

        if self.interceptor.user_agent_type == 'Custom':
            self.interceptor.custom_user_agent = self.custom_ua_input.text()
        else:
            self.interceptor.custom_user_agent = ''
        # Headers
        self.interceptor.enable_dnt = self.dnt_check.isChecked()
        self.interceptor.block_referer = self.referer_check.isChecked()
        self.interceptor.enable_logging = self.logging_check.isChecked()

        # Guardar TODA la configuración en la base de datos (una sola vez)
        self.interceptor.save_configuration()

        # CRÍTICO: Recargar la configuración en el interceptor para que los cambios se apliquen
        # Esto actualiza las variables en memoria del interceptor
        self.interceptor.load_configuration()

        print(f"[NetworkSettings] ✓ Configuration saved and reloaded:")
        print(f"  - User-Agent type: {self.interceptor.user_agent_type}")
        if self.interceptor.user_agent_type == 'Custom':
            print(f"  - Custom UA: {self.interceptor.custom_user_agent}")
        else:
            print(f"  - UA string: {self.interceptor._get_user_agent()}")
        print(f"  - DNT: {self.interceptor.enable_dnt}")
        print(f"  - Block Referer: {self.interceptor.block_referer}")
        print(f"  - Logging: {self.interceptor.enable_logging}")
