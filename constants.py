#!/usr/bin/env python3
"""
Constantes globales del navegador Katphi

Este módulo centraliza todas las constantes utilizadas en el proyecto
para evitar strings mágicos y valores hardcodeados dispersos en el código.
"""

# ============================================================================
# INFORMACIÓN DE LA APLICACIÓN
# ============================================================================

APP_NAME = "Katphi"
APP_TITLE = "Katphi Browser"
APP_VERSION = "3.5.1"
APP_VENDOR = "Katphi"
APP_ORGANIZATION = "Katphi"

# ============================================================================
# CONFIGURACIÓN DE RED
# ============================================================================

# Puerto del socket de bookmarks
BOOKMARK_SOCKET_PORT = 65432
BOOKMARK_SOCKET_HOST = "localhost"

# Timeouts (segundos)
DEFAULT_NETWORK_TIMEOUT = 5
DEFAULT_API_TIMEOUT = 10
DEFAULT_AUTH_TIMEOUT = 15
SOCKET_ACCEPT_TIMEOUT = 1

# ============================================================================
# CONFIGURACIÓN DE BASE DE DATOS
# ============================================================================

# Archivos de base de datos
BOOKMARKS_DB = "bookmarks.db"
PASSWORDS_DB = "passwords.db"

# ============================================================================
# CONFIGURACIÓN DE ARCHIVOS
# ============================================================================

# Archivos de configuración
CONFIG_FILE = "config.yaml"
PLUGIN_CONFIG_FILE = "unified_plugin_config.json"

# Archivos de tema
LIGHT_THEME_FILE = "light_theme.json"
DARK_THEME_FILE = "dark_theme.json"

# Archivos de filtros de privacidad
EASYLIST_FILE = "easylist.txt"
EASYPRIVACY_FILE = "easyprivacy.txt"
CUSTOM_FILTERS_FILE = "custom_filters.txt"

# Directorios
PLUGINS_DIR = "plugins"
ICONS_DIR = "icons"

# ============================================================================
# CONFIGURACIÓN DE PLUGINS
# ============================================================================

# Estados de plugins
PLUGIN_STATUS_INSTALLED = "installed"
PLUGIN_STATUS_NOT_INSTALLED = "not_installed"
PLUGIN_STATUS_ACTIVE = "active"
PLUGIN_STATUS_INACTIVE = "inactive"

# Niveles de acceso a plugins
PLUGIN_ACCESS_FREE = "free"
PLUGIN_ACCESS_TRIAL = "trial"
PLUGIN_ACCESS_PREMIUM = "premium"
PLUGIN_ACCESS_ENTERPRISE = "enterprise"

# ============================================================================
# MENSAJES Y ETIQUETAS
# ============================================================================

# Mensajes de autenticación
MSG_AUTH_REQUIRED = "Por favor, inicia sesión para continuar"
MSG_LOGIN_SUCCESS = "Login exitoso"
MSG_LOGIN_FAILED = "Login fallido"
MSG_LOGOUT_SUCCESS = "Sesión cerrada"

# Mensajes de plugins
MSG_PLUGIN_INSTALLED = "Plugin instalado exitosamente"
MSG_PLUGIN_UNINSTALLED = "Plugin desinstalado"
MSG_PLUGIN_ERROR = "Error en el plugin"
MSG_NO_PLUGINS = "No hay plugins disponibles"

# Mensajes de red
MSG_CONNECTION_SUCCESS = "Conectado al servidor"
MSG_CONNECTION_FAILED = "Error de conexión"
MSG_CONNECTION_LOST = "Conexión perdida"

# ============================================================================
# URLS Y RUTAS
# ============================================================================

# Rutas de API (relativos al backend)
API_PATH_LOGIN = "/api/auth/login"
API_PATH_LOGOUT = "/api/auth/logout"
API_PATH_REFRESH = "/api/auth/refresh"
API_PATH_PLUGINS = "/api/plugins"
API_PATH_LICENSES = "/api/licenses"
API_PATH_DOWNLOAD_PLUGIN = "/api/plugins/{plugin_id}/download"

