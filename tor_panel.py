#!/usr/bin/env python3
"""
Panel de control Tor para Katphi Browser.

Estados: DESCONECTADO, CONECTANDO (con progreso), CONECTADO, NO DISPONIBLE.
Sigue el flujo de Tor Browser: usuario activa → bootstrap → reinicio automático.
"""

from typing import Optional

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QProgressBar,
    QGroupBox,
    QMessageBox,
    QFrame,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QIcon

from tor_manager import TorManager, TorStatus, TOR_AVAILABLE

try:
    from config_manager import config
except ImportError:
    config = None


class TorBootstrapWorker(QThread):
    """Worker que arranca Tor en background y emite progreso."""

    progress = Signal(int)
    finished_success = Signal()
    finished_error = Signal(str)

    def __init__(self, tor_manager: TorManager):
        super().__init__()
        self.tor_manager = tor_manager
        self._cancelled = False
    def cancel(self) -> None:
        self._cancelled = True
    def run(self) -> None:
        def on_progress(pct: int) -> None:
            if not self._cancelled:
                self.progress.emit(pct)
        success = self.tor_manager.start(progress_callback=on_progress)
        if self._cancelled:
            self.tor_manager.stop()
            return
        if success:
            self.finished_success.emit()
        else:
            msg = self.tor_manager.error_message or "Error desconocido"
            self.finished_error.emit(msg)


