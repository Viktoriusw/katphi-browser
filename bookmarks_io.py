#!/usr/bin/env python3
"""
bookmarks_io.py — Importación y exportación de marcadores en formato HTML
"Netscape Bookmark File", el que generan Firefox, Chrome, Edge, Brave, Opera,
Vivaldi y Safari al exportar marcadores.

Proporciona:
  - parse_bookmarks_html : lee un archivo HTML y devuelve un árbol de carpetas
  - import_bookmarks     : vuelca ese árbol en bookmarks.db (una transacción)
  - export_bookmarks_html: escribe bookmarks.db en un HTML importable por
                           cualquier navegador
"""

from __future__ import annotations

from i18n import tr
import html
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from typing import Dict, List, Optional, Set
from urllib.parse import urlparse

import logging

logger = logging.getLogger(__name__)

ROOT_ID = 1
MAX_FILE_BYTES = 64 * 1024 * 1024   # Firefox incrusta los favicons en base64
MAX_TITLE_LEN = 500
# Solo se importan direcciones navegables. Se descartan place: (consultas de
# Firefox), javascript: (bookmarklets), data:, about:, chrome:, etc.
ALLOWED_SCHEMES = ("http", "https", "ftp", "file")


# ─── Modelo ───────────────────────────────────────────────────────────────────

@dataclass
class ParsedBookmark:
    title: str
    url: str
    add_date: Optional[int] = None


@dataclass
class ParsedFolder:
    name: str
    add_date: Optional[int] = None
    toolbar: bool = False
    folders: List["ParsedFolder"] = field(default_factory=list)
    bookmarks: List[ParsedBookmark] = field(default_factory=list)

    def count_bookmarks(self) -> int:
        return len(self.bookmarks) + sum(f.count_bookmarks() for f in self.folders)


@dataclass
class ImportResult:
    imported: int = 0
    folders_created: int = 0
    duplicates: int = 0
    unsupported: int = 0
    target_folder_id: Optional[int] = None


# ─── Parser ───────────────────────────────────────────────────────────────────

def _int_or_none(value) -> Optional[int]:
    try:
        n = int(value)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


