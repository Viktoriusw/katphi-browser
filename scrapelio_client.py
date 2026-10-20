#!/usr/bin/env python3
"""
Cliente del motor de búsqueda Scrapelio (propio, sin APIs de terceros).

El asistente de navegación lo usa para buscar, ofrecer enlaces reales y
abrirlos en pestañas. Las búsquedas se hacen en un QThread para no bloquear
la interfaz mientras el usuario conversa.

Usa /api/assistant, pensado para el asistente: en una sola petición da los
resultados propios marcados según traten el tema (about) o sean portadas
(homepage), artículos de Wikipedia y la consulta ajustada si ninguna página
contenía todas las palabras. Con un servidor antiguo se usa /api/search.
Los resultados que se abren y los que recomienda el LLM se comunican al
buscador (/api/click, /api/feedback) para que aprenda a ordenar mejor.

URL del servidor (por prioridad): variable de entorno SCRAPELIO_URL,
``scrapelio.url`` en config.yaml, o DEFAULT_SCRAPELIO_URL.
"""

import logging
import os
import threading
from urllib.parse import quote_plus

import requests

from PySide6.QtCore import QLocale, QThread, Signal

logger = logging.getLogger(__name__)

DEFAULT_SCRAPELIO_URL = "https://scrapelio.com"
DEFAULT_TIMEOUT = 8
REPORT_TIMEOUT = 5


class ScrapelioError(Exception):
    """Error al consultar el motor Scrapelio."""


def get_scrapelio_url() -> str:
    """URL base del servidor Scrapelio, sin barra final."""
    url = os.environ.get("SCRAPELIO_URL", "").strip()
    if not url:
        try:
            from config_manager import get_config
            url = (get_config().get("scrapelio.url") or "").strip()
        except Exception:
            url = ""
    return (url or DEFAULT_SCRAPELIO_URL).rstrip("/")


def web_search_url(query: str) -> str:
    """URL de la página de resultados de Scrapelio (para abrir en una pestaña)."""
    return f"{get_scrapelio_url()}/?q={quote_plus(query)}"


def _headers() -> dict:
    """Idioma del sistema (Scrapelio sube las páginas en ese idioma) e identificación."""
    name = QLocale.system().name()          # "es_ES"
    lang = name.split("_")[0] or "es"
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")) as f:
            version = f.readline().strip()
    except OSError:
        version = ""
    return {
        "Accept-Language": f"{name.replace('_', '-')},{lang};q=0.9",
        "User-Agent": f"KatphiBrowser/{version or 'dev'}",
    }


def _get(path: str, params: dict, timeout: float) -> requests.Response:
    try:
        return requests.get(f"{get_scrapelio_url()}{path}", params=params,
                            headers=_headers(), timeout=timeout)
    except requests.RequestException as e:
        logger.warning("Scrapelio no accesible: %s", e)
        raise ScrapelioError(f"No se pudo conectar con el buscador Scrapelio ({get_scrapelio_url()}). "
                             "Comprueba tu conexión a Internet.") from e


def _json(resp: requests.Response) -> dict:
    if resp.status_code == 429:
        raise ScrapelioError("Scrapelio: demasiadas búsquedas seguidas, espera un momento")
    if resp.status_code != 200:
        raise ScrapelioError(f"Scrapelio respondió HTTP {resp.status_code}")
    try:
        return resp.json()
    except ValueError as e:
        raise ScrapelioError("Respuesta de Scrapelio no válida") from e


