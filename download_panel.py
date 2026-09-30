#!/usr/bin/env python3
"""
Download Panel - Panel persistente de descargas estilo Chrome/Firefox

Características:
- Lista de descargas activas e históricas
- Botones: pausar, reanudar, cancelar, abrir archivo/carpeta
- Progreso visual con barra y velocidad
- Historial persistente en SQLite
- Estimación de tiempo restante
"""

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QProgressBar, QListWidget, QListWidgetItem,
                               QFrame, QScrollArea, QMessageBox)
from PySide6.QtCore import Qt, Signal, QTimer, QUrl, QSize
from PySide6.QtGui import QFont, QIcon, QDesktopServices
from PySide6.QtWebEngineCore import QWebEngineDownloadRequest


def _themed_icon(name: str, size: int = 16) -> QIcon:
    """Icono SVG de icons/ teñido con el color del tema activo."""
    try:
        from ui.core.strip_icons import build_nav_icon
        return build_nav_icon(name, None, QSize(size, size))
    except Exception:
        return QIcon()
import sqlite3
import os
import time
from datetime import datetime
from pathlib import Path


class DownloadPanel(QWidget):
    """Panel principal de descargas"""

    download_opened = Signal(str)  # Cuando se abre un archivo descargado

    def __init__(self, parent=None):
        super().__init__(parent)
        self.downloads = []  # Lista de (item, widget)
        self.db_path = "downloads_history.db"

        # Diccionario para trackear conexiones de señales y prevenir memory leaks
        self._signal_connections = {}

        self.setup_database()
        self.setup_ui()
        self.load_history()
    def setup_database(self):
        """Crear base de datos para historial de descargas"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    url TEXT NOT NULL,
                    path TEXT NOT NULL,
                    size INTEGER,
                    status TEXT,
                    start_time TIMESTAMP,
                    end_time TIMESTAMP
                )
            """)
            conn.commit()
            conn.close()
            print("[DownloadPanel] Database initialized")
        except Exception as e:
            print(f"[DownloadPanel] Error creating database: {e}")
    def setup_ui(self):
        """Configurar interfaz de usuario"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Header
        header_layout = QHBoxLayout()

        title = QLabel("Descargas")
        title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        header_layout.addWidget(title)

        header_layout.addStretch()

        # Botón para limpiar completadas
        self.clear_btn = QPushButton("Limpiar completadas")
        self.clear_btn.setToolTip("Eliminar descargas completadas de la lista")
        clear_btn_connection = self.clear_completed
        self.clear_btn.clicked.connect(clear_btn_connection)
        self._signal_connections['clear_btn'] = clear_btn_connection
        header_layout.addWidget(self.clear_btn)

        # Botón para abrir carpeta de descargas
        self.open_folder_btn = QPushButton("Abrir carpeta")
        self.open_folder_btn.setToolTip("Abrir carpeta de descargas")
        open_folder_btn_connection = self.open_downloads_folder
        self.open_folder_btn.clicked.connect(open_folder_btn_connection)
        self._signal_connections['open_folder_btn'] = open_folder_btn_connection
        header_layout.addWidget(self.open_folder_btn)

        layout.addLayout(header_layout)

        # Separador
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        # Lista de descargas con scroll
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_widget = QWidget()
        self.downloads_layout = QVBoxLayout(scroll_widget)
        self.downloads_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.downloads_layout.setSpacing(8)

        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)

        # Mensaje cuando no hay descargas
        self.empty_label = QLabel("No hay descargas recientes")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: #888; font-size: 14px; margin-top: 50px;")
        self.downloads_layout.addWidget(self.empty_label)

        # Estilo general
        self.setStyleSheet("""
            DownloadPanel {
                background-color: #f8f9fa;
            }
            QPushButton {
                padding: 6px 12px;
                border: 1px solid #ccc;
                border-radius: 4px;
                background-color: white;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #e8e8e8;
            }
            QPushButton:pressed {
                background-color: #d0d0d0;
            }
        """)
    def add_download(self, download_request):
        """Agregar nueva descarga al panel"""
        # Ocultar mensaje de vacío
        self.empty_label.hide()

        # Crear widget para la descarga
        download_widget = DownloadItemWidget(download_request, self)

        # Conectar señales y guardar referencias
        widget_id = id(download_widget)
        self._signal_connections[widget_id] = {}

        removed_connection = self.remove_download_widget
        download_widget.download_removed.connect(removed_connection)
        self._signal_connections[widget_id]['download_removed'] = removed_connection

        finished_connection = self.save_to_history
        download_widget.download_finished.connect(finished_connection)
        self._signal_connections[widget_id]['download_finished'] = finished_connection

        # Agregar al layout
        self.downloads_layout.insertWidget(0, download_widget)  # Agregar al principio
        self.downloads.append(download_widget)

        print(f"[DownloadPanel] Added download: {download_request.suggestedFileName()}")
    def remove_download_widget(self, widget):
        """Remover widget de descarga"""
        if widget in self.downloads:
            # Desconectar señales del widget antes de eliminarlo
            widget_id = id(widget)
            if widget_id in self._signal_connections:
                connections = self._signal_connections[widget_id]

                try:
                    if 'download_removed' in connections:
                        widget.download_removed.disconnect(connections['download_removed'])
                except:
                    pass
                try:
                    if 'download_finished' in connections:
                        widget.download_finished.disconnect(connections['download_finished'])
                except:
                    pass
                del self._signal_connections[widget_id]
            self.downloads.remove(widget)
            self.downloads_layout.removeWidget(widget)
            widget.deleteLater()
        # Mostrar mensaje de vacío si no hay descargas
        if not self.downloads:
            self.empty_label.show()
    def clear_completed(self):
        """Limpiar descargas completadas"""
        for widget in self.downloads[:]:  # Copiar lista para modificar durante iteración
            if widget.is_finished():
                self.remove_download_widget(widget)
    def open_downloads_folder(self):
        """Abrir carpeta de descargas del sistema"""
        from PySide6.QtCore import QStandardPaths
        download_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        QDesktopServices.openUrl(QUrl.fromLocalFile(download_dir))
    def save_to_history(self, filename, url, path, size, status):
        """Guardar descarga en historial"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO downloads (filename, url, path, size, status, start_time, end_time)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (filename, url, path, size, status,
                  datetime.now().isoformat(),
                  datetime.now().isoformat()))
            conn.commit()
            conn.close()
            print(f"[DownloadPanel] Saved to history: {filename}")
        except Exception as e:
            print(f"[DownloadPanel] Error saving to history: {e}")
    def load_history(self):
        """Cargar historial de descargas (últimas 10)"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT filename, path, size, status, end_time
                FROM downloads
                ORDER BY end_time DESC
                LIMIT 10
            """)

            results = cursor.fetchall()
            for row in results:
                filename, path, size, status, end_time = row
                # Crear widget de historial (solo si el archivo aún existe)
                if os.path.exists(path):
                    # TODO: Crear widget de historial (sin barra de progreso)
                    pass
            conn.close()
        except Exception as e:
            print(f"[DownloadPanel] Error loading history: {e}")
    def _disconnect_signals(self):
        """Desconectar todas las señales para prevenir memory leaks"""
        try:
            # Desconectar señales de botones
            try:
                if 'clear_btn' in self._signal_connections:
                    self.clear_btn.clicked.disconnect(self._signal_connections['clear_btn'])
                    del self._signal_connections['clear_btn']
            except:
                pass
            try:
                if 'open_folder_btn' in self._signal_connections:
                    self.open_folder_btn.clicked.disconnect(self._signal_connections['open_folder_btn'])
                    del self._signal_connections['open_folder_btn']
            except:
                pass
            # Desconectar señales de widgets de descarga
            for widget in self.downloads[:]:
                widget_id = id(widget)
                if widget_id in self._signal_connections:
                    connections = self._signal_connections[widget_id]

                    try:
                        if 'download_removed' in connections:
                            widget.download_removed.disconnect(connections['download_removed'])
                    except:
                        pass
                    try:
                        if 'download_finished' in connections:
                            widget.download_finished.disconnect(connections['download_finished'])
                    except:
                        pass
                    del self._signal_connections[widget_id]
        except Exception as e:
            print(f"Error al desconectar señales del DownloadPanel: {str(e)}")
    def closeEvent(self, event):
        """Manejar cierre del panel"""
        self._disconnect_signals()
        super().closeEvent(event)
    def __del__(self):
        """Destructor del panel"""
        self._disconnect_signals()


