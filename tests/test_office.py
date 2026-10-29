"""Tests de Katphi Office: núcleo 3.6 (katphi-app://, file_handlers) y plugins
office_viewer (gratuito) y office_suite (premium, en premium-plugins/)."""
import base64
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIEWER_DIR = os.path.join(ROOT, "plugins", "office_viewer")
SUITE_DIR = os.path.join(os.path.dirname(ROOT), "premium-plugins", "office_suite")
for p in (os.path.join(ROOT, "tests"), VIEWER_DIR, SUITE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

if not os.path.isdir(VIEWER_DIR):
    # La copia pública no incluye plugins/*/ (vienen de la tienda o del build)
    pytest.skip("plugins/office_viewer no está en esta copia", allow_module_level=True)
HAS_SUITE = os.path.isdir(SUITE_DIR)
needs_suite = pytest.mark.skipif(not HAS_SUITE, reason="plugin premium office_suite no disponible")

from PySide6.QtWidgets import QApplication

import app_scheme
import file_handlers
import katphi_office  # noqa: F401  (añade _vendor a sys.path)
from katphi_office import capabilities, detect, documents, sheets, slides
from katphi_office.safety import UnsafeDocument
import office_samples as S


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def files(tmp_path):
    out = {}
    for kind, maker, name in [("xlsx", S.make_xlsx, "ventas.xlsx"), ("docx", S.make_docx, "informe.docx"),
                              ("pptx", S.make_pptx, "charla.pptx"), ("odt", S.make_odt, "nota.odt"),
                              ("ods", S.make_ods, "datos.ods"), ("pdf", S.make_pdf, "doc.pdf")]:
        p = str(tmp_path / name)
        maker(p)
        out[kind] = p
    csv_p = tmp_path / "datos.csv"
    csv_p.write_text("a;b;c\n1;2;3\n", encoding="utf-8")
    out["csv"] = str(csv_p)
    md_p = tmp_path / "leeme.md"
    md_p.write_text("# Título\n\nTexto **fuerte** y [web](https://katphi.com) y [x](javascript:alert(1))\n\n- uno\n- dos\n", encoding="utf-8")
    out["md"] = str(md_p)
    return out


# ---------------------------------------------------------------- detección y seguridad

def test_detect_by_content(files, tmp_path):
    assert detect.detect(files["xlsx"]).fmt == "xlsx"
    assert detect.detect(files["docx"]).family == "document"
    assert detect.detect(files["pptx"]).family == "slides"
    assert detect.detect(files["odt"]).fmt == "odt"
    assert detect.detect(files["ods"]).fmt == "ods"
    assert detect.detect(files["pdf"]).family == "pdf"
    assert detect.detect(files["csv"]).fmt == "csv"
    # Un .docx renombrado a .pdf se reconoce como documento
    renamed = tmp_path / "engaño.pdf"
    renamed.write_bytes(open(files["docx"], "rb").read())
    assert detect.detect(str(renamed)).fmt == "docx"
    # Un binario cualquiera con extensión .xlsx se rechaza
    fake = tmp_path / "virus.xlsx"
    fake.write_bytes(b"MZ\x90\x00" + os.urandom(200))
    with pytest.raises(UnsafeDocument):
        detect.detect(str(fake))
    ole = tmp_path / "viejo.doc"
    ole.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600)
    assert detect.detect(str(ole)).fmt == "doc"


def test_zip_bomb_and_traversal(tmp_path):
    bomb = tmp_path / "bomba.docx"
    S.make_zip_bomb(str(bomb))
    with pytest.raises(UnsafeDocument):
        documents.load(str(bomb), "docx")
    trav = tmp_path / "trav.docx"
    S.make_traversal_zip(str(trav))
    with pytest.raises(UnsafeDocument):
        documents.load(str(trav), "docx")


def test_xxe_is_rejected(tmp_path):
    p = tmp_path / "xxe.odt"
    S.make_xxe_odt(str(p))
    with pytest.raises(Exception) as exc:
        documents.load(str(p), "odt")
    assert "passwd" not in str(exc.value)


# ---------------------------------------------------------------- conversores

def test_xlsx_model(files):
    m = sheets.load(files["xlsx"], "xlsx")
    names = [s["name"] for s in m["sheets"]]
    assert names == ["Ventas", "Oculta", "Resumen"]
    ventas = m["sheets"][0]
    assert ventas["rows"][0][0] == {"v": "Producto", "t": "s",
                                    "s": {"b": 1, "c": "#ff0000", "bg": "#ffff00"}}
    assert ventas["rows"][1][3] == {"v": "7.5", "t": "n", "f": "=B2*C2"}
    assert ventas["rows"][2][0]["v"] == "Té <b>"            # texto, no HTML
    assert ventas["merges"] == [[4, 0, 4, 1]]
    assert m["sheets"][1]["hidden"] is True