def search(query: str, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """
    Busca en Scrapelio. Devuelve:
    {query, query_id, total_results, relaxed, suggestion, adjusted_query, dropped_terms,
     answer, results: [{position, url, title, domain, lang, snippet, about, homepage}],
     wikipedia: [{title, url, extract, lang}]}
    """
    query = (query or "").strip()[:500]
    if not query:
        raise ScrapelioError("Consulta vacía")
    resp = _get("/api/assistant", {"q": query}, timeout)
    if resp.status_code == 404:          # servidor sin /api/assistant
        data = _json(_get("/api/search", {"q": query, "page": 1}, timeout))
        for i, r in enumerate(data.get("results", []), 1):
            r.setdefault("position", i)
    else:
        data = _json(resp)
    data.setdefault("results", [])
    data.setdefault("wikipedia", [])
    return data


def _post(path: str, payload: dict) -> None:
    """Envía un aviso al buscador en segundo plano; si falla no pasa nada."""
    def send():
        try:
            requests.post(f"{get_scrapelio_url()}{path}", json=payload,
                          headers=_headers(), timeout=REPORT_TIMEOUT)
        except requests.RequestException as e:
            logger.debug("Scrapelio %s: %s", path, e)
    threading.Thread(target=send, daemon=True).start()


def report_click(query_id, position: int, url: str) -> None:
    """El usuario abrió el resultado `position` (desde 1) de la búsqueda `query_id`."""
    if query_id and position:
        _post("/api/click", {"query_id": query_id, "position": position - 1, "url": url})


def report_recommended(query_id, position: int, url: str) -> None:
    """El LLM recomendó ese resultado (señal para el modelo de ranking)."""
    if query_id and position:
        _post("/api/feedback", {"query_id": query_id, "position": position - 1, "url": url,
                                "kind": "recommended"})


def format_results_for_llm(data: dict, limit: int = 8) -> str:
    """Resume los resultados en texto numerado para el contexto del LLM."""
    data = data or {}
    results = data.get("results", [])[:limit]
    wikipedia = data.get("wikipedia", [])
    query = data.get("query", "")
    if not results and not wikipedia:
        return (f'Scrapelio no encontró resultados para "{query}". Díselo al usuario y '
                "propón otra búsqueda con palabras distintas.")
    lines = [f'Resultados de Scrapelio para "{query}" '
             f'({data.get("total_results", len(results))} páginas en total):']
    if data.get("adjusted_query"):
        lines.append(f'Nota: se buscó "{data["adjusted_query"]}" sin las palabras demasiado '
                     f'generales ({", ".join(data["dropped_terms"])}).')
    if data.get("suggestion"):
        lines.append(f'Posible error ortográfico: quizá quería decir "{data["suggestion"]}".')
    if data.get("relaxed"):
        lines.append("Aviso: ninguna página contiene todas las palabras; son coincidencias parciales.")
    for r in results:
        if r.get("about"):
            tag = "trata el tema"
        elif r.get("homepage"):
            tag = "portada de un sitio; solo menciona las palabras"
        elif "about" in r:
            tag = "solo menciona las palabras en el texto"
        else:
            tag = ""
        snippet = " ".join((r.get("snippet") or "").split())[:400]
        lines.append(f"{r.get('position')}. {r.get('title') or r.get('url')}"
                     + (f" [{tag}]" if tag else "") + "\n"
                     f"   URL: {r.get('url')}\n"
                     f"   {snippet}")
    if wikipedia:
        lines.append("Artículos de Wikipedia (fiables para información general; el usuario "
                     "también los ve):")
        for a in wikipedia:
            extract = " ".join((a.get("extract") or "").split())[:300]
            lines.append(f"W. {a.get('title')}\n   URL: {a.get('url')}\n   {extract}")
    return "\n".join(lines)


class ScrapelioSearchWorker(QThread):
    """Ejecuta una búsqueda Scrapelio en segundo plano."""

    results_ready = Signal(str, dict)   # query, datos
    failed = Signal(str, str)           # query, mensaje de error

    def __init__(self, query: str, parent=None):
        super().__init__(parent)
        self.query = query

    def run(self):
        try:
            data = search(self.query)
        except ScrapelioError as e:
            logger.warning("Scrapelio: %s", e)
            self.failed.emit(self.query, str(e))
            return
        except Exception as e:
            logger.error("Scrapelio error inesperado: %s", e, exc_info=True)
            self.failed.emit(self.query, f"Error inesperado en Scrapelio: {e}")
            return
        self.results_ready.emit(self.query, data)
