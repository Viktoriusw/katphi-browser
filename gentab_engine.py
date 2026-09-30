#!/usr/bin/env python3
"""
GenTab Engine - Motor de Pestañas Generativas para Katphi Browser

Inspirado en Google Disco GenTabs: extrae contexto de todas las pestañas abiertas,
lo envía a un LLM y genera aplicaciones web interactivas personalizadas.
"""

import html as _html_escape
import json
import time
import hashlib
import requests
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
from urllib.parse import urlparse
from bs4 import BeautifulSoup

from PySide6.QtCore import QObject, Signal, QThread, QSettings
from llm_client import (
    LLMClient, LLMConfig, LLMError, PROVIDER_LOCAL, PROVIDER_LLMAPI, PROVIDER_OLLAMA,
    OPENAI_COMPAT_PROVIDERS,
)
from constants import (
    GENTAB_MAX_CONTENT_PER_TAB,
    GENTAB_MAX_TOTAL_CONTEXT,
    GENTAB_DEFAULT_TEMPERATURE,
    GENTAB_DEFAULT_MAX_TOKENS,
)

logger = logging.getLogger(__name__)


class GenTabStatus(Enum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    GENERATING = "generating"
    READY = "ready"
    ERROR = "error"


@dataclass
class TabContext:
    """Contexto extraído de una pestaña individual."""
    index: int
    url: str
    title: str
    content: str
    content_length: int
    domain: str
    extracted_at: str = ""

    def __post_init__(self):
        if not self.extracted_at:
            self.extracted_at = datetime.now().isoformat()


@dataclass
class GenTabResult:
    """Resultado de una GenTab generada."""
    id: str
    title: str
    html: str
    prompt: str
    source_tabs: List[Dict[str, str]]
    created_at: str
    status: GenTabStatus = GenTabStatus.READY
    generation_time: float = 0.0
    model_used: str = ""
    token_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['status'] = self.status.value
        return result


class ContentExtractor:
    """Extrae y limpia contenido de páginas web."""

    MAX_CONTENT_PER_TAB = GENTAB_MAX_CONTENT_PER_TAB
    MAX_TOTAL_CONTEXT = GENTAB_MAX_TOTAL_CONTEXT

    _SEARCH_ENGINE_DOMAINS = (
        "google.com", "google.es", "duckduckgo.com", "bing.com",
        "yahoo.com", "yandex.com", "baidu.com", "ecosia.org",
        "startpage.com", "search.brave.com",
    )

    @staticmethod
    def _is_search_engine(url: str) -> bool:
        """Detecta si la URL es de un motor de búsqueda."""
        try:
            host = urlparse(url).netloc.lower()
            return any(se in host for se in ContentExtractor._SEARCH_ENGINE_DOMAINS)
        except Exception:
            return False
    @staticmethod
    def _resolve_search_links(soup: BeautifulSoup, page_url: str) -> List[str]:
        """Extrae URLs reales de páginas de resultados de búsqueda.

        En vez de capturar los links de redirección del buscador, extrae
        las URLs destino reales que el usuario quiere visitar.
        """
        real_links = []
        base_domain = ""
        try:
            base_domain = urlparse(page_url).netloc.lower()
        except Exception:
            pass
        for a in soup.find_all('a', href=True):
            href = a['href']
            link_text = a.get_text(strip=True)

            if not link_text or len(link_text) < 4:
                continue
            # Ignorar links internos del propio buscador
            if href.startswith('/') or href.startswith('#'):
                continue
            try:
                link_domain = urlparse(href).netloc.lower()
            except Exception:
                continue
            # Saltar links que son del propio buscador
            if any(se in link_domain for se in ContentExtractor._SEARCH_ENGINE_DOMAINS):
                continue
            # Saltar links internos de navegación del buscador
            if base_domain and link_domain == base_domain:
                continue
            if href.startswith('http') and link_text:
                real_links.append(f"{link_text}: {href}")
        return real_links[:20]
    @staticmethod
    def extract_from_html(html: str, url: str, title: str) -> str:
        try:
            soup = BeautifulSoup(html, 'lxml')
        except Exception:
            soup = BeautifulSoup(html, 'html.parser')
        is_search = ContentExtractor._is_search_engine(url)

        for tag in soup(['script', 'style', 'nav', 'footer', 'aside',
                         'iframe', 'noscript', 'svg', 'form', 'input',
                         'button', 'select', 'textarea']):
            tag.decompose()
        headings = []
        for h in soup.find_all(['h1', 'h2', 'h3']):
            text = h.get_text(strip=True)
            if text:
                level = h.name
                headings.append(f"[{level.upper()}] {text}")
        if is_search:
            links = ContentExtractor._resolve_search_links(soup, url)
        else:
            links = []
            for a in soup.find_all('a', href=True):
                href = a['href']
                link_text = a.get_text(strip=True)
                if link_text and len(link_text) > 3 and href.startswith('http'):
                    links.append(f"{link_text}: {href}")
            links = links[:15]
        images = []
        for img in soup.find_all('img', alt=True):
            alt = img.get('alt', '').strip()
            if alt and len(alt) > 3:
                images.append(alt)
        main_content = soup.find('main') or soup.find('article') or soup.find('body')
        text = main_content.get_text(separator='\n', strip=True) if main_content else ""

        lines = [l.strip() for l in text.split('\n') if l.strip() and len(l.strip()) > 5]
        clean_text = '\n'.join(lines)

        sections = [f"TITLE: {title}", f"URL: {url}"]
        if headings:
            sections.append("HEADINGS:\n" + '\n'.join(headings[:15]))
        sections.append(f"CONTENT:\n{clean_text[:ContentExtractor.MAX_CONTENT_PER_TAB]}")
        if images:
            sections.append("IMAGES: " + ', '.join(images[:10]))
        if links:
            sections.append("LINKS (real destination URLs):\n" + '\n'.join(links))
        return '\n\n'.join(sections)
    @staticmethod
    def get_domain(url: str) -> str:
        try:
            parsed = urlparse(url)
            return parsed.netloc or url
        except Exception:
            return url


class GenTabWorker(QThread):
    """Worker thread para generar GenTabs sin bloquear la UI."""
    progress = Signal(str)
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, server_url: str, prompt: str, tab_contexts: List[TabContext],
                 temperature: float = 0.7, max_tokens: int = 4000,
                 llm_config: Optional[LLMConfig] = None):
        super().__init__()
        self.server_url = server_url
        self.prompt = prompt
        self.tab_contexts = tab_contexts
        self.temperature = temperature
        self.max_tokens = max_tokens
        if llm_config is not None:
            self.llm_config = llm_config
        else:
            cfg = LLMConfig()
            cfg.local_url = server_url
            cfg.temperature = temperature
            cfg.max_tokens = max_tokens
            self.llm_config = cfg
        self._model_ctx_window = 4096
    _CTX_OVERHEAD_TOKENS = 500
    _MIN_CONTEXT_CHARS = 800
    _MAX_INITIAL_CONTEXT_CHARS = 10000
    _CONTEXT_SHRINK_FACTOR = 0.75
    _OUTPUT_RESERVE_TOKENS = 200
    _MIN_OUTPUT_TOKENS = 3500

    def run(self):
        try:
            client = LLMClient(self.llm_config)
            system_prompt = self._build_system_prompt()

            self._model_ctx_window = client.detect_context_window()

            # Reservar al menos _MIN_OUTPUT_TOKENS para la respuesta HTML
            desired_output = max(self.max_tokens, self._MIN_OUTPUT_TOKENS)
            max_input_tokens = self._model_ctx_window - desired_output - self._CTX_OVERHEAD_TOKENS

            self.progress.emit("Construyendo contexto multi-tab...")
            context_budget = min(ContentExtractor.MAX_TOTAL_CONTEXT, self._MAX_INITIAL_CONTEXT_CHARS)
            context_text = self._build_context(max_total_chars=context_budget)
            user_prompt = self._build_user_prompt(context_text)
            prompt_tokens = self._estimate_tokens(system_prompt) + self._estimate_tokens(user_prompt)

            while prompt_tokens > max_input_tokens and context_budget > self._MIN_CONTEXT_CHARS:
                context_budget = max(self._MIN_CONTEXT_CHARS, int(context_budget * self._CONTEXT_SHRINK_FACTOR))
                context_text = self._build_context(max_total_chars=context_budget)
                user_prompt = self._build_user_prompt(context_text)
                prompt_tokens = self._estimate_tokens(system_prompt) + self._estimate_tokens(user_prompt)
            self.progress.emit(
                f"Contexto: {len(context_text)} chars de {len(self.tab_contexts)} pestañas "
                f"(ventana: {self._model_ctx_window} tokens)"
            )

            safe_max_tokens = max(
                self._MIN_OUTPUT_TOKENS,
                min(desired_output, self._model_ctx_window - prompt_tokens - self._OUTPUT_RESERVE_TOKENS),
            )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            self.progress.emit(f"Generando aplicación (max {safe_max_tokens} tokens de salida)...")
            start_time = time.time()

            raw_content = client.chat(messages, max_tokens=safe_max_tokens, temperature=self.temperature)
            generation_time = time.time() - start_time

            html = self._extract_html(raw_content)

            if not html:
                html = self._build_fallback_html(raw_content or "No se pudo generar contenido.")
                self.progress.emit("Respuesta sin HTML válido. Usando fallback de texto.")
            if self._is_html_visually_empty(html):
                self.progress.emit("HTML vacío. Construyendo resumen interactivo local.")
                html = self._build_local_summary_html()
            html = self._inject_source_links(html)
            if self.llm_config.provider == PROVIDER_LLMAPI:
                model_name = self.llm_config.llmapi_model
            elif self.llm_config.provider == PROVIDER_OLLAMA:
                model_name = f"ollama:{self.llm_config.ollama_model or 'auto'}"
            elif self.llm_config.provider in OPENAI_COMPAT_PROVIDERS:
                model_name = f"{self.llm_config.provider}:{self.llm_config.compat_model(self.llm_config.provider)}"
            else:
                model_name = "local"
            logger.info(
                "GenTab ready | html_len=%s | model=%s | prompt_tokens~%s | max_tokens=%s",
                len(html or ""), model_name, prompt_tokens, safe_max_tokens,
            )
            self.progress.emit("GenTab generada exitosamente")

            gen_id = hashlib.md5(f"{self.prompt}{time.time()}".encode()).hexdigest()[:12]

            result = GenTabResult(
                id=gen_id,
                title=self._generate_title(raw_content),
                html=html,
                prompt=self.prompt,
                source_tabs=[{"url": tc.url, "title": tc.title, "domain": tc.domain}
                             for tc in self.tab_contexts],
                created_at=datetime.now().isoformat(),
                generation_time=round(generation_time, 2),
                model_used=model_name,
                token_count=0,
            )

            self.finished.emit(result)
        except LLMError as e:
            self.error.emit(str(e))
        except requests.exceptions.ConnectionError:
            self.error.emit("No se pudo conectar al servidor LLM. Verifica que LM Studio u Ollama esté ejecutándose.")
        except requests.exceptions.Timeout:
            self.error.emit("Timeout: el servidor tardó demasiado en responder.")
        except Exception as e:
            self.error.emit(f"Error inesperado: {str(e)}")
    def _build_context(self, max_total_chars: Optional[int] = None) -> str:
        sections = []
        total = 0
        limit = max_total_chars if max_total_chars is not None else ContentExtractor.MAX_TOTAL_CONTEXT
        per_tab = limit // max(len(self.tab_contexts), 1)
        for tc in self.tab_contexts:
            if total >= limit:
                break
            remaining = limit - total
            chunk_limit = min(per_tab, ContentExtractor.MAX_CONTENT_PER_TAB, remaining)
            chunk = tc.content[:chunk_limit]
            sections.append(
                f"--- TAB {tc.index + 1} ---\n"
                f"Title: {tc.title}\n"
                f"URL: {tc.url}\n"
                f"Domain: {tc.domain}\n"
                f"{chunk}"
            )
            total += len(chunk)
        return '\n\n'.join(sections)
    def _build_system_prompt(self) -> str:
        return """You are GenTab. Transform browser tab data into a complete, working single-page HTML app.

RULES (non-negotiable):
- Output ONLY a complete HTML document starting with <!DOCTYPE html> and ending with </html>.
- No markdown, no explanations, no code fences around the HTML.
- ALL CSS inside <style>, ALL JS inside <script>. No external CDN links.
- Use ONLY real URLs from the data for links — never invent URLs.

BUILD STRATEGY (follow this order):
1. Read the raw tab data and extract structured items: titles, descriptions, prices, dates, URLs, key facts.
2. Put ALL extracted data in a JS const array at the top of your <script> (one object per item/article/result).
3. Write a render() function that loops over the array and creates HTML cards/rows for each item.
4. Call render() on load. Add a search <input> that filters items and re-renders.

VISUAL STYLE (DUAL THEME — mandatory):
- Use CSS variables in :root for ALL colors. Define TWO sets:
  - Dark (default): :root { --bg:#0f0f23; --card:#1a1a3e; --text:#e2e8f0; --muted:#94a3b8; --accent:#6366f1; --accent2:#818cf8; --border:rgba(99,102,241,0.3); --card-shadow:rgba(0,0,0,0.25); --body-bg:radial-gradient(ellipse at 20% 0%,#1e1b4b,#0f0f23 60%); }
  - Light: [data-theme="light"] { --bg:#f8fafc; --card:#ffffff; --text:#1e293b; --muted:#64748b; --accent:#4f46e5; --accent2:#6366f1; --border:rgba(99,102,241,0.2); --card-shadow:rgba(0,0,0,0.08); --body-bg:linear-gradient(135deg,#eef2ff,#f8fafc 60%); }
- body { background:var(--body-bg); color:var(--text); }
- Cards: background:var(--card); border:1px solid var(--border); border-radius:12px; padding:16px; margin:8px; transition:transform .15s; box-shadow:0 4px 16px var(--card-shadow);
- Card hover: transform:translateY(-3px); border-color:var(--accent);
- Layout: CSS grid, 2-3 columns on wide screens, 1 column on mobile
- Font: system-ui
- REQUIRED: Add a floating theme toggle button in the top-right corner:
  <button id="themeToggle" onclick="document.documentElement.dataset.theme=document.documentElement.dataset.theme==='light'?'dark':'light'" style="position:fixed;top:12px;right:12px;z-index:99999;background:var(--card);border:1px solid var(--border);border-radius:50%;width:36px;height:36px;cursor:pointer;font-size:18px;color:var(--text);display:flex;align-items:center;justify-content:center;"></button>

SOURCE ATTRIBUTION (required):
- Each card/item MUST include a small "Source: [domain]" label that links to the original URL.
- At the end of the page, add a "Sources" section listing all source URLs with their titles.

IMPORTANT: Prioritize DATA RICHNESS over visual complexity. Fill every card with real content from the tabs. An app with 10 filled cards is far better than a pretty empty shell."""

    def _build_user_prompt(self, context: str) -> str:
        request = (self.prompt or "").strip()
        if len(request) > 800:
            request = request[:800] + "..."
        source_list = '\n'.join(
            f"Tab{tc.index + 1}: {tc.title} — {tc.url}"
            for tc in self.tab_contexts[:10]
        )
        return f"""TASK: {request}

SOURCE URLs (use only these, do not invent):
{source_list}

TAB CONTENT TO PROCESS:
{context}

OUTPUT: A single HTML document. Follow this structure EXACTLY:
<!DOCTYPE html><html lang="es"><head>...</head>
<body>
  <!-- header with title and search input -->
  <!-- card grid -->
<script>
const DATA = [
  // ← Fill this array with ALL items/articles/results extracted from the tab content above.
  // Each object: {{ title, description, url, tag, date, price, source_url, source_domain }}
  // MUST include source_url and source_domain from the original tab for each item.
  // Extract AT LEAST 5 items. If the tab has a list, extract every list item.
];
function render(items) {{
  // Loop over items, create card elements, append to grid
  // Each card MUST show: <a class="source" href="${{d.source_url}}">${{d.source_domain}}</a>
}}
render(DATA);
document.getElementById('search').oninput = e => render(DATA.filter(d => JSON.stringify(d).toLowerCase().includes(e.target.value.toLowerCase())));
</script>
</body></html>

After the card grid, include a <footer> section titled "Fuentes" listing all source URLs as links.

Start writing now. Output ONLY the HTML, starting with <!DOCTYPE html>."""

    def _estimate_tokens(self, text: str) -> int:
        """Estimación rápida para ajustar presupuesto (aprox 1 token cada 4 chars)."""
        return max(1, int(len(text or "") / 4))
    # _detect_context_window movido a LLMClient.detect_context_window()

    def _extract_html(self, raw: str) -> str:
        raw = raw.strip()

        for fence in ['```html', '```HTML']:
            if fence in raw:
                start = raw.index(fence) + len(fence)
                end = raw.rfind('```')
                if end > start:
                    raw = raw[start:end].strip()
                break
        if raw.startswith('```'):
            raw = raw[3:]
            if raw.endswith('```'):
                raw = raw[:-3]
            raw = raw.strip()
        if not raw.strip().startswith('<!DOCTYPE') and not raw.strip().startswith('<html'):
            if '<html' in raw:
                idx = raw.index('<html')
                raw = raw[idx:]
            elif '<body' in raw:
                raw = f"<!DOCTYPE html><html><head><meta charset='UTF-8'></head>{raw}</html>"
        if '<html' not in raw.lower() and '<body' not in raw.lower() and '<div' in raw.lower():
            raw = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GenTab</title></head>
