"""Tests de importación/exportación de marcadores HTML (bookmarks_io.py)."""
import sqlite3

import pytest

import bookmarks_io
from folders_manager import BookmarksMigration, FoldersManager

FIREFOX_HTML = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<!-- This is an automatically generated file. -->
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Menú Marcadores</H1>

<DL><p>
    <DT><H3 ADD_DATE="1511739920">Mozilla Firefox</H3>
    <DL><p>
        <DT><A HREF="https://support.mozilla.org/" ADD_DATE="1662900232" ICON="data:image/png;base64,AAAA">Obtener ayuda</A>
    </DL><p>
    <DT><A HREF="place:type=6&amp;sort=14" ADD_DATE="1511739921">Recent Tags</A>
    <HR>
    <DT><H3 ADD_DATE="1775834967" PERSONAL_TOOLBAR_FOLDER="true">Barra de herramientas de marcadores</H3>
    <DL><p>
        <DT><H3>OSINT</H3>
        <DL><p>
            <DT><H3>Air &amp; Space Tracking</H3>
            <DL><p>
                <DT><A HREF="https://example.com/?a=1&amp;b=2">Vuelos &lt;live&gt;</A>
            </DL><p>
            <DT><H3>Vacía</H3>
            <DL><p>
            </DL><p>
        </DL><p>
        <DT><H3>IA</H3>
        <DL><p>
            <DT><A HREF="https://chat.qwen.ai/">Qwen</A>
        </DL><p>
        <DT><H3>IA</H3>
        <DL><p>
            <DT><A HREF="https://claude.ai/">Claude</A>
        </DL><p>
        <DT><A HREF="https://www.reddit.com/"></A>
        <DT><A HREF="javascript:alert(1)">Bookmarklet</A>
        <DT><A HREF="https://support.mozilla.org/">Ayuda repetida</A>
    </DL><p>
