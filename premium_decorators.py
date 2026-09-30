#!/usr/bin/env python3


"""


Premium Decorators - Decorators and utilities for premium plugin features


"""


from functools import wraps


from typing import Callable, Any, Optional, List


import logging


from PySide6.QtWidgets import QWidget, QMessageBox, QVBoxLayout


from PySide6.QtCore import QObject, Signal


# PluginAccessLevel se define en unified_plugin_manager.py — importado aquí para
# evitar dos clases Enum independientes que nunca eran iguales entre sí (bug histórico).


from unified_plugin_manager import PluginAccessLevel
from plugin_policy import dev_mode_allowed


logger = logging.getLogger(__name__)

# Validador por defecto (el UnifiedPluginManager del navegador se registra al crearse).
# Se usa cuando el widget decorado no tiene su propio plugin_validator.
_default_validator = None


def set_default_validator(validator) -> None:
    global _default_validator
    _default_validator = validator


def _no_validator_allows(plugin_id: str) -> bool:
    """Sin validador no hay forma de comprobar la licencia: se deniega el acceso
    (solo se permite en modo desarrollo desde el código fuente)."""
    if dev_mode_allowed():
        logger.debug("Sin plugin_validator para %s — permitido en modo desarrollo", plugin_id)
        return True
    logger.warning("Sin plugin_validator para %s — acceso premium denegado", plugin_id)
    return False


def requires_premium(plugin_id: str, feature: str = None, show_dialog: bool = True):
    """

    Decorator to require premium access for a function or method

    Args:
        plugin_id: ID of the plugin

        feature: Specific feature name (optional)

        show_dialog: Whether to show upgrade dialog if access denied
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)

        def wrapper(*args, **kwargs):
            # Try to get plugin validator from the instance

            validator = None

            parent_widget = None

            # Look for validator in the instance (self)

            if args and hasattr(args[0], 'plugin_validator'):
                validator = args[0].plugin_validator

                parent_widget = args[0] if isinstance(args[0], QWidget) else None
            elif args and hasattr(args[0], 'parent') and hasattr(args[0].parent(), 'plugin_validator'):
                validator = args[0].parent().plugin_validator

                parent_widget = args[0].parent()
            validator = validator or _default_validator
            if not validator:
                return func(*args, **kwargs) if _no_validator_allows(plugin_id) else None
            # Check access

            if feature:
                has_access = validator.can_access_feature(plugin_id, feature)

                if not has_access:
                    if show_dialog:
                        validator.request_feature_access(plugin_id, feature, parent_widget)
                    return None
            else:
                # Check general plugin access

                access_info = validator.get_plugin_access(plugin_id)

                if access_info.access_level not in (
                    PluginAccessLevel.PREMIUM,
                    PluginAccessLevel.TRIAL,
                ):
                    if show_dialog:
                        validator._show_upgrade_dialog(plugin_id, "premium_access", parent_widget)
                    return None
            return func(*args, **kwargs)
        return wrapper
    return decorator


def premium_feature(plugin_id: str, feature: str, fallback_func: Callable = None):
    """

    Decorator for premium features with fallback

    Args:
        plugin_id: ID of the plugin

        feature: Feature name

        fallback_func: Function to call if premium access is not available
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)

        def wrapper(*args, **kwargs):
            # Try to get plugin validator

            validator = None

            parent_widget = None

            if args and hasattr(args[0], 'plugin_validator'):
                validator = args[0].plugin_validator

                parent_widget = args[0] if isinstance(args[0], QWidget) else None
            elif args and hasattr(args[0], 'parent') and hasattr(args[0].parent(), 'plugin_validator'):
                validator = args[0].parent().plugin_validator

                parent_widget = args[0].parent()
            validator = validator or _default_validator
            if not validator:
                if _no_validator_allows(plugin_id):
                    return func(*args, **kwargs)
                if fallback_func:
                    return fallback_func(*args, **kwargs)
                return None
            # Check feature access

            if validator.can_access_feature(plugin_id, feature):
                return func(*args, **kwargs)
            else:
                # Show upgrade dialog

                validator.request_feature_access(plugin_id, feature, parent_widget)

                # Call fallback if available

                if fallback_func:
                    return fallback_func(*args, **kwargs)
                return None
        return wrapper
    return decorator


