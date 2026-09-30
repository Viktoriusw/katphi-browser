#!/usr/bin/env python3
"""
Modern Widgets — Widgets de navegación y UI para Katphi Browser.

Filosofía: minimalismo funcional. Cada widget tiene un propósito claro
y feedback inmediato pero discreto.
"""

from PySide6.QtWidgets import (
    QLineEdit, QPushButton, QGraphicsOpacityEffect, QWidget, QHBoxLayout,
    QLabel, QVBoxLayout, QSizePolicy, QApplication,
)
from PySide6.QtCore import (
    Signal, QPropertyAnimation, Qt, QSize, QTimer,
    QEasingCurve, QRect, QPoint, QParallelAnimationGroup,
)
from PySide6.QtGui import QIcon, QColor


# ─── NavButton ────────────────────────────────────────────────────────────────

class CircularButton(QPushButton):
    """
    Botón de navegación estilo Brave — 32×32px, border-radius 6px.

    Nombre mantenido por compatibilidad; ya no es circular sino
    cuadrado redondeado (más limpio, más estándar).
    """

    def __init__(self, icon_path: str = None, parent=None):
        super().__init__(parent)
        self.setFixedSize(32, 32)
        self.setCursor(Qt.PointingHandCursor)

        if icon_path:
            self.setIcon(QIcon(icon_path))
            self.setIconSize(QSize(16, 16))
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(1.0)
    def animate_click(self):
        """Pulso de opacidad sutil al hacer click."""
        self._anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        self._anim.setDuration(120)
        self._anim.setStartValue(1.0)
        self._anim.setKeyValueAt(0.5, 0.6)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.OutQuad)
        self._anim.start()


# ─── ExpandableUrlBar ─────────────────────────────────────────────────────────

class ExpandableUrlBar(QLineEdit):
    """
    Barra de URL — pill shape, selecciona todo el texto al enfocar.

    La expansión de ancho está desactivada por defecto para evitar
    problemas de layout. Se puede activar con expansion_enabled = True.
    """

    focused   = Signal()
    unfocused = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("Buscar o escribir URL...")

        self.expansion_enabled = False
        self._expand_anim: QPropertyAnimation | None = None
    def focusInEvent(self, event):
        super().focusInEvent(event)
        # Seleccionar todo para fácil edición (comportamiento Arc/Chrome)
        QTimer.singleShot(0, self.selectAll)
        self.focused.emit()
    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.unfocused.emit()
    def enable_expansion(
        self,
        default_width: int = 500,
        expanded_width: int = 680,
        duration: int = 180,
    ):
        """Activa la animación de expansión al recibir foco."""
        self.expansion_enabled = True
        self._default_width   = default_width
        self._expanded_width  = expanded_width
        self._expand_duration = duration
        self.setMinimumWidth(default_width)


# ─── ToastNotification ────────────────────────────────────────────────────────

