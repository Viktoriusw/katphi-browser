#!/usr/bin/env python3
"""
Resolución de rutas de plugins multiplataforma.

Problema que resuelve
---------------------
Hasta ahora el gestor de plugins usaba ``Path("plugins")`` (relativo al
directorio de trabajo). Eso solo funciona cuando el navegador se ejecuta
desde su carpeta de código fuente en Linux/Mac. En un ejecutable empaquetado
(PyInstaller) — sobre todo en Windows instalado en ``C:\\Program Files\\`` — esa
carpeta es de SOLO LECTURA y el directorio de trabajo es impredecible, así que
descargar e instalar un plugin fallaba.

Modelo
------
- ``BUNDLED_PLUGINS_DIR``  → plugins que viajan DENTRO de la app (solo lectura
  cuando está empaquetada). Contiene el paquete base (``plugin_base.py``,
  ``__init__.py``) y los plugins preinstalados (los gratuitos).
- ``USER_PLUGINS_DIR``     → carpeta ESCRIBIBLE por usuario donde se instalan
  los plugins descargados del backend:
    Windows : %APPDATA%\\Katphi\\plugins
    macOS   : ~/Library/Application Support/Katphi/plugins
    Linux   : $XDG_DATA_HOME/Katphi/plugins  (por defecto ~/.local/share/...)

Los plugins se buscan primero en ``USER_PLUGINS_DIR`` y luego en
``BUNDLED_PLUGINS_DIR``, de modo que una versión descargada/actualizada gana
sobre la preinstalada. El mecanismo de carga (``importlib`` con ruta explícita
de ``plugin.py`` + cada ``plugin.py`` añadiendo su propia carpeta a ``sys.path``)
funciona igual en las tres plataformas: un plugin de Python puro NO necesita una
versión específica por sistema operativo.
"""
from __future__ import annotations

import os
import sys
import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Nombre de la app para la carpeta de datos de usuario (coincide con
# constants.APP_NAME / QSettings("Katphi", ...)).
_APP_DIR_NAME = "Katphi"

# Marcadores que identifican una carpeta como un plugin instalado.
_PLUGIN_MARKERS = ("__init__.py", "plugin.py", ".plugin_metadata.json")


def _app_base_dir() -> Path:
    """Directorio donde vive el código de la app (o los datos embebidos)."""
    if getattr(sys, "frozen", False):
        # PyInstaller: los datos (incluido 'plugins/') se extraen a _MEIPASS.
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(os.path.dirname(sys.executable))
    return Path(__file__).resolve().parent


def _user_data_dir() -> Path:
    """Carpeta de datos de usuario, escribible, según el sistema operativo."""
    if sys.platform.startswith("win"):
        root = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        root = str(Path.home() / "Library" / "Application Support")
    else:
        root = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(root) / _APP_DIR_NAME


BUNDLED_PLUGINS_DIR: Path = _app_base_dir() / "plugins"
USER_PLUGINS_DIR: Path = _user_data_dir() / "plugins"


def ensure_user_plugins_dir() -> Path:
    """Crea (si hace falta) y devuelve la carpeta de plugins de usuario."""
    try:
        USER_PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # pragma: no cover - depende del SO/permETC
        logger.error("No se pudo crear USER_PLUGINS_DIR %s: %s", USER_PLUGINS_DIR, e)
    return USER_PLUGINS_DIR


def register_sys_path() -> None:
    """Asegura que el paquete ``plugins`` (bundled) y la carpeta de usuario
    son importables. Idempotente."""
    ensure_user_plugins_dir()
    for p in (str(_app_base_dir()), str(USER_PLUGINS_DIR)):
        if p and p not in sys.path:
            sys.path.insert(0, p)
    # Los plugins descargados viven fuera del paquete ``plugins`` empaquetado:
    # se añade la carpeta de usuario a su __path__ para que ``plugins.<id>``
    # resuelva también los instalados desde el backend.
    try:
        import plugins as _plugins_pkg
        if str(USER_PLUGINS_DIR) not in list(_plugins_pkg.__path__):
            _plugins_pkg.__path__.append(str(USER_PLUGINS_DIR))
    except Exception as e:  # pragma: no cover
        logger.warning("No se pudo añadir la carpeta de usuario al paquete plugins: %s", e)


def plugin_search_roots() -> List[Path]:
    """Raíces donde se buscan plugins, por prioridad (usuario primero)."""
    return [USER_PLUGINS_DIR, BUNDLED_PLUGINS_DIR]


def _looks_like_plugin(path: Path) -> bool:
    return path.is_dir() and any((path / m).exists() for m in _PLUGIN_MARKERS)


def find_plugin_dir(plugin_id: str) -> Optional[Path]:
    """Devuelve la carpeta del plugin (usuario gana sobre bundled) o ``None``."""
    for root in plugin_search_roots():
        candidate = root / plugin_id
        if candidate.is_dir():
            return candidate
    return None


def install_target_dir(plugin_id: str) -> Path:
    """Carpeta destino para instalar/descargar un plugin (siempre escribible)."""
    ensure_user_plugins_dir()
    return USER_PLUGINS_DIR / plugin_id


def is_bundled_only(plugin_id: str) -> bool:
    """True si el plugin solo existe preinstalado (no se puede desinstalar)."""
    return (
        not (USER_PLUGINS_DIR / plugin_id).is_dir()
        and (BUNDLED_PLUGINS_DIR / plugin_id).is_dir()
    )


def iter_installed_plugin_ids() -> List[str]:
    """IDs de todos los plugins instalados (unión de ambas raíces, sin duplicados)."""
    seen: List[str] = []
    for root in plugin_search_roots():
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if child.name in seen or child.name == "__pycache__":
                continue
            if _looks_like_plugin(child):
                seen.append(child.name)
    return seen


def user_config_file(name: str = "plugin_config.json") -> Path:
    """Ruta ESCRIBIBLE del fichero de configuración de plugins."""
    ensure_user_plugins_dir()
    return USER_PLUGINS_DIR / name


def resolve_config_file(name: str = "plugin_config.json") -> Path:
    """Config de plugins a LEER: la copia de usuario si existe, si no la bundled."""
    user = USER_PLUGINS_DIR / name
    if user.exists():
        return user
    return BUNDLED_PLUGINS_DIR / name


def backups_dir() -> Path:
    """Carpeta escribible para backups de plugins antes de actualizar."""
    d = _user_data_dir() / "plugin_backups"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:  # pragma: no cover
        pass
    return d
