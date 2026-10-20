#!/usr/bin/env python3
"""
Sistema de Gestión de Configuración Centralizada para Katphi Browser
Maneja la carga y acceso a configuraciones desde config.yaml
"""

import yaml
import os
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, ClassVar
from dataclasses import dataclass

# Configurar logging
logger = logging.getLogger(__name__)


@dataclass
class BackendConfig:
    """Configuración del backend"""
    primary_url: str
    fallback_urls: List[str]
    timeouts: Dict[str, int]
    max_retries: int
    retry_backoff: int
    license_validation: Dict[str, int]


@dataclass
class FrontendConfig:
    """Configuración del frontend"""
    url: str
    registration_url: str
    login_url: str
    dashboard_url: str


@dataclass
class SMTPConfig:
    """Configuración de email"""
    host: str
    port: int
    web_port: int
    from_email: str


@dataclass
class PluginsConfig:
    """Configuración de plugins"""
    directory: str
    cache_duration: int
    validate_checksum: bool
    validate_signature: bool
    create_backup: bool
    backup_directory: str


@dataclass
class SecurityConfig:
    """Configuración de seguridad"""
    use_keyring: bool
    use_qsettings: bool
    secret_key: str
    algorithm: str
    access_token_expire_minutes: int
    refresh_token_expire_days: int


