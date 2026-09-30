#!/usr/bin/env python3
"""
Panel de visualización de logs en tiempo real.

Muestra todos los registros del sistema de logging con:
- Colores por nivel (DEBUG/INFO/WARNING/ERROR/CRITICAL)
- Filtros por nivel y por módulo
- Búsqueda de texto
- Auto-scroll opcional
- Exportación a fichero de texto
- Acceso directo al fichero .log rotante
"""

from __future__ import annotations

import html
import logging
import os
import subprocess
import sys
from datetime import datetime
from typing import List

from PySide6.QtCore import Qt, QTimer, QSortFilterProxyModel
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor, QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTextEdit, QComboBox, QLineEdit, QCheckBox, QFrame,
    QFileDialog, QMessageBox, QSizePolicy,
)

from base_panel import BasePanel
from logger_setup import get_memory_handler, get_log_signals, LOG_FILE_PATH

_log = logging.getLogger(__name__)

# ── Colores por nivel ─────────────────────────────────────────────────────────
_LEVEL_HTML_COLORS = {
    logging.DEBUG:    ("#94a3b8", "#1e2340"),   # (text, bg)
    logging.INFO:     ("#4ade80", "#0f2d1a"),
    logging.WARNING:  ("#fbbf24", "#2d1f00"),
    logging.ERROR:    ("#f87171", "#2d0a0a"),
    logging.CRITICAL: ("#f0abfc", "#1a0027"),
}
_LEVEL_NAMES = {
    logging.DEBUG:    "DEBUG",
    logging.INFO:     "INFO",
    logging.WARNING:  "WARN",
    logging.ERROR:    "ERROR",
    logging.CRITICAL: "CRIT",
}
_BADGE_STYLES = {
    logging.DEBUG:    "background:#334155;color:#94a3b8;",
    logging.INFO:     "background:#14532d;color:#4ade80;",
    logging.WARNING:  "background:#451a03;color:#fbbf24;",
    logging.ERROR:    "background:#450a0a;color:#f87171;",
    logging.CRITICAL: "background:#3b0764;color:#f0abfc;",
}


def _format_record_html(record: logging.LogRecord) -> str:
    """Convierte un LogRecord en una línea HTML coloreada."""
    text_color, bg_color = _LEVEL_HTML_COLORS.get(
        record.levelno, ("#e2e8f0", "#1a1a3e")
    )
    badge_style = _BADGE_STYLES.get(record.levelno, "")
    level_name = _LEVEL_NAMES.get(record.levelno, record.levelname[:4])

    ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S.%f")[:-3]
    module = record.name.split(".")[-1][:20]
    func = f"{record.funcName}:{record.lineno}"
    msg = html.escape(str(record.getMessage()))

    # Si hay excepción, añadir traceback colapsado
    exc_html = ""
    if record.exc_info:
        import traceback as tb
        exc_text = html.escape(
            "".join(tb.format_exception(*record.exc_info))
        )
        exc_html = (
            f'<div style="margin-left:24px;color:#f87171;'
            f'font-family:monospace;font-size:11px;white-space:pre-wrap;">'
            f'{exc_text}</div>'
        )
    return (
        f'<div style="padding:2px 6px;border-bottom:1px solid rgba(255,255,255,0.04);'
        f'background:{bg_color};">'
        f'<span style="color:#64748b;font-size:11px;">{ts}</span> '
        f'<span style="padding:1px 5px;border-radius:3px;font-size:11px;'
        f'font-weight:bold;{badge_style}">{level_name}</span> '
        f'<span style="color:#60a5fa;font-size:11px;">{module}</span>'
        f'<span style="color:#475569;font-size:10px;"> {func}</span> '
        f'<span style="color:{text_color};font-size:12px;">{msg}</span>'
        f'{exc_html}'
        f'</div>'
    )