<body>{raw}</body></html>"""

        # Si sigue sin contener estructura HTML útil, devolver vacío para fallback
        has_html = ("<html" in raw.lower()) or ("<body" in raw.lower()) or ("<div" in raw.lower())
        return raw if has_html else ""
    def _build_fallback_html(self, text: str) -> str:
        """Construye HTML con formato cuando la IA devuelve texto plano."""
        safe_text = _html_escape.escape(text or "")
        # Convertir listas con guiones/asteriscos en <li>
        lines = safe_text.split("\n")
        formatted_lines = []
        in_list = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(("- ", "* ", "• ")):
                if not in_list:
                    formatted_lines.append("<ul>")
                    in_list = True
                formatted_lines.append(f"<li>{stripped[2:]}</li>")
            else:
                if in_list:
                    formatted_lines.append("</ul>")
                    in_list = False
                if stripped:
                    formatted_lines.append(f"<p>{stripped}</p>")
        if in_list:
            formatted_lines.append("</ul>")
        body_content = "\n".join(formatted_lines)

        title = _html_escape.escape(self._generate_title(self.prompt or "GenTab"))
        return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{ --bg:#0f0f23; --card:#1a1a3e; --text:#e2e8f0; --muted:#94a3b8;
             --accent:#6366f1; --border:rgba(99,102,241,0.3);
             --card-shadow:rgba(0,0,0,0.25);
             --body-bg:radial-gradient(ellipse at 20% 0%,#1e1b4b,#0f0f23 60%); }}
    [data-theme="light"] {{ --bg:#f8fafc; --card:#ffffff; --text:#1e293b; --muted:#64748b;
             --accent:#4f46e5; --border:rgba(99,102,241,0.2);
             --card-shadow:rgba(0,0,0,0.08);
             --body-bg:linear-gradient(135deg,#eef2ff,#f8fafc 60%); }}
    body {{
      font-family: system-ui, -apple-system, sans-serif;
      margin: 0; padding: 24px;
      background: var(--body-bg); color: var(--text);
    }}
    .container {{ max-width: 800px; margin: 0 auto; }}
    h1 {{ font-size: 24px; margin-bottom: 8px; }}
    .meta {{ color: var(--muted); font-size: 13px; margin-bottom: 20px; }}
    .content {{
      background: var(--card); border: 1px solid var(--border);
      border-radius: 16px; padding: 24px; line-height: 1.7;
      box-shadow: 0 8px 24px var(--card-shadow);
    }}
    .content p {{ margin: 0 0 12px; }}
    .content ul {{ padding-left: 20px; margin: 0 0 12px; }}
    .content li {{ margin-bottom: 6px; }}
    #themeToggle {{ position:fixed; top:12px; right:12px; z-index:99999;
      background:var(--card); border:1px solid var(--border); border-radius:50%;
      width:36px; height:36px; cursor:pointer; font-size:18px; color:var(--text);
      display:flex; align-items:center; justify-content:center; transition:all .3s; }}
    #themeToggle:hover {{ border-color:var(--accent); }}
  </style>
</head>
<body>
  <button id="themeToggle" onclick="document.documentElement.dataset.theme=document.documentElement.dataset.theme==='light'?'dark':'light'"></button>
  <div class="container">
    <h1>{title}</h1>
    <div class="meta">Generado por GenTab a partir de {len(self.tab_contexts)} pestañas</div>
    <div class="content">{body_content}</div>
  </div>
</body>
</html>"""

    def _is_html_visually_empty(self, html: str) -> bool:
        """Detecta HTML técnicamente válido pero sin contenido útil visible."""
        try:
            if not html or len(html.strip()) < 80:
                return True
            soup = BeautifulSoup(html, "html.parser")
            body = soup.find("body")
            if body is None:
                return True
            text = body.get_text(" ", strip=True)
            has_meaningful_text = len(text) >= 30
            has_structural_content = bool(body.find(["table", "ul", "ol", "article", "section", "main", "p", "h1", "h2", "h3"]))
            return not (has_meaningful_text or has_structural_content)
        except Exception:
            return False
    def _build_local_summary_html(self) -> str:
        """Fallback local interactivo con búsqueda, filtros y vista grid/lista."""
        import json as _json
        title = _html_escape.escape(self._generate_title(self.prompt or "GenTab"))

        items_data = []
        for tc in self.tab_contexts[:12]:
            raw = (tc.content or "")
            clean_lines = []
            skip_prefixes = (
                "TITLE:", "URL:", "HEADINGS:", "CONTENT:", "IMAGES:",
                "LINKS (real", "KEY LINKS:", "=== TAB",
            )
            for line in raw.split("\n"):
                stripped = line.strip()
                if any(stripped.startswith(p) for p in skip_prefixes):
                    continue
                if stripped.startswith("[H") and "]" in stripped[:6]:
                    continue
                if stripped:
                    clean_lines.append(stripped)
            clean_text = " ".join(clean_lines)[:400]
            items_data.append({
                "title": tc.title or tc.domain or "Pestaña",
                "domain": tc.domain or "",
                "url": tc.url or "",
                "excerpt": clean_text or "Sin contenido disponible.",
            })
        items_json = _json.dumps(items_data, ensure_ascii=False)

        return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{ --bg:#0f0f23; --card:#1a1a3e; --text:#e2e8f0; --muted:#94a3b8;
             --accent:#6366f1; --accent2:#818cf8; --border:rgba(99,102,241,0.3);
             --card-shadow:rgba(0,0,0,0.2);
             --body-bg:radial-gradient(ellipse at 20% 0%,#1e1b4b,#0f0f23 60%); }}
    [data-theme="light"] {{ --bg:#f8fafc; --card:#ffffff; --text:#1e293b; --muted:#64748b;
             --accent:#4f46e5; --accent2:#6366f1; --border:rgba(99,102,241,0.2);
             --card-shadow:rgba(0,0,0,0.08);
             --body-bg:linear-gradient(135deg,#eef2ff,#f8fafc 60%); }}
    * {{ box-sizing:border-box; margin:0; }}
    body {{ background:var(--body-bg);
            color:var(--text); font-family:system-ui,-apple-system,sans-serif; padding:24px; }}
    header {{ display:flex; flex-wrap:wrap; align-items:center; gap:12px;
              margin-bottom:20px; }}
    h1 {{ font-size:24px; flex:1; }}
    .toolbar {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; }}
    #themeToggle {{ position:fixed; top:12px; right:12px; z-index:99999;
      background:var(--card); border:1px solid var(--border); border-radius:50%;
      width:36px; height:36px; cursor:pointer; font-size:18px; color:var(--text);
      display:flex; align-items:center; justify-content:center; transition:all .3s; }}
    #themeToggle:hover {{ border-color:var(--accent); }}
    .toolbar input {{ background:var(--card); border:1px solid var(--border);
                      border-radius:10px; padding:8px 14px; color:var(--text);
                      font-size:14px; width:220px; outline:none; }}
    .toolbar input:focus {{ border-color:var(--accent); }}
    .toolbar button {{ background:var(--card); border:1px solid var(--border);
                       border-radius:8px; padding:6px 14px; color:var(--text);
                       cursor:pointer; font-size:13px; transition:all .2s; }}
    .toolbar button:hover,.toolbar button.active {{ background:var(--accent);
                                                    border-color:var(--accent); }}
    .stats {{ color:var(--muted); font-size:13px; margin-bottom:16px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr));
             gap:16px; }}
    .list .card {{ display:flex; gap:16px; align-items:flex-start; }}
    .list .card .card-body {{ flex:1; }}
    .card {{ background:var(--card); border:1px solid var(--border);
             border-radius:14px; padding:18px; transition:transform .2s,box-shadow .2s;
             box-shadow:0 4px 16px var(--card-shadow); }}
    .card:hover {{ transform:translateY(-3px); box-shadow:0 12px 32px var(--card-shadow); }}
    .card h3 {{ font-size:16px; margin-bottom:6px; line-height:1.3; }}
    .card .domain {{ color:var(--accent2); font-size:12px; margin-bottom:8px; }}
    .card p {{ color:var(--muted); font-size:13px; line-height:1.6;
               display:-webkit-box; -webkit-line-clamp:4; -webkit-box-orient:vertical;
               overflow:hidden; }}
    .card .actions {{ margin-top:12px; display:flex; gap:8px; }}
    .card .actions a {{ color:var(--accent2); text-decoration:none; font-size:13px;
                        padding:4px 10px; border:1px solid var(--border);
                        border-radius:6px; transition:all .2s; }}
    .card .actions a:hover {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
    .hidden {{ display:none!important; }}
  </style>
</head>
<body>
  <button id="themeToggle" onclick="document.documentElement.dataset.theme=document.documentElement.dataset.theme==='light'?'dark':'light'"></button>
  <header>
    <h1>{title}</h1>
    <div class="toolbar">
      <input type="text" id="search" placeholder="Buscar...">
      <button onclick="toggleView('grid')" id="btnGrid" class="active">▦ Grid</button>
      <button onclick="toggleView('list')" id="btnList">Lista</button>
      <button onclick="sortCards('title')">A-Z</button>
      <button onclick="sortCards('domain')">Dominio</button>
    </div>
  </header>
  <div class="stats" id="stats"></div>
  <div class="grid" id="container"></div>
  <script>
    const DATA = {items_json};
    let currentView = 'grid';
    let currentData = [...DATA];

    function render() {{
      const c = document.getElementById('container');
      c.className = currentView;
      c.innerHTML = currentData.map((d,i) => `
        <div class="card" data-idx="${{i}}">
          <div class="card-body">
            <h3>${{esc(d.title)}}</h3>
            <div class="domain">${{esc(d.domain)}}</div>
            <p>${{esc(d.excerpt)}}</p>
            <div class="actions">
              <a href="${{esc(d.url)}}" target="_blank" rel="noopener">Visitar sitio</a>
            </div>
          </div>
        </div>
      `).join('');
      document.getElementById('stats').textContent =
        currentData.length + ' de ' + DATA.length + ' resultados';
    }}

    function esc(s) {{ const d=document.createElement('div'); d.textContent=s; return d.innerHTML; }}

    function toggleView(v) {{
      currentView = v;
      document.getElementById('btnGrid').className = v==='grid'?'active':'';
      document.getElementById('btnList').className = v==='list'?'active':'';
      render();
    }}

    function sortCards(key) {{
      currentData.sort((a,b) => (a[key]||'').localeCompare(b[key]||''));
      render();
    }}

    document.getElementById('search').addEventListener('input', function(e) {{
      const q = e.target.value.toLowerCase();
      currentData = DATA.filter(d =>
        d.title.toLowerCase().includes(q) ||
        d.domain.toLowerCase().includes(q) ||
        d.excerpt.toLowerCase().includes(q)
      );
      render();
    }});

    render();
  </script>
</body>
</html>"""

    def _inject_source_links(self, html: str) -> str:
        badge_css = """
<style id="gentab-badge">
#gentab-badge-bar {
  position: fixed; bottom: 0; left: 0; right: 0;
  background: linear-gradient(135deg, #1e1b4b 0%, #312e81 100%);
  color: #c7d2fe; font-family: system-ui, sans-serif;
  padding: 6px 16px; display: flex; align-items: center;
  gap: 12px; font-size: 12px; z-index: 99999;
  border-top: 1px solid rgba(99,102,241,0.3);
  backdrop-filter: blur(10px);
}
[data-theme="light"] #gentab-badge-bar {
  background: linear-gradient(135deg, #e0e7ff 0%, #c7d2fe 100%);
  color: #3730a3; border-top-color: rgba(99,102,241,0.2);
}
#gentab-badge-bar .gentab-logo {
  background: linear-gradient(135deg, #6366f1, #818cf8);
  color: white; padding: 2px 8px; border-radius: 6px;
  font-weight: 700; font-size: 11px; letter-spacing: 0.5px;
}
#gentab-badge-bar a {
  color: #a5b4fc; text-decoration: none;
  padding: 2px 6px; border-radius: 4px;
  transition: all 0.2s;
}
[data-theme="light"] #gentab-badge-bar a { color: #4338ca; }
#gentab-badge-bar a:hover {
  background: rgba(99,102,241,0.2); color: #e0e7ff;
}
[data-theme="light"] #gentab-badge-bar a:hover { color: #312e81; }
body { padding-bottom: 36px !important; }
</style>
"""
        source_links = ' '.join(
            f'<a href="{_html_escape.escape(tc.url)}" target="_blank" '
            f'title="{_html_escape.escape(tc.title)}">'
            f'{_html_escape.escape(tc.domain)}</a>'
            for tc in self.tab_contexts
        )
        badge_html = f"""