def test_ods_repeated_cells_are_capped(files):
    m = sheets.load(files["ods"], "ods")
    rows = m["sheets"][0]["rows"]
    assert rows[0] == [{"v": "a", "t": "s"}, {"v": "5", "t": "n"}]
    assert len(rows) == 1                                   # el millón de filas vacías no cuenta


def test_csv_semicolon(files):
    rows = sheets.load(files["csv"], "csv")["sheets"][0]["rows"]
    assert [c["v"] for c in rows[1]] == ["1", "2", "3"]


def test_docx_html_is_escaped(files):
    h = documents.load(files["docx"], "docx")["html"]
    assert "<h1>Informe trimestral</h1>" in h
    assert "<strong>negrita</strong>" in h
    assert "&lt;script&gt;" in h and "<script" not in h
    assert "<ul><li>Primer punto</li><li>Segundo punto</li></ul>" in h
    assert "<ol><li>Paso uno</li></ol>" in h
    assert 'href="https://katphi.com"' in h and "javascript:" not in h
    assert "data:image/png;base64," in h
    assert '<table class="doc-table">' in h


def test_odt_md_txt(files, tmp_path):
    assert "<h2>Título ODT</h2>" in documents.load(files["odt"], "odt")["html"]
    md = documents.load(files["md"], "md")["html"]
    assert "<h1>Título</h1>" in md and "<strong>fuerte</strong>" in md
    assert 'href="https://katphi.com"' in md and "javascript" not in md.split("x")[-1] or "href=\"javascript" not in md
    txt = tmp_path / "a.txt"
    txt.write_text("<img src=x onerror=alert(1)>", encoding="utf-8")
    assert "&lt;img" in documents.load(str(txt), "txt")["html"]


def test_pptx_model(files):
    m = slides.load(files["pptx"], "pptx")
    assert len(m["slides"]) == 2
    assert m["slides"][0]["notes"] == "Notas del orador"
    texts = [r["t"] for s in m["slides"][1]["shapes"] if s["type"] == "text"
             for p in s["paragraphs"] for r in p["runs"]]
    assert texts == ["Caja <i>de texto</i>"]
    types = sorted(s["type"] for s in m["slides"][1]["shapes"])
    assert types == ["image", "table", "text"]


# ---------------------------------------------------------------- núcleo

def test_file_handlers_priority(tmp_path):
    opened = []
    file_handlers.register("visor", [".pdf", "docx"], ["application/pdf"],
                           lambda p: opened.append(("visor", p)) or True, "Visor", priority=10)
    file_handlers.register("editor", [".pdf"], [], lambda p: opened.append(("editor", p)) or True,
                           "Editor", priority=20)
    try:
        assert file_handlers.find("a.PDF").plugin_id == "editor"
        assert file_handlers.find("a.docx").plugin_id == "visor"
        assert file_handlers.find("descarga", "application/pdf").plugin_id == "visor"
        assert file_handlers.find("descarga", "application/octet-stream") is None
        f = tmp_path / "x.pdf"
        f.write_bytes(b"%PDF-1.4")
        assert file_handlers.open_path(str(f)) and opened[-1][0] == "editor"
        assert not file_handlers.open_path(str(tmp_path / "no-existe.pdf"))
    finally:
        file_handlers.unregister("visor")
        file_handlers.unregister("editor")


def test_app_scheme_static_is_confined(tmp_path):
    root = tmp_path / "web"
    root.mkdir()
    (root / "a.js").write_text("x")
    (tmp_path / "secreto.txt").write_text("no")
    st = app_scheme._AppSchemeHandler._static
    assert st(root.resolve(), "/a.js") == ("text/javascript", b"x")
    assert st(root.resolve(), "/../secreto.txt") is None
    assert st(root.resolve(), "/%2e%2e/secreto.txt") is None
    assert st(root.resolve(), "/no.js") is None


def test_auto_download_path(tmp_path, monkeypatch):
    from downloads import DownloadManager
    from PySide6.QtCore import QStandardPaths
    monkeypatch.setattr(QStandardPaths, "writableLocation", staticmethod(lambda loc: str(tmp_path)))
    (tmp_path / "a.pdf").write_text("x")
    p = DownloadManager._auto_download_path("a.pdf")
    assert p == str(tmp_path / "a (1).pdf")
    assert DownloadManager._auto_download_path("../../etc/passwd") == str(tmp_path / "passwd")


