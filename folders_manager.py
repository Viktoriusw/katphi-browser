#!/usr/bin/env python3
"""
folders_manager.py — Gestor jerárquico de carpetas para marcadores.

Proporciona:
- BookmarksMigration : migra bookmarks.db de estructura plana a jerárquica
- FolderInfo         : dataclass con la información de una carpeta
- FoldersManager     : CRUD completo de carpetas + consultas de jerarquía
"""

from __future__ import annotations

import shutil
import sqlite3
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

DB_PATH = "bookmarks.db"

# ─── Migración ────────────────────────────────────────────────────────────────

class BookmarksMigration:
    """
    Migra bookmarks.db de una estructura plana (tabla 'bookmarks' con campo
    'category' de texto) a una estructura jerárquica con la tabla
    'bookmark_folders' y los campos 'folder_id' / 'position' en bookmarks.

    Es seguro ejecutarla más de una vez: detecta qué ya existe y solo añade
    lo que falta.
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.backup_path = f"{db_path}.backup"
    # ── API pública ────────────────────────────────────────────────────────────

    def backup(self) -> bool:
        try:
            shutil.copy2(self.db_path, self.backup_path)
            logger.info("Backup creado: %s", self.backup_path)
            return True
        except OSError as e:
            logger.error("Error creando backup: %s", e)
            return False
    def restore(self) -> bool:
        try:
            shutil.copy2(self.backup_path, self.db_path)
            logger.info("Backup restaurado")
            return True
        except OSError as e:
            logger.error("Error restaurando backup: %s", e)
            return False
    def migrate(self) -> bool:
        """
        Ejecuta la migración completa.
        Si la BD no existe aún, la crea con la estructura nueva desde cero.
        Retorna True si la migración fue exitosa.
        """
        import os
        if not os.path.exists(self.db_path):
            logger.info("bookmarks.db no existe — creando BD nueva")
            self._create_new_database()
            return True
        self.backup()
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA foreign_keys = OFF")
            try:
                self._ensure_folders_table(conn)
                self._ensure_bookmark_columns(conn)
                self._migrate_categories_to_folders(conn)
                conn.commit()
                logger.info("Migración completada exitosamente")
                return True
            except Exception as e:
                conn.rollback()
                logger.error("Error durante migración: %s — restaurando backup", e)
                self.restore()
                return False
            finally:
                conn.close()
        except sqlite3.Error as e:
            logger.error("No se pudo conectar a la BD: %s", e)
            return False
    # ── Privados ───────────────────────────────────────────────────────────────

    def _create_new_database(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS bookmark_folders (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT    NOT NULL,
                parent_id  INTEGER,
                position   INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (parent_id) REFERENCES bookmark_folders(id)
            );

            INSERT OR IGNORE INTO bookmark_folders (id, name, parent_id)
            VALUES (1, 'Marcadores', NULL);

            CREATE TABLE IF NOT EXISTS categories (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bookmarks (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT    NOT NULL,
                url        TEXT    NOT NULL,
                category   TEXT    DEFAULT '',
                notes      TEXT    DEFAULT '',
                tags       TEXT    DEFAULT '',
                folder_id  INTEGER DEFAULT 1,
                position   INTEGER DEFAULT 0,
                date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (folder_id) REFERENCES bookmark_folders(id)
            );
        """)
        conn.commit()
        conn.close()
        logger.info("Nueva BD creada: %s", self.db_path)
    def _ensure_folders_table(self, conn: sqlite3.Connection):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bookmark_folders (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT    NOT NULL,
                parent_id  INTEGER,
                position   INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (parent_id) REFERENCES bookmark_folders(id)
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO bookmark_folders (id, name, parent_id)
            VALUES (1, 'Marcadores', NULL)
        """)
    def _ensure_bookmark_columns(self, conn: sqlite3.Connection):
        cur = conn.execute("PRAGMA table_info(bookmarks)")
        existing = {row[1] for row in cur.fetchall()}
        if "folder_id" not in existing:
            conn.execute("ALTER TABLE bookmarks ADD COLUMN folder_id INTEGER DEFAULT 1")
            logger.info("  + columna folder_id añadida a bookmarks")
        if "position" not in existing:
            conn.execute("ALTER TABLE bookmarks ADD COLUMN position INTEGER DEFAULT 0")
            logger.info("  + columna position añadida a bookmarks")
        if "date_added" not in existing:
            # SQLite no permite DEFAULT CURRENT_TIMESTAMP en ALTER TABLE
            # (solo se puede usar en CREATE TABLE), así que usamos DEFAULT NULL
            conn.execute(
                "ALTER TABLE bookmarks ADD COLUMN date_added TEXT DEFAULT NULL"
            )
    def _migrate_categories_to_folders(self, conn: sqlite3.Connection):
        """
        Crea una subcarpeta en bookmark_folders por cada categoría de texto
        que no tenga ya su carpeta equivalente, y mueve los marcadores de
        esa categoría a la carpeta correspondiente.
        """
        cur = conn.execute("SELECT name FROM categories ORDER BY name")
        categories = [row[0] for row in cur.fetchall()]

        for cat_name in categories:
            if not cat_name or cat_name.strip() == "":
                continue
            # ¿Ya existe una carpeta con ese nombre bajo la raíz?
            row = conn.execute(
                "SELECT id FROM bookmark_folders WHERE name = ? AND parent_id = 1",
                (cat_name,),
            ).fetchone()
            if row:
                folder_id = row[0]
            else:
                cur2 = conn.execute(
                    "INSERT INTO bookmark_folders (name, parent_id) VALUES (?, 1)",
                    (cat_name,),
                )
                folder_id = cur2.lastrowid
                logger.info("  Carpeta creada para categoría '%s' → id=%d", cat_name, folder_id)
            # Mover marcadores de esta categoría a la carpeta
            conn.execute(
                "UPDATE bookmarks SET folder_id = ? WHERE category = ? AND (folder_id IS NULL OR folder_id = 1)",
                (folder_id, cat_name),
            )


# ─── FolderInfo ───────────────────────────────────────────────────────────────

class FolderInfo:
    """Modelo de datos de una carpeta."""

    __slots__ = ("id", "name", "parent_id", "position")

    def __init__(self, id: int, name: str, parent_id: Optional[int], position: int = 0):
        self.id = id
        self.name = name
        self.parent_id = parent_id
        self.position = position
    def __repr__(self) -> str:
        return f"Folder(id={self.id}, name={self.name!r}, parent={self.parent_id})"
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "parent_id": self.parent_id,
            "position": self.position,
        }


# ─── FoldersManager ──────────────────────────────────────────────────────────

class FoldersManager:
    """
    Gestor CRUD de carpetas de marcadores sobre SQLite.

    Todas las operaciones abren y cierran su propia conexión para que sea
    seguro llamar desde cualquier hilo (aunque la actualización de UI debe
    hacerse en el hilo principal).
    """

    ROOT_ID = 1

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        # Asegurarse de que la BD tiene la estructura mínima
        self._bootstrap()
    # ── Bootstrap ─────────────────────────────────────────────────────────────

    def _bootstrap(self):
        """Crea la tabla y la carpeta raíz si no existen."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS bookmark_folders (
                        id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        name       TEXT    NOT NULL,
                        parent_id  INTEGER,
                        position   INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (parent_id) REFERENCES bookmark_folders(id)
                    );
                    INSERT OR IGNORE INTO bookmark_folders (id, name, parent_id)
                    VALUES (1, 'Marcadores', NULL);
                """)
        except sqlite3.Error as e:
            logger.error("FoldersManager bootstrap error: %s", e)
    # ── Conexión ──────────────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    # ── CRUD ──────────────────────────────────────────────────────────────────

    def create_folder(self, name: str, parent_id: Optional[int] = ROOT_ID) -> int:
        """
        Crea una carpeta nueva bajo *parent_id*.

        Returns:
            ID de la carpeta recién creada.
        Raises:
            ValueError si el nombre está vacío.
        """
        name = (name or "").strip()
        if not name:
            raise ValueError("El nombre de la carpeta no puede estar vacío")
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(position), 0) FROM bookmark_folders WHERE parent_id = ?",
                (parent_id,),
            ).fetchone()
            next_pos = (row[0] or 0) + 1

            cur = conn.execute(
                "INSERT INTO bookmark_folders (name, parent_id, position) VALUES (?, ?, ?)",
                (name, parent_id, next_pos),
            )
            folder_id = cur.lastrowid
            logger.info("Carpeta creada: %r (id=%d, parent=%s)", name, folder_id, parent_id)
            return folder_id
    def delete_folder(self, folder_id: int, recursive: bool = True) -> bool:
        """
        Elimina una carpeta.  Si *recursive=True*, borra también todos sus
        marcadores y subcarpetas de forma recursiva.
        No se puede eliminar la carpeta raíz (id=1).
        """
        if folder_id == self.ROOT_ID:
            logger.error("No se puede eliminar la carpeta raíz")
            return False
        try:
            with self._conn() as conn:
                if recursive:
                    descendants = self._all_descendants(conn, folder_id)
                    all_ids = [folder_id] + descendants

                    for fid in all_ids:
                        conn.execute("DELETE FROM bookmarks WHERE folder_id = ?", (fid,))
                    for fid in reversed(descendants):
                        conn.execute("DELETE FROM bookmark_folders WHERE id = ?", (fid,))
                conn.execute("DELETE FROM bookmark_folders WHERE id = ?", (folder_id,))
                logger.info("Carpeta %d eliminada (recursive=%s)", folder_id, recursive)
                return True
        except sqlite3.Error as e:
            logger.error("Error eliminando carpeta %d: %s", folder_id, e)
            return False
    def rename_folder(self, folder_id: int, new_name: str) -> bool:
        """Renombra una carpeta."""
        new_name = (new_name or "").strip()
        if not new_name:
            logger.error("El nombre no puede estar vacío")
            return False
        try:
            with self._conn() as conn:
                conn.execute(
                    "UPDATE bookmark_folders SET name = ? WHERE id = ?",
                    (new_name, folder_id),
                )
            logger.info("Carpeta %d renombrada a %r", folder_id, new_name)
            return True
        except sqlite3.Error as e:
            logger.error("Error renombrando carpeta %d: %s", folder_id, e)
            return False
    def move_folder(self, folder_id: int, new_parent_id: int) -> bool:
        """
        Mueve una carpeta a un nuevo padre.
        Previene moverla dentro de sí misma o de sus descendientes.
        """
        if folder_id == self.ROOT_ID:
            logger.error("No se puede mover la carpeta raíz")
            return False
        if folder_id == new_parent_id:
            logger.error("No se puede mover una carpeta dentro de sí misma")
            return False
        if self._is_descendant(folder_id, new_parent_id):
            logger.error("No se puede mover una carpeta dentro de su propia descendencia")
            return False
        try:
            with self._conn() as conn:
                conn.execute(
                    "UPDATE bookmark_folders SET parent_id = ? WHERE id = ?",
                    (new_parent_id, folder_id),
                )
            logger.info("Carpeta %d movida a padre %d", folder_id, new_parent_id)
            return True
        except sqlite3.Error as e:
            logger.error("Error moviendo carpeta: %s", e)
            return False
    # ── Consultas ─────────────────────────────────────────────────────────────

    def get_folder(self, folder_id: int) -> Optional[FolderInfo]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, name, parent_id, position FROM bookmark_folders WHERE id = ?",
                (folder_id,),
            ).fetchone()
        return FolderInfo(row["id"], row["name"], row["parent_id"], row["position"]) if row else None
    def get_children(self, parent_id: int = ROOT_ID) -> List[FolderInfo]:
        """Devuelve las subcarpetas directas de *parent_id*, ordenadas por posición."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, name, parent_id, position FROM bookmark_folders "
                "WHERE parent_id = ? ORDER BY position ASC",
                (parent_id,),
            ).fetchall()
        return [FolderInfo(r["id"], r["name"], r["parent_id"], r["position"]) for r in rows]
    def get_all_folders_flat(self) -> List[FolderInfo]:
        """Devuelve todas las carpetas en una lista plana ordenada por id."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, name, parent_id, position FROM bookmark_folders ORDER BY id"
            ).fetchall()
        return [FolderInfo(r["id"], r["name"], r["parent_id"], r["position"]) for r in rows]
    def get_hierarchy(self, parent_id: int = ROOT_ID) -> Dict:
        """
        Devuelve la estructura jerárquica completa desde *parent_id* como
        un dict anidado listo para construir un QTreeWidget.

        Formato::
            {
                'id': 1,
                'name': 'Marcadores',
                'type': 'folder',
                'children_folders': [ <mismo formato>, … ],
                'children_bookmarks': [
                    {'id':…, 'title':…, 'url':…, 'type':'bookmark'}, …
                ]
            }
        """
        folder = self.get_folder(parent_id)
        return {
            "id": parent_id,
            "name": folder.name if folder else "Marcadores",
            "type": "folder",
            "children_folders": [
                self.get_hierarchy(f.id) for f in self.get_children(parent_id)
            ],
            "children_bookmarks": self._bookmarks_in_folder(parent_id),
        }
    def get_breadcrumb(self, folder_id: int) -> List[FolderInfo]:
        """
        Devuelve la ruta desde la raíz hasta *folder_id*.
        Útil para mostrar «Marcadores › Trabajo › Python».
        """
        crumbs: List[FolderInfo] = []
        current_id: Optional[int] = folder_id
        while current_id:
            folder = self.get_folder(current_id)
            if not folder:
                break
            crumbs.insert(0, folder)
            current_id = folder.parent_id
        return crumbs
    def print_tree(self, parent_id: int = ROOT_ID, indent: int = 0) -> str:
        """Representación textual del árbol (útil para depuración)."""
        lines: List[str] = []
        folder = self.get_folder(parent_id)
        if folder:
            lines.append("  " * indent + f"{folder.name}")
        for child in self.get_children(parent_id):
            lines.append(self.print_tree(child.id, indent + 1))
        for bm in self._bookmarks_in_folder(parent_id):
            lines.append("  " * (indent + 1) + f"{bm['title']}")
        return "\n".join(lines)
    # ── Helpers privados ──────────────────────────────────────────────────────

    def _bookmarks_in_folder(self, folder_id: int) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, title, url, position FROM bookmarks "
                "WHERE folder_id = ? ORDER BY position ASC",
                (folder_id,),
            ).fetchall()
        return [
            {"id": r["id"], "title": r["title"], "url": r["url"],
             "position": r["position"], "type": "bookmark"}
            for r in rows
        ]
    def _all_descendants(self, conn: sqlite3.Connection, folder_id: int) -> List[int]:
        """Devuelve todos los IDs de subcarpetas (recursivo) usando la conexión dada."""
        result: List[int] = []
        rows = conn.execute(
            "SELECT id FROM bookmark_folders WHERE parent_id = ?", (folder_id,)
        ).fetchall()
        for row in rows:
            child_id = row[0]
            result.append(child_id)
            result.extend(self._all_descendants(conn, child_id))
        return result
    def _is_descendant(self, ancestor_id: int, potential_descendant: int) -> bool:
        """True si *potential_descendant* está en el subárbol de *ancestor_id*."""
        for child in self.get_children(ancestor_id):
            if child.id == potential_descendant:
                return True
            if self._is_descendant(child.id, potential_descendant):
                return True
        return False
