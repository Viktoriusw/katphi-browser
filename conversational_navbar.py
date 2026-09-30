#!/usr/bin/env python3
"""
Conversational NavBar — Barra de navegación con lenguaje natural.

Reemplaza la barra de URL estándar con una que acepta URLs, búsquedas y
comandos en lenguaje natural.  Incluye un dropdown de sugerencias IA
y un gestor de historial conversacional.
"""

import json
import logging
import os
import re
from enum import Enum
from typing import Any, Dict, List, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QSettings,
    QSize,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeyEvent, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QCompleter,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# InputType
# ═════════════════════════════════════════════════════════════════════════════

class InputType(Enum):
    """Clasificación del texto introducido por el usuario."""
    URL = "url"
    SEARCH = "search"
    NATURAL_LANG = "natural_lang"


# ═════════════════════════════════════════════════════════════════════════════
# ConversationManager
# ═════════════════════════════════════════════════════════════════════════════

class ConversationManager:
    """Gestiona el historial conversacional persistente.

    Almacena hasta ``MAX_MESSAGES`` mensajes en formato
    ``[{"role": "user"|"assistant", "content": str, "ts": float}, ...]``
    persistido en un fichero JSON local.
    """

    MAX_MESSAGES: int = 50
    CONTEXT_WINDOW: int = 10

    def __init__(self, storage_dir: Optional[str] = None):
        self._dir = storage_dir or os.path.join(
            os.path.expanduser("~"), ".katphi", "conversations",
        )
        os.makedirs(self._dir, exist_ok=True)
        self._file = os.path.join(self._dir, "session_history.json")
        self._messages: List[Dict[str, Any]] = []
        self.load_conversation()
    def save_conversation(self, messages: Optional[List[Dict]] = None) -> None:
        """Persiste el historial.

        Args:
            messages: Si se proporciona, reemplaza el historial actual.
        """
        if messages is not None:
            self._messages = messages[-self.MAX_MESSAGES:]
        try:
            with open(self._file, "w", encoding="utf-8") as f:
                json.dump(self._messages, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("Error al guardar conversación: %s", exc)
    def load_conversation(self) -> List[Dict]:
        """Carga el historial desde disco.

        Returns:
            Lista de mensajes.
        """
        if os.path.isfile(self._file):
            try:
                with open(self._file, "r", encoding="utf-8") as f:
                    self._messages = json.load(f)
            except Exception:
                self._messages = []
        return self._messages
    def add_message(self, role: str, content: str) -> None:
        """Agrega un mensaje al historial.

        Args:
            role: ``"user"`` o ``"assistant"``.
            content: Contenido del mensaje.
        """
        import time
        self._messages.append({"role": role, "content": content, "ts": time.time()})
        if len(self._messages) > self.MAX_MESSAGES:
            self._messages = self._messages[-self.MAX_MESSAGES:]
        self.save_conversation()
    def get_context_window(self) -> List[Dict]:
        """Devuelve los últimos N mensajes del historial.

        Returns:
            Lista de hasta ``CONTEXT_WINDOW`` mensajes.
        """
        return self._messages[-self.CONTEXT_WINDOW:]
    def clear_history(self) -> None:
        """Elimina todo el historial."""
        self._messages.clear()
        self.save_conversation()


# ═════════════════════════════════════════════════════════════════════════════
# SuggestionDropdown
# ═════════════════════════════════════════════════════════════════════════════

class SuggestionDropdown(QFrame):
    """Dropdown emergente con sugerencias debajo de la barra."""

    suggestion_selected = Signal(str)

    MAX_VISIBLE = 6

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("aiSuggestionDropdown")
        self.setAttribute(Qt.WA_ShowWithoutActivating, False)
        # Usar paleta de la aplicación para adaptarse al tema (claro/oscuro)
        self.setAutoFillBackground(True)
        self._apply_theme()
    def _apply_theme(self) -> None:
        """Aplica estilos que respetan el tema de la aplicación."""
        pal = QApplication.palette()
        bg = pal.window().color().name()
        fg = pal.windowText().color().name()
        hi = pal.highlight().color().name()
        hibg = pal.highlightedText().color().name()
        border = pal.mid().color().name()
        self.setStyleSheet(f"""
            #aiSuggestionDropdown {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 8px;
                padding: 4px;
            }}
            QListWidget {{
                background: transparent;
                border: none;
                color: {fg};
                font-size: 13px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 8px 12px;
                border-radius: 6px;
            }}
            QListWidget::item:hover {{
                background: {hi};
                color: {hibg};
            }}
            QListWidget::item:selected {{
                background: {hi};
                color: {hibg};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        self._list = QListWidget()
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list)
        self.hide()
    def set_suggestions(self, items: List[Dict[str, str]]) -> None:
        """Establece las sugerencias visibles.

        Args:
            items: Lista de dicts con ``icon`` (nombre de SVG en icons/), ``text``, ``type``.
        """
        self._list.clear()
        for item_data in items[: self.MAX_VISIBLE]:
            text = item_data.get("text", "")
            list_item = QListWidgetItem(text)
            try:
                from PySide6.QtCore import QSize
                from ui.core.strip_icons import build_nav_icon
                list_item.setIcon(build_nav_icon(item_data.get("icon", "search"), None, QSize(16, 16)))
            except Exception:
                pass
            list_item.setData(Qt.UserRole, text)
            self._list.addItem(list_item)
        height = min(len(items), self.MAX_VISIBLE) * 38 + 10
        self.setFixedHeight(max(height, 48))

        if items:
            self.show()
        else:
            self.hide()
    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        text = item.data(Qt.UserRole)
        if text:
            self.suggestion_selected.emit(text)
        self.hide()


# ═════════════════════════════════════════════════════════════════════════════
# ConversationalNavBar
# ═════════════════════════════════════════════════════════════════════════════

class ConversationalNavBar(QLineEdit):
    """Barra de URL que acepta lenguaje natural.

    Signals:
        navigation_requested(str): Se debe navegar a una URL.
        search_requested(str): Se debe buscar el texto.
        ai_query_requested(str): El texto es lenguaje natural para IA.
        gentab_requested(str): Se solicita crear una GenTab.
    """

    navigation_requested = Signal(str)
    search_requested = Signal(str)
    ai_query_requested = Signal(str)
    gentab_requested = Signal(str)

    _NL_PREFIXES = (
        "crea ", "genera ", "resume ", "compara ", "busca en mis ",
        "qué ", "cuál ", "cómo ", "dónde ", "por qué ",
        "create ", "generate ", "summarize ", "compare ",
        "what ", "which ", "how ", "where ", "why ",
        "haz ", "muestra ", "show ", "list ",
    )

    _GENTAB_PREFIXES = (
        "gentab:", "gentab ",
        "genera una app", "crea una app",
        "generate an app", "create an app",
    )

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("conversationalNavBar")
        self.setPlaceholderText("Buscar, escribir URL o preguntar a la IA...")
        self.setFixedHeight(36)
        self.setMinimumWidth(250)
        self.setMaximumWidth(600)
        if hasattr(self, "setClearButtonEnabled"):
            self.setClearButtonEnabled(True)
        self._conversation = ConversationManager()
        self._dropdown = SuggestionDropdown()
        self._dropdown.suggestion_selected.connect(self._on_suggestion_selected)

        self._suggestion_timer = QTimer(self)
        self._suggestion_timer.setSingleShot(True)
        self._suggestion_timer.setInterval(300)
        self._suggestion_timer.timeout.connect(self._update_suggestions)

        self.textChanged.connect(self._on_text_changed)

        # Sin stylesheet hardcodeado — el estilo lo aplica ui.py via _refresh_url_bar_style()
        # para que respete el tema activo y sea editable desde el plugin de temas.
    # ── Eventos ──────────────────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Procesa Enter para clasificar y despachar el input."""
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            text = self.text().strip()
            if not text:
                return
            self._dropdown.hide()
            self._dispatch(text)
            return
        if event.key() == Qt.Key_Escape:
            self._dropdown.hide()
        super().keyPressEvent(event)
    def focusOutEvent(self, event):
        QTimer.singleShot(200, self._dropdown.hide)
        super().focusOutEvent(event)
    # ── Clasificación ────────────────────────────────────────────────────────

    @classmethod
    def _classify_input(cls, text: str) -> InputType:
        """Clasifica el texto introducido.

        Args:
            text: Texto del usuario.
        Returns:
            ``InputType.URL``, ``InputType.SEARCH`` o ``InputType.NATURAL_LANG``.
        """
        stripped = text.strip().lower()

        if stripped.startswith(("http://", "https://", "file://", "ftp://")):
            return InputType.URL
        if re.match(r'^[\w.-]+\.\w{2,}(/\S*)?$', stripped):
            return InputType.URL
        for prefix in cls._NL_PREFIXES:
            if stripped.startswith(prefix):
                return InputType.NATURAL_LANG
        if "?" in stripped and len(stripped.split()) > 3:
            return InputType.NATURAL_LANG
        if len(stripped.split()) >= 6:
            return InputType.NATURAL_LANG
        return InputType.SEARCH
    def _dispatch(self, text: str) -> None:
        """Despacha el texto según su clasificación."""
        for prefix in self._GENTAB_PREFIXES:
            if text.lower().startswith(prefix):
                prompt = text[len(prefix):].strip() or text
                self._conversation.add_message("user", text)
                self.gentab_requested.emit(prompt)
                return
        input_type = self._classify_input(text)

        if input_type == InputType.URL:
            url = text if text.startswith(("http", "file", "ftp")) else f"https://{text}"
            self.navigation_requested.emit(url)
        elif input_type == InputType.NATURAL_LANG:
            self._conversation.add_message("user", text)
            self.ai_query_requested.emit(text)
        else:
            self.search_requested.emit(text)
    # ── Sugerencias ──────────────────────────────────────────────────────────

    def _on_text_changed(self, text: str) -> None:
        if len(text) < 2:
            self._dropdown.hide()
            return
        # Solo mostrar predictor cuando el usuario ha hecho click en la barra (tiene foco)
        if not self.hasFocus():
            return
        self._suggestion_timer.start()
    def _update_suggestions(self) -> None:
        """Genera sugerencias basadas en el texto actual."""
        # No mostrar si la barra no tiene foco (ej. URL actualizada al navegar)
        if not self.hasFocus():
            self._dropdown.hide()
            return
        text = self.text().strip()
        if len(text) < 2:
            self._dropdown.hide()
            return
        suggestions: List[Dict[str, str]] = []
        input_type = self._classify_input(text)

        if input_type == InputType.NATURAL_LANG:
            suggestions.append({"icon": "chat", "text": f"Preguntar a la IA: {text}", "type": "ai"})
            suggestions.append({"icon": "ide_ai_sparkles", "text": f"GenTab: {text}", "type": "gentab"})
        suggestions.append({"icon": "search", "text": f"Buscar: {text}", "type": "search"})

        if "." in text and " " not in text:
            suggestions.insert(0, {"icon": "link", "text": f"Ir a: {text}", "type": "url"})
        history = self._conversation.get_context_window()
        for msg in reversed(history[-3:]):
            if msg["role"] == "user" and text.lower() in msg["content"].lower():
                suggestions.append({
                    "icon": "history",
                    "text": msg["content"],
                    "type": "history",
                })
        if suggestions:
            self._dropdown.set_suggestions(suggestions)
            pos = self.mapToGlobal(self.rect().bottomLeft())
            self._dropdown.move(pos)
            self._dropdown.setFixedWidth(self.width())
            self._dropdown.show()
        else:
            self._dropdown.hide()
    def _on_suggestion_selected(self, text: str) -> None:
        """Procesa la selección de una sugerencia del dropdown."""
        for prefix in ("Preguntar a la IA: ", "GenTab: ", "Buscar: ", "Ir a: "):
            if text.startswith(prefix):
                clean = text[len(prefix):]
                self.setText(clean)
                self._dispatch(clean)
                return
        self.setText(text)
        self._dispatch(text)
    def _get_ai_suggestions(self, text: str) -> List[str]:
        """Genera sugerencias contextuales de IA (stub para extensión futura).

        Args:
            text: Texto parcial del usuario.
        Returns:
            Lista de sugerencias textuales.
        """
        return []
    # ── Métodos públicos ─────────────────────────────────────────────────────

    def set_placeholder_with_suggestion(self, suggestion: str) -> None:
        """Cambia el placeholder con una sugerencia contextual.

        Args:
            suggestion: Texto de sugerencia.
        """
        self.setPlaceholderText(suggestion)
    def insertFromMimeData(self, source) -> None:
        """Maneja pegado de URLs — navega directamente si es URL."""
        super().insertFromMimeData(source)
        text = self.text().strip()
        if text and self._classify_input(text) == InputType.URL:
            url = text if text.startswith(("http", "file", "ftp")) else f"https://{text}"
            self.navigation_requested.emit(url)