# ---------------------------------------------------------------- premium: PDF

@needs_suite
def test_parse_ranges():
    from katphi_office_suite.pdf_edit import parse_ranges
    assert parse_ranges("1-3,5", 6) == [0, 1, 2, 4]
    for bad in ("", "0", "4-2", "1-9", "a"):
        with pytest.raises(ValueError):
            parse_ranges(bad, 6)


def _session(path):
    from katphi_office.sessions import DocumentSession
    return DocumentSession(token="t", path=path, name=os.path.basename(path),
                           family="pdf", fmt="pdf", view_path=path)


@needs_suite
def test_pdf_page_ops(files, tmp_path, monkeypatch, qapp):
    from pypdf import PdfReader
    from katphi_office_suite import pdf_edit
    from katphi_office_suite import files as suite_files
    monkeypatch.setattr(suite_files, "backup_dir", lambda: tmp_path / "backups")
    monkeypatch.setattr(pdf_edit, "_reload", lambda s, p=None: None)
    s = _session(files["pdf"])
    pages = pdf_edit.PdfPages()
    assert pages.page_op(s, {"op": "rotate", "pages": [2], "angle": 90}, None) == {"ok": True}
    assert PdfReader(files["pdf"]).pages[1].rotation == 90
    assert len(list((tmp_path / "backups").iterdir())) == 1
    assert pages.page_op(s, {"op": "delete", "pages": [1]}, None) == {"ok": True}
    assert len(PdfReader(files["pdf"]).pages) == 1
    assert not pages.page_op(s, {"op": "delete", "pages": [1]}, None)["ok"]     # no todas
    assert not pages.page_op(s, {"op": "rotate", "pages": [7]}, None)["ok"]
    assert not pages.page_op(s, {"op": "rotate", "pages": ["1"]}, None)["ok"]
    out = tmp_path / "extracto.pdf"
    monkeypatch.setattr(pdf_edit, "_ask_pdf_path", lambda *a: str(out))
    assert pages.page_op(s, {"op": "extract", "ranges": "1"}, None)["ok"]
    assert len(PdfReader(str(out)).pages) == 1


@needs_suite
def test_pdf_save_rejects_non_pdf(files, tmp_path, monkeypatch, qapp):
    from katphi_office_suite import pdf_edit
    from katphi_office_suite import files as suite_files
    monkeypatch.setattr(suite_files, "backup_dir", lambda: tmp_path / "backups")
    monkeypatch.setattr(pdf_edit, "_reload", lambda s, p=None: None)
    s = _session(files["pdf"])
    assert not pdf_edit.PdfEditor().save(s, b"<html>", False, None)["ok"]
    new = open(files["pdf"], "rb").read().replace(b"Hola Katphi", b"Hola Editado")
    assert pdf_edit.PdfEditor().save(s, new, False, None)["ok"]
    assert b"Hola Editado" in open(files["pdf"], "rb").read()
    backups = list((tmp_path / "backups").iterdir())
    assert len(backups) == 1 and b"Hola Katphi" in backups[0].read_bytes()


# ---------------------------------------------------------------- de extremo a extremo

class FakeTabs:
    """Lo mínimo de TabManager que usa Katphi Office."""

    def __init__(self):
        from PySide6.QtWebEngineCore import QWebEngineProfile
        self.profile = QWebEngineProfile.defaultProfile()
        app_scheme.install_on_profile(self.profile)
        self.views = []
        self.titles = {}

    def add_app_tab(self, url, title, icon=None, on_close=None, display=None,
                    focus=True, before_load=None):
        from PySide6.QtCore import QUrl
        from PySide6.QtWebEngineCore import QWebEnginePage
        from PySide6.QtWebEngineWidgets import QWebEngineView
        view = QWebEngineView()
        view.setPage(QWebEnginePage(self.profile, view))
        view.resize(1100, 800)
        view.show()
        view._on_close = on_close
        if before_load:
            before_load(view)
        view.setUrl(QUrl(url))
        self.views.append(view)
        self.titles[id(view)] = title
        return view

    def set_app_tab_title(self, view, title, display=None):
        self.titles[id(view)] = title


class FakeWindow:
    def __init__(self):
        self.tab_manager = FakeTabs()


def _wait(ms):
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _js(view, code):
    out = []
    view.page().runJavaScript(code, 0, lambda r: out.append(r))
    for _ in range(100):
        if out:
            break
        _wait(50)
    return out[0] if out else None