# Rutas del sitio web
WEB_PATH_DASHBOARD = "/app/dashboard.html"
WEB_PATH_PLUGIN_PAGE = "/app/dashboard.html?plugin={plugin_id}"
WEB_PATH_REGISTER = "/registro.html"

# ============================================================================
# CONFIGURACIÓN DE SEGURIDAD
# ============================================================================

# Token storage
USE_KEYRING = False
USE_QSETTINGS = True

# Claves de almacenamiento
STORAGE_KEY_ACCESS_TOKEN = "auth/access_token"
STORAGE_KEY_REFRESH_TOKEN = "auth/refresh_token"
STORAGE_KEY_USER_EMAIL = "auth/user_email"

# ============================================================================
# CONFIGURACIÓN DE UI
# ============================================================================

# Temas
THEME_LIGHT = "light"
THEME_DARK = "dark"
DEFAULT_THEME = THEME_LIGHT

# Tamaños de fuente por defecto
DEFAULT_FONT_SIZE = "10pt"
DEFAULT_ICON_SIZE = (24, 24)

# Espaciado por defecto
DEFAULT_SPACING = "4px"
DEFAULT_BORDER = "1px"

# Colores por defecto (fallback)
DEFAULT_COLOR_PRIMARY = "#007bff"
DEFAULT_COLOR_SUCCESS = "#28a745"
DEFAULT_COLOR_ERROR = "#dc3545"
DEFAULT_COLOR_WARNING = "#ffc107"
DEFAULT_COLOR_INFO = "#17a2b8"
DEFAULT_COLOR_TEXT = "#000000"

# ============================================================================
# CONFIGURACIÓN DE LOGGING
# ============================================================================

DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_FILE = "katphi_browser.log"

# Prefijos de log
LOG_PREFIX_INFO = "[INFO]"
LOG_PREFIX_WARNING = "[WARNING]"
LOG_PREFIX_ERROR = "[ERROR]"
LOG_PREFIX_DEBUG = "[DEBUG]"
LOG_PREFIX_OK = "[OK]"

# ============================================================================
# LÍMITES Y VALIDACIÓN
# ============================================================================

# Límites de rendimiento
# Límite por archivo de lista (líneas leídas); 100 era insuficiente para listas ABP reales
MAX_FILTER_RULES = 60000
MAX_LOGIN_ATTEMPTS = 3
MAX_RETRY_ATTEMPTS = 3

# Intervalos (segundos)
LOGIN_RETRY_DELAY = 1
LICENSE_VALIDATION_INTERVAL = 300
LICENSE_CACHE_DURATION = 300

# Delays de reintento
INITIAL_RETRY_DELAY = 1.0
MAX_RETRY_DELAY = 30.0

# ============================================================================
# CONFIGURACIÓN DE PERFORMANCE
# ============================================================================

# Flags de optimización — EasyList/EasyPrivacy: sin ellos el “Block Ads” casi no bloquea
# (solo custom_filters.txt). Valores previos (True/True + MAX 100) dejaban ~16 reglas.
ASYNC_FILTER_LOADING = True
LOAD_BASIC_FILTERS_ONLY = True
SKIP_HEAVY_FILTERS = False
DISABLE_HEAVY_FILTERS = False

# ============================================================================
# CONFIGURACIÓN DE GENTAB (Pestañas Generativas)
# ============================================================================

GENTAB_MAX_CONTENT_PER_TAB = 4000
GENTAB_MAX_TOTAL_CONTEXT = 24000
GENTAB_MAX_HISTORY = 50
GENTAB_DEFAULT_TEMPERATURE = 0.7
GENTAB_DEFAULT_MAX_TOKENS = 4000
GENTAB_URL_SCHEME = "gentab://"
GENTAB_INTERNAL_URL = "about:gentab"

# ============================================================================
# CÓDIGOS DE ESTADO HTTP
# ============================================================================

HTTP_OK = 200
HTTP_CREATED = 201
HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404
HTTP_SERVER_ERROR = 500
