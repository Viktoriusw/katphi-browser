#!/usr/bin/env python3
"""
Lógica de reinicio del navegador con/sin Tor.

Módulo separado para evitar imports circulares.
Debe llamarse init() al inicio de main() con sys.argv.copy().
"""

import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

_sys_argv_original: list = []


def init(argv_copy: list) -> None:
    """Guardar copia de sys.argv para reinicio limpio."""
    global _sys_argv_original
    _sys_argv_original = list(argv_copy)


def restart_with_tor(enabled: bool, window) -> None:
    """
    Guarda configuración Tor, URLs de pestañas y reinicia el navegador.

    Args:
        enabled: True para activar Tor, False para desactivar.
        window: MainWindow para obtener URLs de pestañas abiertas.
    """
    from config_manager import config

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

    os.execv(sys.executable, [sys.executable] + list(_sys_argv_original))
