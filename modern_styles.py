"""
modern_styles.py - Estilos modernos y visuales para Katphi Browser

Este módulo proporciona estilos CSS modernos tipo Chrome/Edge con:
- Botones circulares en navbar
- URL bar expandible
- Pestañas trapezoidales
- Sidebar retráctil
- Temas con gradientes y sombras
- Animaciones suaves

Autor: Katphi Team
Fecha: 2025-12-31
"""

from PySide6.QtWidgets import (QWidget, QPushButton, QLineEdit, QTabBar,
                                QHBoxLayout, QVBoxLayout, QToolButton,
                                QFrame, QSizePolicy, QLabel, QGraphicsOpacityEffect)
from PySide6.QtCore import (Qt, QPropertyAnimation, QEasingCurve, QRect,
                            QSize, Property, QParallelAnimationGroup, Signal,
                            QPoint, QTimer)
from PySide6.QtGui import QPainter, QPainterPath, QColor, QLinearGradient, QPen, QIcon


# ============================================================================
# ESTILOS CSS GLOBALES
# ============================================================================

class ModernTheme:
    """Temas modernos con colores, gradientes y sombras"""

    # Tema Light (predeterminado)
    LIGHT = {
        'bg_primary': '#FFFFFF',
        'bg_secondary': '#F5F5F5',
        'bg_hover': '#E8E8E8',
        'bg_active': '#D0D0D0',
        'text_primary': '#202124',
        'text_secondary': '#5F6368',
        'accent': '#1A73E8',
        'accent_hover': '#1557B0',
        'border': '#DADCE0',
        'shadow': 'rgba(0, 0, 0, 0.1)',
        'tab_bg': '#F1F3F4',
        'tab_active': '#FFFFFF',
        'urlbar_bg': '#FFFFFF',
        'urlbar_border': '#E0E0E0',
    }

    # Tema Dark
    DARK = {
        'bg_primary': '#202124',
        'bg_secondary': '#292A2D',
        'bg_hover': '#35363A',
        'bg_active': '#3C4043',
        'text_primary': '#E8EAED',
        'text_secondary': '#9AA0A6',
        'accent': '#8AB4F8',
        'accent_hover': '#AECBFA',
        'border': '#3C4043',
        'shadow': 'rgba(0, 0, 0, 0.3)',
        'tab_bg': '#292A2D',
        'tab_active': '#35363A',
        'urlbar_bg': '#292A2D',
        'urlbar_border': '#3C4043',
    }

    # Tema Blue (Azul moderno)
    BLUE = {
        'bg_primary': '#F0F4FF',
        'bg_secondary': '#E3EDFF',
        'bg_hover': '#D6E4FF',
        'bg_active': '#B8D4FF',
        'text_primary': '#1E3A5F',
        'text_secondary': '#4A5F7F',
        'accent': '#0066CC',
        'accent_hover': '#0052A3',
        'border': '#B8D4FF',
        'shadow': 'rgba(0, 102, 204, 0.15)',
        'tab_bg': '#E3EDFF',
        'tab_active': '#FFFFFF',
        'urlbar_bg': '#FFFFFF',
        'urlbar_border': '#B8D4FF',
    }

    @staticmethod
    def get_theme(name='light'):
        """Obtener tema por nombre"""
        themes = {
            'light': ModernTheme.LIGHT,
            'dark': ModernTheme.DARK,
            'blue': ModernTheme.BLUE,
        }
        return themes.get(name.lower(), ModernTheme.LIGHT)


def get_circular_button_style(theme_colors):
    """Estilo para botones circulares tipo Chrome"""
    return f"""
        QPushButton {{
            background-color: transparent;
            border: none;
            border-radius: 18px;
            width: 36px;
            height: 36px;
            padding: 6px;
            color: {theme_colors['text_primary']};
        }}
        QPushButton:hover {{
            background-color: {theme_colors['bg_hover']};
        }}
        QPushButton:pressed {{
            background-color: {theme_colors['bg_active']};
        }}
        QPushButton:disabled {{
            opacity: 0.4;
        }}
    """


