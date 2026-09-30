#!/usr/bin/env python3
"""
AI Context Engine — Embeddings y cache vectorial para navegación aumentada.

Proporciona búsqueda semántica sobre el contenido de las pestañas abiertas
usando sentence-transformers (local) con un almacén vectorial en memoria
(por sesión).  Diseñado para degradar con gracia cuando no hay GPU o cuando
faltan dependencias pesadas.
"""

import hashlib
import importlib.util
import logging
import re
import time
from typing import Dict, List, Optional

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal, QSettings

logger = logging.getLogger(__name__)

# ── Flags de disponibilidad ──────────────────────────────────────────────────
# Solo comprobamos que el paquete EXISTE (find_spec, barato) sin importarlo:
# `sentence_transformers` arrastra `torch`, lo que añadía 1-3+ segundos al
# arranque del navegador aunque la navegación con IA estuviera desactivada.
# La importación real (pesada) se difiere a _ensure_model(), solo cuando de
# verdad se usa.

_SENTENCE_TRANSFORMERS_OK = importlib.util.find_spec("sentence_transformers") is not None

if not _SENTENCE_TRANSFORMERS_OK:
    logger.warning("sentence-transformers no disponible; se usará fallback por keywords")


# ═════════════════════════════════════════════════════════════════════════════
# ContentChunker
# ═════════════════════════════════════════════════════════════════════════════

class ContentChunker:
    """Divide contenido de páginas en chunks óptimos para embeddings."""

    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50

    @classmethod
    def chunk_html(cls, html_text: str) -> List[str]:
        """Divide texto plano (ya limpio) en chunks con overlap.

        Args:
            html_text: Texto limpio extraído del HTML.
        Returns:
            Lista de strings de tamaño ≤ CHUNK_SIZE.
        """
        if not html_text or not html_text.strip():
            return []
        text = html_text.strip()
        chunks: List[str] = []
        start = 0
        while start < len(text):
            end = start + cls.CHUNK_SIZE
            chunk = text[start:end]
            if chunk.strip():
                chunks.append(chunk.strip())
            start += cls.CHUNK_SIZE - cls.CHUNK_OVERLAP
        return chunks
    @classmethod
    def chunk_by_headings(cls, html_text: str) -> List[str]:
        """Divide por encabezados (H1-H3) detectados como ``[H1]``, ``[H2]``, etc.

        Cada sección delimitada por un encabezado se devuelve como un chunk
        independiente.  Si una sección excede ``CHUNK_SIZE``, se subdivide
        con :meth:`chunk_html`.

        Args:
            html_text: Texto limpio con marcadores ``[H1]``, ``[H2]``, ``[H3]``.
        Returns:
            Lista de chunks.
        """
        if not html_text or not html_text.strip():
            return []
        heading_pattern = re.compile(r'\[H[1-3]\]')
        parts = heading_pattern.split(html_text)
        chunks: List[str] = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if len(part) <= cls.CHUNK_SIZE:
                chunks.append(part)
            else:
                chunks.extend(cls.chunk_html(part))
        return chunks


# ═════════════════════════════════════════════════════════════════════════════
# EmbeddingProvider
# ═════════════════════════════════════════════════════════════════════════════

class EmbeddingProvider:
    """Abstracción para generar embeddings locales con sentence-transformers.

    Usa ``all-MiniLM-L6-v2`` por defecto (rápido, 384 dims).
    Carga el modelo de forma perezosa para no bloquear el arranque.
    """

    DEFAULT_MODEL = "all-MiniLM-L6-v2"

    def __init__(self, model_name: Optional[str] = None):
        self._model_name = model_name or self.DEFAULT_MODEL
        self._model: Optional["SentenceTransformer"] = None
        self._available = _SENTENCE_TRANSFORMERS_OK
    @property
    def available(self) -> bool:
        return self._available
    def _ensure_model(self) -> None:
        """Lazy-load del modelo de embeddings."""
        if self._model is not None:
            return
        if not self._available:
            raise RuntimeError("sentence-transformers no está instalado")
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
            logger.info("Modelo de embeddings '%s' cargado", self._model_name)
        except Exception as exc:
            self._available = False
            raise RuntimeError(f"No se pudo cargar el modelo: {exc}") from exc
    def encode(self, texts: List[str]) -> np.ndarray:
        """Codifica una lista de textos en vectores.

        Args:
            texts: Textos a codificar.
        Returns:
            ndarray de shape ``(len(texts), dim)``.
        """
        self._ensure_model()
        return self._model.encode(texts, show_progress_bar=False)  # type: ignore[union-attr]
    def encode_single(self, text: str) -> np.ndarray:
        """Codifica un solo texto.

        Args:
            text: Texto a codificar.
        Returns:
            ndarray de shape ``(dim,)``.
        """
        return self.encode([text])[0]


