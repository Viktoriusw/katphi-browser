#!/usr/bin/env python3
"""
Modern Status Bar - Barra de estado moderna con indicadores SSL y zoom

Características:
- Indicador SSL/HTTPS con iconos
- Mostrar URL al hacer hover sobre links
- Nivel de zoom
- Estado de carga
- Información de certificados
- NavbarLoadingBar: barra de progreso de 2px en navbar
"""

from PySide6.QtWidgets import (QStatusBar, QLabel, QWidget, QHBoxLayout,
                               QPushButton, QMessageBox, QFrame)
from PySide6.QtCore import Qt, QUrl, QByteArray, QPropertyAnimation, QEasingCurve, QTimer, QSize
from PySide6.QtGui import QCursor, QPixmap, QIcon
from PySide6.QtSvg import QSvgRenderer


# ── SVG inline para el indicador SSL ──────────────────────────────────────────

_SVG_LOCK = """<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="11" width="14" height="10" rx="2" fill="{color}"/>
  <path d="M8 11V7a4 4 0 0 1 8 0v4" stroke="{color}" stroke-width="2"
        stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="12" cy="16" r="1.2" fill="white"/>
</svg>"""

_SVG_LOCK_OPEN = """<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="11" width="14" height="10" rx="2" fill="{color}"/>
  <path d="M8 11V7a4 4 0 0 1 8 0" stroke="{color}" stroke-width="2"
        stroke-linecap="round" stroke-linejoin="round"/>
  <line x1="16" y1="4" x2="19" y2="7" stroke="{color}" stroke-width="2"
        stroke-linecap="round"/>
  <circle cx="12" cy="16" r="1.2" fill="white"/>
</svg>"""

_SVG_WARN = """<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"
        fill="{color}"/>
  <line x1="12" y1="9" x2="12" y2="13" stroke="white" stroke-width="2" stroke-linecap="round"/>
  <circle cx="12" cy="17" r="1" fill="white"/>
</svg>"""


def _svg_to_pixmap(svg_template: str, color: str, size: int = 16) -> QPixmap:
    svg = svg_template.replace("{color}", color).encode("utf-8")
    renderer = QSvgRenderer(QByteArray(svg))
    px = QPixmap(QSize(size, size))
    px.fill(Qt.transparent)
    from PySide6.QtGui import QPainter
    p = QPainter(px)
    renderer.render(p)
    p.end()
    return px


# ── SslIndicatorButton ────────────────────────────────────────────────────────

class SslIndicatorButton(QLabel):
    """
    Icono SSL compacto para la barra de navegación.
    Muestra candado cerrado (HTTPS), triángulo de advertencia (HTTP)
    o nada (nueva pestaña / página interna).
    """

    _SIZE = 16   # px del icono SVG
    _BTN  = 28   # px del botón contenedor

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_url = ""
        self.setFixedSize(self._BTN, self._BTN)
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.clear()

    def update_ssl(self, url_string: str):
        """Actualiza el icono según el esquema de la URL."""
        self._current_url = url_string
        if url_string.startswith("https://"):
            px = _svg_to_pixmap(_SVG_LOCK, "#5f9ea0", self._SIZE)
            self.setPixmap(px)
            self.setToolTip("Conexión segura (HTTPS)")
            self.setVisible(True)
        elif url_string.startswith("http://"):
            px = _svg_to_pixmap(_SVG_WARN, "#e5743a", self._SIZE)
            self.setPixmap(px)
            self.setToolTip("Conexión no segura — este sitio no usa HTTPS")
            self.setVisible(True)
        else:
            self.clear()
            self.setToolTip("")
            self.setVisible(False)

    def apply_theme(self, colors: dict):
        """Retiñe el icono con los colores del tema activo."""
        self.update_ssl(self._current_url)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._show_popup()
        super().mousePressEvent(event)

    def _show_popup(self):
        url = QUrl(self._current_url)
        host = url.host() or self._current_url
        if self._current_url.startswith("https://"):
            title = "Conexión segura"
            body  = (f"<b>{host}</b> usa HTTPS.<br><br>"
                     "Tu conexión está cifrada y el sitio ha verificado su identidad.")
        elif self._current_url.startswith("http://"):
            title = "Conexión no segura"
            body  = (f"<b>{host}</b> no usa HTTPS.<br><br>"
                     "La información enviada a este sitio puede ser interceptada por terceros.")
        else:
            return
        msg = QMessageBox()
        msg.setWindowTitle(title)
        msg.setTextFormat(Qt.RichText)
        msg.setText(body)
        msg.setIcon(QMessageBox.Information if "segura" in title else QMessageBox.Warning)
        msg.exec()


