#!/usr/bin/env python3
"""
Favorites Bar - Complete implementation similar to Firefox/Chrome
"""

from PySide6.QtWidgets import (QToolBar, QMenu, QDialog, QVBoxLayout,
                               QHBoxLayout, QLabel, QLineEdit, QComboBox,
                               QPushButton, QMessageBox, QCheckBox, QWidget,
                               QToolButton, QApplication, QInputDialog,
                               QFormLayout, QDialogButtonBox, QSizePolicy)
from PySide6.QtCore import Qt, Signal, QUrl, QPoint, QSettings
from PySide6.QtGui import QIcon, QPixmap, QAction, QClipboard
import sqlite3
import os
from urllib.parse import urlparse
import logging

from favicon_manager import get_favicon_manager, _domain as _favicon_domain

logger = logging.getLogger(__name__)


class _BarButton(QToolButton):
    """QToolButton con señal de doble clic (para editar nombre inline)."""
    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

def get_favicon_icon(url, favicon_cache=None):
    """
    Utility function to get favicon from a URL
    Returns a QIcon for general use
    """
    if favicon_cache is None:
        favicon_cache = {}
    try:
        if url in favicon_cache:
            return favicon_cache[url]
        parsed_url = urlparse(url)
        favicon_url = f"{parsed_url.scheme}://{parsed_url.netloc}/favicon.ico"

        # Do not download favicons during initialization to avoid blocking
        # TODO: Implement asynchronous favicon download in the future

        # Default favicon
        try:
            default_icon = QIcon("icons/bookmark.svg")
            if default_icon.isNull():
                # Create a simple icon if no file exists
                pixmap = QPixmap(16, 16)
                pixmap.fill()
                default_icon = QIcon(pixmap)
        except:
            # Last resort: empty icon
            pixmap = QPixmap(16, 16)
            pixmap.fill()
            default_icon = QIcon(pixmap)
        favicon_cache[url] = default_icon
        return default_icon
    except Exception as e:
        logger.error(f"Error getting favicon for URL %s: %s", url, e)
        return QIcon("icons/bookmark.svg")

def get_favicon_pixmap(url, favicon_cache=None):
    """
    Utility function to get favicon as QPixmap
    For compatibility with code that needs QPixmap
    """
    icon = get_favicon_icon(url, favicon_cache)
    return icon.pixmap(16, 16)

