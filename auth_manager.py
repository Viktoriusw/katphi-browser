#!/usr/bin/env python3


"""


Authentication Manager robusto para Katphi Browser


Manejo avanzado de autenticación con validación agresiva y sincronización con backend


"""


import json


import os


import time

import threading

import hashlib


import base64


import logging


from typing import Dict, Optional, List, Tuple, Any


from dataclasses import dataclass, asdict


from datetime import datetime, timedelta


from enum import Enum


from PySide6.QtCore import QObject, Signal, QTimer, QSettings


from PySide6.QtWidgets import QMessageBox


import jwt


# Importar ConfigManager centralizado


from config_manager import ConfigManager, get_config

# Importar utilidades de seguridad
from security_utils import get_token_encryption
# Logging configurado en main.py
logger = logging.getLogger(__name__)


class AuthError(Enum):
    """Tipos de errores de autenticación"""

    INVALID_CREDENTIALS = "invalid_credentials"

    USER_NOT_VERIFIED = "user_not_verified"

    TOKEN_EXPIRED = "token_expired"

    NETWORK_ERROR = "network_error"

    SERVER_ERROR = "server_error"

    LICENSE_REQUIRED = "license_required"

    DEVICE_LIMIT_EXCEEDED = "device_limit_exceeded"


class AuthResult:
    """Resultado de operación de autenticación"""

    def __init__(self, success: bool, error: AuthError = None, message: str = ""):
        self.success = success

        self.error = error

        self.message = message

        self.timestamp = datetime.now()


@dataclass


class UserCredentials:
    """User authentication credentials"""

    email: str

    access_token: str

    refresh_token: str

    expires_at: float

    user_id: str


@dataclass


class PluginLicense:
    """Plugin license information"""

    plugin_id: str

    plugin_name: str

    is_premium: bool

    is_active: bool

    expires_at: Optional[float] = None

    device_limit: int = 3

    current_devices: int = 0


@dataclass


class AuthState:
    """Current authentication state"""

    is_authenticated: bool = False

    user_credentials: Optional[UserCredentials] = None

    plugin_licenses: Dict[str, PluginLicense] = None

    last_validation: float = 0.0

    def __post_init__(self):
        if self.plugin_licenses is None:
            self.plugin_licenses = {}