class ConfigManager:
    """
    Gestor centralizado de configuración para Katphi Browser

    Características:
    - Carga configuración desde config.yaml
    - Soporta variables de entorno como override
    - Sistema de fallbacks para URLs
    - Validación de configuración
    - Cache de configuración en memoria
    """

    _instance: ClassVar[Optional["ConfigManager"]] = None
    _config: ClassVar[Optional[Dict[str, Any]]] = None

    def __new__(cls):
        """Singleton pattern para asegurar una sola instancia"""
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
        return cls._instance
    def __init__(self):
        """Inicializar el gestor de configuración"""
        if self._config is None:
            self.config_file = self._find_config_file()
            self.load_config()
    def _find_config_file(self) -> Path:
        """
        Buscar archivo config.yaml en múltiples ubicaciones

        Returns:
            Path: Ruta al archivo de configuración
        """
        # Posibles ubicaciones del archivo de configuración
        possible_paths = [
            Path(__file__).parent / "config.yaml",  # Mismo directorio que este script
            Path.cwd() / "config.yaml",  # Directorio actual
            Path.home() / ".katphi" / "config.yaml",  # Home del usuario
            Path("/etc/katphi/config.yaml"),  # Sistema (Linux)
        ]

        for path in possible_paths:
            if path.exists():
                logger.info(f"Config file found: {path}")
                return path
        # Si no se encuentra, usar el del directorio del script
        default_path = Path(__file__).parent / "config.yaml"
        logger.warning(f"Config file not found, using default: {default_path}")
        return default_path
    def load_config(self):
        """Cargar configuración desde archivo YAML"""
        try:
            if not self.config_file.exists():
                # Sin config.yaml (p. ej. un clon recién descargado): usar la
                # plantilla pública que viaja con el código.
                example = Path(__file__).parent / "config.example.yaml"
                if not example.exists():
                    logger.warning(f"Config file not found: {self.config_file}, usando valores por defecto")
                    self._config = self._get_default_config()
                    return
                # Se lee la plantilla, pero los cambios se guardan en config.yaml.
                logger.info(f"config.yaml no encontrado, usando {example}")
                source = example
            else:
                source = self.config_file
            with open(source, 'r', encoding='utf-8') as f:
                loaded = yaml.safe_load(f)
            # Un YAML vacío devuelve None y uno mal formado puede devolver una
            # lista o un escalar: se ignora y se parte de los valores por defecto.
            if not isinstance(loaded, dict):
                logger.warning(f"{source} vacío o sin formato de diccionario, usando valores por defecto")
                loaded = {}
            # El secret_key por defecto sale de JWT_SECRET: no debe acabar escrito
            # en config.yaml por persist_config si el fichero no lo traía.
            _sec = loaded.get('security')
            self._secret_from_file = isinstance(_sec, dict) and 'secret_key' in _sec
            # Merge profundo: las secciones/claves que falten salen de los defaults
            self._config = self._deep_merge(self._get_default_config(), loaded)
            # Override con variables de entorno
            self._apply_env_overrides()

            logger.info("Configuration loaded successfully")
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            self._config = self._get_default_config()
    @staticmethod
    def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Mezcla override sobre base de forma recursiva (base no se modifica)."""
        result = dict(base)
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = ConfigManager._deep_merge(result[key], value)
            elif value is None and isinstance(result.get(key), dict):
                # "backend:" sin contenido en el YAML: conservar los defaults
                continue
            else:
                result[key] = value
        return result
    def _section(self, name: str) -> Dict[str, Any]:
        """Devuelve una sección como dict (vacío si falta o no es un dict)."""
        value = self._config.get(name) if isinstance(self._config, dict) else None
        return value if isinstance(value, dict) else {}
    def _apply_env_overrides(self):
        """Aplicar overrides desde variables de entorno"""
        # Backend URL
        if os.getenv("KATPHI_BACKEND_URL"):
            self._config.setdefault('backend', {})['primary_url'] = os.getenv("KATPHI_BACKEND_URL")
        # Frontend URL
        if os.getenv("KATPHI_FRONTEND_URL"):
            self._config.setdefault('frontend', {})['url'] = os.getenv("KATPHI_FRONTEND_URL")
        # Network mode
        if os.getenv("KATPHI_NETWORK_MODE"):
            self._config.setdefault('network', {})['mode'] = os.getenv("KATPHI_NETWORK_MODE")
        # Log level
        if os.getenv("KATPHI_LOG_LEVEL"):
            self._config.setdefault('logging', {})['level'] = os.getenv("KATPHI_LOG_LEVEL")
    def _get_default_config(self) -> Dict[str, Any]:
        """
        Obtener configuración por defecto si no se puede cargar el archivo

        Returns:
            Dict: Configuración por defecto
        """
        return {
            'backend': {
                'primary_url': 'https://api.katphi.com',
                'fallback_urls': [],
                'timeouts': {'auth': 15, 'api': 10, 'plugin_download': 60, 'quick_check': 5},
                'max_retries': 3,
                'retry_backoff': 2,
                'license_validation': {'interval': 300, 'cache_duration': 300}
            },
            'frontend': {
                'url': 'https://katphi.com',
                'registration_url': 'https://katphi.com/auth/registro.html',
                'login_url': 'https://katphi.com/auth/login.html',
                'dashboard_url': 'https://katphi.com/app/dashboard.html'
            },
            'smtp': {
                'host': 'localhost',
                'port': 1025,
                'web_port': 8025,
                'from_email': 'noreply@katphi.com'
            },
            'plugins': {
                'directory': '../products',
                'cache_duration': 300,
                'validate_checksum': True,
                'validate_signature': False,
                'create_backup': True,
                'backup_directory': './plugin_backups'
            },
            'security': {
                'use_keyring': False,
                'use_qsettings': True,
                'secret_key': os.environ.get('JWT_SECRET', 'OVERRIDE_WITH_JWT_SECRET_ENV_VAR'),
                'algorithm': 'HS256',
                'access_token_expire_minutes': 30,
                'refresh_token_expire_days': 7
            },
            'network': {
                'mode': 'network',
                'health_check_interval': 30,
                'connection_timeout': 10
            },
            'logging': {
                'level': 'INFO',
                'file': 'katphi_browser.log',
                'max_size': 10485760,
                'backup_count': 3
            },
            'tor': {
                'enabled': False,
                'socks_port': 9150,
                'control_port': 9151,
                'pending_restore_urls': []
            }
        }
    # ============================================
    # MÉTODOS DE ACCESO A CONFIGURACIÓN
    # ============================================

    def get_backend_url(self, use_fallback: bool = False) -> str:
        """
        Obtener URL del backend

        Args:
            use_fallback: Si True, intenta con URLs de fallback
        Returns:
            str: URL del backend
        """
        backend = self._section('backend')
        if use_fallback and backend.get('fallback_urls'):
            return backend['fallback_urls'][0]
        return backend.get('primary_url', 'https://api.katphi.com')
    def get_backend_fallback_urls(self) -> List[str]:
        """Obtener lista de URLs de fallback"""
        return self._section('backend').get('fallback_urls', []) or []
    def get_all_backend_urls(self) -> List[str]:
        """Obtener todas las URLs del backend (primaria + fallbacks)"""
        urls = [self.get_backend_url()]
        urls.extend(self.get_backend_fallback_urls())
        return urls
    def get_frontend_url(self) -> str:
        """Obtener URL del frontend/sitio web"""
        return self._section('frontend').get('url', 'https://katphi.com')
    def get_registration_url(self) -> str:
        """Obtener URL de registro"""
        return self._section('frontend').get('registration_url', 
                                           f"{self.get_frontend_url()}/auth/registro.html")
    def get_login_url(self) -> str:
        """Obtener URL de login"""
        return self._section('frontend').get('login_url',
                                           f"{self.get_frontend_url()}/auth/login.html")
    def get_dashboard_url(self) -> str:
        """Obtener URL del dashboard web"""
        return self._section('frontend').get('dashboard_url',
                                           f"{self.get_frontend_url()}/app/dashboard.html")
    def get_timeout(self, operation: str = 'api') -> int:
        """
        Obtener timeout para tipo de operación específica

        Args:
            operation: Tipo de operación ('auth', 'api', 'plugin_download', 'quick_check')
        Returns:
            int: Timeout en segundos
        """
        timeouts = self._section('backend').get('timeouts')
        return timeouts.get(operation, 10) if isinstance(timeouts, dict) else 10
    def get_max_retries(self) -> int:
        """Obtener número máximo de reintentos"""
        return self._section('backend').get('max_retries', 5)
    def get_retry_backoff(self) -> float:
        """Obtener multiplicador de backoff exponencial"""
        return self._section('backend').get('retry_backoff', 2.0)
    def get_initial_retry_delay(self) -> float:
        """Obtener delay inicial antes del primer reintento (segundos)"""
        return self._section('backend').get('initial_retry_delay', 1.0)
    def get_max_retry_delay(self) -> float:
        """Obtener delay máximo entre reintentos (segundos)"""
        return self._section('backend').get('max_retry_delay', 30.0)
    def get_license_validation_interval(self) -> int:
        """Obtener intervalo de validación de licencias (en segundos)"""
        lv = self._section('backend').get('license_validation')
        return lv.get('interval', 300) if isinstance(lv, dict) else 300
    def get_license_cache_duration(self) -> int:
        """Obtener duración del caché de licencias (en segundos)"""
        lv = self._section('backend').get('license_validation')
        return lv.get('cache_duration', 300) if isinstance(lv, dict) else 300
    def get_smtp_config(self) -> SMTPConfig:
        """Obtener configuración de SMTP"""
        smtp = self._section('smtp')
        return SMTPConfig(
            host=smtp.get('host', 'localhost'),
            port=smtp.get('port', 1025),
            web_port=smtp.get('web_port', 8025),
            from_email=smtp.get('from_email', 'noreply@katphi.com')
        )
    def get_plugins_directory(self) -> str:
        """Obtener directorio de plugins"""
        return self._section('plugins').get('directory', '../products')
    def use_keyring_for_tokens(self) -> bool:
        """Verificar si se debe usar keyring para tokens"""
        return self._section('security').get('use_keyring', False)
    def use_qsettings_for_tokens(self) -> bool:
        """Verificar si se debe usar QSettings para tokens"""
        return self._section('security').get('use_qsettings', True)
    def get_log_level(self) -> str:
        """Obtener nivel de logging"""
        return self._section('logging').get('level', 'INFO')
    def get_log_file(self) -> str:
        """Obtener archivo de log"""
        return self._section('logging').get('file', 'katphi_browser.log')
    def get(self, key: str, default: Any = None) -> Any:
        """
        Obtener valor de configuración usando dot notation

        Args:
            key: Clave en formato dot notation (ej: 'plugins.validate_checksum')
            default: Valor por defecto si la clave no existe
        Returns:
            Any: Valor de configuración o default
        Examples:
            >>> config.get('plugins.validate_checksum', True)
            True
            >>> config.get('plugins.backup_directory', './backups')
            './plugin_backups'
        """
        keys = key.split('.')
        value = self._config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value
    # ============================================
    # MÉTODOS ÚTILES
    # ============================================

    def reload_config(self):
        """Recargar configuración desde archivo"""
        logger.info("Reloading configuration...")
        self.load_config()
    def get_raw_config(self) -> Dict[str, Any]:
        """Obtener configuración raw completa"""
        return self._config
    # ============================================
    # MÉTODOS TOR
    # ============================================

    def _ensure_tor_section(self) -> None:
        """Asegura que la sección tor existe en la configuración."""
        if not isinstance(self._config, dict):
            self._config = self._get_default_config()
        if not isinstance(self._config.get('tor'), dict):
            self._config['tor'] = {}
        tor = self._config['tor']
        tor.setdefault('enabled', False)
        tor.setdefault('socks_port', 9150)
        tor.setdefault('control_port', 9151)
        tor.setdefault('pending_restore_urls', [])
    def get_tor_config(self) -> dict:
        """Obtener configuración completa de Tor."""
        self._ensure_tor_section()
        return dict(self._config['tor'])
    def is_tor_enabled(self) -> bool:
        """Verificar si Tor está habilitado."""
        self._ensure_tor_section()
        return bool(self._config['tor'].get('enabled', False))
    def set_tor_enabled(self, enabled: bool) -> None:
        """Establecer si Tor está habilitado."""
        self._ensure_tor_section()
        self._config['tor']['enabled'] = bool(enabled)
    def get_tor_pending_urls(self) -> List[str]:
        """Obtener URLs a restaurar tras reinicio por Tor."""
        self._ensure_tor_section()
        urls = self._config['tor'].get('pending_restore_urls', [])
        return list(urls) if isinstance(urls, list) else []
    def set_tor_pending_urls(self, urls: List[str]) -> None:
        """Establecer URLs a restaurar tras reinicio."""
        self._ensure_tor_section()
        self._config['tor']['pending_restore_urls'] = list(urls)
    def clear_tor_pending_urls(self) -> None:
        """Limpiar URLs pendientes de restaurar."""
        self._ensure_tor_section()
        self._config['tor']['pending_restore_urls'] = []
    def persist_config(self) -> None:
        """Persistir configuración actual al archivo YAML."""
        try:
            self._ensure_tor_section()
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            # Escritura atómica: fichero temporal en el mismo directorio y
            # os.replace, para no dejar un config.yaml truncado si se corta.
            import tempfile
            fd, tmp_path = tempfile.mkstemp(
                prefix=".config.", suffix=".yaml.tmp", dir=str(self.config_file.parent)
            )
            try:
                data = self._config
                if not getattr(self, '_secret_from_file', False) and isinstance(data.get('security'), dict):
                    data = dict(data)
                    data['security'] = {k: v for k, v in data['security'].items() if k != 'secret_key'}
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, self.config_file)
            except BaseException:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                raise
            logger.info("Configuration persisted to %s", self.config_file)
        except Exception as e:
            logger.error("Error persisting config: %s", e)
    def print_config(self):
        """Imprimir configuración actual (para debugging)"""
        print("=" * 60)
        print("KATPHI BROWSER - CONFIGURACIÓN ACTUAL")
        print("=" * 60)
        print(f"Backend URL: {self.get_backend_url()}")
        print(f"Frontend URL: {self.get_frontend_url()}")
        print(f"Timeouts: {self._section('backend').get('timeouts')}")
        print(f"Max Retries: {self.get_max_retries()}")
        print(f"Log Level: {self.get_log_level()}")
        print("=" * 60)


# Instancia global única (singleton)
config = ConfigManager()


# ============================================
# FUNCIONES DE CONVENIENCIA
# ============================================

def get_backend_url() -> str:
    """Función de conveniencia para obtener URL del backend"""
    return config.get_backend_url()


def get_frontend_url() -> str:
    """Función de conveniencia para obtener URL del frontend"""
    return config.get_frontend_url()


def get_registration_url() -> str:
    """Función de conveniencia para obtener URL de registro"""
    return config.get_registration_url()


def get_config() -> ConfigManager:
    """Obtener instancia del ConfigManager"""
    return config


if __name__ == "__main__":
    # Test del ConfigManager
    print("Testing ConfigManager...")
    config.print_config()

    print("\nTesting accessors...")
    print(f"Backend URL: {get_backend_url()}")
    print(f"Frontend URL: {get_frontend_url()}")
    print(f"Registration URL: {get_registration_url()}")
    print(f"Auth timeout: {config.get_timeout('auth')}s")
    print(f"Plugin download timeout: {config.get_timeout('plugin_download')}s")
