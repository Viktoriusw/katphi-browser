#!/usr/bin/env python3
"""
Panel de Chat con IA — Copiloto del navegador con Navegación Aumentada por IA.

Integra el chat conversacional con el sistema de análisis de sesión,
sugerencias proactivas y generación de GenTabs.
"""

import json
import re
import time
import requests
from urllib.parse import quote_plus, urlparse, parse_qs, unquote
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QTextEdit, QPushButton, QLabel, QSpinBox,
    QLineEdit, QComboBox, QListWidget, QListWidgetItem,
    QCheckBox, QGroupBox, QScrollArea, QFrame, QMessageBox,
    QSplitter, QProgressBar, QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, QEventLoop, Signal, QThread
from PySide6.QtGui import QFont, QColor, QTextCursor

from base_panel import BasePanel
from llm_client import (
    LLMClient, LLMConfig, LLMError,
    PROVIDER_LOCAL, PROVIDER_LLMAPI, PROVIDER_ANTHROPIC, PROVIDER_HUGGINGFACE,
    PROVIDER_OLLAMA, OLLAMA_DEFAULT_URL, OPENAI_COMPAT_PROVIDERS,
    HUGGINGFACE_MODELS, HUGGINGFACE_DEFAULT_MODEL,
    LLMAPI_FREE_MODELS, ANTHROPIC_MODELS, ANTHROPIC_DEFAULT_MODEL,
)
from llm_provider_widgets import (
    build_compat_provider_widget, load_compat_fields, save_compat_fields,
    ANTHROPIC_MODEL_DESCRIPTIONS, fill_anthropic_model_combo, select_anthropic_model,
    refresh_anthropic_models,
)

# Importación opcional del sistema de navegación IA
try:
    from session_intent_detector import SessionContextAnalyzer, SessionIntent
    from proactive_suggestion_engine import ProactiveSuggestionEngine, SuggestionType
    _AI_NAV_OK = True
except ImportError:
    _AI_NAV_OK = False

# Helio: importación de nivel 2 (solo detector de intención, sin chromadb/embeddings)
try:
    from session_intent_detector import IntentDetector as _HelioIntentDetector
    _HELIO_INTENT_OK = True
except ImportError:
    _HELIO_INTENT_OK = False

SYSTEM_PROMPT_BROWSER = """You are the AI copilot of a modern web browser. You help the user navigate, search and discover content.

When you recommend websites, tools, articles or resources, ALWAYS provide recommendations as SEARCH-READY items, not fragile deep links.

- Use markdown links with clear labels: [What to search](https://example.com) as reference if needed
- Suggest 2-5 concrete options
- Prefer robust recommendations that can be searched in Google/Bing/DuckDuckGo
- The browser will convert your recommendations into search result tabs."""

SYSTEM_PROMPT_NAV_ANALYST = """You are an expert web navigation analyst. Analyze the browser session described by the user.
Respond in Spanish. Be concise and actionable:
- Summarize what the user is researching/doing
- Identify 3-5 key insights from the open tabs
- Suggest 2-3 next steps or related resources
- Format with headers and bullet points."""

import logging as _log_module
_chat_log = _log_module.getLogger(__name__)


class ChatWorker(QThread):
    """Ejecuta la llamada al LLM en un hilo separado para no bloquear el UI."""

    chunk_received = Signal(str)   # fragmento de texto (streaming)
    finished = Signal(str)         # respuesta completa
    error = Signal(str)            # mensaje de error

    def __init__(self, llm_config: "LLMConfig", messages: list,
                 max_tokens: int = 4096, temperature: float = 0.7):
        super().__init__()
        self._llm_config = llm_config
        self._messages = messages
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._cancelled = False
    def cancel(self):
        self._cancelled = True
    def run(self):
        try:
            client = LLMClient(self._llm_config)
            full_text = ""

            # Intentar streaming primero
            try:
                for chunk in client.chat_stream(
                    self._messages,
                    max_tokens=self._max_tokens,
                    temperature=self._temperature,
                ):
                    if self._cancelled:
                        return
                    full_text += chunk
                    self.chunk_received.emit(chunk)
                self.finished.emit(full_text)
            except AttributeError:
                # Fallback sin streaming si el método no existe
                content = client.chat(
                    self._messages,
                    max_tokens=self._max_tokens,
                    temperature=self._temperature,
                )
                if not self._cancelled:
                    self.finished.emit(content)
        except LLMError as e:
            _chat_log.error("ChatWorker LLMError: %s", e, exc_info=True)
            if not self._cancelled:
                self.error.emit(str(e))
        except Exception as e:
            _chat_log.error("ChatWorker error: %s", e, exc_info=True)
            if not self._cancelled:
                self.error.emit(f"Error inesperado: {e}")


