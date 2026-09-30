#!/usr/bin/env python3
"""
Proactive Suggestion Engine — Motor de sugerencias contextuales no intrusivas.

Genera sugerencias basadas en el análisis de la sesión de navegación.
Respeta cooldowns, límites por sesión y las preferencias de privacidad.
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QObject, QSettings, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve

from session_intent_detector import SessionIntent

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# Tipos y modelos
# ═════════════════════════════════════════════════════════════════════════════

class SuggestionType(Enum):
    """Tipos de sugerencia que el motor puede generar."""
    CREATE_GENTAB = "create_gentab"
    SUMMARIZE_TABS = "summarize_tabs"
    OPEN_RELATED = "open_related"
    SEARCH_TOPIC = "search_topic"
    COMPARE_PRODUCTS = "compare_products"
    CREATE_DOC = "create_doc"


@dataclass
class SuggestionModel:
    """Modelo de una sugerencia mostrada al usuario."""
    type: SuggestionType
    title: str
    description: str
    icon: str  # nombre de un SVG de icons/ (sin extensión)
    action_payload: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    dismissible: bool = True


# ═════════════════════════════════════════════════════════════════════════════
# ProactiveSuggestionEngine
# ═════════════════════════════════════════════════════════════════════════════

class ProactiveSuggestionEngine(QObject):
    """Motor que genera sugerencias contextuales no intrusivas.

    Signals:
        suggestions_ready: Emitida con la lista de sugerencias generadas.
    """

    suggestions_ready = Signal(list)

    CONFIDENCE_THRESHOLD: float = 0.6
    MAX_SUGGESTIONS_PER_SESSION: int = 3
    SUGGESTION_COOLDOWN: int = 300  # segundos

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._suggestions_shown: int = 0
        self._last_shown: Dict[str, float] = {}
        self._dismissals: Dict[str, int] = {}
        self._acceptances: Dict[str, int] = {}
        self._settings = QSettings("Katphi", "SuggestionEngine")
        self._load_history()
    # ── Generación ───────────────────────────────────────────────────────────

    def generate_suggestions(
        self, session_analysis: Dict[str, Any],
    ) -> List[SuggestionModel]:
        """Genera sugerencias basadas en el análisis de sesión.

        Args:
            session_analysis: Dict producido por
                ``SessionContextAnalyzer.analyze_current_session``.
        Returns:
            Lista (potencialmente vacía) de ``SuggestionModel``.
        """
        intent: SessionIntent = session_analysis.get("intent", SessionIntent.GENERAL)
        confidence: float = session_analysis.get("confidence", 0.0)
        tab_count: int = session_analysis.get("tab_count", 0)
        domains: List[str] = session_analysis.get("domains", [])

        if confidence < self.CONFIDENCE_THRESHOLD:
            return []
        suggestions: List[SuggestionModel] = []

        if intent == SessionIntent.RESEARCH:
            suggestions.append(SuggestionModel(
                type=SuggestionType.SUMMARIZE_TABS,
                title="Crear resumen de investigación",
                description="Genera un resumen consolidado de tus pestañas de investigación con GenTab",
                icon="edit",
                action_payload={"intent": "research", "action": "summarize"},
                confidence=confidence,
            ))
        elif intent == SessionIntent.SHOPPING:
            suggestions.append(SuggestionModel(
                type=SuggestionType.COMPARE_PRODUCTS,
                title="Comparar productos",
                description="Crea una tabla comparativa de los productos que estás viendo",
                icon="tag",
                action_payload={"intent": "shopping", "action": "compare"},
                confidence=confidence,
            ))
        elif intent == SessionIntent.CODING:
            suggestions.append(SuggestionModel(
                type=SuggestionType.CREATE_DOC,
                title="Generar documentación",
                description="Documenta automáticamente lo que estás investigando",
                icon="code",
                action_payload={"intent": "coding", "action": "document"},
                confidence=confidence,
            ))
        elif intent == SessionIntent.NEWS:
            suggestions.append(SuggestionModel(
                type=SuggestionType.SUMMARIZE_TABS,
                title="Briefing de noticias",
                description="Resume las noticias que estás leyendo en un briefing rápido",
                icon="file-text",
                action_payload={"intent": "news", "action": "briefing"},
                confidence=confidence,
            ))
        elif intent == SessionIntent.TRAVEL:
            suggestions.append(SuggestionModel(
                type=SuggestionType.CREATE_GENTAB,
                title="Crear itinerario de viaje",
                description="Organiza tu investigación de viaje en un itinerario interactivo",
                icon="target",
                action_payload={"intent": "travel", "action": "itinerary"},
                confidence=confidence,
            ))
        elif intent == SessionIntent.ENTERTAINMENT:
            suggestions.append(SuggestionModel(
                type=SuggestionType.CREATE_GENTAB,
                title="Crear lista de reproducción",
                description="Organiza tu contenido de entretenimiento en una lista",
                icon="play",
                action_payload={"intent": "entertainment", "action": "playlist"},
                confidence=confidence,
            ))
        # Sugerencia genérica si hay muchas pestañas del mismo dominio
        if tab_count > 5:
            domain_counts = {}
            for d in domains:
                domain_counts[d] = domain_counts.get(d, 0) + 1
            top_domain = max(domain_counts, key=domain_counts.get) if domain_counts else ""
            if domain_counts.get(top_domain, 0) >= 3:
                suggestions.append(SuggestionModel(
                    type=SuggestionType.SUMMARIZE_TABS,
                    title="Agrupar pestañas similares",
                    description=f"Tienes {domain_counts[top_domain]} pestañas de {top_domain}. ¿Quieres agruparlas?",
                    icon="folder",
                    action_payload={"action": "group", "domain": top_domain},
                    confidence=min(1.0, domain_counts[top_domain] / tab_count),
                ))
        # Sugerencia GenTab si hay contenido suficiente
        if tab_count >= 3 and intent != SessionIntent.GENERAL:
            suggestions.append(SuggestionModel(
                type=SuggestionType.CREATE_GENTAB,
                title="Crear GenTab inteligente",
                description="Genera una app interactiva basada en el contexto de tus pestañas",
                icon="ide_ai_sparkles",
                action_payload={"intent": intent.value, "action": "gentab"},
                confidence=confidence * 0.9,
            ))
        filtered = [s for s in suggestions if self.should_show_suggestion(s.type)]
        filtered.sort(key=lambda s: s.confidence, reverse=True)
        result = filtered[:2]

        if result:
            self.suggestions_ready.emit(result)
        return result
    def should_show_suggestion(
        self, suggestion_type: SuggestionType, user_history: Optional[Dict] = None,
    ) -> bool:
        """Determina si una sugerencia debe mostrarse.

        Args:
            suggestion_type: Tipo de sugerencia.
            user_history: Historial del usuario (no usado actualmente).
        Returns:
            ``True`` si la sugerencia puede mostrarse.
        """
        if self._suggestions_shown >= self.MAX_SUGGESTIONS_PER_SESSION:
            return False
        key = suggestion_type.value
        last = self._last_shown.get(key, 0)
        if time.time() - last < self.SUGGESTION_COOLDOWN:
            return False
        if self._dismissals.get(key, 0) >= 3:
            return False
        return True
    def record_dismissal(self, suggestion_type: SuggestionType) -> None:
        """Registra que el usuario descartó una sugerencia.

        Args:
            suggestion_type: Tipo de sugerencia descartada.
        """
        key = suggestion_type.value
        self._dismissals[key] = self._dismissals.get(key, 0) + 1
        self._last_shown[key] = time.time()
        self._save_history()
        logger.info("Sugerencia '%s' descartada (%d veces)", key, self._dismissals[key])
    def record_acceptance(self, suggestion_type: SuggestionType) -> None:
        """Registra que el usuario aceptó una sugerencia.

        Args:
            suggestion_type: Tipo de sugerencia aceptada.
        """
        key = suggestion_type.value
        self._acceptances[key] = self._acceptances.get(key, 0) + 1
        self._suggestions_shown += 1
        self._last_shown[key] = time.time()
        self._save_history()
        logger.info("Sugerencia '%s' aceptada (%d veces)", key, self._acceptances[key])
    def reset_session(self) -> None:
        """Reinicia contadores de sesión (no persistentes)."""
        self._suggestions_shown = 0
        self._last_shown.clear()
    # ── Persistencia ─────────────────────────────────────────────────────────

    def _save_history(self) -> None:
        self._settings.setValue("dismissals", self._dismissals)
        self._settings.setValue("acceptances", self._acceptances)
    def _load_history(self) -> None:
        self._dismissals = self._settings.value("dismissals", {}) or {}
        self._acceptances = self._settings.value("acceptances", {}) or {}


# ═════════════════════════════════════════════════════════════════════════════
# SuggestionToast — widget de notificación flotante
# ═════════════════════════════════════════════════════════════════════════════

class SuggestionToast(QFrame):
    """Toast flotante que muestra sugerencias proactivas.

    Signals:
        action_clicked(SuggestionModel): Emitida cuando el usuario acepta.
        dismissed(SuggestionModel): Emitida cuando el usuario descarta.
    """

    action_clicked = Signal(object)
    dismissed = Signal(object)

    AUTO_HIDE_MS = 8000

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._current: Optional[SuggestionModel] = None
        self._setup_ui()
        self.hide()
    def _setup_ui(self) -> None:
        self.setObjectName("suggestionToast")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFixedWidth(380)
        self.setStyleSheet("""
            #suggestionToast {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1a1a2e, stop:1 #16213e);
                border: 1px solid #0f3460;
                border-radius: 12px;
                padding: 12px;
            }
            QLabel#toastTitle {
                color: #e0e0e0;
                font-size: 14px;
                font-weight: bold;
            }
            QLabel#toastDesc {
                color: #a0a0a0;
                font-size: 12px;
            }
            QLabel#toastIcon {
                font-size: 24px;
            }
            QPushButton#toastAction {
                background: #0f3460;
                color: #e0e0e0;
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton#toastAction:hover {
                background: #1a5276;
            }
            QPushButton#toastDismiss {
                background: transparent;
                color: #666;
                border: none;
                font-size: 16px;
                padding: 2px 6px;
            }
            QPushButton#toastDismiss:hover {
                color: #e0e0e0;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 8, 8)
        layout.setSpacing(10)

        self._icon_label = QLabel()
        self._icon_label.setObjectName("toastIcon")
        self._icon_label.setFixedWidth(32)
        layout.addWidget(self._icon_label)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        self._title_label = QLabel()
        self._title_label.setObjectName("toastTitle")
        self._title_label.setWordWrap(True)
        text_layout.addWidget(self._title_label)

        self._desc_label = QLabel()
        self._desc_label.setObjectName("toastDesc")
        self._desc_label.setWordWrap(True)
        text_layout.addWidget(self._desc_label)

        self._action_btn = QPushButton("Aceptar")
        self._action_btn.setObjectName("toastAction")
        self._action_btn.setCursor(Qt.PointingHandCursor)
        self._action_btn.clicked.connect(self._on_accept)
        text_layout.addWidget(self._action_btn)

        layout.addLayout(text_layout, 1)

        self._dismiss_btn = QPushButton()
        self._dismiss_btn.setIcon(self._svg_icon("ide_close", 12))
        self._dismiss_btn.setObjectName("toastDismiss")
        self._dismiss_btn.setCursor(Qt.PointingHandCursor)
        self._dismiss_btn.clicked.connect(self._on_dismiss)
        self._dismiss_btn.setFixedSize(24, 24)
        layout.addWidget(self._dismiss_btn, 0, Qt.AlignTop)

        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self._fade_out)
    # ── API pública ──────────────────────────────────────────────────────────

    @staticmethod
    def _svg_icon(name: str, size: int):
        """Icono SVG de icons/ teñido con el color del tema activo."""
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QIcon
        try:
            from ui.core.strip_icons import build_nav_icon
            return build_nav_icon(name, None, QSize(size, size))
        except Exception:
            return QIcon()
    def show_suggestion(self, suggestion: SuggestionModel) -> None:
        """Muestra una sugerencia en el toast.

        Args:
            suggestion: Modelo de sugerencia a mostrar.
        """
        self._current = suggestion
        self._icon_label.setPixmap(self._svg_icon(suggestion.icon, 22).pixmap(22, 22))
        self._title_label.setText(suggestion.title)
        self._desc_label.setText(suggestion.description)

        self._position_toast()
        self.show()
        self.raise_()
        self._auto_hide_timer.start(self.AUTO_HIDE_MS)
    def _position_toast(self) -> None:
        """Posiciona el toast en la esquina superior derecha del padre."""
        parent = self.parentWidget()
        if parent:
            x = parent.width() - self.width() - 20
            y = 60
            self.move(x, y)
    # ── Slots privados ───────────────────────────────────────────────────────

    def _on_accept(self) -> None:
        if self._current:
            self.action_clicked.emit(self._current)
        self._auto_hide_timer.stop()
        self.hide()
    def _on_dismiss(self) -> None:
        if self._current:
            self.dismissed.emit(self._current)
        self._auto_hide_timer.stop()
        self.hide()
    def _fade_out(self) -> None:
        self.hide()
