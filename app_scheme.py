#!/usr/bin/env python3
"""
Esquema katphi-app:// para las aplicaciones web de los plugins.

Cada plugin registra un host (katphi-app://<plugin_id>/...) y sirve desde él
sus archivos estáticos y, si quiere, contenido generado (p. ej. el documento
abierto en Katphi Office). La página es un contexto seguro (SecureScheme):
puede usar Web Workers, WebAssembly y fetch() contra su propio origen.

Seguridad:
- Una web normal no puede cargar ni pedir nada de katphi-app://: las
  peticiones cuyo iniciador no sea el mismo host katphi-app se rechazan.
- Los archivos estáticos se sirven solo desde la carpeta registrada (sin
  "..", enlaces fuera de ella ni rutas absolutas).
- Cada respuesta lleva la CSP del host (por defecto sin red externa).

register_scheme() debe llamarse ANTES de crear la QApplication (lo hace
main.py); install_on_profile() en cada QWebEngineProfile que vaya a abrir
estas páginas.
"""
from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject
from PySide6.QtWebEngineCore import (QWebEngineUrlRequestJob, QWebEngineUrlScheme,
                                     QWebEngineUrlSchemeHandler)

logger = logging.getLogger(__name__)

SCHEME = "katphi-app"
_SCHEME_B = SCHEME.encode()

# Sin red externa: solo el propio origen, data: y blob:
DEFAULT_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
               "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
               "worker-src 'self' blob:; object-src 'none'; frame-src 'none'; "
               "base-uri 'none'; form-action 'none'")

_EXTRA_TYPES = {
    ".mjs": "text/javascript", ".js": "text/javascript", ".css": "text/css",
    ".html": "text/html", ".json": "application/json", ".svg": "image/svg+xml",
    ".wasm": "application/wasm", ".bcmap": "application/octet-stream",
    ".pfb": "application/octet-stream", ".ttf": "font/ttf", ".woff2": "font/woff2",
    ".ftl": "text/plain",
}

# Respuesta dinámica: (content_type, bytes) o None (404)
DynamicHandler = Callable[[str, QWebEngineUrlRequestJob], Optional[Tuple[str, bytes]]]

_registered = False
_hosts: Dict[str, dict] = {}
_handler = None
_profiles: set = set()


def register_scheme() -> None:
    """Registra katphi-app en Qt WebEngine (antes de crear la QApplication)."""
    global _registered
    if _registered:
        return
    scheme = QWebEngineUrlScheme(_SCHEME_B)
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    F = QWebEngineUrlScheme.Flag
    scheme.setFlags(F.SecureScheme | F.CorsEnabled | F.FetchApiAllowed)
    QWebEngineUrlScheme.registerScheme(scheme)
    _registered = True


def is_registered() -> bool:
    return _registered


def register_app_host(host: str, root_dir, dynamic: Optional[DynamicHandler] = None,
                      csp: str = DEFAULT_CSP, cross_origin_isolated: bool = False) -> None:
    """Sirve root_dir en katphi-app://<host>/ (y rutas dinámicas con `dynamic`).

    dynamic(path, job) se consulta antes que los archivos: devuelve
    (content_type, bytes) para responder, o None para seguir con los estáticos.
    """
    host = host.lower()
    _hosts[host] = {
        "root": Path(root_dir).resolve() if root_dir else None,
        "dynamic": dynamic,
        "csp": csp,
        "coi": cross_origin_isolated,
    }
    logger.info("[app_scheme] Host registrado: %s://%s/", SCHEME, host)


def unregister_app_host(host: str) -> None:
    _hosts.pop(host.lower(), None)


def app_url(host: str, path: str = "") -> str:
    return f"{SCHEME}://{host.lower()}/{path.lstrip('/')}"


def is_app_url(url) -> bool:
    try:
        scheme = url.scheme() if hasattr(url, "scheme") else str(url).split(":", 1)[0]
    except Exception:
        return False
    return str(scheme).lower() == SCHEME