class DownloadItemWidget(QWidget):
    """Widget para un item de descarga individual"""

    download_removed = Signal(object)  # Emitir cuando se remueve
    download_finished = Signal(str, str, str, int, str)  # filename, url, path, size, status

    def __init__(self, download_request, parent=None):
        super().__init__(parent)
        self.download = download_request
        self.filename = download_request.suggestedFileName()
        self.url = download_request.url().toString()
        self.path = ""
        self.is_paused = False
        self.start_time = time.time()
        self.last_received = 0
        self.last_time = time.time()
        self.speeds = []  # Últimas velocidades para promedio

        self.setup_ui()
        self.connect_signals()
    def setup_ui(self):
        """Configurar interfaz del item"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # Container con borde
        container = QFrame()
        container.setFrameShape(QFrame.Shape.StyledPanel)
        container.setStyleSheet("""
            QFrame {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 6px;
                padding: 8px;
            }
        """)

        container_layout = QVBoxLayout(container)
        container_layout.setSpacing(6)

        # Primera fila: Nombre del archivo y botones
        top_layout = QHBoxLayout()

        # Icono y nombre
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(24, 24)
        top_layout.addWidget(self.icon_label)
        self.update_icon()

        self.filename_label = QLabel(self.filename)
        self.filename_label.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        self.filename_label.setWordWrap(True)
        top_layout.addWidget(self.filename_label, 1)

        # Botones de control
        self.pause_btn = QPushButton()
        self.pause_btn.setIcon(_themed_icon("pause"))
        self.pause_btn.setFixedSize(32, 32)
        self.pause_btn.setToolTip("Pausar descarga")
        self.pause_btn.clicked.connect(self.toggle_pause)
        top_layout.addWidget(self.pause_btn)

        self.cancel_btn = QPushButton()
        self.cancel_btn.setIcon(_themed_icon("ide_close"))
        self.cancel_btn.setFixedSize(32, 32)
        self.cancel_btn.setToolTip("Cancelar descarga")
        self.cancel_btn.clicked.connect(self.cancel_download)
        top_layout.addWidget(self.cancel_btn)

        container_layout.addLayout(top_layout)

        # Segunda fila: Barra de progreso
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ccc;
                border-radius: 4px;
                text-align: center;
                height: 24px;
            }
            QProgressBar::chunk {
                background-color: #4a90e2;
                border-radius: 3px;
            }
        """)
        container_layout.addWidget(self.progress_bar)

        # Tercera fila: Info de descarga
        info_layout = QHBoxLayout()

        self.size_label = QLabel("0 KB / 0 KB")
        self.size_label.setStyleSheet("color: #666; font-size: 11px;")
        info_layout.addWidget(self.size_label)

        info_layout.addStretch()

        self.speed_label = QLabel("0 KB/s")
        self.speed_label.setStyleSheet("color: #666; font-size: 11px;")
        info_layout.addWidget(self.speed_label)

        self.time_label = QLabel("")
        self.time_label.setStyleSheet("color: #666; font-size: 11px;")
        info_layout.addWidget(self.time_label)

        container_layout.addLayout(info_layout)

        # Botones de acción (aparecen cuando termina)
        actions_layout = QHBoxLayout()

        self.open_file_btn = QPushButton("Abrir archivo")
        self.open_file_btn.clicked.connect(self.open_file)
        self.open_file_btn.hide()
        actions_layout.addWidget(self.open_file_btn)

        self.open_folder_btn = QPushButton("Abrir carpeta")
        self.open_folder_btn.clicked.connect(self.open_folder)
        self.open_folder_btn.hide()
        actions_layout.addWidget(self.open_folder_btn)

        actions_layout.addStretch()

        container_layout.addLayout(actions_layout)

        main_layout.addWidget(container)
    def connect_signals(self):
        """Conectar señales de descarga"""
        self.download.receivedBytesChanged.connect(self.update_progress)
        self.download.stateChanged.connect(self.on_state_changed)
    def disconnect_signals(self):
        """Desconectar señales para prevenir memory leaks"""
        try:
            self.download.receivedBytesChanged.disconnect(self.update_progress)
        except:
            pass
        try:
            self.download.stateChanged.disconnect(self.on_state_changed)
        except:
            pass
    def closeEvent(self, event):
        """Manejar cierre del widget"""
        self.disconnect_signals()
        super().closeEvent(event)
    def __del__(self):
        """Destructor del widget"""
        self.disconnect_signals()
    def update_progress(self):
        """Actualizar progreso de descarga"""
        received = self.download.receivedBytes()
        total = self.download.totalBytes()

        if total > 0:
            # Actualizar barra de progreso
            progress = int((received / total) * 100)
            self.progress_bar.setValue(progress)

            # Actualizar tamaños
            self.size_label.setText(f"{self.format_size(received)} / {self.format_size(total)}")

            # Calcular velocidad
            current_time = time.time()
            time_diff = current_time - self.last_time

            if time_diff >= 0.5:  # Actualizar cada 0.5 segundos
                bytes_diff = received - self.last_received
                speed = bytes_diff / time_diff if time_diff > 0 else 0

                # Guardar velocidad para promedio
                self.speeds.append(speed)
                if len(self.speeds) > 10:
                    self.speeds.pop(0)
                avg_speed = sum(self.speeds) / len(self.speeds) if self.speeds else 0
                self.speed_label.setText(f"{self.format_size(avg_speed)}/s")

                # Calcular tiempo restante
                if avg_speed > 0:
                    remaining_bytes = total - received
                    remaining_seconds = remaining_bytes / avg_speed
                    self.time_label.setText(f"{self.format_time(remaining_seconds)}")
                self.last_received = received
                self.last_time = current_time
    def on_state_changed(self, state):
        """Manejar cambios de estado"""
        if state == QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
            self.on_download_completed()
        elif state == QWebEngineDownloadRequest.DownloadState.DownloadCancelled:
            self.on_download_cancelled()
        elif state == QWebEngineDownloadRequest.DownloadState.DownloadInterrupted:
            self.on_download_failed()
    def on_download_completed(self):
        """Descarga completada"""
        self.progress_bar.setValue(100)
        self.speed_label.setText("Completado")
        self.time_label.setText("")

        # Ocultar botones de control
        self.pause_btn.hide()
        self.cancel_btn.hide()

        # Mostrar botones de acción
        self.open_file_btn.show()
        self.open_folder_btn.show()

        # Actualizar icono según tipo de archivo
        self.update_icon()

        # Guardar ruta completa
        self.path = os.path.join(
            self.download.downloadDirectory(),
            self.download.downloadFileName()
        )

        # Emitir señal para guardar en historial
        self.download_finished.emit(
            self.filename,
            self.url,
            self.path,
            self.download.totalBytes(),
            "completed"
        )

        print(f"[Download] Completed: {self.filename}")
    def on_download_cancelled(self):
        """Descarga cancelada"""
        self.speed_label.setText("Cancelada")
        self.time_label.setText("")
        self.progress_bar.setStyleSheet("""
            QProgressBar::chunk {
                background-color: #dc3545;
            }
        """)
    def on_download_failed(self):
        """Descarga fallida"""
        self.speed_label.setText("Error")
        self.time_label.setText("")
        self.progress_bar.setStyleSheet("""
            QProgressBar::chunk {
                background-color: #ffc107;
            }
        """)
    def toggle_pause(self):
        """Pausar/reanudar descarga"""
        if self.is_paused:
            self.download.resume()
            self.pause_btn.setIcon(_themed_icon("pause"))
            self.pause_btn.setToolTip("Pausar descarga")
            self.is_paused = False
            self.speed_label.setText("Descargando...")
        else:
            self.download.pause()
            self.pause_btn.setIcon(_themed_icon("play"))
            self.pause_btn.setToolTip("Reanudar descarga")
            self.is_paused = True
            self.speed_label.setText("Pausada")
            self.time_label.setText("")
    def cancel_download(self):
        """Cancelar descarga"""
        reply = QMessageBox.question(
            self,
            "Cancelar descarga",
            f"¿Seguro que quieres cancelar la descarga de '{self.filename}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.download.cancel()
    def open_file(self):
        """Abrir archivo descargado"""
        if self.path and os.path.exists(self.path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.path))
        else:
            QMessageBox.warning(self, "Archivo no encontrado",
                              "El archivo descargado ya no existe en la ubicación original.")
    def open_folder(self):
        """Abrir carpeta contenedora"""
        if self.path:
            folder = os.path.dirname(self.path)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
    def is_finished(self):
        """Verificar si la descarga terminó"""
        state = self.download.state()
        return state in [
            QWebEngineDownloadRequest.DownloadState.DownloadCompleted,
            QWebEngineDownloadRequest.DownloadState.DownloadCancelled,
            QWebEngineDownloadRequest.DownloadState.DownloadInterrupted
        ]
    def update_icon(self):
        """Actualizar icono según tipo de archivo"""
        ext = os.path.splitext(self.filename)[1].lower()

        icons = {
            '.pdf': 'file-pdf',
            '.xls': 'file-excel', '.xlsx': 'file-excel',
            '.csv': 'file-csv', '.json': 'file-json',
            '.zip': 'folder', '.rar': 'folder', '.7z': 'folder',
            '.jpg': 'image', '.jpeg': 'image', '.png': 'image', '.gif': 'image', '.webp': 'image', '.svg': 'image',
            '.mp3': 'play', '.wav': 'play', '.ogg': 'play',
            '.mp4': 'play', '.avi': 'play', '.mkv': 'play',
            '.py': 'code', '.js': 'code', '.html': 'code',
        }

        self.icon_label.setPixmap(_themed_icon(icons.get(ext, 'file-text'), 22).pixmap(22, 22))
    @staticmethod
    def format_size(bytes_size):
        """Formatear tamaño en bytes a formato legible"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.1f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.1f} TB"
    @staticmethod
    def format_time(seconds):
        """Formatear segundos a formato legible"""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            return f"{hours}h {minutes}m"
