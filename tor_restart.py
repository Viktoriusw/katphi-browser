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

# El estado de Tor (todas las ventanas, también la privada) viaja en
# config_manager.TOR_SESSION_ENV: Tor solo de sesión, nunca en config.yaml.

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
    Activa/desactiva Tor para ESTA sesión, guarda las URLs de las pestañas y
    reinicia el navegador. El estado de Tor no se guarda en config.yaml: viaja
    en el entorno (os.execv lo conserva) y desaparece al cerrar el navegador.

    Args:
        enabled: True para activar Tor, False para desactivar.
        window: MainWindow para obtener URLs de pestañas abiertas.
    """
    from config_manager import config
    from constants import is_private_mode

    private = is_private_mode()
    argv = _clean_argv(_sys_argv_original or sys.argv)
    config.set_tor_enabled(enabled)

    if private:
        # Ventana privada: sin URLs pendientes en config.yaml.
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
    config.persist_config()

    relaunch(argv)