def _until(fn, ms=15000):
    for _ in range(ms // 100):
        if fn():
            return True
        _wait(100)
    return fn()


@pytest.fixture
def office(qapp, tmp_path, monkeypatch):
    try:
        import PySide6.QtWebEngineWidgets  # noqa: F401
    except Exception:
        pytest.skip("Qt WebEngine no disponible")
    if not app_scheme.is_registered():
        pytest.skip("katphi-app no registrado antes de la QApplication")
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, str(tmp_path / "qs"))
    from katphi_office import app
    app.register_host()
    win = FakeWindow()
    yield app, win
    for cap in ("pdf_edit", "pdf_pages", "sheets_edit"):
        capabilities.unregister(cap)
    app.unregister_mount("suite")
    for v in win.tab_manager.views:
        v.close()


def _open(app, win, path):
    assert app.open_document(win, path)
    view = win.tab_manager.views[-1]
    ok = _until(lambda: _js(view, "document.body && document.body.dataset.ready") == "1", 20000)
    if not ok:
        state = _js(view, "document.body ? document.body.innerText.slice(0, 300) : ''")
        pytest.fail(f"El visor no terminó de cargar: {state!r}")
    return view


def test_e2e_document(office, files):
    app, win = office
    view = _open(app, win, files["docx"])
    assert _js(view, "document.querySelector('.doc-page h1').textContent") == "Informe trimestral"
    # El <script> del documento es texto, no se ejecutó ni se insertó como etiqueta
    assert _js(view, "document.querySelectorAll('.doc-page script').length") == 0
    assert _js(view, "document.querySelector('#doc-name').textContent") == "informe.docx"
    # Una web normal no puede leer katphi-app (el iniciador no es el host)
    assert win.tab_manager.titles[id(view)] == "informe.docx"


def test_e2e_sheets(office, files):
    app, win = office
    view = _open(app, win, files["xlsx"])
    tabs = json.loads(_js(view, "JSON.stringify(Array.from(document.querySelectorAll('.sheet-tabs button')).map(b => b.textContent))"))
    assert tabs == ["Ventas", "Resumen"]                       # la hoja oculta no aparece
    assert _js(view, "document.querySelector('td[data-r=\"1\"][data-c=\"3\"]').textContent") == "7.5"
    assert _js(view, "document.querySelector('td[data-r=\"4\"][data-c=\"0\"]').colSpan") == 2
    _js(view, "document.querySelector('td[data-r=\"1\"][data-c=\"3\"]').click(); 1")
    assert _js(view, "document.querySelector('.formula-bar .value').textContent") == "=B2*C2"


def test_e2e_slides(office, files):
    app, win = office
    view = _open(app, win, files["pptx"])
    assert _js(view, "document.querySelectorAll('.thumb').length") == 2
    assert _js(view, "document.querySelector('.notes').textContent") == "Notas del orador"
    _js(view, "document.querySelector('[title=\"Diapositiva siguiente\"]').click(); 1")
    assert _until(lambda: _js(view, "document.querySelector('.stage-main .slide').innerText.includes('Caja <i>de texto</i>')"))


@needs_suite
def test_e2e_pdf_viewer_and_premium_edit(office, files, tmp_path, monkeypatch):
    app, win = office
    view = _open(app, win, files["pdf"])
    assert _until(lambda: _js(view, "document.body.dataset.pdfPages") == "2", 20000)
    assert _until(lambda: "Hola Katphi 1" in (_js(view, "document.querySelector('.textLayer') ? document.querySelector('.textLayer').textContent : ''") or ""), 20000)
    # Sin el plugin premium no hay barra de edición
    assert _js(view, "document.querySelector('#edit-bar').hidden") is True

    # Con office_suite cargado: barra de edición y operaciones en Python
    from katphi_office_suite import pdf_edit
    from katphi_office_suite import files as suite_files
    monkeypatch.setattr(suite_files, "backup_dir", lambda: tmp_path / "backups")
    pdf_edit.set_main_window(win)
    capabilities.register("pdf_edit", pdf_edit.PdfEditor())
    capabilities.register("pdf_pages", pdf_edit.PdfPages())
    view2 = _open(app, win, files["pdf"])
    assert _until(lambda: _js(view2, "document.querySelector('#edit-bar').hidden") is False)
    titles = json.loads(_js(view2, "JSON.stringify(Array.from(document.querySelectorAll('#edit-bar button')).map(b => b.title))"))
    assert "Dibujar o firmar a mano" in titles and "Guardar (Ctrl+S)" in titles

    from katphi_office.sessions import STORE
    session = [s for s in STORE.sessions() if s.extra.get("browser") is view2][0]
    bridge = session.extra["bridge"]
    res = json.loads(bridge.pdfPageOp(session.token, json.dumps({"op": "delete", "pages": [2]})))
    assert res == {"ok": True}
    assert _until(lambda: _js(view2, "document.body.dataset.pdfPages") == "1", 20000)
    # Otro token (otra pestaña) no puede operar sobre este documento
    assert not json.loads(bridge.pdfPageOp("otro", json.dumps({"op": "delete", "pages": [1]})))["ok"]
    # Guardar desde la página (PDF.js serializa y Python escribe con copia)
    _js(view2, "document.querySelector('[title=\"Guardar (Ctrl+S)\"]').click(); 1")
    assert _until(lambda: (tmp_path / "backups").exists() and len(list((tmp_path / "backups").iterdir())) >= 2)


