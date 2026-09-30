#!/usr/bin/env python3
"""
Screenshot Advanced - Capturas de pantalla avanzadas con selección de región y anotaciones

Características adicionales:
- Captura de región específica con selector visual
- Anotaciones básicas (texto, flechas, resaltados)
- Captura de elemento específico del DOM
"""

from PySide6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QColorDialog, QSpinBox, QLineEdit, QComboBox,
                               QToolBar, QApplication)
from PySide6.QtCore import Qt, QRect, QPoint, Signal
from PySide6.QtGui import (QPainter, QPen, QColor, QPixmap, QImage, QCursor, QFont,
                          QBrush, QPainterPath)
from PySide6.QtWebEngineWidgets import QWebEngineView


class RegionSelector(QWidget):
    """Widget para seleccionar región de captura"""

    region_selected = Signal(QRect)

    def __init__(self, screenshot_image, parent=None):
        super().__init__(parent)
        self.screenshot = screenshot_image
        self.start_point = None
        self.end_point = None
        self.selecting = False

        # Configurar ventana
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.showFullScreen()
        self.setCursor(Qt.CrossCursor)
    def paintEvent(self, event):
        """Dibujar screenshot con overlay de selección"""
        painter = QPainter(self)

        # Dibujar screenshot de fondo
        if self.screenshot:
            painter.drawPixmap(0, 0, QPixmap.fromImage(self.screenshot))
        # Overlay oscuro
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))

        # Si hay selección, mostrar región clara
        if self.start_point and self.end_point:
            selection_rect = QRect(self.start_point, self.end_point).normalized()

            # Región seleccionada (clara)
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(selection_rect, Qt.transparent)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

            # Dibujar screenshot en región seleccionada
            if self.screenshot:
                painter.drawPixmap(selection_rect, QPixmap.fromImage(self.screenshot), selection_rect)
            # Borde de selección
            pen = QPen(QColor(0, 120, 215), 2, Qt.SolidLine)
            painter.setPen(pen)
            painter.drawRect(selection_rect)

            # Mostrar dimensiones
            width = selection_rect.width()
            height = selection_rect.height()
            text = f"{width} x {height}"

            painter.setPen(Qt.white)
            painter.setFont(QFont("Arial", 12, QFont.Bold))
            painter.drawText(
                selection_rect.x() + 5,
                selection_rect.y() - 5,
                text
            )
    def mousePressEvent(self, event):
        """Iniciar selección"""
        if event.button() == Qt.LeftButton:
            self.start_point = event.pos()
            self.end_point = event.pos()
            self.selecting = True
            self.update()
    def mouseMoveEvent(self, event):
        """Actualizar selección"""
        if self.selecting:
            self.end_point = event.pos()
            self.update()
    def mouseReleaseEvent(self, event):
        """Finalizar selección"""
        if event.button() == Qt.LeftButton and self.selecting:
            self.selecting = False

            if self.start_point and self.end_point:
                selection_rect = QRect(self.start_point, self.end_point).normalized()

                # Validar que la selección tenga tamaño mínimo
                if selection_rect.width() > 10 and selection_rect.height() > 10:
                    self.region_selected.emit(selection_rect)
                    self.close()
    def keyPressEvent(self, event):
        """Cancelar con ESC"""
        if event.key() == Qt.Key_Escape:
            self.close()


