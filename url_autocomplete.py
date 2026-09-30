#!/usr/bin/env python3
"""
URL Autocomplete System - Sistema de autocompletado inteligente para la barra de URL

Características:
- Autocompletado basado en historial
- Sugerencias de marcadores
- URLs más visitadas priorizadas
- Sugerencias de búsqueda
- Predicción inteligente
"""

from PySide6.QtCore import Qt, Signal, QObject, QTimer, QStringListModel, QEvent
from PySide6.QtWidgets import (QCompleter, QListView, QStyledItemDelegate,
                               QStyle, QApplication)
from PySide6.QtGui import QFont, QPalette, QColor, QPainter, QIcon
import sqlite3
from datetime import datetime, timedelta


class AutocompleteItem:
    """Representa un item de autocompletado"""

    TYPE_URL = "url"
    TYPE_HISTORY = "history"
    TYPE_BOOKMARK = "bookmark"
    TYPE_SEARCH = "search"

    def __init__(self, text, url, item_type, title=None, visit_count=0, last_visit=None, icon=None):
        self.text = text
        self.url = url
        self.type = item_type
        self.title = title or text
        self.visit_count = visit_count
        self.last_visit = last_visit
        self.icon = icon
        self.score = 0  # Score para ranking
    def calculate_score(self):
        """Calcular score para ranking de sugerencias"""
        score = 0

        # Bonus por tipo
        if self.type == self.TYPE_BOOKMARK:
            score += 100  # Marcadores tienen prioridad
        elif self.type == self.TYPE_HISTORY:
            score += 50
        # Bonus por frecuencia de visitas
        score += min(self.visit_count * 5, 200)  # Max 200 puntos por frecuencia

        # Bonus por recencia (últimos 7 días)
        if self.last_visit:
            try:
                last_visit_dt = datetime.fromisoformat(self.last_visit)
                days_ago = (datetime.now() - last_visit_dt).days
                if days_ago < 7:
                    score += 30 - (days_ago * 4)  # Más reciente = más score
            except:
                pass
        self.score = score
        return score


