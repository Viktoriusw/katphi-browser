"""
Formatos de GenTab: cada opción produce una página con una estructura propia.

Antes todas las opciones pedían al modelo el mismo esqueleto (rejilla de
tarjetas con render()), así que la tabla comparativa, el mapa mental o el
dashboard acababan siendo la misma página. Ahora:

  - El modelo solo extrae los DATOS en JSON con el esquema del formato.
  - La página la monta una plantilla fija de Katphi (HTML + CSS + JS), una
    por formato: tabla ordenable, informe, mapa mental SVG, tarjetas que
    giran, línea de tiempo y directorio de enlaces.
  - "links" no usa el modelo: reúne los enlaces reales de las pestañas.
  - Una petición libre ("free") sigue generando HTML con el modelo, pero ya
    sin imponerle la rejilla de tarjetas.

Las fuentes nunca las escribe el modelo: cada dato lleva "src" (número de
pestaña) y la plantilla enlaza la URL real de esa pestaña. Los textos se
pintan con textContent, nunca como HTML.
"""

import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

FORMAT_FREE = "free"
FORMAT_LINKS = "links"

# Orden en el que se ofrecen en el panel GenTab y en el asistente de chat
FORMATS: Dict[str, Dict[str, Any]] = {
    "compare": {
        "label": "Tabla comparativa",
        "description": "Tabla ordenable con una fila por elemento y sus características.",
        "task": ("Tabla comparativa: compara los elementos de las pestañas abiertas "
                 "(productos, opciones, artículos...) en una tabla ordenable con sus "
                 "características principales."),
    },
    "briefing": {
        "label": "Informe resumido",
        "description": "Documento de lectura: resumen, ideas clave por temas y conclusiones.",
        "task": ("Informe resumido: resume el contenido de las pestañas en un informe "
                 "con las ideas clave por temas y las conclusiones."),
    },
    "mindmap": {
        "label": "Mapa mental",
        "description": "Diagrama con el tema central, sus ramas y las ideas de cada rama.",
        "task": ("Mapa mental: organiza los temas de las pestañas en un mapa mental con "
                 "el tema central, sus ramas y las ideas clave."),
    },
    "flashcards": {
        "label": "Tarjetas de estudio",
        "description": "Preguntas y respuestas de una en una para repasar.",
        "task": ("Tarjetas de estudio: crea flashcards de preguntas y respuestas para "
                 "estudiar el contenido de las pestañas."),
    },
    "timeline": {
        "label": "Línea de tiempo",
        "description": "Fechas y acontecimientos ordenados cronológicamente.",
        "task": ("Línea de tiempo: ordena cronológicamente las fechas y acontecimientos "
                 "que aparecen en las pestañas."),
    },
    FORMAT_LINKS: {
        "label": "Directorio de enlaces",
        "description": "Todos los enlaces de las pestañas, por dominio y con buscador.",
        "task": ("Directorio de enlaces: reúne todos los enlaces de las pestañas, "
                 "agrupados por dominio y con buscador."),
    },
}

# Palabras clave para reconocer el formato en una petición escrita a mano.
# Van de la más específica a la más general ("tabla" o "resume" son genéricas).
_KEYWORDS = (
    ("flashcards", ("flashcard", "tarjetas de estudio", "tarjetas de memoria",
                    "preguntas y respuestas", "cuestionario", "quiz")),
    ("timeline", ("línea de tiempo", "linea de tiempo", "línea temporal", "linea temporal",
                  "cronolog", "timeline")),
    ("mindmap", ("mapa mental", "mind map", "mapa conceptual", "mapa de información",
                 "mapa de informacion")),
    (FORMAT_LINKS, ("directorio de enlaces", "mapa de enlaces", "lista de enlaces",
                    "todos los enlaces", "todos los links", "link directory")),
    ("compare", ("tabla comparativa", "comparativa", "compara", "comparación",
                 "comparacion", "compare", "tabla")),
    ("briefing", ("informe resumido", "resumen", "resume", "resumir", "briefing",
                  "summary", "summarize")),
)

_REQUEST_MARKER = "[Solicitud actual]"
_HISTORY_MARKER = "[Contexto de la conversación previa]"


def split_request(prompt: str):
    """(petición, historial). El chat antepone su historial a la petición."""
    prompt = (prompt or "").strip()
    if _REQUEST_MARKER not in prompt:
        return prompt, ""
    history, _, request = prompt.partition(_REQUEST_MARKER)
    history = history.replace(_HISTORY_MARKER, "").strip()
    return request.strip(), history


def detect_format(prompt: str) -> str:
    """Formato que corresponde a la petición (solo mira la petición, no el historial)."""
    request, _ = split_request(prompt)
    text = request.lower()
    for fmt, words in _KEYWORDS:
        if any(w in text for w in words):
            return fmt
    return FORMAT_FREE


def format_label(fmt: str) -> str:
    if fmt in FORMATS:
        return FORMATS[fmt]["label"]
    return "Página libre"


def uses_llm_json(fmt: str) -> bool:
    return fmt in FORMATS and fmt != FORMAT_LINKS


# ─── Prompts para extraer los datos ───────────────────────────────────────────