class LogViewerPanel(BasePanel):
    """Panel de visualización de logs en tiempo real."""

    def get_tab_definitions(self):
        return [
            (self._create_live_tab,  "En vivo"),
            (self._create_file_tab,  "Fichero log"),
            (self._create_stats_tab, "Estadísticas"),
        ]
    def post_setup_ui(self):
        self.set_object_name("logViewerPanel")
        self._min_level = logging.DEBUG
        self._module_filter = ""
        self._search_filter = ""
        self._auto_scroll = True
        self._paused = False
        self._pending_html: List[str] = []
        self._flush_timer = QTimer(self)
        self._flush_timer.timeout.connect(self._flush_pending)
        self._flush_timer.start(150)   # actualizar la UI cada 150 ms

        # Conectar la señal del sistema de logging
        sigs = get_log_signals()
        sigs.new_record.connect(self._on_new_record)

        # Cargar registros previos (buffer en memoria)
        QTimer.singleShot(100, self._load_initial_records)
    def _on_theme_changed(self, theme_name):
        """Recarga los estilos del panel cuando cambia el tema global."""
        super()._on_theme_changed(theme_name)
        self._apply_dynamic_styles()
    def _apply_dynamic_styles(self):
        """Aplica los estilos dinámicos de todos los widgets usando el ThemeEngine activo."""
        c = self.get_theme_colors()
        text_view_style = (
            f"QTextEdit {{ background: {c['surface_0']}; color: {c['text_primary']};"
            f" border: 1px solid {c['border']}; border-radius: 8px;"
            f" selection-background-color: {c['selected']}; }}"
        )
        btn_style = (
            f"QPushButton {{ background: {c['surface_1']}; color: {c['text_primary']};"
            f" border: 1px solid {c['border']}; border-radius: 6px;"
            f" padding: 4px 10px; font-size: 12px; }}"
            f" QPushButton:hover {{ background: {c['surface_hover']}; }}"
            f" QPushButton:checked {{ background: {c['error_subtle']}; color: {c['error']};"
            f" border-color: {c['error']}; }}"
        )
        combo_style = (
            f"QComboBox {{ background: {c['input_bg']}; color: {c['text_primary']};"
            f" border: 1px solid {c['border']}; border-radius: 6px;"
            f" padding: 3px 8px; font-size: 12px; }}"
            f" QComboBox::drop-down {{ border: none; }}"
            f" QComboBox QAbstractItemView {{ background: {c['input_bg']}; color: {c['text_primary']}; }}"
        )
        input_style = (
            f"QLineEdit {{ background: {c['input_bg']}; color: {c['text_primary']};"
            f" border: 1px solid {c['border']}; border-radius: 6px;"
            f" padding: 3px 8px; font-size: 12px; }}"
            f" QLineEdit:focus {{ border-color: {c['input_focus']}; }}"
        )
        count_style = f"color: {c['text_secondary']}; font-size: 11px;"
        for attr, style in [
            ("_log_view", text_view_style),
            ("_file_view", text_view_style),
            ("_stats_text", text_view_style),
            ("_pause_btn", btn_style),
            ("_level_combo", combo_style),
            ("_module_input", input_style),
            ("_search_input", input_style),
            ("_count_label", count_style),
            ("_file_path_label", count_style),
        ]:
            w = getattr(self, attr, None)
            if w:
                w.setStyleSheet(style)
    # ── Tab "En vivo" ─────────────────────────────────────────────────────────

    def _create_live_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── Toolbar ──────────────────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        # Filtro por nivel
        self._level_combo = QComboBox()
        self._level_combo.addItem("Todos",    logging.DEBUG)
        self._level_combo.addItem("DEBUG",  logging.DEBUG)
        self._level_combo.addItem("INFO",   logging.INFO)
        self._level_combo.addItem("WARN",   logging.WARNING)
        self._level_combo.addItem("ERROR",  logging.ERROR)
        self._level_combo.addItem("CRIT",   logging.CRITICAL)
        self._level_combo.setFixedWidth(130)
        self._level_combo.currentIndexChanged.connect(self._on_filter_changed)
        toolbar.addWidget(QLabel("Nivel:"))
        toolbar.addWidget(self._level_combo)

        # Filtro por módulo
        self._module_input = QLineEdit()
        self._module_input.setPlaceholderText("módulo... (ej: gentab)")
        self._module_input.setFixedWidth(140)
        self._module_input.textChanged.connect(self._on_filter_changed)
        toolbar.addWidget(QLabel("Módulo:"))
        toolbar.addWidget(self._module_input)

        # Búsqueda
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Buscar en mensajes...")
        self._search_input.textChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._search_input, 1)

        toolbar.addSpacing(8)

        # Pausa
        self._pause_btn = QPushButton("Pausar")
        self._pause_btn.setCheckable(True)
        self._pause_btn.toggled.connect(self._on_pause_toggled)
        self._pause_btn.setFixedWidth(90)
        toolbar.addWidget(self._pause_btn)

        # Auto-scroll
        self._autoscroll_chk = QCheckBox("Auto-scroll")
        self._autoscroll_chk.setChecked(True)
        self._autoscroll_chk.toggled.connect(lambda v: setattr(self, "_auto_scroll", v))
        toolbar.addWidget(self._autoscroll_chk)

        layout.addLayout(toolbar)

        # ── Contador de registros ─────────────────────────────────────────────
        self._count_label = QLabel("0 registros")
        layout.addWidget(self._count_label)

        # ── Área de logs ──────────────────────────────────────────────────────
        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setObjectName("logView")
        self._log_view.setFont(QFont("Monospace", 11))
        self._log_view.setLineWrapMode(QTextEdit.NoWrap)
        layout.addWidget(self._log_view, 1)

        # ── Barra inferior ────────────────────────────────────────────────────
        bottom = QHBoxLayout()

        clear_btn = QPushButton("Limpiar vista")
        clear_btn.clicked.connect(self._clear_view)
        bottom.addWidget(clear_btn)

        export_btn = QPushButton("Exportar filtrado")
        export_btn.clicked.connect(self._export_filtered)
        bottom.addWidget(export_btn)

        bottom.addStretch()

        open_file_btn = QPushButton("Abrir katphi_browser.log")
        open_file_btn.clicked.connect(self._open_log_file)
        bottom.addWidget(open_file_btn)

        layout.addLayout(bottom)

        self._apply_dynamic_styles()
        return widget
    def _apply_toolbar_style(self):
        """Delegado a _apply_dynamic_styles para compatibilidad."""
        self._apply_dynamic_styles()
    # ── Tab "Fichero log" ─────────────────────────────────────────────────────

    def _create_file_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        self._file_path_label = QLabel(f"{LOG_FILE_PATH}")
        self._file_path_label.setWordWrap(True)
        header.addWidget(self._file_path_label, 1)

        reload_btn = QPushButton("Recargar")
        reload_btn.clicked.connect(self._reload_file_tab)
        header.addWidget(reload_btn)
        layout.addLayout(header)

        self._file_view = QTextEdit()
        self._file_view.setReadOnly(True)
        self._file_view.setFont(QFont("Monospace", 10))
        self._file_view.setLineWrapMode(QTextEdit.NoWrap)
        layout.addWidget(self._file_view, 1)

        # Cargar últimas 500 líneas al crear
        QTimer.singleShot(200, self._reload_file_tab)
        return widget
    def _reload_file_tab(self):
        if not hasattr(self, "_file_view"):
            return
        if not os.path.exists(LOG_FILE_PATH):
            self._file_view.setPlainText("No se encontró el fichero de log.")
            return
        try:
            with open(LOG_FILE_PATH, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            # Últimas 500 líneas
            tail = "".join(lines[-500:])
            self._file_view.setPlainText(tail)
            self._file_view.moveCursor(QTextCursor.End)
        except Exception as exc:
            self._file_view.setPlainText(f"Error leyendo log: {exc}")
    # ── Tab "Estadísticas" ────────────────────────────────────────────────────

    def _create_stats_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self._stats_text = QTextEdit()
        self._stats_text.setReadOnly(True)
        layout.addWidget(self._stats_text, 1)

        refresh_btn = QPushButton("Actualizar estadísticas")
        refresh_btn.clicked.connect(self._refresh_stats)
        layout.addWidget(refresh_btn)

        QTimer.singleShot(300, self._refresh_stats)
        return widget
    def _refresh_stats(self):
        if not hasattr(self, "_stats_text"):
            return
        handler = get_memory_handler()
        records = handler.get_records()
        total = len(records)

        by_level: dict[int, int] = {}
        by_module: dict[str, int] = {}
        for r in records:
            by_level[r.levelno] = by_level.get(r.levelno, 0) + 1
            mod = r.name.split(".")[0]
            by_module[mod] = by_module.get(mod, 0) + 1
        lines = [
            f"<h3 style='color:#c7d2fe;'>Estadísticas del buffer en memoria</h3>",
            f"<p>Total registros: <b style='color:#4ade80;'>{total}</b> / {2000}</p>",
            "<h4 style='color:#94a3b8;'>Por nivel:</h4><ul>",
        ]
        for lvl in (logging.CRITICAL, logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG):
            count = by_level.get(lvl, 0)
            badge = _BADGE_STYLES.get(lvl, "")
            name = _LEVEL_NAMES.get(lvl, str(lvl))
            lines.append(
                f'<li><span style="padding:1px 5px;border-radius:3px;{badge}">'
                f'{name}</span>  {count}</li>'
            )
        lines.append("</ul>")

        top_modules = sorted(by_module.items(), key=lambda x: -x[1])[:15]
        lines.append("<h4 style='color:#94a3b8;'>Top módulos:</h4><ul>")
        for mod, count in top_modules:
            lines.append(
                f'<li style="color:#60a5fa;">{html.escape(mod)}'
                f'<span style="color:#64748b;"> — {count} registros</span></li>'
            )
        lines.append("</ul>")

        if os.path.exists(LOG_FILE_PATH):
            size_kb = os.path.getsize(LOG_FILE_PATH) / 1024
            lines.append(
                f"<p>Tamaño fichero log: <b style='color:#fbbf24;'>{size_kb:.1f} KB</b></p>"
            )
            lines.append(f"<p style='color:#475569;font-size:11px;'>{LOG_FILE_PATH}</p>")
        self._stats_text.setHtml("".join(lines))
    # ── Lógica de actualización ───────────────────────────────────────────────

    def _on_new_record(self, record: logging.LogRecord) -> None:
        if self._paused:
            return
        if not self._record_passes_filter(record):
            return
        self._pending_html.append(_format_record_html(record))
    def _flush_pending(self) -> None:
        if not self._pending_html or not hasattr(self, "_log_view"):
            return
        batch = self._pending_html[:]
        self._pending_html.clear()

        cursor = self._log_view.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml("".join(batch))

        if self._auto_scroll:
            self._log_view.moveCursor(QTextCursor.End)
        self._update_count_label()
    def _load_initial_records(self) -> None:
        """Carga los registros que ya estaban en el buffer al abrir el panel."""
        if not hasattr(self, "_log_view"):
            return
        handler = get_memory_handler()
        records = handler.get_records()
        html_parts = [
            _format_record_html(r)
            for r in records
            if self._record_passes_filter(r)
        ]
        if html_parts:
            self._log_view.setHtml("".join(html_parts))
            if self._auto_scroll:
                self._log_view.moveCursor(QTextCursor.End)
        self._update_count_label()
    def _record_passes_filter(self, record: logging.LogRecord) -> bool:
        if record.levelno < self._min_level:
            return False
        if self._module_filter and self._module_filter.lower() not in record.name.lower():
            return False
        if self._search_filter and self._search_filter.lower() not in record.getMessage().lower():
            return False
        return True
    def _on_filter_changed(self) -> None:
        self._min_level = self._level_combo.currentData() or logging.DEBUG
        self._module_filter = self._module_input.text().strip() if hasattr(self, "_module_input") else ""
        self._search_filter = self._search_input.text().strip() if hasattr(self, "_search_input") else ""
        self._reload_live_view()
    def _reload_live_view(self) -> None:
        if not hasattr(self, "_log_view"):
            return
        handler = get_memory_handler()
        records = handler.get_records()
        html_parts = [
            _format_record_html(r)
            for r in records
            if self._record_passes_filter(r)
        ]
        self._log_view.setHtml("".join(html_parts))
        if self._auto_scroll:
            self._log_view.moveCursor(QTextCursor.End)
        self._update_count_label()
    def _update_count_label(self) -> None:
        if not hasattr(self, "_count_label"):
            return
        handler = get_memory_handler()
        total = len(handler.get_records())
        visible = len(handler.get_records(self._min_level))
        self._count_label.setText(f"{visible} visibles / {total} totales en buffer")
    def _on_pause_toggled(self, paused: bool) -> None:
        self._paused = paused
        if hasattr(self, "_pause_btn"):
            self._pause_btn.setText("Reanudar" if paused else "Pausar")
    def _clear_view(self) -> None:
        if hasattr(self, "_log_view"):
            self._log_view.clear()
        get_memory_handler().clear()
        self._update_count_label()
    def _export_filtered(self) -> None:
        handler = get_memory_handler()
        records = handler.get_records()
        filtered = [r for r in records if self._record_passes_filter(r)]
        if not filtered:
            QMessageBox.information(self, "Exportar", "No hay registros que exportar con el filtro actual.")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar log filtrado",
            f"katphi_debug_{datetime.now():%Y%m%d_%H%M%S}.log",
            "Ficheros de log (*.log *.txt)",
        )
        if not filename:
            return
        fmt = logging.Formatter(
            fmt="%(asctime)s [%(levelname)-8s] %(name)s (%(funcName)s:%(lineno)d): %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        try:
            with open(filename, "w", encoding="utf-8") as f:
                for r in filtered:
                    f.write(fmt.format(r) + "\n")
                    if r.exc_info:
                        import traceback as tb
                        f.write("".join(tb.format_exception(*r.exc_info)))
            QMessageBox.information(self, "Exportar", f"Exportados {len(filtered)} registros a:\n{filename}")
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"No se pudo guardar: {exc}")
    def _open_log_file(self) -> None:
        """Abre el fichero .log con el editor/visor predeterminado del sistema."""
        if not os.path.exists(LOG_FILE_PATH):
            QMessageBox.information(self, "Log", "Todavía no existe el fichero de log.")
            return
        try:
            if sys.platform.startswith("linux"):
                subprocess.Popen(["xdg-open", LOG_FILE_PATH])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", LOG_FILE_PATH])
            else:
                os.startfile(LOG_FILE_PATH)
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"No se pudo abrir el fichero: {exc}\n\nRuta: {LOG_FILE_PATH}")
