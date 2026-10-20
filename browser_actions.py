#!/usr/bin/env python3
"""
Acciones de navegación que puede ejecutar el asistente.

Las usan tanto las órdenes directas del chat ("vuelve atrás", "cierra la pestaña")
como las etiquetas que escribe el LLM (<nav>back</nav>, <tab>3</tab>...), y por
tanto también el control por voz. Cada acción devuelve una frase corta de
confirmación pensada para mostrarse en el chat o leerse en voz alta.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional, Tuple

_NUMBER_WORDS = {
    "uno": 1, "una": 1, "primera": 1, "primero": 1, "dos": 2, "segunda": 2, "segundo": 2,
    "tres": 3, "tercera": 3, "tercero": 3, "cuatro": 4, "cuarta": 4, "cuarto": 4,
    "cinco": 5, "quinta": 5, "quinto": 5, "seis": 6, "sexta": 6, "sexto": 6,
    "siete": 7, "septima": 7, "septimo": 7, "ocho": 8, "octava": 8, "octavo": 8,
    "nueve": 9, "novena": 9, "noveno": 9, "diez": 10, "decima": 10, "decimo": 10,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10,
}

# Valores válidos de cada etiqueta del LLM
TAG_VALUES = {
    "nav": ("back", "forward", "reload"),
    "tab": ("new", "close", "next", "prev"),          # o un número
    "scroll": ("down", "up", "top", "bottom"),
    "zoom": ("in", "out", "reset"),
}

# Acciones que solo se ejecutan si el usuario lo pidió expresamente
CLOSE_INTENT_RE = re.compile(r"\b(?:cierr[ae]\w*|cerrar|close)\b", re.IGNORECASE)


def normalize(text: str) -> str:
    """Minúsculas, sin acentos ni puntuación final: así se reconocen mejor las
    órdenes escritas y las que llegan del reconocimiento de voz."""
    text = unicodedata.normalize("NFD", (text or "").lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.strip(" .,:;!?¿¡\"'\n\t")


def _number(word: str) -> Optional[int]:
    if word.isdigit():
        return int(word)
    return _NUMBER_WORDS.get(word)


_POLITE = r"(?:(?:por\s+favor|porfa|please)[\s,]+)?"
_TAB = r"(?:pestana|tab|ventana)"
_PAGE = r"(?:(?:la|esta|esa)\s+)?(?:pagina|web|pestana)"
_GO_TO = r"(?:(?:(?:ve|ir|vete|cambia|pasa|salta|llevame)\s+a|muestrame|ensename)\s+)?"

# (regex sobre texto normalizado, acción, argumento fijo o None si sale del grupo 1)
_DIRECT_COMMANDS = [
    (rf"(?:vuelve|volver|regresa|regresar)(?:\s+(?:hacia\s+)?atras)?|"
     rf"(?:ve|ir|vete)\s+(?:hacia\s+)?atras|atras|retrocede|"
     rf"(?:ve\s+a\s+la\s+)?pagina\s+anterior|go\s+back|back", "nav", "back"),
    (rf"(?:ve\s+|ir\s+)?(?:hacia\s+)?adelante|avanza|(?:ve\s+a\s+la\s+)?pagina\s+siguiente|"
     rf"go\s+forward|forward", "nav", "forward"),
    (rf"(?:recarga|recargar|actualiza|actualizar|refresca|refrescar)(?:\s+{_PAGE})?|reload",
     "nav", "reload"),
    (rf"(?:abre\s+|abrir\s+|crea\s+)?(?:una\s+)?(?:nueva\s+{_TAB}|{_TAB}\s+nueva)|new\s+tab",
     "tab", "new"),
    (rf"(?:cierra|cerrar)\s+(?:(?:la|esta|esa)\s+)?{_TAB}(?:\s+actual)?|close\s+(?:the\s+)?tab",
     "tab", "close"),
    (rf"(?:ve\s+a\s+la\s+|cambia\s+a\s+la\s+)?(?:siguiente\s+{_TAB}|{_TAB}\s+siguiente)|next\s+tab",
     "tab", "next"),
    (rf"(?:ve\s+a\s+la\s+|cambia\s+a\s+la\s+)?{_TAB}\s+anterior|previous\s+tab", "tab", "prev"),
    (rf"{_GO_TO}la\s+{_TAB}\s+(?:numero\s+)?(\w+)|{_GO_TO}la\s+(\w+)\s+{_TAB}|"
     rf"{_TAB}\s+(?:numero\s+)?(\w+)",
     "tab", None),
    (r"(?:baja|bajar|desplaza(?:te)?\s+(?:hacia\s+)?abajo|mas\s+abajo|scroll\s+down)",
     "scroll", "down"),
    (r"(?:sube|subir|desplaza(?:te)?\s+(?:hacia\s+)?arriba|mas\s+arriba|scroll\s+up)",
     "scroll", "up"),
    (r"(?:ve\s+|vete\s+|ir\s+)?(?:al\s+principio|al\s+inicio|arriba\s+del\s+todo)"
     r"(?:\s+de\s+la\s+pagina)?", "scroll", "top"),
    (r"(?:ve\s+|vete\s+|ir\s+)?(?:al\s+final|abajo\s+del\s+todo)(?:\s+de\s+la\s+pagina)?",
     "scroll", "bottom"),
    (r"(?:aumenta|sube)\s+(?:el\s+)?zoom|amplia(?:r)?(?:\s+la\s+pagina)?|acerca(?:r)?|zoom\s+in|mas\s+zoom",
     "zoom", "in"),
    (r"(?:reduce|baja|quita)\s+(?:el\s+)?zoom|aleja(?:r)?|zoom\s+out|menos\s+zoom", "zoom", "out"),
    (r"(?:restablece|resetea|quita)\s+(?:el\s+)?zoom|zoom\s+(?:normal|al\s+100)", "zoom", "reset"),
    (rf"(?:busca|buscar|encuentra|localiza)\s+en\s+{_PAGE}\s+(.+)|"
     rf"(?:busca|buscar|encuentra|localiza)\s+(.+?)\s+en\s+{_PAGE}", "find", None),
    (r"(?:deja\s+de\s+buscar|quita\s+(?:la\s+)?busqueda|cierra\s+(?:la\s+)?busqueda)", "find", ""),
]
_DIRECT_COMMANDS = [(re.compile(rf"^{_POLITE}(?:{rx})$", re.DOTALL), action, arg)
                    for rx, action, arg in _DIRECT_COMMANDS]


def parse_direct_command(message: str) -> Optional[Tuple[str, str]]:
    """Reconoce una orden de navegación que ocupa todo el mensaje.
    Devuelve (acción, argumento) o None. Solo mensajes completos: "¿qué hay atrás
    de esta teoría?" no debe mover el navegador."""
    text = normalize(message)
    if not text or len(text) > 120:
        return None
    for rx, action, arg in _DIRECT_COMMANDS:
        m = rx.match(text)
        if not m:
            continue
        if arg is not None:
            return action, arg
        value = next((g for g in m.groups() if g), "")
        if action == "tab":
            n = _number(value)
            if n is None:
                continue
            return action, str(n)
        if action == "find":
            # Recuperar el texto original (con mayúsculas/acentos) a partir de la longitud
            return action, _original_slice(message, value)
        return action, value
    return None


