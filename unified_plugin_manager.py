#!/usr/bin/env python3


"""


Gestor Unificado de Plugins Robusto


Sistema de gestión de plugins con validación agresiva y manejo robusto de errores


"""


import os


import sys


import json


import time


import requests


import zipfile


import shutil


import tempfile


import logging


from pathlib import Path


from typing import Dict, List, Optional, Any, Tuple


from dataclasses import dataclass, asdict


from datetime import datetime, timedelta


from enum import Enum


from PySide6.QtCore import QObject, Signal, QTimer, QThread, QSettings


from PySide6.QtWidgets import QMessageBox, QWidget


# Importar ConfigManager centralizado


from config_manager import ConfigManager, get_config, get_backend_url
# Logging configurado en main.py
logger = logging.getLogger(__name__)


# Importar dependencias existentes


from auth_manager import AuthManager, UserCredentials, PluginLicense, AuthState, AuthResult, AuthError


from plugins.plugin_base import PluginBase, PluginMetadata

# Rutas de plugins multiplataforma (carpeta escribible por usuario para las
# descargas + carpeta bundled de solo lectura para los preinstalados).
from plugin_paths import (
    BUNDLED_PLUGINS_DIR,
    USER_PLUGINS_DIR,
    ensure_user_plugins_dir,
    find_plugin_dir,
    install_target_dir,
    is_bundled_only,
    iter_installed_plugin_ids,
    resolve_config_file,
    user_config_file,
)
from plugin_policy import is_free_plugin, dev_mode_allowed


class PluginAccessLevel(Enum):
    """Niveles de acceso a plugins"""

    NONE = "none"  # Sin acceso: no autenticado, sin auth_manager o plugin desconocido

    FREE = "free"

    PREMIUM = "premium"

    TRIAL = "trial"

    EXPIRED = "expired"


@dataclass


class PluginAccessInfo:
    """Información de acceso a un plugin"""

    plugin_id: str

    plugin_name: str

    access_level: PluginAccessLevel

    is_licensed: bool

    license_info: Optional[PluginLicense] = None

    trial_remaining: int = 0

    features_available: List[str] = None

    def __post_init__(self):
        if self.features_available is None:
            self.features_available = []


@dataclass


class PluginInfo:
    """Información completa de un plugin"""

    id: str

    name: str

    version: str

    author: str

    description: str

    premium: bool = False

    price: float = 0.0

    currency: str = "USD"

    billing_cycle: str = "monthly"

    category: str = "general"

    tags: List[str] = None

    features: List[str] = None

    requirements: Dict[str, Any] = None

    permissions: List[str] = None

    icon: str = None

    download_url: str = None

    info_url: str = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.features is None:
            self.features = []
        if self.requirements is None:
            self.requirements = {}
        if self.permissions is None:
            self.permissions = []


class PluginDownloader(QThread):
    """Thread para descargar plugins desde el backend"""

    progress_updated = Signal(int)

    download_completed = Signal(str, bool)  # plugin_id, success

    error_occurred = Signal(str)

    def __init__(self, plugin_id: str, auth_manager: AuthManager, parent=None):
        super().__init__(parent)

        self.plugin_id = plugin_id

        self.auth_manager = auth_manager

        # Usar ConfigManager para obtener backend URL

        self.api_base_url = get_backend_url()
    def run(self):
        """Descargar plugin desde el backend"""

        try:
            # Usar integración con backend

            from backend_integration import backend_integration

            if not backend_integration.is_authenticated():
                self.error_occurred.emit("Usuario debe estar autenticado para descargar plugins")

                return
            if not backend_integration.has_plugin_access(self.plugin_id):
                self.error_occurred.emit("No tienes acceso a este plugin. Por favor, compra la suscripción primero.")

                return
            # Descargar plugin usando la integración

            self.progress_updated.emit(10)  # Inicio de descarga

            response = backend_integration.download_plugin(self.plugin_id)

            if response and response.success:
                self.progress_updated.emit(100)  # Descarga completada

                self.download_completed.emit(self.plugin_id, True)
            else:
                msg = getattr(response, 'message', None) if response else "Error desconocido"
                self.error_occurred.emit(msg or "Error descargando plugin desde el backend")
        except Exception as e:
            self.error_occurred.emit(f"Error de descarga: {str(e)}")
    def _install_plugin(self, zip_path: str, plugin_id: str) -> bool:
        """Instalar plugin desde archivo ZIP"""

        try:
            plugin_dir = install_target_dir(plugin_id)

            if plugin_dir.exists():
                shutil.rmtree(plugin_dir)
            plugin_dir.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(plugin_dir)
            print(f"[UnifiedPluginManager] Plugin '{plugin_id}' instalado exitosamente")

            return True
        except Exception as e:
            print(f"[UnifiedPluginManager] Error instalando plugin '{plugin_id}': {e}")

            return False


