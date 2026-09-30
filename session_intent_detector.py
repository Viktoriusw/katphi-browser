#!/usr/bin/env python3
"""
Session Intent Detector — Detección de intención de la sesión de navegación.

Analiza las pestañas abiertas (dominios, títulos, contenido) para inferir
qué está haciendo el usuario y sugerir acciones proactivas.
"""

import logging
import re
from collections import Counter
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# SessionIntent
# ═════════════════════════════════════════════════════════════════════════════

class SessionIntent(Enum):
    """Intenciones de sesión reconocidas."""
    RESEARCH = "research"
    SHOPPING = "shopping"
    NEWS = "news"
    TRAVEL = "travel"
    CODING = "coding"
    ENTERTAINMENT = "entertainment"
    GENERAL = "general"


# ═════════════════════════════════════════════════════════════════════════════
# IntentDetector
# ═════════════════════════════════════════════════════════════════════════════

class IntentDetector:
    """Detecta la intención del usuario basándose en las pestañas abiertas.

    Combina heurísticas de dominio y análisis de títulos para producir
    una clasificación ``(SessionIntent, confidence)`` con ``confidence``
    entre 0.0 y 1.0.
    """

    DOMAIN_PATTERNS: Dict[str, List[str]] = {
        "research": [
            "wikipedia", "github", "stackoverflow", "medium", "docs",
            "arxiv", "scholar", "researchgate", "academia", "quora",
        ],
        "shopping": [
            "amazon", "ebay", "aliexpress", "wish", "shop", "etsy",
            "mercadolibre", "wallapop", "pccomponentes", "mediamarkt",
        ],
        "news": [
            "news", "bbc", "cnn", "elperiodico", "elmundo", "elpais",
            "reuters", "theguardian", "nytimes", "lavanguardia",
        ],
        "travel": [
            "booking", "airbnb", "tripadvisor", "skyscanner", "kayak",
            "expedia", "hostelworld", "renfe", "google.com/maps",
        ],
        "coding": [
            "github", "stackoverflow", "dev.to", "npm", "pypi",
            "gitlab", "bitbucket", "codepen", "jsfiddle", "replit",
        ],
        "entertainment": [
            "youtube", "netflix", "spotify", "twitch", "disney",
            "hbo", "primevideo", "tiktok", "reddit", "9gag",
        ],
    }

    TITLE_KEYWORDS: Dict[str, List[str]] = {
        "research": [
            "research", "paper", "study", "analysis", "documentation",
            "wiki", "investigación", "estudio", "tutorial", "guide",
        ],
        "shopping": [
            "buy", "price", "cart", "deal", "offer", "comprar",
            "precio", "carrito", "oferta", "descuento", "review",
        ],
        "news": [
            "breaking", "latest", "politics", "economy", "world",
            "noticias", "última hora", "política", "economía",
        ],
        "travel": [
            "hotel", "flight", "travel", "booking", "trip",
            "vuelo", "viaje", "reserva", "destino", "vacation",
        ],
        "coding": [
            "code", "programming", "error", "bug", "api", "function",
            "class", "debug", "deploy", "repository", "pull request",
        ],
        "entertainment": [
            "watch", "listen", "play", "stream", "video", "music",
            "movie", "series", "game", "ver", "escuchar",
        ],
    }

    def detect_from_domains(self, domains: List[str]) -> Tuple[SessionIntent, float]:
        """Detecta intención a partir de los dominios visitados.

        Args:
            domains: Lista de dominios de las pestañas abiertas.
        Returns:
            Tupla ``(intent, confidence)``.
        """
        if not domains:
            return SessionIntent.GENERAL, 0.0
        scores: Counter = Counter()
        for domain in domains:
            domain_lower = domain.lower()
            for intent_key, patterns in self.DOMAIN_PATTERNS.items():
                for pattern in patterns:
                    if pattern in domain_lower:
                        scores[intent_key] += 1
                        break
        return self._pick_winner(scores, len(domains))
    def detect_from_titles(self, titles: List[str]) -> Tuple[SessionIntent, float]:
        """Detecta intención a partir de los títulos de las pestañas.

        Args:
            titles: Lista de títulos de pestañas.
        Returns:
            Tupla ``(intent, confidence)``.
        """
        if not titles:
            return SessionIntent.GENERAL, 0.0
        scores: Counter = Counter()
        joined = " ".join(titles).lower()
        for intent_key, keywords in self.TITLE_KEYWORDS.items():
            for keyword in keywords:
                count = joined.count(keyword.lower())
                if count > 0:
                    scores[intent_key] += count
        return self._pick_winner(scores, max(len(titles), 1))
    def detect_hybrid(
        self,
        tab_contexts: List[Any],
    ) -> Tuple[SessionIntent, float]:
        """Detección híbrida combinando dominios y títulos.

        ``tab_contexts`` debe ser una lista de objetos con atributos
        ``domain`` y ``title`` (como ``gentab_engine.TabContext``).

        Args:
            tab_contexts: Contextos de pestañas.
        Returns:
            Tupla ``(intent, confidence)``.
        """
        domains = [getattr(tc, "domain", "") for tc in tab_contexts if getattr(tc, "domain", "")]
        titles = [getattr(tc, "title", "") for tc in tab_contexts if getattr(tc, "title", "")]

        domain_intent, domain_conf = self.detect_from_domains(domains)
        title_intent, title_conf = self.detect_from_titles(titles)

        if domain_conf >= title_conf:
            combined_conf = min(1.0, domain_conf * 0.6 + title_conf * 0.4)
            return domain_intent, combined_conf
        combined_conf = min(1.0, title_conf * 0.6 + domain_conf * 0.4)
        return title_intent, combined_conf
    @staticmethod
    def _pick_winner(scores: Counter, total: int) -> Tuple[SessionIntent, float]:
        """Selecciona la intención ganadora del contador de scores."""
        if not scores:
            return SessionIntent.GENERAL, 0.0
        best_key, best_count = scores.most_common(1)[0]
        confidence = min(1.0, best_count / max(total, 1))

        try:
            intent = SessionIntent(best_key)
        except ValueError:
            intent = SessionIntent.GENERAL
            confidence = 0.0
        return intent, round(confidence, 3)


