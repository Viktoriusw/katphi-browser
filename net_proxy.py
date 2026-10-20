"""
Proxy de red para el tráfico que NO pasa por Chromium.

Con Tor activo, main.py solo configura el proxy SOCKS de Qt WebEngine
(--proxy-server). Las peticiones hechas desde Python (requests) y desde
QNetworkAccessManager salían por la IP real. Este módulo centraliza la
decisión para que todo el tráfico de la aplicación use el mismo SOCKS.

Uso con requests:
    from net_proxy import requests_proxies
    requests.get(url, proxies=requests_proxies(url), timeout=10)

Uso con Qt (una vez, al arrancar, tras crear QApplication):
    from net_proxy import apply_qt_application_proxy
    apply_qt_application_proxy()
"""

import logging
from typing import Dict, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

# None = seguir la configuración; True/False = forzado para esta sesión
# (p. ej. el usuario eligió "continuar sin Tor" porque el SOCKS no responde).
_session_override: Optional[bool] = None


def set_tor_active(active: Optional[bool]) -> None:
    """Fuerza el estado de Tor para el resto de la sesión (None = usar config)."""
    global _session_override
    _session_override = active


def is_tor_active() -> bool:
    if _session_override is not None:
        return _session_override
    try:
        from config_manager import config
        return config.is_tor_enabled()
    except Exception:
        return False


def tor_socks_port() -> int:
    try:
        from config_manager import config
        return int(config.get_tor_config().get("socks_port", 9150))
    except Exception:
        return 9150


def is_local_url(url: str) -> bool:
    """True si la URL apunta a esta máquina (LLM local, Ollama...)."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host in _LOCAL_HOSTS or host.endswith(".localhost")


def requests_proxies(url: str = "") -> Optional[Dict[str, str]]:
    """
    Diccionario `proxies` para requests, o None si no hay que usar proxy.

    socks5h hace que la resolución DNS también pase por Tor. Las URLs locales
    nunca se enrutan (un LLM en localhost no es alcanzable a través de Tor).
    """
    if not is_tor_active():
        return None
    if url and is_local_url(url):
        return None
    proxy = f"socks5h://127.0.0.1:{tor_socks_port()}"
    return {"http": proxy, "https": proxy}


def apply_qt_application_proxy() -> None:
    """Configura QNetworkProxy global (QNetworkAccessManager) si Tor está activo."""
    try:
        from PySide6.QtNetwork import QNetworkProxy
    except Exception:
        return
    if is_tor_active():
        QNetworkProxy.setApplicationProxy(
            QNetworkProxy(QNetworkProxy.Socks5Proxy, "127.0.0.1", tor_socks_port())
        )
        logger.info("[TOR] Proxy de aplicación Qt -> SOCKS5 127.0.0.1:%s", tor_socks_port())
    else:
        QNetworkProxy.setApplicationProxy(QNetworkProxy(QNetworkProxy.NoProxy))