class AnnotationEditor(QDialog):
    """Editor de anotaciones para screenshots"""

    def __init__(self, image, parent=None):
        super().__init__(parent)
        self.original_image = image
        self.current_image = image.copy()
        self.annotations = []
        self.current_tool = "none"
        self.current_color = QColor(255, 0, 0)
        self.current_width = 3

        self.setWindowTitle("Editar captura")
        self.setMinimumSize(800, 600)

        self.setup_ui()
    def setup_ui(self):
        """Configurar interfaz"""
        layout = QVBoxLayout(self)

        # Toolbar
        toolbar = QToolBar()

        # Herramientas
        self.arrow_btn = QPushButton("Flecha")
        self.arrow_btn.setCheckable(True)
        self.arrow_btn.clicked.connect(lambda: self.set_tool("arrow"))
        toolbar.addWidget(self.arrow_btn)

        self.rect_btn = QPushButton("Rectángulo")
        self.rect_btn.setCheckable(True)
        self.rect_btn.clicked.connect(lambda: self.set_tool("rect"))
        toolbar.addWidget(self.rect_btn)

        self.text_btn = QPushButton("Texto")
        self.text_btn.setCheckable(True)
        self.text_btn.clicked.connect(lambda: self.set_tool("text"))
        toolbar.addWidget(self.text_btn)

        self.highlight_btn = QPushButton("Resaltar")
        self.highlight_btn.setCheckable(True)
        self.highlight_btn.clicked.connect(lambda: self.set_tool("highlight"))
        toolbar.addWidget(self.highlight_btn)

        toolbar.addSeparator()

        # Color
        color_btn = QPushButton("Color")
        color_btn.clicked.connect(self.choose_color)
        toolbar.addWidget(color_btn)

        # Grosor
        toolbar.addWidget(QLabel("Grosor:"))
        self.width_spin = QSpinBox()
        self.width_spin.setMinimum(1)
        self.width_spin.setMaximum(10)
        self.width_spin.setValue(3)
        self.width_spin.valueChanged.connect(lambda v: setattr(self, 'current_width', v))
        toolbar.addWidget(self.width_spin)

        toolbar.addSeparator()

        # Deshacer
        undo_btn = QPushButton("Deshacer")
        undo_btn.clicked.connect(self.undo)
        toolbar.addWidget(undo_btn)

        # Limpiar
        clear_btn = QPushButton("Limpiar todo")
        clear_btn.clicked.connect(self.clear_all)
        toolbar.addWidget(clear_btn)

        layout.addWidget(toolbar)

        # Canvas
        self.canvas = AnnotationCanvas(self.current_image, self)
        self.canvas.annotation_added.connect(self.add_annotation)
        layout.addWidget(self.canvas)

        # Botones
        buttons_layout = QHBoxLayout()

        save_btn = QPushButton("Guardar")
        save_btn.clicked.connect(self.accept)
        buttons_layout.addWidget(save_btn)

        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_btn)

        layout.addLayout(buttons_layout)
    def set_tool(self, tool):
        """Cambiar herramienta activa"""
        self.current_tool = tool
        self.canvas.current_tool = tool
        self.canvas.current_color = self.current_color
        self.canvas.current_width = self.current_width

        # Actualizar botones
        self.arrow_btn.setChecked(tool == "arrow")
        self.rect_btn.setChecked(tool == "rect")
        self.text_btn.setChecked(tool == "text")
        self.highlight_btn.setChecked(tool == "highlight")
    def choose_color(self):
        """Elegir color"""
        color = QColorDialog.getColor(self.current_color, self)
        if color.isValid():
            self.current_color = color
            if self.canvas:
                self.canvas.current_color = color
    def add_annotation(self, annotation):
        """Agregar anotación"""
        self.annotations.append(annotation)
        self.current_image = self.canvas.get_image()
    def undo(self):
        """Deshacer última anotación"""
        if self.annotations:
            self.annotations.pop()
            self.canvas.annotations = self.annotations.copy()
            self.canvas.update()
            self.current_image = self.canvas.get_image()
    def clear_all(self):
        """Limpiar todas las anotaciones"""
        self.annotations.clear()
        self.canvas.annotations.clear()
        self.canvas.update()
        self.current_image = self.original_image.copy()
    def get_annotated_image(self):
        """Obtener imagen con anotaciones"""
        return self.canvas.get_image()


