#!/usr/bin/env python3
"""
Lógica de reinicio del navegador con/sin Tor.

Módulo separado para evitar imports circulares: es la API que debe usarse
(``from tor_restart import restart_with_tor``), nunca ``from main import ...``,
que vuelve a ejecutar main.py como otro módulo (C-008).
main.py llama a init() al arrancar con la copia de sys.argv original.
"""

import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

_sys_argv_original: list = []

# En una ventana privada no se toca config.yaml: el estado de Tor deseado se
# pasa al proceso relanzado por el entorno (sobrevive a os.execv).
PRIVATE_TOR_ENV = "KATPHI_PRIVATE_TOR"

# Flags de proxy que main.py añade a argv con Tor activo; nunca deben
# arrastrarse al proceso relanzado (las vuelve a decidir main.py).
_TOR_ARG_PREFIXES = (
    "--proxy-server=",
    "--host-resolver-rules=",
    "--proxy-bypass-list=",
    "--force-webrtc-ip-handling-policy=",
)


def _clean_argv(argv: list) -> list:
    return [a for a in argv if not a.startswith(_TOR_ARG_PREFIXES) and a != "--disable-webrtc"]


def init(argv_copy: list) -> None:
    """Guardar copia de sys.argv para reinicio limpio."""
    global _sys_argv_original
    _sys_argv_original = list(argv_copy)


def relaunch(argv: list = None) -> None:
    """Reemplaza el proceso actual (os.execv) por una instancia nueva.

    Usa el argv original (sin flags de proxy de Tor). Congelado con
    PyInstaller, argv[0] ya es el ejecutable, así que no se repite.
    """
    args = _clean_argv(list(argv if argv is not None else (_sys_argv_original or sys.argv)))
    if getattr(sys, "frozen", False):
        args = args[1:]
    os.execv(sys.executable, [sys.executable] + args)


def restart_with_tor(enabled: bool, window) -> None:
    """
    Guarda configuración Tor, URLs de pestañas y reinicia el navegador.

    Args:
        enabled: True para activar Tor, False para desactivar.
        window: MainWindow para obtener URLs de pestañas abiertas.
    """
    from config_manager import config
    from constants import is_private_mode

    private = is_private_mode()
    argv = _clean_argv(_sys_argv_original or sys.argv)

    if private:
        # Ventana privada: ni URLs pendientes ni persistencia en config.yaml.
        os.environ[PRIVATE_TOR_ENV] = "1" if enabled else "0"
        if "--private" not in argv:
            argv.append("--private")
        relaunch(argv)
        return

    if window and hasattr(window, "tab_manager"):
        urls = []
        try:
            for i in range(window.tab_manager.tabs.count()):
                w = window.tab_manager.tabs.widget(i)
                if w and hasattr(w, "url"):
                    url = w.url().toString()
                    if url and url not in ("about:blank", ""):
                        urls.append(url)
        except Exception:
            pass
        config.set_tor_pending_urls(urls)
    config.set_tor_enabled(enabled)
    config.persist_config()

    relaunch(argv)
