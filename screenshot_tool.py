#!/usr/bin/env python3
"""
Screenshot Tool - Herramienta de captura de pantalla estilo Firefox/Edge

Características:
- Capturar área visible de la página
- Capturar página completa (con scroll automático)
- Guardar como PNG o JPG
- Copiar al portapapeles
- Diálogo de opciones con preview
"""

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QDialog, QFileDialog, QMessageBox,
                               QRadioButton, QButtonGroup, QSpinBox, QCheckBox,
                               QProgressDialog, QApplication)
from PySide6.QtCore import Qt, QTimer, QSize, QRect, QByteArray, QBuffer
from PySide6.QtGui import QPixmap, QImage, QPainter, QClipboard
from PySide6.QtWebEngineWidgets import QWebEngineView
import os
from datetime import datetime
from pathlib import Path


class ScreenshotTool:
    """Herramienta para capturar screenshots de páginas web"""

    def __init__(self, browser_view, parent=None):
        """
        Args:
            browser_view: QWebEngineView - Vista del navegador a capturar
            parent: QWidget - Widget padre (MainWindow)
        """
        self.browser = browser_view
        self.parent = parent
        self.full_page_image = None
        self.capture_in_progress = False
    def show_screenshot_dialog(self):
        """Mostrar diálogo de opciones de captura"""
        if not self.browser:
            QMessageBox.warning(
                self.parent,
                "Sin página activa",
                "No hay ninguna página activa para capturar."
            )
            return
        dialog = ScreenshotDialog(self.browser, self.parent)
        dialog.screenshot_captured.connect(self.on_screenshot_captured)
        dialog.exec()
    def capture_visible_area(self):
        """Capturar solo el área visible de la página"""
        if not self.browser:
            return None
        # Capturar el widget completo
        pixmap = self.browser.grab()
        return pixmap.toImage()
    def capture_full_page(self, callback=None):
        """
        Capturar página completa con scroll automático

        Args:
            callback: Función a llamar cuando termine (recibe QImage)
        """
        if not self.browser or self.capture_in_progress:
            return
        self.capture_in_progress = True
        self.capture_callback = callback

        # Obtener dimensiones de la página
        self.browser.page().runJavaScript("""
            ({
                scrollHeight: document.documentElement.scrollHeight,
                scrollWidth: document.documentElement.scrollWidth,
                clientHeight: window.innerHeight,
                clientWidth: window.innerWidth
            })
        """, self._on_page_dimensions_received)
    def _on_page_dimensions_received(self, dimensions):
        """Callback cuando se reciben las dimensiones de la página"""
        if not dimensions:
            self.capture_in_progress = False
            return
        page_height = dimensions['scrollHeight']
        page_width = dimensions['scrollWidth']
        viewport_height = dimensions['clientHeight']
        viewport_width = dimensions['clientWidth']

        # Crear imagen para la página completa
        self.full_page_image = QImage(page_width, page_height, QImage.Format.Format_ARGB32)
        self.full_page_image.fill(Qt.GlobalColor.white)

        # Configurar variables para el scroll
        self.current_scroll_y = 0
        self.page_height = page_height
        self.viewport_height = viewport_height
        self.captures = []

        # Mostrar diálogo de progreso
        self.progress_dialog = QProgressDialog(
            "Capturando página completa...",
            "Cancelar",
            0,
            page_height,
            self.parent
        )
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.canceled.connect(self._cancel_full_page_capture)

        # Iniciar captura por scroll
        self._capture_next_section()
    def _capture_next_section(self):
        """Capturar la siguiente sección de la página"""
        if self.current_scroll_y >= self.page_height:
            # Terminado - combinar todas las capturas
            self._combine_captures()
            return
        if self.progress_dialog.wasCanceled():
            self._cancel_full_page_capture()
            return
        # Scroll a la posición actual
        js_code = f"window.scrollTo(0, {self.current_scroll_y});"
        self.browser.page().runJavaScript(js_code)

        # Actualizar progreso
        self.progress_dialog.setValue(self.current_scroll_y)

        # Esperar un poco para que se renderice y luego capturar
        QTimer.singleShot(200, self._capture_current_viewport)
    def _capture_current_viewport(self):
        """Capturar el viewport actual"""
        # Capturar área visible
        pixmap = self.browser.grab()
        image = pixmap.toImage()

        # Guardar captura con su posición
        self.captures.append({
            'image': image,
            'y_position': self.current_scroll_y
        })

        # Avanzar al siguiente viewport
        self.current_scroll_y += self.viewport_height

        # Continuar con la siguiente sección
        QTimer.singleShot(100, self._capture_next_section)
    def _combine_captures(self):
        """Combinar todas las capturas en una sola imagen"""
        if not self.captures:
            self._cancel_full_page_capture()
            return
        # Crear painter para dibujar en la imagen completa
        painter = QPainter(self.full_page_image)

        # Dibujar cada captura en su posición
        for capture in self.captures:
            y_pos = capture['y_position']
            image = capture['image']
            painter.drawImage(0, y_pos, image)
        painter.end()

        # Limpiar
        self.captures = []
        self.capture_in_progress = False
        self.progress_dialog.close()

        # Restaurar scroll al inicio
        self.browser.page().runJavaScript("window.scrollTo(0, 0);")

        # Llamar callback con la imagen completa
        if self.capture_callback:
            self.capture_callback(self.full_page_image)
    def _cancel_full_page_capture(self):
        """Cancelar captura de página completa"""
        self.capture_in_progress = False
        self.captures = []
        self.full_page_image = None

        # Restaurar scroll
        if self.browser:
            self.browser.page().runJavaScript("window.scrollTo(0, 0);")
    def save_image(self, image, suggested_filename=None):
        """
        Guardar imagen en disco

        Args:
            image: QImage - Imagen a guardar
            suggested_filename: str - Nombre sugerido para el archivo
        """
        if not image:
            return False
        # Generar nombre por defecto si no se proporciona
        if not suggested_filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            current_url = self.browser.url().host() if self.browser else "screenshot"
            suggested_filename = f"screenshot_{current_url}_{timestamp}.png"
        # Diálogo para guardar
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self.parent,
            "Guardar captura de pantalla",
            os.path.expanduser(f"~/Pictures/{suggested_filename}"),
            "PNG Image (*.png);;JPEG Image (*.jpg *.jpeg);;All Files (*.*)"
        )

        if file_path:
            # Determinar formato según extensión
            ext = os.path.splitext(file_path)[1].lower()
            format_str = "PNG"
            quality = -1  # Mejor calidad

            if ext in ['.jpg', '.jpeg']:
                format_str = "JPEG"
                quality = 95  # Alta calidad para JPEG
            # Guardar imagen
            success = image.save(file_path, format_str, quality)

            if success:
                QMessageBox.information(
                    self.parent,
                    "Captura guardada",
                    f"La captura se guardó exitosamente en:\n{file_path}"
                )
                return True
            else:
                QMessageBox.critical(
                    self.parent,
                    "Error",
                    "No se pudo guardar la captura de pantalla."
                )
                return False
        return False
    def copy_to_clipboard(self, image):
        """
        Copiar imagen al portapapeles

        Args:
            image: QImage - Imagen a copiar
        """
        if not image:
            return False
        clipboard = QApplication.clipboard()
        pixmap = QPixmap.fromImage(image)
        clipboard.setPixmap(pixmap)

        QMessageBox.information(
            self.parent,
            "Copiado al portapapeles",
            "La captura de pantalla se copió al portapapeles."
        )
        return True
    def on_screenshot_captured(self, image):
        """Callback cuando se captura una screenshot desde el diálogo"""
        # Este método se puede usar para procesar la imagen si es necesario
        pass


