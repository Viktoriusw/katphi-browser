#!/usr/bin/env python3


"""


Integración robusta con el Backend de Katphi


Manejo avanzado de errores, timeouts y validación de conectividad


"""


import requests

import jwt


import json


import os


import time

import threading

import logging


from typing import Dict, List, Optional, Any, Tuple


from dataclasses import dataclass


from datetime import datetime, timedelta


from enum import Enum


from pathlib import Path


from PySide6.QtCore import QObject, Signal, QTimer, QSettings


from PySide6.QtWidgets import QMessageBox


# Importar ConfigManager centralizado


from config_manager import ConfigManager, get_backend_url, get_config

# Importar utilidades de seguridad
from security_utils import get_token_encryption

# Importar validación de esquemas
from backend_schemas import (
    validate_auth_response,
    validate_user_info,
    validate_plugin_info,
    validate_license_info,
    validate_plugin_list,
    safe_validate,
    ValidationError
)

# Rutas de plugins multiplataforma (carpeta escribible por usuario).
from plugin_paths import install_target_dir, backups_dir
# Logging configurado en main.py
logger = logging.getLogger(__name__)


class BackendError(Enum):
    """Tipos de errores del backend"""

    NETWORK_ERROR = "network_error"

    AUTHENTICATION_ERROR = "auth_error"

    AUTHORIZATION_ERROR = "authorization_error"

    SERVER_ERROR = "server_error"

    TIMEOUT_ERROR = "timeout_error"

    INVALID_RESPONSE = "invalid_response"

    TOKEN_EXPIRED = "token_expired"

    USER_NOT_VERIFIED = "user_not_verified"

    PLUGIN_NOT_FOUND = "plugin_not_found"

    LICENSE_REQUIRED = "license_required"


class BackendResponse:
    """Respuesta del backend con manejo de errores"""

    def __init__(self, success: bool, data: Any = None, error: BackendError = None, 

                 status_code: int = 200, message: str = ""):
        self.success = success

        self.data = data

        self.error = error

        self.status_code = status_code

        self.message = message

        self.timestamp = datetime.now()


@dataclass


class BackendUser:
    """Usuario del backend"""

    id: str

    email: str

    full_name: str

    is_verified: bool

    created_at: str


@dataclass


class BackendPlugin:
    """Plugin del backend"""

    id: str

    name: str

    description: str

    version: str

    author: str

    price: float

    currency: str

    billing_cycle: str

    category: str

    tags: List[str]

    has_access: bool

    trial_days: int

    features: List[str]


@dataclass


class BackendLicense:
    """Licencia del backend"""

    plugin_id: str

    plugin_name: str

    is_licensed: bool

    expires_at: Optional[str] = None

    trial_remaining: int = 0

    trial_days_remaining: int = 0  # Alias para compatibilidad

    price_cents: int = 0  # Precio en centavos