class _AppSchemeHandler(QWebEngineUrlSchemeHandler):

    def requestStarted(self, job: QWebEngineUrlRequestJob) -> None:
        try:
            url = job.requestUrl()
            host = url.host().lower()
            entry = _hosts.get(host)
            if entry is None:
                job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
                return
            if not self._initiator_allowed(job, host):
                logger.warning("[app_scheme] Petición a %s bloqueada (iniciador %s)",
                               url.toString(), job.initiator().toString())
                job.fail(QWebEngineUrlRequestJob.Error.RequestDenied)
                return
            if bytes(job.requestMethod()).upper() not in (b"GET", b"HEAD"):
                job.fail(QWebEngineUrlRequestJob.Error.RequestDenied)
                return
            path = url.path() or "/"
            result = None
            if entry["dynamic"] is not None:
                result = entry["dynamic"](path, job)
            if result is None:
                result = self._static(entry["root"], path)
            if result is None:
                job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
                return
            content_type, data = result
            self._reply(job, content_type, data, entry)
        except Exception as e:
            logger.error("[app_scheme] Error sirviendo %s: %s", job.requestUrl().toString(), e)
            try:
                job.fail(QWebEngineUrlRequestJob.Error.RequestFailed)
            except Exception:
                pass

    @staticmethod
    def _initiator_allowed(job, host: str) -> bool:
        """Solo navegaciones del navegador (sin iniciador) o el mismo host."""
        initiator = job.initiator()
        if initiator.isEmpty():
            return True
        return initiator.scheme().lower() == SCHEME and initiator.host().lower() == host

    @staticmethod
    def _static(root: Optional[Path], path: str):
        if root is None:
            return None
        rel = path.lstrip("/") or "index.html"
        if "\x00" in rel or rel.startswith(("/", "\\")):
            return None
        target = (root / rel).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return None   # fuera de la carpeta del host (.., enlaces)
        if not target.is_file():
            return None
        ext = target.suffix.lower()
        ctype = _EXTRA_TYPES.get(ext) or mimetypes.guess_type(target.name)[0] \
            or "application/octet-stream"
        return ctype, target.read_bytes()

    def _reply(self, job, content_type: str, data: bytes, entry: dict) -> None:
        headers = {b"Content-Security-Policy": entry["csp"].encode(),
                   b"X-Content-Type-Options": b"nosniff",
                   b"Cache-Control": b"no-store"}
        if entry["coi"]:
            headers[b"Cross-Origin-Opener-Policy"] = b"same-origin"
            headers[b"Cross-Origin-Embedder-Policy"] = b"require-corp"
        # PySide6 convierte el dict a QMultiMap: cada valor va en una lista (un
        # QByteArray suelto se trocea carácter a carácter y rompe la CSP)
        try:
            job.setAdditionalResponseHeaders(
                {QByteArray(k): [QByteArray(v)] for k, v in headers.items()})
        except Exception as e:
            logger.error("[app_scheme] No se pudieron fijar las cabeceras: %s", e)
        buf = QBuffer(job)
        buf.setData(QByteArray(data))
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        ctype = content_type.encode()
        if content_type.startswith("text/") or content_type in ("application/json",):
            if b"charset" not in ctype:
                ctype += b"; charset=utf-8"
        job.reply(ctype, buf)


def install_on_profile(profile) -> None:
    """Instala el manejador de katphi-app en el perfil (una vez por perfil)."""
    global _handler
    if not _registered or profile is None:
        return
    key = id(profile)
    if key in _profiles:
        return
    if _handler is None:
        from PySide6.QtWidgets import QApplication
        _handler = _AppSchemeHandler(QApplication.instance())
    try:
        if profile.urlSchemeHandler(_SCHEME_B) is None:
            profile.installUrlSchemeHandler(_SCHEME_B, _handler)
        _profiles.add(key)
    except Exception as e:
        logger.error("[app_scheme] No se pudo instalar en el perfil: %s", e)
