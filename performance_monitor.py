#!/usr/bin/env python3
"""
Performance Monitor - Gestor de tareas y diagnóstico de rendimiento

Características:
- Monitor de uso de CPU y memoria por pestaña
- Diagnóstico de rendimiento general
- Finalizar pestañas problemáticas
- Estadísticas de red
"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
                               QTableWidgetItem, QPushButton, QLabel, QHeaderView,
                               QMessageBox, QProgressBar)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
import psutil
import os


class PerformanceMonitor(QDialog):
    """Monitor de rendimiento del navegador"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.process = psutil.Process(os.getpid())

        self.setWindowTitle("Administrador de tareas - Katphi")
        self.setMinimumSize(800, 600)
        self.setModal(False)

        self.setup_ui()

        # Timer para actualizar estadísticas
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_stats)
        self.update_timer.start(2000)  # Actualizar cada 2 segundos

        # Actualizar inmediatamente
        self.update_stats()
    def setup_ui(self):
        """Configurar interfaz de usuario"""
        layout = QVBoxLayout(self)

        # Título
        title = QLabel("Administrador de tareas del navegador")
        title.setStyleSheet("font-size: 16px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)

        # Estadísticas generales
        stats_layout = QHBoxLayout()

        # CPU
        cpu_widget = QVBoxLayout()
        self.cpu_label = QLabel("CPU: 0%")
        self.cpu_label.setStyleSheet("font-weight: bold;")
        self.cpu_bar = QProgressBar()
        self.cpu_bar.setMaximum(100)
        self.cpu_bar.setTextVisible(True)
        cpu_widget.addWidget(self.cpu_label)
        cpu_widget.addWidget(self.cpu_bar)
        stats_layout.addLayout(cpu_widget)

        # Memoria
        mem_widget = QVBoxLayout()
        self.mem_label = QLabel("Memoria: 0 MB")
        self.mem_label.setStyleSheet("font-weight: bold;")
        self.mem_bar = QProgressBar()
        self.mem_bar.setMaximum(100)
        self.mem_bar.setTextVisible(True)
        mem_widget.addWidget(self.mem_label)
        mem_widget.addWidget(self.mem_bar)
        stats_layout.addLayout(mem_widget)

        layout.addLayout(stats_layout)

        # Separador
        layout.addSpacing(10)

        # Tabla de pestañas
        tabs_label = QLabel("Pestañas activas:")
        tabs_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(tabs_label)

        self.tabs_table = QTableWidget()
        self.tabs_table.setColumnCount(5)
        self.tabs_table.setHorizontalHeaderLabels([
            "Pestaña", "URL", "Título", "Estado", "Acciones"
        ])

        # Configurar tabla
        header = self.tabs_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)

        self.tabs_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabs_table.setEditTriggers(QTableWidget.NoEditTriggers)

        layout.addWidget(self.tabs_table)

        # Información adicional
        info_layout = QHBoxLayout()

        self.info_label = QLabel()
        self.info_label.setStyleSheet("color: #666; font-size: 11px;")
        info_layout.addWidget(self.info_label)

        info_layout.addStretch()

        # Botón de actualizar
        refresh_btn = QPushButton("Actualizar")
        refresh_btn.clicked.connect(self.update_stats)
        info_layout.addWidget(refresh_btn)

        # Botón de cerrar
        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(self.close)
        info_layout.addWidget(close_btn)

        layout.addLayout(info_layout)
    def update_stats(self):
        """Actualizar estadísticas de rendimiento"""
        try:
            # Estadísticas del proceso
            cpu_percent = self.process.cpu_percent(interval=0.1)
            memory_info = self.process.memory_info()
            memory_mb = memory_info.rss / (1024 * 1024)  # Convertir a MB

            # Actualizar CPU
            self.cpu_label.setText(f"CPU: {cpu_percent:.1f}%")
            self.cpu_bar.setValue(int(min(cpu_percent, 100)))

            # Color según uso de CPU
            if cpu_percent > 80:
                self.cpu_bar.setStyleSheet("QProgressBar::chunk { background-color: #e74c3c; }")
            elif cpu_percent > 50:
                self.cpu_bar.setStyleSheet("QProgressBar::chunk { background-color: #f39c12; }")
            else:
                self.cpu_bar.setStyleSheet("QProgressBar::chunk { background-color: #27ae60; }")
            # Actualizar Memoria
            self.mem_label.setText(f"Memoria: {memory_mb:.1f} MB")

            # Calcular porcentaje de memoria del sistema
            system_memory = psutil.virtual_memory()
            mem_percent = (memory_mb / (system_memory.total / (1024 * 1024))) * 100
            self.mem_bar.setValue(int(min(mem_percent, 100)))

            # Color según uso de memoria
            if mem_percent > 80:
                self.mem_bar.setStyleSheet("QProgressBar::chunk { background-color: #e74c3c; }")
            elif mem_percent > 50:
                self.mem_bar.setStyleSheet("QProgressBar::chunk { background-color: #f39c12; }")
            else:
                self.mem_bar.setStyleSheet("QProgressBar::chunk { background-color: #27ae60; }")
            # Actualizar tabla de pestañas
            self.update_tabs_table()

            # Información adicional
            threads = self.process.num_threads()
            self.info_label.setText(
                f"Hilos: {threads} | "
                f"Memoria total del sistema: {system_memory.percent:.1f}% usada"
            )
        except Exception as e:
            print(f"[PerformanceMonitor] Error updating stats: {e}")
    def update_tabs_table(self):
        """Actualizar tabla de pestañas"""
        if not self.parent or not hasattr(self.parent, 'tab_manager'):
            return
        tab_manager = self.parent.tab_manager
        tabs_widget = tab_manager.tabs

        # Limpiar tabla
        self.tabs_table.setRowCount(0)

        # Agregar cada pestaña
        for i in range(tabs_widget.count()):
            browser = tabs_widget.widget(i)
            if not browser:
                continue
            row = self.tabs_table.rowCount()
            self.tabs_table.insertRow(row)

            # Número de pestaña
            tab_num = QTableWidgetItem(f"#{i + 1}")
            tab_num.setTextAlignment(Qt.AlignCenter)
            self.tabs_table.setItem(row, 0, tab_num)

            # URL
            url = browser.url().toString()
            url_item = QTableWidgetItem(url if url else "about:blank")
            url_item.setToolTip(url)
            self.tabs_table.setItem(row, 1, url_item)

            # Título
            title = tabs_widget.tabText(i)
            # Limpiar marcador de estado
            title = title.replace("● ", "")
            title_item = QTableWidgetItem(title if title else "Sin título")
            title_item.setToolTip(title)
            self.tabs_table.setItem(row, 2, title_item)

            # Estado
            loading = browser.page().isLoading() if hasattr(browser, 'page') else False
            status = "Cargando..." if loading else "Listo"
            status_item = QTableWidgetItem(status)
            status_item.setTextAlignment(Qt.AlignCenter)

            if loading:
                status_item.setForeground(Qt.blue)
            self.tabs_table.setItem(row, 3, status_item)

            # Botón de cerrar
            close_btn = QPushButton("Cerrar")
            close_btn.setMaximumWidth(80)
            close_btn.clicked.connect(lambda checked, idx=i: self.close_tab(idx))
            self.tabs_table.setCellWidget(row, 4, close_btn)
    def close_tab(self, tab_index):
        """Cerrar una pestaña específica"""
        reply = QMessageBox.question(
            self,
            "Cerrar pestaña",
            f"¿Cerrar la pestaña #{tab_index + 1}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            if self.parent and hasattr(self.parent, 'tab_manager'):
                self.parent.tab_manager.close_tab(tab_index)
                self.update_tabs_table()
    def closeEvent(self, event):
        """Detener timer al cerrar"""
        self.update_timer.stop()
        event.accept()


class PerformanceDiagnostic:
    """Diagnóstico de rendimiento del navegador"""

    @staticmethod
    def run_diagnostic(parent=None):
        """Ejecutar diagnóstico completo"""
        from PySide6.QtWidgets import QMessageBox

        try:
            process = psutil.Process(os.getpid())

            # Recopilar información
            cpu_percent = process.cpu_percent(interval=1.0)
            memory_info = process.memory_info()
            memory_mb = memory_info.rss / (1024 * 1024)
            threads = process.num_threads()

            # Información del sistema
            system_memory = psutil.virtual_memory()
            system_cpu = psutil.cpu_percent(interval=1.0)

            # Crear reporte
            report = f"""
DIAGNÓSTICO DE RENDIMIENTO
==========================

NAVEGADOR:
- Uso de CPU: {cpu_percent:.1f}%
- Memoria RAM: {memory_mb:.1f} MB
- Hilos activos: {threads}

SISTEMA:
- CPU total: {system_cpu:.1f}%
- Memoria total: {system_memory.percent:.1f}% ({system_memory.used / (1024**3):.1f} GB / {system_memory.total / (1024**3):.1f} GB)
- Memoria disponible: {system_memory.available / (1024**3):.1f} GB

RECOMENDACIONES:
"""

            # Recomendaciones basadas en métricas
            recommendations = []

            if cpu_percent > 80:
                recommendations.append("- Alto uso de CPU. Considera cerrar pestañas innecesarias.")
            if memory_mb > 1000:
                recommendations.append("- Alto uso de memoria (>1GB). Considera cerrar pestañas.")
            if threads > 50:
                recommendations.append("- Muchos hilos activos. Revisa extensiones/plugins.")
            if system_memory.percent > 90:
                recommendations.append("- Memoria del sistema casi llena. Cierra otras aplicaciones.")
            if not recommendations:
                recommendations.append("- El navegador funciona correctamente.")
            report += "\n".join(recommendations)

            # Mostrar reporte
            msg = QMessageBox(parent)
            msg.setWindowTitle("Diagnóstico de rendimiento")
            msg.setText("Diagnóstico completado")
            msg.setDetailedText(report)
            msg.setIcon(QMessageBox.Information)
            msg.exec()

            return report
        except Exception as e:
            QMessageBox.warning(
                parent,
                "Error",
                f"Error al ejecutar diagnóstico: {e}"
            )
            return None