def test_e2e_web_page_cannot_read_app_scheme(office, files):
    """Una página http(s) no puede pedir recursos de katphi-app://."""
    app, win = office
    view = _open(app, win, files["docx"])
    from PySide6.QtCore import QUrl
    from PySide6.QtWebEngineCore import QWebEnginePage
    from PySide6.QtWebEngineWidgets import QWebEngineView
    web = QWebEngineView()
    web.setPage(QWebEnginePage(win.tab_manager.profile, web))
    loaded = []
    web.loadFinished.connect(lambda ok: loaded.append(ok))
    web.setHtml("<p>web</p>", QUrl("https://example.com/"))
    _until(lambda: loaded)
    # Ni como script ni como imagen (el manejador rechaza el iniciador https)
    web.page().runJavaScript(
        "window.__r = [];"
        "var s = document.createElement('script'); s.src = 'katphi-app://office/viewer.js';"
        "s.onload = () => window.__r.push('script-cargado'); s.onerror = () => window.__r.push('script-bloqueado');"
        "document.body.appendChild(s);"
        "var i = new Image(); i.onload = () => window.__r.push('img-cargada');"
        "i.onerror = () => window.__r.push('img-bloqueada'); i.src = 'katphi-app://office/pdfjs/web/images/loading-icon.gif';", 0)
    _until(lambda: (_js(web, "window.__r.length") or 0) >= 2, 8000)
    assert sorted(json.loads(_js(web, "JSON.stringify(window.__r)"))) == ["img-bloqueada", "script-bloqueado"]
    web.close()


# ---------------------------------------------------------------- premium: hojas (conversión)

def _rich_xlsx(path):
    import openpyxl
    from openpyxl.formatting.rule import CellIsRule, ColorScaleRule, FormulaRule
    from openpyxl.styles import Alignment, Border, PatternFill, Side
    from openpyxl.worksheet.datavalidation import DataValidation
    S.make_xlsx(path)
    wb = openpyxl.load_workbook(path)
    ws = wb["Ventas"]
    ws.freeze_panes = "B2"
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["E"].hidden = True
    ws.row_dimensions[1].height = 30
    ws.auto_filter.ref = "A1:D3"
    ws["B2"].border = Border(top=Side(style="thin", color="FF0000FF"), bottom=Side(style="double"))
    ws["C2"].number_format = "0.00%"
    ws["A2"].alignment = Alignment(horizontal="right", vertical="top", wrap_text=True)
    ws.conditional_formatting.add("B2:B10", CellIsRule(operator="greaterThan", formula=["2"],
                                  fill=PatternFill(start_color="FF00FF00", end_color="FF00FF00", fill_type="solid")))
    ws.conditional_formatting.add("C2:C10", ColorScaleRule(start_type="min", start_color="FFFFFFFF",
                                                           end_type="max", end_color="FFFF0000"))
    ws.conditional_formatting.add("A2:A10", FormulaRule(formula=["LEN(A2)>3"], fill=PatternFill(start_color="FFFF0000", end_color="FFFF0000", fill_type="solid")))
    dv = DataValidation(type="list", formula1='"si,no"')
    dv.sqref = "E2:E9"
    ws.add_data_validation(dv)
    dv2 = DataValidation(type="whole", operator="between", formula1="1", formula2="10")
    dv2.sqref = "F2:F9"
    ws.add_data_validation(dv2)
    ws.sheet_properties.tabColor = "FF0000"
    wb.defined_names["Total"] = __import__("openpyxl").workbook.defined_name.DefinedName("Total", attr_text="Ventas!$D$2:$D$3")
    wb.save(path)
    S._set_cached_values(path, {"D2": "7.5", "D3": "2.5"})


