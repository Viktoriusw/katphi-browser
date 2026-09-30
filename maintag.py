from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                              QLineEdit, QTreeWidget, QTreeWidgetItem, QDialog,
                              QLabel, QComboBox, QMessageBox, QMenu, QInputDialog,
                              QMainWindow, QTextEdit)
from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QIcon, QPixmap
import sqlite3
import os
import urllib.request
from urllib.parse import urlparse
import logging


class BookmarkDialog(QDialog):
    def __init__(self, parent=None, values=None):
        super().__init__(parent)

        self.setWindowTitle("Add Bookmark" if not values else "Edit Bookmark")

        self.setModal(True)

        layout = QVBoxLayout(self)

        # Title

        title_layout = QHBoxLayout()

        title_layout.addWidget(QLabel("Title:"))

        self.title_edit = QLineEdit()

        if values:
            self.title_edit.setText(values[0])
        title_layout.addWidget(self.title_edit)

        layout.addLayout(title_layout)

        # URL

        url_layout = QHBoxLayout()

        url_layout.addWidget(QLabel("URL:"))

        self.url_edit = QLineEdit()

        if values:
            self.url_edit.setText(values[1])
        url_layout.addWidget(self.url_edit)

        layout.addLayout(url_layout)

        # Category

        category_layout = QHBoxLayout()

        category_layout.addWidget(QLabel("Category:"))

        self.category_combo = QComboBox()

        if values:
            self.category_combo.addItem(values[2])
        category_layout.addWidget(self.category_combo)

        layout.addLayout(category_layout)

        # Tags

        tags_layout = QHBoxLayout()

        tags_layout.addWidget(QLabel("Tags:"))

        self.tags_edit = QLineEdit()

        if values:
            self.tags_edit.setText(values[3])
        tags_layout.addWidget(self.tags_edit)

        layout.addLayout(tags_layout)

        # Notes

        notes_layout = QVBoxLayout()

        notes_layout.addWidget(QLabel("Notes:"))

        self.notes_edit = QTextEdit()

        if values and len(values) > 4:
            self.notes_edit.setPlainText(values[4])
        notes_layout.addWidget(self.notes_edit)

        layout.addLayout(notes_layout)

        # Buttons

        button_layout = QHBoxLayout()

        save_button = QPushButton("Save")

        save_button.clicked.connect(self.accept)

        cancel_button = QPushButton("Cancel")

        cancel_button.clicked.connect(self.reject)

        button_layout.addWidget(save_button)

        button_layout.addWidget(cancel_button)

        layout.addLayout(button_layout)
    def get_values(self):
        return (

            self.title_edit.text(),

            self.url_edit.text(),

            self.category_combo.currentText(),

            self.tags_edit.text(),

            self.notes_edit.toPlainText()
        )