# ═════════════════════════════════════════════════════════════════════════════
# ContextVectorStore
# ═════════════════════════════════════════════════════════════════════════════

class ContextVectorStore:
    """Almacena embeddings del contenido de pestañas para búsqueda semántica.

    Almacén en memoria (por sesión) con búsqueda brute-force por coseno.
    """

    def __init__(self):
        self._embedding_provider = EmbeddingProvider()
        self._mem_store: Dict[str, Dict] = {}
    # ── API pública ──────────────────────────────────────────────────────────

    def add_tab_context(
        self,
        tab_id: str,
        url: str,
        title: str,
        content_chunks: List[str],
    ) -> None:
        """Indexa los chunks de una pestaña.

        Args:
            tab_id: Identificador único de la pestaña.
            url: URL de la pestaña.
            title: Título de la pestaña.
            content_chunks: Lista de fragmentos de texto.
        """
        if not content_chunks:
            return
        self.delete_tab(tab_id)

        embeddings = None
        if self._embedding_provider.available:
            try:
                embeddings = self._embedding_provider.encode(content_chunks)
            except Exception:
                pass
        self._mem_store[tab_id] = {
            "url": url,
            "title": title,
            "chunks": content_chunks,
            "embeddings": embeddings,
        }
    def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """Busca los chunks más relevantes para una query.

        Args:
            query: Texto de búsqueda.
            top_k: Número máximo de resultados.
        Returns:
            Lista de dicts con keys ``tab_id``, ``url``, ``title``,
            ``chunk``, ``score``.
        """
        return self._search_memory(query, top_k)
    def _search_memory(self, query: str, top_k: int) -> List[Dict]:
        """Búsqueda fallback en memoria (coseno o keywords)."""
        query_emb = None
        if self._embedding_provider.available:
            try:
                query_emb = self._embedding_provider.encode_single(query)
            except Exception:
                pass
        results: List[Dict] = []
        for tab_id, data in self._mem_store.items():
            chunks = data["chunks"]
            embeddings = data.get("embeddings")

            for i, chunk in enumerate(chunks):
                if query_emb is not None and embeddings is not None:
                    chunk_emb = embeddings[i]
                    score = float(np.dot(query_emb, chunk_emb) / (
                        np.linalg.norm(query_emb) * np.linalg.norm(chunk_emb) + 1e-10
                    ))
                else:
                    score = self._keyword_score(query, chunk)
                results.append({
                    "tab_id": tab_id,
                    "url": data["url"],
                    "title": data["title"],
                    "chunk": chunk,
                    "score": score,
                })
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]
    @staticmethod
    def _keyword_score(query: str, text: str) -> float:
        """Score simple basado en keywords cuando no hay embeddings."""
        query_words = set(query.lower().split())
        text_lower = text.lower()
        if not query_words:
            return 0.0
        matches = sum(1 for w in query_words if w in text_lower)
        return matches / len(query_words)
    def delete_tab(self, tab_id: str) -> None:
        """Elimina todos los chunks de una pestaña.

        Args:
            tab_id: Identificador de la pestaña a eliminar.
        """
        self._mem_store.pop(tab_id, None)
    def clear(self) -> None:
        """Elimina todo el contenido indexado."""
        self._mem_store.clear()
    @property
    def tab_count(self) -> int:
        """Número de pestañas indexadas."""
        return len(self._mem_store)


# ═════════════════════════════════════════════════════════════════════════════
# IndexWorker — indexación en segundo plano
# ═════════════════════════════════════════════════════════════════════════════

class IndexWorker(QThread):
    """Worker que indexa el contenido de una pestaña en segundo plano."""

    indexing_done = Signal(str)   # tab_id
    indexing_error = Signal(str)  # mensaje de error

    def __init__(
        self,
        store: ContextVectorStore,
        tab_id: str,
        url: str,
        title: str,
        html_content: str,
    ):
        super().__init__()
        self._store = store
        self._tab_id = tab_id
        self._url = url
        self._title = title
        self._html = html_content
    def run(self) -> None:
        try:
            from gentab_engine import ContentExtractor
            clean_text = ContentExtractor.extract_from_html(
                self._html, self._url, self._title,
            )
            chunks = ContentChunker.chunk_html(clean_text)
            if chunks:
                self._store.add_tab_context(
                    self._tab_id, self._url, self._title, chunks,
                )
            self.indexing_done.emit(self._tab_id)
        except Exception as exc:
            logger.error("Error indexando pestaña %s: %s", self._tab_id, exc)
            self.indexing_error.emit(str(exc))