_SCHEMAS = {
    "compare": (
        '{"title": str, "summary": str (1-2 sentences), '
        '"columns": [str] (3 to 6 attribute names, without the item name), '
        '"rows": [{"name": str, "values": [str, one per column, same order], "src": int}]}\n'
        "One row per product/option/article/item found in the tabs (at least 2 rows). "
        "Pick columns that let the user compare the rows (price, features, pros, cons, "
        "dates, figures...). Use \"-\" when a value is not in the tabs.",
        {"title": "Comparativa de portátiles", "summary": "Tres modelos de gama media.",
         "columns": ["Precio", "Peso", "Batería", "Pantalla"],
         "rows": [{"name": "Modelo A", "values": ["799 €", "1,4 kg", "10 h", "14 pulgadas"], "src": 1},
                  {"name": "Modelo B", "values": ["649 €", "1,8 kg", "8 h", "15,6 pulgadas"], "src": 2}]},
    ),
    "briefing": (
        '{"title": str, "tldr": str (2-3 sentences with the main idea), '
        '"sections": [{"heading": str, "points": [{"text": str, "src": int}]}] '
        "(3 to 6 sections grouped by TOPIC, not by tab, covering ALL the tabs; 2 to 5 points each), "
        '"conclusions": [str] (2 to 4)}',
        {"title": "Informe sobre la energía solar", "tldr": "La energía solar crece...",
         "sections": [{"heading": "Funcionamiento", "points": [
             {"text": "Los paneles fotovoltaicos convierten la luz en electricidad.", "src": 1}]}],
         "conclusions": ["Su coste ha bajado mucho en la última década."]},
    ),
    "mindmap": (
        '{"title": str, "center": str (the main topic, 1-4 words), '
        '"branches": [{"label": str (1-4 words), '
        '"children": [{"label": str (1-5 words), "detail": str (1-2 sentences), "src": int}]}]}\n'
        "3 to 6 branches that cover ALL the tabs, 2 to 5 children per branch. "
        "The center is the topic shared by all the tabs.",
        {"title": "Mapa de las energías renovables", "center": "Energías renovables",
         "branches": [{"label": "Solar", "children": [
             {"label": "Fotovoltaica", "detail": "Convierte la luz en electricidad.", "src": 1}]}]},
    ),
    "flashcards": (
        '{"title": str, "cards": [{"q": str (a question), "a": str (short answer), "src": int}]}\n'
        "Write AT LEAST 8 cards (up to 20), taken from ALL the tabs. "
        "Questions must be answerable with the tab content.",
        {"title": "Repaso de energía eólica",
         "cards": [{"q": "¿Qué convierte un aerogenerador?",
                    "a": "La energía cinética del viento en electricidad.", "src": 2}]},
    ),
    "timeline": (
        '{"title": str, "events": [{"date": str (year or date as written in the tab), '
        '"title": str, "detail": str (1-2 sentences), "src": int}]}\n'
        "Write AT LEAST 6 events if the tabs have them (up to 20), from ALL the tabs, in "
        "chronological order. Only historical events with a date written in the tab content: "
        "ignore the dates of the web page itself (last edit, access date, copyright).",
        {"title": "Historia de la energía hidráulica",
         "events": [{"date": "1882", "title": "Primera central hidroeléctrica",
                     "detail": "Se inaugura en Appleton (Wisconsin).", "src": 3}]},
    ),
}


def json_system_prompt(fmt: str) -> str:
    return (
        "You are the data extractor of GenTab, a tool of a web browser. You read the "
        "content of the user's browser tabs and return the data for a page of type "
        f"\"{FORMATS[fmt]['label']}\".\n"
        "RULES:\n"
        "- Output ONLY one valid JSON object. No markdown, no code fences, no comments, "
        "no text before or after it.\n"
        "- Use only information that appears in the tab content. Never invent facts, "
        "figures, dates or URLs.\n"
        "- Write every text value in the language of the user's request (Spanish if in doubt).\n"
        "- \"src\" is the number of the TAB the information comes from (TAB 1 -> 1).\n"
        "- Keep the texts short and concrete."
    )


def json_user_prompt(fmt: str, request: str, history: str, context: str, source_list: str) -> str:
    schema, example = _SCHEMAS[fmt]
    parts = [f"USER REQUEST: {request}"]
    if history:
        parts.append(f"PREVIOUS CONVERSATION (only for context):\n{history}")
    parts.append(f"OUTPUT FORMAT ({FORMATS[fmt]['label']}):\n{schema}")
    parts.append("EXAMPLE (structure only, do not copy its content):\n"
                 + json.dumps(example, ensure_ascii=False))
    parts.append(f"TABS:\n{source_list}")
    parts.append(f"TAB CONTENT:\n{context}")
    parts.append("Return the JSON object now.")
    return "\n\n".join(parts)


# ─── Lectura y limpieza de la respuesta del modelo ────────────────────────────

_THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)
_FENCE_RE = re.compile(r"```(?:json)?", re.I)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def parse_json_object(raw: str) -> Optional[dict]:
    """Primer objeto JSON de la respuesta, tolerando razonamiento, ``` y comas finales."""
    if not raw:
        return None
    text = _FENCE_RE.sub("", _THINK_RE.sub("", raw))
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    candidate = text[start:end + 1]
    for attempt in (candidate, _TRAILING_COMMA_RE.sub(r"\1", candidate)):
        try:
            data = json.loads(attempt)
        except ValueError:
            continue
        return data if isinstance(data, dict) else None
    return None


def _text(value, limit=400) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = " ".join(value.split())
    return value if len(value) <= limit else value[:limit - 1].rstrip() + "…"