<div id="gentab-badge-bar">
  <span class="gentab-logo">GenTab</span>
  <span>Fuentes:</span>
  {source_links}
  <span style="margin-left:auto;opacity:0.6;">Katphi Browser</span>
</div>
"""
        # Inyectar CSS de tema light como fallback si el LLM no lo incluyó
        theme_fallback_css = ""
        if '[data-theme="light"]' not in html:
            theme_fallback_css = """
<style id="gentab-theme-fallback">
[data-theme="light"] { --bg:#f8fafc; --card:#ffffff; --text:#1e293b; --muted:#64748b;
  --accent:#4f46e5; --accent2:#6366f1; --border:rgba(99,102,241,0.2);
  --card-shadow:rgba(0,0,0,0.08);
  --body-bg:linear-gradient(135deg,#eef2ff,#f8fafc 60%); }
[data-theme="light"] body { background:var(--body-bg); color:var(--text); }
</style>
"""
        # Inyectar toggle si no existe
        toggle_html = ""
        if 'themeToggle' not in html:
            toggle_html = """<button id="themeToggle" onclick="document.documentElement.dataset.theme=document.documentElement.dataset.theme==='light'?'dark':'light'" style="position:fixed;top:12px;right:12px;z-index:99999;background:var(--card,#1a1a3e);border:1px solid var(--border,rgba(99,102,241,0.3));border-radius:50%;width:36px;height:36px;cursor:pointer;font-size:18px;color:var(--text,#e2e8f0);display:flex;align-items:center;justify-content:center;"></button>
"""
        if '</head>' in html:
            html = html.replace('</head>', f'{theme_fallback_css}{badge_css}</head>')
        if '</body>' in html:
            html = html.replace('</body>', f'{toggle_html}{badge_html}</body>')
        return html
    def _generate_title(self, raw: str) -> str:
        if '<title>' in raw and '</title>' in raw:
            start = raw.index('<title>') + 7
            end = raw.index('</title>')
            if end > start:
                title = raw[start:end].strip()
                if title:
                    return title
        words = self.prompt.split()
        return ' '.join(words[:6]).capitalize() + ('...' if len(words) > 6 else '')


class GenTabEngine(QObject):
    """Motor principal del sistema GenTabs."""

    gentab_started = Signal()
    gentab_progress = Signal(str)
    gentab_completed = Signal(object)
    gentab_error = Signal(str)
    context_extracted = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("Katphi", "GenTabs")
        self.history: List[GenTabResult] = []
        self._worker: Optional[GenTabWorker] = None
        self._load_history()
    def extract_all_tabs_context(self, tab_manager) -> Tuple[List[TabContext], int]:
        """Extrae contexto de todas las pestañas abiertas. Retorna (contextos, pending_count)."""
        contexts: List[TabContext] = []
        pending = 0

        for i in range(tab_manager.tabs.count()):
            browser = tab_manager.tabs.widget(i)
            if not browser:
                continue
            url = browser.url().toString()
            if not url or url in ('about:blank', 'about:gentab'):
                continue
            title = ""
            if hasattr(browser, 'page') and browser.page():
                title = browser.page().title() or ""
            domain = ContentExtractor.get_domain(url)

            ctx = TabContext(
                index=i,
                url=url,
                title=title or f"Tab {i + 1}",
                content="",
                content_length=0,
                domain=domain
            )
            contexts.append(ctx)
            pending += 1
        return contexts, pending
    def extract_tab_html(self, browser, tab_context: TabContext, callback):
        """Extrae HTML de una pestaña individual de forma asíncrona."""
        def on_html(html):
            try:
                content = ContentExtractor.extract_from_html(
                    html, tab_context.url, tab_context.title
                )
                tab_context.content = content
                tab_context.content_length = len(content)
            except Exception as e:
                tab_context.content = f"[Error extracting: {e}]"
                tab_context.content_length = 0
            callback(tab_context)
        if hasattr(browser, 'page') and browser.page():
            browser.page().toHtml(on_html)
        else:
            tab_context.content = "[No page available]"
            callback(tab_context)
    def generate_gentab(self, server_url: str, prompt: str,
                        tab_contexts: List[TabContext],
                        temperature: float = 0.7,
                        max_tokens: int = 1200,
                        llm_config: Optional[LLMConfig] = None):
        """Inicia la generación de una GenTab en un hilo de trabajo."""
        if self._worker and self._worker.isRunning():
            self.gentab_error.emit("Ya hay una generación en curso.")
            return
        valid = [tc for tc in tab_contexts if tc.content and tc.content_length > 0]
        if not valid:
            self.gentab_error.emit("No hay contenido extraído de las pestañas.")
            return
        self._worker = GenTabWorker(
            server_url, prompt, valid, temperature, max_tokens,
            llm_config=llm_config
        )
        self._worker.progress.connect(self.gentab_progress.emit)
        self._worker.finished.connect(self._on_generation_complete)
        self._worker.error.connect(self.gentab_error.emit)

        self.gentab_started.emit()
        self._worker.start()
    def _on_generation_complete(self, result: GenTabResult):
        self.history.insert(0, result)
        if len(self.history) > 50:
            self.history = self.history[:50]
        self._save_history()
        self.gentab_completed.emit(result)
    def get_history(self) -> List[GenTabResult]:
        return self.history
    def clear_history(self):
        self.history.clear()
        self._save_history()
    def _save_history(self):
        try:
            data = []
            for r in self.history[:20]:
                entry = {
                    'id': r.id,
                    'title': r.title,
                    'prompt': r.prompt,
                    'source_tabs': r.source_tabs,
                    'created_at': r.created_at,
                    'generation_time': r.generation_time,
                    'model_used': r.model_used,
                }
                data.append(entry)
            self.settings.setValue("history", json.dumps(data))
        except Exception as e:
            logger.error(f"Error saving GenTab history: {e}")
    def _load_history(self):
        try:
            raw = self.settings.value("history", "[]")
            data = json.loads(raw) if isinstance(raw, str) else []
            self.history = []
            for entry in data:
                result = GenTabResult(
                    id=entry.get('id', ''),
                    title=entry.get('title', ''),
                    html='',
                    prompt=entry.get('prompt', ''),
                    source_tabs=entry.get('source_tabs', []),
                    created_at=entry.get('created_at', ''),
                    generation_time=entry.get('generation_time', 0),
                    model_used=entry.get('model_used', ''),
                )
                self.history.append(result)
        except Exception as e:
            logger.error(f"Error loading GenTab history: {e}")
            self.history = []