class ToastNotification(QWidget):
    """
    Notificación toast — esquina inferior derecha, auto-dismiss 3s.

    Tipos: 'success', 'error', 'info', 'warning'
    Slide desde abajo + fade in. Fade out al desaparecer.
    """

    _TYPE_COLORS = {
        "success": "#3FB950",
        "error":   "#F85149",
        "info":    "#4B9EFF",
        "warning": "#D29922",
    }

    def __init__(self, message: str, kind: str = "info", parent=None, duration_ms: int = 3000):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)

        self._duration = duration_ms
        self._color    = self._TYPE_COLORS.get(kind, self._TYPE_COLORS["info"])
        self._setup_ui(message)
    def _setup_ui(self, message: str):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        label = QLabel(message)
        label.setWordWrap(False)
        label.setStyleSheet(f"color: #F0F0F0; font-size: 13px;")
        layout.addWidget(label)

        self.setStyleSheet(f"""
            QWidget {{
                background: #222222;
                border: 1px solid rgba(255,255,255,0.08);
                border-left: 3px solid {self._color};
                border-radius: 6px;
            }}
        """)
        self.setMaximumWidth(280)
        self.adjustSize()
    # ── Animación ─────────────────────────────────────────────────────────────

    def _opacity_effect(self) -> QGraphicsOpacityEffect:
        if not hasattr(self, "_op_effect"):
            self._op_effect = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(self._op_effect)
        return self._op_effect
    def show_animated(self):
        """Muestra el toast con slide-in + fade-in."""
        self.show()
        op = self._opacity_effect()

        # Fade in
        self._fade_in = QPropertyAnimation(op, b"opacity")
        self._fade_in.setDuration(180)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.OutQuad)
        self._fade_in.start()

        # Auto-dismiss
        QTimer.singleShot(self._duration, self._dismiss)
    def _dismiss(self):
        op = self._opacity_effect()
        self._fade_out = QPropertyAnimation(op, b"opacity")
        self._fade_out.setDuration(220)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.InQuad)
        self._fade_out.finished.connect(self.close)
        self._fade_out.start()
    # ── Helper estático ───────────────────────────────────────────────────────

    @staticmethod
    def show_toast(
        parent: QWidget,
        message: str,
        kind: str = "info",
        duration_ms: int = 3000,
    ) -> "ToastNotification":
        """
        Muestra un toast posicionado en la esquina inferior derecha del padre.
        Retorna la instancia del toast.
        """
        toast = ToastNotification(message, kind, parent, duration_ms)

        if parent:
            parent_rect = parent.rect()
            margin = 16
            toast.adjustSize()
            x = parent_rect.right()  - toast.width()  - margin
            y = parent_rect.bottom() - toast.height() - margin
            toast.move(parent.mapToGlobal(QPoint(x, y)))
        toast.show_animated()
        return toast


# ─── ToggleSwitch ─────────────────────────────────────────────────────────────

class ToggleSwitch(QWidget):
    """
    Toggle switch personalizado — 32×18px.
    ON: fondo accent (#4B9EFF), knob blanco.
    OFF: fondo surface_hover, knob text_muted.
    Animación de 150ms.
    """

    toggled = Signal(bool)

    _COLOR_ON_BG    = "#4B9EFF"
    _COLOR_OFF_BG   = "#303030"
    _COLOR_KNOB_ON  = "#FFFFFF"
    _COLOR_KNOB_OFF = "#606060"

    def __init__(self, parent=None, checked: bool = False):
        super().__init__(parent)
        self.setFixedSize(32, 18)
        self.setCursor(Qt.PointingHandCursor)
        self._checked = checked
        self._knob_x  = 16 if checked else 2
        self._setup_animation()
    def _setup_animation(self):
        self._anim = QPropertyAnimation(self, b"_knob_pos")
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
    def isChecked(self) -> bool:
        return self._checked
    def setChecked(self, value: bool):
        if value == self._checked:
            return
        self._checked = value
        self._animate_to(16 if value else 2)
        self.toggled.emit(value)
    def mousePressEvent(self, event):
        self.setChecked(not self._checked)
    def _animate_to(self, target_x: int):
        self._anim.stop()
        self._anim.setStartValue(self._knob_x)
        self._anim.setEndValue(target_x)
        self._anim.start()
    def _get_knob_pos(self) -> int:
        return self._knob_x
    def _set_knob_pos(self, x: int):
        self._knob_x = x
        self.update()
    _knob_pos = property(_get_knob_pos, _set_knob_pos)  # type: ignore[assignment]

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QPainterPath, QBrush
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        bg_color = QColor(self._COLOR_ON_BG if self._checked else self._COLOR_OFF_BG)
        knob_color = QColor(self._COLOR_KNOB_ON if self._checked else self._COLOR_KNOB_OFF)

        # Track
        track_path = QPainterPath()
        track_path.addRoundedRect(0, 0, 32, 18, 9, 9)
        painter.fillPath(track_path, QBrush(bg_color))

        # Knob
        knob_path = QPainterPath()
        knob_path.addEllipse(self._knob_x, 2, 14, 14)
        painter.fillPath(knob_path, QBrush(knob_color))

        painter.end()