class ScreenshotDialog(QDialog):
    """Diálogo para opciones de captura de pantalla"""

    from PySide6.QtCore import Signal
    screenshot_captured = Signal(QImage)

    def __init__(self, browser_view, parent=None):
        super().__init__(parent)
        self.browser = browser_view
        self.screenshot_tool = ScreenshotTool(browser_view, parent)
        self.captured_image = None

        self.setWindowTitle("Captura de pantalla")
        self.setModal(True)
        self.setMinimumWidth(400)

        self.setup_ui()
    def setup_ui(self):
        """Configurar interfaz del diálogo"""
        layout = QVBoxLayout(self)

        # Título
        title = QLabel("Captura de pantalla")
        title.setStyleSheet("font-size: 16px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)

        # Opciones de captura
        options_group = QButtonGroup(self)

        self.visible_radio = QRadioButton("Capturar área visible")
        self.visible_radio.setToolTip("Captura solo lo que se ve en pantalla actualmente")
        self.visible_radio.setChecked(True)
        options_group.addButton(self.visible_radio)
        layout.addWidget(self.visible_radio)

        self.fullpage_radio = QRadioButton("Capturar página completa")
        self.fullpage_radio.setToolTip("Captura toda la página haciendo scroll automático")
        options_group.addButton(self.fullpage_radio)
        layout.addWidget(self.fullpage_radio)

        # Separador
        layout.addSpacing(20)

        # Opciones de guardado
        save_label = QLabel("Opciones de guardado:")
        save_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(save_label)

        self.save_file_check = QCheckBox("Guardar en archivo")
        self.save_file_check.setChecked(True)
        layout.addWidget(self.save_file_check)

        self.copy_clipboard_check = QCheckBox("Copiar al portapapeles")
        self.copy_clipboard_check.setChecked(False)
        layout.addWidget(self.copy_clipboard_check)

        # Separador
        layout.addSpacing(20)

        # Botones de acción
        buttons_layout = QHBoxLayout()

        self.capture_btn = QPushButton("Capturar")
        self.capture_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a90e2;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #357abd;
            }
        """)
        self.capture_btn.clicked.connect(self.perform_capture)
        buttons_layout.addWidget(self.capture_btn)

        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_btn)

        layout.addLayout(buttons_layout)

        # Info
        info_label = QLabel(
            "Tip: La captura de página completa puede tardar unos segundos "
            "en páginas largas."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #666; font-size: 11px; margin-top: 10px;")
        layout.addWidget(info_label)
    def perform_capture(self):
        """Realizar la captura según las opciones seleccionadas"""
        if self.visible_radio.isChecked():
            # Captura de área visible
            image = self.screenshot_tool.capture_visible_area()
            if image:
                self.process_captured_image(image)
        else:
            # Captura de página completa
            self.capture_btn.setEnabled(False)
            self.capture_btn.setText("Capturando...")
            self.screenshot_tool.capture_full_page(self.on_full_page_captured)
    def on_full_page_captured(self, image):
        """Callback cuando termina la captura de página completa"""
        self.capture_btn.setEnabled(True)
        self.capture_btn.setText("Capturar")

        if image:
            self.process_captured_image(image)
    def process_captured_image(self, image):
        """Procesar imagen capturada según opciones"""
        if not image:
            return
        self.captured_image = image

        # Guardar en archivo si está marcado
        if self.save_file_check.isChecked():
            self.screenshot_tool.save_image(image)
        # Copiar al portapapeles si está marcado
        if self.copy_clipboard_check.isChecked():
            self.screenshot_tool.copy_to_clipboard(image)
        # Emitir señal
        self.screenshot_captured.emit(image)

        # Cerrar diálogo
        self.accept()


class ScreenshotButton(QPushButton):
    """Botón especializado para captura de pantalla"""

    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            from ui.core.strip_icons import build_nav_icon
            self.setIcon(build_nav_icon("camera", None, QSize(18, 18)))
            self.setIconSize(QSize(18, 18))
        except Exception:
            pass
        self.setToolTip("Captura de pantalla (Ctrl+Shift+S)")
        self.setFixedSize(36, 36)
        self.setStyleSheet("""
            QPushButton {
                border: none;
                border-radius: 18px;
                background-color: transparent;
                font-size: 18px;
            }
            QPushButton:hover {
                background-color: rgba(0, 0, 0, 0.05);
            }
            QPushButton:pressed {
                background-color: rgba(0, 0, 0, 0.1);
            }
        """)
