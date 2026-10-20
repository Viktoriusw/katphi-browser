#!/usr/bin/env python3
"""
favicon_manager.py — Gestor asíncrono de favicons con caché en disco.

Descarga favicons directamente desde {scheme}://{domain}/favicon.ico sin
depender de servicios externos. Las imágenes se cachean en disco para no
volver a descargarlas en cada arranque.

Uso:
    fm = get_favicon_manager()
    icon = fm.get(url)          # None si no está cacheado → inicia descarga
    fm.favicon_ready.connect(callback)   # callback(domain: str, icon: QIcon)
    fm.store(url, icon)         # alimentar con iconos ya obtenidos (WebEngine)
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkProxy,
    QNetworkReply,
    QNetworkRequest,
)

logger = logging.getLogger(__name__)


def _private_mode() -> bool:
    """Ventana privada: los favicons solo se guardan en memoria."""
    try:
        from constants import is_private_mode
        return bool(is_private_mode())
    except Exception:
        return False

# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: "FaviconManager | None" = None


def get_favicon_manager() -> "FaviconManager":
    global _instance
    if _instance is None:
        _instance = FaviconManager()
    return _instance


# ── Manager ───────────────────────────────────────────────────────────────────

class FaviconManager(QObject):
    """
    Gestor asíncrono de favicons.

    - Memoria: dict domain → QIcon (se pierde al cerrar)
    - Disco:   ~/.cache/katphi/favicons/{md5(domain)}.png
    - Red:     descarga favicon.ico directamente del dominio (sin terceros)
    """

    favicon_ready = Signal(str, QIcon)   # domain, icon

    _SIZE = 16           # píxeles a los que se escala el favicon
    _CACHE_DIR = Path.home() / ".cache" / "katphi" / "favicons"

    def __init__(self) -> None:
        super().__init__()
        self._mem: dict[str, QIcon] = {}
        self._pending: set[str] = set()
        self._private = _private_mode()
        if not self._private:
            self._CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._nam = QNetworkAccessManager(self)
        self._nam.setRedirectPolicy(
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy
        )

    # ── API pública ───────────────────────────────────────────────────────────

    def get(self, url: str) -> QIcon | None:
        """
        Devuelve el favicon si está disponible (memoria o disco).
        Si no, inicia la descarga asíncrona y devuelve None.
        Conectar a favicon_ready para recibir el icono cuando llegue.
        """
        domain = _domain(url)
        if not domain:
            return None

        if domain in self._mem:
            return self._mem[domain]

        disk_icon = self._from_disk(domain)
        if disk_icon:
            self._mem[domain] = disk_icon
            return disk_icon

        self._fetch(domain)
        return None

    def store(self, url: str, icon: QIcon) -> None:
        """
        Almacena un favicon ya obtenido externamente (p. ej. desde
        QWebEngineView.iconChanged). Emite favicon_ready si es nuevo.
        """
        domain = _domain(url)
        if not domain or icon.isNull():
            return
        if domain in self._mem:
            return   # ya tenemos uno
        pix = icon.pixmap(self._SIZE, self._SIZE)
        if pix.isNull():
            return
        self._mem[domain] = icon
        self._save_to_disk(pix, domain)
        self.favicon_ready.emit(domain, icon)

    def clear_cache(self) -> None:
        """Vacía la caché en memoria y en disco (lo usa "Limpiar datos")."""
        self._mem.clear()
        try:
            if self._CACHE_DIR.is_dir():
                for entry in self._CACHE_DIR.iterdir():
                    try:
                        if entry.is_file() or entry.is_symlink():
                            entry.unlink()
                    except OSError as exc:
                        logger.debug("No se pudo borrar %s: %s", entry, exc)
        except OSError as exc:
            logger.debug("Error vaciando la caché de favicons: %s", exc)

    def prefetch(self, url: str) -> None:
        """Inicia la descarga en background sin retornar resultado."""
        domain = _domain(url)
        if domain and domain not in self._mem and not self._from_disk(domain):
            self._fetch(domain)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _disk_path(self, domain: str) -> Path:
        safe = hashlib.md5(domain.encode()).hexdigest()
        return self._CACHE_DIR / f"{safe}.png"

    def _save_to_disk(self, pix: QPixmap, domain: str) -> None:
        if self._private:
            return
        try:
            self._CACHE_DIR.mkdir(parents=True, exist_ok=True)
            pix.save(str(self._disk_path(domain)), "PNG")
        except Exception as exc:
            logger.debug("No se pudo guardar el favicon de %s: %s", domain, exc)

    def _from_disk(self, domain: str) -> QIcon | None:
        if self._private:
            return None
        path = self._disk_path(domain)
        if path.exists():
            pix = QPixmap()
            if pix.load(str(path)) and not pix.isNull():
                return QIcon(pix)
        return None

    def _fetch(self, domain: str) -> None:
        if domain in self._pending:
            return
        self._pending.add(domain)
        # Intentar primero HTTPS, luego HTTP en _on_reply si falla
        self._request(f"https://{domain}/favicon.ico", domain, https=True)

    def _request(self, favicon_url: str, domain: str, *, https: bool) -> None:
        req = QNetworkRequest(QUrl(favicon_url))
        req.setRawHeader(b"User-Agent", b"Mozilla/5.0 (compatible; Katphi)")
        self._apply_proxy()
        reply = self._nam.get(req)
        reply.finished.connect(
            lambda: self._on_reply(reply, domain, https_attempt=https)
        )

    def _apply_proxy(self) -> None:
        """Con Tor activo, la descarga va por el SOCKS de Tor (B-002).

        No depende de que main.py haya fijado el proxy de aplicación: se
        decide en cada petición, por si Tor se activa o desactiva en caliente.
        Sin Tor se usa el proxy de aplicación/sistema (DefaultProxy).
        """
        try:
            from net_proxy import is_tor_active, tor_socks_port
            if is_tor_active():
                self._nam.setProxy(QNetworkProxy(
                    QNetworkProxy.ProxyType.Socks5Proxy, "127.0.0.1", tor_socks_port()
                ))
            else:
                self._nam.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.DefaultProxy))
        except Exception as exc:
            logger.debug("Favicons: no se pudo configurar el proxy: %s", exc)

    def _on_reply(self, reply: QNetworkReply, domain: str, *, https_attempt: bool) -> None:
        try:
            ok = reply.error() == QNetworkReply.NetworkError.NoError
            if ok:
                data = reply.readAll()
                pix = QPixmap()
                if pix.loadFromData(data) and not pix.isNull():
                    pix = pix.scaled(
                        self._SIZE, self._SIZE,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    icon = QIcon(pix)
                    self._mem[domain] = icon
                    self._save_to_disk(pix, domain)
                    self._pending.discard(domain)
                    self.favicon_ready.emit(domain, icon)
                    return

            # HTTPS falló → intentar HTTP como fallback
            if https_attempt:
                self._pending.discard(domain)
                self._pending.add(domain)
                self._request(f"http://{domain}/favicon.ico", domain, https=False)
            else:
                self._pending.discard(domain)
        except Exception as exc:
            logger.debug("Error favicon %s: %s", domain, exc)
            self._pending.discard(domain)
        finally:
            reply.deleteLater()


# ── Utilidad ──────────────────────────────────────────────────────────────────

def _domain(url: str) -> str:
    """Extrae el host en minúsculas de una URL."""
    try:
        parsed = urlparse(url)
        host = parsed.netloc or ""
        # Quitar puerto
        host = host.split(":")[0]
        return host.lower()
    except Exception:
        return ""