</DL>
"""


@pytest.fixture
def html_file(tmp_path):
    p = tmp_path / "bookmarks.html"
    p.write_text(FIREFOX_HTML, encoding="utf-8")
    return str(p)


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "bookmarks.db")
    BookmarksMigration(path).migrate()
    return path


def _rows(db, sql, args=()):
    with sqlite3.connect(db) as c:
        return c.execute(sql, args).fetchall()


def test_parse_structure(html_file):
    root, unsupported = bookmarks_io.parse_bookmarks_html(html_file)
    assert root.name == "Menú Marcadores"
    assert unsupported == 2                  # place: y javascript:
    names = [f.name for f in root.folders]
    assert names == ["Mozilla Firefox", "Barra de herramientas de marcadores"]
    toolbar = root.folders[1]
    assert toolbar.toolbar is True
    assert [f.name for f in toolbar.folders] == ["OSINT", "IA", "IA"]
    air = toolbar.folders[0].folders[0]
    assert air.name == "Air & Space Tracking"
    assert air.bookmarks[0].url == "https://example.com/?a=1&b=2"
    assert air.bookmarks[0].title == "Vuelos <live>"
    # Título vacío → dominio
    assert toolbar.bookmarks[0].title == "www.reddit.com"
    assert root.folders[0].bookmarks[0].add_date == 1662900232
    assert root.count_bookmarks() == 6


def test_rejects_non_bookmark_file(tmp_path):
    p = tmp_path / "x.html"
    p.write_text("<html><body>hola</body></html>", encoding="utf-8")
    with pytest.raises(ValueError):
        bookmarks_io.parse_bookmarks_html(str(p))


def test_import_into_new_container(db, html_file):
    root, _ = bookmarks_io.parse_bookmarks_html(html_file)
    res = bookmarks_io.import_bookmarks(db, root, container_name="Importados")
    # La ayuda repetida dentro del archivo se omite
    assert res.imported == 5
    assert res.duplicates == 1
    fm = FoldersManager(db)
    top = [f.name for f in fm.get_children(1)]
    assert top == ["Importados"]
    container = fm.get_children(1)[0]
    assert res.target_folder_id == container.id
    sub = [f.name for f in fm.get_children(container.id)]
    assert sub == ["Mozilla Firefox", "Barra de herramientas de marcadores"]
    toolbar = fm.get_children(container.id)[1]
    # Las dos carpetas «IA» del archivo siguen separadas; «Vacía» no se crea
    assert [f.name for f in fm.get_children(toolbar.id)] == ["OSINT", "IA", "IA"]
    osint = fm.get_children(toolbar.id)[0]
    assert [f.name for f in fm.get_children(osint.id)] == ["Air & Space Tracking"]
    dates = _rows(db, "SELECT date_added FROM bookmarks WHERE url = ?",
                  ("https://support.mozilla.org/",))
    assert dates[0][0].startswith("2022-09-")


def test_reimport_adds_nothing(db, html_file):
    root, _ = bookmarks_io.parse_bookmarks_html(html_file)
    bookmarks_io.import_bookmarks(db, root, container_name="Importados")
    folders_before = _rows(db, "SELECT COUNT(*) FROM bookmark_folders")[0][0]
    root, _ = bookmarks_io.parse_bookmarks_html(html_file)
    res = bookmarks_io.import_bookmarks(db, root, container_name="Importados")
    assert res.imported == 0 and res.folders_created == 0
    assert res.duplicates == 6
    assert _rows(db, "SELECT COUNT(*) FROM bookmark_folders")[0][0] == folders_before


def test_import_merges_with_existing_folder(db, html_file):
    fm = FoldersManager(db)
    existing = fm.create_folder("Mozilla Firefox", 1)
    root, _ = bookmarks_io.parse_bookmarks_html(html_file)
    bookmarks_io.import_bookmarks(db, root, parent_id=1)
    names = [f.name for f in fm.get_children(1)]
    assert names.count("Mozilla Firefox") == 1
    assert _rows(db, "SELECT folder_id FROM bookmarks WHERE title = 'Obtener ayuda'")[0][0] == existing


def test_import_without_dedupe_keeps_everything(db, html_file):
    root, _ = bookmarks_io.parse_bookmarks_html(html_file)
    res = bookmarks_io.import_bookmarks(db, root, skip_duplicates=False)
    assert res.imported == 6


def test_export_roundtrip(db, html_file, tmp_path):
    root, _ = bookmarks_io.parse_bookmarks_html(html_file)
    bookmarks_io.import_bookmarks(db, root, container_name="Importados")
    out = str(tmp_path / "out.html")
    assert bookmarks_io.export_bookmarks_html(db, out) == 5
    text = open(out, encoding="utf-8").read()
    assert "Air &amp; Space Tracking" in text
    assert "Vuelos &lt;live&gt;" in text
    assert 'HREF="https://example.com/?a=1&amp;b=2"' in text
    assert 'ADD_DATE="1662900232"' in text

    root2, unsupported = bookmarks_io.parse_bookmarks_html(out)
    assert unsupported == 0
    assert root2.count_bookmarks() == 5
    assert [f.name for f in root2.folders] == ["Importados"]
    titles = []

    def walk(f):
        titles.extend(b.title for b in f.bookmarks)
        for s in f.folders:
            walk(s)
    walk(root2)
    assert "Vuelos <live>" in titles


def test_panel_has_import_export_buttons(db, monkeypatch):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from bookmark_panel_ui import BookmarkPanelWidget
    panel = BookmarkPanelWidget(bookmark_manager=None, folders_manager=FoldersManager(db))
    assert panel._import_btn.toolTip().startswith("Importar")
    assert panel._export_btn.toolTip().startswith("Exportar")
    assert panel._import_btn.text() == "" and panel._export_btn.text() == ""
    assert not panel._import_btn.icon().isNull()
    panel.deleteLater()
    app.processEvents()