class AnnotationCanvas(QWidget):
    """Canvas para dibujar anotaciones"""

    annotation_added = Signal(dict)

    def __init__(self, image, parent=None):
        super().__init__(parent)
        self.image = image
        self.annotations = []
        self.current_tool = "none"
        self.current_color = QColor(255, 0, 0)
        self.current_width = 3
        self.start_point = None
        self.end_point = None
        self.drawing = False

        self.setMinimumSize(600, 400)
    def paintEvent(self, event):
        """Dibujar imagen y anotaciones"""
        painter = QPainter(self)

        # Dibujar imagen de fondo
        if self.image:
            scaled_image = self.image.scaled(
                self.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            x = (self.width() - scaled_image.width()) // 2
            y = (self.height() - scaled_image.height()) // 2
            painter.drawImage(x, y, scaled_image)
        # Dibujar anotaciones guardadas
        for annotation in self.annotations:
            self.draw_annotation(painter, annotation)
        # Dibujar anotación en progreso
        if self.drawing and self.start_point and self.end_point:
            temp_annotation = {
                'type': self.current_tool,
                'start': self.start_point,
                'end': self.end_point,
                'color': self.current_color,
                'width': self.current_width
            }
            self.draw_annotation(painter, temp_annotation)
    def draw_annotation(self, painter, annotation):
        """Dibujar una anotación específica"""
        pen = QPen(annotation['color'], annotation['width'])
        painter.setPen(pen)

        start = annotation['start']
        end = annotation['end']

        if annotation['type'] == 'arrow':
            # Dibujar línea
            painter.drawLine(start, end)

            # Dibujar punta de flecha
            angle = QPoint(end - start)
            import math
            arrow_angle = math.atan2(angle.y(), angle.x())
            arrow_size = 15

            p1 = QPoint(
                int(end.x() - arrow_size * math.cos(arrow_angle - math.pi / 6)),
                int(end.y() - arrow_size * math.sin(arrow_angle - math.pi / 6))
            )
            p2 = QPoint(
                int(end.x() - arrow_size * math.cos(arrow_angle + math.pi / 6)),
                int(end.y() - arrow_size * math.sin(arrow_angle + math.pi / 6))
            )

            painter.drawLine(end, p1)
            painter.drawLine(end, p2)
        elif annotation['type'] == 'rect':
            rect = QRect(start, end).normalized()
            painter.drawRect(rect)
        elif annotation['type'] == 'highlight':
            rect = QRect(start, end).normalized()
            # Semi-transparente
            color = QColor(annotation['color'])
            color.setAlpha(100)
            painter.fillRect(rect, color)
        elif annotation['type'] == 'text':
            if 'text' in annotation:
                painter.setFont(QFont("Arial", 14, QFont.Bold))
                painter.drawText(start, annotation['text'])
    def mousePressEvent(self, event):
        """Iniciar anotación"""
        if event.button() == Qt.LeftButton and self.current_tool != "none":
            self.start_point = event.pos()
            self.end_point = event.pos()
            self.drawing = True

            # Para texto, pedir input inmediatamente
            if self.current_tool == "text":
                from PySide6.QtWidgets import QInputDialog
                text, ok = QInputDialog.getText(self, "Texto", "Ingrese el texto:")
                if ok and text:
                    annotation = {
                        'type': 'text',
                        'start': self.start_point,
                        'end': self.start_point,
                        'color': self.current_color,
                        'width': self.current_width,
                        'text': text
                    }
                    self.annotations.append(annotation)
                    self.annotation_added.emit(annotation)
                    self.update()
                self.drawing = False
    def mouseMoveEvent(self, event):
        """Actualizar anotación"""
        if self.drawing:
            self.end_point = event.pos()
            self.update()
    def mouseReleaseEvent(self, event):
        """Finalizar anotación"""
        if event.button() == Qt.LeftButton and self.drawing:
            self.drawing = False

            if self.current_tool != "text":  # Texto ya se maneja en mousePressEvent
                annotation = {
                    'type': self.current_tool,
                    'start': self.start_point,
                    'end': self.end_point,
                    'color': self.current_color,
                    'width': self.current_width
                }
                self.annotations.append(annotation)
                self.annotation_added.emit(annotation)
                self.update()
    def get_image(self):
        """Obtener imagen con anotaciones renderizadas"""
        # Crear imagen del tamaño original
        result = QImage(self.image.size(), QImage.Format_ARGB32)
        result.fill(Qt.white)

        painter = QPainter(result)

        # Dibujar imagen original
        painter.drawImage(0, 0, self.image)

        # Calcular escala
        scale_x = self.image.width() / self.width()
        scale_y = self.image.height() / self.height()

        # Dibujar anotaciones escaladas
        for annotation in self.annotations:
            scaled_annotation = annotation.copy()
            scaled_annotation['start'] = QPoint(
                int(annotation['start'].x() * scale_x),
                int(annotation['start'].y() * scale_y)
            )
            scaled_annotation['end'] = QPoint(
                int(annotation['end'].x() * scale_x),
                int(annotation['end'].y() * scale_y)
            )
            self.draw_annotation(painter, scaled_annotation)
        painter.end()
        return result


class ElementSelector:
    """Selector de elementos del DOM para captura"""

    @staticmethod
    def capture_element(browser, callback):
        """Capturar un elemento específico del DOM"""
        if not browser or not hasattr(browser, 'page'):
            return
        # JavaScript para resaltar elementos al hover y capturar al click
        js_code = """
        (function() {
            let highlightedElement = null;
            let overlay = null;

            function createOverlay() {
                overlay = document.createElement('div');
                overlay.style.position = 'absolute';
                overlay.style.border = '2px solid #0078d4';
                overlay.style.backgroundColor = 'rgba(0, 120, 212, 0.1)';
                overlay.style.pointerEvents = 'none';
                overlay.style.zIndex = '999999';
                document.body.appendChild(overlay);
            }

            function updateOverlay(element) {
                if (!overlay) createOverlay();
                const rect = element.getBoundingClientRect();
                overlay.style.left = (rect.left + window.scrollX) + 'px';
                overlay.style.top = (rect.top + window.scrollY) + 'px';
                overlay.style.width = rect.width + 'px';
                overlay.style.height = rect.height + 'px';
                overlay.style.display = 'block';
            }

            function hideOverlay() {
                if (overlay) overlay.style.display = 'none';
            }

            document.addEventListener('mouseover', function(e) {
                if (e.target !== overlay) {
                    highlightedElement = e.target;
                    updateOverlay(e.target);
                }
            }, true);

            document.addEventListener('mouseout', function(e) {
                hideOverlay();
            }, true);

            document.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();

                if (highlightedElement) {
                    const rect = highlightedElement.getBoundingClientRect();

                    // Retornar coordenadas del elemento
                    return {
                        x: rect.left + window.scrollX,
                        y: rect.top + window.scrollY,
                        width: rect.width,
                        height: rect.height
                    };
                }
            }, true);

            return 'Element selector activated';
        })();
        """

        browser.page().runJavaScript(js_code, lambda result: print(f"[ElementSelector] {result}"))