def get_modern_urlbar_style(theme_colors):
    """Estilo para barra de URL expandible tipo Chrome"""
    return f"""
        QLineEdit {{
            background-color: {theme_colors['urlbar_bg']};
            border: 1px solid {theme_colors['urlbar_border']};
            border-radius: 20px;
            padding: 8px 40px 8px 40px;
            font-size: 14px;
            color: {theme_colors['text_primary']};
            selection-background-color: {theme_colors['accent']};
        }}
        QLineEdit:focus {{
            border: 2px solid {theme_colors['accent']};
            padding: 7px 39px 7px 39px;
            box-shadow: 0 2px 8px {theme_colors['shadow']};
        }}
        QLineEdit:hover {{
            border: 1px solid {theme_colors['border']};
            box-shadow: 0 1px 4px {theme_colors['shadow']};
        }}
    """


def get_trapezoidal_tab_style(theme_colors):
    """Estilo para pestañas trapezoidales tipo Chrome"""
    return f"""
        QTabBar::tab {{
            background-color: {theme_colors['tab_bg']};
            color: {theme_colors['text_secondary']};
            border: none;
            padding: 8px 20px;
            margin-right: 2px;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            min-width: 120px;
            max-width: 240px;
        }}
        QTabBar::tab:selected {{
            background-color: {theme_colors['tab_active']};
            color: {theme_colors['text_primary']};
            font-weight: bold;
            box-shadow: 0 -2px 8px {theme_colors['shadow']};
        }}
        QTabBar::tab:hover {{
            background-color: {theme_colors['bg_hover']};
        }}
        QTabBar::tab:!selected {{
            margin-top: 3px;
        }}
        QTabBar::close-button {{
            image: url(icons/close.png);
            subcontrol-position: right;
            margin: 4px;
        }}
        QTabBar::close-button:hover {{
            background-color: {theme_colors['bg_active']};
            border-radius: 8px;
        }}
    """


def get_modern_navbar_style(theme_colors):
    """Estilo para barra de navegación moderna"""
    return f"""
        QWidget#navbar {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {theme_colors['bg_primary']},
                stop:1 {theme_colors['bg_secondary']});
            border-bottom: 1px solid {theme_colors['border']};
            padding: 4px;
        }}
    """


def get_sidebar_style(theme_colors):
    """Estilo para sidebar retráctil"""
    return f"""
        QFrame#sidebar {{
            background-color: {theme_colors['bg_secondary']};
            border-right: 1px solid {theme_colors['border']};
        }}
        QLabel#sidebar_title {{
            font-size: 16px;
            font-weight: bold;
            color: {theme_colors['text_primary']};
            padding: 12px;
        }}
    """


# ============================================================================
# WIDGETS MODERNOS PERSONALIZADOS
# ============================================================================

class CircularButton(QPushButton):
    """Botón circular estilo Chrome con animaciones"""

    def __init__(self, icon_path=None, parent=None):
        super().__init__(parent)
        self.setFixedSize(36, 36)
        self.setCursor(Qt.PointingHandCursor)

        if icon_path:
            self.setIcon(QIcon(icon_path))
            self.setIconSize(QSize(20, 20))

        # Efecto de opacidad para animaciones
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(1.0)

    def animate_click(self):
        """Animación al hacer click"""
        self.animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.animation.setDuration(150)
        self.animation.setStartValue(1.0)
        self.animation.setKeyValueAt(0.5, 0.7)
        self.animation.setEndValue(1.0)
        self.animation.start()


class ExpandableUrlBar(QLineEdit):
    """Barra de URL expandible tipo Chrome"""

    focused = Signal()
    unfocused = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.default_width = 600
        self.expanded_width = 800
        self.is_expanded = False

        # Placeholder moderno
        self.setPlaceholderText("Buscar en Google o escribir URL")

        # Animación de expansión
        self.width_animation = QPropertyAnimation(self, b"minimumWidth")
        self.width_animation.setDuration(200)
        self.width_animation.setEasingCurve(QEasingCurve.OutCubic)

        self.setMinimumWidth(self.default_width)

    def focusInEvent(self, event):
        """Expandir al recibir foco"""
        super().focusInEvent(event)
        self.expand()
        self.focused.emit()

    def focusOutEvent(self, event):
        """Contraer al perder foco"""
        super().focusOutEvent(event)
        self.contract()
        self.unfocused.emit()

    def expand(self):
        """Expandir la barra de URL"""
        if not self.is_expanded:
            self.width_animation.setStartValue(self.minimumWidth())
            self.width_animation.setEndValue(self.expanded_width)
            self.width_animation.start()
            self.is_expanded = True

    def contract(self):
        """Contraer la barra de URL"""
        if self.is_expanded and not self.hasFocus():
            self.width_animation.setStartValue(self.minimumWidth())
            self.width_animation.setEndValue(self.default_width)
            self.width_animation.start()
            self.is_expanded = False


