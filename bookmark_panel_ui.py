#!/usr/bin/env python3
"""
bookmark_panel_ui.py — Panel de marcadores con árbol jerárquico de carpetas.

Este widget reemplaza/complementa al BookmarkManager de maintag.py ofreciendo:
  - Vista de árbol (QTreeWidget) con carpetas anidadas y marcadores
  - Crear, renombrar, eliminar carpetas vía menú contextual
  - Mover marcadores entre carpetas (menú contextual)
  - Doble clic para abrir un marcador en el navegador
  - Búsqueda rápida por título / URL
  - Exportación a HTML compatible con Firefox/Chrome
  - Diálogo para agregar marcador con selector de carpeta
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon

try:
    from favicon_manager import get_favicon_manager, _domain as _favicon_domain
    _FAVICON_AVAILABLE = True
except ImportError:
    _FAVICON_AVAILABLE = False
    def get_favicon_manager(): return None
    def _favicon_domain(url): return ""
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
)

import logging

logger = logging.getLogger(__name__)

# ─── ThemeEngine (opcional) ───────────────────────────────────────────────────
try:
    from ui.core.theme_engine import get_theme_engine
    _THEME_AVAILABLE = True
except ImportError:
    _THEME_AVAILABLE = False
    def get_theme_engine():
        return None


def _get_bookmark_theme_colors() -> dict:
    """Retorna colores del tema activo para el panel de marcadores."""
    if _THEME_AVAILABLE:
        te = get_theme_engine()
        if te:
            data = te.get_theme_data()
            colors = data.get("colors", {})
            return {
                "background": colors.get("background", "#1e1e2e"),
                "surface": colors.get("surface", "#313244"),
                "primary": colors.get("primary", "#cdd6f4"),
                "secondary": colors.get("secondary", "#a6adc8"),
                "border": colors.get("border", "#313244"),
                "hover": colors.get("hover", "#45475a"),
                "selected": colors.get("selected", "#45475a"),
                "accent": colors.get("accent", "#89b4fa"),
                "input_bg": colors.get("input_background", colors.get("surface", "#313244")),
                "input_border": colors.get("input_border", colors.get("border", "#45475a")),
            }
    return {
        "background": "#1e1e2e",
        "surface": "#313244",
        "primary": "#cdd6f4",
        "secondary": "#a6adc8",
        "border": "#313244",
        "hover": "#45475a",
        "selected": "#45475a",
        "accent": "#89b4fa",
        "input_bg": "#313244",
        "input_border": "#45475a",
    }

DB_PATH = "bookmarks.db"

# ─── Utilidades de iconos ─────────────────────────────────────────────────────

def _icon(name: str) -> QIcon:
    """Devuelve un QIcon desde la carpeta icons/ del proyecto."""
    return QIcon(f"icons/{name}.svg") or QIcon(f"icons/{name}.png")


# ─── Diálogo para añadir/editar un marcador ──────────────────────────────────

class AddBookmarkDialog(QDialog):
    """Diálogo modal para guardar un nuevo marcador eligiendo la carpeta."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        title: str = "",
        url: str = "",
        folders_manager=None,
        current_folder_id: int = 1,
    ):
        super().__init__(parent)
        self._folders_manager = folders_manager
        self.setWindowTitle("Guardar marcador")
        self.setModal(True)
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Título
        layout.addWidget(QLabel("Nombre:"))
        self.title_edit = QLineEdit(title)
        layout.addWidget(self.title_edit)

        # URL
        layout.addWidget(QLabel("URL:"))
        self.url_edit = QLineEdit(url)
        self.url_edit.setReadOnly(True)
        layout.addWidget(self.url_edit)

        # Carpeta destino + botón nueva carpeta
        layout.addWidget(QLabel("Guardar en carpeta:"))
        folder_row = QHBoxLayout()
        self.folder_combo = QComboBox()
        self._populate_folders(folders_manager, current_folder_id)
        folder_row.addWidget(self.folder_combo, stretch=1)
        new_folder_btn = QPushButton("+ Nueva carpeta")
        new_folder_btn.setFixedWidth(130)
        new_folder_btn.setToolTip("Crear una nueva carpeta y seleccionarla")
        new_folder_btn.clicked.connect(self._on_new_folder)
        folder_row.addWidget(new_folder_btn)
        layout.addLayout(folder_row)

        # Botones OK / Cancelar
        layout.addSpacing(4)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Guardar")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _on_new_folder(self) -> None:
        """Crea una nueva carpeta y la selecciona en el combo."""
        if not self._folders_manager:
            return
        name, ok = QInputDialog.getText(self, "Nueva carpeta", "Nombre de la carpeta:")
        if not ok or not name.strip():
            return
        try:
            # Crear como hija de la carpeta actualmente seleccionada
            parent_id = self.folder_combo.currentData() or 1
            new_folder = self._folders_manager.create_folder(name.strip(), parent_id)
            new_id = getattr(new_folder, "id", None)
            # Refrescar el combo y seleccionar la nueva carpeta
            self._populate_folders(self._folders_manager, new_id or 1)
            if new_id:
                idx = self.folder_combo.findData(new_id)
                if idx >= 0:
                    self.folder_combo.setCurrentIndex(idx)
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"No se pudo crear la carpeta:\n{exc}")

    def _populate_folders(self, folders_manager, current_folder_id: int):
        """Rellena el combo con todas las carpetas (árbol aplanado con sangría)."""
        self.folder_combo.clear()
        if folders_manager is None:
            self.folder_combo.addItem("Marcadores", 1)
            return
        selected_index = 0

        def _add(parent_id: int, indent: str = ""):
            nonlocal selected_index
            for folder in folders_manager.get_children(parent_id):
                label = f"{indent}{folder.name}"
                self.folder_combo.addItem(label, folder.id)
                if folder.id == current_folder_id:
                    selected_index = self.folder_combo.count() - 1
                _add(folder.id, indent + "")

        self.folder_combo.addItem("Marcadores (raíz)", 1)
        if current_folder_id == 1:
            selected_index = 0
        _add(1)
        self.folder_combo.setCurrentIndex(selected_index)

    @property
    def result_title(self) -> str:
        return self.title_edit.text().strip()

    @property
    def result_url(self) -> str:
        return self.url_edit.text().strip()

    @property
    def result_folder_id(self) -> int:
        return self.folder_combo.currentData() or 1