def _src(value, n_sources: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if 1 <= n <= n_sources else 0


def _list(value) -> list:
    return value if isinstance(value, list) else []


# Una fecha tiene cifras o es un periodo con nombre ("Siglo XIII", "Edad Media")
_DATE_RE = re.compile(r"\d|\bsiglo\b|\bcentury\b|\bedad\b|\bera\b|\bépoca\b|a\.\s?c\.|d\.\s?c\.", re.I)


def normalize(fmt: str, data: dict, n_sources: int) -> Optional[dict]:
    """Datos limpios para la plantilla, o None si no hay suficiente contenido."""
    if not isinstance(data, dict):
        return None
    title = _text(data.get("title"), 120)
    if fmt == "compare":
        columns = [_text(c, 60) for c in _list(data.get("columns")) if _text(c)][:8]
        rows = []
        for r in _list(data.get("rows"))[:60]:
            if not isinstance(r, dict) or not _text(r.get("name")):
                continue
            values = [_text(v, 200) or "-" for v in _list(r.get("values"))]
            values = (values + ["-"] * len(columns))[:len(columns)]
            rows.append({"name": _text(r.get("name"), 120), "values": values,
                         "src": _src(r.get("src"), n_sources)})
        if not columns or not rows:
            return None
        return {"title": title, "summary": _text(data.get("summary"), 400),
                "columns": columns, "rows": rows}
    if fmt == "briefing":
        sections = []
        for s in _list(data.get("sections"))[:10]:
            if not isinstance(s, dict):
                continue
            points = []
            for p in _list(s.get("points"))[:8]:
                if isinstance(p, str):
                    p = {"text": p}
                if isinstance(p, dict) and _text(p.get("text")):
                    points.append({"text": _text(p.get("text"), 500),
                                   "src": _src(p.get("src"), n_sources)})
            if points:
                sections.append({"heading": _text(s.get("heading"), 100) or "Ideas clave",
                                 "points": points})
        tldr = _text(data.get("tldr"), 800)
        conclusions = [_text(c, 400) for c in _list(data.get("conclusions")) if _text(c)]
        # La plantilla ya tiene su bloque de conclusiones: una sección con ese nombre se funde en él
        for sec in [x for x in sections if re.match(r"conclusi|resumen final", x["heading"], re.I)]:
            sections.remove(sec)
            conclusions += [p["text"] for p in sec["points"] if p["text"] not in conclusions]
        conclusions = conclusions[:6]
        if not sections and not tldr:
            return None
        return {"title": title, "tldr": tldr, "sections": sections, "conclusions": conclusions}
    if fmt == "mindmap":
        branches = []
        for b in _list(data.get("branches"))[:8]:
            if not isinstance(b, dict) or not _text(b.get("label")):
                continue
            children = []
            for c in _list(b.get("children"))[:6]:
                if isinstance(c, str):
                    c = {"label": c}
                if isinstance(c, dict) and _text(c.get("label")):
                    children.append({"label": _text(c.get("label"), 60),
                                     "detail": _text(c.get("detail"), 400),
                                     "src": _src(c.get("src"), n_sources)})
            branches.append({"label": _text(b.get("label"), 50), "children": children})
        if len(branches) < 2:
            return None
        return {"title": title, "center": _text(data.get("center"), 50) or title or "Tema",
                "branches": branches}
    if fmt == "flashcards":
        cards = []
        for c in _list(data.get("cards"))[:40]:
            if isinstance(c, dict) and _text(c.get("q")) and _text(c.get("a")):
                cards.append({"q": _text(c.get("q"), 300), "a": _text(c.get("a"), 600),
                              "src": _src(c.get("src"), n_sources)})
        if len(cards) < 2:
            return None
        return {"title": title, "cards": cards}
    if fmt == "timeline":
        events = []
        for e in _list(data.get("events"))[:40]:
            if isinstance(e, dict) and _DATE_RE.search(_text(e.get("date"))) and _text(e.get("title")):
                events.append({"date": _text(e.get("date"), 40), "title": _text(e.get("title"), 150),
                               "detail": _text(e.get("detail"), 500),
                               "src": _src(e.get("src"), n_sources)})
        if len(events) < 2:
            return None
        return {"title": title, "events": events}
    return None


# ─── Directorio de enlaces (sin modelo) ───────────────────────────────────────

def links_data(tabs: List[Any]) -> Optional[dict]:
    """Enlaces reales de las pestañas (TabContext.links), sin repetir."""
    links, seen = [], set()
    for n, tc in enumerate(tabs, start=1):
        tab_host = urlparse(tc.url).netloc.lower()
        for text, url in getattr(tc, "links", None) or []:
            if url in seen:
                continue
            seen.add(url)
            host = urlparse(url).netloc.lower()
            if not host:
                continue
            links.append({"text": _text(text, 160) or url, "url": url,
                          "domain": host[4:] if host.startswith("www.") else host,
                          "src": n, "internal": host == tab_host})
    if not links:
        return None
    return {"title": "Directorio de enlaces", "links": links}


# ─── Plantillas ───────────────────────────────────────────────────────────────

_BASE_CSS = """
:root { --bg:#0f0f23; --card:#1a1a3e; --text:#e2e8f0; --muted:#94a3b8; --accent:#6366f1;
  --accent2:#818cf8; --border:rgba(99,102,241,0.3); --card-shadow:rgba(0,0,0,0.25);
  --body-bg:radial-gradient(ellipse at 20% 0%,#1e1b4b,#0f0f23 60%); --hl:rgba(99,102,241,0.14); }
[data-theme="light"] { --bg:#f8fafc; --card:#ffffff; --text:#1e293b; --muted:#64748b;
  --accent:#4f46e5; --accent2:#6366f1; --border:rgba(99,102,241,0.2); --card-shadow:rgba(0,0,0,0.08);
  --body-bg:linear-gradient(135deg,#eef2ff,#f8fafc 60%); --hl:rgba(79,70,229,0.08); }
* { box-sizing:border-box; }
body { margin:0; font-family:system-ui,-apple-system,"Segoe UI",sans-serif; background:var(--body-bg);
  background-attachment:fixed; color:var(--text); line-height:1.5; }
header.page { padding:28px 32px 8px; max-width:1200px; margin:0 auto; }
header.page h1 { margin:0 0 4px; font-size:26px; }
header.page .sub { color:var(--muted); margin:0; font-size:14px; }
main { max-width:1200px; margin:0 auto; padding:16px 32px 32px; }
a { color:var(--accent2); }
.src { font-size:12px; color:var(--accent2); text-decoration:none; white-space:nowrap; }
.src:hover { text-decoration:underline; }
.cite { font-size:11px; vertical-align:super; text-decoration:none; margin-left:2px; }
input.search { background:var(--card); color:var(--text); border:1px solid var(--border);
  border-radius:8px; padding:8px 12px; font-size:14px; min-width:240px; }
button.btn { background:var(--card); color:var(--text); border:1px solid var(--border);
  border-radius:8px; padding:8px 14px; font-size:14px; cursor:pointer; }
button.btn:hover { border-color:var(--accent); }
button.btn.primary { background:var(--accent); color:#fff; border-color:var(--accent); }
footer.sources { max-width:1200px; margin:0 auto; padding:8px 32px 48px; color:var(--muted); font-size:13px; }
footer.sources h2 { font-size:15px; color:var(--text); }
footer.sources li { margin:4px 0; }
#themeToggle { position:fixed; top:12px; right:12px; z-index:99999; background:var(--card);
  border:1px solid var(--border); border-radius:50%; width:36px; height:36px; cursor:pointer;
  color:var(--text); display:flex; align-items:center; justify-content:center; padding:0; }
.empty { color:var(--muted); padding:24px 0; }
@media (max-width:700px) { header.page, main, footer.sources { padding-left:16px; padding-right:16px; } }
"""

_BASE_JS = r"""
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}
function source(n) { return SOURCES[n - 1] || null; }
function srcLink(n) {
  const s = source(n);
  if (!s) return null;
  const a = el('a', 'src', s.domain);
  a.href = s.url; a.title = s.title; a.target = '_blank';
  return a;
}
function cite(n) {
  const s = source(n);
  if (!s) return null;
  const a = el('a', 'cite', '[' + n + ']');
  a.href = '#fuente-' + n; a.title = s.title;
  return a;
}
document.title = DATA.title || PAGE_LABEL;
document.getElementById('pageTitle').textContent = DATA.title || PAGE_LABEL;
(function () {
  const ol = document.getElementById('sourceList');
  SOURCES.forEach((s, i) => {
    const li = el('li'); li.id = 'fuente-' + (i + 1);
    const a = el('a', null, s.title || s.url); a.href = s.url; a.target = '_blank';
    li.appendChild(a); li.appendChild(el('span', 'src', '  ' + s.domain));
    ol.appendChild(li);
  });
})();
"""

_THEME_TOGGLE = (
    '<button id="themeToggle" title="Cambiar tema claro / oscuro" onclick="document.documentElement.'
    "dataset.theme=document.documentElement.dataset.theme==='light'?'dark':'light'\">"
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 0 0 18z" '
    'fill="currentColor"/></svg></button>'
)

_TEMPLATES: Dict[str, Dict[str, str]] = {}

_TEMPLATES["compare"] = {"css": """
.toolbar { display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin-bottom:14px; }
.count { color:var(--muted); font-size:13px; }
.tablewrap { overflow-x:auto; background:var(--card); border:1px solid var(--border);
  border-radius:12px; box-shadow:0 4px 16px var(--card-shadow); }
table { border-collapse:collapse; width:100%; font-size:14px; }
th, td { padding:10px 14px; text-align:left; border-bottom:1px solid var(--border); vertical-align:top; }
thead th { position:sticky; top:0; background:var(--card); cursor:pointer; user-select:none;
  white-space:nowrap; font-size:13px; color:var(--muted); text-transform:uppercase; letter-spacing:.03em; }
thead th:hover { color:var(--text); }
thead th.sorted { color:var(--accent2); }
th .arrow { display:inline-block; width:12px; margin-left:4px; }
tbody tr:hover { background:var(--hl); }
td.name { font-weight:600; }
td.num { font-variant-numeric:tabular-nums; }
tbody tr:last-child td { border-bottom:none; }
""", "js": r"""
(function () {
  document.getElementById('pageSub').textContent = DATA.summary || '';
  const main = document.getElementById('app');
  const bar = el('div', 'toolbar');
  const q = el('input', 'search'); q.placeholder = 'Filtrar filas...';
  const count = el('span', 'count');
  bar.appendChild(q); bar.appendChild(count); main.appendChild(bar);
  const wrap = el('div', 'tablewrap'); const table = el('table');
  const thead = el('thead'); const tbody = el('tbody');
  table.appendChild(thead); table.appendChild(tbody); wrap.appendChild(table); main.appendChild(wrap);
  const headers = ['Elemento'].concat(DATA.columns).concat(['Fuente']);
  let sortCol = -1, sortDir = 1;
  function num(v) {
    const m = String(v).replace(/\s/g, '').match(/-?\d[\d.,]*/);
    if (!m) return null;
    let s = m[0];
    if (/,\d{1,2}$/.test(s)) s = s.replace(/\./g, '').replace(',', '.'); else s = s.replace(/,/g, '');
    const x = parseFloat(s);
    return isNaN(x) ? null : x;
  }
  function cell(r, c) { return c === 0 ? r.name : (r.values[c - 1] || ''); }
  const hr = el('tr');
  headers.forEach((h, i) => {
    const th = el('th', null, h);
    const arrow = el('span', 'arrow'); th.appendChild(arrow);
    if (i < headers.length - 1) {
      th.title = 'Ordenar por ' + h;
      th.onclick = () => { sortDir = (sortCol === i) ? -sortDir : 1; sortCol = i; render(); };
    }
    hr.appendChild(th);
  });
  thead.appendChild(hr);
  function render() {
    const term = q.value.toLowerCase();
    let rows = DATA.rows.filter(r => JSON.stringify(r).toLowerCase().includes(term));
    if (sortCol >= 0) {
      rows = rows.slice().sort((a, b) => {
        const x = cell(a, sortCol), y = cell(b, sortCol), nx = num(x), ny = num(y);
        if (nx !== null && ny !== null) return (nx - ny) * sortDir;
        return String(x).localeCompare(String(y), 'es', { numeric: true }) * sortDir;
      });
    }
    hr.querySelectorAll('th').forEach((th, i) => {
      th.classList.toggle('sorted', i === sortCol);
      th.querySelector('.arrow').textContent = i === sortCol ? (sortDir > 0 ? '▲' : '▼') : '';
    });
    tbody.innerHTML = '';
    rows.forEach(r => {
      const tr = el('tr');
      tr.appendChild(el('td', 'name', r.name));
      r.values.forEach(v => tr.appendChild(el('td', num(v) !== null ? 'num' : null, v)));
      const td = el('td'); const a = srcLink(r.src); if (a) td.appendChild(a); tr.appendChild(td);
      tbody.appendChild(tr);
    });
    count.textContent = rows.length + ' de ' + DATA.rows.length + ' filas';
  }
  q.oninput = render;
  render();
})();
"""}

_TEMPLATES["briefing"] = {"css": """
main.doc { display:grid; grid-template-columns:220px minmax(0,760px); gap:40px; justify-content:center; }
nav.toc { position:sticky; top:24px; align-self:start; font-size:13px; }
nav.toc h2 { font-size:12px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); }
nav.toc a { display:block; padding:4px 0; color:var(--muted); text-decoration:none; }
nav.toc a:hover { color:var(--accent2); }
article { font-size:16px; }
.tldr { background:var(--hl); border-left:4px solid var(--accent); border-radius:8px;
  padding:16px 20px; margin:8px 0 28px; }
.tldr strong { display:block; font-size:12px; text-transform:uppercase; letter-spacing:.05em;
  color:var(--accent2); margin-bottom:6px; }
article h2 { font-size:20px; margin:32px 0 10px; padding-bottom:6px; border-bottom:1px solid var(--border); }
article ul { padding-left:22px; margin:0; }
article li { margin:8px 0; }
.conclusions { margin-top:32px; background:var(--card); border:1px solid var(--border);
  border-radius:12px; padding:16px 20px; }
.conclusions h2 { border:none; margin-top:0; }
.meta { color:var(--muted); font-size:13px; }
@media (max-width:900px) { main.doc { grid-template-columns:1fr; } nav.toc { display:none; } }
""", "js": r"""
(function () {
  const main = document.getElementById('app'); main.className = 'doc';
  const words = JSON.stringify(DATA).split(/\s+/).length;
  document.getElementById('pageSub').textContent =
    SOURCES.length + ' fuentes · lectura de ' + Math.max(1, Math.round(words / 220)) + ' min';
  const toc = el('nav', 'toc'); toc.appendChild(el('h2', null, 'Contenido'));
  const art = el('article');
  if (DATA.tldr) {
    const box = el('div', 'tldr'); box.appendChild(el('strong', null, 'En pocas palabras'));
    box.appendChild(el('span', null, DATA.tldr)); art.appendChild(box);
  }
  DATA.sections.forEach((s, i) => {
    const h = el('h2', null, s.heading); h.id = 'sec-' + i; art.appendChild(h);
    const a = el('a', null, s.heading); a.href = '#sec-' + i; toc.appendChild(a);
    const ul = el('ul');
    s.points.forEach(p => {
      const li = el('li', null, p.text); const c = cite(p.src); if (c) li.appendChild(c);
      ul.appendChild(li);
    });
    art.appendChild(ul);
  });
  if (DATA.conclusions.length) {
    const box = el('section', 'conclusions'); const h = el('h2', null, 'Conclusiones'); h.id = 'sec-c';
    box.appendChild(h);
    const ul = el('ul'); DATA.conclusions.forEach(c => ul.appendChild(el('li', null, c)));
    box.appendChild(ul); art.appendChild(box);
    const a = el('a', null, 'Conclusiones'); a.href = '#sec-c'; toc.appendChild(a);
  }
  main.appendChild(toc); main.appendChild(art);
})();
"""}

_TEMPLATES["mindmap"] = {"css": """
main.map { max-width:none; padding:0 16px 16px; display:flex; gap:16px; }
.canvas { flex:1; min-height:72vh; background:var(--card); border:1px solid var(--border);
  border-radius:12px; overflow:hidden; position:relative; }
.canvas svg { width:100%; height:100%; display:block; cursor:grab; touch-action:none; }
.canvas svg.dragging { cursor:grabbing; }
.hint { position:absolute; left:12px; bottom:10px; font-size:12px; color:var(--muted); }
.node rect { stroke-width:2; }
.node text { font-size:13px; fill:var(--text); pointer-events:none; }
.node { cursor:pointer; }
.node:hover rect { filter:brightness(1.25); }
.node.active rect { stroke:var(--text); }
.edge { fill:none; stroke-width:2; opacity:.55; }
aside.detail { width:300px; background:var(--card); border:1px solid var(--border);
  border-radius:12px; padding:16px; align-self:flex-start; }
aside.detail h2 { margin:0 0 8px; font-size:18px; }
aside.detail .branch { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.05em; }
aside.detail ul { padding-left:18px; }
@media (max-width:900px) { main.map { flex-direction:column; } aside.detail { width:auto; } }
""", "js": r"""
(function () {
  const main = document.getElementById('app'); main.className = 'map';
  document.getElementById('pageSub').textContent =
    DATA.branches.length + ' ramas · pulsa un nodo para ver el detalle';
  const NS = 'http://www.w3.org/2000/svg';
  const COLORS = ['#6366f1', '#0ea5e9', '#10b981', '#f59e0b', '#ef4444', '#a855f7', '#14b8a6', '#ec4899'];
  const canvas = el('div', 'canvas'); const svg = document.createElementNS(NS, 'svg');
  canvas.appendChild(svg); canvas.appendChild(el('div', 'hint', 'Rueda: zoom · arrastrar: mover · doble clic: encajar'));
  const detail = el('aside', 'detail');
  main.appendChild(canvas); main.appendChild(detail);
  const gEdges = document.createElementNS(NS, 'g'), gNodes = document.createElementNS(NS, 'g');
  svg.appendChild(gEdges); svg.appendChild(gNodes);
  function short(t, n) { return t.length > n ? t.slice(0, n - 1) + '…' : t; }
  function node(x, y, label, color, big, onClick) {
    const g = document.createElementNS(NS, 'g'); g.setAttribute('class', 'node');
    const text = short(label, big ? 26 : 30);
    const w = Math.max(70, text.length * (big ? 9.5 : 7.4) + 28), h = big ? 46 : 32;
    const r = document.createElementNS(NS, 'rect');
    r.setAttribute('x', x - w / 2); r.setAttribute('y', y - h / 2);
    r.setAttribute('width', w); r.setAttribute('height', h); r.setAttribute('rx', h / 2);
    r.setAttribute('fill', big ? color : 'var(--bg)'); r.setAttribute('stroke', color);
    const t = document.createElementNS(NS, 'text');
    t.setAttribute('x', x); t.setAttribute('y', y + (big ? 6 : 4.5));
    t.setAttribute('text-anchor', 'middle'); t.textContent = text;
    if (big) { t.style.fontSize = '16px'; t.style.fontWeight = '700'; t.style.fill = '#fff'; }
    const tip = document.createElementNS(NS, 'title'); tip.textContent = label;
    g.appendChild(tip); g.appendChild(r); g.appendChild(t);
    g.addEventListener('click', e => { e.stopPropagation(); select(g, onClick); });
    gNodes.appendChild(g);
    return g;
  }
  function edge(x1, y1, x2, y2, color) {
    const p = document.createElementNS(NS, 'path');
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
    p.setAttribute('d', 'M' + x1 + ',' + y1 + ' Q' + (mx + (y1 - y2) * 0.15) + ',' + (my + (x2 - x1) * 0.15) + ' ' + x2 + ',' + y2);
    p.setAttribute('class', 'edge'); p.setAttribute('stroke', color);
    gEdges.appendChild(p);
  }
  function select(g, show) {
    gNodes.querySelectorAll('.node').forEach(n => n.classList.remove('active'));
    g.classList.add('active'); detail.innerHTML = ''; show();
  }
  function showCenter() {
    detail.appendChild(el('div', 'branch', 'Tema central'));
    detail.appendChild(el('h2', null, DATA.center));
    const ul = el('ul'); DATA.branches.forEach(b => ul.appendChild(el('li', null, b.label)));
    detail.appendChild(ul);
  }
  function showBranch(b) {
    detail.appendChild(el('div', 'branch', 'Rama'));
    detail.appendChild(el('h2', null, b.label));
    const ul = el('ul'); b.children.forEach(c => ul.appendChild(el('li', null, c.label)));
    detail.appendChild(ul);
  }
  function showChild(b, c) {
    detail.appendChild(el('div', 'branch', b.label));
    detail.appendChild(el('h2', null, c.label));
    if (c.detail) detail.appendChild(el('p', null, c.detail));
    const a = srcLink(c.src); if (a) { const p = el('p', null, 'Fuente: '); p.appendChild(a); detail.appendChild(p); }
  }
  const B = DATA.branches.length, R1 = 240, R2 = 470;
  DATA.branches.forEach((b, i) => {
    const color = COLORS[i % COLORS.length];
    const ang = -Math.PI / 2 + i * 2 * Math.PI / B;
    const bx = R1 * Math.cos(ang), by = R1 * Math.sin(ang);
    edge(0, 0, bx, by, color);
    const span = Math.min(2 * Math.PI / B * 0.85, 1.3), n = b.children.length;
    b.children.forEach((c, j) => {
      const a = n === 1 ? ang : ang - span / 2 + j * span / (n - 1);
      const r = R2 + (j % 2) * 50;
      const cx = r * Math.cos(a), cy = r * Math.sin(a);
      edge(bx, by, cx, cy, color);
      node(cx, cy, c.label, color, false, () => showChild(b, c));
    });
    node(bx, by, b.label, color, true, () => showBranch(b));
  });
  const center = node(0, 0, DATA.center, '#6366f1', true, showCenter);
  center.querySelector('rect').setAttribute('rx', 24);
  let vb = { x: -760, y: -620, w: 1520, h: 1240 };
  function apply() { svg.setAttribute('viewBox', vb.x + ' ' + vb.y + ' ' + vb.w + ' ' + vb.h); }
  function fit() {
    const b = gNodes.getBBox(), rect = svg.getBoundingClientRect(), pad = 30;
    let w = b.width + 2 * pad, h = b.height + 2 * pad;
    const ratio = rect.width / Math.max(rect.height, 1);
    if (w / h < ratio) w = h * ratio; else h = w / ratio;
    vb = { x: b.x + b.width / 2 - w / 2, y: b.y + b.height / 2 - h / 2, w: w, h: h }; apply();
  }
  apply(); fit();
  svg.addEventListener('dblclick', fit);
  svg.addEventListener('wheel', e => {
    e.preventDefault();
    const k = e.deltaY > 0 ? 1.12 : 0.89, rect = svg.getBoundingClientRect();
    const px = vb.x + (e.clientX - rect.left) / rect.width * vb.w;
    const py = vb.y + (e.clientY - rect.top) / rect.height * vb.h;
    vb = { x: px - (px - vb.x) * k, y: py - (py - vb.y) * k, w: vb.w * k, h: vb.h * k }; apply();
  }, { passive: false });
  let drag = null;
  svg.addEventListener('pointerdown', e => { drag = { x: e.clientX, y: e.clientY, vb: Object.assign({}, vb) }; svg.classList.add('dragging'); });
  window.addEventListener('pointermove', e => {
    if (!drag) return;
    const rect = svg.getBoundingClientRect();
    vb.x = drag.vb.x - (e.clientX - drag.x) / rect.width * vb.w;
    vb.y = drag.vb.y - (e.clientY - drag.y) / rect.height * vb.h; apply();
  });
  window.addEventListener('pointerup', () => { drag = null; svg.classList.remove('dragging'); });
  select(center, showCenter);
})();
"""}

_TEMPLATES["flashcards"] = {"css": """
main.study { max-width:760px; text-align:center; }
.progress { height:6px; background:var(--border); border-radius:3px; overflow:hidden; margin:8px 0 6px; }
.progress div { height:100%; background:var(--accent); transition:width .3s; }
.counter { color:var(--muted); font-size:13px; margin-bottom:18px; }
.scene { perspective:1200px; height:340px; margin-bottom:20px; cursor:pointer; }
.flash { position:relative; width:100%; height:100%; transition:transform .6s; transform-style:preserve-3d; }
.flash.flipped { transform:rotateY(180deg); }
.face { position:absolute; inset:0; backface-visibility:hidden; -webkit-backface-visibility:hidden;
  display:flex; flex-direction:column; align-items:center; justify-content:center; padding:32px;
  border-radius:18px; border:1px solid var(--border); background:var(--card);
  box-shadow:0 12px 40px var(--card-shadow); font-size:22px; line-height:1.4; }
.face.back { transform:rotateY(180deg); background:var(--hl); font-size:19px; }
.face .tag { position:absolute; top:14px; left:18px; font-size:12px; color:var(--muted);
  text-transform:uppercase; letter-spacing:.05em; }
.face .src { position:absolute; bottom:14px; right:18px; }
.controls { display:flex; gap:10px; justify-content:center; flex-wrap:wrap; margin-bottom:12px; }
.score { color:var(--muted); font-size:13px; }
.done { background:var(--card); border:1px solid var(--border); border-radius:18px; padding:40px; }
.done h2 { margin-top:0; }
""", "js": r"""
(function () {
  const main = document.getElementById('app'); main.className = 'study';
  document.getElementById('pageSub').textContent =
    DATA.cards.length + ' tarjetas · pulsa la tarjeta o la barra espaciadora para girarla';
  let deck = DATA.cards.slice(), idx = 0, known = new Set(), review = new Set();
  const prog = el('div', 'progress'); const bar = el('div'); prog.appendChild(bar);
  const counter = el('div', 'counter');
  const scene = el('div', 'scene'); const flash = el('div', 'flash');
  const front = el('div', 'face front'), back = el('div', 'face back');
  flash.appendChild(front); flash.appendChild(back); scene.appendChild(flash);
  const controls = el('div', 'controls'); const score = el('div', 'score');
  function button(label, cls, fn) { const b = el('button', 'btn ' + (cls || ''), label); b.onclick = fn; controls.appendChild(b); return b; }
  button('Anterior', '', () => go(-1));
  button('Girar', '', flip);
  button('Repasar', '', () => mark(false));
  button('Lo sabía', 'primary', () => mark(true));
  button('Siguiente', '', () => go(1));
  button('Barajar', '', shuffle);
  [prog, counter, scene, controls, score].forEach(x => main.appendChild(x));
  scene.onclick = flip;
  function flip() { flash.classList.toggle('flipped'); }
  function face(box, tag, text, src) {
    box.innerHTML = ''; box.appendChild(el('span', 'tag', tag)); box.appendChild(el('div', null, text));
    const a = srcLink(src); if (a) box.appendChild(a);
  }
  function show() {
    const c = deck[idx];
    flash.classList.remove('flipped');
    face(front, 'Pregunta', c.q, null); face(back, 'Respuesta', c.a, c.src);
    counter.textContent = 'Tarjeta ' + (idx + 1) + ' de ' + deck.length;
    bar.style.width = ((idx + 1) / deck.length * 100) + '%';
    score.textContent = 'Lo sabías: ' + known.size + ' · Para repasar: ' + review.size;
  }
  function go(d) {
    if (idx + d >= deck.length) { finish(); return; }
    idx = Math.max(0, idx + d); show();
  }
  function mark(ok) {
    const c = deck[idx];
    (ok ? known : review).add(c); (ok ? review : known).delete(c); go(1);
  }
  function shuffle() {
    for (let i = deck.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [deck[i], deck[j]] = [deck[j], deck[i]]; }
    idx = 0; show();
  }
  function finish() {
    main.innerHTML = '';
    const box = el('div', 'done'); box.appendChild(el('h2', null, 'Has terminado el mazo'));
    box.appendChild(el('p', null, 'Lo sabías: ' + known.size + ' de ' + DATA.cards.length + '. Para repasar: ' + review.size + '.'));
    const again = el('button', 'btn primary', 'Repasar las que fallé');
    again.disabled = review.size === 0;
    again.onclick = () => { deck = Array.from(review); restart(); };
    const all = el('button', 'btn', 'Empezar de nuevo');
    all.onclick = () => { deck = DATA.cards.slice(); restart(); };
    const row = el('div', 'controls'); row.appendChild(again); row.appendChild(all); box.appendChild(row);
    main.appendChild(box);
  }
  function restart() {
    idx = 0; known = new Set(); review = new Set(); main.innerHTML = '';
    [prog, counter, scene, controls, score].forEach(x => main.appendChild(x)); show();
  }
  document.addEventListener('keydown', e => {
    if (e.target.tagName === 'INPUT') return;
    if (e.code === 'Space') { e.preventDefault(); flip(); }
    else if (e.code === 'ArrowRight') go(1);
    else if (e.code === 'ArrowLeft') go(-1);
  });
  show();
})();
"""}

_TEMPLATES["timeline"] = {"css": """
.toolbar { margin-bottom:20px; }
.tl { position:relative; max-width:980px; margin:0 auto; }
.tl::before { content:''; position:absolute; left:50%; top:0; bottom:0; width:3px;
  background:linear-gradient(var(--accent), var(--accent2)); transform:translateX(-50%); border-radius:2px; }
.era { position:relative; text-align:center; margin:28px 0 12px; }
.era span { background:var(--accent); color:#fff; padding:4px 14px; border-radius:14px; font-size:13px; font-weight:600; }
.ev { position:relative; width:50%; padding:10px 36px; }
.ev.left { left:0; text-align:right; }
.ev.right { left:50%; }
.ev::after { content:''; position:absolute; top:22px; width:14px; height:14px; border-radius:50%;
  background:var(--bg); border:3px solid var(--accent); }
.ev.left::after { right:-8.5px; }
.ev.right::after { left:-8.5px; }
.box { display:inline-block; text-align:left; background:var(--card); border:1px solid var(--border);
  border-radius:12px; padding:12px 16px; box-shadow:0 4px 16px var(--card-shadow); max-width:100%; }
.date { font-weight:700; color:var(--accent2); font-size:15px; }
.box h3 { margin:2px 0 6px; font-size:16px; }
.box p { margin:0 0 6px; color:var(--muted); font-size:14px; }
@media (max-width:760px) {
  .tl::before { left:10px; } .ev, .ev.right { width:100%; left:0; padding-left:36px; padding-right:0; text-align:left; }
  .ev.left::after, .ev.right::after { left:3px; right:auto; } .era { text-align:left; padding-left:24px; }
}
""", "js": r"""
(function () {
  const main = document.getElementById('app');
  function roman(r) {
    const v = { I: 1, V: 5, X: 10, L: 50, C: 100 }; let n = 0;
    for (let i = 0; i < r.length; i++) { const a = v[r[i]], b = v[r[i + 1]] || 0; n += a < b ? -a : a; }
    return n;
  }
  function year(d) {
    const m = String(d).match(/\d{1,4}/);
    const c = String(d).match(/siglo\s+([IVXLC]+)/i);
    if (!m && c) {
      const y = (roman(c[1].toUpperCase()) - 1) * 100 + 50;
      return /a\.?\s?c\.?|antes de cristo/i.test(d) ? -y : y;
    }
    if (!m) return null;
    let y = parseInt(m[0], 10);
    if (/a\.?\s?c\.?|antes de cristo|\bbc\b/i.test(d)) y = -y;
    return y;
  }
  const events = DATA.events.map((e, i) => Object.assign({ y: year(e.date), i: i }, e));
  events.sort((a, b) => (a.y === null || b.y === null) ? a.i - b.i : (a.y - b.y) || (a.i - b.i));
  const dated = events.filter(e => e.y !== null);
  document.getElementById('pageSub').textContent = events.length + ' acontecimientos' +
    (dated.length ? ' · de ' + dated[0].date + ' a ' + dated[dated.length - 1].date : '');
  const bar = el('div', 'toolbar'); const q = el('input', 'search'); q.placeholder = 'Buscar en la línea de tiempo...';
  bar.appendChild(q); main.appendChild(bar);
  const tl = el('div', 'tl'); main.appendChild(tl);
  function era(y) {
    if (y === null) return 'Sin fecha exacta';
    if (y < 0) return 'Antes de Cristo';
    let c = Math.floor((y - 1) / 100) + 1, r = '';
    [[10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I']].forEach(([v, s]) => { while (c >= v) { r += s; c -= v; } });
    return 'Siglo ' + r;
  }
  function render() {
    const term = q.value.toLowerCase(); tl.innerHTML = '';
    let last = null, side = 0;
    events.filter(e => JSON.stringify(e).toLowerCase().includes(term)).forEach(e => {
      const label = era(e.y);
      if (label !== last) { const d = el('div', 'era'); d.appendChild(el('span', null, label)); tl.appendChild(d); last = label; }
      const ev = el('div', 'ev ' + (side++ % 2 ? 'right' : 'left'));
      const box = el('div', 'box');
      box.appendChild(el('div', 'date', e.date)); box.appendChild(el('h3', null, e.title));
      if (e.detail) box.appendChild(el('p', null, e.detail));
      const a = srcLink(e.src); if (a) box.appendChild(a);
      ev.appendChild(box); tl.appendChild(ev);
    });
    if (!tl.children.length) tl.appendChild(el('p', 'empty', 'Ningún acontecimiento coincide.'));
  }
  q.oninput = render; render();
})();
"""}

_TEMPLATES[FORMAT_LINKS] = {"css": """
main.dir { display:grid; grid-template-columns:260px minmax(0,1fr); gap:24px; }
aside.domains { position:sticky; top:16px; align-self:start; max-height:calc(100vh - 32px); overflow:auto;
  background:var(--card); border:1px solid var(--border); border-radius:12px; padding:8px;
  scrollbar-color:var(--border) transparent; scrollbar-width:thin; }
aside.domains button { display:flex; justify-content:space-between; width:100%; gap:8px; background:none;
  border:none; color:var(--text); padding:7px 10px; border-radius:8px; cursor:pointer; font-size:13px; text-align:left; }
aside.domains button:hover { background:var(--hl); }
aside.domains button.on { background:var(--accent); color:#fff; }
aside.domains .n { color:inherit; opacity:.7; font-variant-numeric:tabular-nums; }
.toolbar { display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin-bottom:12px; }
.toolbar label { font-size:13px; color:var(--muted); display:flex; gap:6px; align-items:center; }
.count { color:var(--muted); font-size:13px; }
ul.links { list-style:none; padding:0; margin:0; }
ul.links li { padding:9px 12px; border-bottom:1px solid var(--border); display:flex; gap:12px; align-items:baseline; }
ul.links li:hover { background:var(--hl); }
ul.links .txt { flex:1; min-width:0; }
ul.links .txt a { text-decoration:none; font-weight:500; }
ul.links .url { display:block; color:var(--muted); font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
@media (max-width:800px) { main.dir { grid-template-columns:1fr; } aside.domains { position:static; max-height:220px; } }
""", "js": r"""
(function () {
  const main = document.getElementById('app'); main.className = 'dir';
  const byDomain = {};
  DATA.links.forEach(l => { byDomain[l.domain] = (byDomain[l.domain] || 0) + 1; });
  const domains = Object.keys(byDomain).sort((a, b) => byDomain[b] - byDomain[a] || a.localeCompare(b));
  document.getElementById('pageSub').textContent =
    DATA.links.length + ' enlaces de ' + domains.length + ' dominios en ' + SOURCES.length + ' pestañas';
  let current = null;
  const side = el('aside', 'domains'); const right = el('div');
  main.appendChild(side); main.appendChild(right);
  function domainButton(name, n) {
    const b = el('button'); b.appendChild(el('span', null, name || 'Todos los dominios'));
    b.appendChild(el('span', 'n', String(n)));
    b.onclick = () => { current = name; render(); };
    b.dataset.domain = name || ''; side.appendChild(b);
  }
  domainButton(null, DATA.links.length);
  domains.forEach(d => domainButton(d, byDomain[d]));
  const bar = el('div', 'toolbar'); const q = el('input', 'search'); q.placeholder = 'Buscar enlaces...';
  const lab = el('label'); const ext = el('input'); ext.type = 'checkbox';
  lab.appendChild(ext); lab.appendChild(document.createTextNode('Solo enlaces a otros sitios'));
  const count = el('span', 'count');
  bar.appendChild(q); bar.appendChild(lab); bar.appendChild(count); right.appendChild(bar);
  const ul = el('ul', 'links'); right.appendChild(ul);
  function render() {
    side.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.domain === (current || '')));
    const term = q.value.toLowerCase(); ul.innerHTML = '';
    const rows = DATA.links.filter(l => (!current || l.domain === current) && (!ext.checked || !l.internal) &&
      (l.text + ' ' + l.url).toLowerCase().includes(term));
    rows.slice(0, 1500).forEach(l => {
      const li = el('li'); const box = el('div', 'txt');
      const a = el('a', null, l.text); a.href = l.url; a.target = '_blank'; box.appendChild(a);
      box.appendChild(el('span', 'url', l.url)); li.appendChild(box);
      const c = cite(l.src); if (c) li.appendChild(c);
      ul.appendChild(li);
    });
    if (!rows.length) ul.appendChild(el('li', 'empty', 'Ningún enlace coincide.'));
    count.textContent = rows.length + ' enlaces';
  }
  q.oninput = render; ext.onchange = render; render();
})();
"""}


def _json_for_script(obj) -> str:
    return (json.dumps(obj, ensure_ascii=False)
            .replace("</", "<\\/")
            .replace("<!--", "<\\!--"))


def build_page(fmt: str, data: dict, sources: List[dict]) -> str:
    """Página completa del formato. sources: [{url, title, domain}] en orden de TAB."""
    tpl = _TEMPLATES[fmt]
    label = FORMATS[fmt]["label"]
    script = (f"const DATA = {_json_for_script(data)};\n"
              f"const SOURCES = {_json_for_script(sources)};\n"
              f"const PAGE_LABEL = {_json_for_script(label)};\n"
              + _BASE_JS + tpl["js"])
    return (
        "<!DOCTYPE html>\n<html lang=\"es\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{label}</title>\n<style>{_BASE_CSS}{tpl['css']}</style>\n</head>\n<body>\n"
        f"{_THEME_TOGGLE}\n"
        "<header class=\"page\"><h1 id=\"pageTitle\"></h1><p class=\"sub\" id=\"pageSub\"></p></header>\n"
        "<main id=\"app\"></main>\n"
        "<footer class=\"sources\"><h2>Fuentes</h2><ol id=\"sourceList\"></ol></footer>\n"
        f"<script>\n{script}\n</script>\n</body>\n</html>\n"
    )
