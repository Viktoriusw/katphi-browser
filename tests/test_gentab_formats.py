"""Formatos de GenTab: detección, lectura del JSON del modelo y plantillas."""
import json
import re
import shutil
import subprocess

import pytest

import gentab_formats as gf
from gentab_engine import ContentExtractor, GenTabWorker, TabContext


def _tab(n, url, links=()):
    return TabContext(index=n, url=url, title=f"Tab {n}", content="x", content_length=1,
                      domain=url.split("/")[2], links=list(links))


SOURCES = [{"url": "https://a.example/1", "title": "A", "domain": "a.example"},
           {"url": "https://b.example/2", "title": "B", "domain": "b.example"}]

SAMPLES = {
    "compare": {"title": "T", "summary": "S", "columns": ["Precio", "Peso"],
                "rows": [{"name": "X", "values": ["10 €", "1 kg"], "src": 1},
                         {"name": "Y", "values": ["8 €"], "src": 2}]},
    "briefing": {"title": "T", "tldr": "Idea", "conclusions": ["C"],
                 "sections": [{"heading": "H", "points": [{"text": "P", "src": 1}, "Q"]}]},
    "mindmap": {"title": "T", "center": "C",
                "branches": [{"label": "B1", "children": [{"label": "c", "detail": "d", "src": 1}]},
                             {"label": "B2", "children": ["solo texto"]}]},
    "flashcards": {"title": "T", "cards": [{"q": "¿1?", "a": "uno", "src": 1},
                                           {"q": "¿2?", "a": "dos", "src": 9}]},
    "timeline": {"title": "T", "events": [{"date": "1882", "title": "E1", "src": 2},
                                          {"date": "300 a. C.", "title": "E0", "detail": "d"}]},
}


@pytest.mark.parametrize("prompt,fmt", [
    (gf.FORMATS["compare"]["task"], "compare"),
    (gf.FORMATS["briefing"]["task"], "briefing"),
    (gf.FORMATS["mindmap"]["task"], "mindmap"),
    (gf.FORMATS["flashcards"]["task"], "flashcards"),
    (gf.FORMATS["timeline"]["task"], "timeline"),
    (gf.FORMATS["links"]["task"], "links"),
    ("Compara los precios de estos portátiles", "compare"),
    ("hazme un quiz para estudiar", "flashcards"),
    ("resume estas noticias con enlaces a las fuentes", "briefing"),
    ("Crea un juego de memoria con los países", "free"),
    ("Crea un dashboard con métricas", "free"),
])
def test_detect_format(prompt, fmt):
    assert gf.detect_format(prompt) == fmt


def test_detect_format_ignores_chat_history():
    prompt = ("[Contexto de la conversación previa]\nUsuario: compárame dos tablas\n\n"
              "[Solicitud actual]\nHaz un mapa mental de las pestañas")
    assert gf.detect_format(prompt) == "mindmap"
    request, history = gf.split_request(prompt)
    assert request == "Haz un mapa mental de las pestañas"
    assert "compárame" in history and "[Contexto" not in history


def test_every_format_has_label_task_and_template():
    for fmt, info in gf.FORMATS.items():
        assert info["label"] and info["task"] and info["description"]
        assert gf.detect_format(info["task"]) == fmt
        assert fmt in gf._TEMPLATES
    assert set(gf._SCHEMAS) == {f for f in gf.FORMATS if gf.uses_llm_json(f)}


@pytest.mark.parametrize("raw", [
    '{"a": 1}',
    '```json\n{"a": 1}\n```',
    '<think>razono {mucho}</think>\nAquí está: {"a": 1,}',
    'Texto previo {"a": 1} texto final',
])
def test_parse_json_object(raw):
    assert gf.parse_json_object(raw) == {"a": 1}


@pytest.mark.parametrize("raw", ["", "sin json", "[1, 2]", "{roto"])
def test_parse_json_object_invalid(raw):
    assert gf.parse_json_object(raw) is None


def test_normalize_samples():
    compare = gf.normalize("compare", SAMPLES["compare"], 2)
    assert compare["rows"][1]["values"] == ["8 €", "-"]      # rellena columnas
    briefing = gf.normalize("briefing", SAMPLES["briefing"], 2)
    assert briefing["sections"][0]["points"][1] == {"text": "Q", "src": 0}
    mindmap = gf.normalize("mindmap", SAMPLES["mindmap"], 2)
    assert mindmap["branches"][1]["children"][0]["label"] == "solo texto"
    cards = gf.normalize("flashcards", SAMPLES["flashcards"], 2)
    assert cards["cards"][1]["src"] == 0                      # TAB inexistente -> sin fuente
    assert gf.normalize("timeline", SAMPLES["timeline"], 2)["events"][1]["src"] == 0