# ─── Diálogo para seleccionar carpeta destino ─────────────────────────────────

class MoveToCarpetaDialog(QDialog):
    """Diálogo para mover un marcador o carpeta a otra carpeta."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        folders_manager=None,
        exclude_folder_id: Optional[int] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Mover a…")
        self.setModal(True)
        self.setMinimumWidth(300)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Selecciona la carpeta destino:"))

        self.combo = QComboBox()
        self._populate(folders_manager, exclude_folder_id)
        layout.addWidget(self.combo)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("Mover")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)
    def _populate(self, folders_manager, exclude_id: Optional[int]):
        if not folders_manager:
            self.combo.addItem("Marcadores", 1)
            return
        def _add(parent_id: int, indent: str = ""):
            for f in folders_manager.get_children(parent_id):
                if f.id == exclude_id:
                    continue
                self.combo.addItem(f"{indent}{f.name}", f.id)
                _add(f.id, indent + "")
        self.combo.addItem("Marcadores (raíz)", 1)
        _add(1)
    @property
    def selected_folder_id(self) -> int:
        return self.combo.currentData() or 1


# ─── Panel principal ──────────────────────────────────────────────────────────

class BookmarkPanelWidget(QWidget):
    """
    Widget de panel de marcadores con árbol jerárquico de carpetas.

    Señales:
        bookmark_opened(url: str)   — emitida cuando el usuario hace doble clic
                                      en un marcador o elige «Abrir».
        new_tab_requested(url: str) — emitida cuando el usuario elige
                                      «Abrir en nueva pestaña».
        data_changed()              — emitida tras cualquier operación de escritura
                                      (crear/mover/eliminar), útil para refrescar
                                      la FavoritesBar.
    """

    bookmark_opened = Signal(str)
    new_tab_requested = Signal(str)
    data_changed = Signal()

    # Roles de datos en los QTreeWidgetItem
    _ROLE_ID = Qt.UserRole
    _ROLE_TYPE = Qt.UserRole + 1   # 'folder' | 'bookmark'

    def __init__(
        self,
        bookmark_manager=None,
        folders_manager=None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.bm = bookmark_manager    # instancia de BookmarkManager (maintag.py)
        self.fm = folders_manager     # instancia de FoldersManager

        # Dict domain → [QTreeWidgetItem, ...] pendientes de recibir favicon
        self._favicon_pending: dict[str, list] = {}

        self._build_ui()
        self._apply_dynamic_styles()
        self.reload()

        # Conectar al FaviconManager para actualizar items cuando llegue un favicon
        if _FAVICON_AVAILABLE:
            fvm = get_favicon_manager()
            if fvm:
                fvm.favicon_ready.connect(self._on_favicon_ready)

        # Conectar al ThemeEngine para reaccionar a cambios de tema
        if _THEME_AVAILABLE:
            te = get_theme_engine()
            if te:
                te.theme_changed.connect(self._on_theme_changed)
    def _on_favicon_ready(self, domain: str, icon: QIcon) -> None:
        """Actualiza los QTreeWidgetItem que esperaban el favicon de *domain*."""
        items = self._favicon_pending.pop(domain, [])
        for item in items:
            try:
                item.setIcon(0, icon)
            except RuntimeError:
                pass  # item ya destruido

    def _on_theme_changed(self, _theme_name: str) -> None:
        """Actualiza los estilos cuando cambia el tema global."""
        self._apply_dynamic_styles()
    def _apply_dynamic_styles(self) -> None:
        """Aplica estilos al panel usando el ThemeEngine activo."""
        c = _get_bookmark_theme_colors()
        self._title_lbl.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {c['primary']}; padding: 4px 0;"
        )
        self._tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {c['background']};
                color: {c['primary']};
                border: 1px solid {c['border']};
                border-radius: 6px;
                font-size: 13px;
            }}
            QTreeWidget::item {{
                padding: 3px 2px;
                border-radius: 4px;
            }}
            QTreeWidget::item:hover {{
                background-color: {c['hover']};
            }}
            QTreeWidget::item:selected {{
                background-color: {c['selected']};
                color: {c['primary']};
            }}
            QHeaderView::section {{
                background-color: {c['surface']};
                color: {c['secondary']};
                border: none;
                padding: 4px;
            }}
            QScrollBar:vertical {{
                background: {c['background']};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {c['hover']};
                border-radius: 4px;
            }}
        """)
    # ── Construcción de la UI ──────────────────────────────────────────────────

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(4, 4, 4, 4)
        root_layout.setSpacing(4)

        # — Título del panel —
        self._title_lbl = QLabel("Marcadores")
        root_layout.addWidget(self._title_lbl)

        # — Barra de búsqueda —
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Buscar marcadores…")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(self._on_search)
        root_layout.addWidget(self._search_edit)

        # — Árbol —
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Nombre", "URL"])
        self._tree.setColumnCount(2)
        self._tree.header().setStretchLastSection(True)
        self._tree.setAnimated(True)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        root_layout.addWidget(self._tree)
    # ── Carga de datos ─────────────────────────────────────────────────────────

    def reload(self):
        """Recarga el árbol completo desde la BD."""
        self._tree.clear()
        if not self.fm:
            return
        try:
            hierarchy = self.fm.get_hierarchy()
            self._add_node(None, hierarchy)
            self._tree.expandAll()
            self._tree.resizeColumnToContents(0)
        except Exception as e:
            logger.error("Error recargando panel de marcadores: %s", e)
    def _add_node(self, parent_item: Optional[QTreeWidgetItem], node: dict):
        """Añade recursivamente carpetas y marcadores al árbol."""
        # Item de carpeta
        if parent_item is None:
            folder_item = QTreeWidgetItem(self._tree)
        else:
            folder_item = QTreeWidgetItem(parent_item)
        folder_item.setText(0, f"{node['name']}")
        folder_item.setIcon(0, _icon("folder"))
        folder_item.setData(0, self._ROLE_ID, node["id"])
        folder_item.setData(0, self._ROLE_TYPE, "folder")
        folder_item.setFlags(folder_item.flags() | Qt.ItemIsDropEnabled)

        # Subcarpetas
        for sub in node.get("children_folders", []):
            self._add_node(folder_item, sub)
        # Marcadores
        for bm in node.get("children_bookmarks", []):
            bm_item = QTreeWidgetItem(folder_item)
            bm_item.setText(0, bm["title"])
            bm_item.setText(1, bm["url"])
            bm_item.setToolTip(1, bm["url"])
            bm_item.setData(0, self._ROLE_ID, bm["id"])
            bm_item.setData(0, self._ROLE_TYPE, "bookmark")
            # Favicon: inmediato si está en caché, asíncrono si no
            if _FAVICON_AVAILABLE:
                fvm = get_favicon_manager()
                icon = fvm.get(bm["url"]) if fvm else None
                if icon:
                    bm_item.setIcon(0, icon)
                else:
                    bm_item.setIcon(0, _icon("star"))
                    domain = _favicon_domain(bm["url"])
                    if domain and fvm:
                        self._favicon_pending.setdefault(domain, []).append(bm_item)
            else:
                bm_item.setIcon(0, _icon("star"))
    # ── Búsqueda ──────────────────────────────────────────────────────────────

    def _on_search(self, text: str):
        """Filtra el árbol mostrando solo los items que coincidan."""
        text = text.strip().lower()
        if not text:
            self.reload()
            return
        if not self.bm:
            return
        results = self.bm.search_bookmarks_text(text)
        self._tree.clear()

        root = QTreeWidgetItem(self._tree)
        root.setText(0, f"Resultados ({len(results)})")
        root.setData(0, self._ROLE_TYPE, "folder")

        for bm in results:
            item = QTreeWidgetItem(root)
            item.setText(0, bm["title"])
            item.setText(1, bm["url"])
            item.setToolTip(1, bm["url"])
            item.setData(0, self._ROLE_ID, bm["id"])
            item.setData(0, self._ROLE_TYPE, "bookmark")
            if _FAVICON_AVAILABLE:
                fvm = get_favicon_manager()
                icon = fvm.get(bm["url"]) if fvm else None
                if icon:
                    item.setIcon(0, icon)
                else:
                    item.setIcon(0, _icon("star"))
                    domain = _favicon_domain(bm["url"])
                    if domain and fvm:
                        self._favicon_pending.setdefault(domain, []).append(item)
            else:
                item.setIcon(0, _icon("star"))
        root.setExpanded(True)
        self._tree.resizeColumnToContents(0)
    # ── Acciones sobre carpetas ───────────────────────────────────────────────

    def _on_new_folder(self, parent_id: int = 1):
        """Crea una carpeta en la raíz (o en *parent_id*)."""
        name, ok = QInputDialog.getText(
            self, "Nueva carpeta", "Nombre de la carpeta:", QLineEdit.Normal, ""
        )
        if ok and name.strip():
            try:
                self.fm.create_folder(name.strip(), parent_id)
                self.reload()
                self.data_changed.emit()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"No se pudo crear la carpeta:\n{e}")
    def _create_subfolder(self, parent_id: int):
        name, ok = QInputDialog.getText(
            self, "Nueva subcarpeta", "Nombre:", QLineEdit.Normal, ""
        )
        if ok and name.strip():
            try:
                self.fm.create_folder(name.strip(), parent_id)
                self.reload()
                self.data_changed.emit()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"No se pudo crear la subcarpeta:\n{e}")
    def _rename_folder(self, item: QTreeWidgetItem, folder_id: int):
        old = item.text(0)
        new_name, ok = QInputDialog.getText(
            self, "Renombrar carpeta", "Nuevo nombre:", QLineEdit.Normal, old
        )
        if ok and new_name.strip():
            if self.fm.rename_folder(folder_id, new_name.strip()):
                self.reload()
                self.data_changed.emit()
            else:
                QMessageBox.critical(self, "Error", "No se pudo renombrar la carpeta")
    def _delete_folder(self, folder_id: int):
        reply = QMessageBox.question(
            self,
            "Eliminar carpeta",
            "¿Eliminar esta carpeta y todo su contenido?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            if self.fm.delete_folder(folder_id, recursive=True):
                self.reload()
                self.data_changed.emit()
            else:
                QMessageBox.critical(self, "Error", "No se pudo eliminar la carpeta")
    def _move_folder(self, folder_id: int):
        dlg = MoveToCarpetaDialog(self, self.fm, exclude_folder_id=folder_id)
        if dlg.exec():
            dest = dlg.selected_folder_id
            if self.fm.move_folder(folder_id, dest):
                self.reload()
                self.data_changed.emit()
            else:
                QMessageBox.critical(self, "Error", "No se pudo mover la carpeta")
    def _folder_properties(self, folder_id: int):
        if not self.fm:
            return
        folder = self.fm.get_folder(folder_id)
        children = self.fm.get_children(folder_id)
        bms = self.bm.get_bookmarks_by_folder(folder_id) if self.bm else []
        crumbs = self.fm.get_breadcrumb(folder_id)
        ruta = " › ".join(f.name for f in crumbs)
        msg = (
            f"Carpeta: {folder.name}\n"
            f"Ruta: {ruta}\n"
            f"Subcarpetas directas: {len(children)}\n"
            f"Marcadores directos: {len(bms)}"
        )
        QMessageBox.information(self, "Propiedades", msg)
    # ── Acciones sobre marcadores ─────────────────────────────────────────────

    def _on_add_bookmark(self):
        """Muestra el diálogo para añadir un marcador manualmente."""
        # Intentar obtener la URL actual del navegador
        main_window = self.window()
        url, title = "", ""
        if hasattr(main_window, "tab_manager"):
            tab = main_window.tab_manager.tabs.currentWidget()
            if tab:
                url = tab.url().toString()
                title = tab.page().title() if hasattr(tab, "page") else url
        dlg = AddBookmarkDialog(self, title=title, url=url, folders_manager=self.fm)
        if dlg.exec():
            if dlg.result_url and self.bm:
                self.bm.add_bookmark_to_folder(dlg.result_url, dlg.result_title or dlg.result_url, dlg.result_folder_id)
                self.reload()
                self.data_changed.emit()
    def _open_bookmark(self, item: QTreeWidgetItem):
        url = item.text(1)
        if url:
            self.bookmark_opened.emit(url)
    def _open_in_new_tab(self, item: QTreeWidgetItem):
        url = item.text(1)
        if url:
            self.new_tab_requested.emit(url)
    def _copy_url(self, item: QTreeWidgetItem):
        url = item.text(1)
        if url:
            QApplication.clipboard().setText(url)
    def _move_bookmark(self, item: QTreeWidgetItem, bookmark_id: int):
        dlg = MoveToCarpetaDialog(self, self.fm)
        if dlg.exec():
            if self.bm and self.bm.move_bookmark_to_folder(bookmark_id, dlg.selected_folder_id):
                self.reload()
                self.data_changed.emit()
            else:
                QMessageBox.critical(self, "Error", "No se pudo mover el marcador")
    def _delete_bookmark(self, bookmark_id: int):
        reply = QMessageBox.question(
            self, "Eliminar marcador", "¿Eliminar este marcador?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes and self.bm:
            if self.bm.delete_bookmark_by_id(bookmark_id):
                self.reload()
                self.data_changed.emit()
            else:
                QMessageBox.critical(self, "Error", "No se pudo eliminar el marcador")
    # ── Exportar ──────────────────────────────────────────────────────────────

    def _on_export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar marcadores", "bookmarks.html", "HTML (*.html)"
        )
        if path and self.bm and self.fm:
            if self.bm.export_bookmarks_html(path, self.fm):
                QMessageBox.information(self, "Exportado", f"Marcadores exportados a:\n{path}")
            else:
                QMessageBox.critical(self, "Error", "No se pudo exportar los marcadores")
    # ── Doble clic ────────────────────────────────────────────────────────────

    def _on_double_click(self, item: QTreeWidgetItem, _column: int):
        if item.data(0, self._ROLE_TYPE) == "bookmark":
            self._open_bookmark(item)
    # ── Menú contextual ───────────────────────────────────────────────────────

    def _on_context_menu(self, position):
        item = self._tree.itemAt(position)
        if not item:
            return
        item_type = item.data(0, self._ROLE_TYPE)
        item_id = item.data(0, self._ROLE_ID)
        menu = QMenu()

        if item_type == "folder":
            if item_id and item_id != 1:   # No en carpeta raíz
                menu.addAction("Renombrar", lambda: self._rename_folder(item, item_id))
                menu.addAction("Mover a…", lambda: self._move_folder(item_id))
                menu.addAction("Eliminar", lambda: self._delete_folder(item_id))
                menu.addSeparator()
            menu.addAction("Nueva subcarpeta", lambda: self._create_subfolder(item_id or 1))
            menu.addAction("Propiedades", lambda: self._folder_properties(item_id or 1))
        elif item_type == "bookmark":
            menu.addAction("Abrir", lambda: self._open_bookmark(item))
            menu.addAction("Abrir en nueva pestaña", lambda: self._open_in_new_tab(item))
            menu.addAction("Copiar URL", lambda: self._copy_url(item))
            menu.addSeparator()
            menu.addAction("Mover a carpeta…", lambda: self._move_bookmark(item, item_id))
            menu.addAction("Eliminar", lambda: self._delete_bookmark(item_id))
        menu.exec(self._tree.mapToGlobal(position))