def trial_feature(plugin_id: str, feature: str, max_uses: int = 10):
    """

    Decorator for trial features with usage limits

    Args:
        plugin_id: ID of the plugin

        feature: Feature name

        max_uses: Maximum number of uses in trial
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)

        def wrapper(*args, **kwargs):
            # Try to get plugin validator

            validator = None

            parent_widget = None

            if args and hasattr(args[0], 'plugin_validator'):
                validator = args[0].plugin_validator

                parent_widget = args[0] if isinstance(args[0], QWidget) else None
            elif args and hasattr(args[0], 'parent') and hasattr(args[0].parent(), 'plugin_validator'):
                validator = args[0].parent().plugin_validator

                parent_widget = args[0].parent()
            validator = validator or _default_validator
            if not validator:
                return func(*args, **kwargs) if _no_validator_allows(plugin_id) else None
            # Check if user has premium access

            access_info = validator.get_plugin_access(plugin_id)

            if access_info.access_level == PluginAccessLevel.PREMIUM:
                return func(*args, **kwargs)
            # Check trial access

            if access_info.access_level == PluginAccessLevel.TRIAL:
                # Check usage limits (this would need to be implemented in validator)

                # For now, just allow trial access

                return func(*args, **kwargs)
            # No access - show upgrade dialog

            validator.request_feature_access(plugin_id, feature, parent_widget)

            return None
        return wrapper
    return decorator


class PremiumMixin:
    """Mixin class to add premium functionality to widgets"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.plugin_validator = None

        self._premium_features = {}
    def set_plugin_validator(self, validator):
        """Set the plugin validator"""

        self.plugin_validator = validator
    def check_premium_access(self, plugin_id: str, feature: str = None) -> bool:
        """Check if user has premium access"""

        if not self.plugin_validator:
            return False
        if feature:
            return self.plugin_validator.can_access_feature(plugin_id, feature)
        else:
            access_info = self.plugin_validator.get_plugin_access(plugin_id)

            return access_info.access_level in [PluginAccessLevel.PREMIUM, PluginAccessLevel.TRIAL]
    def request_premium_access(self, plugin_id: str, feature: str) -> bool:
        """Request premium access for a feature"""

        if not self.plugin_validator:
            return False
        return self.plugin_validator.request_feature_access(plugin_id, feature, self)
    def show_premium_required_dialog(self, plugin_id: str, feature: str):
        """Show dialog for premium feature requirement"""

        if not self.plugin_validator:
            return
        self.plugin_validator._show_upgrade_dialog(plugin_id, feature, self)
    def get_available_features(self, plugin_id: str) -> List[str]:
        """Get available features for a plugin"""

        if not self.plugin_validator:
            return []
        return self.plugin_validator.get_available_features(plugin_id)
    def update_premium_ui(self, plugin_id: str):
        """Update UI based on premium access"""

        if not self.plugin_validator:
            return
        access_info = self.plugin_validator.get_plugin_access(plugin_id)

        # Update UI elements based on access level

        for widget_name, widget in self._premium_features.items():
            if hasattr(self, widget_name):
                widget_obj = getattr(self, widget_name)

                has_access = access_info.access_level in (
                    PluginAccessLevel.PREMIUM,
                    PluginAccessLevel.TRIAL,
                )
                if hasattr(widget_obj, 'setEnabled'):
                    widget_obj.setEnabled(has_access)
                # Update tooltips

                if hasattr(widget_obj, 'setToolTip'):
                    if not has_access:
                        widget_obj.setToolTip("Función premium - Requiere suscripción")
                    elif access_info.access_level == PluginAccessLevel.TRIAL:
                        widget_obj.setToolTip(f"Prueba gratuita - {access_info.trial_remaining} días restantes")
                    else:
                        widget_obj.setToolTip("Función premium activa")


class PremiumButton(QWidget):
    """Premium button that shows upgrade dialog when clicked without access"""

    clicked = Signal()

    def __init__(self, plugin_id: str, feature: str, text: str = "Premium Feature", parent=None):
        super().__init__(parent)

        self.plugin_id = plugin_id

        self.feature = feature

        self.text = text

        from PySide6.QtWidgets import QPushButton

        self.button = QPushButton(text)

        self.button.clicked.connect(self._on_clicked)

        layout = QVBoxLayout(self)

        layout.addWidget(self.button)

        layout.setContentsMargins(0, 0, 0, 0)

        self.plugin_validator = None
    def set_plugin_validator(self, validator):
        """Set the plugin validator"""

        self.plugin_validator = validator

        self._update_button_state()
    def _update_button_state(self):
        """Update button state based on access"""

        if not self.plugin_validator:
            return
        access_info = self.plugin_validator.get_plugin_access(self.plugin_id)

        if access_info.access_level == PluginAccessLevel.PREMIUM:
            self.button.setText(self.text)

            self.button.setStyleSheet("")
        elif access_info.access_level == PluginAccessLevel.TRIAL:
            self.button.setText(f"{self.text} (Prueba: {access_info.trial_remaining}d)")

            self.button.setStyleSheet("background-color: #f39c12; color: white;")
        else:
            self.button.setText(f"{self.text} (Premium)")

            self.button.setStyleSheet("background-color: #e74c3c; color: white;")
    def _on_clicked(self):
        """Handle button click"""

        if not self.plugin_validator:
            return
        if self.plugin_validator.can_access_feature(self.plugin_id, self.feature):
            self.clicked.emit()
        else:
            self.plugin_validator.request_feature_access(self.plugin_id, self.feature, self)


def create_premium_widget(plugin_id: str, feature: str, widget_class, *args, **kwargs):
    """

    Create a premium widget that automatically handles access validation

    Args:
        plugin_id: Plugin ID

        feature: Feature name

        widget_class: Widget class to create

        *args, **kwargs: Arguments for widget creation
    """

    class PremiumWidget(widget_class, PremiumMixin):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

            self.plugin_id = plugin_id

            self.feature = feature
        def showEvent(self, event):
            super().showEvent(event)

            self.update_premium_ui(self.plugin_id)
    return PremiumWidget(*args, **kwargs)