# ═════════════════════════════════════════════════════════════════════════════
# SessionContextAnalyzer
# ═════════════════════════════════════════════════════════════════════════════

class SessionContextAnalyzer(QObject):
    """Analiza patrones de navegación en la sesión actual.

    Emite ``analysis_ready`` cuando el análisis finaliza con un dict que
    contiene: ``intent``, ``confidence``, ``tab_count``, ``domains``,
    ``related_tabs``, ``suggested_action``.
    """

    analysis_ready = Signal(dict)

    _ACTION_MAP: Dict[SessionIntent, str] = {
        SessionIntent.RESEARCH: "Crear resumen de investigación con GenTab",
        SessionIntent.SHOPPING: "Comparar productos en una tabla",
        SessionIntent.NEWS: "Generar briefing de noticias",
        SessionIntent.TRAVEL: "Crear itinerario de viaje",
        SessionIntent.CODING: "Generar documentación técnica",
        SessionIntent.ENTERTAINMENT: "Crear playlist o watchlist",
        SessionIntent.GENERAL: "Organizar pestañas por tema",
    }

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._detector = IntentDetector()
    def analyze_current_session(self, tab_manager: Any) -> Dict[str, Any]:
        """Analiza las pestañas abiertas en el ``TabManager``.

        Args:
            tab_manager: Instancia de ``tabs.TabManager``.
        Returns:
            Dict con claves ``intent``, ``confidence``, ``tab_count``,
            ``domains``, ``related_tabs``, ``suggested_action``.
        """
        tabs_info = self._extract_tabs_info(tab_manager)
        if not tabs_info:
            result = self._empty_result()
            self.analysis_ready.emit(result)
            return result
        domains = [info["domain"] for info in tabs_info]
        titles = [info["title"] for info in tabs_info]

        domain_intent, domain_conf = self._detector.detect_from_domains(domains)
        title_intent, title_conf = self._detector.detect_from_titles(titles)

        if domain_conf >= title_conf:
            intent = domain_intent
            confidence = min(1.0, domain_conf * 0.6 + title_conf * 0.4)
        else:
            intent = title_intent
            confidence = min(1.0, title_conf * 0.6 + domain_conf * 0.4)
        related = self._find_related_tabs(tabs_info, intent)

        result: Dict[str, Any] = {
            "intent": intent,
            "confidence": round(confidence, 3),
            "tab_count": len(tabs_info),
            "domains": list(set(domains)),
            "related_tabs": related,
            "suggested_action": self._ACTION_MAP.get(intent, ""),
        }

        self.analysis_ready.emit(result)
        return result
    def _extract_tabs_info(self, tab_manager: Any) -> List[Dict[str, str]]:
        """Extrae URL, título y dominio de cada pestaña."""
        from PySide6.QtWebEngineWidgets import QWebEngineView

        info_list: List[Dict[str, str]] = []
        tabs_widget = getattr(tab_manager, "tabs", None)
        if tabs_widget is None:
            return info_list
        for i in range(tabs_widget.count()):
            widget = tabs_widget.widget(i)
            if not isinstance(widget, QWebEngineView):
                continue
            url = widget.url().toString()
            title = widget.title() or tabs_widget.tabText(i) or ""
            domain = ""
            try:
                domain = urlparse(url).netloc
            except Exception:
                pass
            info_list.append({
                "index": str(i),
                "url": url,
                "title": title,
                "domain": domain,
            })
        return info_list
    def _find_related_tabs(
        self,
        tabs_info: List[Dict[str, str]],
        intent: SessionIntent,
    ) -> List[str]:
        """Identifica pestañas relacionadas con la intención detectada."""
        patterns = IntentDetector.DOMAIN_PATTERNS.get(intent.value, [])
        keywords = IntentDetector.TITLE_KEYWORDS.get(intent.value, [])
        related: List[str] = []
        for info in tabs_info:
            domain = info["domain"].lower()
            title = info["title"].lower()
            match = any(p in domain for p in patterns) or any(k in title for k in keywords)
            if match:
                related.append(info["index"])
        return related
    @staticmethod
    def _empty_result() -> Dict[str, Any]:
        return {
            "intent": SessionIntent.GENERAL,
            "confidence": 0.0,
            "tab_count": 0,
            "domains": [],
            "related_tabs": [],
            "suggested_action": "",
        }