class TorPanel(QWidget):
    """
    Panel de control Tor integrado en la barra lateral.

    Muestra estado, progreso de bootstrap y botones Conectar/Desconectar/Nueva identidad.
    """

    def __init__(self, tor_manager: Optional[TorManager] = None, parent=None):
        super().__init__(parent)
        self.tor_manager = tor_manager or TorManager()
        self._bootstrap_worker: Optional[TorBootstrapWorker] = None
        self._restart_callback = None
        self.setup_ui()
        self._update_ui_state()
    def set_restart_callback(self, callback) -> None:
        """Callback para reiniciar el navegador (enabled: bool) -> None."""
        self._restart_callback = callback
    def setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Título
        title = QLabel("Red Tor")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        # Contenedor de estado
        self.state_frame = QFrame()
        self.state_frame.setFrameStyle(QFrame.StyledPanel)
        state_layout = QVBoxLayout(self.state_frame)

        self.status_label = QLabel("Estado: Desconectado")
        self.status_label.setWordWrap(True)
        state_layout.addWidget(self.status_label)

        self.detail_label = QLabel("")
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet("color: #666; font-size: 11px;")
        state_layout.addWidget(self.detail_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        state_layout.addWidget(self.progress_bar)

        layout.addWidget(self.state_frame)

        # Botones
        btn_layout = QVBoxLayout()

        self.connect_btn = QPushButton("Conectar a Tor")
        self.connect_btn.clicked.connect(self._on_connect_clicked)
        btn_layout.addWidget(self.connect_btn)

        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        self.cancel_btn.setVisible(False)
        btn_layout.addWidget(self.cancel_btn)

        self.disconnect_btn = QPushButton("Desconectar")
        self.disconnect_btn.clicked.connect(self._on_disconnect_clicked)
        self.disconnect_btn.setVisible(False)
        btn_layout.addWidget(self.disconnect_btn)

        self.new_identity_btn = QPushButton("Nueva identidad")
        self.new_identity_btn.clicked.connect(self._on_new_identity_clicked)
        self.new_identity_btn.setVisible(False)
        btn_layout.addWidget(self.new_identity_btn)

        layout.addLayout(btn_layout)
        layout.addStretch()
    def _update_ui_state(self) -> None:
        """Actualiza la UI según el estado actual."""
        err = self.tor_manager.get_availability_error() if TOR_AVAILABLE else "stem no instalado"

        if err:
            self._show_unavailable(err)
            return
        # Tor ya activo (p. ej. tras reinicio): SOCKS5 listo y config habilitada
        if (
            config
            and config.is_tor_enabled()
            and self.tor_manager.is_socks5_ready()
        ):
            self.tor_manager._status = TorStatus.CONNECTED
            self._show_connected()
            return
        status = self.tor_manager.status

        if status == TorStatus.STOPPED:
            self._show_disconnected()
        elif status in (TorStatus.STARTING, TorStatus.BOOTSTRAPPING):
            self._show_connecting()
        elif status == TorStatus.CONNECTED:
            self._show_connected()
        else:
            self._show_error(self.tor_manager.error_message or "Error")
    def _show_unavailable(self, message: str) -> None:
        """Estado: Tor no disponible (falta stem o binario)."""
        self.status_label.setText("Tor no disponible")
        self.detail_label.setText(message)
        self.progress_bar.setVisible(False)
        self.connect_btn.setEnabled(False)
        self.connect_btn.setToolTip(message)
        self.cancel_btn.setVisible(False)
        self.disconnect_btn.setVisible(False)
        self.new_identity_btn.setVisible(False)
    def _show_disconnected(self) -> None:
        """Estado: Desconectado, listo para conectar."""
        self.status_label.setText("Tor desconectado")
        self.detail_label.setText(
            "Conecta a la red Tor para navegar de forma anónima. "
            "El navegador se reiniciará automáticamente al conectar."
        )
        self.progress_bar.setVisible(False)
        self.connect_btn.setEnabled(True)
        self.connect_btn.setVisible(True)
        self.cancel_btn.setVisible(False)
        self.disconnect_btn.setVisible(False)
        self.new_identity_btn.setVisible(False)
    def _show_connecting(self) -> None:
        """Estado: Bootstrap en progreso."""
        pct = self.tor_manager.bootstrap_percent
        self.status_label.setText(f"Conectando... Bootstrap: {pct}%")
        self.detail_label.setText("Espere mientras Tor establece el circuito...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(pct)
        self.connect_btn.setVisible(False)
        self.cancel_btn.setVisible(True)
        self.disconnect_btn.setVisible(False)
        self.new_identity_btn.setVisible(False)
    def _show_connected(self) -> None:
        """Estado: Conectado."""
        self.status_label.setText("Tor activo")
        self.status_label.setStyleSheet("color: #2e7d32; font-weight: bold;")
        self.detail_label.setText("Tu tráfico está enrutado por la red Tor.")
        self.detail_label.setStyleSheet("color: #666; font-size: 11px;")
        self.progress_bar.setVisible(False)
        self.connect_btn.setVisible(False)
        self.cancel_btn.setVisible(False)
        self.disconnect_btn.setVisible(True)
        self.new_identity_btn.setVisible(True)
    def _show_error(self, message: str) -> None:
        """Estado: Error."""
        self.status_label.setText("Error")
        self.status_label.setStyleSheet("color: #c62828;")
        self.detail_label.setText(message)
        self.progress_bar.setVisible(False)
        self.connect_btn.setEnabled(True)
        self.connect_btn.setVisible(True)
        self.cancel_btn.setVisible(False)
        self.disconnect_btn.setVisible(False)
        self.new_identity_btn.setVisible(False)
    def _on_connect_clicked(self) -> None:
        """Usuario pulsa Conectar a Tor."""
        if self._bootstrap_worker and self._bootstrap_worker.isRunning():
            return
        self._bootstrap_worker = TorBootstrapWorker(self.tor_manager)
        self._bootstrap_worker.progress.connect(self._on_bootstrap_progress)
        self._bootstrap_worker.finished_success.connect(self._on_bootstrap_success)
        self._bootstrap_worker.finished_error.connect(self._on_bootstrap_error)
        self._bootstrap_worker.start()

        self._update_ui_state()
    def _on_bootstrap_progress(self, pct: int) -> None:
        self.tor_manager._bootstrap_percent = pct
        self.progress_bar.setValue(pct)
        self.status_label.setText(f"Conectando... Bootstrap: {pct}%")
    def _on_bootstrap_success(self) -> None:
        self._bootstrap_worker = None
        # Si Tor ya estaba corriendo (SOCKS5 activo, _process=None), no pedir reinicio
        if self.tor_manager._process is None and self.tor_manager.is_socks5_ready():
            self._show_connected()
            self._update_ui_state()
            return
        if not self._restart_callback:
            self._show_error("No hay callback de reinicio configurado")
            return
        reply = QMessageBox.question(
            self,
            "Reiniciar navegador",
            "Tor está listo. El navegador se reiniciará para activar la conexión Tor.\n\n"
            "¿Continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply == QMessageBox.Yes:
            self._restart_callback(True)
    def _on_bootstrap_error(self, message: str) -> None:
        self._bootstrap_worker = None
        self._show_error(message)
    def _on_cancel_clicked(self) -> None:
        """Usuario cancela el bootstrap."""
        if self._bootstrap_worker and self._bootstrap_worker.isRunning():
            self._bootstrap_worker.cancel()
            self._bootstrap_worker.wait(3000)
        self.tor_manager.stop()
        self._bootstrap_worker = None
        self._update_ui_state()
    def _on_disconnect_clicked(self) -> None:
        """Usuario pulsa Desconectar."""
        reply = QMessageBox.question(
            self,
            "Desconectar Tor",
            "El navegador se reiniciará para desactivar Tor.\n\n¿Continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.tor_manager.stop()
            if self._restart_callback:
                self._restart_callback(False)
    def _on_new_identity_clicked(self) -> None:
        """Usuario solicita nueva identidad (nuevo circuito)."""
        if self.tor_manager.request_new_identity():
            self.detail_label.setText("Nueva identidad solicitada. El próximo circuito usará otra IP.")
        else:
            self.detail_label.setText("Error al solicitar nueva identidad.")
