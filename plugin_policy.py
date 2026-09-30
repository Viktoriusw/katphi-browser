#!/usr/bin/env python3
"""
Política de acceso a plugins: qué es gratuito y cuándo se permite el modo desarrollo.

Vive en el código de la aplicación (dentro del ejecutable) a propósito: los
ficheros que acompañan a cada plugin (plugin_info.json, plugin_config.json) se
instalan en la carpeta de usuario (%APPDATA%\\Katphi\\plugins en Windows),
que el propio usuario puede editar. Nada de lo que haya ahí puede decidir si un
plugin premium se carga sin licencia.
"""
from __future__ import annotations

import os
import sys

# Únicos plugins que se cargan sin sesión ni licencia. Cualquier otro plugin,
# diga lo que diga su plugin_info.json, es premium y necesita licencia del backend.
FREE_PLUGIN_IDS = frozenset({"themes", "split_view"})


def is_free_plugin(plugin_id: str) -> bool:
    return plugin_id in FREE_PLUGIN_IDS


def dev_mode_allowed() -> bool:
    """Modo desarrollo (cargar plugins premium sin licencia): solo ejecutando desde
    el código fuente con KATPHI_DEV=1. Nunca en el ejecutable empaquetado."""
    if getattr(sys, "frozen", False):
        return False
    return os.environ.get("KATPHI_DEV") == "1"