class AuthManager(QObject):
    """Gestor de autenticación robusto para el navegador"""

    # Signals

    auth_state_changed = Signal(bool)  # Authentication state changed

    plugin_license_changed = Signal(str, bool)  # Plugin ID, is_licensed

    login_successful = Signal(UserCredentials)

    login_failed = Signal(str)  # Error message

    logout_successful = Signal()

    connection_status_changed = Signal(bool)  # Backend connection status

    def __init__(self, parent=None):
        super().__init__(parent)

        # Cargar configuración centralizada

        self.config = get_config()

        # Integración con backend

        try:
            from backend_integration import backend_integration

            self.backend = backend_integration  # Usar instancia global

            self.backend.login_successful.connect(self._on_backend_login_success)

            self.backend.login_failed.connect(self._on_backend_login_failed)

            self.backend.connection_status_changed.connect(self._on_connection_status_changed)

            # Resultado negativo de la restauración de sesión al arrancar (D-005)
            self.backend.session_restore_failed.connect(self._on_backend_session_restore_failed)
        except ImportError:
            logger.error("Backend integration not available")

            self.backend = None
        # Configuración desde config.yaml

        self.device_fingerprint = self._generate_device_fingerprint()

        self.validation_interval = self.config.get_license_validation_interval()  # Desde config (300s = 5 min)

        self.max_login_attempts = 3

        self.login_attempts = 0

        self.last_login_attempt = 0.0

        logger.info(f"Auth Manager initialized with validation interval: {self.validation_interval}s")

        # Estado

        self.auth_state = AuthState()

        self.settings = QSettings("Katphi", "Browser")

        # Tolerancia a fallos transitorios en la validación periódica de licencias:
        # solo se fuerza logout tras varios fallos consecutivos, no ante el primer
        # error de red/timeout puntual.
        self._validation_failure_count = 0
        self._max_validation_failures = 3

        # Timer de validación más frecuente

        self.validation_timer = QTimer()

        self.validation_timer.timeout.connect(self._validate_licenses)

        self.validation_timer.setInterval(self.validation_interval * 1000)

        # Timer de verificación de conectividad

        self.connection_timer = QTimer()

        self.connection_timer.timeout.connect(self._check_connection)

        self.connection_timer.setInterval(30000)  # 30 segundos

        self.connection_timer.start()

        # Cargar credenciales guardadas

        self._load_saved_credentials()

        # Iniciar validación si está autenticado

        if self.auth_state.is_authenticated:
            self.validation_timer.start()

            logger.info("Auth manager initialized with existing authentication")
    def _on_backend_login_success(self, user):
        """Manejador de login exitoso del backend (login interactivo y auto-login).

        Se ejecuta SIEMPRE en el hilo de la GUI: el LoginWorker solo hace la
        petición y backend.login_successful llega aquí por conexión encolada.
        Todas las mutaciones de auth_state se hacen aquí (C-004).
        """

        logger.info(f"Backend login successful for user: {user.email}")

        was_authenticated = self.auth_state.is_authenticated

        # Estado + credenciales sin emitir todavía: los listeners de
        # auth_state_changed (resync de plugins) deben ver ya las licencias.
        self._update_auth_state(True, user, emit_signal=False)

        # Licencias del usuario (el backend ya las cargó en _load_user_data)
        self._load_user_entitlements()

        if not was_authenticated:
            self.auth_state_changed.emit(True)

            logger.info("Authentication state changed: True")
        # CRÍTICO: Guardar credenciales para auto-login

        self._save_credentials()

        logger.info("User credentials saved for auto-login")

        # Validación periódica de licencias también tras un login interactivo
        # (antes solo se arrancaba en __init__ con sesión guardada).
        self._validation_failure_count = 0

        if not self.validation_timer.isActive():
            self.validation_timer.start()

        if not self.connection_timer.isActive():
            self.connection_timer.start()

        self.login_successful.emit(self.auth_state.user_credentials)
    def _on_backend_session_restore_failed(self, auth_rejected: bool):
        """La restauración de sesión del backend al arrancar no se completó.

        auth_rejected=True: el backend rechazó los tokens (o no hay sesión
        guardada): se descarta el estado optimista cargado de las credenciales
        guardadas. auth_rejected=False: fallo de red/servidor; se mantiene el
        estado local y el backend reintenta al volver la conexión (D-005).
        """

        if not auth_rejected:
            logger.warning("Backend session restore pending (network/server error), keeping local session")

            return
        if not self.auth_state.is_authenticated and not self.settings.value("user_credentials"):
            return
        logger.warning("Saved session rejected by backend, clearing local authentication state")

        self.validation_timer.stop()

        # Igual que en logout(): vaciar antes de emitir auth_state_changed
        self.auth_state.plugin_licenses = {}

        self._clear_saved_credentials()

        self._update_auth_state(False)
    def _on_backend_login_failed(self, error_message):
        """Manejador de login fallido del backend"""

        logger.warning(f"Backend login failed: {error_message}")

        self.login_failed.emit(error_message)
    def _on_connection_status_changed(self, is_connected):
        """Manejador de cambio de estado de conexión"""

        logger.info(f"Backend connection status changed: {is_connected}")

        self.connection_status_changed.emit(is_connected)

        if not is_connected and self.auth_state.is_authenticated:
            logger.warning("Backend disconnected, but user still authenticated locally")
    def _check_connection(self):
        """Verificar conectividad con el backend"""

        if self.backend:
            # El backend maneja su propia verificación de conectividad

            pass
        else:
            logger.warning("Backend integration not available")
    def _update_auth_state(self, is_authenticated: bool, user=None, emit_signal: bool = True):
        """Actualizar estado de autenticación (solo desde el hilo de la GUI)"""

        was_authenticated = self.auth_state.is_authenticated

        self.auth_state.is_authenticated = is_authenticated

        if is_authenticated and user:
            # Crear credenciales del usuario

            # Usar la expiración real del token (leída del JWT por backend_integration)
            # en vez de un valor fijo desincronizado del token real.
            if self.backend and getattr(self.backend, "token_expires_at", None):
                expires_at = self.backend.token_expires_at.timestamp()
            else:
                expires_at = time.time() + 1800  # Fallback conservador: 30 minutos

            self.auth_state.user_credentials = UserCredentials(

                email=user.email,

                access_token="",  # Se maneja en el backend

                refresh_token="",  # Se maneja en el backend

                expires_at=expires_at,

                user_id=user.id
            )
        else:
            self.auth_state.user_credentials = None
        # Emitir señal si cambió el estado

        if emit_signal and was_authenticated != is_authenticated:
            self.auth_state_changed.emit(is_authenticated)

            logger.info(f"Authentication state changed: {is_authenticated}")
    def _generate_device_fingerprint(self) -> str:
        """Generar huella digital única del dispositivo"""

        import platform

        import uuid

        # Get system information

        system_info = {

            'platform': platform.system(),

            'platform_release': platform.release(),

            'platform_version': platform.version(),

            'machine': platform.machine(),

            'processor': platform.processor(),
        }

        # Get MAC address

        mac = uuid.getnode()

        # Create fingerprint

        fingerprint_data = f"{system_info}{mac}"

        fingerprint = hashlib.sha256(fingerprint_data.encode()).hexdigest()

        return fingerprint
    def _load_saved_credentials(self):
        """Load saved credentials from settings and restore session"""

        try:
            credentials_data = self.settings.value("user_credentials")

            if credentials_data:
                encryption = get_token_encryption()

                cred_dict = json.loads(credentials_data)

                # Descifrar tokens sensibles
                if cred_dict.get('access_token'):
                    cred_dict['access_token'] = encryption.decrypt_token(cred_dict['access_token'])
                if cred_dict.get('refresh_token'):
                    cred_dict['refresh_token'] = encryption.decrypt_token(cred_dict['refresh_token'])
                # Check if token is still valid

                if cred_dict.get('expires_at', 0) > time.time():
                    self.auth_state.user_credentials = UserCredentials(**cred_dict)

                    # Estado optimista mientras el backend valida la sesión.
                    self.auth_state.is_authenticated = True

                    # C-003: la sesión del backend NO se restaura aquí de forma
                    # síncrona. La restaura una sola vez el singleShot de
                    # BackendIntegration.__init__, que emite login_successful
                    # (-> _on_backend_login_success: licencias, timers y
                    # login_successful hacia la UI) o session_restore_failed.

                    # Load plugin licenses (caché local hasta que llegue el backend)

                    self._load_plugin_licenses()

                    logger.info("[AUTH] Loaded saved credentials, backend session restore scheduled")
                else:
                    # expires_at es la caducidad del access token (30 min), no la
                    # de la sesión: backend_integration._restore_session la renueva
                    # con el refresh token y emite login_successful si sigue válida.
                    logger.info("[AUTH] Access token expired, backend will refresh the saved session")
        except Exception as e:
            logger.error(f"[AUTH] Error loading saved credentials: {e}")

            self._clear_saved_credentials()
    def _save_credentials(self):
        """Save credentials to settings"""

        try:
            if self.auth_state.user_credentials:
                encryption = get_token_encryption()

                cred_dict = asdict(self.auth_state.user_credentials)

                # Cifrar tokens sensibles
                if cred_dict.get('access_token'):
                    cred_dict['access_token'] = encryption.encrypt_token(cred_dict['access_token'])
                if cred_dict.get('refresh_token'):
                    cred_dict['refresh_token'] = encryption.encrypt_token(cred_dict['refresh_token'])
                self.settings.setValue("user_credentials", json.dumps(cred_dict))

                print("[AUTH] Credentials saved (encrypted)")
        except Exception as e:
            print(f"[AUTH] Error saving credentials: {e}")
    def _clear_saved_credentials(self):
        """Clear saved credentials"""

        self.settings.remove("user_credentials")

        self.settings.remove("plugin_licenses")
    def _load_plugin_licenses(self):
        """Load plugin licenses from settings"""

        try:
            licenses_data = self.settings.value("plugin_licenses")

            if licenses_data:
                from security_utils import get_token_encryption
                decrypted = get_token_encryption().decrypt(licenses_data)
                # Una caché antigua en texto plano (o manipulada) se descarta:
                # el backend la rehace cifrada al sincronizar las licencias
                licenses_dict = json.loads(decrypted) if decrypted else {}

                self.auth_state.plugin_licenses = {

                    plugin_id: PluginLicense(**license_data)

                    for plugin_id, license_data in licenses_dict.items()
                }

                print("[AUTH] Loaded plugin licenses")
        except Exception as e:
            print(f"[AUTH] Error loading plugin licenses: {e}")

            self.auth_state.plugin_licenses = {}
    def _save_plugin_licenses(self):
        """Save plugin licenses to settings"""

        try:
            licenses_dict = {

                plugin_id: asdict(license_info)

                for plugin_id, license_info in self.auth_state.plugin_licenses.items()
            }

            from security_utils import get_token_encryption
            encrypted = get_token_encryption().encrypt(json.dumps(licenses_dict))
            if encrypted:
                self.settings.setValue("plugin_licenses", encrypted)

            print("[AUTH] Plugin licenses saved")
        except Exception as e:
            print(f"[AUTH] Error saving plugin licenses: {e}")
    def login(self, email: str, password: str) -> AuthResult:
        """Login del usuario con validación agresiva"""

        # Validar entrada

        if not email or not password:
            return AuthResult(False, AuthError.INVALID_CREDENTIALS, "User ID and password are required")
        # Verificar límite de intentos

        current_time = time.time()

        if current_time - self.last_login_attempt < 60:  # 1 minuto entre intentos
            if self.login_attempts >= self.max_login_attempts:
                return AuthResult(False, AuthError.INVALID_CREDENTIALS, 

                               "Too many login attempts. Please wait before trying again.")
        # Resetear contador si pasó suficiente tiempo

        if current_time - self.last_login_attempt > 300:  # 5 minutos
            self.login_attempts = 0
        self.login_attempts += 1

        self.last_login_attempt = current_time

        logger.info(f"Login attempt {self.login_attempts} for user: {email}")

        # Verificar conectividad del backend

        if not self.backend:
            return AuthResult(False, AuthError.NETWORK_ERROR, "Backend integration not available")
        if not self.backend.is_connected:
            return AuthResult(False, AuthError.NETWORK_ERROR, "No connection to backend server")
        # Realizar login a través del backend

        try:
            response = self.backend.login(email, password)

            if response.success:
                logger.info(f"Login successful for user: {email}")

                # C-004: este método corre en el LoginWorker. El estado de
                # autenticación y las licencias se actualizan en el hilo de la
                # GUI, en _on_backend_login_success (backend.login_successful
                # llega encolada ANTES que login_completed del worker).

                return AuthResult(True)
            else:
                # Mapear errores del backend a errores de auth

                if response.error.value == "auth_error":
                    return AuthResult(False, AuthError.INVALID_CREDENTIALS, response.message)
                elif response.error.value == "user_not_verified":
                    return AuthResult(False, AuthError.USER_NOT_VERIFIED, response.message)
                else:
                    return AuthResult(False, AuthError.NETWORK_ERROR, response.message)
        except Exception as e:
            logger.error(f"Login error: {e}")

            return AuthResult(False, AuthError.NETWORK_ERROR, f"Login failed: {e}")
    def logout(self):
        """Logout del usuario con limpieza completa"""

        logger.info("User logout initiated")

        # Detener timers

        self.validation_timer.stop()

        self.connection_timer.stop()

        # Logout del backend

        if self.backend:
            try:
                self.backend.logout()

                logger.info("Backend logout completed")
            except Exception as e:
                logger.warning(f"Error during backend logout: {e}")
        # Limpiar estado local.
        # IMPORTANTE: vaciar licencias y credenciales ANTES de _update_auth_state,
        # porque ese método emite auth_state_changed y no debe haber ningún
        # listener (p.ej. el resync de plugins) que vea licencias del usuario
        # que está saliendo.

        self.auth_state.plugin_licenses = {}

        self._clear_saved_credentials()

        self._update_auth_state(False)

        # Resetear contadores

        self.login_attempts = 0

        self.last_login_attempt = 0.0

        # Emitir señales

        self.logout_successful.emit()

        logger.info("User logout completed successfully")
    def _load_user_entitlements(self):
        """Cargar permisos del usuario desde el backend"""

        try:
            if not self.auth_state.is_authenticated or not self.backend:
                return
            # Obtener licencias del backend

            user_licenses = self.backend.get_user_licenses()

            # Estado anterior, para emitir solo los cambios (D-003)
            previous_state = {
                pid: bool(getattr(lic, "is_active", False))
                for pid, lic in self.auth_state.plugin_licenses.items()
            }

            # Limpiar licencias existentes

            self.auth_state.plugin_licenses = {}

            # Procesar licencias del backend

            for license_info in user_licenses:
                logger.info(f"[DEBUG] Processing license: plugin_id={license_info.plugin_id}, is_licensed={license_info.is_licensed}, expires={license_info.expires_at}")

                license_obj = PluginLicense(

                    plugin_id=license_info.plugin_id,

                    plugin_name=license_info.plugin_name,

                    is_premium=True,

                    is_active=license_info.is_licensed,

                    expires_at=license_info.expires_at,

                    device_limit=3,  # Por defecto

                    current_devices=0  # Por defecto
                )

                self.auth_state.plugin_licenses[license_info.plugin_id] = license_obj

                logger.info(f"[DEBUG] License stored in auth_state: {license_info.plugin_id} -> is_active={license_obj.is_active}")
            # Guardar licencias

            self._save_plugin_licenses()

            # Emitir señales SOLO para los plugins cuyo estado cambió (D-003):
            # antes se emitía una por licencia en cada validación periódica y
            # cada una disparaba un resync completo de plugins en main_window.
            # Un plugin que desaparece de la lista cuenta como revocado.

            current_state = {
                pid: bool(lic.is_active)
                for pid, lic in self.auth_state.plugin_licenses.items()
            }

            for plugin_id in sorted(set(previous_state) | set(current_state)):
                was_active = previous_state.get(plugin_id, False)

                is_active = current_state.get(plugin_id, False)

                if was_active != is_active:
                    if not is_active:
                        logger.warning(f"Licencia revocada o inactiva: {plugin_id}")
                    self.plugin_license_changed.emit(plugin_id, is_active)
            logger.info(f"Loaded {len(self.auth_state.plugin_licenses)} plugin licenses from backend")
        except Exception as e:
            logger.error(f"Error loading entitlements: {e}")
    def _validate_licenses(self):
        """Validar licencias actuales con el servidor (validación agresiva, con
        tolerancia a fallos transitorios: no se cierra sesión ante un único
        error de red/timeout, solo tras varios fallos consecutivos)."""

        try:
            if not self.auth_state.is_authenticated:
                self._validation_failure_count = 0

                return
            # Verificar conectividad del backend

            if not self.backend or not self.backend.is_connected:
                logger.warning("Backend not connected during license validation, omitiendo este ciclo")

                return
            # D-005: sesión guardada pendiente de restaurar por un fallo de
            # red; no cuenta como fallo de autenticación (el backend reintenta
            # al recuperar la conexión).
            if getattr(self.backend, "is_restore_pending", None) and self.backend.is_restore_pending():
                logger.warning("Backend session restore pending, omitiendo este ciclo de validación")

                return
            # Verificar autenticación del backend

            if not self.backend.is_authenticated():
                self._validation_failure_count += 1

                logger.warning(
                    f"Backend authentication check failed "
                    f"({self._validation_failure_count}/{self._max_validation_failures})"
                )

                if self._validation_failure_count >= self._max_validation_failures:
                    logger.warning("Backend authentication lost tras varios intentos consecutivos, cerrando sesión")

                    self.logout()
                return
            self._validation_failure_count = 0

            # Cargar permisos frescos. _load_user_entitlements ya emite
            # plugin_license_changed solo para lo que cambió, revocaciones
            # incluidas (para descargar plugins en caliente).

            self._load_user_entitlements()

            self.auth_state.last_validation = time.time()

            logger.info("License validation completed successfully")

            self._validation_failure_count = 0
        except Exception as e:
            self._validation_failure_count += 1

            logger.error(
                f"License validation error "
                f"({self._validation_failure_count}/{self._max_validation_failures}): {e}"
            )

            # Solo forzar logout tras varios fallos consecutivos, no ante un
            # único error transitorio (timeout, hiccup del backend, etc.)
            if self._validation_failure_count >= self._max_validation_failures:
                logger.error("Fallos repetidos en validación de licencias, cerrando sesión por seguridad")

                self.logout()
    def is_plugin_licensed(self, plugin_id: str) -> bool:
        """Verificar si un plugin está licenciado (validación agresiva)"""

        if not self.auth_state.is_authenticated:
            logger.warning(f"Plugin {plugin_id} access denied: User not authenticated")

            return False
        # Verificar conectividad del backend

        if not self.backend or not self.backend.is_connected:
            logger.warning(f"Plugin {plugin_id} access denied: Backend not connected")

            return False
        # Verificar autenticación del backend

        if not self.backend.is_authenticated():
            logger.warning(f"Plugin {plugin_id} access denied: Backend authentication lost")

            # Solo cerrar sesión si el backend ya la descartó (refresh rechazado);
            # ante un fallo de red al refrescar se deniega sin destruir la sesión
            if not self.backend.refresh_token:
                self.logout()

            return False
        # Verificar con el backend directamente (validación en tiempo real)

        if self.backend.has_plugin_access(plugin_id):
            logger.info(f"Plugin {plugin_id} access granted")

            return True
        # Con la lista de licencias ya recibida del backend, su "no" es
        # definitivo: la caché local (QSettings) solo cubre el arranque, antes
        # de que llegue esa lista. Antes un "no" del backend se podía saltar
        # editando la caché.
        if getattr(self.backend, "_licenses_loaded", False):
            logger.warning(f"Plugin {plugin_id} access denied by backend")

            return False
        # Verificar cache local como fallback

        logger.info(f"[DEBUG] Checking local cache for {plugin_id}. Total licenses in cache: {len(self.auth_state.plugin_licenses)}")

        logger.info(f"[DEBUG] Plugin licenses keys: {list(self.auth_state.plugin_licenses.keys())}")

        license_info = self.auth_state.plugin_licenses.get(plugin_id)

        if license_info:
            logger.info(f"[DEBUG] License found for {plugin_id}: is_active={license_info.is_active}, expires_at={license_info.expires_at}")

            # Verificar si la licencia está activa

            if not license_info.is_active:
                logger.warning(f"Plugin {plugin_id} access denied: License not active")

                return False
            # Verificar si la licencia expiró

            if license_info.expires_at and license_info.expires_at <= time.time():
                logger.warning(f"Plugin {plugin_id} access denied: License expired")

                return False
            logger.info(f"Plugin {plugin_id} access granted from cache")

            return True
        logger.warning(f"Plugin {plugin_id} access denied: No license found in cache")

        return False
    def get_plugin_license(self, plugin_id: str) -> Optional[PluginLicense]:
        """Get plugin license information"""

        return self.auth_state.plugin_licenses.get(plugin_id)
    def get_user_info(self) -> Optional[Dict]:
        """Get current user information"""

        if not self.auth_state.is_authenticated or not self.auth_state.user_credentials:
            return None
        return {

            "email": self.auth_state.user_credentials.email,

            "user_id": self.auth_state.user_credentials.user_id,

            "is_authenticated": self.auth_state.is_authenticated,

            "plugin_count": len(self.auth_state.plugin_licenses)
        }
    def get_licensed_plugins(self) -> List[str]:
        """Get list of licensed plugin IDs"""

        return [

            plugin_id for plugin_id, license_info in self.auth_state.plugin_licenses.items()

            if self.is_plugin_licensed(plugin_id)
        ]
    def force_validation(self):
        """Forzar validación inmediata de licencias"""

        logger.info("Forcing immediate license validation")

        self._validate_licenses()
    def get_auth_status(self) -> Dict[str, Any]:
        """Obtener estado completo de autenticación"""

        return {

            "is_authenticated": self.auth_state.is_authenticated,

            "is_connected": self.backend.is_connected if self.backend else False,

            "user_email": self.auth_state.user_credentials.email if self.auth_state.user_credentials else None,

            "plugin_licenses_count": len(self.auth_state.plugin_licenses),

            "last_validation": self.auth_state.last_validation,

            "device_fingerprint": self.device_fingerprint,

            "login_attempts": self.login_attempts,

            "backend_status": self.backend.get_connection_status() if self.backend else None
        }
    def force_reconnect(self):
        """Forzar reconexión con el backend"""

        if self.backend:
            self.backend.force_reconnect()

            logger.info("Forced backend reconnection")
    def clear_cache(self):
        """Limpiar cache de licencias y forzar recarga"""

        self.auth_state.plugin_licenses = {}

        self._clear_saved_credentials()

        if self.auth_state.is_authenticated:
            self._load_user_entitlements()
        logger.info("Auth cache cleared")
