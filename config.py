#!/usr/bin/env python3
"""
Configuración del navegador Katphi

OBSOLETO: Este archivo está DEPRECADO y se mantendrá solo por compatibilidad.
USAR: ConfigManager (config_manager.py) con config.yaml para todas las configuraciones nuevas.
Este archivo será eliminado en una versión futura.

Migración:
- Las configuraciones de este archivo deben moverse a config.yaml
- Usar ConfigManager para acceder a configuraciones en lugar de importar este módulo
"""

import warnings
warnings.warn(
    "config.py está deprecado. Use ConfigManager con config.yaml",
    DeprecationWarning,
    stacklevel=2
)

# Configuración de rendimiento
PERFORMANCE_CONFIG = {
    # Cargar filtros de adblocking de forma asíncrona
    "async_filter_loading": True,

    # Cargar solo filtros básicos al inicio
    "load_basic_filters_only": True,

    # Deshabilitar filtros pesados en desarrollo
    "skip_heavy_filters": True,

    # Timeout para operaciones de red
    "network_timeout": 5,

    # Límite de reglas de filtro (muy reducido para desarrollo)
    "max_filter_rules": 100,

    # Deshabilitar carga de filtros pesados completamente
    "disable_heavy_filters": True,
}

# Configuración de autenticación
AUTH_CONFIG = {
    # Timeout para login
    "login_timeout": 3,

    # Máximo de intentos de login
    "max_login_attempts": 3,

    # Intervalo entre intentos (segundos)
    "login_retry_delay": 1,
}

# Configuración de UI
UI_CONFIG = {
    # Mostrar mensajes de debug
    "debug_messages": True,

    # Animaciones habilitadas
    "animations_enabled": True,

    # Tema por defecto
    "default_theme": "light",
}