class FavoriteDialog(QDialog):
    """Dialog for adding/editing favorites in the bar"""

    def __init__(self, parent=None, title="", url="", category="", show_in_bar=True):
        super().__init__(parent)
        self.setWindowTitle("Add to Favorites")
        self.setModal(True)
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)

        # Title
        title_layout = QHBoxLayout()
        title_layout.addWidget(QLabel("Title:"))
        self.title_edit = QLineEdit(title)
        title_layout.addWidget(self.title_edit)
        layout.addLayout(title_layout)

        # URL
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("URL:"))
        self.url_edit = QLineEdit(url)
        url_layout.addWidget(self.url_edit)
        layout.addLayout(url_layout)

        # Category
        category_layout = QHBoxLayout()
        category_layout.addWidget(QLabel("Category:"))
        self.category_combo = QComboBox()
        self.load_categories()
        if category:
            index = self.category_combo.findText(category)
            if index >= 0:
                self.category_combo.setCurrentIndex(index)
        category_layout.addWidget(self.category_combo)
        layout.addLayout(category_layout)

        # Show in favorites bar
        self.show_in_bar_check = QCheckBox("Show in favorites bar")
        self.show_in_bar_check.setChecked(show_in_bar)
        layout.addWidget(self.show_in_bar_check)

        # Buttons
        button_layout = QHBoxLayout()
        save_button = QPushButton("Save")
        save_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(save_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
    def load_categories(self):
        """Loads available categories"""
        try:
            conn = sqlite3.connect('bookmarks.db')
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM categories ORDER BY name")
            categories = cursor.fetchall()

            self.category_combo.addItem("No category")
            for category in categories:
                self.category_combo.addItem(category[0])
            conn.close()
        except Exception as e:
            logger.error("Error loading favorite categories from bookmarks.db: %s", e)
    def get_values(self):
        """Gets values from the dialog"""
        return {
            'title': self.title_edit.text(),
            'url': self.url_edit.text(),
            'category': self.category_combo.currentText(),
            'show_in_bar': self.show_in_bar_check.isChecked()
        }

class FavoritesBar(QToolBar):
    """Favorites bar with complete functionality"""

    favorite_clicked = Signal(str)  # Signal when a favorite is clicked

    # Tamaño del icono de carpeta en la barra
    _FOLDER_ICON_SIZE = 14

    def __init__(self, parent=None):
        super().__init__("Favorites", parent)
        self.setObjectName("favoritesBar")   # necesario para la regla QSS #id
        self.setWindowTitle("Favorites Bar")
        self.setVisible(False)  # Initially hidden

        # Configure the bar — compacta, estilo Firefox
        self.setMovable(False)
        self.setFloatable(False)
        from PySide6.QtCore import QSize
        self.setIconSize(QSize(14, 14))
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setMaximumHeight(32)
        # Usamos #favoritesBar para ganar en especificidad a la regla global
        # del ThemeEngine: "QToolBar QToolButton { max-width:32px !important }"
        # Un selector #id tiene mayor especificidad que un selector de tipo,
        # por lo que #favoritesBar QToolButton gana incluso con !important.
        self.setStyleSheet("""
            #favoritesBar {
                spacing: 0px;
                padding: 0px 6px;
                border: none;
                background: transparent;
            }
            #favoritesBar::separator {
                width: 1px;
                background: rgba(128,128,128,0.30);
                margin: 4px 2px;
            }
            #favoritesBar QToolButton {
                padding: 2px 7px !important;
                margin: 0px 1px !important;
                border: none !important;
                border-radius: 4px !important;
                font-size: 12px !important;
                background: transparent !important;
                min-width: 0px !important;
                max-width: 9999px !important;
                min-height: 0px !important;
                max-height: 9999px !important;
            }
            #favoritesBar QToolButton:hover {
                background-color: rgba(255, 255, 255, 0.12) !important;
            }
            #favoritesBar QToolButton:pressed {
                background-color: rgba(255, 255, 255, 0.20) !important;
            }
            #favoritesBar QToolButton::menu-indicator {
                width: 0; height: 0; image: none;
            }
        """)

        # Favicon cache (legacy — mantenido por compatibilidad)
        self.favicon_cache = {}

        # Referencia al FoldersManager (se asigna en load_with_folders)
        self.folders_manager = None

        # Dict domain → lista de QToolButton pendientes de recibir su favicon
        self._favicon_pending: dict[str, list] = {}

        # Conectar al FaviconManager asíncrono
        _fm = get_favicon_manager()
        _fm.favicon_ready.connect(self._on_favicon_ready)

        # Modo icono-solo (sin nombre de texto) — se persiste en QSettings
        _s = QSettings("Katphi", "Browser")
        self._icon_only: bool = _s.value("favbar/icon_only", False, type=bool)

        # Menú contextual en el área vacía de la barra
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_toolbar_right_click)

        # Load favorites
        self.load_favorites()
    def load_favorites(self):
        """Loads favorites from the database"""
        try:
            conn = sqlite3.connect('bookmarks.db')
            cursor = conn.cursor()

            # Get favorites marked for the bar
            cursor.execute("""
                SELECT title, url, category, notes, tags 
                FROM bookmarks 
                WHERE notes LIKE '%[barra]%' 
                   OR tags LIKE '%[barra]%' 
                   OR category LIKE '%Barra%' 
                   OR tags LIKE '%barra%' 
                   OR notes LIKE '%barra%'
                   OR category = 'Barra de Favoritos'
                ORDER BY title
            """)

            favorites = cursor.fetchall()
            conn.close()

            # Clear current bar
            self.clear()

            # Add favorites to the bar
            for favorite in favorites:
                title, url, category, notes, tags = favorite
                self.add_favorite_to_bar(title, url)
            # Add button to add current page
            self.add_add_favorite_action()
        except Exception as e:
            logger.error("Error loading favorites for favorites bar: %s", e)
    def add_favorite_to_bar(self, title, url, bookmark_id: int = None):
        """Adds a favorite to the bar as a compact button (favicon + title or icon-only)."""
        try:
            from PySide6.QtCore import QSize

            favicon_mgr = get_favicon_manager()
            icon = favicon_mgr.get(url) or self._get_themed_bookmark_icon()

            btn = _BarButton(self)
            btn.setText(title)
            btn.setIcon(icon)
            btn.setIconSize(QSize(16, 16))
            btn.setToolButtonStyle(
                Qt.ToolButtonIconOnly if self._icon_only else Qt.ToolButtonTextBesideIcon
            )
            btn.setToolTip(f"{title}\n{url}")
            btn.clicked.connect(lambda _checked=False, u=url: self.favorite_clicked.emit(u))

            # Registrar como pendiente si el favicon aún no está en caché
            domain = _favicon_domain(url)
            if domain and favicon_mgr.get(url) is None:
                self._favicon_pending.setdefault(domain, []).append(btn)

            # Doble clic → editar nombre
            bm_data = {"id": bookmark_id, "title": title, "url": url}
            btn.doubleClicked.connect(lambda d=bm_data: self._edit_bookmark_dialog(d))

            # Menú contextual (clic derecho) estilo Firefox
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, b=btn, d=bm_data: self._show_bookmark_context_menu(b.mapToGlobal(pos), d)
            )

            self.addWidget(btn)
        except Exception as e:
            logger.error("Error adding favorite '%s' (%s) to bar: %s", title, url, e)

    def _on_favicon_ready(self, domain: str, icon) -> None:
        """Actualiza los botones de la barra que esperaban el favicon de *domain*."""
        from PySide6.QtCore import QSize
        btns = self._favicon_pending.pop(domain, [])
        for btn in btns:
            if btn is not None:
                try:
                    btn.setIcon(icon)
                    btn.setIconSize(QSize(16, 16))
                except RuntimeError:
                    pass  # widget ya destruido

    def _get_themed_bookmark_icon(self):
        """Devuelve un QIcon de marcador coloreado con el tema activo."""
        from PySide6.QtCore import QSize
        try:
            from ui.core.strip_icons import build_nav_icon, get_icon_color
            ico = build_nav_icon("star", get_icon_color(), QSize(14, 14))
            if not ico.isNull():
                return ico
        except Exception:
            pass
        return QIcon("icons/star.svg")
    def create_favorite_menu(self, title, url):
        """Creates the context menu for a favorite"""
        menu = QMenu()

        # Open
        open_action = menu.addAction("Open")
        open_action.triggered.connect(lambda: self.favorite_clicked.emit(url))

        # Open in new tab
        open_new_tab_action = menu.addAction("Open in new tab")
        open_new_tab_action.triggered.connect(lambda: self.open_in_new_tab(url))

        menu.addSeparator()

        # Edit
        edit_action = menu.addAction("Edit")
        edit_action.triggered.connect(lambda: self.edit_favorite(title, url))

        # Remove from bar
        remove_action = menu.addAction("Remove from favorites bar")
        remove_action.triggered.connect(lambda: self.remove_from_bar(title, url))

        menu.addSeparator()

        # Delete
        delete_action = menu.addAction("Delete")
        delete_action.triggered.connect(lambda: self.delete_favorite(title, url))

        return menu
    def add_add_favorite_action(self):
        """Adds the button to add the current page"""
        add_action = QAction("Añadir", self)
        try:
            from ui.core.strip_icons import build_nav_icon
            from PySide6.QtCore import QSize
            add_action.setIcon(build_nav_icon("star", None, QSize(14, 14)))
        except Exception:
            pass
        add_action.setToolTip("Add current page to favorites")
        add_action.triggered.connect(self.add_current_page)
        self.addAction(add_action)
    def add_current_page(self):
        """Adds the current page to favorites"""
        try:
            # Get the current page from the browser
            main_window = self.window()
            if hasattr(main_window, 'tab_manager'):
                current_tab = main_window.tab_manager.tabs.currentWidget()
                if current_tab:
                    url = current_tab.url().toString()
                    title = current_tab.page().title()

                    # Show dialog
                    dialog = FavoriteDialog(self, title, url)
                    if dialog.exec():
                        values = dialog.get_values()
                        self.save_favorite(values)
        except Exception as e:
            logger.error("Error adding current page to favorites: %s", e)
    def save_favorite(self, values):
        """Saves a favorite to the database"""
        try:
            conn = sqlite3.connect('bookmarks.db')
            cursor = conn.cursor()

            # Prepare notes and tags based on whether it's shown in the bar
            notes = "[barra]" if values['show_in_bar'] else ""
            tags = "barra" if values['show_in_bar'] else ""

            # Insert into database
            cursor.execute("""
                INSERT INTO bookmarks (title, url, category, notes, tags) 
                VALUES (?, ?, ?, ?, ?)
            """, (values['title'], values['url'], values['category'], notes, tags))

            conn.commit()
            conn.close()

            # Reload the bar
            self.load_favorites()

            QMessageBox.information(self, "Success", "Favorite saved successfully")
        except Exception as e:
            logger.error("Error saving favorite to bookmarks.db: %s", e)
            QMessageBox.critical(self, "Error", f"Error saving favorite: {e}")
    def edit_favorite(self, title, url):
        """Edits an existing favorite"""
        try:
            conn = sqlite3.connect('bookmarks.db')
            cursor = conn.cursor()

            # Get current data
            cursor.execute("""
                SELECT title, url, category, notes, tags 
                FROM bookmarks 
                WHERE url = ?
            """, (url,))

            result = cursor.fetchone()
            if result:
                current_title, current_url, current_category, current_notes, current_tags = result
                show_in_bar = "[barra]" in current_notes or "barra" in current_tags

                # Show edit dialog
                dialog = FavoriteDialog(self, current_title, current_url, current_category, show_in_bar)
                if dialog.exec():
                    values = dialog.get_values()
                    self.update_favorite(url, values)
            conn.close()
        except Exception as e:
            logger.error("Error editing favorite '%s' (%s): %s", title, url, e)
            QMessageBox.critical(self, "Error", f"Error editing favorite: {e}")
    def update_favorite(self, old_url, values):
        """Updates an existing favorite"""
        try:
            conn = sqlite3.connect('bookmarks.db')
            cursor = conn.cursor()

            # Prepare notes and tags
            notes = "[barra]" if values['show_in_bar'] else ""
            tags = "barra" if values['show_in_bar'] else ""

            # Update in database
            cursor.execute("""
                UPDATE bookmarks 
                SET title = ?, url = ?, category = ?, notes = ?, tags = ?
                WHERE url = ?
            """, (values['title'], values['url'], values['category'], notes, tags, old_url))

            conn.commit()
            conn.close()

            # Reload the bar
            self.load_favorites()

            QMessageBox.information(self, "Success", "Favorite updated successfully")
        except Exception as e:
            logger.error("Error updating favorite %s -> %s: %s", old_url, values.get('url'), e)
            QMessageBox.critical(self, "Error", f"Error updating favorite: {e}")
    def remove_from_bar(self, title, url):
        """Removes a favorite from the bar (but does not delete it)"""
        try:
            conn = sqlite3.connect('bookmarks.db')
            cursor = conn.cursor()

            # Update to remove from bar
            cursor.execute("""
                UPDATE bookmarks 
                SET notes = REPLACE(notes, '[barra]', ''), 
                    tags = REPLACE(tags, 'barra', '')
                WHERE url = ?
            """, (url,))

            conn.commit()
            conn.close()

            # Reload the bar
            self.load_favorites()

            QMessageBox.information(self, "Success", "Favorite removed from bar")
        except Exception as e:
            logger.error("Error removing favorite '%s' (%s) from bar: %s", title, url, e)
            QMessageBox.critical(self, "Error", f"Error removing favorite from bar: {e}")
    def delete_favorite(self, title, url):
        """Completely deletes a favorite"""
        reply = QMessageBox.question(
            self, "Confirm deletion", 
            f"Are you sure you want to delete '{title}'?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            try:
                conn = sqlite3.connect('bookmarks.db')
                cursor = conn.cursor()

                cursor.execute("DELETE FROM bookmarks WHERE url = ?", (url,))

                conn.commit()
                conn.close()

                # Reload the bar
                self.load_favorites()

                QMessageBox.information(self, "Success", "Favorite deleted successfully")
            except Exception as e:
                logger.error("Error deleting favorite '%s' (%s): %s", title, url, e)
                QMessageBox.critical(self, "Error", f"Error deleting favorite: {e}")
    def open_in_new_tab(self, url):
        """Opens a favorite in a new tab"""
        try:
            main_window = self.window()
            if hasattr(main_window, 'tab_manager'):
                main_window.tab_manager.add_new_tab(url)
        except Exception as e:
            logger.error("Error opening favorite in new tab (%s): %s", url, e)
    def get_favicon(self, url: str):
        """Devuelve el favicon para una URL (caché en memoria/disco)."""
        icon = get_favicon_manager().get(url)
        if icon:
            return icon
        return self._get_themed_bookmark_icon()
    def refresh_favorites(self):
        """Updates the favorites bar"""
        self.load_favorites()
    # ─── Integración con el sistema de carpetas ───────────────────────────────

    def load_with_folders(self, folders_manager) -> None:
        """
        Recarga la barra mostrando primero las carpetas como botones con
        submenú desplegable y después los marcadores sueltos de la raíz.

        Debe llamarse cuando el sistema de carpetas está disponible, en lugar
        de (o además de) load_favorites().

        Args:
            folders_manager: Instancia de FoldersManager.
        """
        try:
            self.folders_manager = folders_manager
            self.clear()

            hierarchy = folders_manager.get_hierarchy()

            # Subcarpetas de la raíz → botón con submenú
            for sub in hierarchy.get("children_folders", []):
                self._add_folder_button(sub)
            # Marcadores directamente en la raíz
            for bm in hierarchy.get("children_bookmarks", []):
                self.add_favorite_to_bar(bm["title"], bm["url"], bookmark_id=bm.get("id"))
            # Separador + botón de añadir
            self.addSeparator()
            self.add_add_favorite_action()
        except Exception as e:
            logger.error("Error cargando barra de favoritos con carpetas: %s", e)
            # Fallback al sistema anterior
            self.load_favorites()
    @property
    def _FOLDER_MENU_STYLE(self) -> str:
        """Estilo del menú desplegable de carpeta, usando colores del tema activo."""
        bg      = "#1e1e2e"
        text    = "#cdd6f4"
        border  = "#313244"
        hover   = "#45475a"
        try:
            from ui.core.theme_engine import get_theme_engine
            te = get_theme_engine()
            if te:
                c = te.get_theme_data().get("colors", {})
                bg     = c.get("surface",    bg)
                text   = c.get("primary",    text)
                border = c.get("border",     border)
                hover  = c.get("hover",      hover)
        except Exception:
            pass
        return f"""
            QMenu {{
                background-color: {bg};
                color: {text};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 4px;
                font-size: 12px;
            }}
            QMenu::item {{
                padding: 5px 20px 5px 10px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: {hover};
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {border};
                margin: 4px 8px;
            }}
        """

    def _add_folder_button(self, folder_node: dict) -> None:
        """Añade un botón de carpeta con icono SVG temático + nombre completo."""
        try:
            from PySide6.QtCore import QSize, QPoint

            submenu = QMenu(folder_node["name"], self)
            submenu.setStyleSheet(self._FOLDER_MENU_STYLE)
            self._build_folder_submenu(submenu, folder_node)

            btn = QToolButton(self)
            name = folder_node["name"]
            btn.setText(name)
            btn.setToolTip(name)
            btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            # Abrimos el submenú manualmente en clicked para evitar que
            # InstantPopup/MenuButtonPopup distorsione el sizeHint del botón
            # (con esos modos Qt reserva ancho para el indicador, ocultándolo
            # con QSS sólo afecta al render pero no al cálculo de tamaño).
            btn.clicked.connect(
                lambda _c=False, m=submenu, b=btn: m.exec(b.mapToGlobal(QPoint(0, b.height())))
            )

            # Icono SVG de carpeta coloreado con el tema activo
            try:
                from ui.core.strip_icons import build_nav_icon, get_icon_color
                folder_icon = build_nav_icon(
                    "folder", get_icon_color(), QSize(self._FOLDER_ICON_SIZE, self._FOLDER_ICON_SIZE)
                )
                if not folder_icon.isNull():
                    btn.setIcon(folder_icon)
                    btn.setIconSize(QSize(self._FOLDER_ICON_SIZE, self._FOLDER_ICON_SIZE))
            except Exception:
                pass

            # Sin setStyleSheet individual: los botones heredan el QSS de la
            # barra (que ya define hover/pressed), evitando que QStyleSheetStyle
            # recalcule el sizeHint de forma incorrecta para ToolButtonTextBesideIcon.

            # Menú contextual (clic derecho) estilo Firefox
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, b=btn, fn=folder_node: self._show_folder_context_menu(b.mapToGlobal(pos), fn)
            )

            self.addWidget(btn)
        except Exception as e:
            logger.error("Error añadiendo botón de carpeta '%s': %s", folder_node.get("name"), e)
    def _build_folder_submenu(self, menu: QMenu, folder_node: dict) -> None:
        """
        Rellena *menu* de forma recursiva con las subcarpetas y marcadores
        de *folder_node*.
        """
        # Subcarpetas → submenús anidados
        for sub in folder_node.get("children_folders", []):
            submenu = menu.addMenu(f"{sub['name']}")
            submenu.setStyleSheet(self._FOLDER_MENU_STYLE)
            self._build_folder_submenu(submenu, sub)
        # Marcadores de esta carpeta
        bms = folder_node.get("children_bookmarks", [])
        if folder_node.get("children_folders") and bms:
            menu.addSeparator()
        for bm in bms:
            url = bm["url"]
            title = bm["title"]
            icon = self.get_favicon(url)
            action = menu.addAction(icon, title)
            action.setToolTip(f"{title}\n{url}")
            action.triggered.connect(lambda _checked=False, u=url: self.favorite_clicked.emit(u))

    # ─── Menús contextuales estilo Firefox ───────────────────────────────────

    def _on_toolbar_right_click(self, pos: QPoint) -> None:
        """Clic derecho en el área vacía de la barra de favoritos."""
        menu = QMenu(self)
        menu.setStyleSheet(self._FOLDER_MENU_STYLE)
        a = menu.addAction("Nueva carpeta aquí...")
        a.triggered.connect(lambda: self._new_folder_dialog(None))
        a2 = menu.addAction("Añadir marcador aquí...")
        a2.triggered.connect(lambda: self._new_bookmark_dialog(None))
        menu.exec(self.mapToGlobal(pos))

    def _show_bookmark_context_menu(self, global_pos: QPoint, bm_data: dict) -> None:
        """Menú contextual completo para un marcador (estilo Firefox)."""
        menu = QMenu(self)
        menu.setStyleSheet(self._FOLDER_MENU_STYLE)

        a = menu.addAction("Abrir")
        a.triggered.connect(lambda: self.favorite_clicked.emit(bm_data["url"]))

        a = menu.addAction("Abrir en nueva pestaña")
        a.triggered.connect(lambda: self.open_in_new_tab(bm_data["url"]))

        a = menu.addAction("Abrir en nueva ventana")
        a.triggered.connect(lambda: self._open_in_new_window(bm_data["url"]))

        menu.addSeparator()

        a = menu.addAction("Editar marcador...")
        a.triggered.connect(lambda: self._edit_bookmark_dialog(bm_data))

        a = menu.addAction("Copiar URL")
        a.triggered.connect(lambda: self._copy_url(bm_data["url"]))

        if self.folders_manager:
            move_menu = menu.addMenu("Mover a")
            move_menu.setStyleSheet(self._FOLDER_MENU_STYLE)
            self._build_move_to_submenu(
                move_menu,
                lambda fid: self._move_bookmark_to_folder(bm_data.get("id"), fid)
            )

        menu.addSeparator()

        a = menu.addAction("Eliminar")
        a.triggered.connect(lambda: self._delete_bookmark_by_id(bm_data))

        menu.exec(global_pos)

    def _show_folder_context_menu(self, global_pos: QPoint, folder_node: dict) -> None:
        """Menú contextual completo para una carpeta (estilo Firefox)."""
        menu = QMenu(self)
        menu.setStyleSheet(self._FOLDER_MENU_STYLE)

        a = menu.addAction("Abrir todo en pestañas")
        a.triggered.connect(lambda: self._open_all_in_tabs(folder_node))

        menu.addSeparator()

        a = menu.addAction("Nuevo marcador aquí...")
        a.triggered.connect(lambda: self._new_bookmark_dialog(folder_node["id"]))

        a = menu.addAction("Nueva subcarpeta...")
        a.triggered.connect(lambda: self._new_folder_dialog(folder_node["id"]))

        menu.addSeparator()

        a = menu.addAction("Renombrar carpeta...")
        a.triggered.connect(lambda: self._rename_folder_dialog(folder_node))

        if self.folders_manager:
            move_menu = menu.addMenu("Mover a")
            move_menu.setStyleSheet(self._FOLDER_MENU_STYLE)
            self._build_move_to_submenu(
                move_menu,
                lambda fid: self._move_folder_to(folder_node["id"], fid),
                exclude_id=folder_node["id"]
            )

        menu.addSeparator()

        a = menu.addAction("Eliminar carpeta...")
        a.triggered.connect(lambda: self._delete_folder_confirmed(folder_node))

        menu.exec(global_pos)

    # ─── Acciones de marcadores ───────────────────────────────────────────────

    def _open_in_new_window(self, url: str) -> None:
        """Abre una URL en una nueva ventana del navegador."""
        try:
            main_window = self.window()
            if hasattr(main_window, 'open_new_window'):
                main_window.open_new_window(url)
            else:
                self.open_in_new_tab(url)
        except Exception as e:
            logger.error("Error abriendo URL en nueva ventana (%s): %s", url, e)

    def _copy_url(self, url: str) -> None:
        """Copia una URL al portapapeles."""
        try:
            QApplication.clipboard().setText(url)
        except Exception as e:
            logger.error("Error copiando URL al portapapeles: %s", e)

    def _open_all_in_tabs(self, folder_node: dict) -> None:
        """Abre todos los marcadores de una carpeta (recursivo) en pestañas nuevas."""
        try:
            for url in self._collect_all_urls(folder_node):
                self.open_in_new_tab(url)
        except Exception as e:
            logger.error("Error abriendo todos los marcadores en pestañas: %s", e)

    def _collect_all_urls(self, folder_node: dict) -> list:
        """Devuelve recursivamente todas las URLs de una carpeta."""
        urls = [bm["url"] for bm in folder_node.get("children_bookmarks", [])]
        for sub in folder_node.get("children_folders", []):
            urls.extend(self._collect_all_urls(sub))
        return urls

    def _edit_bookmark_dialog(self, bm_data: dict) -> None:
        """Diálogo para editar título y URL de un marcador existente."""
        try:
            bm_id = bm_data.get("id")
            if bm_id:
                conn = sqlite3.connect('bookmarks.db')
                cursor = conn.cursor()
                cursor.execute("SELECT title, url FROM bookmarks WHERE id=?", (bm_id,))
                row = cursor.fetchone()
                conn.close()
                if not row:
                    return
                title, url = row
            else:
                title = bm_data.get("title", "")
                url   = bm_data.get("url", "")

            dlg = QDialog(self)
            dlg.setWindowTitle("Editar marcador")
            dlg.setMinimumWidth(380)
            form = QFormLayout(dlg)
            title_edit = QLineEdit(title)
            url_edit   = QLineEdit(url)
            form.addRow("Nombre:", title_edit)
            form.addRow("URL:", url_edit)
            btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            btns.accepted.connect(dlg.accept)
            btns.rejected.connect(dlg.reject)
            form.addRow(btns)

            if dlg.exec() != QDialog.Accepted:
                return

            new_title = title_edit.text().strip()
            new_url   = url_edit.text().strip()
            if not new_title or not new_url:
                return

            conn = sqlite3.connect('bookmarks.db')
            cursor = conn.cursor()
            if bm_id:
                cursor.execute("UPDATE bookmarks SET title=?, url=? WHERE id=?", (new_title, new_url, bm_id))
            else:
                cursor.execute("UPDATE bookmarks SET title=?, url=? WHERE url=?", (new_title, new_url, url))
            conn.commit()
            conn.close()
            self._reload_bar()
        except Exception as e:
            logger.error("Error editando marcador: %s", e)
            QMessageBox.critical(self, "Error", f"Error al editar el marcador: {e}")

    def _move_bookmark_to_folder(self, bookmark_id, folder_id) -> None:
        """Mueve un marcador a una carpeta diferente."""
        try:
            if bookmark_id is None:
                return
            conn = sqlite3.connect('bookmarks.db')
            cursor = conn.cursor()
            cursor.execute("UPDATE bookmarks SET folder_id=? WHERE id=?", (folder_id, bookmark_id))
            conn.commit()
            conn.close()
            self._reload_bar()
        except Exception as e:
            logger.error("Error moviendo marcador %s a carpeta %s: %s", bookmark_id, folder_id, e)

    def _delete_bookmark_by_id(self, bm_data: dict) -> None:
        """Pide confirmación y elimina un marcador."""
        title = bm_data.get("title", "")
        reply = QMessageBox.question(
            self, "Confirmar eliminación",
            f"¿Eliminar el marcador «{title}»?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        try:
            conn = sqlite3.connect('bookmarks.db')
            cursor = conn.cursor()
            bm_id = bm_data.get("id")
            if bm_id:
                cursor.execute("DELETE FROM bookmarks WHERE id=?", (bm_id,))
            else:
                cursor.execute("DELETE FROM bookmarks WHERE url=?", (bm_data.get("url", ""),))
            conn.commit()
            conn.close()
            self._reload_bar()
        except Exception as e:
            logger.error("Error eliminando marcador: %s", e)

    def _new_bookmark_dialog(self, folder_id) -> None:
        """Diálogo para crear un nuevo marcador (prerellena con la página actual)."""
        try:
            current_url, current_title = "", ""
            main_window = self.window()
            if hasattr(main_window, 'tab_manager'):
                tab = main_window.tab_manager.tabs.currentWidget()
                if tab:
                    current_url   = tab.url().toString()
                    current_title = tab.page().title()

            dlg = QDialog(self)
            dlg.setWindowTitle("Nuevo marcador")
            dlg.setMinimumWidth(380)
            form = QFormLayout(dlg)
            title_edit = QLineEdit(current_title)
            url_edit   = QLineEdit(current_url)
            form.addRow("Nombre:", title_edit)
            form.addRow("URL:", url_edit)
            btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            btns.accepted.connect(dlg.accept)
            btns.rejected.connect(dlg.reject)
            form.addRow(btns)

            if dlg.exec() != QDialog.Accepted:
                return

            new_title = title_edit.text().strip()
            new_url   = url_edit.text().strip()
            if not new_title or not new_url:
                return

            conn = sqlite3.connect('bookmarks.db')
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO bookmarks (title, url, folder_id) VALUES (?, ?, ?)",
                (new_title, new_url, folder_id)
            )
            conn.commit()
            conn.close()
            self._reload_bar()
        except Exception as e:
            logger.error("Error creando marcador: %s", e)

    # ─── Acciones de carpetas ─────────────────────────────────────────────────

    def _new_folder_dialog(self, parent_id) -> None:
        """Diálogo para crear una nueva carpeta."""
        try:
            if not self.folders_manager:
                return
            name, ok = QInputDialog.getText(self, "Nueva carpeta", "Nombre de la carpeta:")
            if not ok or not name.strip():
                return
            self.folders_manager.create_folder(name.strip(), parent_id)
            self._reload_bar()
        except Exception as e:
            logger.error("Error creando carpeta: %s", e)

    def _rename_folder_dialog(self, folder_node: dict) -> None:
        """Diálogo para renombrar una carpeta."""
        try:
            if not self.folders_manager:
                return
            name, ok = QInputDialog.getText(
                self, "Renombrar carpeta", "Nuevo nombre:",
                text=folder_node.get("name", "")
            )
            if not ok or not name.strip():
                return
            self.folders_manager.rename_folder(folder_node["id"], name.strip())
            self._reload_bar()
        except Exception as e:
            logger.error("Error renombrando carpeta: %s", e)

    def _move_folder_to(self, folder_id, new_parent_id) -> None:
        """Mueve una carpeta a un nuevo padre."""
        try:
            if not self.folders_manager:
                return
            self.folders_manager.move_folder(folder_id, new_parent_id)
            self._reload_bar()
        except Exception as e:
            logger.error("Error moviendo carpeta %s a %s: %s", folder_id, new_parent_id, e)

    def _delete_folder_confirmed(self, folder_node: dict) -> None:
        """Pide confirmación y elimina una carpeta con todo su contenido."""
        name = folder_node.get("name", "")
        reply = QMessageBox.question(
            self, "Eliminar carpeta",
            f"¿Eliminar la carpeta «{name}» y todo su contenido?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        try:
            if self.folders_manager:
                self.folders_manager.delete_folder(folder_node["id"], recursive=True)
                self._reload_bar()
        except Exception as e:
            logger.error("Error eliminando carpeta '%s': %s", name, e)

    def _build_move_to_submenu(self, menu: QMenu, callback, exclude_id=None) -> None:
        """Rellena *menu* con todas las carpetas disponibles como destino de movimiento."""
        try:
            if not self.folders_manager:
                return
            a = menu.addAction("\U0001f4c2 Raíz (barra principal)")
            a.triggered.connect(lambda _checked=False: callback(None))
            folders = self.folders_manager.get_all_folders_flat()
            if folders:
                menu.addSeparator()
            for f in folders:
                if f.id == exclude_id:
                    continue
                a = menu.addAction(f"\U0001f4c1 {f.name}")
                fid = f.id
                a.triggered.connect(lambda _checked=False, fid=fid: callback(fid))
        except Exception as e:
            logger.error("Error construyendo submenú 'Mover a': %s", e)

    def _reload_bar(self) -> None:
        """Recarga la barra de favoritos completa."""
        try:
            if self.folders_manager:
                self.load_with_folders(self.folders_manager)
            else:
                self.load_favorites()
        except Exception as e:
            logger.error("Error recargando barra de favoritos: %s", e)
