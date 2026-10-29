#!/usr/bin/env python3
"""
Registro de manejadores de archivo para plugins.

Un plugin registra las extensiones y tipos MIME que sabe abrir (p. ej. Katphi
Office: .pdf, .docx, .xlsx...) y una función que recibe la ruta del archivo.
El núcleo lo consulta al descargar (ofrece "Abrir en ..." además de
"Guardar"), al abrir archivos locales desde la línea de comandos o al
arrastrarlos a la ventana.

Si varios plugins abren la misma extensión gana el de mayor prioridad (el
editor premium por encima del visor gratuito).
"""
from __future__ import annotations

import logging
import mimetypes
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class FileHandler:
    plugin_id: str
    extensions: frozenset
    mime_types: frozenset
    open_callback: Callable[[str], bool]
    label: str
    priority: int = 0
    extra: dict = field(default_factory=dict)


_handlers: Dict[str, FileHandler] = {}


def _norm_ext(ext: str) -> str:
    ext = ext.lower().strip()
    return ext if ext.startswith(".") else "." + ext


def register(plugin_id: str, extensions: Iterable[str], mime_types: Iterable[str],
             open_callback: Callable[[str], bool], label: str, priority: int = 0) -> None:
    """Registra (o sustituye) el manejador de un plugin."""
    _handlers[plugin_id] = FileHandler(
        plugin_id=plugin_id,
        extensions=frozenset(_norm_ext(e) for e in extensions),
        mime_types=frozenset(m.lower() for m in mime_types),
        open_callback=open_callback, label=label, priority=priority)
    logger.info("[file_handlers] %s abre %d extensiones", plugin_id, len(_handlers[plugin_id].extensions))


def unregister(plugin_id: str) -> None:
    _handlers.pop(plugin_id, None)


def handlers() -> List[FileHandler]:
    return sorted(_handlers.values(), key=lambda h: -h.priority)


def find(filename: str = "", mime_type: str = "") -> Optional[FileHandler]:
    """Manejador de mayor prioridad para ese nombre de archivo o tipo MIME."""
    ext = os.path.splitext(filename or "")[1].lower()
    mime = (mime_type or "").lower().split(";")[0].strip()
    if not mime and filename:
        mime = (mimetypes.guess_type(filename)[0] or "").lower()
    for h in handlers():
        if ext and ext in h.extensions:
            return h
    # Por MIME solo si la extensión no dice nada (descargas sin nombre útil)
    generic = ("application/octet-stream", "binary/octet-stream", "")
    for h in handlers():
        if mime and mime not in generic and mime in h.mime_types:
            return h
    return None


def open_path(path: str) -> bool:
    """Abre un archivo local con su manejador. False si no hay ninguno."""
    if not path or not os.path.isfile(path):
        return False
    h = find(path)
    if h is None:
        return False
    try:
        return bool(h.open_callback(os.path.abspath(path)))
    except Exception as e:
        logger.error("[file_handlers] %s no pudo abrir %s: %s", h.plugin_id, path, e)
        return False