class BookmarkManager(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.favicon_cache = {}

        self.logger = logging.getLogger(__name__)

        self.init_ui()

        self.init_database()

        self.load_bookmarks()
    def init_ui(self):
        layout = QVBoxLayout(self)

        # Toolbar

        toolbar = QHBoxLayout()

        # Add Bookmark button

        add_bookmark_btn = QPushButton("Add Bookmark")

        add_bookmark_btn.clicked.connect(self.add_bookmark)

        toolbar.addWidget(add_bookmark_btn)

        # Add Folder button

        add_folder_btn = QPushButton("Add Folder")

        add_folder_btn.clicked.connect(self.add_category)

        toolbar.addWidget(add_folder_btn)

        # View Categories button

        view_categories_btn = QPushButton("View Categories")

        view_categories_btn.clicked.connect(self.show_categories)

        toolbar.addWidget(view_categories_btn)

        # Search bar con estilo moderno

        self.search_bar = QLineEdit()

        self.search_bar.setPlaceholderText("Search bookmarks...")

        self.search_bar.setFixedHeight(32)  # Altura consistente con la modernización

        if hasattr(self.search_bar, "setClearButtonEnabled"):
            self.search_bar.setClearButtonEnabled(True)
        self.search_bar.textChanged.connect(self.search_bookmarks)

        toolbar.addWidget(self.search_bar)

        # Tag filter

        tag_filter_layout = QHBoxLayout()

        self.tag_filter = QComboBox()

        self.tag_filter.addItem("All Tags", "")

        self.tag_filter.currentIndexChanged.connect(self.filter_by_tag)

        tag_filter_layout.addWidget(self.tag_filter)

        # Add new tag button

        add_tag_button = QPushButton("+")

        add_tag_button.setToolTip("Add new tag")

        add_tag_button.setMaximumWidth(30)

        add_tag_button.clicked.connect(self.add_new_tag)

        tag_filter_layout.addWidget(add_tag_button)

        toolbar.addLayout(tag_filter_layout)

        layout.addLayout(toolbar)

        # Tree widget for bookmarks

        self.tree = QTreeWidget()

        self.tree.setHeaderLabels(["Title", "URL", "Category", "Tags", "Notes"])

        self.tree.setColumnWidth(0, 200)

        self.tree.setColumnWidth(1, 300)

        self.tree.setColumnWidth(2, 100)

        self.tree.setColumnWidth(3, 100)

        self.tree.setColumnWidth(4, 200)

        self.tree.itemDoubleClicked.connect(self.on_double_click)

        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)

        self.tree.customContextMenuRequested.connect(self.show_context_menu)

        # Estilo para tema claro: fondo claro y texto oscuro

        self.tree.setStyleSheet("""

            QTreeWidget {

                background-color: #f5f5f5;
                color: #111111;
            }

            QHeaderView::section {

                background-color: #e0e0e0;
                color: #111111;
            }
        """)

        layout.addWidget(self.tree)
    def init_database(self):
        try:
            self.conn = sqlite3.connect('bookmarks.db')

            self.cursor = self.conn.cursor()

            # Create tables

            self.cursor.execute('''

                CREATE TABLE IF NOT EXISTS bookmarks (

                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    title TEXT NOT NULL,

                    url TEXT NOT NULL,

                    category TEXT NOT NULL,

                    notes TEXT,

                    tags TEXT
                )
            ''')

            self.cursor.execute('''

                CREATE TABLE IF NOT EXISTS categories (

                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    name TEXT UNIQUE NOT NULL
                )
            ''')

            # Insert initial categories

            initial_categories = [

                "All bookmarks", "Buy", "Trash", "Work",

                "Design Inspiration", "Interior", "Interface", "Icons",

                "Apps", "Home", "Buy", "Movies", "Plan next trip"
            ]

            for category in initial_categories:
                try:
                    self.cursor.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (category,))
                except sqlite3.Error:
                    continue
            self.conn.commit()
        except sqlite3.Error as e:
            QMessageBox.critical(self, "Database Error", f"Error initializing database: {str(e)}")
    def get_favicon(self, url):
        """Obtiene el favicon de una URL (sin bloquear)"""

        from favorites_bar import get_favicon_pixmap

        return get_favicon_pixmap(url, self.favicon_cache)
    def load_bookmarks(self):
        self.tree.clear()

        try:
            # First, get all categories

            self.cursor.execute("SELECT name FROM categories ORDER BY name")

            categories = self.cursor.fetchall()

            # Create category items

            category_items = {}

            for category in categories:
                category_name = category[0]

                category_item = QTreeWidgetItem(self.tree)

                category_item.setText(0, category_name)

                category_item.setExpanded(True)

                category_items[category_name] = category_item
            # Load bookmarks under their categories

            self.cursor.execute("SELECT id, title, url, category, tags, notes FROM bookmarks ORDER BY title")

            for bookmark in self.cursor.fetchall():
                item = QTreeWidgetItem(category_items.get(bookmark[3], self.tree))

                # Set favicon

                favicon = self.get_favicon(bookmark[2])

                item.setIcon(0, QIcon(favicon))

                item.setText(0, bookmark[1])  # Title

                item.setText(1, bookmark[2])  # URL

                item.setText(2, bookmark[3])  # Category

                item.setText(3, bookmark[4] if bookmark[4] else "")  # Tags

                item.setText(4, bookmark[5] if bookmark[5] else "")  # Notes

                item.setData(0, Qt.UserRole, bookmark[0])  # Store ID
            # Update tag filter

            self.update_tag_filter()
        except sqlite3.Error as e:
            QMessageBox.critical(self, "Database Error", f"Error loading bookmarks: {str(e)}")
    def update_tag_filter(self):
        """Actualiza el filtro de tags"""

        try:
            current_tag = self.tag_filter.currentData()

            self.tag_filter.clear()

            self.tag_filter.addItem("All Tags", "")

            # Get all unique tags

            self.cursor.execute("SELECT DISTINCT tags FROM bookmarks WHERE tags IS NOT NULL AND tags != ''")

            tags = set()

            for row in self.cursor.fetchall():
                if row[0]:
                    tags.update(tag.strip() for tag in row[0].split(','))
            # Add tags to filter

            for tag in sorted(tags):
                self.tag_filter.addItem(tag, tag)
            # Restore previous selection

            if current_tag:
                index = self.tag_filter.findData(current_tag)

                if index >= 0:
                    self.tag_filter.setCurrentIndex(index)
        except sqlite3.Error as e:
            self.logger.error("Error updating tag filter: %s", e)
    def filter_by_tag(self):
        """Filtra los marcadores por tag seleccionado"""

        selected_tag = self.tag_filter.currentData()

        if not selected_tag:
            # Show all bookmarks

            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)

                item.setHidden(False)

                for j in range(item.childCount()):
                    item.child(j).setHidden(False)
        else:
            # Filter by tag

            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)

                show_category = False

                for j in range(item.childCount()):
                    child = item.child(j)

                    tags = child.text(3).split(',')

                    if selected_tag in [tag.strip() for tag in tags]:
                        child.setHidden(False)

                        show_category = True
                    else:
                        child.setHidden(True)
                item.setHidden(not show_category)
    def add_bookmark(self):
        dialog = BookmarkDialog(self)

        if dialog.exec():
            title, url, category, tags, notes = dialog.get_values()

            try:
                self.cursor.execute(

                    "INSERT INTO bookmarks (title, url, category, tags, notes) VALUES (?, ?, ?, ?, ?)",

                    (title, url, category, tags, notes)
                )

                self.conn.commit()

                self.load_bookmarks()
            except sqlite3.Error as e:
                QMessageBox.critical(self, "Database Error", f"Error adding bookmark: {str(e)}")
    def add_category(self):
        category, ok = QInputDialog.getText(self, "Add Category", "Category Name:")

        if ok and category:
            try:
                self.cursor.execute("INSERT INTO categories (name) VALUES (?)", (category,))

                self.conn.commit()

                QMessageBox.information(self, "Success", f"Category '{category}' added successfully!")
            except sqlite3.IntegrityError:
                QMessageBox.warning(self, "Error", "This category already exists.")
            except sqlite3.Error as e:
                QMessageBox.critical(self, "Database Error", f"Error adding category: {str(e)}")
    def show_categories(self):
        try:
            self.cursor.execute("SELECT name FROM categories ORDER BY name")

            categories = self.cursor.fetchall()

            if not categories:
                QMessageBox.information(self, "Categories", "No categories found.")

                return
            # Create dialog to show categories

            dialog = QDialog(self)

            dialog.setWindowTitle("Categories")

            dialog.setModal(True)

            layout = QVBoxLayout(dialog)

            # Add list widget to show categories

            list_widget = QTreeWidget()

            list_widget.setHeaderLabels(["Category", "Bookmark Count"])

            list_widget.setColumnWidth(0, 200)

            for category in categories:
                category_name = category[0]

                # Get bookmark count for this category

                self.cursor.execute("SELECT COUNT(*) FROM bookmarks WHERE category = ?", (category_name,))

                count = self.cursor.fetchone()[0]

                item = QTreeWidgetItem(list_widget)

                item.setText(0, category_name)

                item.setText(1, str(count))
            layout.addWidget(list_widget)

            # Add close button

            close_btn = QPushButton("Close")

            close_btn.clicked.connect(dialog.accept)

            layout.addWidget(close_btn)

            dialog.exec()
        except sqlite3.Error as e:
            QMessageBox.critical(self, "Database Error", f"Error loading categories: {str(e)}")
    def on_double_click(self, item, column):
        url = item.text(1)  # URL is in column 1

        if url:
            # Get the parent window (BrowserUI)

            parent = self.parent()

            while parent and not isinstance(parent, QMainWindow):
                parent = parent.parent()
            if parent and hasattr(parent, 'tab_manager'):
                # Get the current tab

                current_tab = parent.tab_manager.tabs.currentWidget()

                if current_tab:
                    # Load the URL in the current tab

                    current_tab.setUrl(QUrl(url))
                else:
                    # If no current tab, create a new one

                    parent.tab_manager.add_new_tab(url)
            else:
                QMessageBox.warning(self, "Error", "Could not find browser window to load URL")
    def show_context_menu(self, position):
        item = self.tree.itemAt(position)

        if item:
            menu = QMenu()

            open_action = menu.addAction("Open")

            edit_action = menu.addAction("Edit")

            delete_action = menu.addAction("Delete")

            action = menu.exec(self.tree.mapToGlobal(position))

            if action == open_action:
                self.on_double_click(item, 0)
            elif action == edit_action:
                self.edit_bookmark(item)
            elif action == delete_action:
                self.delete_bookmark(item)
    def edit_bookmark(self, item):
        bookmark_id = item.data(0, Qt.UserRole)

        values = (item.text(0), item.text(1), item.text(2), item.text(3), item.text(4))

        dialog = BookmarkDialog(self, values)

        if dialog.exec():
            title, url, category, tags, notes = dialog.get_values()

            try:
                self.cursor.execute(

                    "UPDATE bookmarks SET title=?, url=?, category=?, tags=?, notes=? WHERE id=?",

                    (title, url, category, tags, notes, bookmark_id)
                )

                self.conn.commit()

                self.load_bookmarks()
            except sqlite3.Error as e:
                QMessageBox.critical(self, "Database Error", f"Error updating bookmark: {str(e)}")
    def delete_bookmark(self, item):
        reply = QMessageBox.question(self, "Confirm Delete", 

                                   "Are you sure you want to delete this bookmark?",

                                   QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            bookmark_id = item.data(0, Qt.UserRole)

            try:
                self.cursor.execute("DELETE FROM bookmarks WHERE id=?", (bookmark_id,))

                self.conn.commit()

                self.load_bookmarks()
            except sqlite3.Error as e:
                QMessageBox.critical(self, "Database Error", f"Error deleting bookmark: {str(e)}")
    def search_bookmarks(self, text):
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)

            show = False

            for j in range(item.columnCount()):
                if text.lower() in item.text(j).lower():
                    show = True

                    break
            item.setHidden(not show)
    def add_new_tag(self):
        """Añade un nuevo tag al sistema"""

        try:
            tag, ok = QInputDialog.getText(

                self,

                "Add New Tag",

                "Enter new tag name:",

                QLineEdit.Normal
            )

            if ok and tag:
                tag = tag.strip()

                if tag:
                    # Verificar si el tag ya existe

                    self.cursor.execute("SELECT DISTINCT tags FROM bookmarks WHERE tags IS NOT NULL AND tags != ''")

                    existing_tags = set()

                    for row in self.cursor.fetchall():
                        if row[0]:
                            existing_tags.update(tag.strip() for tag in row[0].split(','))
                    if tag in existing_tags:
                        QMessageBox.warning(self, "Warning", f"Tag '{tag}' already exists!")

                        return
                    # Añadir el tag al filtro

                    self.tag_filter.addItem(tag, tag)

                    self.tag_filter.setCurrentText(tag)

                    # Actualizar la base de datos si es necesario

                    # (Aquí podrías añadir una tabla específica para tags si lo prefieres)

                    QMessageBox.information(self, "Success", f"Tag '{tag}' added successfully!")
        except sqlite3.Error as e:
            QMessageBox.critical(self, "Database Error", f"Error adding new tag: {str(e)}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Unexpected error: {str(e)}")
    def get_favorites_for_bar(self):
        """Devuelve una lista de favoritos marcados para mostrar en la barra de favoritos"""

        favs = []

        try:
            self.cursor.execute("SELECT title, url, notes, tags FROM bookmarks WHERE notes LIKE '%[barra]%' OR tags LIKE '%[barra]%' OR category LIKE '%Barra%' OR tags LIKE '%barra%' OR notes LIKE '%barra%'")

            for row in self.cursor.fetchall():
                title, url, notes, tags = row

                # Obtener favicon

                icon = self.get_favicon(url)

                favs.append({

                    'url': url,

                    'title': title,

                    'icon': icon
                })
        except Exception as e:
            print(f"Error getting favorites for bar: {str(e)}")
        return favs
    # ─── Métodos de carpetas (integración con FoldersManager) ─────────────────

    def add_bookmark_to_folder(self, url: str, title: str, folder_id: int = 1) -> bool:
        """
        Guarda un marcador en una carpeta específica del sistema jerárquico.

        Args:
            url: URL del sitio.
            title: Título del marcador.
            folder_id: ID de la carpeta destino (por defecto la raíz, id=1).
        Returns:
            True si se guardó correctamente.
        """
        if not url or not title:
            self.logger.error("add_bookmark_to_folder: URL y título son obligatorios")
            return False
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            conn = sqlite3.connect("bookmarks.db")
            cursor = conn.cursor()

            cursor.execute(
                "SELECT COALESCE(MAX(position), 0) FROM bookmarks WHERE folder_id = ?",
                (folder_id,),
            )
            next_pos = (cursor.fetchone()[0] or 0) + 1

            cursor.execute(
                """INSERT INTO bookmarks (title, url, category, notes, tags, folder_id, position)
                   VALUES (?, ?, '', '', '', ?, ?)""",
                (title, url, folder_id, next_pos),
            )
            conn.commit()
            conn.close()
            self.load_bookmarks()
            self.logger.info("Marcador '%s' añadido a carpeta %d", title, folder_id)
            return True
        except sqlite3.Error as e:
            self.logger.error("Error en add_bookmark_to_folder: %s", e)
            return False
    def move_bookmark_to_folder(self, bookmark_id: int, new_folder_id: int) -> bool:
        """Mueve un marcador existente a otra carpeta."""
        try:
            conn = sqlite3.connect("bookmarks.db")
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE bookmarks SET folder_id = ? WHERE id = ?",
                (new_folder_id, bookmark_id),
            )
            conn.commit()
            conn.close()
            self.load_bookmarks()
            self.logger.info("Marcador %d movido a carpeta %d", bookmark_id, new_folder_id)
            return True
        except sqlite3.Error as e:
            self.logger.error("Error moviendo marcador: %s", e)
            return False
    def get_bookmarks_by_folder(self, folder_id: int = 1) -> list:
        """Devuelve todos los marcadores de una carpeta ordenados por posición."""
        try:
            conn = sqlite3.connect("bookmarks.db")
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, url, title, position FROM bookmarks "
                "WHERE folder_id = ? ORDER BY position ASC",
                (folder_id,),
            )
            rows = cursor.fetchall()
            conn.close()
            return [{"id": r[0], "url": r[1], "title": r[2], "position": r[3]} for r in rows]
        except sqlite3.Error as e:
            self.logger.error("Error obteniendo marcadores de carpeta %d: %s", folder_id, e)
            return []
    def delete_bookmark_by_id(self, bookmark_id: int) -> bool:
        """Elimina un marcador por su ID numérico."""
        try:
            conn = sqlite3.connect("bookmarks.db")
            cursor = conn.cursor()
            cursor.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
            conn.commit()
            conn.close()
            self.load_bookmarks()
            return True
        except sqlite3.Error as e:
            self.logger.error("Error eliminando marcador %d: %s", bookmark_id, e)
            return False
    def search_bookmarks_text(self, query: str) -> list:
        """Busca marcadores por título o URL (sin importar carpeta)."""
        like = f"%{query}%"
        try:
            conn = sqlite3.connect("bookmarks.db")
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, url, title, folder_id FROM bookmarks "
                "WHERE title LIKE ? OR url LIKE ? ORDER BY title ASC",
                (like, like),
            )
            rows = cursor.fetchall()
            conn.close()
            return [{"id": r[0], "url": r[1], "title": r[2], "folder_id": r[3]} for r in rows]
        except sqlite3.Error as e:
            self.logger.error("Error buscando marcadores: %s", e)
            return []
    def export_bookmarks_html(self, output_path: str, folders_manager) -> bool:
        """
        Exporta todos los marcadores a un archivo HTML compatible con Firefox/Chrome.

        Args:
            output_path: Ruta del archivo HTML de salida.
            folders_manager: Instancia de FoldersManager para obtener la jerarquía.
        """
        try:
            hierarchy = folders_manager.get_hierarchy()
            html = self._render_html(hierarchy)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(html)
            self.logger.info("Marcadores exportados a %s", output_path)
            return True
        except Exception as e:
            self.logger.error("Error exportando marcadores: %s", e)
            return False
    def _render_html(self, folder: dict, level: int = 0) -> str:
        """Genera el HTML de una carpeta y sus contenidos (recursivo)."""
        if level == 0:
            html = (
                "<!DOCTYPE NETSCAPE-Bookmark-file-1>\n"
                "<META HTTP-EQUIV=\"Content-Type\" CONTENT=\"text/html; charset=UTF-8\">\n"
                "<TITLE>Bookmarks</TITLE>\n<H1>Bookmarks</H1>\n<DL><p>\n"
            )
        else:
            html = ""
        indent = "    " * level
        for sub in folder.get("children_folders", []):
            html += f"{indent}<DT><H3>{sub['name']}</H3>\n{indent}<DL><p>\n"
            html += self._render_html(sub, level + 1)
            html += f"{indent}</DL><p>\n"
        for bm in folder.get("children_bookmarks", []):
            html += f"{indent}<DT><A HREF=\"{bm['url']}\">{bm['title']}</A>\n"
        if level == 0:
            html += "</DL><p>\n</html>"
        return html