@needs_suite
def test_sheets_roundtrip(tmp_path):
    import openpyxl
    from katphi_office_suite import sheets_io
    src = str(tmp_path / "rico.xlsx")
    _rich_xlsx(src)
    snap, info = sheets_io.load(src, "xlsx")
    s1 = snap["sheets"]["s1"]
    assert s1["freeze"]["xSplit"] == 1 and s1["freeze"]["ySplit"] == 1
    assert s1["columnData"][0]["w"] == 145 and s1["columnData"][4]["hd"] == 1
    assert s1["rowData"][0]["h"] == 40 and s1["tabColor"] == "#ff0000"
    assert s1["cellData"][1][3] == {"f": "=B2*C2", "v": 7.5, "t": 2}
    assert snap["styles"][s1["cellData"][0][0]["s"]] == {"bl": 1, "cl": {"rgb": "#ff0000"}, "bg": {"rgb": "#ffff00"}}
    res = {r["name"]: json.loads(r["data"]) for r in snap["resources"]}
    assert res["SHEET_FILTER_PLUGIN"]["s1"]["ref"]["endColumn"] == 3
    dv = res["SHEET_DATA_VALIDATION_PLUGIN"]["s1"]
    assert dv[0]["type"] == "list" and dv[0]["formula1"] == "si,no"
    assert dv[1]["type"] == "whole" and dv[1]["operator"] == "between"
    cf_types = sorted((r["rule"]["type"], r["rule"].get("subType", "")) for r in res["SHEET_CONDITIONAL_FORMATTING_PLUGIN"]["s1"])
    assert cf_types == [("colorScale", ""), ("highlightCell", "formula"), ("highlightCell", "number")]
    assert snap["sheets"]["s2"]["hidden"] == 1

    # Cambios como los haría el editor
    s1["cellData"][1][1]["v"] = 10
    s1["cellData"].setdefault(6, {})[0] = {"f": "=SUM(B2:B3)", "v": 12, "t": 2}
    s1["cellData"].setdefault(7, {})[0] = {"v": 1, "t": 3}
    del s1["cellData"][2]                      # fila 3 vaciada
    s1["name"] = "Ventas2025"
    del snap["sheets"]["s2"]
    snap["sheetOrder"].remove("s2")
    snap["sheets"]["s9"] = {"id": "s9", "name": "Nueva", "cellData": {0: {0: {"v": "hola", "t": 1}}}}
    snap["sheetOrder"].insert(0, "s9")
    res["SHEET_DATA_VALIDATION_PLUGIN"]["s1"][0]["formula1"] = '["a","b"]'   # formato del editor
    snap["resources"] = [{"name": k, "data": json.dumps(v)} for k, v in res.items()]
    out = tmp_path / "salida.xlsx"
    out.write_bytes(sheets_io.save_xlsx(snap, src, "xlsx", info["sheet_ids"]))

    wb = openpyxl.load_workbook(str(out))
    assert wb.sheetnames == ["Nueva", "Ventas2025", "Resumen"]
    w = wb["Ventas2025"]
    assert w["B2"].value == 10 and w["A7"].value == "=SUM(B2:B3)" and w["A8"].value is True
    assert w["A3"].value is None
    assert w.freeze_panes == "B2" and w.auto_filter.ref == "A1:D3"
    assert [str(r) for r in w.merged_cells.ranges] == ["A5:B5"]
    assert w["A1"].font.b and w["A1"].font.color.rgb == "FFFF0000" and w["A1"].fill.fgColor.rgb == "FFFFFF00"
    assert w["C2"].number_format == "0.00%"
    assert w["B2"].border.top.style == "thin" and w["B2"].border.top.color.rgb == "FF0000FF"
    assert w["B2"].border.bottom.style == "double"
    assert w["A2"].alignment.horizontal == "right" and w["A2"].alignment.wrap_text
    assert w.column_dimensions["A"].width == 20 and w.column_dimensions["E"].hidden
    assert w.row_dimensions[1].height == 30
    assert w.sheet_properties.tabColor.rgb == "00FF0000" or w.sheet_properties.tabColor.rgb.endswith("FF0000")
    assert sorted(d.type for d in w.data_validations.dataValidation) == ["list", "whole"]
    assert [d.formula1 for d in w.data_validations.dataValidation if d.type == "list"] == ['"a,b"']
    assert sorted(r.type for cf in w.conditional_formatting for r in cf.rules) == ["cellIs", "colorScale", "expression"]
    assert "Total" in wb.defined_names                       # conservado del original
    wv = openpyxl.load_workbook(str(out), data_only=True)["Ventas2025"]
    assert wv["A7"].value == 12 and wv["D2"].value == 7.5      # valores calculados escritos


