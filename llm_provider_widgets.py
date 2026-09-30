#!/usr/bin/env python3
"""
Widgets de configuración para los proveedores cloud OpenAI-compatibles
(OPENAI_COMPAT_PROVIDERS en llm_client). Compartido por el Chat con IA y GenTabs:
cada proveedor de la tabla obtiene su sección (API key + modelo + enlace) sin
código específico en los paneles.
"""

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QPushButton, QMessageBox,
)

from llm_client import LLMClient, LLMConfig, OPENAI_COMPAT_PROVIDERS, PROVIDER_ANTHROPIC


@dataclass
class CompatProviderFields:
    widget: QWidget
    key_input: QLineEdit
    model_combo: QComboBox


def build_compat_provider_widget(provider: str, link_color: str, hint_color: str,
                                 icon_setter=None) -> CompatProviderFields:
    """Crea la sección de configuración (API key, modelo, enlace) de un proveedor.
    icon_setter: BasePanel.set_button_icon del panel, para el icono temático del botón de mostrar."""
    spec = OPENAI_COMPAT_PROVIDERS[provider]
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)

    key_row = QHBoxLayout()
    key_lbl = QLabel("API Key:")
    key_lbl.setFixedWidth(72)
    key_row.addWidget(key_lbl)
    key_input = QLineEdit()
    key_input.setPlaceholderText(spec["key_placeholder"])
    key_input.setEchoMode(QLineEdit.Password)
    key_row.addWidget(key_input)
    show_btn = QPushButton()
    show_btn.setMaximumWidth(32)
    show_btn.setToolTip("Mostrar u ocultar la API key")
    if icon_setter:
        icon_setter(show_btn, "eye")
    else:
        show_btn.setText("Mostrar")
    show_btn.setCheckable(True)
    show_btn.toggled.connect(
        lambda on: key_input.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
    )
    key_row.addWidget(show_btn)
    layout.addLayout(key_row)

    model_row = QHBoxLayout()
    model_lbl = QLabel("Modelo:")
    model_lbl.setFixedWidth(72)
    model_row.addWidget(model_lbl)
    model_combo = QComboBox()
    model_combo.addItems(spec["models"])
    model_combo.setEditable(True)
    model_combo.setInsertPolicy(QComboBox.NoInsert)
    model_row.addWidget(model_combo)
    refresh_btn = QPushButton("Actualizar")
    refresh_btn.setToolTip(f"Cargar los modelos disponibles para tu cuenta de {spec['label']}")
    refresh_btn.clicked.connect(
        lambda: _refresh_models(widget, provider, key_input, model_combo)
    )
    model_row.addWidget(refresh_btn)
    layout.addLayout(model_row)

    info = QLabel(
        f'Obtén tu API key en <a href="{spec["key_url"]}" '
        f'style="color:{link_color};">{spec["key_url"].split("//", 1)[1]}</a>'
    )
    info.setOpenExternalLinks(True)
    info.setTextFormat(Qt.RichText)
    info.setWordWrap(True)
    info.setStyleSheet(f"color: {hint_color}; font-size: 11px;")
    layout.addWidget(info)

    return CompatProviderFields(widget, key_input, model_combo)


def load_compat_fields(fields: dict, cfg: LLMConfig) -> None:
    """Vuelca en los widgets la key y el modelo guardados de cada proveedor."""
    for pid, f in fields.items():
        f.key_input.setText(cfg.compat_key(pid))
        f.model_combo.setEditText(cfg.compat_model(pid))


def save_compat_fields(fields: dict, cfg: LLMConfig) -> None:
    """Copia a la configuración la key y el modelo de cada proveedor."""
    for pid, f in fields.items():
        cfg.compat_keys[pid] = f.key_input.text().strip()
        model = f.model_combo.currentText().strip()
        if model:
            cfg.compat_models[pid] = model


def _refresh_models(parent: QWidget, provider: str, key_input: QLineEdit, model_combo: QComboBox) -> None:
    label = OPENAI_COMPAT_PROVIDERS[provider]["label"]
    cfg = LLMConfig(provider=provider, compat_keys={provider: key_input.text().strip()})
    client = LLMClient(cfg)
    models = client.list_models()
    if not models:
        ok, info = client.test()
        QMessageBox.warning(
            parent, label,
            info if not ok else
            "Este servicio no devuelve la lista de modelos: escribe el nombre del modelo a mano.",
        )
        return
    current = model_combo.currentText().strip()
    model_combo.clear()
    model_combo.addItems(models)
    model_combo.setEditText(current if current in models else models[0])


# ─── Anthropic ──────────────────────────────────────────────────────────────────

ANTHROPIC_MODEL_DESCRIPTIONS = {
    "claude-opus-5":     "Opus 5 — muy capaz en razonamiento y tareas complejas (recomendado)",
    "claude-sonnet-5":   "Sonnet 5 — equilibrio entre inteligencia, velocidad y coste",
    "claude-fable-5-1":  "Fable 5.1 — el modelo más capaz de Anthropic; más lento y caro",
    "claude-opus-4-8":   "Opus 4.8 — generación anterior de Opus",
    "claude-sonnet-4-6": "Sonnet 4.6 — generación anterior; respeta el ajuste de temperatura",
    "claude-haiku-4-5":  "Haiku 4.5 — el más rápido y económico, ideal para tareas cortas",
}

_ANTHROPIC_MODEL_GROUPS = [
    ("── Claude 5 ──", ["claude-opus-5", "claude-sonnet-5", "claude-fable-5-1"]),
    ("── Claude 4 ──", ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"]),
]


def fill_anthropic_model_combo(combo: QComboBox, models: list = None) -> None:
    """Rellena el selector: agrupado con la lista sugerida, o plano con los de la cuenta."""
    combo.clear()
    if models:
        combo.addItems(models)
        return
    for header, group in _ANTHROPIC_MODEL_GROUPS:
        combo.addItem(header)
        item = combo.model().item(combo.count() - 1)
        if item:
            item.setEnabled(False)
            item.setForeground(QColor("#606060"))
        combo.addItems(group)


def select_anthropic_model(combo: QComboBox, model: str) -> None:
    """Selecciona el modelo; si no está en la lista (p. ej. uno cargado de la API), lo añade."""
    idx = combo.findText(model)
    if idx < 0 or not combo.model().item(idx).isEnabled():
        combo.addItem(model)
        idx = combo.count() - 1
    combo.setCurrentIndex(idx)


def refresh_anthropic_models(parent: QWidget, api_key: str, combo: QComboBox) -> None:
    if not api_key:
        QMessageBox.warning(parent, "Anthropic", "Introduce tu API key para cargar los modelos de tu cuenta.")
        return
    client = LLMClient(LLMConfig(provider=PROVIDER_ANTHROPIC, anthropic_key=api_key))
    models = client.list_models()
    if not models:
        ok, info = client.test()
        QMessageBox.warning(parent, "Anthropic", info if not ok else "No se encontraron modelos.")
        return
    current = combo.currentText()
    fill_anthropic_model_combo(combo, models)
    select_anthropic_model(combo, current if current in models else models[0])