def _original_slice(original: str, normalized_part: str) -> str:
    """Busca en el mensaje original el fragmento que corresponde a normalized_part."""
    words = normalized_part.split()
    if not words:
        return normalized_part
    orig_words = (original or "").strip(" .,:;!?¿¡\"'").split()
    norm_words = [normalize(w) for w in orig_words]
    for i in range(len(norm_words) - len(words) + 1):
        if norm_words[i:i + len(words)] == words:
            return " ".join(orig_words[i:i + len(words)]).strip(" .,:;!?¿¡\"'")
    return normalized_part


class BrowserActions:
    """Ejecuta acciones sobre la ventana principal del navegador."""

    SCROLL_JS = {
        "down": "window.scrollBy({top: window.innerHeight * 0.8, behavior: 'smooth'});",
        "up": "window.scrollBy({top: -window.innerHeight * 0.8, behavior: 'smooth'});",
        "top": "window.scrollTo({top: 0, behavior: 'smooth'});",
        "bottom": "window.scrollTo({top: document.documentElement.scrollHeight, behavior: 'smooth'});",
    }

    def __init__(self, get_main_window):
        # Se resuelve en cada llamada: el panel puede cambiar de ventana (dock flotante)
        self._get_main_window = get_main_window

    # ── utilidades ──────────────────────────────────────────────────────────

    @property
    def _main(self):
        return self._get_main_window()

    @property
    def _tabs(self):
        tm = getattr(self._main, "tab_manager", None)
        return getattr(tm, "tabs", None) if tm else None

    def current_browser(self):
        tabs = self._tabs
        return tabs.currentWidget() if tabs is not None else None

    # ── API ─────────────────────────────────────────────────────────────────

    def execute(self, action: str, arg: str = "") -> Tuple[bool, str]:
        """Ejecuta una acción. Devuelve (ok, mensaje para el usuario)."""
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:
            return False, f"Acción desconocida: {action}"
        try:
            return handler((arg or "").strip().lower() if action != "find" else (arg or "").strip())
        except Exception as e:  # nunca romper el chat por una acción
            return False, f"No se pudo ejecutar la acción: {e}"

    def _do_nav(self, arg: str) -> Tuple[bool, str]:
        browser = self.current_browser()
        if browser is None:
            return False, "No hay ninguna pestaña abierta."
        if arg == "back":
            if not browser.history().canGoBack():
                return False, "No hay ninguna página anterior."
            browser.back()
            return True, "Volviendo a la página anterior."
        if arg == "forward":
            if not browser.history().canGoForward():
                return False, "No hay ninguna página siguiente."
            browser.forward()
            return True, "Avanzando a la página siguiente."
        if arg == "reload":
            browser.reload()
            return True, "Recargando la página."
        return False, f"Navegación no válida: {arg}"

    def _do_tab(self, arg: str) -> Tuple[bool, str]:
        tabs = self._tabs
        tm = getattr(self._main, "tab_manager", None)
        if tabs is None or tm is None:
            return False, "No se puede acceder a las pestañas."
        count = tabs.count()
        if arg == "new":
            tm.add_new_tab(None, focus=True)
            return True, "Pestaña nueva abierta."
        if arg == "close":
            if count <= 1:
                return False, "Es la única pestaña abierta; no la cierro."
            tm.close_tab(tabs.currentIndex())
            return True, "Pestaña cerrada."
        if arg in ("next", "prev"):
            if count <= 1:
                return False, "Solo hay una pestaña abierta."
            step = 1 if arg == "next" else -1
            tabs.setCurrentIndex((tabs.currentIndex() + step) % count)
            return True, f"Pestaña {tabs.currentIndex() + 1} de {count}."
        n = _number(arg)
        if n is None:
            return False, f"Pestaña no válida: {arg}"
        if not 1 <= n <= count:
            return False, f"No existe la pestaña {n}; hay {count} abiertas."
        tabs.setCurrentIndex(n - 1)
        return True, f"Pestaña {n}: {tabs.tabText(n - 1) or 'sin título'}."

    def _do_scroll(self, arg: str) -> Tuple[bool, str]:
        browser = self.current_browser()
        if browser is None or not hasattr(browser, "page"):
            return False, "No hay ninguna página abierta."
        js = self.SCROLL_JS.get(arg)
        if not js:
            return False, f"Desplazamiento no válido: {arg}"
        browser.page().runJavaScript(js)
        return True, {"down": "Bajando.", "up": "Subiendo.", "top": "Al principio de la página.",
                      "bottom": "Al final de la página."}[arg]

    def _do_zoom(self, arg: str) -> Tuple[bool, str]:
        main = self._main
        method = {"in": "zoom_in", "out": "zoom_out", "reset": "zoom_reset"}.get(arg)
        if not method or not hasattr(main, method):
            return False, f"Zoom no válido: {arg}"
        getattr(main, method)()
        browser = self.current_browser()
        level = f" ({int(browser.zoomFactor() * 100)} %)" if browser is not None and arg != "reset" else ""
        return True, {"in": "Zoom aumentado", "out": "Zoom reducido",
                      "reset": "Zoom al 100 %"}[arg] + level + "."

    def _do_find(self, arg: str) -> Tuple[bool, str]:
        browser = self.current_browser()
        if browser is None or not hasattr(browser, "findText"):
            return False, "No hay ninguna página abierta."
        browser.findText(arg)  # texto vacío = quitar el resaltado
        if not arg:
            return True, "Búsqueda en la página quitada."
        return True, f"Buscando «{arg}» en la página."