class TrapezoidalTabBar(QTabBar):
    """Barra de pestañas trapezoidales tipo Chrome"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDrawBase(False)
        self.setExpanding(False)
        self.setMovable(True)
        self.setTabsClosable(True)
        self.setElideMode(Qt.ElideRight)

    def paintEvent(self, event):
        """Pintar pestañas con forma trapezoidal"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        for index in range(self.count()):
            rect = self.tabRect(index)
            is_selected = (index == self.currentIndex())

            # Colores según estado
            if is_selected:
                bg_color = QColor("#FFFFFF")
                text_color = QColor("#202124")
            else:
                bg_color = QColor("#F1F3F4")
                text_color = QColor("#5F6368")

            # Crear forma trapezoidal
            path = QPainterPath()

            # Puntos del trapecio (más ancho arriba que abajo)
            top_left = QPoint(rect.left() + 8, rect.top())
            top_right = QPoint(rect.right() - 8, rect.top())
            bottom_right = QPoint(rect.right() - 4, rect.bottom())
            bottom_left = QPoint(rect.left() + 4, rect.bottom())

            path.moveTo(top_left)
            path.lineTo(top_right)
            path.lineTo(bottom_right)
            path.lineTo(bottom_left)
            path.closeSubpath()

            # Dibujar fondo
            painter.fillPath(path, bg_color)

            # Dibujar borde suave si está seleccionada
            if is_selected:
                painter.setPen(QPen(QColor("#E0E0E0"), 1))
                painter.drawPath(path)

            # Dibujar texto
            painter.setPen(text_color)
            text_rect = rect.adjusted(16, 0, -30, 0)  # Espacio para icono y botón cerrar
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter,
                           self.tabText(index))


class RetractableSidebar(QFrame):
    """Sidebar retráctil con animación suave"""

    toggled = Signal(bool)  # True = expandido, False = contraído

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")

        self.expanded_width = 250
        self.collapsed_width = 50
        self.is_expanded = True

        self.setMinimumWidth(self.expanded_width)
        self.setMaximumWidth(self.expanded_width)

        # Layout principal
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # Botón de toggle
        self.toggle_btn = QPushButton(self)
        try:
            from ui.core.strip_icons import build_nav_icon
            self.toggle_btn.setIcon(build_nav_icon("menu", None, QSize(20, 20)))
            self.toggle_btn.setIconSize(QSize(20, 20))
        except Exception:
            pass
        self.toggle_btn.setFixedSize(40, 40)
        self.toggle_btn.clicked.connect(self.toggle)
        self.layout.addWidget(self.toggle_btn, alignment=Qt.AlignRight)

        # Contenedor de contenido
        self.content_widget = QWidget(self)
        self.content_layout = QVBoxLayout(self.content_widget)
        self.layout.addWidget(self.content_widget)

        # Animación de ancho
        self.width_animation = QPropertyAnimation(self, b"minimumWidth")
        self.width_animation.setDuration(250)
        self.width_animation.setEasingCurve(QEasingCurve.InOutCubic)

        self.max_width_animation = QPropertyAnimation(self, b"maximumWidth")
        self.max_width_animation.setDuration(250)
        self.max_width_animation.setEasingCurve(QEasingCurve.InOutCubic)

        # Grupo de animaciones paralelas
        self.animation_group = QParallelAnimationGroup(self)
        self.animation_group.addAnimation(self.width_animation)
        self.animation_group.addAnimation(self.max_width_animation)

    def toggle(self):
        """Alternar entre expandido/contraído"""
        if self.is_expanded:
            self.collapse()
        else:
            self.expand()

    def expand(self):
        """Expandir sidebar"""
        self.width_animation.setStartValue(self.width())
        self.width_animation.setEndValue(self.expanded_width)
        self.max_width_animation.setStartValue(self.maximumWidth())
        self.max_width_animation.setEndValue(self.expanded_width)

        self.animation_group.start()
        self.is_expanded = True
        self.content_widget.show()
        self.toggled.emit(True)

    def collapse(self):
        """Contraer sidebar"""
        self.width_animation.setStartValue(self.width())
        self.width_animation.setEndValue(self.collapsed_width)
        self.max_width_animation.setStartValue(self.maximumWidth())
        self.max_width_animation.setEndValue(self.collapsed_width)

        self.animation_group.start()
        self.is_expanded = False

        # Ocultar contenido después de la animación
        QTimer.singleShot(250, lambda: self.content_widget.hide() if not self.is_expanded else None)
        self.toggled.emit(False)

    def add_item(self, widget):
        """Agregar widget al sidebar"""
        self.content_layout.addWidget(widget)