class BackendIntegration(QObject):
    """Integración robusta con el backend de Katphi"""

    # Signals

    login_successful = Signal(BackendUser)

    login_failed = Signal(str)

    plugins_loaded = Signal(list)

    plugin_downloaded = Signal(str, bool)  # plugin_id, success

    error_occurred = Signal(str)

    connection_status_changed = Signal(bool)  # connected/disconnected

    # Nuevas señales para notificaciones de licencias

    license_expiring_soon = Signal(str, int)  # plugin_id, days_remaining

    license_expired = Signal(str)  # plugin_id

    license_renewed = Signal(str)  # plugin_id

    def __init__(self, parent=None):
        super().__init__(parent)

        # Cargar configuración centralizada

        self.config = get_config()

        # Configuración del backend usando ConfigManager

        self.api_base_url = self.config.get_backend_url()

        self.fallback_urls = self.config.get_backend_fallback_urls()

        # Configuración de timeouts y reintentos con backoff exponencial (desde config.yaml)

        self.timeout = self.config.get_timeout('api')  # Timeout base

        self.max_retries = self.config.get_max_retries()  # 5 reintentos

        self.initial_retry_delay = self.config.get_initial_retry_delay()  # 1.0s inicial

        self.retry_backoff = self.config.get_retry_backoff()  # 2.0 multiplicador

        self.max_retry_delay = self.config.get_max_retry_delay()  # 30s máximo

        # QSettings para persistencia de tokens

        self.settings = QSettings("Katphi", "Browser")

        # Lock para prevenir race conditions en refresh token
        self._token_refresh_lock = threading.Lock()

        logger.info(f"Backend Integration initialized with URL: {self.api_base_url}")

        logger.info(f"Fallback URLs: {self.fallback_urls}")

        logger.info(f"Timeouts - API: {self.timeout}s, Max retries: {self.max_retries}")

        # Estado de autenticación

        self.current_user: Optional[BackendUser] = None

        self.access_token: Optional[str] = None

        self.refresh_token: Optional[str] = None

        self.token_expires_at: Optional[datetime] = None

        # Cache de plugins y licencias

        self.available_plugins: List[BackendPlugin] = []

        self.user_licenses: List[BackendLicense] = []

        self.plugin_licenses: Dict[str, BackendLicense] = {}

        # True cuando /licenses/me/entitlements respondió bien (aunque sea con una
        # lista vacía): a partir de ahí la lista es la verdad y no hay que
        # preguntar plugin a plugin al backend.
        self._licenses_loaded = False

        # Sistema de caché para licencias con timestamps

        self._license_cache: Dict[str, BackendLicense] = {}

        self._license_cache_timestamps: Dict[str, float] = {}

        self._license_cache_duration = self.config.get_license_cache_duration()  # 300s = 5 min

        # Estado de conectividad

        self.is_connected = False

        self.last_connection_check = 0.0

        self.connection_check_interval = 30.0  # 30 segundos

        # Timer para verificación periódica de conectividad

        self.connection_timer = QTimer()

        self.connection_timer.timeout.connect(self._check_connection)

        self.connection_timer.start(30000)  # 30 segundos

        # Verificar conectividad inicial y auto-login: se difieren al siguiente
        # ciclo del event loop (en vez de ejecutarse aquí de forma síncrona)
        # para no bloquear el arranque del navegador — este constructor corre
        # durante MainWindow.__init__, ANTES de que se muestre la ventana, y
        # estas llamadas hacen peticiones HTTP con reintentos/backoff que
        # pueden tardar decenas de segundos si el backend no responde.
        QTimer.singleShot(0, self._check_connection)

        QTimer.singleShot(0, self._restore_session)
    def _check_connection(self):
        """Verificar conectividad con el backend"""

        try:
            response = requests.get(f"{self.api_base_url}/health", timeout=5)

            was_connected = self.is_connected

            self.is_connected = response.status_code == 200

            if was_connected != self.is_connected:
                self.connection_status_changed.emit(self.is_connected)

                logger.info(f"Connection status changed: {self.is_connected}")
            self.last_connection_check = time.time()
        except Exception as e:
            was_connected = self.is_connected

            self.is_connected = False

            if was_connected != self.is_connected:
                self.connection_status_changed.emit(self.is_connected)

                logger.warning(f"Connection lost: {e}")
    def _make_request(self, method: str, endpoint: str, **kwargs) -> BackendResponse:
        """Realizar petición HTTP con manejo robusto de errores"""

        url = f"{self.api_base_url}{endpoint}"

        # Configurar headers por defecto

        headers = kwargs.get('headers', {})

        if self.access_token:
            headers['Authorization'] = f'Bearer {self.access_token}'
        kwargs['headers'] = headers

        # Configurar timeout

        timeout_value = kwargs.get('timeout', self.timeout)

        # Remover timeout de kwargs para evitar conflicto

        if 'timeout' in kwargs:
            del kwargs['timeout']
        for attempt in range(self.max_retries):
            try:
                logger.info(f"Making {method} request to {url} (attempt {attempt + 1})")

                logger.info(f"Request timeout: {timeout_value} seconds")

                # Realizar petición con timeout único

                response = requests.request(method, url, timeout=timeout_value, **kwargs)

                logger.info(f"Response received: {response.status_code}")

                # Manejar códigos de estado específicos

                if response.status_code in (200, 201):
                    try:
                        data = response.json()

                        # Validación básica: debe ser un dict o list
                        if not isinstance(data, (dict, list)):
                            logger.warning(f"Unexpected response type: {type(data)}")
                            return BackendResponse(False, error=BackendError.INVALID_RESPONSE,
                                                 status_code=response.status_code, message="Invalid response structure")
                        return BackendResponse(True, data, status_code=response.status_code)
                    except json.JSONDecodeError:
                        return BackendResponse(False, error=BackendError.INVALID_RESPONSE, 

                                            status_code=200, message="Invalid JSON response")
                elif response.status_code == 401:
                    return BackendResponse(False, error=BackendError.AUTHENTICATION_ERROR,

                                        status_code=401, message="Authentication failed")
                elif response.status_code == 403:
                    return BackendResponse(False, error=BackendError.AUTHORIZATION_ERROR,

                                        status_code=403, message="Access denied")
                elif response.status_code == 404:
                    return BackendResponse(False, error=BackendError.PLUGIN_NOT_FOUND,

                                        status_code=404, message="Resource not found")
                elif response.status_code >= 500:
                    logger.error(f"Server error {response.status_code}: {response.text}")

                    return BackendResponse(False, error=BackendError.SERVER_ERROR,

                                        status_code=response.status_code, message=f"Server error: {response.text}")
                else:
                    return BackendResponse(False, error=BackendError.INVALID_RESPONSE,

                                        status_code=response.status_code, message=f"Unexpected status: {response.status_code}")
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout on attempt {attempt + 1}/{self.max_retries}")

                if attempt < self.max_retries - 1:
                    # Backoff exponencial: delay = initial * (backoff ^ attempt), limitado a max_delay

                    delay = min(self.initial_retry_delay * (self.retry_backoff ** attempt), 

                               self.max_retry_delay)
                    logger.info(f"Retrying in {delay:.2f} seconds...")

                    time.sleep(delay)

                    continue
                return BackendResponse(False, error=BackendError.TIMEOUT_ERROR, 

                                     message="Request timeout after all retries")
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"Connection error on attempt {attempt + 1}/{self.max_retries}: {e}")

                if attempt < self.max_retries - 1:
                    # Backoff exponencial para errores de conexión

                    delay = min(self.initial_retry_delay * (self.retry_backoff ** attempt), 

                               self.max_retry_delay)
                    logger.info(f"Retrying in {delay:.2f} seconds...")

                    time.sleep(delay)

                    continue
                return BackendResponse(False, error=BackendError.NETWORK_ERROR, 

                                     message="Connection failed after all retries")
            except Exception as e:
                logger.error(f"Unexpected error on attempt {attempt + 1}/{self.max_retries}: {e}")

                if attempt < self.max_retries - 1:
                    # Backoff exponencial para errores inesperados

                    delay = min(self.initial_retry_delay * (self.retry_backoff ** attempt), 

                               self.max_retry_delay)
                    logger.info(f"Retrying in {delay:.2f} seconds...")

                    time.sleep(delay)

                    continue
                return BackendResponse(False, error=BackendError.NETWORK_ERROR, 

                                     message=f"Error after all retries: {str(e)}")
        return BackendResponse(False, error=BackendError.NETWORK_ERROR, message="Max retries exceeded")
    def is_authenticated(self) -> bool:
        """Verificar si el usuario está autenticado con validación de token"""

        if not self.current_user or not self.access_token:
            return False
        # Verificar si el token expiró

        if self.token_expires_at and datetime.now() >= self.token_expires_at:
            logger.info("Token expired, attempting refresh")

            return self._refresh_token()
        return True
    # ============================================

    # MÉTODOS DE PERSISTENCIA DE TOKENS

    # ============================================

    def _save_tokens(self):
        """

        Guardar tokens en QSettings para persistencia de sesión

        Guarda:
        - access_token

        - refresh_token

        - token_expires_at

        - user_id

        - user_email

        """

        try:
            if not self.access_token or not self.refresh_token:
                logger.warning("Cannot save tokens: tokens are missing")

                return
            # Guardar tokens (cifrados)
            encryption = get_token_encryption()

            encrypted_access = encryption.encrypt_token(self.access_token) if self.access_token else ""
            encrypted_refresh = encryption.encrypt_token(self.refresh_token) if self.refresh_token else ""

            self.settings.setValue("access_token", encrypted_access)

            self.settings.setValue("refresh_token", encrypted_refresh)

            # Guardar expiración como timestamp

            if self.token_expires_at:
                self.settings.setValue("token_expires_at", self.token_expires_at.timestamp())
            # Guardar info del usuario

            if self.current_user:
                self.settings.setValue("user_id", self.current_user.id)

                self.settings.setValue("user_email", self.current_user.email)

                self.settings.setValue("user_full_name", self.current_user.full_name)
            # Timestamp de guardado

            self.settings.setValue("session_saved_at", datetime.now().timestamp())

            logger.info("Tokens saved successfully to QSettings")
        except Exception as e:
            logger.error(f"Error saving tokens: {e}")
    def _restore_session(self):
        """

        Restaurar sesión desde tokens guardados (AUTO-LOGIN)

        Este método se llama automáticamente al iniciar el navegador.

        Si hay una sesión guardada válida, restaura la autenticación.

        """

        try:
            # Verificar si hay tokens guardados (cifrados)
            encryption = get_token_encryption()

            encrypted_access = self.settings.value("access_token")

            encrypted_refresh = self.settings.value("refresh_token")

            if not encrypted_access or not encrypted_refresh:
                logger.info("No saved session found")

                return
            # Restaurar tokens (descifrados)

            self.access_token = encryption.decrypt_token(encrypted_access)

            self.refresh_token = encryption.decrypt_token(encrypted_refresh)

            # Verificar que el descifrado fue exitoso
            if not self.access_token or not self.refresh_token:
                logger.warning("Failed to decrypt tokens")
                return
            # Restaurar expiración

            expires_timestamp = self.settings.value("token_expires_at")

            if expires_timestamp:
                self.token_expires_at = datetime.fromtimestamp(float(expires_timestamp))
            # Restaurar info del usuario (básica)

            user_id = self.settings.value("user_id")

            user_email = self.settings.value("user_email")

            user_full_name = self.settings.value("user_full_name")

            logger.info(f"Session data found for user: {user_email}")

            # Verificar si el token todavía es válido

            if self.token_expires_at and datetime.now() >= self.token_expires_at:
                logger.info("Saved token expired, attempting refresh...")

                if self._refresh_token():
                    logger.info("Token refreshed successfully, session restored")
                else:
                    logger.warning("Token refresh failed, clearing saved session")

                    self._clear_saved_tokens()

                    return
            # Validar token con el backend

            try:
                user_response = self._make_request("GET", "/auth/me", timeout=self.config.get_timeout('quick_check'))

                if user_response.success:
                    user_data = user_response.data

                    self.current_user = BackendUser(

                        id=user_data["id"],

                        email=user_data["email"],

                        full_name=user_data["full_name"],

                        is_verified=user_data["is_verified"],

                        created_at=user_data["created_at"]
                    )

                    # Cargar datos del usuario

                    self._load_user_data()

                    # Emitir señal de login exitoso

                    self.login_successful.emit(self.current_user)

                    logger.info(f"AUTO-LOGIN successful for: {user_email}")
                else:
                    logger.warning(f"Token validation failed: {user_response.message}")

                    self._clear_saved_tokens()
            except Exception as e:
                logger.error(f"Error validating saved token: {e}")

                self._clear_saved_tokens()
        except Exception as e:
            logger.error(f"Error restoring session: {e}")

            self._clear_saved_tokens()
    def _clear_saved_tokens(self):
        """Limpiar tokens guardados"""

        try:
            self.settings.remove("access_token")

            self.settings.remove("refresh_token")

            self.settings.remove("token_expires_at")

            self.settings.remove("user_id")

            self.settings.remove("user_email")

            self.settings.remove("user_full_name")

            self.settings.remove("session_saved_at")

            logger.info("Saved tokens cleared")
        except Exception as e:
            logger.error(f"Error clearing saved tokens: {e}")
    # ============================================

    # FIN DE MÉTODOS DE PERSISTENCIA

    # ============================================

    def login(self, email: str, password: str) -> BackendResponse:
        """Iniciar sesión en el backend con validación robusta"""

        # Validar entrada

        if not email or not password:
            return BackendResponse(False, error=BackendError.AUTHENTICATION_ERROR,

                                message="User ID and password are required")
        # Verificar conectividad

        if not self.is_connected:
            return BackendResponse(False, error=BackendError.NETWORK_ERROR, 

                                message="No connection to backend server")
        # Realizar login con timeout adecuado (desde config)

        auth_timeout = self.config.get_timeout('auth')  # 15 segundos por defecto

        response = self._make_request("POST", "/auth/login", 

                                    json={"email": email, "password": password},

                                    timeout=auth_timeout)
        if response.success:
            try:
                data = response.data

                # Guardar tokens

                self.access_token = data["access_token"]

                self.refresh_token = data["refresh_token"]

                # Calcular expiración real del token (claim 'exp' del JWT)

                self.token_expires_at = self._compute_token_expiry(self.access_token)

                # Obtener información del usuario

                user_response = self._make_request("GET", "/auth/me")

                if user_response.success:
                    user_data = user_response.data

                    self.current_user = BackendUser(

                        id=user_data["id"],

                        email=user_data["email"],

                        full_name=user_data["full_name"],

                        is_verified=user_data["is_verified"],

                        created_at=user_data["created_at"]
                    )

                    # Verificar si el usuario está verificado

                    if not user_data["is_verified"]:
                        self.logout()

                        return BackendResponse(False, error=BackendError.USER_NOT_VERIFIED,

                                            message="User email not verified")
                    # Cargar datos del usuario

                    self._load_user_data()

                    # GUARDAR TOKENS: Persistir sesión

                    self._save_tokens()

                    self.login_successful.emit(self.current_user)

                    logger.info(f"Login successful and tokens saved for: {email}")

                    return BackendResponse(True, data=self.current_user)
                else:
                    self.logout()

                    return BackendResponse(False, error=BackendError.AUTHENTICATION_ERROR,

                                        message="Failed to get user information")
            except Exception as e:
                logger.error(f"Error processing login response: {e}")

                self.logout()

                return BackendResponse(False, error=BackendError.INVALID_RESPONSE,

                                    message="Error processing server response")
        else:
            # Manejar errores específicos

            if response.error == BackendError.AUTHENTICATION_ERROR:
                return BackendResponse(False, error=BackendError.AUTHENTICATION_ERROR,

                                    message="Invalid email or password")
            elif response.error == BackendError.USER_NOT_VERIFIED:
                return BackendResponse(False, error=BackendError.USER_NOT_VERIFIED,

                                    message="Email not verified. Please check your email.")
            else:
                return BackendResponse(False, error=response.error, message=response.message)
    def _compute_token_expiry(self, token: str, fallback_minutes: int = 30) -> datetime:
        """
        Calcula la expiración real del token leyendo el claim 'exp' del JWT
        (sin verificar firma: solo leemos nuestro propio token para saber cuándo
        caduca, la validación real la hace el backend en cada request).
        Si no se puede decodificar, usa un margen conservador como fallback.
        """

        try:
            payload = jwt.decode(token, options={"verify_signature": False})

            exp = payload.get("exp")

            if exp:
                return datetime.fromtimestamp(exp)
        except Exception as e:
            logger.warning(f"No se pudo leer 'exp' del token, usando fallback de {fallback_minutes}min: {e}")
        return datetime.now() + timedelta(minutes=fallback_minutes)
    def _refresh_token(self) -> bool:
        """Refrescar token de acceso (thread-safe)"""

        if not self.refresh_token:
            return False
        # Usar lock para prevenir race conditions
        with self._token_refresh_lock:
            # Verificar nuevamente después de adquirir el lock
            # (otro thread podría haber refrescado el token mientras esperábamos)
            if self.token_expires_at and self.token_expires_at > datetime.now():
                logger.info("Token already refreshed by another thread")
                return True
            try:
                response = self._make_request("POST", "/auth/refresh",

                                           headers={"Authorization": f"Bearer {self.refresh_token}"})
                if response.success:
                    data = response.data

                    self.access_token = data["access_token"]

                    self.refresh_token = data["refresh_token"]

                    self.token_expires_at = self._compute_token_expiry(self.access_token)

                    # GUARDAR TOKENS REFRESCADOS

                    self._save_tokens()

                    logger.info("Token refreshed successfully and saved")

                    return True
                else:
                    logger.warning(f"Failed to refresh token: {response.error}")

                    # Solo cerrar sesión si el backend rechazó explícitamente el
                    # refresh token (credenciales inválidas de verdad). Ante un
                    # fallo de red/timeout/servidor no destruimos la sesión local:
                    # se reintentará en el próximo ciclo de validación.
                    if response.error in (BackendError.AUTHENTICATION_ERROR, BackendError.AUTHORIZATION_ERROR):
                        self.logout()
                    return False
            except Exception as e:
                logger.error(f"Error refreshing token: {e}")

                # Error inesperado (no confirmado como credenciales inválidas):
                # no cerramos sesión, solo falla este intento de refresco.
                return False
    def logout(self):
        """Cerrar sesión con limpieza completa"""

        try:
            if self.access_token and self.is_connected:
                # Notificar al backend del logout

                self._make_request("POST", "/auth/logout")
        except Exception as e:
            logger.warning(f"Error during logout: {e}")
        # Limpiar estado completamente

        self.current_user = None

        self.access_token = None

        self.refresh_token = None

        self.token_expires_at = None

        self.available_plugins = []

        self.user_licenses = []

        self.plugin_licenses = {}

        self._licenses_loaded = False

        # Limpiar caché de licencias

        self._clear_license_cache()

        # LIMPIAR TOKENS GUARDADOS

        self._clear_saved_tokens()

        logger.info("User logged out successfully and session cleared")
    def _get_user_info(self) -> Optional[Dict]:
        """Obtener información del usuario actual"""

        if not self.is_authenticated():
            return None
        response = self._make_request("GET", "/auth/me")

        if response.success:
            return response.data
        return None
    def _load_user_data(self):
        """Cargar datos del usuario (plugins y licencias)"""

        if not self.is_authenticated():
            return
        # Cargar plugins disponibles

        self._load_available_plugins()

        # Cargar licencias del usuario

        self._load_user_licenses()
    def _load_available_plugins(self):
        """Cargar plugins disponibles con manejo robusto de errores"""

        if not self.is_authenticated():
            return
        response = self._make_request("GET", "/api/plugins/available")

        if response.success:
            try:
                plugins_data = response.data

                self.available_plugins = [

                    BackendPlugin(**plugin) for plugin in plugins_data
                ]

                self.plugins_loaded.emit(self.available_plugins)

                logger.info(f"Loaded {len(self.available_plugins)} plugins")
            except Exception as e:
                logger.error(f"Error processing plugins data: {e}")

                self.error_occurred.emit("Error processing plugins data")
        else:
            logger.error(f"Failed to load plugins: {response.message}")

            self.error_occurred.emit(f"Failed to load plugins: {response.message}")
    def _load_user_licenses(self):
        """Cargar licencias del usuario con validación y notificaciones de expiración"""

        if not self.is_authenticated():
            return
        # Invalidar el caché de licencias antes de recargar: con TTL de 300 s
        # podía arrastrar el acceso del usuario anterior tras un cambio de sesión.
        self._clear_license_cache()
        response = self._make_request("GET", "/licenses/me/entitlements")

        if response.success:
            try:
                licenses_data = response.data

                self.user_licenses = [

                    BackendLicense(**license) for license in licenses_data
                ]

                # Actualizar diccionario de licencias

                self.plugin_licenses = {

                    license.plugin_id: license for license in self.user_licenses
                }

                self._licenses_loaded = True

                # Descartar resultados cacheados antes de tener la lista real
                self._clear_license_cache()

                logger.info(f"Loaded {len(self.user_licenses)} licenses")

                # NUEVO: Verificar expiración de licencias y emitir notificaciones

                self._check_license_expiration()
            except Exception as e:
                logger.error(f"Error processing licenses data: {e}")

                self.error_occurred.emit("Error processing licenses data")
        else:
            logger.error(f"Failed to load licenses: {response.message}")

            self.error_occurred.emit(f"Failed to load licenses: {response.message}")
    def get_available_plugins(self) -> List[BackendPlugin]:
        """Obtener plugins disponibles"""

        return self.available_plugins
    def get_user_licenses(self) -> List[BackendLicense]:
        """Obtener licencias del usuario"""

        return self.user_licenses
    def has_plugin_access(self, plugin_id: str) -> bool:
        """

        Verificar si el usuario tiene acceso a un plugin con sistema de caché

        El caché reduce llamadas al backend y mejora el rendimiento

        """

        if not self.is_authenticated():
            return False
        # SISTEMA DE CACHÉ: Verificar si tenemos una respuesta cacheada válida

        current_time = time.time()

        if plugin_id in self._license_cache_timestamps:
            cache_age = current_time - self._license_cache_timestamps[plugin_id]

            if cache_age < self._license_cache_duration:
                # Caché válido, usar respuesta cacheada

                if plugin_id in self._license_cache:
                    cached_license = self._license_cache[plugin_id]

                    logger.debug(f"Using cached license for {plugin_id} (age: {cache_age:.1f}s)")

                    return cached_license.is_licensed
        # Verificar en cache de licencias del usuario

        if plugin_id in self.plugin_licenses:
            license = self.plugin_licenses[plugin_id]

            if license.is_licensed:
                # Verificar si la licencia expiró

                if license.expires_at:
                    try:
                        expires_date = datetime.fromisoformat(license.expires_at.replace('Z', '+00:00'))

                        if datetime.now() >= expires_date:
                            logger.warning(f"License for {plugin_id} has expired")

                            # Actualizar caché con resultado negativo

                            self._update_license_cache(plugin_id, license, False)

                            return False
                    except Exception as e:
                        logger.warning(f"Error parsing expiration date for {plugin_id}: {e}")
                # Licencia válida, actualizar caché

                self._update_license_cache(plugin_id, license, True)

                return True
        # Con las licencias ya cargadas, un plugin que no aparece (cuenta nueva sin
        # suscripciones) o que no está activo simplemente no tiene acceso. No se
        # consulta /api/plugins/{id}/info: esa llamada es síncrona en el hilo de la
        # UI y, repetida por cada plugin y cada refresco del panel, congelaba el
        # navegador tras el login de cuentas sin suscripción.
        if self._licenses_loaded:
            self._cache_access_result(plugin_id, False)

            return False
        # Licencias aún sin cargar: preguntar al backend y cachear el resultado
        # (también el negativo, para no repetir la petición en cada comprobación)

        has_access = self._verify_plugin_access_with_backend(plugin_id)

        self._cache_access_result(plugin_id, has_access)

        return has_access
    def _cache_access_result(self, plugin_id: str, is_licensed: bool):
        """Cachear un resultado de acceso aunque el plugin no tenga licencia en la lista"""

        license = self.plugin_licenses.get(plugin_id) or BackendLicense(

            plugin_id=plugin_id,

            plugin_name=plugin_id,

            is_licensed=is_licensed,

            expires_at=None,

            trial_remaining=0
        )

        self._update_license_cache(plugin_id, license, is_licensed)
    def _update_license_cache(self, plugin_id: str, license: BackendLicense, is_licensed: bool):
        """Actualizar caché de licencias con timestamp"""

        cache_entry = BackendLicense(

            plugin_id=license.plugin_id,

            plugin_name=license.plugin_name,

            is_licensed=is_licensed,

            expires_at=license.expires_at,

            trial_remaining=license.trial_remaining
        )

        self._license_cache[plugin_id] = cache_entry

        self._license_cache_timestamps[plugin_id] = time.time()

        logger.debug(f"License cache updated for {plugin_id}: {is_licensed}")
    def _clear_license_cache(self):
        """Limpiar completamente el caché de licencias"""

        self._license_cache.clear()

        self._license_cache_timestamps.clear()

        logger.info("License cache cleared")
    def _verify_plugin_access_with_backend(self, plugin_id: str) -> bool:
        """Verificar acceso al plugin con el backend"""

        try:
            response = self._make_request("GET", f"/api/plugins/{plugin_id}/info")

            if response.success:
                plugin_data = response.data

                return plugin_data.get("has_access", False)
        except Exception as e:
            logger.error(f"Error verifying plugin access: {e}")
        return False
    def download_plugin(self, plugin_id: str) -> BackendResponse:
        """

        Descargar plugin del backend con validación robusta y seguridad

        Incluye: validación de checksum, backup, y verificación de integridad

        """

        if not self.is_authenticated():
            return BackendResponse(False, error=BackendError.AUTHENTICATION_ERROR,

                                message="User not authenticated")
        if not self.has_plugin_access(plugin_id):
            return BackendResponse(False, error=BackendError.LICENSE_REQUIRED,

                                message=f"No access to plugin {plugin_id}")
        try:
            # Usar requests directamente para descargar archivo ZIP binario

            url = f"{self.api_base_url}/api/plugins/{plugin_id}/file"

            headers = {'Authorization': f'Bearer {self.access_token}'}

            logger.info(f"Downloading plugin {plugin_id} from {url}")

            # Descargar archivo ZIP con timeout extendido

            http_response = requests.get(url, headers=headers, timeout=60)

            if http_response.status_code == 200:
                try:
                    # Importar módulos necesarios

                    from pathlib import Path

                    import zipfile

                    import shutil

                    import hashlib

                    import json

                    from datetime import datetime

                    # Directorio del plugin específico, en la carpeta ESCRIBIBLE
                    # por usuario (%APPDATA%/Katphi/plugins en Windows, etc.).
                    # Antes era Path("plugins") relativo al CWD y fallaba en un
                    # ejecutable instalado en una ruta de solo lectura.

                    plugin_dir = install_target_dir(plugin_id)

                    # PASO 1: CREAR BACKUP SI EL PLUGIN YA EXISTE

                    if plugin_dir.exists() and self.config.get('plugins.create_backup', True):
                        backup_success = self._create_plugin_backup(plugin_id, plugin_dir)

                        if backup_success:
                            logger.info(f"Backup created for existing plugin: {plugin_id}")
                        else:
                            logger.warning(f"Failed to create backup for: {plugin_id}")
                    # PASO 2: OBTENER CHECKSUM DEL SERVIDOR

                    expected_checksum = None

                    if self.config.get('plugins.validate_checksum', True):
                        expected_checksum = self._get_plugin_checksum(plugin_id)

                        if expected_checksum:
                            logger.info(f"Expected checksum for {plugin_id}: {expected_checksum[:16]}...")
                    # PASO 3: CALCULAR CHECKSUM DEL ARCHIVO DESCARGADO

                    zip_content = http_response.content

                    actual_checksum = hashlib.sha256(zip_content).hexdigest()

                    logger.info(f"Actual checksum: {actual_checksum[:16]}...")

                    # PASO 4: VALIDAR CHECKSUM

                    if expected_checksum and self.config.get('plugins.validate_checksum', True):
                        if actual_checksum != expected_checksum:
                            logger.error(f"Checksum mismatch for {plugin_id}!")

                            logger.error(f"Expected: {expected_checksum}")

                            logger.error(f"Actual: {actual_checksum}")

                            return BackendResponse(False, error=BackendError.SERVER_ERROR,

                                                message="Plugin integrity check failed. Download may be corrupted.")
                        logger.info(f"Checksum validation passed for {plugin_id}")
                    # PASO 5: VALIDAR QUE ES UN ZIP VÁLIDO

                    try:
                        # Validar estructura del ZIP sin extraerlo aún

                        import io

                        zip_buffer = io.BytesIO(zip_content)

                        with zipfile.ZipFile(zip_buffer, 'r') as test_zip:
                            # Verificar que tenga archivos

                            file_list = test_zip.namelist()

                            if not file_list:
                                logger.error(f"ZIP file is empty for {plugin_id}")

                                return BackendResponse(False, error=BackendError.SERVER_ERROR,

                                                    message="Downloaded plugin is empty")
                            # Verificar que tenga plugin.py o __init__.py

                            has_plugin_file = any('plugin.py' in f or '__init__.py' in f for f in file_list)

                            if not has_plugin_file:
                                logger.warning(f"Plugin {plugin_id} may not have plugin.py or __init__.py")
                            # Testear integridad del ZIP

                            bad_file = test_zip.testzip()

                            if bad_file:
                                logger.error(f"Corrupted file in ZIP: {bad_file}")

                                return BackendResponse(False, error=BackendError.SERVER_ERROR,

                                                    message=f"Plugin ZIP is corrupted: {bad_file}")
                        logger.info(f"ZIP validation passed for {plugin_id} ({len(file_list)} files)")
                    except zipfile.BadZipFile:
                        logger.error(f"Invalid ZIP file for {plugin_id}")

                        return BackendResponse(False, error=BackendError.SERVER_ERROR,

                                            message="Downloaded file is not a valid ZIP")
                    # PASO 6: PREPARAR DIRECTORIO (eliminar existente si hay)

                    if plugin_dir.exists():
                        shutil.rmtree(plugin_dir)
                    plugin_dir.mkdir(exist_ok=True)

                    # PASO 7: GUARDAR ARCHIVO ZIP

                    zip_path = plugin_dir / f"{plugin_id}.zip"

                    with open(zip_path, 'wb') as f:
                        f.write(zip_content)
                    logger.info(f"ZIP file saved: {zip_path} ({len(zip_content)} bytes)")

                    # PASO 8: EXTRAER ZIP

                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                        zip_ref.extractall(plugin_dir)
                    logger.info(f"ZIP file extracted to: {plugin_dir}")

                    # PASO 9: GUARDAR METADATA DE INSTALACIÓN

                    metadata = {

                        "plugin_id": plugin_id,

                        "installed_at": datetime.now().isoformat(),

                        "checksum": actual_checksum,

                        "size_bytes": len(zip_content),

                        "file_count": len(file_list),

                        "source": "backend",

                        "version": self._extract_plugin_version(plugin_dir)
                    }

                    metadata_path = plugin_dir / ".plugin_metadata.json"

                    with open(metadata_path, 'w') as f:
                        json.dump(metadata, f, indent=2)
                    logger.info(f"Plugin metadata saved: {metadata_path}")

                    # PASO 10: ELIMINAR ARCHIVO ZIP (mantener solo archivos extraídos)

                    zip_path.unlink()

                    # Emitir señal de éxito

                    self.plugin_downloaded.emit(plugin_id, True)

                    logger.info(f"Plugin {plugin_id} downloaded and installed successfully")

                    return BackendResponse(True, data={

                        "plugin_id": plugin_id,

                        "path": str(plugin_dir),

                        "checksum": actual_checksum,

                        "metadata": metadata
                    })
                except Exception as e:
                    logger.error(f"Error saving/extracting plugin {plugin_id}: {e}")

                    import traceback

                    traceback.print_exc()

                    return BackendResponse(False, error=BackendError.NETWORK_ERROR,

                                        message=f"Error saving plugin: {e}")
            elif http_response.status_code == 403:
                logger.error(f"Access denied for plugin {plugin_id}")

                return BackendResponse(False, error=BackendError.LICENSE_REQUIRED,

                                    message="No access to this plugin. Purchase required.")
            elif http_response.status_code == 401:
                logger.error(f"Authentication failed when downloading plugin {plugin_id}")

                return BackendResponse(False, error=BackendError.AUTHENTICATION_ERROR,

                                    message="Authentication failed. Please login again.")
            else:
                logger.error(f"Download failed with status {http_response.status_code}")

                return BackendResponse(False, error=BackendError.SERVER_ERROR,

                                    message=f"Download failed: HTTP {http_response.status_code}")
        except requests.exceptions.Timeout:
            logger.error(f"Timeout downloading plugin {plugin_id}")

            return BackendResponse(False, error=BackendError.TIMEOUT_ERROR,

                                message="Download timeout. Please try again.")
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error downloading plugin {plugin_id}: {e}")

            return BackendResponse(False, error=BackendError.NETWORK_ERROR,

                                message="Connection error. Check your network.")
        except Exception as e:
            logger.error(f"Unexpected error downloading plugin {plugin_id}: {e}")

            import traceback

            traceback.print_exc()

            return BackendResponse(False, error=BackendError.NETWORK_ERROR,

                                message=f"Error downloading plugin: {e}")
    # ============================================

    # MÉTODOS AUXILIARES PARA SEGURIDAD DE PLUGINS

    # ============================================

    def _create_plugin_backup(self, plugin_id: str, plugin_dir: Path) -> bool:
        """

        Crear backup del plugin existente antes de actualizar

        Guarda en directorio de backups con timestamp

        """

        try:
            from datetime import datetime

            import shutil

            # Obtener directorio de backups: si config da una ruta absoluta se
            # respeta; si no, se usa una carpeta escribible bajo los datos de
            # usuario (evita './plugin_backups' relativo al CWD).

            _cfg_backup = self.config.get('plugins.backup_directory', '')

            if _cfg_backup and os.path.isabs(str(_cfg_backup)):
                backup_base = Path(_cfg_backup)
            else:
                backup_base = backups_dir()

            backup_base.mkdir(parents=True, exist_ok=True)

            # Crear nombre de backup con timestamp

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            backup_name = f"{plugin_id}_{timestamp}"

            backup_path = backup_base / backup_name

            # Copiar directorio completo

            shutil.copytree(plugin_dir, backup_path)

            logger.info(f"Plugin backup created: {backup_path}")

            # Limpiar backups antiguos (mantener solo últimos 5)

            self._cleanup_old_backups(plugin_id, backup_base, keep=5)

            return True
        except Exception as e:
            logger.error(f"Error creating backup for {plugin_id}: {e}")

            return False
    def _cleanup_old_backups(self, plugin_id: str, backup_dir: Path, keep: int = 5):
        """Eliminar backups antiguos, mantener solo los últimos N"""

        try:
            # Encontrar todos los backups de este plugin

            backups = sorted(

                [d for d in backup_dir.iterdir() if d.is_dir() and d.name.startswith(f"{plugin_id}_")],

                key=lambda x: x.stat().st_mtime,

                reverse=True
            )

            # Eliminar los más antiguos si hay más de 'keep'

            if len(backups) > keep:
                for old_backup in backups[keep:]:
                    import shutil

                    shutil.rmtree(old_backup)

                    logger.info(f"Removed old backup: {old_backup.name}")
        except Exception as e:
            logger.warning(f"Error cleaning up old backups: {e}")
    def _get_plugin_checksum(self, plugin_id: str) -> Optional[str]:
        """

        Obtener checksum del plugin desde el backend

        Retorna el SHA256 esperado del archivo ZIP

        """

        try:
            response = self._make_request("GET", f"/api/plugins/{plugin_id}/checksum")

            if response.success and response.data:
                checksum = response.data.get("checksum") or response.data.get("sha256")

                return checksum
            else:
                logger.warning(f"No checksum available for plugin {plugin_id}")

                return None
        except Exception as e:
            logger.warning(f"Error getting checksum for {plugin_id}: {e}")

            return None
    def _extract_plugin_version(self, plugin_dir: Path) -> Optional[str]:
        """

        Extraer versión del plugin desde plugin_info.json o __init__.py

        """

        try:
            import json

            # Intentar desde plugin_info.json

            info_path = plugin_dir / "plugin_info.json"

            if info_path.exists():
                with open(info_path, 'r') as f:
                    info = json.load(f)

                    return info.get("version", "unknown")
            # Intentar desde __init__.py

            init_path = plugin_dir / "__init__.py"

            if init_path.exists():
                with open(init_path, 'r') as f:
                    content = f.read()

                    # Buscar __version__ = "x.x.x"

                    import re

                    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)

                    if match:
                        return match.group(1)
            return "unknown"
        except Exception as e:
            logger.debug(f"Could not extract version for plugin: {e}")

            return "unknown"
    def get_plugin_info(self, plugin_id: str) -> Optional[BackendPlugin]:
        """Obtener información detallada de un plugin"""

        for plugin in self.available_plugins:
            if plugin.id == plugin_id:
                return plugin
        return None
    def purchase_plugin_license(self, plugin_id: str) -> BackendResponse:
        """Comprar licencia de plugin con validación"""

        if not self.is_authenticated():
            return BackendResponse(False, error=BackendError.AUTHENTICATION_ERROR,

                                message="User not authenticated")
        try:
            response = self._make_request("POST", "/licenses/purchase", 

                                        json={"plugin_id": plugin_id})
            if response.success:
                # Recargar licencias del usuario

                self._load_user_licenses()

                logger.info(f"License purchased for plugin {plugin_id}")

                return BackendResponse(True, data={"plugin_id": plugin_id})
            else:
                logger.error(f"Failed to purchase license for {plugin_id}: {response.message}")

                return BackendResponse(False, error=response.error, message=response.message)
        except Exception as e:
            logger.error(f"Error purchasing license for {plugin_id}: {e}")

            return BackendResponse(False, error=BackendError.NETWORK_ERROR,

                                message=f"Error purchasing license: {e}")
    def get_connection_status(self) -> Dict[str, Any]:
        """Obtener estado de la conexión"""

        return {

            "is_connected": self.is_connected,

            "is_authenticated": self.is_authenticated(),

            "backend_url": self.api_base_url,

            "last_check": self.last_connection_check,

            "user": self.current_user.email if self.current_user else None,

            "plugins_loaded": len(self.available_plugins),

            "licenses_loaded": len(self.user_licenses)
        }
    def force_reconnect(self):
        """Forzar reconexión con el backend"""

        logger.info("Forcing reconnection to backend")

        self._check_connection()

        if self.is_authenticated():
            # Recargar datos del usuario

            self._load_user_data()

            logger.info("User data reloaded after reconnection")
    def refresh_licenses(self):
        """

        REFRESCAR LICENCIAS MANUALMENTE

        Método público para refrescar las licencias del usuario desde el backend.

        Útil después de que el usuario complete una suscripción en el dashboard web.

        """

        if not self.is_authenticated():
            logger.warning("Cannot refresh licenses: User not authenticated")

            return False
        try:
            logger.info("Refreshing user licenses from backend...")

            # Limpiar caché de licencias

            self._clear_license_cache()

            # Recargar licencias desde el backend

            self._load_user_licenses()

            # Recargar plugins disponibles (actualiza has_access)

            self._load_available_plugins()

            logger.info(f"Licenses refreshed successfully. Active licenses: {len(self.user_licenses)}")

            return True
        except Exception as e:
            logger.error(f"Error refreshing licenses: {e}")

            return False
    def get_user_info(self) -> Optional[BackendUser]:
        """Obtener información del usuario actual"""

        return self.current_user
    def refresh_authentication(self) -> bool:
        """Refrescar token de autenticación"""

        if not self.refresh_token:
            return False
        try:
            response = requests.post(

                f"{self.api_base_url}/auth/refresh",

                headers={"Authorization": f"Bearer {self.refresh_token}"},

                timeout=10
            )

            if response.status_code == 200:
                try:
                    raw_data = response.json()
                    # Validar esquema de respuesta de autenticación
                    data = validate_auth_response(raw_data)
                except (json.JSONDecodeError, ValidationError) as e:
                    logger.error(f"Invalid refresh token response: {e}")
                    return False
                self.access_token = data["access_token"]

                self.refresh_token = data["refresh_token"]

                return True
            return False
        except Exception as e:
            logger.error(f"Error refreshing access token: {e}")
            return False
    # ============================================

    # SISTEMA DE RENOVACIÓN Y NOTIFICACIONES

    # ============================================

    def _check_license_expiration(self):
        """

        Verificar expiración de licencias y emitir notificaciones

        Notifica si una licencia expira en 7 días o menos

        """

        try:
            import math

            for license in self.user_licenses:
                if not license.expires_at or not license.is_licensed:
                    continue
                try:
                    # Parsear fecha de expiración

                    expires_date = datetime.fromisoformat(license.expires_at.replace('Z', '+00:00'))

                    now = datetime.now()

                    # Calcular días restantes (redondear hacia arriba para mejor UX)

                    time_remaining = expires_date - now

                    days_remaining = math.ceil(time_remaining.total_seconds() / 86400)

                    if days_remaining <= 0:
                        # Licencia expirada

                        logger.warning(f"License expired for {license.plugin_id}")

                        self.license_expired.emit(license.plugin_id)
                    elif days_remaining <= 7:
                        # Licencia expira pronto (7 días o menos)

                        logger.info(f"License expiring soon for {license.plugin_id}: {days_remaining} days")

                        self.license_expiring_soon.emit(license.plugin_id, days_remaining)
                except Exception as e:
                    logger.error(f"Error checking expiration for {license.plugin_id}: {e}")
        except Exception as e:
            logger.error(f"Error in license expiration check: {e}")
    def renew_license(self, plugin_id: str) -> BackendResponse:
        """

        Renovar licencia de un plugin

        En producción, esto abriría el proceso de pago

        """

        if not self.is_authenticated():
            return BackendResponse(False, error=BackendError.AUTHENTICATION_ERROR,

                                message="User not authenticated")
        try:
            # Llamar al endpoint de renovación en el backend

            response = self._make_request("POST", f"/licenses/renew/{plugin_id}")

            if response.success:
                logger.info(f"License renewed successfully for {plugin_id}")

                # Recargar licencias para actualizar información

                self._load_user_licenses()

                # Emitir señal de renovación exitosa

                self.license_renewed.emit(plugin_id)

                return BackendResponse(True, data=response.data,

                                    message=f"License for {plugin_id} renewed successfully")
            else:
                logger.error(f"Failed to renew license for {plugin_id}: {response.message}")

                return response
        except Exception as e:
            logger.error(f"Error renewing license for {plugin_id}: {e}")

            return BackendResponse(False, error=BackendError.NETWORK_ERROR,

                                message=f"Error renewing license: {e}")
    def get_expiring_licenses(self, days_threshold: int = 7) -> List[BackendLicense]:
        """

        Obtener lista de licencias que expiran pronto

        Args:
            days_threshold: Número de días de anticipación (default: 7)
        Returns:
            Lista de licencias que expiran en N días o menos
        """

        expiring_licenses = []

        try:
            for license in self.user_licenses:
                if not license.expires_at or not license.is_licensed:
                    continue
                try:
                    expires_date = datetime.fromisoformat(license.expires_at.replace('Z', '+00:00'))

                    days_remaining = (expires_date - datetime.now()).days

                    if 0 <= days_remaining <= days_threshold:
                        expiring_licenses.append(license)
                except Exception as e:
                    logger.error(f"Error checking {license.plugin_id}: {e}")
        except Exception as e:
            logger.error(f"Error getting expiring licenses: {e}")
        return expiring_licenses


# Instancia global para uso en toda la aplicación


backend_integration = BackendIntegration()