class ModernStatusBar(QStatusBar):
    """Status bar moderna estilo Chrome/Firefox"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(24)
        self.current_url = ""
        self.ssl_info = {}

        self.setup_ui()
    def setup_ui(self):
        """Configurar interfaz de usuario"""
        # Widget principal (muestra URLs al hover)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #555; font-size: 12px; padding-left: 8px;")
        self.addWidget(self.status_label, 1)  # Stretch factor 1

        # Widget SSL
        self.ssl_widget = QWidget()
        ssl_layout = QHBoxLayout(self.ssl_widget)
        ssl_layout.setContentsMargins(0, 0, 8, 0)
        ssl_layout.setSpacing(4)

        self.ssl_icon = QLabel()
        self.ssl_text = QLabel()
        self.ssl_text.setStyleSheet("font-size: 11px;")

        # Hacer clickeable para mostrar info del certificado
        self.ssl_widget.setCursor(QCursor(Qt.PointingHandCursor))
        self.ssl_widget.mousePressEvent = self.show_ssl_info

        ssl_layout.addWidget(self.ssl_icon)
        ssl_layout.addWidget(self.ssl_text)

        # Separador
        separator1 = QLabel("|")
        separator1.setStyleSheet("color: #ccc;")
        # Estado de carga
        self.load_label = QLabel("")
        self.load_label.setStyleSheet("font-size: 11px; color: #555;")
        # Separador
        separator2 = QLabel("|")
        separator2.setStyleSheet("color: #ccc;")
        # Nivel de zoom
        self.zoom_label = QLabel("100%")
        self.zoom_label.setFixedWidth(50)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self.zoom_label.setStyleSheet("font-size: 11px; font-weight: bold;")
        self.zoom_label.setCursor(QCursor(Qt.PointingHandCursor))
        self.zoom_label.mousePressEvent = self.reset_zoom_on_click

        # Agregar widgets permanentes (derecha)
        self.addPermanentWidget(self.load_label)
        self.addPermanentWidget(separator1)
        self.addPermanentWidget(self.ssl_widget)
        self.addPermanentWidget(separator2)
        self.addPermanentWidget(self.zoom_label)

        # Estilo general
        self.setStyleSheet("""
            QStatusBar {
                background-color: #f5f5f5;
                border-top: 1px solid #d0d0d0;
            }
            QStatusBar::item {
                border: none;
            }
        """)
    def update_url_hover(self, url):
        """Actualizar texto cuando el mouse pasa sobre un link"""
        if url:
            # Limitar longitud
            display_url = url if len(url) <= 100 else url[:97] + "..."
            self.status_label.setText(f"{display_url}")
        else:
            self.status_label.setText("")
    def _set_ssl_icon(self, icon_name, color):
        """Icono SVG del indicador de conexión (candado, aviso, carpeta)."""
        try:
            from ui.core.strip_icons import build_nav_icon
            self.ssl_icon.setPixmap(build_nav_icon(icon_name, color, QSize(14, 14)).pixmap(14, 14))
        except Exception:
            self.ssl_icon.clear()
    def update_ssl_status(self, url_string):
        """Actualizar indicador SSL basado en la URL"""
        self.current_url = url_string

        if url_string.startswith('https://'):
            self._set_ssl_icon("lock", "#28a745")
            self.ssl_text.setText("Seguro")
            self.ssl_widget.setStyleSheet("""
                QWidget {
                    background-color: transparent;
                }
                QLabel {
                    color: #28a745;
                    font-weight: bold;
                }
            """)
            self.ssl_widget.setToolTip("Conexión segura (HTTPS)\nClick para ver detalles del certificado")
        elif url_string.startswith('http://'):
            self._set_ssl_icon("alert-triangle", "#dc3545")
            self.ssl_text.setText("No seguro")
            self.ssl_widget.setStyleSheet("""
                QWidget {
                    background-color: transparent;
                }
                QLabel {
                    color: #dc3545;
                    font-weight: bold;
                }
            """)
            self.ssl_widget.setToolTip("Conexión no segura (HTTP)")
        elif url_string.startswith('file://'):
            self._set_ssl_icon("folder", None)
            self.ssl_text.setText("Local")
            self.ssl_widget.setStyleSheet("""
                QWidget {
                    background-color: transparent;
                }
                QLabel {
                    color: #6c757d;
                }
            """)
            self.ssl_widget.setToolTip("Archivo local")
        else:
            self.ssl_icon.clear()
            self.ssl_text.setText("")
            self.ssl_widget.setToolTip("")
    def update_load_status(self, status):
        """Actualizar estado de carga"""
        self.load_label.setText(status)
    def update_load_progress(self, progress):
        """Actualizar progreso de carga (0-100)"""
        if progress < 100:
            self.load_label.setText(f"Cargando... {progress}%")
        else:
            self.load_label.setText("Completado")
            # Limpiar después de 2 segundos
            from PySide6.QtCore import QTimer
            QTimer.singleShot(2000, lambda: self.load_label.setText(""))
    def update_zoom(self, zoom_factor):
        """Actualizar nivel de zoom"""
        zoom_percent = int(zoom_factor * 100)
        self.zoom_label.setText(f"{zoom_percent}%")

        # Cambiar color si no es 100%
        if zoom_percent != 100:
            self.zoom_label.setStyleSheet("font-size: 11px; font-weight: bold; color: #007bff;")
        else:
            self.zoom_label.setStyleSheet("font-size: 11px; font-weight: bold;")
        self.zoom_label.setToolTip(f"Zoom: {zoom_percent}%\nClick para restablecer a 100%")
    def reset_zoom_on_click(self, event):
        """Restablecer zoom al hacer click en el indicador"""
        # Emitir señal para que el navegador restablezca el zoom
        if hasattr(self.parent(), 'zoom_reset'):
            self.parent().zoom_reset()
    def show_ssl_info(self, event):
        """Mostrar información del certificado SSL"""
        if not self.current_url.startswith('https://'):
            return
        # Extraer dominio
        url = QUrl(self.current_url)
        host = url.host()

        # Información básica (en una implementación real, obtendríamos
        # info del certificado vía QWebEngineCertificateError)
        info_text = f"""
        <h3>Información de Seguridad</h3>

        <p><b>Sitio web:</b> {host}</p>
        <p><b>Protocolo:</b> HTTPS (Seguro)</p>

        <p><b>Conexión:</b></p>
        <ul>
            <li>Tu conexión a este sitio está encriptada</li>
            <li>Los certificados son válidos</li>
            <li>La identidad del sitio ha sido verificada</li>
        </ul>

        <p><small>Para ver detalles completos del certificado, abre las herramientas de desarrollador.</small></p>
        """

        msg = QMessageBox(self)
        msg.setWindowTitle("Información de Seguridad")
        msg.setTextFormat(Qt.RichText)
        msg.setText(info_text)
        msg.setIcon(QMessageBox.Information)
        msg.exec()
    def show_message(self, message, timeout=3000):
        """Mostrar mensaje temporal en la status bar"""
        self.showMessage(message, timeout)


# ─── NavbarLoadingBar ─────────────────────────────────────────────────────────

class NavbarLoadingBar(QFrame):
    """
    Barra de progreso de carga — línea de 2px en la parte superior de la navbar.

    Uso:
        bar = NavbarLoadingBar(navbar_widget)
        # Conectar a señales del QWebEngineView:
        web_view.loadStarted.connect(bar.on_load_started)
        web_view.loadProgress.connect(bar.on_load_progress)
        web_view.loadFinished.connect(bar.on_load_finished)
    """

    _ACCENT = "#4B9EFF"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(2)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._progress = 0

        self.setStyleSheet(
            f"QFrame {{ background: {self._ACCENT}; border: none; }}"
        )
        self.hide()

        # Animación de progreso (valor lógico 0–100)
        self._prog_anim = QPropertyAnimation(self, b"_bar_progress")
        self._prog_anim.setDuration(300)
        self._prog_anim.setEasingCurve(QEasingCurve.OutCubic)

        # Animación de fade-out al finalizar
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._fade_anim = QPropertyAnimation(self._opacity, b"opacity")
        self._fade_anim.setDuration(300)
        self._fade_anim.finished.connect(self.hide)
    def _get_progress(self) -> int:
        return self._progress
    def _set_progress(self, value: int):
        self._progress = value
        self._update_width()
    _bar_progress = property(_get_progress, _set_progress)  # type: ignore

    def _update_width(self):
        parent = self.parentWidget()
        if parent:
            total = parent.width()
            w = int(total * self._progress / 100)
            self.setFixedWidth(max(0, w))
    def resizeEvent(self, event):
        self._update_width()
        super().resizeEvent(event)
    # ── API pública ────────────────────────────────────────────────────────────

    def on_load_started(self):
        """Llamar cuando comienza la carga (loadStarted signal)."""
        self._fade_anim.stop()
        self._opacity.setOpacity(1.0)
        self._set_progress(0)
        self.show()
        self.raise_()
        self._animate_to(15)  # Arranque inmediato hasta 15%
    def on_load_progress(self, progress: int):
        """Llamar con el progreso de carga 0-100 (loadProgress signal)."""
        self._animate_to(min(95, progress))  # No llegar a 100 hasta finish
    def on_load_finished(self, ok: bool):
        """Llamar cuando termina la carga (loadFinished signal)."""
        self._animate_to(100)
        # Fade out tras 300ms
        QTimer.singleShot(300, self._fade_out)
    def _animate_to(self, target: int):
        self._prog_anim.stop()
        self._prog_anim.setStartValue(self._progress)
        self._prog_anim.setEndValue(target)
        self._prog_anim.start()
    def _fade_out(self):
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()