class UnifiedPluginManager(QObject):
    """Gestor unificado de plugins con validación agresiva"""

    # Signals

    plugin_loaded = Signal(str)  # plugin_id

    plugin_unloaded = Signal(str)  # plugin_id

    plugin_enabled = Signal(str)  # plugin_id

    plugin_disabled = Signal(str)  # plugin_id

    plugin_installed = Signal(str)  # plugin_id

    plugin_uninstalled = Signal(str)  # plugin_id

    plugin_error = Signal(str, str)  # plugin_id, error_message

    access_granted = Signal(str)  # plugin_id

    access_denied = Signal(str, str)  # plugin_id, reason

    trial_started = Signal(str)  # plugin_id

    trial_expired = Signal(str)  # plugin_id

    validation_required = Signal(str)  # plugin_id

    def __init__(self, auth_manager: AuthManager = None, parent=None):
        super().__init__(parent)

        # Cargar configuración centralizada

        self.config = get_config()

        # Configuración de backend desde ConfigManager

        self.api_base_url = self.config.get_backend_url()

        logger.info(f"Backend URL configured: {self.api_base_url}")

        # Configuración de plugins desde config.yaml
        # plugins_dir = carpeta ESCRIBIBLE (descargas del backend).
        # bundled_plugins_dir = carpeta de SOLO LECTURA que viaja con la app
        # (paquete base + plugins preinstalados/gratuitos).

        self.plugins_dir = ensure_user_plugins_dir()

        self.bundled_plugins_dir = BUNDLED_PLUGINS_DIR

        # Se ESCRIBE siempre en la copia de usuario; se LEE con fallback a la bundled.
        self.config_file = str(user_config_file())

        self.plugins: Dict[str, PluginBase] = {}

        self.plugin_configs: Dict[str, Dict[str, Any]] = {}

        self.available_plugins: Dict[str, PluginInfo] = {}

        self.trial_starts: Dict[str, float] = {}
        # Validador por defecto de los decoradores premium (widgets sin plugin_validator)
        try:
            from premium_decorators import set_default_validator
            set_default_validator(self)
        except Exception as e:  # pragma: no cover
            logger.warning(f"No se pudo registrar el validador por defecto: {e}")

        # Auth manager

        self.auth_manager = auth_manager or AuthManager()

        # Configuración de validación desde config.yaml

        self.validation_interval = self.config.get_license_validation_interval()  # 300s = 5 min

        self.max_validation_attempts = 3

        self.validation_attempts = {}

        logger.info(f"Plugin Manager initialized - Validation interval: {self.validation_interval}s")

        # Timer para validación periódica

        self.validation_timer = QTimer()

        self.validation_timer.timeout.connect(self._validate_all_plugins)

        self.validation_timer.setInterval(self.validation_interval * 1000)

        # Conectar señales del auth manager

        if self.auth_manager:
            self.auth_manager.auth_state_changed.connect(self.on_auth_state_changed)

            self.auth_manager.plugin_license_changed.connect(self.on_plugin_license_changed)
        # Iniciar validación si está autenticado

        if self.auth_manager and self.auth_manager.auth_state.is_authenticated:
            self.validation_timer.start()

            logger.info("Plugin manager initialized with authentication")
        # Configuración de plugins

        self.plugin_configs_data = {

            "scraping": {

                "name": "Scraping Avanzado",

                "free_features": ["basic_scraping", "simple_export"],

                "premium_features": ["analysis", "interactive_selection", "advanced_scraping", "scheduled_scraping", "javascript_handling", "proxy_rotation", "data_analysis", "export"],

                "trial_days": 7
            },

            "proxy": {

                "name": "Gestor de Proxies",

                "free_features": ["basic_proxy"],

                "premium_features": ["validation", "proxy_rotation", "proxy_testing", "multiple_profiles", "geo_location", "speed_testing"],

                "trial_days": 7
            },

            "themes": {

                "name": "Temas Avanzados",

                "free_features": ["basic_themes"],

                "premium_features": ["custom_themes", "theme_editor", "animated_themes", "import_export"],

                "trial_days": 3
            },
            "seo_analyzer": {

                "name": "SEO Analyzer Pro",

                "free_features": ["basic_seo_check", "simple_analysis"],

                "premium_features": ["advanced_seo_metrics", "competitor_analysis", "keyword_research", "site_audit"],

                "trial_days": 7
            },
            "pentesting_tool": {
                "name": "Pentesting Suite",
                "free_features": ["basic_payloads", "form_detection"],
                "premium_features": ["sql_injection", "xss_testing", "header_manipulation", "security_scanner", "js_console"],
                "trial_days": 7
            },

            "ai_live_ide": {

                "name": "AI Live IDE",

                "free_features": [],

                "premium_features": ["ai_code_edit", "ai_chat", "live_preview", "project_open", "save_file"],

                "trial_days": 7
            },

            "ai_assistant": {

                "name": "Asistente de IA",

                "free_features": ["chat_access"],

                "premium_features": [],

                "trial_days": 0
            },
        }

        # Crear directorio de plugins si no existe

        self.plugins_dir.mkdir(parents=True, exist_ok=True)

        # Cargar configuración

        self.load_configuration()
    def load_configuration(self):
        """Cargar configuración de plugins"""

        try:
            cfg_path = resolve_config_file()

            if cfg_path.exists():
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    self.plugin_configs = json.load(f)
                print(f"[UnifiedPluginManager] Configuración cargada desde {cfg_path}")
        except Exception as e:
            print(f"[UnifiedPluginManager] Error cargando configuración: {e}")

            self.plugin_configs = {}
    def save_configuration(self):
        """Guardar configuración de plugins"""

        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)

            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.plugin_configs, f, indent=2)
            print(f"[UnifiedPluginManager] Configuración guardada en {self.config_file}")
        except Exception as e:
            print(f"[UnifiedPluginManager] Error guardando configuración: {e}")
    def load_available_plugins(self) -> List[PluginInfo]:
        """Cargar plugins disponibles desde el backend"""

        try:
            if not self.auth_manager or not self.auth_manager.auth_state.is_authenticated:
                return []
            # Usar integración con backend

            from backend_integration import backend_integration

            if backend_integration.is_authenticated():
                backend_plugins = backend_integration.get_available_plugins()

                plugins = []

                for backend_plugin in backend_plugins:
                    # Convertir BackendPlugin a PluginInfo

                    plugin_info = PluginInfo(

                        id=backend_plugin.id,

                        name=backend_plugin.name,

                        version=backend_plugin.version,

                        author=backend_plugin.author,

                        description=backend_plugin.description,

                        premium=backend_plugin.price > 0,

                        price=backend_plugin.price,

                        currency=backend_plugin.currency,

                        billing_cycle=backend_plugin.billing_cycle,

                        category=backend_plugin.category,

                        tags=backend_plugin.tags,

                        features=backend_plugin.features,

                        download_url=f"{self.api_base_url}/api/plugins/{backend_plugin.id}/download",

                        info_url=f"{self.api_base_url}/api/plugins/{backend_plugin.id}/info"
                    )

                    self.available_plugins[plugin_info.id] = plugin_info

                    plugins.append(plugin_info)
                return plugins
            else:
                print("[UnifiedPluginManager] Usuario no autenticado en backend")

                return []
        except Exception as e:
            print(f"[UnifiedPluginManager] Error cargando plugins disponibles: {e}")

            return []
    def get_plugin_access(self, plugin_id: str) -> PluginAccessInfo:
        """Obtener información de acceso a un plugin con validación agresiva"""

        # Gratuito o premium lo decide la lista del programa (plugin_policy), NO el
        # plugin_info.json del plugin: ese fichero está en la carpeta de usuario y
        # cualquiera puede editarlo para marcar como gratuito un plugin premium.
        if is_free_plugin(plugin_id):
            logger.info(f"Plugin {plugin_id} access granted: Free plugin (no auth required)")
            return PluginAccessInfo(
                plugin_id=plugin_id,
                plugin_name=plugin_id,
                access_level=PluginAccessLevel.FREE,
                is_licensed=True,  # Free plugins are "licensed" by default
                features_available=[]
            )
        if not self.auth_manager:
            logger.warning(f"Plugin {plugin_id} access denied: No auth manager")

            return PluginAccessInfo(

                plugin_id=plugin_id,

                plugin_name="Plugin Desconocido",

                access_level=PluginAccessLevel.NONE,

                is_licensed=False
            )
        if not self.auth_manager.auth_state.is_authenticated:
            logger.warning(f"Plugin {plugin_id} access denied: User not authenticated")

            return PluginAccessInfo(

                plugin_id=plugin_id,

                plugin_name="Plugin Desconocido",

                access_level=PluginAccessLevel.NONE,

                is_licensed=False
            )
        if plugin_id not in self.plugin_configs_data:
            logger.warning(f"Plugin {plugin_id} access denied: Unknown plugin")

            return PluginAccessInfo(

                plugin_id=plugin_id,

                plugin_name="Plugin Desconocido",

                access_level=PluginAccessLevel.NONE,

                is_licensed=False
            )
        config = self.plugin_configs_data[plugin_id]

        # Verificar si el usuario tiene licencia (validación agresiva)

        is_licensed = self.auth_manager.is_plugin_licensed(plugin_id)

        license_info = self.auth_manager.get_plugin_license(plugin_id)

        # DEBUG: Mostrar información de licencia

        logger.info(f"[DEBUG] Plugin {plugin_id}: is_licensed={is_licensed}, license_info={'EXISTS' if license_info else 'NONE'}")

        if is_licensed and license_info:
            logger.info(f"Plugin {plugin_id} access granted: Licensed")

            return PluginAccessInfo(

                plugin_id=plugin_id,

                plugin_name=config["name"],

                access_level=PluginAccessLevel.PREMIUM,

                is_licensed=True,

                license_info=license_info,

                features_available=config["free_features"] + config["premium_features"]
            )
        # Verificar si está en período de prueba

        if self._is_trial_active(plugin_id):
            trial_remaining = self._get_trial_remaining_days(plugin_id)

            logger.info(f"Plugin {plugin_id} access granted: Trial ({trial_remaining} days remaining)")

            return PluginAccessInfo(

                plugin_id=plugin_id,

                plugin_name=config["name"],

                access_level=PluginAccessLevel.TRIAL,

                is_licensed=False,

                trial_remaining=trial_remaining,

                features_available=config["free_features"] + config["premium_features"]
            )
        # Solo acceso gratuito

        logger.info(f"Plugin {plugin_id} access granted: Free features only")

        return PluginAccessInfo(

            plugin_id=plugin_id,

            plugin_name=config["name"],

            access_level=PluginAccessLevel.FREE,

            is_licensed=False,

            features_available=config["free_features"]
        )
    def can_access_feature(self, plugin_id: str, feature: str) -> bool:
        """Verificar si el usuario puede acceder a una característica específica"""

        access_info = self.get_plugin_access(plugin_id)

        return feature in access_info.features_available
    def request_feature_access(self, plugin_id: str, feature: str, parent_widget: QWidget = None) -> bool:
        """Solicitar acceso a una característica premium"""

        access_info = self.get_plugin_access(plugin_id)

        if feature in access_info.features_available:
            self.access_granted.emit(plugin_id)

            return True
        # Característica no disponible - mostrar diálogo de actualización

        self._show_upgrade_dialog(plugin_id, feature, parent_widget)

        self.access_denied.emit(plugin_id, f"La característica '{feature}' requiere acceso premium")

        return False
    def start_trial(self, plugin_id: str) -> bool:
        """Las pruebas locales están desactivadas: la prueba gratuita de 7 días se
        solicita por email y se concede como licencia temporal en el backend."""
        return False
    def _is_trial_active(self, plugin_id: str) -> bool:
        """Sin pruebas locales (ver start_trial): una prueba concedida en el backend
        llega como licencia normal y se valida con is_plugin_licensed."""
        return False
    def _get_trial_remaining_days(self, plugin_id: str) -> int:
        """Obtener días restantes del período de prueba"""

        if not self._is_trial_active(plugin_id):
            return 0
        config = self.plugin_configs_data.get(plugin_id, {})

        trial_days = config.get("trial_days", 0)

        trial_start = self.trial_starts[plugin_id]

        trial_duration = trial_days * 24 * 60 * 60

        elapsed = time.time() - trial_start

        remaining_seconds = trial_duration - elapsed

        remaining_days = max(0, int(remaining_seconds / (24 * 60 * 60)))

        return remaining_days
    def _show_upgrade_dialog(self, plugin_id: str, feature: str, parent_widget: QWidget = None):
        """Mostrar diálogo de actualización para características premium"""

        config = self.plugin_configs_data.get(plugin_id, {})

        plugin_name = config.get("name", "Plugin")

        msg = QMessageBox(parent_widget)

        msg.setWindowTitle("Característica Premium")

        msg.setIcon(QMessageBox.Information)

        msg.setText(f"La característica '{feature}' requiere una suscripción premium de {plugin_name}.")

        msg.setInformativeText(
            "Visita nuestro sitio web para obtener acceso premium.\n\n"
            "Si quieres probarlo antes, la prueba gratuita de 7 días se solicita "
            "por email a vicrosdev@proton.me."
        )

        upgrade_btn = msg.addButton("Comprar Premium", QMessageBox.ActionRole)

        msg.addButton("Cancelar", QMessageBox.RejectRole)

        msg.setDefaultButton(upgrade_btn)

        msg.exec()

        if msg.clickedButton() == upgrade_btn:
            self._open_upgrade_page(plugin_id)
    def _open_upgrade_page(self, plugin_id: str):
        """Abrir página de actualización en el navegador"""

        import webbrowser

        frontend_url = self.config.get_frontend_url()

        webbrowser.open(f"{frontend_url}/plugins/{plugin_id}")
    def install_plugin(self, plugin_id: str, progress_callback=None) -> bool:
        """Instalar un plugin"""

        try:
            if self.is_plugin_installed(plugin_id):
                print(f"[UnifiedPluginManager] Plugin '{plugin_id}' ya está instalado")

                return True
            # Usar integración con backend

            from backend_integration import backend_integration

            if not backend_integration.is_authenticated():
                self.plugin_error.emit(plugin_id, "Usuario no autenticado")

                return False
            if not backend_integration.has_plugin_access(plugin_id):
                self.plugin_error.emit(plugin_id, "No tienes acceso a este plugin")

                return False
            # Iniciar descarga en thread

            self.downloader = PluginDownloader(plugin_id, self.auth_manager, self)

            if progress_callback:
                self.downloader.progress_updated.connect(progress_callback)
            self.downloader.download_completed.connect(

                lambda pid, success: self._on_download_completed(pid, success)
            )

            self.downloader.error_occurred.connect(

                lambda error: self._on_download_error(plugin_id, error)
            )

            self.downloader.start()

            return True
        except Exception as e:
            print(f"[UnifiedPluginManager] Error iniciando instalación del plugin: {e}")

            self.plugin_error.emit(plugin_id, str(e))

            return False
    def _on_download_completed(self, plugin_id: str, success: bool):
        """Manejar finalización de descarga"""

        if success:
            # Intentar cargar el plugin dinámicamente

            if self.load_plugin(plugin_id):
                self.plugin_installed.emit(plugin_id)

                print(f"[UnifiedPluginManager] Plugin '{plugin_id}' instalado y cargado exitosamente")
            else:
                self.plugin_installed.emit(plugin_id)  # Emitir señal aunque no se cargue

                print(f"[UnifiedPluginManager] Plugin '{plugin_id}' instalado pero no se pudo cargar dinámicamente")
        else:
            self.plugin_error.emit(plugin_id, "Instalación falló")
    def _on_download_error(self, plugin_id: str, error: str):
        """Manejar error de descarga"""

        self.plugin_error.emit(plugin_id, error)

        print(f"[UnifiedPluginManager] Error instalando plugin '{plugin_id}': {error}")
    def is_plugin_installed(self, plugin_id: str) -> bool:
        """Verificar si un plugin está instalado"""

        # Busca en la carpeta de usuario (descargas) y en la bundled (preinstalados).
        plugin_dir = find_plugin_dir(plugin_id)

        # Un plugin está instalado si existe su carpeta y tiene __init__.py
        # (plugins locales) O plugin.py O .plugin_metadata.json (descargados del backend).
        if plugin_dir is None:
            return False
        has_init = (plugin_dir / "__init__.py").exists()
        has_metadata = (plugin_dir / ".plugin_metadata.json").exists()
        has_plugin_py = (plugin_dir / "plugin.py").exists()

        return has_init or has_metadata or has_plugin_py
    def uninstall_plugin(self, plugin_id: str) -> bool:
        """Desinstalar un plugin (solo los descargados a la carpeta de usuario;
        los preinstalados en el bundle no se pueden borrar)."""

        try:
            if is_bundled_only(plugin_id):
                print(
                    f"[UnifiedPluginManager] Plugin '{plugin_id}' es preinstalado "
                    f"(bundle de solo lectura); no se puede desinstalar"
                )
                return False

            plugin_dir = USER_PLUGINS_DIR / plugin_id

            if plugin_dir.exists():
                shutil.rmtree(plugin_dir)

                self.plugin_uninstalled.emit(plugin_id)

                print(f"[UnifiedPluginManager] Plugin '{plugin_id}' desinstalado exitosamente")

                return True
            return False
        except Exception as e:
            print(f"[UnifiedPluginManager] Error desinstalando plugin '{plugin_id}': {e}")

            return False
    def get_installed_plugins(self) -> List[str]:
        """Obtener lista de plugins instalados (usuario + bundled, sin duplicados)"""

        return list(iter_installed_plugin_ids())
    def get_plugin_info(self, plugin_id: str) -> Optional[PluginInfo]:
        """Obtener información detallada de un plugin"""

        return self.available_plugins.get(plugin_id)
    def get_plugin_status_summary(self) -> Dict[str, Dict]:
        """Obtener resumen del estado de todos los plugins"""

        summary = {}

        for plugin_id in self.plugin_configs_data.keys():
            access_info = self.get_plugin_access(plugin_id)

            summary[plugin_id] = {

                "name": access_info.plugin_name,

                "access_level": access_info.access_level.value,

                "is_licensed": access_info.is_licensed,

                "trial_remaining": access_info.trial_remaining,

                "features_count": len(access_info.features_available),

                "is_installed": self.is_plugin_installed(plugin_id)
            }
        return summary
    def on_auth_state_changed(self, is_authenticated: bool):
        """Manejar cambio de estado de autenticación"""

        if is_authenticated:
            for plugin_id in self.plugin_configs_data.keys():
                self.access_granted.emit(plugin_id)
        else:
            for plugin_id in self.plugin_configs_data.keys():
                self.access_denied.emit(plugin_id, "Usuario no autenticado")
    def on_plugin_license_changed(self, plugin_id: str, is_licensed: bool):
        """Manejar cambio de licencia de plugin"""

        if is_licensed:
            self.access_granted.emit(plugin_id)

            logger.info(f"Plugin {plugin_id} license activated")
        else:
            self.access_denied.emit(plugin_id, "Licencia no válida")

            logger.warning(f"Plugin {plugin_id} license deactivated")
    def _validate_all_plugins(self):
        """Validar todos los plugins periódicamente"""

        if not self.auth_manager or not self.auth_manager.auth_state.is_authenticated:
            logger.warning("Plugin validation skipped: User not authenticated")

            return
        logger.info("Starting periodic plugin validation")

        for plugin_id in self.plugin_configs_data.keys():
            try:
                self._validate_plugin_access(plugin_id)
            except Exception as e:
                logger.error(f"Error validating plugin {plugin_id}: {e}")
    def _validate_plugin_access(self, plugin_id: str):
        """Validar acceso a un plugin específico"""

        if not self.auth_manager:
            return
        # Verificar autenticación

        if not self.auth_manager.auth_state.is_authenticated:
            logger.warning(f"Plugin {plugin_id} validation failed: User not authenticated")

            self.validation_required.emit(plugin_id)

            return
        # Verificar licencia

        is_licensed = self.auth_manager.is_plugin_licensed(plugin_id)

        if not is_licensed:
            # Verificar si el trial expiró

            if self._is_trial_active(plugin_id):
                trial_remaining = self._get_trial_remaining_days(plugin_id)

                if trial_remaining <= 0:
                    logger.warning(f"Plugin {plugin_id} trial expired")

                    self.trial_expired.emit(plugin_id)
            else:
                logger.warning(f"Plugin {plugin_id} access denied: No license")

                self.validation_required.emit(plugin_id)
    def force_validation(self, plugin_id: str = None):
        """Forzar validación de plugins"""

        if plugin_id:
            self._validate_plugin_access(plugin_id)
        else:
            self._validate_all_plugins()
        logger.info(f"Forced validation for {'all plugins' if not plugin_id else plugin_id}")
    def get_validation_status(self) -> Dict[str, Any]:
        """Obtener estado de validación del sistema"""

        return {

            "validation_interval": self.validation_interval,

            "validation_attempts": self.validation_attempts,

            "timer_active": self.validation_timer.isActive(),

            "auth_connected": self.auth_manager.is_connected if self.auth_manager else False,

            "plugins_count": len(self.plugin_configs_data),

            "installed_plugins": len(self.get_installed_plugins())
        }
    def load_plugin(self, plugin_id: str) -> bool:
        """

        Cargar un plugin dinámicamente después de la instalación

        Args:
            plugin_id: ID del plugin a cargar
        Returns:
            bool: True si el plugin se cargó exitosamente
        """

        # Idempotencia: si ya está cargado, no reimportar (evita trabajo
        # redundante y doble registro de UI cuando el resync se dispara
        # varias veces en un mismo login).
        if plugin_id in self.plugins:
            return True
        # ENFORCEMENT (punto único): ninguna ruta de carga puede saltarse
        # la validación de licencia. Cubre _load_free_plugins, dev_mode,
        # auto-descubrimiento, force-load y reload_plugin.
        if not self.can_load_plugin(plugin_id):
            return False
        try:
            # Busca en la carpeta de usuario (descargas) y luego en la bundled.
            plugin_dir = find_plugin_dir(plugin_id)

            if plugin_dir is None or not plugin_dir.exists():
                logger.error(f"Plugin directory not found for '{plugin_id}' "
                             f"(buscado en {USER_PLUGINS_DIR} y {BUNDLED_PLUGINS_DIR})")

                return False
            # Verificar que tenga __init__.py

            if not (plugin_dir / "__init__.py").exists():
                logger.warning(f"Plugin {plugin_id} missing __init__.py")
            # Verificar que tenga plugin.py

            # Algunos paquetes (pentesting_tool) vienen anidados: <id>/<id>/plugin.py
            module_prefix = f"plugins.{plugin_id}"
            if not (plugin_dir / "plugin.py").exists() and (plugin_dir / plugin_id / "plugin.py").exists():
                plugin_dir = plugin_dir / plugin_id
                module_prefix = f"plugins.{plugin_id}.{plugin_id}"
            if not (plugin_dir / "plugin.py").exists():
                logger.error(f"Plugin {plugin_id} missing plugin.py")

                return False
            # Importar el módulo dinámicamente

            import importlib.util

            import sys

            # Asegura que la carpeta del plugin está en sys.path para sus
            # imports internos (cada plugin.py también lo hace por su cuenta).
            if str(plugin_dir) not in sys.path:
                sys.path.insert(0, str(plugin_dir))

            module_name = f"{module_prefix}.plugin"

            plugin_file = plugin_dir / "plugin.py"

            spec = importlib.util.spec_from_file_location(module_name, plugin_file)

            if spec is None or spec.loader is None:
                logger.error(f"Could not load plugin spec for {plugin_id}")

                return False
            module = importlib.util.module_from_spec(spec)

            sys.modules[module_name] = module

            spec.loader.exec_module(module)

            # Verificar que el módulo tenga la función initialize_plugin

            if not hasattr(module, 'initialize_plugin'):
                logger.warning(f"Plugin {plugin_id} missing initialize_plugin function")

                return False
            # Inicializar el plugin

            try:
                initialized = module.initialize_plugin()

                if initialized:
                    logger.info(f"Plugin {plugin_id} initialized successfully")

                    self.plugins[plugin_id] = module

                    self.plugin_loaded.emit(plugin_id)

                    return True
                else:
                    logger.warning(f"Plugin {plugin_id} initialization returned False")

                    return False
            except Exception as init_error:
                logger.error(f"Error initializing plugin {plugin_id}: {init_error}")

                return False
        except Exception as e:
            logger.error(f"Error loading plugin {plugin_id}: {e}")

            import traceback

            traceback.print_exc()

            return False
    def unload_plugin(self, plugin_id: str) -> bool:
        """

        Descargar un plugin de la memoria

        Args:
            plugin_id: ID del plugin a descargar
        Returns:
            bool: True si el plugin se descargó exitosamente
        """

        try:
            if plugin_id in self.plugins:
                plugin_instance = self.plugins[plugin_id]

                # Llamar al método shutdown() del plugin si existe
                if hasattr(plugin_instance, 'shutdown'):
                    try:
                        logger.info(f"Calling shutdown() on plugin {plugin_id}")
                        plugin_instance.shutdown()
                    except Exception as e:
                        logger.error(f"Error calling shutdown() on plugin {plugin_id}: {e}")
                # Remover del diccionario

                del self.plugins[plugin_id]

                # Remover del sys.modules

                import sys

                module_name = f"plugins.{plugin_id}.plugin"

                if module_name in sys.modules:
                    del sys.modules[module_name]
                self.plugin_unloaded.emit(plugin_id)

                logger.info(f"Plugin {plugin_id} unloaded successfully")

                return True
            return False
        except Exception as e:
            logger.error(f"Error unloading plugin {plugin_id}: {e}")

            return False
    def get_loaded_plugins(self) -> List[str]:
        """Obtener lista de plugins cargados en memoria"""

        return list(self.plugins.keys())
    def is_plugin_loaded(self, plugin_id: str) -> bool:
        """Verificar si un plugin está cargado en memoria"""

        return plugin_id in self.plugins
    def reload_plugin(self, plugin_id: str) -> bool:
        """Recargar un plugin"""

        if self.is_plugin_loaded(plugin_id):
            if not self.unload_plugin(plugin_id):
                return False
        return self.load_plugin(plugin_id)
    def can_load_plugin(self, plugin_id: str) -> bool:
        """Puerta única de carga: un plugin premium solo se carga con licencia
        confirmada por el backend (o en modo desarrollo desde el código fuente).
        Tener los ficheros instalados en la carpeta de usuario no basta."""
        if is_free_plugin(plugin_id) or dev_mode_allowed():
            return True
        access_info = self.get_plugin_access(plugin_id)
        if access_info.is_licensed and access_info.access_level == PluginAccessLevel.PREMIUM:
            return True
        logger.warning(
            f"Plugin {plugin_id} no se carga: plugin premium sin licencia "
            f"(access_level={access_info.access_level.value})"
        )
        return False
    def load_all_installed_plugins(self) -> Dict[str, bool]:
        """

        Cargar todos los plugins instalados

        Returns:
            Dict[str, bool]: Diccionario con plugin_id -> success
        """

        results = {}

        installed = self.get_installed_plugins()

        logger.info(f"Loading {len(installed)} installed plugins...")

        for plugin_id in installed:
            # Verificar que el usuario tenga acceso

            access_info = self.get_plugin_access(plugin_id)

            # Solo plugins gratuitos o premium con licencia (ver can_load_plugin).
            # Tener los ficheros instalados localmente no basta.
            if self.can_load_plugin(plugin_id):
                success = self.load_plugin(plugin_id)

                results[plugin_id] = success

                if success:
                    logger.info(f"Loaded plugin: {plugin_id} (access_level={access_info.access_level.value})")
                else:
                    logger.warning(f"Failed to load plugin: {plugin_id}")
            else:
                logger.info(f"Skipping plugin {plugin_id} - no access (access_level={access_info.access_level.value}, is_licensed={access_info.is_licensed})")

                results[plugin_id] = False
        return results