class _NetscapeParser(HTMLParser):
    """
    Recorre la estructura  <DT><H3>Carpeta</H3> <DL><p> … </DL>  y
    <DT><A HREF=…>Título</A>.  Los <DT>/<p> sin cerrar del formato no
    importan: solo se miran H3, A y DL.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = ParsedFolder(name="")
        self.unsupported = 0
        self._stack: List[ParsedFolder] = []
        self._pending_folder: Optional[ParsedFolder] = None
        self._in_h1 = False
        self._h3: Optional[ParsedFolder] = None
        self._a: Optional[dict] = None
        self._text: List[str] = []
        self._root_opened = False

    @property
    def _current(self) -> ParsedFolder:
        return self._stack[-1] if self._stack else self.root

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "h1":
            self._in_h1, self._text = True, []
        elif tag == "h3":
            self._h3 = ParsedFolder(
                name="",
                add_date=_int_or_none(a.get("add_date")),
                toolbar=a.get("personal_toolbar_folder", "").lower() == "true",
            )
            self._text = []
        elif tag == "a":
            self._a = a
            self._text = []
        elif tag == "dl":
            if self._pending_folder is not None:
                self._stack.append(self._pending_folder)
                self._pending_folder = None
            elif not self._root_opened:
                # Primer <DL>: el contenedor raíz del archivo
                self._root_opened = True
            else:
                # <DL> sin <H3> delante (archivo raro): se aplana en el actual
                self._stack.append(self._current)

    def handle_endtag(self, tag):
        if tag == "h1" and self._in_h1:
            self._in_h1 = False
            self.root.name = "".join(self._text).strip()
        elif tag == "h3" and self._h3 is not None:
            folder = self._h3
            folder.name = " ".join("".join(self._text).split()) or tr("Carpeta")
            self._current.folders.append(folder)
            self._pending_folder = folder
            self._h3 = None
        elif tag == "a" and self._a is not None:
            self._add_bookmark(self._a, "".join(self._text))
            self._a = None
        elif tag == "dl":
            if self._stack:
                self._stack.pop()

    def handle_data(self, data):
        if self._in_h1 or self._h3 is not None or self._a is not None:
            self._text.append(data)

    def _add_bookmark(self, attrs: dict, text: str):
        url = attrs.get("href", "").strip()
        if not url:
            return
        scheme = urlparse(url).scheme.lower()
        if scheme not in ALLOWED_SCHEMES:
            self.unsupported += 1
            return
        title = " ".join(text.split())
        if not title:
            title = urlparse(url).netloc or url
        self._current.bookmarks.append(
            ParsedBookmark(
                title=title[:MAX_TITLE_LEN],
                url=url,
                add_date=_int_or_none(attrs.get("add_date")),
            )
        )


def parse_bookmarks_html(path: str) -> tuple[ParsedFolder, int]:
    """
    Lee un archivo de marcadores HTML.

    Returns:
        (raíz, descartados): árbol de carpetas y nº de entradas con esquema
        no soportado (place:, javascript:…).
    Raises:
        ValueError si el archivo no parece un archivo de marcadores.
    """
    import os
    if os.path.getsize(path) > MAX_FILE_BYTES:
        raise ValueError(tr("El archivo es demasiado grande (máx. 64 MB)."))
    with open(path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8-sig", errors="replace")
    head = text[:4096].lower()
    if "netscape-bookmark-file" not in head and "<dl" not in text[:200000].lower():
        raise ValueError(tr("El archivo no tiene formato de marcadores HTML."))
    parser = _NetscapeParser()
    parser.feed(text)
    parser.close()
    return parser.root, parser.unsupported


# ─── Importación ──────────────────────────────────────────────────────────────

def _ts_to_db(ts: Optional[int]) -> Optional[str]:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return None


def _prune(folder: ParsedFolder, existing_urls: Set[str], result: ImportResult) -> bool:
    """
    Quita los marcadores duplicados (ya guardados o repetidos en el archivo) y
    las carpetas que se queden vacías.  Devuelve True si queda algo.
    """
    kept = []
    for bm in folder.bookmarks:
        if bm.url in existing_urls:
            result.duplicates += 1
            continue
        existing_urls.add(bm.url)
        kept.append(bm)
    folder.bookmarks = kept
    folder.folders = [f for f in folder.folders if _prune(f, existing_urls, result)]
    return bool(folder.bookmarks or folder.folders)


def import_bookmarks(
    db_path: str,
    root: ParsedFolder,
    parent_id: int = ROOT_ID,
    container_name: Optional[str] = None,
    skip_duplicates: bool = True,
) -> ImportResult:
    """
    Inserta el árbol *root* en la BD dentro de *parent_id*.

    Si *container_name* se indica, todo se mete en una carpeta nueva con ese
    nombre.  Las subcarpetas con el mismo nombre que una existente en el mismo
    nivel se fusionan, así que reimportar el mismo archivo no duplica nada.
    """
    result = ImportResult()
    conn = sqlite3.connect(db_path)
    try:
        if skip_duplicates:
            existing = {r[0] for r in conn.execute("SELECT url FROM bookmarks")}
            _prune(root, existing, result)
        if not root.bookmarks and not root.folders:
            result.target_folder_id = parent_id
            return result

        def next_pos(table: str, col: str, pid: int) -> int:
            row = conn.execute(
                f"SELECT COALESCE(MAX(position), 0) FROM {table} WHERE {col} = ?", (pid,)
            ).fetchone()
            return (row[0] or 0) + 1

        created_ids: Set[int] = set()

        def folder_id_for(name: str, pid: int, add_date: Optional[int], merge: bool) -> int:
            if merge:
                # Solo se fusiona con carpetas que ya existían antes de importar:
                # dos carpetas homónimas del propio archivo se mantienen separadas.
                for (fid,) in conn.execute(
                    "SELECT id FROM bookmark_folders WHERE name = ? AND parent_id = ? "
                    "ORDER BY id",
                    (name, pid),
                ):
                    if fid not in created_ids:
                        return fid
            cur = conn.execute(
                "INSERT INTO bookmark_folders (name, parent_id, position, created_at) "
                "VALUES (?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))",
                (name, pid, next_pos("bookmark_folders", "parent_id", pid), _ts_to_db(add_date)),
            )
            result.folders_created += 1
            created_ids.add(cur.lastrowid)
            return cur.lastrowid

        def insert(folder: ParsedFolder, fid: int):
            for sub in folder.folders:
                insert(sub, folder_id_for(sub.name, fid, sub.add_date, merge=True))
            pos = next_pos("bookmarks", "folder_id", fid)
            for bm in folder.bookmarks:
                conn.execute(
                    "INSERT INTO bookmarks (title, url, category, notes, tags, folder_id, "
                    "position, date_added) VALUES (?, ?, '', '', '', ?, ?, "
                    "COALESCE(?, CURRENT_TIMESTAMP))",
                    (bm.title, bm.url, fid, pos, _ts_to_db(bm.add_date)),
                )
                pos += 1
                result.imported += 1

        with conn:
            target = parent_id
            if container_name:
                target = folder_id_for(container_name, parent_id, None, merge=False)
            insert(root, target)
            result.target_folder_id = target
        logger.info(
            tr("Marcadores importados: %d nuevos, %d carpetas, %d duplicados"),
            result.imported, result.folders_created, result.duplicates,
        )
        return result
    finally:
        conn.close()


# ─── Exportación ──────────────────────────────────────────────────────────────

def _db_to_ts(value) -> Optional[int]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return int(datetime.strptime(str(value), fmt).timestamp())
        except ValueError:
            continue
    return None


def export_bookmarks_html(db_path: str, output_path: str) -> int:
    """
    Exporta todos los marcadores de *db_path* a *output_path*.

    Returns:
        Número de marcadores exportados.
    """
    conn = sqlite3.connect(db_path)
    try:
        folder_cols = {r[1] for r in conn.execute("PRAGMA table_info(bookmark_folders)")}
        created = "created_at" if "created_at" in folder_cols else "NULL"
        folders = conn.execute(
            f"SELECT id, name, parent_id, {created} FROM bookmark_folders "
            "ORDER BY position, id"
        ).fetchall()
        bookmarks = conn.execute(
            "SELECT title, url, folder_id, date_added FROM bookmarks ORDER BY position, id"
        ).fetchall()
    finally:
        conn.close()

    children: Dict[Optional[int], list] = {}
    for fid, name, pid, cdate in folders:
        if fid != ROOT_ID:
            children.setdefault(pid, []).append((fid, name, cdate))
    by_folder: Dict[int, list] = {}
    known = {f[0] for f in folders}
    for title, url, fid, ddate in bookmarks:
        # Marcadores de carpetas borradas: a la raíz, para no perderlos
        by_folder.setdefault(fid if fid in known else ROOT_ID, []).append((title, url, ddate))

    esc = lambda s: html.escape(str(s or ""), quote=True)
    date_attr = lambda v: f' ADD_DATE="{_db_to_ts(v)}"' if _db_to_ts(v) else ""
    lines = [
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
        "<!-- This is an automatically generated file.",
        "     It will be read and overwritten.",
        "     DO NOT EDIT! -->",
        '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
        "<TITLE>Bookmarks</TITLE>",
        tr("<H1>Marcadores de Katphi</H1>"),
        "",
        "<DL><p>",
    ]
    count = 0
    visited: Set[int] = set()

    def render(fid: int, level: int):
        nonlocal count
        if fid in visited:      # protección ante ciclos en parent_id
            return
        visited.add(fid)
        pad = "    " * level
        for sub_id, name, cdate in children.get(fid, []):
            lines.append(f"{pad}<DT><H3{date_attr(cdate)}>{esc(name)}</H3>")
            lines.append(f"{pad}<DL><p>")
            render(sub_id, level + 1)
            lines.append(f"{pad}</DL><p>")
        for title, url, ddate in by_folder.get(fid, []):
            lines.append(f'{pad}<DT><A HREF="{esc(url)}"{date_attr(ddate)}>{esc(title)}</A>')
            count += 1

    render(ROOT_ID, 1)
    lines.append("</DL><p>")
    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    logger.info(tr("Exportados %d marcadores a %s"), count, output_path)
    return count