class ChatPanelSafe(BasePanel):
    # Señal para solicitar apertura de GenTab desde dentro del panel
    gentab_requested = Signal(str)

    # _C se construye dinámicamente desde ThemeEngine en _build_color_palette()
    _C: dict = {}

    def __init__(self, parent=None):
        self.chat_history = []
        self.session_messages = []
        self.llm_config = LLMConfig.load("ChatPanel")
        self.server_url = self.llm_config.local_url
        self.activity_timer = None
        self._activity_frames = ["◜", "◝", "◞", "◟"]
        self._activity_idx = 0
        self._last_session_analysis = {}
        self._chat_worker: "ChatWorker | None" = None
        self._streaming_placeholder_added = False

        # ── Helio: estado interno ──
        self._helio_last_url: str = ""
        self._helio_last_time: float = 0.0
        self._helio_suggestions_container = None
        self._helio_suggestion_frames: list = []
        self._helio_refresh_timer: "QTimer | None" = None

        # Inicializar _C antes de super().__init__ porque los métodos
        # create_*_tab() se invocan durante setup_ui() dentro del constructor base.
        # En este punto ThemeEngine ya está activo, pero como fallback usamos
        # los tokens oscuros por defecto definidos en base_panel.
        try:
            from ui.core.theme_engine import get_theme_engine as _gte
            _te = _gte()
            if _te:
                _data = _te.get_theme_data()
                _colors = _data.get("colors", {})
                import re as _re2
                def _rxa(h, a):
                    m = _re2.match(r"#([0-9a-fA-F]{6})", h)
                    if m:
                        rv, gv, bv = int(m.group(1)[:2],16), int(m.group(1)[2:4],16), int(m.group(1)[4:],16)
                        return f"rgba({rv},{gv},{bv},{a})"
                    return h
                _bg = _colors.get("background", "#1A1A1A")
                _sf = _colors.get("surface", "#222222")
                _pr = _colors.get("primary", "#F0F0F0")
                _se = _colors.get("secondary", "#A0A0A0")
                _ac = _colors.get("accent", "#4B9EFF")
                _bo = _colors.get("border", "rgba(255,255,255,0.08)")
                _ho = _colors.get("hover", "#303030")
                _er = _colors.get("error", "#F85149")
                _su = _colors.get("success", "#3FB950")
                self._C = {
                    "surface_0": _bg, "surface_1": _sf, "surface_hover": _ho,
                    "border": _bo, "text_primary": _pr, "text_secondary": _se,
                    "text_muted": _colors.get("text_disabled", _se),
                    "accent": _ac, "accent_subtle": _rxa(_ac, 0.12),
                    "error": _er, "error_subtle": _rxa(_er, 0.08),
                    "success": _su,
                    "input_bg": _colors.get("input_background", _sf),
                    "input_border": _colors.get("input_border", _bo),
                    "input_focus": _colors.get("input_focus", _ac),
                    "selected": _colors.get("selected", "#303030"),
                    "scroll_handle": _rxa(_pr, 0.15),
                    "scroll_handle_hover": _rxa(_pr, 0.30),
                    "warning": _colors.get("warning", "#D29922"),
                }
            else:
                raise RuntimeError("no engine")
        except Exception:
            self._C = {
                "surface_0": "#1A1A1A", "surface_1": "#222222", "surface_hover": "#303030",
                "border": "rgba(255,255,255,0.08)", "text_primary": "#F0F0F0",
                "text_secondary": "#A0A0A0", "text_muted": "#606060",
                "accent": "#4B9EFF", "accent_subtle": "rgba(75,158,255,0.12)",
                "error": "#F85149", "error_subtle": "rgba(248,81,73,0.08)",
                "success": "#3FB950", "warning": "#D29922",
                "input_bg": "#222222", "input_border": "rgba(255,255,255,0.08)",
                "input_focus": "#4B9EFF", "selected": "#303030",
                "scroll_handle": "rgba(255,255,255,0.12)",
                "scroll_handle_hover": "rgba(255,255,255,0.25)",
            }
        super().__init__(parent)

        # Helio: conectar auto-contexto tras construir la UI
        QTimer.singleShot(2000, self._helio_connect_auto_context)
    def _build_color_palette(self) -> dict:
        """Construye la paleta _C leyendo el ThemeEngine activo.
        Si el ThemeEngine no está disponible, devuelve self._C existente o el fallback."""
        try:
            c = self.get_theme_colors()
            if c:
                return c
        except Exception:
            pass
        return self._C if self._C else {
            "surface_0": "#1A1A1A", "surface_1": "#222222", "surface_hover": "#303030",
            "border": "rgba(255,255,255,0.08)", "text_primary": "#F0F0F0",
            "text_secondary": "#A0A0A0", "text_muted": "#606060",
            "accent": "#4B9EFF", "accent_subtle": "rgba(75,158,255,0.12)",
            "error": "#F85149", "error_subtle": "rgba(248,81,73,0.08)",
            "success": "#3FB950", "warning": "#D29922",
            "input_bg": "#222222", "input_border": "rgba(255,255,255,0.08)",
            "input_focus": "#4B9EFF", "selected": "#303030",
            "scroll_handle": "rgba(255,255,255,0.12)",
            "scroll_handle_hover": "rgba(255,255,255,0.25)",
        }
    def get_tab_definitions(self):
        return [
            (self.create_chat_tab,       "Chat"),
            (self.create_nav_tab,        "Navegación"),
            (self.create_settings_tab,   "Config"),
            (self.create_history_tab,    "Historial"),
            (self.create_help_tab,       "Ayuda"),
        ]
    def post_setup_ui(self):
        self.set_object_name("chatPanel")
        self._apply_chat_style()
    def _on_theme_changed(self, theme_name):
        """Recarga estilos del chat cuando cambia el tema global."""
        super()._on_theme_changed(theme_name)
        self._C = self._build_color_palette()
        self._apply_chat_style()
    def _apply_chat_style(self):
        """Aplica el sistema de diseño al panel de chat usando el tema activo."""
        self._C = self._build_color_palette()
        c = self._C
        self.setStyleSheet(f"""
            QWidget#chatPanel, QWidget {{
                background: {c['surface_0']};
                color: {c['text_primary']};
            }}
            QTabWidget::pane {{
                border: none;
                background: {c['surface_0']};
            }}
            QTabBar {{
                background: transparent;
            }}
            QTabBar::tab {{
                background: transparent;
                color: {c['text_secondary']};
                border: none;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                min-height: 26px;
            }}
            QTabBar::tab:selected {{
                background: {c['surface_1']};
                color: {c['text_primary']};
            }}
            QTabBar::tab:hover:!selected {{
                background: {c['surface_hover']};
            }}
            /* Mensajes usuario — borde izquierdo acento */
            QWidget#userBubble {{
                background: {c['accent_subtle']};
                border-left: 2px solid {c['accent']};
                border-radius: 0px 6px 6px 0px;
            }}
            QWidget#assistantBubble {{
                background: transparent;
            }}
            QWidget#errorBubble {{
                background: {c['error_subtle']};
                border-left: 2px solid {c['error']};
                border-radius: 0px 6px 6px 0px;
            }}
            QLabel#bubbleTitle {{
                font-size: 11px;
                color: {c['text_muted']};
                font-weight: 600;
                background: transparent;
            }}
            QLabel#bubbleMsg {{
                font-size: 13px;
                color: {c['text_primary']};
                background: transparent;
            }}
            /* Input area */
            QTextEdit#chatInput {{
                background: transparent;
                border: none;
                font-size: 13px;
                color: {c['text_primary']};
            }}
            /* Scrollbar mínima */
            QScrollBar:vertical {{
                background: transparent; width: 6px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(255,255,255,0.12);
                border-radius: 3px; min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: rgba(255,255,255,0.25);
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {{ background: transparent; }}
            /* Botones */
            QPushButton {{
                background: transparent;
                border: 1px solid {c['border']};
                border-radius: 4px;
                color: {c['text_secondary']};
                font-size: 12px;
                padding: 4px 10px;
            }}
            QPushButton:hover {{
                background: {c['surface_hover']};
                color: {c['text_primary']};
            }}
            QPushButton#chatSend {{
                background: {c['accent_subtle']};
                border-color: {c['accent']};
                color: {c['accent']};
                font-weight: 600;
                min-width: 28px;
                max-width: 28px;
                min-height: 28px;
                max-height: 28px;
                border-radius: 6px;
                padding: 0px;
                font-size: 16px;
            }}
            QPushButton#chatSend:hover {{
                background: {c['accent']};
                color: #FFFFFF;
            }}
            /* Grupos */
            QGroupBox {{
                background: transparent;
                border: 1px solid {c['border']};
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 8px;
                font-size: 11px;
                color: {c['text_secondary']};
            }}
            QGroupBox::title {{
                color: {c['text_secondary']};
                subcontrol-origin: margin;
                left: 8px; padding: 0 4px;
            }}
            /* ComboBox, Spin */
            QComboBox, QSpinBox {{
                background: {c['surface_1']};
                border: 1px solid {c['border']};
                border-radius: 4px;
                color: {c['text_primary']};
                padding: 3px 6px;
                font-size: 12px;
            }}
            QComboBox::drop-down {{
                border: none; width: 16px;
            }}
            /* Status */
            QLabel#statusBadge {{
                font-size: 11px;
                padding: 2px 6px;
                border-radius: 3px;
            }}
        """)
    # ── Helio: Auto-contexto continuo (Mejora 1) ────────────────────────────

    def _helio_connect_auto_context(self) -> None:
        """Conecta señales del navegador para actualizar contexto automáticamente."""
        try:
            main = self.window()
            if not hasattr(main, "tab_manager"):
                return
            tm = main.tab_manager
            # Conectar cambio de pestaña
            tm.tabs.currentChanged.connect(self._helio_on_tab_changed)
            # Conectar loadFinished de pestañas existentes
            for i in range(tm.tabs.count()):
                browser = tm.tabs.widget(i)
                if browser and hasattr(browser, "loadFinished"):
                    try:
                        browser.loadFinished.connect(self._helio_on_page_loaded)
                    except Exception:
                        pass
            # Timer de debounce para sugerencias Helio (Mejora 5)
            self._helio_refresh_timer = QTimer(self)
            self._helio_refresh_timer.setSingleShot(True)
            self._helio_refresh_timer.setInterval(10000)
            self._helio_refresh_timer.timeout.connect(self._helio_refresh_suggestions)
            _chat_log.info("Helio: auto-context connected")
        except Exception as e:
            _chat_log.debug("Helio: auto-context connection failed: %s", e)
    def _helio_on_tab_changed(self, index: int) -> None:
        """Cuando cambia la pestaña activa, extrae contexto automáticamente."""
        try:
            main = self.window()
            if not hasattr(main, "tab_manager"):
                return
            browser = main.tab_manager.tabs.widget(index)
            if browser and hasattr(browser, "url"):
                url = browser.url().toString()
                if url and not url.startswith("about:"):
                    self._helio_extract_and_update(browser)
            # Conectar loadFinished si no estaba conectado
            if browser and hasattr(browser, "loadFinished"):
                try:
                    browser.loadFinished.connect(self._helio_on_page_loaded)
                except Exception:
                    pass  # ya conectado
            # Programar refresco de sugerencias
            if self._helio_refresh_timer:
                self._helio_refresh_timer.start()
        except Exception as e:
            _chat_log.debug("Helio: tab change handler error: %s", e)
    def _helio_on_page_loaded(self, ok: bool) -> None:
        """Cuando una página termina de cargar, extrae contexto."""
        if not ok:
            return
        try:
            main = self.window()
            if not hasattr(main, "tab_manager"):
                return
            browser = main.tab_manager.tabs.currentWidget()
            if browser and hasattr(browser, "url"):
                self._helio_extract_and_update(browser)
            # Programar refresco de sugerencias
            if self._helio_refresh_timer:
                self._helio_refresh_timer.start()
        except Exception as e:
            _chat_log.debug("Helio: page loaded handler error: %s", e)
    def _helio_extract_and_update(self, browser) -> None:
        """Extrae contenido de la pestaña y actualiza el contexto del chat."""
        try:
            url = browser.url().toString()
            if not url or url.startswith("about:"):
                return
            # Throttle: no re-extraer si misma URL en últimos 5 segundos
            now = time.time()
            if url == self._helio_last_url and (now - self._helio_last_time) < 5.0:
                return
            self._helio_last_url = url
            self._helio_last_time = now

            title = ""
            if hasattr(browser, "page") and browser.page():
                title = browser.page().title() or ""
            def _on_html(html):
                try:
                    extracted = self._simple_extract_text(html, url, title)
                    if hasattr(self, "context_display"):
                        self.context_display.setPlainText(extracted)
                    _chat_log.debug("Helio: auto-extracted %d chars from %s", len(extracted), url[:60])
                except Exception as e:
                    _chat_log.debug("Helio: extraction callback error: %s", e)
            if hasattr(browser, "page") and browser.page():
                browser.page().toHtml(_on_html)
        except Exception as e:
            _chat_log.debug("Helio: extract_and_update error: %s", e)
    # ── Helio: Guard con fallback de 3 niveles (Mejora 2) ─────────────────

    def _helio_detect_intent_level(self) -> int:
        """Detecta el nivel de funcionalidad IA disponible.

        Returns:
            1 = completo (_AI_NAV_OK + ai_nav_enabled en MainWindow)
            2 = ligero (IntentDetector disponible, sin chromadb)
            3 = básico (heurísticas simples, siempre disponible)
        """
        try:
            if _AI_NAV_OK:
                main = self.window()
                if hasattr(main, "ai_nav_enabled") and main.ai_nav_enabled:
                    return 1
        except Exception:
            pass
        if _HELIO_INTENT_OK:
            return 2
        return 3
    def _helio_basic_intent(self) -> dict:
        """Detección de intención básica por heurísticas de dominio (nivel 3)."""
        result = {"intent": "general", "confidence": 0.3, "source": "helio_basic",
                  "suggested_action": "Explora más pestañas para un análisis completo"}
        try:
            main = self.window()
            if not hasattr(main, "tab_manager"):
                return result
            browser = main.tab_manager.tabs.currentWidget()
            if not browser or not hasattr(browser, "url"):
                return result
            url = browser.url().toString().lower()
            domain = urlparse(url).netloc.lower() if url else ""

            _PATTERNS = {
                "shopping": ["amazon", "ebay", "aliexpress", "mercadolibre", "etsy", "shopify", "tienda"],
                "news": ["bbc", "cnn", "reuters", "elpais", "elmundo", "nytimes", "news"],
                "coding": ["github", "stackoverflow", "gitlab", "codepen", "dev.to", "docs.python"],
                "research": ["scholar.google", "arxiv", "wikipedia", "pubmed", "researchgate"],
                "travel": ["booking", "airbnb", "tripadvisor", "skyscanner", "expedia"],
                "entertainment": ["youtube", "netflix", "twitch", "spotify", "imdb"],
            }
            for intent, keywords in _PATTERNS.items():
                if any(kw in domain for kw in keywords):
                    result["intent"] = intent
                    result["confidence"] = 0.5
                    _ACTIONS = {
                        "shopping": "Compara precios con GenTab",
                        "news": "Resume las noticias con el asistente",
                        "coding": "Analiza el código con el copiloto",
                        "research": "Crea un resumen ejecutivo de tus fuentes",
                        "travel": "Compara destinos y precios",
                        "entertainment": "Descubre contenido relacionado",
                    }
                    result["suggested_action"] = _ACTIONS.get(intent, result["suggested_action"])
                    break
        except Exception as e:
            _chat_log.debug("Helio: basic intent error: %s", e)
        return result
    def _helio_analyze_with_level(self, level: int) -> dict:
        """Ejecuta análisis de sesión según el nivel disponible."""
        if level == 1:
            try:
                analyzer = SessionContextAnalyzer()
                main = self.window()
                if hasattr(main, "tab_manager"):
                    return analyzer.analyze_current_session(main.tab_manager)
            except Exception:
                pass
            # Degradar a nivel 2
            level = 2
        if level == 2 and _HELIO_INTENT_OK:
            try:
                detector = _HelioIntentDetector()
                main = self.window()
                if not hasattr(main, "tab_manager"):
                    return self._helio_basic_intent()
                tabs = main.tab_manager.tabs
                domains = []
                titles = []
                for i in range(tabs.count()):
                    w = tabs.widget(i)
                    if w and hasattr(w, "url"):
                        url = w.url().toString()
                        if url and not url.startswith("about:"):
                            domains.append(urlparse(url).netloc.lower())
                            if hasattr(w, "page") and w.page():
                                titles.append(w.page().title() or "")
                intent = detector.detect_hybrid(domains, titles)
                confidence = 0.4 if intent.value != "general" else 0.2
                return {
                    "intent": intent,
                    "confidence": confidence,
                    "tab_count": tabs.count(),
                    "domains": domains[:5],
                    "suggested_action": f"Análisis ligero: sesión de {intent.value}",
                    "source": "helio_level2",
                }
            except Exception:
                pass
        # Nivel 3: básico
        basic = self._helio_basic_intent()
        main = self.window()
        tab_count = 0
        if hasattr(main, "tab_manager"):
            tab_count = main.tab_manager.tabs.count()
        basic["tab_count"] = tab_count
        basic["domains"] = []
        return basic
    # ── Helio: Contexto de chat para GenTab (Mejora 3) ────────────────────

    def _helio_build_gentab_context(self, user_prompt: str) -> str:
        """Enriquece el prompt de GenTab con el historial reciente del chat."""
        try:
            history_parts = []
            # Tomar los últimos 6 mensajes del historial de sesión
            recent = self.session_messages[-6:] if self.session_messages else []
            total_chars = 0
            for msg in recent:
                role = "Usuario" if msg.get("role") == "user" else "Asistente"
                content = msg.get("content", "")
                # Truncar mensajes largos
                if len(content) > 400:
                    content = content[:400] + "..."
                history_parts.append(f"{role}: {content}")
                total_chars += len(content)
                if total_chars > 2000:
                    break
            if history_parts:
                history_text = "\n".join(history_parts)
                return (
                    f"[Contexto de la conversación previa]\n"
                    f"{history_text}\n\n"
                    f"[Solicitud actual]\n"
                    f"{user_prompt}"
                )
        except Exception as e:
            _chat_log.debug("Helio: build_gentab_context error: %s", e)
        return user_prompt
    # ── Helio: Panel de sugerencias (Mejora 5) ────────────────────────────

    def _helio_refresh_suggestions(self) -> None:
        """Actualiza las sugerencias en el panel de navegación."""
        if not self._helio_suggestion_frames:
            return
        try:
            level = self._helio_detect_intent_level()
            suggestions = []

            if level == 1 and _AI_NAV_OK:
                try:
                    main = self.window()
                    if hasattr(main, "suggestion_engine") and main.suggestion_engine:
                        analysis = self._helio_analyze_with_level(1)
                        if analysis:
                            raw = main.suggestion_engine.generate_suggestions(analysis)
                            for s in (raw or [])[:3]:
                                suggestions.append({
                                    "text": getattr(s, "message", str(s)),
                                    "action": getattr(s, "suggestion_type", None),
                                })
                except Exception:
                    pass
            # Sugerencias básicas si no hay suficientes del nivel 1
            if len(suggestions) < 3:
                main = self.window()
                tab_count = 0
                if hasattr(main, "tab_manager"):
                    tab_count = main.tab_manager.tabs.count()
                basic = self._helio_basic_intent()
                intent = basic.get("intent", "general")

                _basic_suggestions = []
                if tab_count > 4:
                    _basic_suggestions.append({
                        "text": f"Tienes {tab_count} pestañas — resume todas con IA",
                        "action": "summarize",
                    })
                if intent == "shopping":
                    _basic_suggestions.append({
                        "text": "Compara productos en una tabla interactiva",
                        "action": "gentab_compare",
                    })
                elif intent == "research":
                    _basic_suggestions.append({
                        "text": "Genera flashcards de estudio",
                        "action": "gentab_flashcards",
                    })
                elif intent == "news":
                    _basic_suggestions.append({
                        "text": "Resume las noticias en un briefing",
                        "action": "gentab_news",
                    })
                if tab_count > 1:
                    _basic_suggestions.append({
                        "text": "Crea un dashboard desde tus pestañas",
                        "action": "gentab_dashboard",
                    })
                _basic_suggestions.append({
                    "text": "Analiza tu sesión de navegación",
                    "action": "analyze",
                })

                for bs in _basic_suggestions:
                    if len(suggestions) >= 3:
                        break
                    if not any(s["text"] == bs["text"] for s in suggestions):
                        suggestions.append(bs)
            # Actualizar UI
            for i, frame in enumerate(self._helio_suggestion_frames):
                if i < len(suggestions):
                    s = suggestions[i]
                    lbl = frame.findChild(QLabel, f"helio_sug_label_{i}")
                    if lbl:
                        lbl.setText(s["text"])
                    frame.setProperty("_helio_action", s.get("action"))
                    frame.show()
                else:
                    frame.hide()
        except Exception as e:
            _chat_log.debug("Helio: refresh suggestions error: %s", e)
    def _helio_on_suggestion_clicked(self, index: int) -> None:
        """Ejecuta la acción de una sugerencia del panel Helio."""
        try:
            if index >= len(self._helio_suggestion_frames):
                return
            frame = self._helio_suggestion_frames[index]
            action = frame.property("_helio_action")

            if action == "summarize":
                self._apply_quick_action(
                    "Resume todas las pestañas abiertas en un briefing ejecutivo.",
                    "multi",
                )
            elif action == "analyze":
                self._run_session_analysis()
            elif action and action.startswith("gentab_"):
                _prompts = {
                    "gentab_compare": "Compara los productos/contenidos de todas las pestañas en una tabla interactiva ordenable.",
                    "gentab_flashcards": "Genera flashcards interactivas con preguntas y respuestas extraídas del contenido.",
                    "gentab_news": "Resume las noticias en un briefing ejecutivo con los puntos más importantes.",
                    "gentab_dashboard": "Crea un dashboard con métricas y datos extraídos de las pestañas. Usa gráficos y contadores.",
                }
                prompt = _prompts.get(action, "Genera una app interactiva desde las pestañas.")
                self._apply_quick_action(prompt, "gentab")
            else:
                # Acción genérica: poner texto en el chat
                lbl = frame.findChild(QLabel, f"helio_sug_label_{index}")
                if lbl:
                    self.set_input_text(lbl.text())
        except Exception as e:
            _chat_log.debug("Helio: suggestion click error: %s", e)
    # ── Métodos públicos para integración externa ────────────────────────────

    def set_input_text(self, text: str) -> None:
        """Establece el texto del input de chat y cambia al tab Chat."""
        if hasattr(self, "message_input"):
            self.message_input.setPlainText(text)
            self.message_input.setFocus()
        if hasattr(self, "tab_widget") and self.tab_widget:
            self.tab_widget.setCurrentIndex(0)
    def set_prompt(self, prompt: str) -> None:
        """Recibe un prompt de GenTab, lo muestra y activa el modo GenTab."""
        if hasattr(self, "message_input"):
            self.message_input.setPlainText(prompt)
        if hasattr(self, "assistant_mode"):
            idx = self.assistant_mode.findData("gentab")
            if idx >= 0:
                self.assistant_mode.setCurrentIndex(idx)
        if hasattr(self, "tab_widget") and self.tab_widget:
            self.tab_widget.setCurrentIndex(0)
    def show_navigation_tab(self) -> None:
        """Cambia al tab de Navegación IA."""
        if hasattr(self, "tab_widget") and self.tab_widget:
            self.tab_widget.setCurrentIndex(1)
    def create_chat_tab(self):
        """Tab principal del chat — estilo documento, no burbujas."""
        c = self._C
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Mini header de estado ──────────────────────────────────────────────
        status_bar = QWidget()
        status_bar.setFixedHeight(32)
        status_bar.setStyleSheet(
            f"background: {c['surface_1']}; border-bottom: 1px solid {c['border']};"
        )
        sb_layout = QHBoxLayout(status_bar)
        sb_layout.setContentsMargins(12, 0, 8, 0)
        sb_layout.setSpacing(6)

        self.status_label = QLabel("● Desconectado")
        self.status_label.setStyleSheet(f"color: {c['error']}; font-size: 11px; background: transparent;")
        sb_layout.addWidget(self.status_label)
        sb_layout.addStretch()

        self.test_connection_btn = QPushButton("Conectar")
        self.test_connection_btn.setFixedHeight(22)
        self.test_connection_btn.clicked.connect(self.test_connection_safe)
        self.test_connection_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: 1px solid {c['border']};
                border-radius: 3px; color: {c['text_secondary']};
                font-size: 11px; padding: 0px 8px;
            }}
            QPushButton:hover {{
                border-color: {c['accent']}; color: {c['accent']};
            }}
        """)
        sb_layout.addWidget(self.test_connection_btn)
        layout.addWidget(status_bar)

        # ── Contexto de página (colapsable visualmente) ────────────────────────
        ctx_bar = QWidget()
        ctx_bar.setStyleSheet(f"background: {c['surface_1']}; border-bottom: 1px solid {c['border']};")
        ctx_l = QHBoxLayout(ctx_bar)
        ctx_l.setContentsMargins(12, 4, 8, 4)
        ctx_l.setSpacing(6)

        self.context_display = QTextEdit()
        self.context_display.setReadOnly(True)
        self.context_display.setPlaceholderText("Sin contexto de página")
        self.context_display.setMaximumHeight(70)
        self.context_display.setStyleSheet(
            f"background: transparent; border: none; font-size: 11px; "
            f"color: {c['text_secondary']};"
        )
        ctx_l.addWidget(self.context_display, 1)

        ctx_btns = QVBoxLayout()
        ctx_btns.setSpacing(3)
        self.extract_context_btn = QPushButton("↻")
        self.extract_context_btn.setFixedSize(24, 24)
        self.extract_context_btn.setToolTip("Extraer contenido de la página actual")
        self.extract_context_btn.setCursor(Qt.PointingHandCursor)
        self.extract_context_btn.clicked.connect(self.extract_page_content_now)
        self.extract_context_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; border-radius: 3px; "
            f"color: {c['text_muted']}; font-size: 14px; }}"
            f"QPushButton:hover {{ background: {c['surface_hover']}; color: {c['accent']}; }}"
        )
        ctx_btns.addWidget(self.extract_context_btn)

        self.clear_context_btn = QPushButton()
        self.set_button_icon(self.clear_context_btn, "ide_close", 14)
        self.clear_context_btn.setFixedSize(24, 24)
        self.clear_context_btn.setToolTip("Limpiar contexto")
        self.clear_context_btn.setCursor(Qt.PointingHandCursor)
        self.clear_context_btn.clicked.connect(lambda: self.context_display.clear())
        self.clear_context_btn.setStyleSheet(self.extract_context_btn.styleSheet())
        ctx_btns.addWidget(self.clear_context_btn)
        ctx_l.addLayout(ctx_btns)
        layout.addWidget(ctx_bar)

        # ── Área de mensajes ───────────────────────────────────────────────────
        self.chat_scroll = QScrollArea()
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setObjectName("chatScroll")
        self.chat_scroll.setFrameShape(QFrame.NoFrame)
        self.chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chat_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.chat_scroll.setStyleSheet(f"background: {c['surface_0']}; border: none;")

        self.chat_messages_widget = QWidget()
        self.chat_messages_widget.setStyleSheet(f"background: {c['surface_0']};")
        self.chat_messages_layout = QVBoxLayout(self.chat_messages_widget)
        self.chat_messages_layout.setAlignment(Qt.AlignTop)
        self.chat_messages_layout.setSpacing(2)
        self.chat_messages_layout.setContentsMargins(0, 8, 0, 8)
        self.chat_messages_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)
        self.chat_scroll.setWidget(self.chat_messages_widget)
        layout.addWidget(self.chat_scroll, 1)

        # ── Área de input (fija en la parte inferior) ──────────────────────────
        input_area = QWidget()
        input_area.setObjectName("chatInputArea")
        input_area.setStyleSheet(
            f"background: {c['surface_1']}; border-top: 1px solid {c['border']};"
        )
        ia_layout = QVBoxLayout(input_area)
        ia_layout.setContentsMargins(12, 8, 12, 8)
        ia_layout.setSpacing(6)

        # Fila de modo + controles
        mode_row = QHBoxLayout()
        mode_row.setSpacing(6)

        self.assistant_mode = QComboBox()
        for mode_id, mode_label in self._ASSISTANT_MODES:
            self.assistant_mode.addItem(mode_label, mode_id)
        self.assistant_mode.setToolTip("Modo del asistente")
        self.assistant_mode.setFixedHeight(24)
        self.assistant_mode.setStyleSheet(f"""
            QComboBox {{
                background: transparent; border: 1px solid {c['border']};
                border-radius: 3px; color: {c['text_secondary']};
                font-size: 11px; padding: 0px 4px;
            }}
            QComboBox::drop-down {{ border: none; width: 14px; }}
            QComboBox QAbstractItemView {{
                background: {c['surface_2'] if 'surface_2' in c else c['surface_1']};
                color: {c['text_primary']};
                border: 1px solid {c['border']};
                selection-background-color: {c['surface_hover']};
            }}
        """)
        mode_row.addWidget(self.assistant_mode)

        self.context_checkbox = QCheckBox("Contexto")
        self.context_checkbox.setChecked(True)
        self.context_checkbox.toggled.connect(self.on_context_toggled)
        self.context_checkbox.setStyleSheet(
            f"color: {c['text_secondary']}; font-size: 11px; background: transparent;"
        )
        mode_row.addWidget(self.context_checkbox)
        mode_row.addStretch()

        self.clear_btn = QPushButton("Limpiar")
        self.clear_btn.setFixedHeight(22)
        self.clear_btn.clicked.connect(self.clear_chat)
        self.clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none;
                color: {c['text_muted']}; font-size: 11px;
            }}
            QPushButton:hover {{ color: {c['text_secondary']}; }}
        """)
        mode_row.addWidget(self.clear_btn)
        ia_layout.addLayout(mode_row)

        # Input + botón enviar
        input_row = QHBoxLayout()
        input_row.setSpacing(6)

        self.message_input = QTextEdit()
        self.message_input.setObjectName("chatInput")
        self.message_input.setPlaceholderText("Ask about this page...")
        self.message_input.setMinimumHeight(36)
        self.message_input.setMaximumHeight(100)
        self.message_input.setAcceptRichText(False)
        self.message_input.setStyleSheet(
            f"background: transparent; border: none; font-size: 13px; "
            f"color: {c['text_primary']}; padding: 4px 0px;"
        )
        input_row.addWidget(self.message_input, 1)

        self.send_btn = QPushButton("↑")
        self.send_btn.setObjectName("chatSend")
        self.send_btn.setFixedSize(28, 28)
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.clicked.connect(self.send_message_safe)
        self.send_btn.setEnabled(False)
        self.send_btn.setStyleSheet(f"""
            QPushButton {{
                background: {c['accent_subtle']}; color: {c['accent']};
                border: 1px solid {c['accent']}; border-radius: 6px;
                font-size: 16px; font-weight: bold;
            }}
            QPushButton:hover {{
                background: {c['accent']}; color: #FFFFFF;
            }}
            QPushButton:disabled {{
                background: transparent;
                border-color: {c['border']};
                color: {c['text_muted']};
            }}
        """)
        input_row.addWidget(self.send_btn)
        ia_layout.addLayout(input_row)
        layout.addWidget(input_area)

        widget.setLayout(layout)
        self.message_input.textChanged.connect(
            lambda: self.send_btn.setEnabled(bool(self.message_input.toPlainText().strip()))
        )
        return widget
    # ── Tab Navegación IA ────────────────────────────────────────────────────

    def _nav_group_style(self, c: dict) -> str:
        """Estilo de QGroupBox para el tab de navegación usando colores del tema."""
        return (
            f"QGroupBox {{ color: {c['text_primary']}; border: 1px solid {c['border']};"
            f" border-radius: 10px; margin-top: 8px; font-size: 13px; font-weight: bold; }}"
            f" QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px; }}"
        )
    def create_nav_tab(self):
        """Tab de Navegación Aumentada con IA: análisis de sesión + GenTab."""
        c = self._build_color_palette()
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        group_style = self._nav_group_style(c)

        # ── Análisis de sesión ────────────────────────────────────────────────
        session_group = QGroupBox("Análisis de Sesión")
        session_group.setStyleSheet(group_style)
        sg_layout = QVBoxLayout(session_group)
        sg_layout.setSpacing(8)

        # Badge de intención
        self._intent_badge = QLabel("— Sin analizar —")
        self._intent_badge.setAlignment(Qt.AlignCenter)
        self._intent_badge.setStyleSheet(
            f"background: {c['accent_subtle']}; border: 1px solid {c['border']};"
            f" border-radius: 8px; padding: 6px 12px; color: {c['text_primary']}; font-size: 13px;"
        )
        sg_layout.addWidget(self._intent_badge)

        # Barra de confianza
        conf_row = QHBoxLayout()
        conf_row.addWidget(QLabel("Confianza:"))
        self._conf_bar = QProgressBar()
        self._conf_bar.setRange(0, 100)
        self._conf_bar.setValue(0)
        self._conf_bar.setFixedHeight(10)
        self._conf_bar.setTextVisible(False)
        self._conf_bar.setStyleSheet(
            f"QProgressBar {{ background: {c['surface_1']}; border-radius: 5px; border: none; }}"
            f" QProgressBar::chunk {{ background: {c['accent']}; border-radius: 5px; }}"
        )
        conf_row.addWidget(self._conf_bar, 1)
        self._conf_pct_label = QLabel("0%")
        self._conf_pct_label.setFixedWidth(36)
        self._conf_pct_label.setStyleSheet(f"color: {c['text_secondary']}; font-size: 12px;")
        conf_row.addWidget(self._conf_pct_label)
        sg_layout.addLayout(conf_row)

        # Acción sugerida
        self._suggested_action_label = QLabel("")
        self._suggested_action_label.setWordWrap(True)
        self._suggested_action_label.setStyleSheet(
            f"color: {c['text_secondary']}; font-size: 12px; font-style: italic;"
        )
        sg_layout.addWidget(self._suggested_action_label)

        # Botón de análisis
        analyze_btn = QPushButton("Analizar sesión actual")
        analyze_btn.setStyleSheet(
            f"QPushButton {{ background: {c['surface_1']}; color: {c['text_primary']};"
            f" border: 1px solid {c['border']}; border-radius: 8px;"
            f" padding: 7px 14px; font-size: 13px; }}"
            f" QPushButton:hover {{ background: {c['surface_hover']}; border-color: {c['accent']}; }}"
        )
        analyze_btn.setCursor(Qt.PointingHandCursor)
        analyze_btn.clicked.connect(self._run_session_analysis)
        sg_layout.addWidget(analyze_btn)

        layout.addWidget(session_group)

        # ── Pestañas abiertas ─────────────────────────────────────────────────
        tabs_group = QGroupBox("Pestañas abiertas")
        tabs_group.setStyleSheet(group_style)
        tg_layout = QVBoxLayout(tabs_group)
        tg_layout.setSpacing(6)

        tabs_header = QHBoxLayout()
        self._tabs_count_label = QLabel("0 pestañas")
        self._tabs_count_label.setStyleSheet(f"color: {c['text_secondary']}; font-size: 12px;")
        tabs_header.addWidget(self._tabs_count_label)
        tabs_header.addStretch()
        refresh_tabs_btn = QPushButton()
        self.set_button_icon(refresh_tabs_btn, "refresh")
        refresh_tabs_btn.setFixedSize(28, 28)
        refresh_tabs_btn.setToolTip("Actualizar lista de pestañas")
        refresh_tabs_btn.setStyleSheet(
            f"QPushButton {{ background: {c['surface_1']}; color: {c['text_primary']};"
            f" border: 1px solid {c['border']}; border-radius: 6px; }}"
            f" QPushButton:hover {{ background: {c['surface_hover']}; }}"
        )
        refresh_tabs_btn.clicked.connect(self._refresh_open_tabs_list)
        tabs_header.addWidget(refresh_tabs_btn)
        tg_layout.addLayout(tabs_header)

        self._open_tabs_list = QListWidget()
        self._open_tabs_list.setMaximumHeight(130)
        self._open_tabs_list.setStyleSheet(
            f"QListWidget {{ background: {c['surface_1']}; border: 1px solid {c['border']};"
            f" border-radius: 8px; color: {c['text_primary']}; font-size: 12px; outline: none; }}"
            f" QListWidget::item {{ padding: 5px 8px; border-radius: 4px; }}"
            f" QListWidget::item:hover {{ background: {c['surface_hover']}; }}"
        )
        self._open_tabs_list.itemDoubleClicked.connect(self._on_tab_item_double_click)
        tg_layout.addWidget(self._open_tabs_list)

        layout.addWidget(tabs_group)

        # ── Acciones rápidas de navegación ───────────────────────────────────
        actions_group = QGroupBox("Acciones rápidas")
        actions_group.setStyleSheet(group_style)
        ag_layout = QVBoxLayout(actions_group)
        ag_layout.setSpacing(6)

        quick_actions = [
            ("Analizar y resumir sesión con IA",
             "Analiza todas mis pestañas abiertas, identifica qué estoy investigando y dame un resumen con insights clave.",
             "session"),
            ("Comparar contenido de pestañas",
             "Compara el contenido de todas las pestañas abiertas en una tabla interactiva con los puntos clave de cada una.",
             "gentab"),
            ("Resumen ejecutivo multi-pestaña",
             "Resume todas las pestañas abiertas en un briefing ejecutivo con los puntos más importantes.",
             "multi"),
            ("Mapa de enlaces y relaciones",
             "Genera un mapa de enlaces que muestre todos los links encontrados en las pestañas, agrupados por dominio.",
             "gentab"),
            ("Flashcards de estudio",
             "Genera flashcards interactivas con preguntas y respuestas extraídas del contenido de mis pestañas.",
             "gentab"),
            ("Dashboard de datos",
             "Crea un dashboard con métricas y KPIs extraídos de los datos de las pestañas. Usa gráficos y contadores.",
             "gentab"),
        ]

        _qa_style = (
            f"QPushButton {{ background: {c['surface_1']}; color: {c['text_primary']};"
            f" border: 1px solid {c['border']}; border-radius: 8px;"
            f" padding: 7px 12px; font-size: 12px; text-align: left; }}"
            f" QPushButton:hover {{ background: {c['surface_hover']}; border-color: {c['accent']}; }}"
        )
        for label, prompt, mode_text in quick_actions:
            btn = QPushButton(label)
            btn.setStyleSheet(_qa_style)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(
                lambda checked=False, p=prompt, m=mode_text: self._apply_quick_action(p, m)
            )
            ag_layout.addWidget(btn)
        layout.addWidget(actions_group)

        # ── GenTab directo ───────────────────────────────────────────────────
        gentab_group = QGroupBox("GenTab — Generador de aplicaciones")
        gentab_group.setStyleSheet(group_style)
        gg_layout = QVBoxLayout(gentab_group)
        gg_layout.setSpacing(6)

        gentab_info = QLabel(
            "Genera una aplicación web interactiva desde el contenido de tus pestañas."
        )
        gentab_info.setWordWrap(True)
        gentab_info.setStyleSheet(f"color: {c['text_secondary']}; font-size: 12px;")
        gg_layout.addWidget(gentab_info)

        self._gentab_prompt_input = QTextEdit()
        self._gentab_prompt_input.setPlaceholderText(
            "Describe la aplicación a generar...\n"
            "Ej: «Compara los precios de las pestañas en una tabla ordenable»"
        )
        self._gentab_prompt_input.setMaximumHeight(70)
        self._gentab_prompt_input.setAcceptRichText(False)
        self._gentab_prompt_input.setStyleSheet(
            f"QTextEdit {{ background: {c['input_bg']}; color: {c['text_primary']};"
            f" border: 1px solid {c['input_border']}; border-radius: 8px;"
            f" padding: 6px; font-size: 12px; }}"
            f" QTextEdit:focus {{ border-color: {c['input_focus']}; }}"
        )
        gg_layout.addWidget(self._gentab_prompt_input)

        open_gentab_btn = QPushButton("Abrir panel GenTab")
        open_gentab_btn.setStyleSheet(
            f"QPushButton {{ background: {c['accent']}; color: {c['surface_0']}; border: none;"
            f" border-radius: 8px; padding: 8px 16px; font-size: 13px; font-weight: bold; }}"
            f" QPushButton:hover {{ background: {c['accent_subtle']}; color: {c['accent']}; }}"
        )
        open_gentab_btn.setCursor(Qt.PointingHandCursor)
        open_gentab_btn.clicked.connect(self._open_gentab_panel)
        gg_layout.addWidget(open_gentab_btn)

        layout.addWidget(gentab_group)

        # ── Helio: Panel de sugerencias ────────────────────────
        helio_group = QGroupBox("Sugerencias Helio")
        helio_group.setStyleSheet(group_style)
        hg_layout = QVBoxLayout(helio_group)
        hg_layout.setSpacing(6)

        helio_info = QLabel("Sugerencias inteligentes basadas en tu actividad")
        helio_info.setStyleSheet(f"color: {c['text_secondary']}; font-size: 11px; font-style: italic;")
        hg_layout.addWidget(helio_info)

        self._helio_suggestion_frames = []
        for i in range(3):
            frame = QFrame()
            frame.setStyleSheet(
                f"QFrame {{ background: {c['surface_1']}; border: 1px solid {c['border']};"
                f" border-radius: 8px; padding: 4px; }}"
                f" QFrame:hover {{ background: {c['surface_hover']}; border-color: {c['accent']}; }}"
            )
            frame.setCursor(Qt.PointingHandCursor)
            fl = QHBoxLayout(frame)
            fl.setContentsMargins(8, 6, 8, 6)
            fl.setSpacing(8)
            lbl = QLabel("Cargando sugerencias...")
            lbl.setObjectName(f"helio_sug_label_{i}")
            lbl.setStyleSheet(f"color: {c['text_primary']}; font-size: 12px; background: transparent; border: none;")
            lbl.setWordWrap(True)
            fl.addWidget(lbl, 1)
            action_btn = QPushButton("→")
            action_btn.setFixedSize(24, 24)
            action_btn.setStyleSheet(
                f"QPushButton {{ background: {c['accent_subtle']}; color: {c['accent']};"
                f" border: 1px solid {c['border']}; border-radius: 6px; font-size: 14px; }}"
                f" QPushButton:hover {{ background: {c['accent']}; color: {c['surface_0']}; }}"
            )
            idx = i
            action_btn.clicked.connect(lambda checked=False, n=idx: self._helio_on_suggestion_clicked(n))
            fl.addWidget(action_btn)
            hg_layout.addWidget(frame)
            self._helio_suggestion_frames.append(frame)
        refresh_helio_btn = QPushButton("Actualizar sugerencias")
        refresh_helio_btn.setStyleSheet(
            f"QPushButton {{ background: {c['surface_1']}; color: {c['text_primary']};"
            f" border: 1px solid {c['border']}; border-radius: 8px;"
            f" padding: 5px 12px; font-size: 12px; }}"
            f" QPushButton:hover {{ background: {c['surface_hover']}; }}"
        )
        refresh_helio_btn.setCursor(Qt.PointingHandCursor)
        refresh_helio_btn.clicked.connect(self._helio_refresh_suggestions)
        hg_layout.addWidget(refresh_helio_btn)

        layout.addWidget(helio_group)

        layout.addStretch()

        # Cargar pestañas al crear el tab
        QTimer.singleShot(500, self._refresh_open_tabs_list)
        # Helio: cargar sugerencias iniciales
        QTimer.singleShot(3000, self._helio_refresh_suggestions)
        return widget
    # ── Métodos de Navegación IA ─────────────────────────────────────────────

    def _run_session_analysis(self) -> None:
        """Ejecuta el análisis de sesión con fallback Helio de 3 niveles."""
        main = self.window()
        if not hasattr(main, "tab_manager"):
            self.add_message_to_chat("System", "No se puede acceder al gestor de pestañas.", "error")
            return
        self._refresh_open_tabs_list()

        # Actualizar badge a "analizando"
        self._intent_badge.setText("Analizando...")

        # Helio: usar sistema de 3 niveles
        level = self._helio_detect_intent_level()
        analysis = self._helio_analyze_with_level(level)

        if analysis:
            self._last_session_analysis = analysis
            self._update_session_ui(analysis)

            intent = analysis.get("intent")
            intent_name = intent.value if hasattr(intent, "value") else str(intent)
            conf = int(analysis.get("confidence", 0) * 100)
            tab_count = analysis.get("tab_count", 0)
            domains = ", ".join(analysis.get("domains", [])[:5])
            action = analysis.get("suggested_action", "")
            source = analysis.get("source", f"nivel {level}")

            analysis_summary = (
                f"Analiza mi sesión de navegación actual:\n"
                f"- Intención detectada: {intent_name} (confianza: {conf}%)\n"
                f"- Pestañas abiertas: {tab_count}\n"
                f"- Dominios: {domains or 'varios'}\n"
                f"- Acción sugerida: {action}\n"
                f"- Motor de análisis: {source}\n\n"
                f"Dame un análisis detallado con insights y próximos pasos."
            )

            if hasattr(self, "message_input"):
                self.message_input.setPlainText(analysis_summary)
            if hasattr(self, "assistant_mode"):
                idx = self.assistant_mode.findData("session")
                if idx >= 0:
                    self.assistant_mode.setCurrentIndex(idx)
            if hasattr(self, "tab_widget"):
                self.tab_widget.setCurrentIndex(0)
            return
        # Fallback final: extracción directa
        tabs_context = self._extract_all_open_tabs_context(limit_tabs=6)
        prompt = (
            "Analiza estas pestañas que tengo abiertas y dime:\n"
            "1. ¿Qué estoy investigando/haciendo?\n"
            "2. Insights clave de cada pestaña\n"
            "3. Próximos pasos recomendados\n\n"
            f"{tabs_context}"
        )
        if hasattr(self, "message_input"):
            self.message_input.setPlainText(prompt)
        if hasattr(self, "tab_widget"):
            self.tab_widget.setCurrentIndex(0)
        self._intent_badge.setText("Análisis manual solicitado")
    def _update_session_ui(self, analysis: dict) -> None:
        """Actualiza los widgets del tab Navegación con los datos del análisis."""
        intent = analysis.get("intent")
        confidence = analysis.get("confidence", 0.0)
        action = analysis.get("suggested_action", "")

        _INTENT_LABELS = {
            "research":      "Investigación",
            "shopping":      "Compras",
            "news":          "Noticias",
            "travel":        "Viajes",
            "coding":        "Programación",
            "entertainment": "Entretenimiento",
            "general":       "General",
        }
        # Helio: soportar tanto enums como strings de los diferentes niveles
        intent_key = intent.value if hasattr(intent, "value") else str(intent) if intent else "general"
        label = _INTENT_LABELS.get(intent_key, "General")
        pct = int(confidence * 100)

        self._intent_badge.setText(label)
        self._conf_bar.setValue(pct)
        self._conf_pct_label.setText(f"{pct}%")
        if action:
            self._suggested_action_label.setText(f"{action}")
    def _refresh_open_tabs_list(self) -> None:
        """Actualiza la lista de pestañas abiertas en el tab Navegación."""
        if not hasattr(self, "_open_tabs_list"):
            return
        self._open_tabs_list.clear()
        main = self.window()
        if not hasattr(main, "tab_manager"):
            return
        tabs = main.tab_manager.tabs
        count = 0
        for i in range(tabs.count()):
            widget = tabs.widget(i)
            if widget is None:
                continue
            url = widget.url().toString() if hasattr(widget, "url") else ""
            if not url or url.startswith("about:"):
                continue
            title = tabs.tabText(i) or url
            item = QListWidgetItem(f"  {i+1}. {title[:55]}")
            item.setToolTip(url)
            item.setData(Qt.UserRole, url)
            self._open_tabs_list.addItem(item)
            count += 1
        self._tabs_count_label.setText(f"{count} pestaña{'s' if count != 1 else ''}")
    def _on_tab_item_double_click(self, item: QListWidgetItem) -> None:
        """Al hacer doble clic en una pestaña, activa ese tab en el navegador."""
        url = item.data(Qt.UserRole)
        if not url:
            return
        main = self.window()
        if not hasattr(main, "tab_manager"):
            return
        tabs = main.tab_manager.tabs
        for i in range(tabs.count()):
            w = tabs.widget(i)
            if w and hasattr(w, "url") and w.url().toString() == url:
                tabs.setCurrentIndex(i)
                break
    # Modos del asistente: (id interno, etiqueta visible). La lógica usa el id.
    _ASSISTANT_MODES = [
        ("chat", "Chat"),
        ("summary", "Resumen pestaña"),
        ("multi", "Multi-pestaña"),
        ("session", "Sesión"),
        ("gentab", "GenTab"),
        ("search", "Búsqueda"),
        ("open", "Abrir"),
    ]

    def _set_assistant_mode(self, mode_id: str) -> None:
        if hasattr(self, "assistant_mode"):
            idx = self.assistant_mode.findData(mode_id)
            if idx >= 0:
                self.assistant_mode.setCurrentIndex(idx)
    def _current_assistant_mode(self) -> str:
        if hasattr(self, "assistant_mode"):
            return self.assistant_mode.currentData() or "chat"
        return "chat"
    def _apply_quick_action(self, prompt: str, mode_id: str) -> None:
        """Aplica una acción rápida: pone el prompt en el input y activa el modo."""
        if hasattr(self, "message_input"):
            self.message_input.setPlainText(prompt)
        self._set_assistant_mode(mode_id)
        if hasattr(self, "tab_widget"):
            self.tab_widget.setCurrentIndex(0)
    def _open_gentab_panel(self) -> None:
        """Abre el panel GenTab desde el botón del tab Navegación."""
        prompt = ""
        if hasattr(self, "_gentab_prompt_input"):
            prompt = self._gentab_prompt_input.toPlainText().strip()
        main = self.window()
        if hasattr(main, "gentab_panel") and main.gentab_panel:
            if hasattr(main, "show_advanced_panel"):
                main.show_advanced_panel(main.gentab_panel)
            if prompt and hasattr(main.gentab_panel, "prompt_input"):
                main.gentab_panel.prompt_input.setPlainText(prompt)
        else:
            # Emitir señal para que la MainWindow lo maneje
            self.gentab_requested.emit(prompt)
    def create_settings_tab(self):
        """Tab de configuración del servidor LLM"""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # ── Proveedor ──────────────────────────────────────────────────────────
        prov_group = QGroupBox("Proveedor de IA")
        prov_layout = QVBoxLayout()

        prov_row = QHBoxLayout()
        prov_row.addWidget(QLabel("Proveedor:"))
        self.chat_provider_combo = QComboBox()
        self.chat_provider_combo.addItem("LM Studio / Local", PROVIDER_LOCAL)
        self.chat_provider_combo.addItem("llmapi.ai (cloud gratuito)", PROVIDER_LLMAPI)
        self.chat_provider_combo.addItem("Anthropic (Claude)", PROVIDER_ANTHROPIC)
        self.chat_provider_combo.addItem("HuggingFace (Inference API)", PROVIDER_HUGGINGFACE)
        self.chat_provider_combo.addItem("Ollama (local)", PROVIDER_OLLAMA)
        for pid, spec in OPENAI_COMPAT_PROVIDERS.items():
            self.chat_provider_combo.addItem(spec["label"], pid)
        prov_row.addWidget(self.chat_provider_combo)
        prov_layout.addLayout(prov_row)

        # Local URL
        self.chat_local_widget = QWidget()
        local_layout = QHBoxLayout(self.chat_local_widget)
        local_layout.setContentsMargins(0, 0, 0, 0)
        local_layout.addWidget(QLabel("URL servidor:"))
        self.server_url_input = QLineEdit()
        self.server_url_input.setPlaceholderText("http://localhost:1234")
        if hasattr(self.server_url_input, "setClearButtonEnabled"):
            self.server_url_input.setClearButtonEnabled(True)
        self.server_url_input.textChanged.connect(self.on_server_url_changed)
        local_layout.addWidget(self.server_url_input)
        prov_layout.addWidget(self.chat_local_widget)

        # Cloud (llmapi.ai)
        self.chat_cloud_widget = QWidget()
        cloud_layout = QVBoxLayout(self.chat_cloud_widget)
        cloud_layout.setContentsMargins(0, 0, 0, 0)

        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("API Key:"))
        self.chat_api_key_input = QLineEdit()
        self.chat_api_key_input.setPlaceholderText("lak-...")
        self.chat_api_key_input.setEchoMode(QLineEdit.Password)
        key_row.addWidget(self.chat_api_key_input)
        show_btn = QPushButton()
        self.set_button_icon(show_btn, "eye")
        show_btn.setMaximumWidth(32)
        show_btn.setCheckable(True)
        show_btn.toggled.connect(
            lambda on: self.chat_api_key_input.setEchoMode(
                QLineEdit.Normal if on else QLineEdit.Password
            )
        )
        key_row.addWidget(show_btn)
        cloud_layout.addLayout(key_row)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Modelo:"))
        self.chat_model_combo = QComboBox()
        for m in LLMAPI_FREE_MODELS:
            self.chat_model_combo.addItem(m)
        model_row.addWidget(self.chat_model_combo)
        cloud_layout.addLayout(model_row)

        info_cloud = QLabel(
            'API key gratuita en <a href="https://llmapi.ai" style="color:#4f8ef7;">llmapi.ai</a>'
        )
        info_cloud.setOpenExternalLinks(True)
        info_cloud.setTextFormat(Qt.RichText)
        info_cloud.setStyleSheet("color: #94a3b8; font-size: 11px;")
        cloud_layout.addWidget(info_cloud)
        prov_layout.addWidget(self.chat_cloud_widget)

        # ── Panel Anthropic ──────────────────────────────────────────────────
        self.chat_anthropic_widget = QWidget()
        ant_layout = QVBoxLayout(self.chat_anthropic_widget)
        ant_layout.setContentsMargins(0, 0, 0, 0)
        ant_layout.setSpacing(6)

        # API Key
        ant_key_row = QHBoxLayout()
        ant_key_lbl = QLabel("API Key:")
        ant_key_lbl.setFixedWidth(72)
        ant_key_row.addWidget(ant_key_lbl)
        self.chat_anthropic_key_input = QLineEdit()
        self.chat_anthropic_key_input.setPlaceholderText("sk-ant-api03-...")
        self.chat_anthropic_key_input.setEchoMode(QLineEdit.Password)
        ant_key_row.addWidget(self.chat_anthropic_key_input)
        ant_show_btn = QPushButton()
        self.set_button_icon(ant_show_btn, "eye")
        ant_show_btn.setMaximumWidth(32)
        ant_show_btn.setCheckable(True)
        ant_show_btn.toggled.connect(
            lambda on: self.chat_anthropic_key_input.setEchoMode(
                QLineEdit.Normal if on else QLineEdit.Password
            )
        )
        ant_key_row.addWidget(ant_show_btn)
        ant_layout.addLayout(ant_key_row)

        # Selector de modelo
        ant_model_row = QHBoxLayout()
        ant_model_lbl = QLabel("Modelo:")
        ant_model_lbl.setFixedWidth(72)
        ant_model_row.addWidget(ant_model_lbl)
        self.chat_anthropic_model_combo = QComboBox()
        fill_anthropic_model_combo(self.chat_anthropic_model_combo)
        ant_model_row.addWidget(self.chat_anthropic_model_combo)
        ant_refresh_btn = QPushButton("Actualizar")
        ant_refresh_btn.setToolTip("Cargar los modelos disponibles para tu cuenta de Anthropic")
        ant_refresh_btn.clicked.connect(
            lambda: refresh_anthropic_models(
                self, self.chat_anthropic_key_input.text().strip(), self.chat_anthropic_model_combo
            )
        )
        ant_model_row.addWidget(ant_refresh_btn)
        ant_layout.addLayout(ant_model_row)

        # Descripción del modelo seleccionado
        self.chat_anthropic_model_desc = QLabel("")
        self.chat_anthropic_model_desc.setWordWrap(True)
        self.chat_anthropic_model_desc.setStyleSheet(
            f"color: {self._C['text_secondary']}; font-size: 11px;"
        )
        ant_layout.addWidget(self.chat_anthropic_model_desc)
        self.chat_anthropic_model_combo.currentTextChanged.connect(
            self._update_anthropic_model_desc
        )

        # Link a consola Anthropic
        ant_info = QLabel(
            'Obtén tu API key en '
            '<a href="https://console.anthropic.com/settings/keys" '
            'style="color:#4B9EFF;">console.anthropic.com</a>'
        )
        ant_info.setOpenExternalLinks(True)
        ant_info.setTextFormat(Qt.RichText)
        ant_info.setStyleSheet(f"color: {self._C['text_secondary']}; font-size: 11px;")
        ant_layout.addWidget(ant_info)

        prov_layout.addWidget(self.chat_anthropic_widget)
        # ── fin panel Anthropic ──────────────────────────────────────────────

        # ── Panel HuggingFace ────────────────────────────────────────────────
        self.chat_hf_widget = QWidget()
        hf_layout = QVBoxLayout(self.chat_hf_widget)
        hf_layout.setContentsMargins(0, 0, 0, 0)
        hf_layout.setSpacing(6)

        # API Key
        hf_key_row = QHBoxLayout()
        hf_key_lbl = QLabel("API Key:")
        hf_key_lbl.setFixedWidth(72)
        hf_key_row.addWidget(hf_key_lbl)
        self.chat_hf_key_input = QLineEdit()
        self.chat_hf_key_input.setPlaceholderText("hf_...")
        self.chat_hf_key_input.setEchoMode(QLineEdit.Password)
        hf_key_row.addWidget(self.chat_hf_key_input)
        hf_show_btn = QPushButton()
        self.set_button_icon(hf_show_btn, "eye")
        hf_show_btn.setMaximumWidth(32)
        hf_show_btn.setCheckable(True)
        hf_show_btn.toggled.connect(
            lambda on: self.chat_hf_key_input.setEchoMode(
                QLineEdit.Normal if on else QLineEdit.Password
            )
        )
        hf_key_row.addWidget(hf_show_btn)
        hf_layout.addLayout(hf_key_row)

        # Selector de modelo
        hf_model_row = QHBoxLayout()
        hf_model_lbl = QLabel("Modelo:")
        hf_model_lbl.setFixedWidth(72)
        hf_model_row.addWidget(hf_model_lbl)
        self.chat_hf_model_combo = QComboBox()
        for hf_m in HUGGINGFACE_MODELS:
            self.chat_hf_model_combo.addItem(hf_m)
        self.chat_hf_model_combo.setEditable(True)
        self.chat_hf_model_combo.setInsertPolicy(QComboBox.NoInsert)
        self.chat_hf_model_combo.setPlaceholderText("organización/nombre-del-modelo")
        hf_model_row.addWidget(self.chat_hf_model_combo)
        hf_layout.addLayout(hf_model_row)

        # Descripción del modelo
        self.chat_hf_model_desc = QLabel("")
        self.chat_hf_model_desc.setWordWrap(True)
        self.chat_hf_model_desc.setStyleSheet(
            f"color: {self._C['text_secondary']}; font-size: 11px;"
        )
        hf_layout.addWidget(self.chat_hf_model_desc)
        self.chat_hf_model_combo.currentTextChanged.connect(self._update_hf_model_desc)

        # Enlace a HuggingFace
        hf_info = QLabel(
            'Genera tu token en '
            '<a href="https://huggingface.co/settings/tokens" '
            'style="color:#4B9EFF;">huggingface.co/settings/tokens</a>'
            ' (rol <em>Inference</em>)'
        )
        hf_info.setOpenExternalLinks(True)
        hf_info.setTextFormat(Qt.RichText)
        hf_info.setStyleSheet(f"color: {self._C['text_secondary']}; font-size: 11px;")
        hf_layout.addWidget(hf_info)

        prov_layout.addWidget(self.chat_hf_widget)
        # ── fin panel HuggingFace ────────────────────────────────────────────

        # ── Panel Ollama ─────────────────────────────────────────────────────
        self.chat_ollama_widget = QWidget()
        ol_layout = QVBoxLayout(self.chat_ollama_widget)
        ol_layout.setContentsMargins(0, 0, 0, 0)
        ol_layout.setSpacing(6)

        ol_url_row = QHBoxLayout()
        ol_url_lbl = QLabel("URL:")
        ol_url_lbl.setFixedWidth(72)
        ol_url_row.addWidget(ol_url_lbl)
        self.chat_ollama_url_input = QLineEdit()
        self.chat_ollama_url_input.setPlaceholderText(OLLAMA_DEFAULT_URL)
        ol_url_row.addWidget(self.chat_ollama_url_input)
        ol_layout.addLayout(ol_url_row)

        ol_model_row = QHBoxLayout()
        ol_model_lbl = QLabel("Modelo:")
        ol_model_lbl.setFixedWidth(72)
        ol_model_row.addWidget(ol_model_lbl)
        self.chat_ollama_model_combo = QComboBox()
        self.chat_ollama_model_combo.setEditable(True)
        self.chat_ollama_model_combo.setInsertPolicy(QComboBox.NoInsert)
        self.chat_ollama_model_combo.setPlaceholderText("vacío = primer modelo instalado")
        ol_model_row.addWidget(self.chat_ollama_model_combo)
        ol_refresh_btn = QPushButton("Actualizar")
        ol_refresh_btn.setToolTip("Cargar los modelos instalados en Ollama")
        ol_refresh_btn.clicked.connect(self._refresh_ollama_models)
        ol_model_row.addWidget(ol_refresh_btn)
        ol_layout.addLayout(ol_model_row)

        ol_info = QLabel(
            'Instala Ollama desde <a href="https://ollama.com/download" '
            'style="color:#4B9EFF;">ollama.com</a> y descarga un modelo, '
            'p. ej. <code>ollama pull llama3.2</code>'
        )
        ol_info.setOpenExternalLinks(True)
        ol_info.setTextFormat(Qt.RichText)
        ol_info.setWordWrap(True)
        ol_info.setStyleSheet(f"color: {self._C['text_secondary']}; font-size: 11px;")
        ol_layout.addWidget(ol_info)

        prov_layout.addWidget(self.chat_ollama_widget)
        # ── fin panel Ollama ─────────────────────────────────────────────────

        # ── Paneles cloud OpenAI-compatibles (OpenAI, DeepSeek...) ──────────
        self.chat_compat_fields = {}
        for pid in OPENAI_COMPAT_PROVIDERS:
            fields = build_compat_provider_widget(
                pid, "#4B9EFF", self._C['text_secondary'], self.set_button_icon
            )
            self.chat_compat_fields[pid] = fields
            prov_layout.addWidget(fields.widget)

        # Estado + botones
        conn_row = QHBoxLayout()
        self.test_btn = QPushButton("Probar conexión")
        self.test_btn.clicked.connect(self.test_connection_safe)
        conn_row.addWidget(self.test_btn)
        save_btn = QPushButton("Guardar")
        save_btn.clicked.connect(self.save_server_url)
        conn_row.addWidget(save_btn)
        prov_layout.addLayout(conn_row)

        self.connection_status_label = QLabel("Estado: sin configurar")
        prov_layout.addWidget(self.connection_status_label)

        prov_group.setLayout(prov_layout)
        layout.addWidget(prov_group)

        # ── Avanzado ───────────────────────────────────────────────────────────
        adv_group = QGroupBox("Avanzado")
        adv_layout = QVBoxLayout()

        temp_row = QHBoxLayout()
        temp_row.addWidget(QLabel("Temperatura:"))
        self.temperature_spin = QSpinBox()
        self.temperature_spin.setRange(0, 20)
        self.temperature_spin.setValue(7)
        self.temperature_spin.setSuffix(" /10")
        temp_row.addWidget(self.temperature_spin)
        adv_layout.addLayout(temp_row)

        tokens_row = QHBoxLayout()
        tokens_row.addWidget(QLabel("Máx tokens:"))
        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(100, 8192)
        self.max_tokens_spin.setValue(int(self.llm_config.max_tokens))
        tokens_row.addWidget(self.max_tokens_spin)
        adv_layout.addLayout(tokens_row)

        adv_group.setLayout(adv_layout)
        layout.addWidget(adv_group)

        layout.addStretch()

        # Conectar cambio de proveedor
        self.chat_provider_combo.currentIndexChanged.connect(self._on_chat_provider_changed)

        # Poblar con valores guardados
        self._populate_chat_settings_ui()

        widget.setLayout(layout)
        return widget
    def _populate_chat_settings_ui(self):
        if hasattr(self, "chat_provider_combo"):
            idx = self.chat_provider_combo.findData(self.llm_config.provider)
            self.chat_provider_combo.setCurrentIndex(max(idx, 0))
        if hasattr(self, "server_url_input"):
            self.server_url_input.setText(self.llm_config.local_url or "")
        if hasattr(self, "chat_api_key_input"):
            self.chat_api_key_input.setText(self.llm_config.llmapi_key or "")
        if hasattr(self, "chat_model_combo"):
            mi = self.chat_model_combo.findText(self.llm_config.llmapi_model)
            if mi >= 0:
                self.chat_model_combo.setCurrentIndex(mi)
        # Poblar campos Anthropic
        if hasattr(self, "chat_anthropic_key_input"):
            self.chat_anthropic_key_input.setText(self.llm_config.anthropic_key or "")
        if hasattr(self, "chat_anthropic_model_combo"):
            target = self.llm_config.anthropic_model or ANTHROPIC_DEFAULT_MODEL
            select_anthropic_model(self.chat_anthropic_model_combo, target)
            self._update_anthropic_model_desc(self.chat_anthropic_model_combo.currentText())
        # Poblar campos HuggingFace
        if hasattr(self, "chat_hf_key_input"):
            self.chat_hf_key_input.setText(self.llm_config.huggingface_key or "")
        if hasattr(self, "chat_hf_model_combo"):
            hf_target = self.llm_config.huggingface_model or HUGGINGFACE_DEFAULT_MODEL
            hf_mi = self.chat_hf_model_combo.findText(hf_target)
            if hf_mi >= 0:
                self.chat_hf_model_combo.setCurrentIndex(hf_mi)
            else:
                self.chat_hf_model_combo.setEditText(hf_target)
            self._update_hf_model_desc(self.chat_hf_model_combo.currentText())
        # Poblar campos Ollama
        if hasattr(self, "chat_ollama_url_input"):
            self.chat_ollama_url_input.setText(self.llm_config.ollama_url or OLLAMA_DEFAULT_URL)
        if hasattr(self, "chat_ollama_model_combo"):
            self.chat_ollama_model_combo.setEditText(self.llm_config.ollama_model or "")
        if hasattr(self, "chat_compat_fields"):
            load_compat_fields(self.chat_compat_fields, self.llm_config)
        if hasattr(self, "max_tokens_spin"):
            self.max_tokens_spin.setValue(int(self.llm_config.max_tokens))
        self._on_chat_provider_changed()
    _ANTHROPIC_MODEL_DESCRIPTIONS = ANTHROPIC_MODEL_DESCRIPTIONS

    def _update_anthropic_model_desc(self, model_text: str) -> None:
        """Actualiza la descripción del modelo Anthropic seleccionado."""
        if not hasattr(self, "chat_anthropic_model_desc"):
            return
        desc = self._ANTHROPIC_MODEL_DESCRIPTIONS.get(model_text, "")
        self.chat_anthropic_model_desc.setText(desc)
    _HUGGINGFACE_MODEL_DESCRIPTIONS = {
        "meta-llama/Llama-3.3-70B-Instruct": "Llama 3.3 70B — el más potente de Meta, excelente en razonamiento",
        "meta-llama/Llama-3.1-8B-Instruct": "Llama 3.1 8B — ligero y rápido, ideal para tareas sencillas",
        "meta-llama/Llama-3.2-3B-Instruct": "Llama 3.2 3B — ultra-ligero, respuestas muy rápidas",
        "mistralai/Mistral-7B-Instruct-v0.3": "Mistral 7B — equilibrio rendimiento/velocidad, multilingüe",
        "mistralai/Mixtral-8x7B-Instruct-v0.1": "Mixtral 8x7B — MoE de alto rendimiento, contexto largo",
        "mistralai/Mistral-Small-3.1-24B-Instruct-2503": "Mistral Small 3.1 24B — versión reciente, capacidades avanzadas",
        "Qwen/Qwen2.5-72B-Instruct": "Qwen 2.5 72B — muy potente, destaca en código y matemáticas",
        "Qwen/Qwen2.5-Coder-32B-Instruct": "Qwen 2.5 Coder 32B — especializado en programación",
        "deepseek-ai/DeepSeek-R1": "DeepSeek R1 — razonamiento avanzado tipo o1, respuestas largas",
        "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B": "DeepSeek R1 Distill 32B — R1 destilado, más rápido",
        "google/gemma-2-27b-it": "Gemma 2 27B — modelo de Google, muy capaz en instrucciones",
        "google/gemma-2-9b-it": "Gemma 2 9B — versión ligera de Gemma, rápida y eficiente",
        "microsoft/Phi-4-mini-instruct": "Phi-4 Mini — modelo compacto de Microsoft, sorprendentemente capaz",
    }

    def _update_hf_model_desc(self, model_text: str) -> None:
        """Actualiza la descripción del modelo HuggingFace seleccionado."""
        if not hasattr(self, "chat_hf_model_desc"):
            return
        desc = self._HUGGINGFACE_MODEL_DESCRIPTIONS.get(model_text, "")
        self.chat_hf_model_desc.setText(desc)
    def _on_chat_provider_changed(self):
        if not hasattr(self, "chat_provider_combo"):
            return
        provider = self.chat_provider_combo.currentData()
        if hasattr(self, "chat_local_widget"):
            self.chat_local_widget.setVisible(provider == PROVIDER_LOCAL)
        if hasattr(self, "chat_cloud_widget"):
            self.chat_cloud_widget.setVisible(provider == PROVIDER_LLMAPI)
        if hasattr(self, "chat_anthropic_widget"):
            self.chat_anthropic_widget.setVisible(provider == PROVIDER_ANTHROPIC)
        if hasattr(self, "chat_hf_widget"):
            self.chat_hf_widget.setVisible(provider == PROVIDER_HUGGINGFACE)
        if hasattr(self, "chat_ollama_widget"):
            self.chat_ollama_widget.setVisible(provider == PROVIDER_OLLAMA)
        for pid, fields in getattr(self, "chat_compat_fields", {}).items():
            fields.widget.setVisible(provider == pid)
    def _refresh_ollama_models(self):
        """Rellena el selector con los modelos instalados en Ollama (/api/tags)."""
        cfg = LLMConfig(
            provider=PROVIDER_OLLAMA,
            ollama_url=self.chat_ollama_url_input.text().strip() or OLLAMA_DEFAULT_URL,
        )
        current = self.chat_ollama_model_combo.currentText().strip()
        models = LLMClient(cfg).list_models()
        if not models:
            QMessageBox.warning(
                self, "Ollama",
                f"No se encontraron modelos en {cfg.ollama_url}.\n"
                "Comprueba que Ollama está ejecutándose y que tienes algún modelo "
                "descargado (ollama pull llama3.2).",
            )
            return
        self.chat_ollama_model_combo.clear()
        self.chat_ollama_model_combo.addItems(models)
        self.chat_ollama_model_combo.setEditText(current if current in models else models[0])
    def create_history_tab(self):
        """Tab del historial de conversaciones"""
        widget = QWidget()
        layout = QVBoxLayout()

        # Controls
        controls_layout = QHBoxLayout()

        self.refresh_history_btn = QPushButton("Refresh History")
        self.refresh_history_btn.clicked.connect(self.refresh_history)
        controls_layout.addWidget(self.refresh_history_btn)

        self.clear_history_btn = QPushButton("Clear History")
        self.clear_history_btn.clicked.connect(self.clear_history)
        controls_layout.addWidget(self.clear_history_btn)

        self.export_history_btn = QPushButton("Export History")
        self.export_history_btn.clicked.connect(self.export_history)
        controls_layout.addWidget(self.export_history_btn)

        layout.addLayout(controls_layout)

        # History list
        self.history_list = QListWidget()
        self.history_list.itemDoubleClicked.connect(self.load_conversation)
        layout.addWidget(self.history_list)

        widget.setLayout(layout)
        return widget
    def create_help_tab(self):
        """Tab de ayuda y documentación"""
        widget = QWidget()
        layout = QVBoxLayout()

        help_text = QTextEdit()
        help_text.setReadOnly(True)
        help_text.setHtml("""
        <h2>Chat with IA Panel - Help</h2>

        <h3>Initial Configuration:</h3>
        <ol>
            <li>Download and install <a href="https://lmstudio.ai/">LM Studio</a></li>
            <li>Open LM Studio and download an AI model</li>
            <li>Start the local server in LM Studio</li>
            <li>Configure the server URL in the "Settings" tab</li>
            <li>Test the connection</li>
        </ol>

        <h3>Using the Chat:</h3>
        <ul>
            <li><strong>Send message:</strong> Write in the text area and press "Send"</li>
            <li><strong>Page context:</strong> Check the box to include information about the current page</li>
            <li><strong>Clear chat:</strong> Use the "Clear Chat" button to start a new conversation</li>
        </ul>

        <h3>Advanced Settings:</h3>
        <ul>
            <li><strong>Temperature:</strong> Controls the creativity of responses (0.0 = very conservative, 1.0 = very creative)</li>
            <li><strong>Max tokens:</strong> Limits the length of responses</li>
        </ul>

        <h3>Typical LM Studio URLs:</h3>
        <ul>
            <li><code>http://localhost:1234</code> - Default port</li>
            <li><code>http://localhost:8080</code> - Alternative port</li>
            <li><code>http://127.0.0.1:1234</code> - Local IP</li>
        </ul>

        <h3>Using Ollama:</h3>
        <ul>
            <li>Install <a href="https://ollama.com/download">Ollama</a> and download a model: <code>ollama pull llama3.2</code></li>
            <li>Select "Ollama (local)" as provider in the "Settings" tab</li>
            <li>Default URL: <code>http://localhost:11434</code>. Press "Actualizar" to list installed models</li>
        </ul>

        <h3>Cloud providers (Anthropic, OpenAI, Gemini, DeepSeek, OpenRouter, Groq, Mistral, Grok, Qwen, HuggingFace, llmapi.ai):</h3>
        <ul>
            <li>Select the provider in the "Settings" tab and paste your API key</li>
            <li>Press "Actualizar" to list the models available for your account, then "Probar conexión"</li>
        </ul>

        <h3>Troubleshooting:</h3>
        <ul>
            <li><strong>Connection error:</strong> Ensure LM Studio or Ollama is running</li>
            <li><strong>Timeout:</strong> The model may take a while to load, wait a few seconds</li>
            <li><strong>Empty response:</strong> Try a simpler message</li>
        </ul>
        """)

        layout.addWidget(help_text)
        widget.setLayout(layout)
        return widget
    def on_server_url_changed(self):
        url = self.server_url_input.text().strip()
        self.server_url = url
        self.llm_config.local_url = url
        self.send_btn.setEnabled(bool(url) or self.llm_config.provider != PROVIDER_LOCAL)
    def save_server_url(self):
        """Guarda configuración del proveedor LLM."""
        if hasattr(self, "chat_provider_combo"):
            self.llm_config.provider = self.chat_provider_combo.currentData()
        if hasattr(self, "server_url_input"):
            self.llm_config.local_url = self.server_url_input.text().strip()
            self.server_url = self.llm_config.local_url
        if hasattr(self, "chat_api_key_input"):
            self.llm_config.llmapi_key = self.chat_api_key_input.text().strip()
        if hasattr(self, "chat_model_combo"):
            self.llm_config.llmapi_model = self.chat_model_combo.currentText()
        # Guardar configuración Anthropic
        if hasattr(self, "chat_anthropic_key_input"):
            self.llm_config.anthropic_key = self.chat_anthropic_key_input.text().strip()
        if hasattr(self, "chat_anthropic_model_combo"):
            item = self.chat_anthropic_model_combo.model().item(
                self.chat_anthropic_model_combo.currentIndex()
            )
            if item and item.isEnabled():
                self.llm_config.anthropic_model = self.chat_anthropic_model_combo.currentText()
        # Guardar configuración HuggingFace
        if hasattr(self, "chat_hf_key_input"):
            self.llm_config.huggingface_key = self.chat_hf_key_input.text().strip()
        if hasattr(self, "chat_hf_model_combo"):
            hf_model = self.chat_hf_model_combo.currentText().strip()
            if hf_model:
                self.llm_config.huggingface_model = hf_model
        # Guardar configuración Ollama
        if hasattr(self, "chat_ollama_url_input"):
            self.llm_config.ollama_url = self.chat_ollama_url_input.text().strip() or OLLAMA_DEFAULT_URL
        if hasattr(self, "chat_ollama_model_combo"):
            self.llm_config.ollama_model = self.chat_ollama_model_combo.currentText().strip()
        if hasattr(self, "chat_compat_fields"):
            save_compat_fields(self.chat_compat_fields, self.llm_config)
        if hasattr(self, "max_tokens_spin"):
            self.llm_config.max_tokens = self.max_tokens_spin.value()
        self.llm_config.save("ChatPanel")
        if hasattr(self, "connection_status_label"):
            self.connection_status_label.setText("Guardado")
    def test_connection_safe(self):
        """Prueba la conexión con el proveedor configurado."""
        c = self._C
        self.save_server_url()
        if hasattr(self, "status_label"):
            self.status_label.setText("● Probando...")
            self.status_label.setStyleSheet(
                f"color: {c['accent']}; font-size: 11px; background: transparent;"
            )
        try:
            client = LLMClient(self.llm_config)
            ok, info = client.test()
            if hasattr(self, "status_label"):
                if ok:
                    self.status_label.setText("● Conectado")
                    self.status_label.setStyleSheet(
                        f"color: {c['success']}; font-size: 11px; background: transparent;"
                    )
                else:
                    self.status_label.setText("● Error")
                    self.status_label.setStyleSheet(
                        f"color: {c['error']}; font-size: 11px; background: transparent;"
                    )
            if hasattr(self, "connection_status_label"):
                self.connection_status_label.setText(
                    f"{'✓' if ok else '✗'} {info[:80]}"
                )
            if not ok:
                QMessageBox.warning(self, "Error de conexión", info)
        except Exception as e:
            if hasattr(self, "status_label"):
                self.status_label.setText("● Error")
                self.status_label.setStyleSheet(
                    f"color: {c['error']}; font-size: 11px; background: transparent;"
                )
            QMessageBox.warning(self, "Error", str(e))
    def send_message_safe(self):
        """Send message safely without threads"""
        message = self.message_input.toPlainText().strip()
        if not message:
            QMessageBox.warning(self, "Error", "Please write a message")
            return
        # Get context from the visible display (what user extracted)
        context = ""
        if self.context_checkbox.isChecked():
            context = self.context_display.toPlainText()
            if not context or context.startswith(("Error", "Extracting page content")):
                # No valid context extracted
                self.add_message_to_chat("System", "Warning: Context checkbox is enabled but no page content extracted. Click 'Extract Page Content' first.", "error")
                context = ""
        # Add user message to chat
        self.add_message_to_chat("User", message, "user")

        mode = self._current_assistant_mode()

        # Comandos interactivos del navegador (funcionan incluso sin servidor LLM)
        if mode == "search":
            if self._try_handle_browser_command(f"busca {message}"):
                self.message_input.clear()
                return
        if mode == "open":
            if self._try_handle_browser_command(f"abre {message}"):
                self.message_input.clear()
                return
        if self._try_handle_browser_command(message):
            self.message_input.clear()
            return
        if self.llm_config.provider == PROVIDER_LOCAL and not self.llm_config.local_url:
            QMessageBox.warning(self, "Error", "Configura la URL del servidor en la pestaña Settings")
            return
        if self.llm_config.provider == PROVIDER_LLMAPI and not self.llm_config.llmapi_key:
            QMessageBox.warning(self, "Error", "Introduce tu API key de llmapi.ai en la pestaña Settings")
            return
        if self.llm_config.provider == PROVIDER_ANTHROPIC and not self.llm_config.anthropic_key:
            QMessageBox.warning(self, "Error", "Introduce tu API key de Anthropic en la pestaña Settings (sk-ant-...)")
            return
        if self.llm_config.provider == PROVIDER_HUGGINGFACE and not self.llm_config.huggingface_key:
            QMessageBox.warning(self, "Error", "Introduce tu token de HuggingFace en la pestaña Settings (hf_...)")
            return
        if (self.llm_config.provider in OPENAI_COMPAT_PROVIDERS
                and not self.llm_config.compat_key(self.llm_config.provider)):
            label = OPENAI_COMPAT_PROVIDERS[self.llm_config.provider]["label"]
            QMessageBox.warning(self, "Error", f"Introduce tu API key de {label} en la pestaña Settings")
            return
        # Clear input
        self.message_input.clear()

        # Disable send button while processing
        self.send_btn.setEnabled(False)
        self.send_btn.setText("Processing...")
        self._start_activity("Procesando...")

        try:
            # Construir prompt según modo
            if mode == "summary":  # resumen pestaña actual
                if not context:
                    self.extract_page_content_now()
                    context = self.context_display.toPlainText()
                user_content = (
                    "Resume de forma clara y estructurada el siguiente contenido de la pestaña actual. "
                    "Incluye puntos clave, hallazgos y próximos pasos.\n\n"
                    f"{context}\n\nSolicitud del usuario: {message}"
                )
            elif mode == "multi":  # resumen multi-pestaña
                all_tabs_context = self._extract_all_open_tabs_context(limit_tabs=8)
                user_content = (
                    "Resume y compara el contenido de TODAS estas pestañas abiertas. "
                    "Devuelve: resumen ejecutivo, diferencias clave y recomendaciones accionables.\n\n"
                    f"{all_tabs_context}\n\nSolicitud del usuario: {message}"
                )
                self.add_message_to_chat("System", "Contexto multi-pestaña extraído.", "assistant")
            elif mode == "session":  # analizar sesión
                all_tabs_context = self._extract_all_open_tabs_context(limit_tabs=10)
                intent_info = ""
                if self._last_session_analysis:
                    intent = self._last_session_analysis.get("intent")
                    conf = int(self._last_session_analysis.get("confidence", 0) * 100)
                    intent_name = intent.value if hasattr(intent, "value") else str(intent) if intent else "general"
                    intent_info = f"\nIntención detectada automáticamente: {intent_name} ({conf}% confianza)\n"
                user_content = (
                    f"Analiza la sesión de navegación del usuario.{intent_info}\n"
                    f"Pestañas abiertas:\n{all_tabs_context}\n\n"
                    f"Solicitud: {message}"
                )
                self.add_message_to_chat("System", "Contexto de sesión capturado para análisis.", "assistant")
            elif mode == "gentab":  # Crear GenTab
                # Despachar al panel GenTab en vez de al chat
                self._create_gentab_from_chat(message)
                self.message_input.clear()
                self.send_btn.setEnabled(True)
                self.send_btn.setText("Enviar")
                self._stop_activity()
                return
            else:
                if context:
                    user_content = f"""Estoy viendo una página web. Contenido:\n\n{context}\n\n---\n\nBasándote en este contenido, {message}"""
                    self.add_message_to_chat("System", f"Contexto enviado ({len(context)} chars)", "assistant")
                else:
                    user_content = message
            # Seleccionar prompt de sistema según modo
            system_prompt = SYSTEM_PROMPT_BROWSER
            if mode == "summary" or mode == "multi":
                system_prompt = (
                    "You are an expert assistant that creates high-quality summaries in Spanish. "
                    "Be clear, structured and practical. Use headings and bullet points."
                )
            elif mode == "session":
                system_prompt = SYSTEM_PROMPT_NAV_ANALYST
            # Conversación persistente: incluir últimos turnos
            history_window = self.session_messages[-10:] if self.session_messages else []
            messages = [{"role": "system", "content": system_prompt}] + history_window + [
                {"role": "user", "content": user_content}
            ]

            temperature = getattr(self.llm_config, "temperature", 0.7)
            # Límite razonable: evita respuestas interminables y timeouts
            max_tokens = max(1024, min(8192, getattr(self.llm_config, "max_tokens", 4096)))

            # Guardar el mensaje del usuario en historial antes de lanzar el worker
            self.session_messages.append({"role": "user", "content": user_content})

            # Lanzar worker asíncrono para no bloquear el UI
            self._launch_chat_worker(messages, message, max_tokens, temperature)
            return  # el resto lo gestionan los slots del worker
        except Exception as e:
            _chat_log.critical("Error preparando mensaje: %s", e, exc_info=True)
            self.add_message_to_chat("System", f"Error al preparar mensaje: {e}", "error")
            self.send_btn.setEnabled(True)
            self.send_btn.setText("Enviar")
            self._stop_activity()
    # ── Worker asíncrono para chat ────────────────────────────────────────────

    def _launch_chat_worker(self, messages: list, original_message: str,
                            max_tokens: int, temperature: float):
        """Lanza ChatWorker en segundo plano. NO bloquea el hilo principal."""
        # Cancelar worker anterior si sigue activo
        if self._chat_worker and self._chat_worker.isRunning():
            self._chat_worker.cancel()
            self._chat_worker.wait(2000)
        self._streaming_placeholder_added = False
        self._streaming_original_message = original_message

        self._chat_worker = ChatWorker(
            self.llm_config, messages, max_tokens, temperature
        )
        self._chat_worker.chunk_received.connect(self._on_chat_chunk)
        self._chat_worker.finished.connect(self._on_chat_finished)
        self._chat_worker.error.connect(self._on_chat_error)

        # Botón cambia a "Cancelar"
        self.send_btn.setEnabled(True)
        self.send_btn.setText("Cancelar")
        try:
            self.send_btn.clicked.disconnect()
        except Exception:
            pass
        self.send_btn.clicked.connect(self._cancel_chat_worker)

        self._chat_worker.start()
    def _cancel_chat_worker(self):
        """Cancela el worker en curso y restaura el botón de envío."""
        if self._chat_worker and self._chat_worker.isRunning():
            self._chat_worker.cancel()
            self._chat_worker.wait(2000)
        self.add_message_to_chat("System", "Generación cancelada.", "assistant")
        self._restore_send_button()
        self._stop_activity()
    def _on_chat_chunk(self, chunk: str):
        """Añade fragmento de streaming al último mensaje IA."""
        if not self._streaming_placeholder_added:
            self.add_message_to_chat("IA", "", "assistant")
            self._streaming_placeholder_added = True
            self._streaming_text = ""
        self._streaming_text = getattr(self, "_streaming_text", "") + chunk

        # Actualizar el QLabel del último mensaje de IA (objectName "bubbleMsg")
        last_labels = self.chat_messages_widget.findChildren(
            QLabel, "bubbleMsg"
        )
        if last_labels:
            last_labels[-1].setText(self._streaming_text)
            last_labels[-1].adjustSize()
        # Auto-scroll
        QTimer.singleShot(0, lambda: self.chat_scroll.verticalScrollBar().setValue(
            self.chat_scroll.verticalScrollBar().maximum()
        ))
    def _on_chat_finished(self, full_content: str):
        """Llamado cuando el worker termina correctamente."""
        if not self._streaming_placeholder_added:
            # Sin streaming: mostrar de una vez
            self.add_message_to_chat("IA", full_content, "assistant")
        else:
            # Streaming terminado: aplicar formato HTML al texto acumulado
            try:
                last_labels = self.chat_messages_widget.findChildren(
                    QLabel, "bubbleMsg"
                )
                if last_labels:
                    formatted = self.format_ai_response(full_content)
                    last_labels[-1].setTextFormat(Qt.RichText)
                    last_labels[-1].setText(formatted)
                    last_labels[-1].adjustSize()
                    self.chat_messages_widget.updateGeometry()
                    QTimer.singleShot(10, lambda: self.chat_scroll.verticalScrollBar().setValue(
                        self.chat_scroll.verticalScrollBar().maximum()
                    ))
            except Exception:
                pass
        # Registrar en historial
        self.session_messages.append({"role": "assistant", "content": full_content})
        original = getattr(self, "_streaming_original_message", "")
        self.save_to_history(original, full_content)
        self._restore_send_button()
        self._stop_activity()
    def _on_chat_error(self, error_msg: str):
        """Llamado cuando el worker devuelve un error."""
        self.add_message_to_chat("System", f"{error_msg}", "error")
        self._restore_send_button()
        self._stop_activity()
    def _restore_send_button(self):
        """Restaura el botón de envío a su estado normal."""
        try:
            self.send_btn.clicked.disconnect()
        except Exception:
            pass
        self.send_btn.clicked.connect(self.send_message_safe)
        self.send_btn.setEnabled(True)
        self.send_btn.setText("Enviar")
    def _try_handle_browser_command(self, message):
        """
        Ejecuta acciones directas del navegador desde lenguaje natural:
        - "busca ...": abre búsqueda en nueva pestaña
        - "abre ...": abre URL(s)/dominios o una búsqueda si no hay URL
        """
        text = (message or "").strip()
        lower = text.lower().strip()

        # Normalizar acentos para detectar comandos robustamente (busca/busqueda/abrir/etc.)
        normalized = (
            lower.replace("á", "a")
                 .replace("é", "e")
                 .replace("í", "i")
                 .replace("ó", "o")
                 .replace("ú", "u")
        )

        # Buscar en la web (acepta frases como "por favor buscame X")
        search_match = re.search(
            r"\b(?:busca(?:me|r)?|search|find)\b\s+(.+)$",
            normalized,
            flags=re.IGNORECASE
        )
        if search_match:
            start_idx = search_match.start(1)
            query = text[start_idx:].strip(" .,:;!?")
            if not query:
                self.add_message_to_chat("System", "Escribe qué quieres buscar. Ejemplo: \"busca vuelos baratos a Tokio\"", "error")
                return True
            opened_url = self._open_best_result_from_query(query)
            if opened_url:
                self.add_message_to_chat("IA", f"He abierto el mejor resultado web para: **{query}**\n\n[{opened_url}]({opened_url})", "assistant")
            else:
                search_url = self._build_search_url(query)
                self._open_url_in_browser(search_url)
                self.add_message_to_chat("IA", f"No pude resolver resultado directo. Abrí la búsqueda para: **{query}**\n\n[{search_url}]({search_url})", "assistant")
            return True
        # Abrir web(s) (acepta "abre", "abrir", "open", incluso dentro de frase)
        open_match = re.search(
            r"\b(?:abre|abrir|open)\b\s+(.+)$",
            normalized,
            flags=re.IGNORECASE
        )
        if open_match:
            start_idx = open_match.start(1)
            target = text[start_idx:].strip(" .,:;!?")
            if not target:
                self.add_message_to_chat("System", "Indica qué quieres abrir. Ejemplo: \"abre github.com\"", "error")
                return True
            links = self._extract_urls_from_message(target)
            urls = [u[0] for u in links]

            # Si no hay URL explícita, intentar detectar dominios sueltos
            if not urls:
                domains = re.findall(r'\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b', target)
                for d in domains:
                    urls.append(f"https://{d}")
            # Si sigue sin haber URLs, abrir una búsqueda con el texto objetivo
            if not urls:
                opened_url = self._open_best_result_from_query(target)
                if opened_url:
                    self.add_message_to_chat("IA", f"No detecté URL exacta, abrí el mejor resultado para: **{target}**\n\n[{opened_url}]({opened_url})", "assistant")
                else:
                    search_url = self._build_search_url(target)
                    self._open_url_in_browser(search_url)
                    self.add_message_to_chat("IA", f"No detecté una URL exacta, así que abrí una búsqueda para: **{target}**\n\n[{search_url}]({search_url})", "assistant")
                return True
            self._open_urls_in_browser(urls)
            self.add_message_to_chat("IA", f"He abierto {len(urls)} pestaña(s) en el navegador.", "assistant")
            return True
        return False
    def _create_gentab_from_chat(self, prompt: str) -> None:
        """Abre el panel GenTab con el prompt enriquecido con historial del chat."""
        # Helio Mejora 3: enriquecer prompt con historial de conversación
        enriched_prompt = self._helio_build_gentab_context(prompt)

        self.add_message_to_chat(
            "System",
            f"Abriendo GenTab con el prompt: «{prompt[:80]}{'...' if len(prompt) > 80 else ''}»",
            "assistant",
        )
        main = self.window()
        if hasattr(main, "gentab_panel") and main.gentab_panel:
            if hasattr(main, "show_advanced_panel"):
                main.show_advanced_panel(main.gentab_panel)
            if enriched_prompt and hasattr(main.gentab_panel, "prompt_input"):
                main.gentab_panel.prompt_input.setPlainText(enriched_prompt)
        else:
            self.gentab_requested.emit(enriched_prompt)
    def _build_search_url(self, query):
        """Construye URL de búsqueda usando el motor predeterminado si existe."""
        q = quote_plus(query)
        main = self.window()
        try:
            if hasattr(main, 'search_engine_manager') and main.search_engine_manager:
                default_engine = main.search_engine_manager.get_default_engine()
                engine_id = getattr(default_engine, "id", "duckduckgo")
                if engine_id == "google":
                    return f"https://www.google.com/search?q={q}"
                if engine_id == "bing":
                    return f"https://www.bing.com/search?q={q}"
                return f"https://duckduckgo.com/?q={q}"
        except Exception:
            pass
        return f"https://duckduckgo.com/?q={q}"
    def _get_search_engine_name(self):
        """Obtiene nombre legible del buscador activo."""
        main = self.window()
        try:
            if hasattr(main, 'search_engine_manager') and main.search_engine_manager:
                default_engine = main.search_engine_manager.get_default_engine()
                engine_id = getattr(default_engine, "id", "duckduckgo")
                if engine_id == "google":
                    return "Google"
                if engine_id == "bing":
                    return "Bing"
                return "DuckDuckGo"
        except Exception:
            pass
        return "DuckDuckGo"
    def _extract_all_open_tabs_context(self, limit_tabs=8):
        """Extrae contexto de múltiples pestañas abiertas de forma síncrona (con timeout por pestaña)."""
        import logging as _logging
        _log = _logging.getLogger(__name__)

        main = self.window()
        if not hasattr(main, 'tab_manager') or not main.tab_manager:
            _log.warning("_extract_all_open_tabs_context: tab_manager no disponible")
            return "No se pudo acceder a las pestañas."
        contexts = []
        tabs = main.tab_manager.tabs
        total = min(tabs.count(), limit_tabs)
        _log.debug("Extrayendo contexto de %d/%d pestañas", total, tabs.count())

        for i in range(total):
            browser = tabs.widget(i)
            if not browser or not hasattr(browser, "page"):
                _log.debug("Pestaña %d: sin widget o sin page, omitida", i)
                continue
            try:
                url = browser.url().toString()
            except Exception as e:
                _log.warning("Pestaña %d: error obteniendo URL: %s", i, e)
                continue
            if not url or url.startswith("about:"):
                continue
            holder = {"html": None}
            loop = QEventLoop()

            def on_html(html_content, l=loop, h=holder):
                h["html"] = html_content
                if l.isRunning():
                    l.quit()
            _log.debug("Pestaña %d (%s): solicitando HTML…", i, url[:60])
            QTimer.singleShot(3000, loop.quit)
            try:
                browser.page().toHtml(on_html)
                loop.exec()
            except Exception as e:
                _log.error("Pestaña %d: error en toHtml/loop.exec: %s", i, e, exc_info=True)
                continue
            html_content = holder.get("html") or ""
            if not html_content:
                _log.warning("Pestaña %d (%s): HTML vacío tras timeout", i, url[:60])
                continue
            try:
                title = browser.page().title() or f"Tab {i+1}"
                extracted = self._simple_extract_text(html_content, url, title)
                contexts.append(f"=== TAB {i+1} ===\n{extracted[:2500]}")
                _log.debug("Pestaña %d: extraídos %d chars", i, len(extracted))
            except Exception as e:
                _log.error("Pestaña %d: error extrayendo texto: %s", i, e, exc_info=True)
        if not contexts:
            _log.warning("No se pudo extraer contexto de ninguna pestaña")
            return "No se pudo extraer contenido de pestañas abiertas."
        _log.info("Contexto multi-pestaña extraído: %d pestañas", len(contexts))
        return "\n\n".join(contexts)
    def _start_activity(self, base_text="Procesando..."):
        """Inicia animación suave en la etiqueta de estado."""
        c = self._C
        self._activity_idx = 0
        if not self.activity_timer:
            self.activity_timer = QTimer(self)
            self.activity_timer.timeout.connect(lambda: self._tick_activity(base_text))
        if hasattr(self, "status_label"):
            self.status_label.setStyleSheet(
                f"color: {c['warning'] if 'warning' in c else '#D29922'}; "
                "font-size: 11px; background: transparent;"
            )
        self.activity_timer.start(200)
    def _tick_activity(self, base_text):
        frame = self._activity_frames[self._activity_idx % len(self._activity_frames)]
        self._activity_idx += 1
        if hasattr(self, "status_label"):
            self.status_label.setText(f"{frame} {base_text}")
    def _stop_activity(self):
        """Detiene animación de actividad y actualiza indicador."""
        c = self._C
        if self.activity_timer and self.activity_timer.isActive():
            self.activity_timer.stop()
        if hasattr(self, "status_label"):
            if self.server_url:
                self.status_label.setText("● Conectado")
                self.status_label.setStyleSheet(
                    f"color: {c['success']}; font-size: 11px; background: transparent;"
                )
            else:
                self.status_label.setText("● Desconectado")
                self.status_label.setStyleSheet(
                    f"color: {c['error']}; font-size: 11px; background: transparent;"
                )
    def _get_search_engine_id(self):
        """Obtiene id interno del buscador activo."""
        main = self.window()
        try:
            if hasattr(main, 'search_engine_manager') and main.search_engine_manager:
                default_engine = main.search_engine_manager.get_default_engine()
                return getattr(default_engine, "id", "duckduckgo")
        except Exception:
            pass
        return "duckduckgo"
    def _open_best_result_from_query(self, query):
        """
        Resuelve una consulta al primer resultado web y lo abre automáticamente.
        Devuelve la URL abierta o None.
        """
        direct_url = self._resolve_first_result_url(query)
        if direct_url:
            self._open_url_in_browser(direct_url)
            return direct_url
        return None
    def _resolve_first_result_url(self, query):
        """
        Intenta resolver la consulta a la primera URL real del buscador seleccionado.
        Fallback: None.
        """
        search_url = self._build_search_url(query)
        engine_id = self._get_search_engine_id()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            )
        }

        try:
            resp = requests.get(search_url, headers=headers, timeout=10)
            if resp.status_code != 200 or not resp.text:
                return None
            html = resp.text

            # Bing parser
            if engine_id == "bing":
                m = re.search(r'<li class="b_algo".*?<h2><a href="(https?://[^"]+)"', html, re.DOTALL)
                if m:
                    return m.group(1)
            # Google parser (frágil por cambios, pero útil como intento)
            if engine_id == "google":
                m = re.search(r'/url\\?q=(https?[^&"]+)&', html)
                if m:
                    return unquote(m.group(1))
            # DuckDuckGo parser
            m = re.search(r'class="result__a"[^>]*href="([^"]+)"', html)
            if m:
                href = m.group(1)
                # Puede venir redirect /l/?uddg=...
                if "duckduckgo.com/l/?" in href or href.startswith("/l/?"):
                    parsed = urlparse(href if href.startswith("http") else f"https://duckduckgo.com{href}")
                    uddg = parse_qs(parsed.query).get("uddg", [])
                    if uddg:
                        return unquote(uddg[0])
                if href.startswith("http"):
                    return href
        except Exception:
            return None
        return None
    def format_ai_response(self, text):
        """
        Formats text with simple lists/headers to readable HTML.
        Adjusted for dark mode: subtle backgrounds and borders.
        """
        if not text:
            return text
        # Convert text to HTML with appropriate formatting
        formatted_text = text

        # Split preserving paragraph breaks (double newlines)
        lines = formatted_text.split('\n')
        formatted_lines = []

        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                # Línea vacía = separación de párrafo
                formatted_lines.append('<div style="margin: 8px 0;"></div>')
                continue
            # Detect main headings (lines ending with :)
            if line.endswith(':') and len(line) < 100:
                formatted_lines.append(f'<h3 style="margin: 15px 0 10px 0; font-size: 16px; font-weight: bold;">{line}</h3>')
                continue
            # Detect secondary headings (lines starting with **)
            if line.startswith('**') and line.endswith('**'):
                title = line[2:-2]  # Remove **
                formatted_lines.append(f'<h4 style="margin: 12px 0 8px 0; font-size: 14px; font-weight: bold;">{title}</h4>')
                continue
            # Detect numbered lists (lines starting with number.)
            if line and line[0].isdigit() and '. ' in line[:5]:
                parts = line.split('. ', 1)
                if len(parts) == 2:
                    number = parts[0]
                    content = parts[1]
                    formatted_lines.append(f'<div style="margin: 5px 0; padding-left: 20px;"><strong>{number}.</strong> {content}</div>')
                    continue
            # Detect list items with *
            if line.startswith('* ') or line.startswith('- '):
                content = line[2:] if line.startswith('* ') else line[2:]
                formatted_lines.append(f'<div style="margin: 3px 0; padding-left: 20px;">• {content}</div>')
                continue
            # Detect list items with +
            if line.startswith('+ '):
                content = line[2:]
                formatted_lines.append(f'<div style="margin: 3px 0; padding-left: 20px;">• {content}</div>')
                continue
            # Detect bold text (**text**)
            if '**' in line:
                # Replace **text** with <strong>text</strong>
                import re
                line = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', line)
            # Detect italic text (*text*)
            if '*' in line and '**' not in line:
                # Replace *text* with <em>text</em> (only if not **)
                import re
                line = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', line)
            # Normal line
            if line:
                formatted_lines.append(f'<div style="margin: 5px 0; line-height: 1.4;">{line}</div>')
        # Join all formatted lines
        formatted_text = '\n'.join(formatted_lines)

        # No inline styles - use current theme QSS
        formatted_text = f"""
        <div style="
            font-family: 'Segoe UI', Arial, sans-serif;
            line-height: 1.55;
            padding: 12px 14px;
            border-radius: 10px;
            margin: 10px 0;
        ">
            {formatted_text}
        </div>
        """

        return formatted_text
    def add_message_to_chat(self, sender, message, message_type):
        """
        Añade un mensaje al chat — estilo documento (no burbujas).

        Usuario: borde izquierdo accent, fondo sutil.
        IA: sin fondo, solo texto.
        Error/Sistema: borde izquierdo rojo, fondo sutil.
        """
        import html as _html

        c = self._C
        timestamp = datetime.now().strftime("%H:%M")

        # Contenedor del mensaje
        msg_widget = QWidget()
        msg_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)

        if message_type == "user":
            msg_widget.setObjectName("userBubble")
            margin_left = 16
        elif message_type == "assistant":
            msg_widget.setObjectName("assistantBubble")
            margin_left = 0
        else:
            msg_widget.setObjectName("errorBubble")
            margin_left = 0
        msg_layout = QVBoxLayout(msg_widget)
        msg_layout.setSpacing(2)

        if message_type == "user":
            msg_layout.setContentsMargins(12, 8, 10, 8)
        else:
            msg_layout.setContentsMargins(12, 6, 10, 6)
        # Fila meta: remitente + hora
        meta_row = QHBoxLayout()
        meta_row.setSpacing(6)

        sender_map = {"user": "Tú", "assistant": sender, "error": "Sistema"}
        sender_text = sender_map.get(message_type, sender)

        meta_lbl = QLabel(f"{sender_text}")
        meta_lbl.setObjectName("bubbleTitle")
        meta_lbl.setStyleSheet(
            f"font-size: 11px; font-weight: 600; "
            f"color: {c['accent'] if message_type == 'user' else c['text_muted']}; "
            "background: transparent;"
        )
        meta_row.addWidget(meta_lbl)

        time_lbl = QLabel(timestamp)
        time_lbl.setStyleSheet(f"font-size: 10px; color: {c['text_muted']}; background: transparent;")
        meta_row.addWidget(time_lbl)
        meta_row.addStretch()
        msg_layout.addLayout(meta_row)

        # Contenido del mensaje
        if message_type == "assistant" and sender == "IA":
            content_html = self.format_ai_response(message)
            msg_lbl = QLabel(content_html)
            msg_lbl.setTextFormat(Qt.RichText)
        else:
            msg_lbl = QLabel(_html.escape(message) if message_type != "assistant" else message)
            msg_lbl.setTextFormat(Qt.PlainText if message_type != "assistant" else Qt.RichText)
        msg_lbl.setObjectName("bubbleMsg")
        msg_lbl.setWordWrap(True)
        msg_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        msg_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        msg_lbl.setOpenExternalLinks(True)
        msg_layout.addWidget(msg_lbl)

        # Tarjetas de recomendación solo para IA real
        if message_type == "assistant" and sender == "IA":
            search_links = self._extract_search_links_from_message(message)
            if search_links:
                self._add_recommendation_cards(msg_layout, search_links)
        # Añadir a la lista con margen izquierdo para mensajes de usuario
        if margin_left:
            row = QHBoxLayout()
            row.setContentsMargins(margin_left, 0, 0, 0)
            row.addWidget(msg_widget)
            row_widget = QWidget()
            row_widget.setLayout(row)
            row_widget.setStyleSheet("background: transparent;")
            self.chat_messages_layout.addWidget(row_widget)
        else:
            self.chat_messages_layout.addWidget(msg_widget)
        # Forzar actualización de layout
        self.chat_messages_widget.updateGeometry()
        self.chat_scroll.updateGeometry()

        # Auto-scroll al final
        QTimer.singleShot(10, lambda: self.chat_scroll.verticalScrollBar().setValue(
            self.chat_scroll.verticalScrollBar().maximum()
        ))
    def _extract_urls_from_message(self, text):
        """Extrae URLs de la respuesta de la IA: markdown [texto](url) y URLs planas."""
        if not text:
            return []
        urls = []
        # Enlaces markdown [texto](url)
        for m in re.finditer(r'\[([^\]]*)\]\((https?://[^\)\s]+)\)', text):
            url = m.group(2).rstrip('.,;:!?)')
            title = (m.group(1).strip() or None)
            if url and url not in [u[0] for u in urls]:
                urls.append((url, title))
        # URLs planas no capturadas ya
        for m in re.finditer(r'https?://[^\s\)\]\>\"]+', text):
            url = m.group(0).rstrip('.,;:!?)')
            if not any(u[0] == url for u in urls):
                urls.append((url, None))
        return urls[:10]  # Máximo 10 para no saturar la UI
    def _extract_search_links_from_message(self, text):
        """
        Convierte recomendaciones de la IA en enlaces de búsqueda robustos.
        Devuelve lista de tuplas: (search_url, label)
        """
        raw_links = self._extract_urls_from_message(text)
        search_links = []
        seen = set()

        for url, title in raw_links:
            query = self._build_search_query_from_recommendation(url, title)
            if not query:
                continue
            search_url = self._build_search_url(query)
            if search_url in seen:
                continue
            seen.add(search_url)
            label = title or query
            search_links.append((search_url, label))
        # Fallback: sólo extraer bullets que parezcan nombres de sitios/herramientas,
        # NUNCA cabeceras markdown, frases largas de análisis ni mensajes del sistema.
        if not search_links and text:
            for line in text.splitlines():
                stripped = line.strip()
                # Ignorar cabeceras markdown (# ## ###)
                if stripped.startswith("#"):
                    continue
                # Ignorar líneas que son claramente frases normales de análisis
                # Ignorar líneas demasiado cortas o demasiado largas
                clean = stripped.strip(" -•*\t")
                if len(clean) < 8 or len(clean) > 60:
                    continue
                # Solo aceptar si parece un nombre de herramienta/sitio:
                # debe contener al menos un punto o ser una palabra compuesta
                # Requisito mínimo: no ser una frase con verbo
                words = clean.split()
                if len(words) > 6:
                    continue  # Frases largas no son recomendaciones de sitios
                query = clean
                search_url = self._build_search_url(query)
                if search_url in seen:
                    continue
                seen.add(search_url)
                search_links.append((search_url, query))
                if len(search_links) >= 5:
                    break
        return search_links[:10]
    def _build_search_query_from_recommendation(self, url, title=None):
        """Construye una query estable para buscador desde URL/título sugerido por IA."""
        if title and title.strip():
            return title.strip()
        clean = re.sub(r'^https?://', '', (url or '').strip(), flags=re.IGNORECASE)
        clean = clean.split('#')[0].split('?')[0]
        parts = [p for p in clean.split('/') if p]
        if not parts:
            return ""
        domain = parts[0].replace("www.", "")
        path = "".join(parts[1:3]) if len(parts) > 1 else ""
        path = path.replace('-', ' ').replace('_', ' ')
        query = f"{domain} {path}".strip()
        return query[:120]
    def _add_recommendation_cards(self, parent_layout, urls):
        """Añade tarjetas para abrir resultados de búsqueda en pestañas."""
        rec_frame = QFrame()
        rec_frame.setObjectName("recommendationCards")
        rec_layout = QVBoxLayout(rec_frame)
        rec_layout.setContentsMargins(8, 10, 8, 4)
        rec_layout.setSpacing(8)

        rec_label = QLabel(f"<b>Abrir búsqueda en {self._get_search_engine_name()}</b>")
        rec_label.setStyleSheet("color: #1a73e8; font-size: 12px;")
        rec_label.setTextFormat(Qt.RichText)
        rec_layout.addWidget(rec_label)

        # Fila de botones por enlace
        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(6)
        for url, title in urls:
            label = (title or url)
            if len(label) > 45:
                label = label[:42] + "..."
            btn = QPushButton(f"{label}")
            btn.setToolTip(url)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background: rgba(26, 115, 232, 0.12);
                    color: #1a73e8; border: 1px solid rgba(26, 115, 232, 0.4);
                    border-radius: 6px; padding: 6px 12px; font-size: 12px;
                    text-align: left; max-width: 220px;
                }
                QPushButton:hover {
                    background: rgba(26, 115, 232, 0.25);
                    border-color: #1a73e8;
                }
            """)
            btn.clicked.connect(lambda checked, u=url: self._open_url_in_browser(u))
            buttons_row.addWidget(btn)
        buttons_row.addStretch(1)
        rec_layout.addLayout(buttons_row)

        if len(urls) > 1:
            open_all_btn = QPushButton(f"Abrir todas en {self._get_search_engine_name()}")
            open_all_btn.setCursor(Qt.PointingHandCursor)
            open_all_btn.setStyleSheet("""
                QPushButton {
                    background: #1a73e8; color: white; border: none;
                    border-radius: 6px; padding: 8px 14px; font-size: 12px; font-weight: bold;
                }
                QPushButton:hover { background: #1557b0; }
            """)
            open_all_btn.clicked.connect(lambda: self._open_urls_in_browser([u[0] for u in urls]))
            rec_layout.addWidget(open_all_btn)
        rec_frame.setStyleSheet("""
            QFrame#recommendationCards {
                background: rgba(26, 115, 232, 0.06);
                border: 1px solid rgba(26, 115, 232, 0.2);
                border-radius: 8px;
            }
        """)
        parent_layout.addWidget(rec_frame)
    def _auto_open_recommendations(self, search_links, max_auto_open=3):
        """
        Abre automáticamente resultados web reales desde recomendaciones de búsqueda.
        search_links: [(search_url, label), ...]
        """
        opened = 0
        for search_url, label in search_links:
            if opened >= max_auto_open:
                break
            query = (label or "").strip()
            if not query:
                # fallback: usar q de la URL
                try:
                    parsed = urlparse(search_url)
                    q = parse_qs(parsed.query).get("q", [""])[0]
                    query = unquote(q)
                except Exception:
                    query = ""
            if not query:
                continue
            direct = self._resolve_first_result_url(query)
            if direct:
                self._open_url_in_browser(direct)
                opened += 1
    def _open_url_in_browser(self, url):
        """Abre una URL en una nueva pestaña del navegador."""
        main = self.window()
        if hasattr(main, 'tab_manager') and main.tab_manager:
            main.tab_manager.add_new_tab(url)
    def _open_urls_in_browser(self, urls):
        """Abre varias URLs en pestañas nuevas."""
        for url in urls:
            self._open_url_in_browser(url)
    def clear_chat(self):
        """Clear chat area"""
        for i in reversed(range(self.chat_messages_layout.count())):
            widget = self.chat_messages_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()
        self.chat_history = []
        self.session_messages = []
        self._stop_activity()
    def save_to_history(self, user_message, ai_response):
        """Save conversation to history"""
        conversation = {
            "timestamp": datetime.now().isoformat(),
            "user_message": user_message,
            "ai_response": ai_response
        }
        self.chat_history.append(conversation)
        self.refresh_history()
    def refresh_history(self):
        """Update history list"""
        self.history_list.clear()
        for i, conv in enumerate(self.chat_history):
            timestamp = datetime.fromisoformat(conv["timestamp"]).strftime("%Y-%m-%d %H:%M")
            item_text = f"{timestamp}: {conv['user_message'][:50]}..."
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, i)
            self.history_list.addItem(item)
    def load_conversation(self, item):
        """Load conversation from history"""
        index = item.data(Qt.UserRole)
        if 0 <= index < len(self.chat_history):
            conv = self.chat_history[index]
            self.clear_chat()
            self.add_message_to_chat("User", conv["user_message"], "user")
            self.add_message_to_chat("IA", conv["ai_response"], "assistant")
    def clear_history(self):
        """Clear history"""
        self.chat_history.clear()
        self.history_list.clear()
    def export_history(self):
        """Export history to file"""
        if not self.chat_history:
            QMessageBox.information(self, "History", "No conversations to export")
            return
        try:
            filename = f"chat_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.chat_history, f, indent=2, ensure_ascii=False)
            QMessageBox.information(self, "Export", f"History exported to {filename}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not export history: {e}")
    def load_settings(self):
        """Load saved settings"""
        try:
            # Here you could load from a configuration file
            # For now, we use default values
            pass
        except Exception as e:
            print(f"Error loading configuration: {e}")
    def save_settings(self):
        """Save settings"""
        try:
            # Here you could save to a configuration file
            pass
        except Exception as e:
            print(f"Error saving configuration: {e}") 
    def update_context_info(self):
        """DEPRECATED - Trigger extraction instead"""
        # Now we just trigger the extraction
        self.extract_page_content_now()
    def on_context_toggled(self, checked):
        """Callback when context is toggled"""
        if checked:
            # Show message suggesting to extract content
            if not self.context_display.toPlainText() or self.context_display.toPlainText().startswith("Page content"):
                self.add_message_to_chat("System", "Tip: Click 'Extract Page Content' to load the current page's content", "assistant")
        else:
            self.add_message_to_chat("System", "Page context disabled - AI will not receive page content", "assistant")
    def extract_page_content_now(self):
        """Extract page content and display it - SIMPLE VERSION"""
        try:
            # Show loading message
            self.context_display.setPlainText("Extracting page content...")
            self.extract_context_btn.setEnabled(False)

            # Get current tab
            main_window = self.window()
            if not hasattr(main_window, 'tab_manager'):
                self.context_display.setPlainText("Error: Cannot access tab manager")
                self.extract_context_btn.setEnabled(True)
                return
            current_tab = main_window.tab_manager.tabs.currentWidget()
            if not current_tab or not hasattr(current_tab, 'page'):
                self.context_display.setPlainText("Error: No active tab")
                self.extract_context_btn.setEnabled(True)
                return
            # Get URL and title
            current_url = current_tab.url().toString()
            current_title = current_tab.page().title()

            # Request HTML
            def on_html_received(html):
                try:
                    # Extract text content
                    extracted_text = self._simple_extract_text(html, current_url, current_title)

                    # Display in text edit
                    self.context_display.setPlainText(extracted_text)

                    # Add success message to chat
                    self.add_message_to_chat("System", f"Page content extracted: {len(extracted_text)} characters", "assistant")
                except Exception as e:
                    error_msg = f"Error extracting content: {str(e)}"
                    self.context_display.setPlainText(error_msg)
                    print(error_msg)
                    import traceback
                    traceback.print_exc()
                finally:
                    self.extract_context_btn.setEnabled(True)
            # Request HTML asynchronously
            current_tab.page().toHtml(on_html_received)
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            self.context_display.setPlainText(error_msg)
            print(error_msg)
            import traceback
            traceback.print_exc()
            self.extract_context_btn.setEnabled(True)
    def _simple_extract_text(self, html, url, title):
        """Simple and effective text extraction"""
        try:
            from bs4 import BeautifulSoup

            # Parse HTML
            soup = BeautifulSoup(html, 'lxml')

            # Remove unwanted elements
            for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'iframe', 'noscript', 'form']):
                element.decompose()
            # Get all text
            text = soup.get_text(separator='\n', strip=True)

            # Clean up
            lines = []
            for line in text.split('\n'):
                line = line.strip()
                if line and len(line) > 2:  # Skip very short lines
                    lines.append(line)
            clean_text = '\n'.join(lines)

            # Build context
            context = f"""PAGE: {title}
URL: {url}

CONTENT:
{clean_text[:3000]}

{'[Content truncated - showing first 3000 characters]' if len(clean_text) > 3000 else '[End of content]'}"""

            return context
        except ImportError:
            # Fallback without BeautifulSoup
            import re
            text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
            text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', '', text)
            text = re.sub(r'\s+', ' ', text).strip()

            return f"""PAGE: {title}
URL: {url}

CONTENT:
{text[:3000]}

{'[Content truncated]' if len(text) > 3000 else '[End]'}"""
        except Exception as e:
            return f"Error extracting text: {str(e)}"
    def get_current_context(self):
        """DEPRECATED - Now using context_display directly"""
        # This function is kept for compatibility but no longer used
        return self.context_display.toPlainText() if hasattr(self, 'context_display') else "" 