@needs_suite
def test_sheets_csv_ods_new(tmp_path, files):
    from katphi_office_suite import sheets_io
    snap, _ = sheets_io.load(files["ods"], "ods")
    assert snap["sheets"]["s1"]["cellData"][0] == {0: {"v": "a", "t": 1}, 1: {"v": 5, "t": 2}}
    snap, _ = sheets_io.load(files["csv"], "csv")
    data = sheets_io.save_csv(snap, ";").decode("utf-8-sig")
    assert data.splitlines() == ["a;b;c", "1;2;3"]
    new = sheets_io.new_workbook()
    new["sheets"]["s1"]["cellData"] = {0: {0: {"v": "x", "t": 1}, 1: {"f": "=1+1", "v": 2, "t": 2}}}
    out = tmp_path / "nuevo.xlsx"
    out.write_bytes(sheets_io.save_xlsx(new))
    import openpyxl
    assert openpyxl.load_workbook(str(out))["Hoja1"]["B1"].value == "=1+1"


# ---------------------------------------------------------------- premium: hojas (editor)

def _enable_suite(app, win, tmp_path, monkeypatch):
    from katphi_office_suite import files as suite_files, sheets_edit
    monkeypatch.setattr(suite_files, "backup_dir", lambda: tmp_path / "backups")
    sheets_edit.set_main_window(win)
    app.register_mount("suite", os.path.join(SUITE_DIR, "web"))
    capabilities.register("sheets_edit", sheets_edit.SheetsEditor())


def _open_editor(app, win, path):
    assert app.open_document(win, path)
    view = win.tab_manager.views[-1]
    ok = _until(lambda: _js(view, "!!(window.__katphiUniver && document.querySelector('#univer-app canvas'))") is True, 30000)
    if not ok:
        pytest.fail("El editor no arrancó: " + repr(_js(view, "document.body.innerText.slice(0,300)")))
    _wait(1500)
    return view


def _sheet_js(view, code):
    return _js(view, "(function(){const wb=window.__katphiUniver.getActiveWorkbook();"
                     "const ws=wb.getActiveSheet();" + code + "})()")


@needs_suite
def test_e2e_sheet_editor_edit_and_save(office, tmp_path, monkeypatch):
    import openpyxl
    app, win = office
    _enable_suite(app, win, tmp_path, monkeypatch)
    src = str(tmp_path / "rico.xlsx")
    _rich_xlsx(src)
    view = _open_editor(app, win, src)
    assert _sheet_js(view, "return ws.getRange('A1').getValue()") == "Producto"
    assert _sheet_js(view, "return ws.getRange('D2').getValue()") == 7.5
    assert _sheet_js(view, "return ws.getRange('D2').getFormula()") == "=B2*C2"
    # Editar: el valor de B2 cambia y la fórmula se recalcula
    _sheet_js(view, "ws.getRange('B2').setValue(10); return 1")
    assert _until(lambda: _sheet_js(view, "return ws.getRange('D2').getValue()") == 25)
    assert _until(lambda: win.tab_manager.titles[id(view)] == "* rico.xlsx")
    # Guardar (Ctrl+S → window.__katphiSheetSave)
    _js(view, "window.__katphiSheetSave(false).then(r => window.__saved = JSON.stringify(r)); 1")
    assert _until(lambda: _js(view, "window.__saved || ''") != "")
    assert json.loads(_js(view, "window.__saved"))["ok"] is True
    assert win.tab_manager.titles[id(view)] == "rico.xlsx"
    assert len(list((tmp_path / "backups").iterdir())) == 1
    wb = openpyxl.load_workbook(src)
    assert wb["Ventas"]["B2"].value == 10 and wb["Ventas"]["D2"].value == "=B2*C2"
    assert wb["Ventas"]["A1"].font.b and wb["Ventas"].freeze_panes == "B2"
    assert openpyxl.load_workbook(src, data_only=True)["Ventas"]["D2"].value == 25