class ModernMenuButton(QPushButton):
    """Botón de menú moderno con animación"""

    def __init__(self, text="", icon=None, parent=None):
        super().__init__(text, parent)

        if icon:
            self.setIcon(icon)
            self.setIconSize(QSize(20, 20))

        self.setMinimumHeight(40)
        self.setCursor(Qt.PointingHandCursor)

        # Estilo base
        self.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 8px;
                padding: 8px 16px;
                text-align: left;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(0, 0, 0, 0.05);
            }
            QPushButton:pressed {
                background-color: rgba(0, 0, 0, 0.1);
            }
        """)


class FloatingActionButton(QPushButton):
    """Botón de acción flotante (FAB) estilo Material Design"""

    def __init__(self, icon_path=None, parent=None):
        super().__init__(parent)
        self.setFixedSize(56, 56)
        self.setCursor(Qt.PointingHandCursor)

        if icon_path:
            self.setIcon(QIcon(icon_path))
            self.setIconSize(QSize(24, 24))

        # Estilo con sombra
        self.setStyleSheet("""
            QPushButton {
                background-color: #1A73E8;
                border: none;
                border-radius: 28px;
                color: white;
            }
            QPushButton:hover {
                background-color: #1557B0;
            }
            QPushButton:pressed {
                background-color: #0D47A1;
            }
        """)

        # Efecto de elevación (sombra)
        self.setGraphicsEffect(self._create_shadow_effect())

    def _create_shadow_effect(self):
        """Crear efecto de sombra para el botón"""
        from PySide6.QtWidgets import QGraphicsDropShadowEffect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(12)
        shadow.setXOffset(0)
        shadow.setYOffset(4)
        shadow.setColor(QColor(0, 0, 0, 60))
        return shadow


# ============================================================================
# GESTOR DE TEMAS
# ============================================================================

class ThemeManager:
    """Gestor de temas para toda la aplicación"""

    def __init__(self, initial_theme='light'):
        self.current_theme_name = initial_theme
        self.current_theme = ModernTheme.get_theme(initial_theme)
        self.widgets = []  # Widgets que usan el tema

    def register_widget(self, widget):
        """Registrar widget para actualizar cuando cambie el tema"""
        if widget not in self.widgets:
            self.widgets.append(widget)

    def change_theme(self, theme_name):
        """Cambiar tema global"""
        self.current_theme_name = theme_name
        self.current_theme = ModernTheme.get_theme(theme_name)
        self._apply_theme_to_all()

    def _apply_theme_to_all(self):
        """Aplicar tema a todos los widgets registrados"""
        for widget in self.widgets:
            if hasattr(widget, 'apply_theme'):
                widget.apply_theme(self.current_theme)

    def get_current_theme(self):
        """Obtener tema actual"""
        return self.current_theme

    def get_circular_button_style(self):
        """Obtener estilo para botones circulares"""
        return get_circular_button_style(self.current_theme)

    def get_urlbar_style(self):
        """Obtener estilo para URL bar"""
        return get_modern_urlbar_style(self.current_theme)

    def get_tab_style(self):
        """Obtener estilo para pestañas"""
        return get_trapezoidal_tab_style(self.current_theme)

    def get_navbar_style(self):
        """Obtener estilo para navbar"""
        return get_modern_navbar_style(self.current_theme)

    def get_sidebar_style(self):
        """Obtener estilo para sidebar"""
        return get_sidebar_style(self.current_theme)


# ============================================================================
# ANIMACIONES PREDEFINIDAS
# ============================================================================

class AnimationHelper:
    """Helper para crear animaciones comunes"""

    @staticmethod
    def create_fade_in(widget, duration=300):
        """Crear animación de fade in"""
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)

        animation = QPropertyAnimation(effect, b"opacity")
        animation.setDuration(duration)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.InOutCubic)

        return animation

    @staticmethod
    def create_fade_out(widget, duration=300):
        """Crear animación de fade out"""
        effect = widget.graphicsEffect()
        if not effect:
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)

        animation = QPropertyAnimation(effect, b"opacity")
        animation.setDuration(duration)
        animation.setStartValue(1.0)
        animation.setEndValue(0.0)
        animation.setEasingCurve(QEasingCurve.InOutCubic)

        return animation

    @staticmethod
    def create_slide_in(widget, direction='left', duration=300):
        """Crear animación de slide in"""
        start_pos = widget.pos()

        if direction == 'left':
            end_pos = QPoint(start_pos.x() + 200, start_pos.y())
        elif direction == 'right':
            end_pos = QPoint(start_pos.x() - 200, start_pos.y())
        elif direction == 'top':
            end_pos = QPoint(start_pos.x(), start_pos.y() + 200)
        else:  # bottom
            end_pos = QPoint(start_pos.x(), start_pos.y() - 200)

        animation = QPropertyAnimation(widget, b"pos")
        animation.setDuration(duration)
        animation.setStartValue(end_pos)
        animation.setEndValue(start_pos)
        animation.setEasingCurve(QEasingCurve.OutCubic)

        return animation

    @staticmethod
    def create_bounce(widget, duration=500):
        """Crear animación de rebote"""
        animation = QPropertyAnimation(widget, b"geometry")
        animation.setDuration(duration)
        animation.setEasingCurve(QEasingCurve.OutBounce)

        start_rect = widget.geometry()
        animation.setStartValue(start_rect)
        animation.setEndValue(start_rect)

        return animation


# ============================================================================
# UTILIDADES
# ============================================================================

def apply_shadow_effect(widget, blur_radius=10, offset_x=0, offset_y=2, color=QColor(0, 0, 0, 40)):
    """Aplicar efecto de sombra a un widget"""
    from PySide6.QtWidgets import QGraphicsDropShadowEffect

    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur_radius)
    shadow.setXOffset(offset_x)
    shadow.setYOffset(offset_y)
    shadow.setColor(color)
    widget.setGraphicsEffect(shadow)
    return shadow


def create_gradient_background(widget, color1, color2, vertical=True):
    """Crear fondo con gradiente para un widget"""
    if vertical:
        gradient_style = f"""
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {color1}, stop:1 {color2});
        """
    else:
        gradient_style = f"""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {color1}, stop:1 {color2});
        """

    current_style = widget.styleSheet()
    widget.setStyleSheet(current_style + gradient_style)


# ============================================================================
# EJEMPLO DE USO
# ============================================================================

if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)

    # Crear ventana de prueba
    window = QWidget()
    window.setWindowTitle("Modern Styles Demo")
    window.resize(900, 600)

    layout = QVBoxLayout(window)

    # Tema manager
    theme_manager = ThemeManager('light')

    # Botones circulares
    btn_layout = QHBoxLayout()
    back_btn = CircularButton()
    back_btn.setText("←")
    back_btn.setStyleSheet(theme_manager.get_circular_button_style())
    btn_layout.addWidget(back_btn)

    forward_btn = CircularButton()
    forward_btn.setText("→")
    forward_btn.setStyleSheet(theme_manager.get_circular_button_style())
    btn_layout.addWidget(forward_btn)

    reload_btn = CircularButton()
    reload_btn.setIcon(QIcon("icons/refresh.svg"))
    reload_btn.setStyleSheet(theme_manager.get_circular_button_style())
    btn_layout.addWidget(reload_btn)

    layout.addLayout(btn_layout)

    # URL bar expandible
    urlbar = ExpandableUrlBar()
    urlbar.setStyleSheet(theme_manager.get_urlbar_style())
    layout.addWidget(urlbar)

    # Sidebar retráctil
    sidebar = RetractableSidebar()
    sidebar.setStyleSheet(theme_manager.get_sidebar_style())
    sidebar.add_item(QLabel("Item 1"))
    sidebar.add_item(QLabel("Item 2"))
    sidebar.add_item(QLabel("Item 3"))

    main_layout = QHBoxLayout()
    main_layout.addWidget(sidebar)
    main_layout.addWidget(QLabel("Contenido principal"))

    layout.addLayout(main_layout)

    window.show()
    sys.exit(app.exec())