class AutocompleteDelegate(QStyledItemDelegate):
    """Delegate personalizado para renderizar items de autocompletado"""

    def __init__(self, parent=None):
        super().__init__(parent)
    def paint(self, painter, option, index):
        """Renderizar item con estilo personalizado"""
        painter.save()

        # Colores
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor("#e8eaed"))
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(option.rect, QColor("#f5f5f5"))
        else:
            painter.fillRect(option.rect, QColor("#ffffff"))
        # Obtener datos del item
        text = index.data(Qt.DisplayRole)
        url = index.data(Qt.UserRole)
        item_type = index.data(Qt.UserRole + 1)
        title = index.data(Qt.UserRole + 2)

        # Icono según tipo
        icon_rect = option.rect.adjusted(8, 8, -option.rect.width() + 24, -8)

        icon_name = {"bookmark": "star", "history": "history", "search": "search"}.get(item_type, "link")
        # Dibujar icono SVG
        try:
            from PySide6.QtCore import QSize
            from ui.core.strip_icons import build_nav_icon
            build_nav_icon(icon_name, "#666666", QSize(14, 14)).paint(painter, icon_rect, Qt.AlignCenter)
        except Exception:
            pass

        # Dibujar título (en negrita)
        title_rect = option.rect.adjusted(36, 6, -10, -option.rect.height() // 2)
        painter.setPen(QColor("#1a1a1a"))
        font = QFont("Segoe UI", 10)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, title or text)

        # Dibujar URL (más pequeña, gris)
        url_rect = option.rect.adjusted(36, option.rect.height() // 2, -10, -6)
        painter.setPen(QColor("#666"))
        font = QFont("Segoe UI", 9)
        font.setBold(False)
        painter.setFont(font)
        painter.drawText(url_rect, Qt.AlignLeft | Qt.AlignVCenter, url or text)

        painter.restore()
    def sizeHint(self, option, index):
        """Tamaño de cada item"""
        return option.rect.adjusted(0, 0, 0, 54).size()


class UrlAutocompleteSystem(QObject):
    """Sistema de autocompletado inteligente para URLs"""

    suggestion_selected = Signal(str)  # URL seleccionada

    def __init__(self, url_bar, history_manager, parent=None):
        super().__init__(parent)
        self.url_bar = url_bar
        self.history_manager = history_manager
        self.parent_window = parent

        # Configurar completer
        self.completer = QCompleter()
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setCompletionMode(QCompleter.PopupCompletion)
        self.completer.setMaxVisibleItems(8)

        # Modelo de sugerencias
        self.model = QStringListModel()
        self.completer.setModel(self.model)

        # Vista personalizada
        self.popup = QListView()
        self.popup.setItemDelegate(AutocompleteDelegate())
        self.popup.setStyleSheet("""
            QListView {
                background-color: white;
                border: 1px solid #ccc;
                border-radius: 4px;
                outline: none;
            }
            QListView::item {
                height: 54px;
                border: none;
            }
        """)
        self.completer.setPopup(self.popup)

        # Conectar completer a url_bar
        self.url_bar.setCompleter(self.completer)

        # Timer para búsqueda con delay (evitar búsquedas mientras el usuario escribe)
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.update_suggestions)

        # Usar textEdited (sólo dispara con entrada del usuario, NO cuando se cambia
        # programáticamente al navegar o cambiar de pestaña)
        self.url_bar.textEdited.connect(self.on_text_changed)
        self.completer.activated.connect(self.on_suggestion_selected)

        # Instalar event filter para mostrar historial reciente al hacer clic
        self.url_bar.installEventFilter(self)
        self._focus_was_from_mouse = False

        # Cache de sugerencias
        self.suggestions_cache = []
        self.last_query = ""
    def eventFilter(self, obj, event):
        """Detectar clic en la barra para mostrar historial reciente."""
        if obj is self.url_bar:
            if event.type() == QEvent.MouseButtonPress:
                self._focus_was_from_mouse = True
            elif event.type() == QEvent.FocusIn and self._focus_was_from_mouse:
                self._focus_was_from_mouse = False
                QTimer.singleShot(50, self._show_recent_on_focus)
            elif event.type() == QEvent.FocusOut:
                self._focus_was_from_mouse = False
        return super().eventFilter(obj, event)
    def _show_recent_on_focus(self):
        """Mostrar las URLs más recientes al hacer clic en la barra."""
        if not self.url_bar.hasFocus():
            return
        # Solo si la barra está en blanco o seleccionada al completo (click para editar)
        recents = self._get_recent_history(8)
        if not recents:
            return
        self.model.setStringList([item.url for item in recents])
        for i, item in enumerate(recents):
            idx = self.model.index(i, 0)
            self.model.setData(idx, item.url, Qt.UserRole)
            self.model.setData(idx, item.type, Qt.UserRole + 1)
            self.model.setData(idx, item.title, Qt.UserRole + 2)
        self.completer.complete()
    def _get_recent_history(self, limit=8):
        """Obtener las URLs visitadas más recientemente."""
        suggestions = []
        try:
            if hasattr(self.history_manager, 'history') and self.history_manager.history:
                for entry in reversed(self.history_manager.history):
                    url = entry.get('url', '')
                    if not url:
                        continue
                    timestamp = entry.get('timestamp', None)
                    item = AutocompleteItem(
                        text=url,
                        url=url,
                        item_type=AutocompleteItem.TYPE_HISTORY,
                        title=entry.get('title', url) or url,
                        visit_count=1,
                        last_visit=timestamp.isoformat() if timestamp else None,
                    )
                    item.calculate_score()
                    suggestions.append(item)
                    if len(suggestions) >= limit:
                        break
        except Exception:
            pass
        return suggestions
    def on_text_changed(self, text):
        """Manejar cambios en el texto de la barra de URL"""
        # CRITICO: Solo buscar sugerencias si la barra tiene el foco
        # Esto evita que aparezcan al cambiar de pestaña
        if not self.url_bar.hasFocus():
            self.completer.popup().hide()
            return
        if len(text) < 2:
            self.completer.popup().hide()
            return
        # Reiniciar timer para búsqueda con delay
        self.search_timer.stop()
        self.search_timer.start(200)  # 200ms delay
    def update_suggestions(self):
        """Actualizar sugerencias de autocompletado"""
        # Verificación doble de foco (por si se perdió durante el delay)
        if not self.url_bar.hasFocus():
            return
        query = self.url_bar.text().strip().lower()

        if len(query) < 2:
            return
        # Evitar búsquedas duplicadas
        if query == self.last_query:
            return
        self.last_query = query

        # Buscar sugerencias
        suggestions = self.get_suggestions(query)

        # Ordenar por score
        suggestions.sort(key=lambda x: x.score, reverse=True)

        # Limitar a 8 resultados
        suggestions = suggestions[:8]

        # Actualizar modelo
        urls = [s.url for s in suggestions]
        self.model.setStringList(urls)

        # Guardar datos adicionales en el modelo
        for i, suggestion in enumerate(suggestions):
            index = self.model.index(i, 0)
            self.model.setData(index, suggestion.url, Qt.UserRole)
            self.model.setData(index, suggestion.type, Qt.UserRole + 1)
            self.model.setData(index, suggestion.title, Qt.UserRole + 2)
        # Mostrar popup si hay resultados
        if suggestions:
            self.completer.complete()
        else:
            self.completer.popup().hide()
    def get_suggestions(self, query):
        """Obtener sugerencias basadas en el query"""
        suggestions = []

        # 1. Buscar en historial
        history_suggestions = self.search_history(query)
        suggestions.extend(history_suggestions)

        # 2. Buscar en marcadores (si hay bookmarks disponibles)
        if hasattr(self.parent_window, 'bookmark_manager'):
            bookmark_suggestions = self.search_bookmarks(query)
            suggestions.extend(bookmark_suggestions)
        # 3. Agregar sugerencia de búsqueda
        if len(query) > 0:
            search_item = AutocompleteItem(
                text=f"Buscar: {query}",
                url=query,  # Se procesará como búsqueda
                item_type=AutocompleteItem.TYPE_SEARCH,
                title=f"Buscar \"{query}\"",
                visit_count=0
            )
            search_item.score = 10  # Baja prioridad
            suggestions.append(search_item)
        # Calcular scores
        for suggestion in suggestions:
            suggestion.calculate_score()
        return suggestions
    def search_history(self, query):
        """Buscar en el historial"""
        suggestions = []

        try:
            # El HistoryManager usa una lista en memoria, no base de datos
            if hasattr(self.history_manager, 'history') and self.history_manager.history:
                query_lower = query.lower()

                # Filtrar historial por coincidencias
                for entry in self.history_manager.history:
                    url = entry.get('url', '')
                    timestamp = entry.get('timestamp', None)

                    # Buscar en la URL
                    if query_lower in url.lower():
                        item = AutocompleteItem(
                            text=url,
                            url=url,
                            item_type=AutocompleteItem.TYPE_HISTORY,
                            title=url,  # Sin título separado en este sistema
                            visit_count=1,  # Sistema simple: cada entrada = 1 visita
                            last_visit=timestamp.isoformat() if timestamp else None
                        )
                        suggestions.append(item)
                # Limitar a 10 resultados más recientes
                suggestions = suggestions[-10:]
        except Exception as e:
            print(f"[Autocomplete] Error searching history: {e}")
        return suggestions
    def search_bookmarks(self, query):
        """Buscar en marcadores"""
        suggestions = []

        try:
            bookmark_manager = self.parent_window.bookmark_manager

            # BookmarkManager usa conn/cursor directamente, no db_path
            if hasattr(bookmark_manager, 'conn') and bookmark_manager.conn:
                cursor = bookmark_manager.conn.cursor()

                query_lower = query.lower()

                # Buscar en la tabla bookmarks (no "favorites")
                cursor.execute("""
                    SELECT url, title
                    FROM bookmarks
                    WHERE url LIKE ? OR title LIKE ?
                    LIMIT 10
                """, (f'%{query_lower}%', f'%{query_lower}%'))

                for row in cursor.fetchall():
                    url, title = row
                    item = AutocompleteItem(
                        text=url,
                        url=url,
                        item_type=AutocompleteItem.TYPE_BOOKMARK,
                        title=title or url,
                        visit_count=100  # Los marcadores tienen alta prioridad
                    )
                    suggestions.append(item)
        except Exception as e:
            print(f"[Autocomplete] Error searching bookmarks: {e}")
        return suggestions
    def on_suggestion_selected(self, text):
        """Manejar selección de sugerencia"""
        self.suggestion_selected.emit(text)
    def clear_cache(self):
        """Limpiar cache de sugerencias"""
        self.suggestions_cache = []
        self.last_query = ""