@pytest.mark.parametrize("fmt,data", [
    ("compare", {"columns": [], "rows": [{"name": "x"}]}),
    ("briefing", {"sections": []}),
    ("mindmap", {"branches": [{"label": "solo una"}]}),
    ("flashcards", {"cards": [{"q": "a", "a": "b"}]}),
    ("timeline", {"events": [{"date": "", "title": "x"}]}),
    ("compare", "no es un dict"),
])
def test_normalize_rejects_empty(fmt, data):
    assert gf.normalize(fmt, data, 2) is None


def _script(html):
    return re.search(r"<script>\n(.*)\n</script>", html, re.S).group(1)


@pytest.mark.parametrize("fmt", list(SAMPLES))
def test_build_page(fmt):
    data = gf.normalize(fmt, SAMPLES[fmt], 2)
    html = gf.build_page(fmt, data, SOURCES)
    assert html.startswith("<!DOCTYPE html>") and 'id="themeToggle"' in html
    assert "const DATA = " in html and "const SOURCES = " in html


def test_build_page_escapes_script_end():
    data = gf.normalize("flashcards", {"cards": [{"q": "</script><img src=x>", "a": "<!--"},
                                                 {"q": "b", "a": "c"}]}, 2)
    html = gf.build_page("flashcards", data, SOURCES)
    assert html.count("</script>") == 1 and "<\\/script>" in html


@pytest.mark.skipif(not shutil.which("node"), reason="node no está instalado")
@pytest.mark.parametrize("fmt", list(SAMPLES) + ["links"])
def test_template_js_syntax(fmt, tmp_path):
    if fmt == "links":
        data = gf.links_data([_tab(0, "https://a.example/1", [("Uno", "https://c.example/x")])])
    else:
        data = gf.normalize(fmt, SAMPLES[fmt], 2)
    js = tmp_path / "page.js"
    js.write_text(_script(gf.build_page(fmt, data, SOURCES)), encoding="utf-8")
    proc = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_links_data_dedup_and_internal():
    tabs = [_tab(0, "https://www.a.example/p", [("Interno", "https://www.a.example/q"),
                                                 ("Fuera", "https://b.example/")]),
            _tab(1, "https://b.example/", [("Fuera otra vez", "https://b.example/")])]
    data = gf.links_data(tabs)
    assert [l["url"] for l in data["links"]] == ["https://www.a.example/q", "https://b.example/"]
    assert data["links"][0]["internal"] and data["links"][0]["domain"] == "a.example"
    assert not data["links"][1]["internal"] and data["links"][1]["src"] == 1
    assert gf.links_data([_tab(0, "https://a.example/")]) is None


def test_extract_links():
    html = """<html><body><nav><a href="/menu">Menú principal</a></nav>
      <main><a href="/wiki/Sol">Sol</a> <a href="https://otra.example/x#frag">Otra</a>
      <a href="#arriba">Arriba</a> <a href="javascript:void(0)">JS</a>
      <a href="/wiki/Sol">Sol repetido</a> <a href="mailto:a@b.c">Correo</a></main></body></html>"""
    links = ContentExtractor.extract_links(html, "https://es.wikipedia.org/wiki/Luna")
    assert links == [("Sol", "https://es.wikipedia.org/wiki/Sol"), ("Otra", "https://otra.example/x")]


def test_worker_numbers_tabs_sequentially():
    tabs = [_tab(3, "https://a.example/"), _tab(7, "https://b.example/")]
    worker = GenTabWorker("http://localhost:1234", "x", tabs)
    ctx = worker._build_context()
    assert "--- TAB 1 ---" in ctx and "--- TAB 2 ---" in ctx and "TAB 4" not in ctx
    assert worker._source_list().startswith("TAB 1: Tab 3")


def test_free_prompt_keeps_request_with_long_history():
    request = "Crea un juego de memoria con los países"
    prompt = ("[Contexto de la conversación previa]\n" + "historial " * 600
              + "\n\n[Solicitud actual]\n" + request)
    worker = GenTabWorker("http://localhost:1234", prompt, [_tab(0, "https://a.example/")])
    user = worker._build_user_prompt("contenido")
    assert f"TASK: {request}" in user
    assert "card grid" not in worker._build_system_prompt().lower()