@needs_suite
def test_e2e_sheet_editor_spanish_formula_by_keyboard(office, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    app, win = office
    _enable_suite(app, win, tmp_path, monkeypatch)
    src = str(tmp_path / "ventas.xlsx")
    S.make_xlsx(src)
    view = _open_editor(app, win, src)
    _sheet_js(view, "ws.getRange('F1').activate(); return 1")
    _wait(500)
    target = view.focusProxy() or view
    target.setFocus()
    QTest.keyClicks(target, "=SUMA(B2;B3)*1,5")
    QTest.keyClick(target, Qt.Key_Return)
    ok = _until(lambda: _sheet_js(view, "return ws.getRange('F1').getFormula()") == "=SUM(B2,B3)*1.5", 8000)
    assert ok, _sheet_js(view, "return ws.getRange('F1').getFormula() + ' | ' + ws.getRange('F1').getValue()")
    assert _until(lambda: _sheet_js(view, "return ws.getRange('F1').getValue()") == 7.5)


@needs_suite
def test_e2e_new_workbook_save_as_and_print(office, tmp_path, monkeypatch):
    import openpyxl
    from PySide6.QtWidgets import QFileDialog
    app, win = office
    _enable_suite(app, win, tmp_path, monkeypatch)
    assert app.new_document(win, "sheets")
    view = win.tab_manager.views[-1]
    assert _until(lambda: _js(view, "!!(window.__katphiUniver && document.querySelector('#univer-app canvas'))") is True, 30000)
    _wait(1000)
    _sheet_js(view, "ws.getRange('A1').setValue('Hola'); ws.getRange('B1').setValue(4);"
                    "ws.getRange('C1').setFormula('=B1*2'); return 1")
    assert _until(lambda: _sheet_js(view, "return ws.getRange('C1').getValue()") == 8)
    target = str(tmp_path / "nuevo")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (target, "Libro de Excel (*.xlsx)")))
    _js(view, "window.__katphiSheetSave(false).then(r => window.__saved = JSON.stringify(r)); 1")
    assert _until(lambda: _js(view, "window.__saved || ''") != "")
    res = json.loads(_js(view, "window.__saved"))
    assert res["ok"] and res["path"].endswith("nuevo.xlsx")
    assert win.tab_manager.titles[id(view)] == "nuevo.xlsx"
    ws = openpyxl.load_workbook(target + ".xlsx")["Hoja1"]
    assert (ws["A1"].value, ws["B1"].value, ws["C1"].value) == ("Hola", 4, "=B1*2")
    # Imprimir: la tabla de impresión se genera con los valores mostrados
    printed = []
    monkeypatch.setattr(app, "print_session", lambda s, parent: printed.append(s.name))
    _js(view, "document.querySelector('[title=\"Imprimir (Ctrl+P)\"]').click(); 1")
    assert _until(lambda: printed == ["nuevo.xlsx"])
    cells = json.loads(_js(view, "JSON.stringify(Array.from(document.querySelectorAll('#katphi-print-area td')).map(t => t.textContent))"))
    assert cells == ["Hola", "4", "8"]


@needs_suite
def test_e2e_spanish_translator_module(office, tmp_path, monkeypatch, files):
    """El traductor de fórmulas, cargado en la página del visor."""
    app, win = office
    _enable_suite(app, win, tmp_path, monkeypatch)
    view = _open(app, win, files["docx"])
    _js(view, "import('katphi-app://office/suite/sheets/es-formulas.js').then(m => { window.__t = JSON.stringify(["
              "m.translateFormula('=SUMA(A1;A2)'), m.translateFormula('=SI(A1>0;\"a;b\";FALSO)'),"
              "m.translateFormula('=BUSCARV(A1;B:C;2;FALSO)'), m.translateFormula('=SUM(A1,A2)'),"
              "m.translateFormula('=PROMEDIO(1,5;B2)'), m.translateFormula('=SUMA(A1,5)')]) }); 1")
    assert _until(lambda: _js(view, "window.__t || ''") != "")
    assert json.loads(_js(view, "window.__t")) == [
        "=SUM(A1,A2)", '=IF(A1>0,"a;b",FALSE)', "=VLOOKUP(A1,B:C,2,FALSE)", None,
        "=AVERAGE(1.5,B2)", "=SUM(A1,5)"]


def test_e2e_read_only_notice_links_to_store(office, files, tmp_path, monkeypatch):
    """Sin el plugin premium el visor dice que es de solo lectura y lleva a la tienda."""
    app, win = office
    opened = []
    win.toggle_plugin_store = lambda: opened.append(True)
    view = _open(app, win, files["xlsx"])
    badges = json.loads(_js(view, "JSON.stringify(Array.from(document.querySelectorAll('#tb-left .badge')).map(b => b.textContent))"))
    assert "Solo lectura" in badges
    _js(view, "document.querySelector('.upsell').click(); 1")
    assert _until(lambda: opened == [True])
    # Documentos de texto: solo lectura, sin botón (aún no hay editor)
    view2 = _open(app, win, files["docx"])
    assert _js(view2, "!!document.querySelector('.upsell')") is False
    assert "Solo lectura" in _js(view2, "document.querySelector('#tb-left').textContent")
    if HAS_SUITE:
        _enable_suite(app, win, tmp_path, monkeypatch)
        view3 = _open_editor(app, win, files["xlsx"])
        assert _js(view3, "!!document.querySelector('.upsell')") is False
