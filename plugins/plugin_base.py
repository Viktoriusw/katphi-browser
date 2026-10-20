#!/usr/bin/env python3


"""


Base Plugin Class - Foundation for all Katphi plugins


"""


from abc import ABC, abstractmethod


from typing import Dict, Any, Optional


from dataclasses import dataclass, field


from datetime import datetime


import json


@dataclass


class PluginMetadata:
    """Plugin metadata information"""

    id: str

    name: str

    version: str

    author: str

    description: str

    min_browser_version: str = "1.0.0"

    max_browser_version: str = "999.0.0"

    dependencies: list = field(default_factory=list)

    permissions: list = field(default_factory=list)

    icon: Optional[str] = None

    homepage: Optional[str] = None

    repository: Optional[str] = None

    tags: list = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary"""

        return {

            'id': self.id,

            'name': self.name,

            'version': self.version,

            'author': self.author,

            'description': self.description,

            'min_browser_version': self.min_browser_version,

            'max_browser_version': self.max_browser_version,

            'dependencies': self.dependencies,

            'permissions': self.permissions,

            'icon': self.icon,

            'homepage': self.homepage,

            'repository': self.repository,

            'tags': self.tags
        }
    @classmethod

    def from_dict(cls, data: Dict[str, Any]) -> 'PluginMetadata':
        """Create metadata from dictionary"""

        return cls(

            id=data.get('id', ''),

            name=data.get('name', 'Unknown Plugin'),

            version=data.get('version', '0.0.0'),

            author=data.get('author', 'Unknown'),

            description=data.get('description', ''),

            min_browser_version=data.get('min_browser_version', '1.0.0'),

            max_browser_version=data.get('max_browser_version', '999.0.0'),

            dependencies=data.get('dependencies', []),

            permissions=data.get('permissions', []),

            icon=data.get('icon'),

            homepage=data.get('homepage'),

            repository=data.get('repository'),

            tags=data.get('tags', [])
        )


class PluginBase(ABC):
    """

    Base class for all Katphi plugins.

    All plugins must inherit from this class and implement the required methods.

    """

    def __init__(self):
        self._enabled = False

        self._installed_at = None

        self._config = {}
    @abstractmethod

    def get_metadata(self) -> PluginMetadata:
        """

        Return plugin metadata.

        This method must be implemented by all plugins.

        """

        pass
    @abstractmethod

    def initialize(self, browser_instance) -> bool:
        """

        Initialize the plugin.

        Called when the plugin is first loaded or enabled.

        Args:
            browser_instance: Reference to the main browser window
        Returns:
            bool: True if initialization was successful, False otherwise
        """

        pass
    @abstractmethod

    def shutdown(self) -> bool:
        """

        Shutdown the plugin.

        Called when the plugin is disabled or the browser is closing.

        Returns:
            bool: True if shutdown was successful, False otherwise
        """

        pass
    def get_settings_widget(self):
        """

        Return a QWidget for plugin settings/configuration.

        Override this method if your plugin has configurable settings.

        Returns:
            QWidget or None: Settings widget or None if no settings
        """

        return None
    def on_page_loaded(self, url: str, page):
        """

        Called when a page is loaded.

        Override this to react to page load events.

        Args:
            url: The URL that was loaded

            page: The QWebEnginePage instance
        """

        pass
    def on_tab_changed(self, tab_index: int):
        """

        Called when the active tab changes.

        Override this to react to tab changes.

        Args:
            tab_index: Index of the new active tab
        """

        pass
    def on_browser_startup(self):
        """

        Called when the browser starts up.

        Override this for startup actions.

        """

        pass
    def on_browser_shutdown(self):
        """

        Called when the browser is shutting down.

        Override this for cleanup actions.

        """

        pass
    def get_menu_items(self) -> list:
        """

        Return menu items to add to browser menus.

        Override this to add custom menu items.

        Returns:
            list: List of tuples (menu_name, action_name, callback)
        """

        return []
    def get_toolbar_actions(self) -> list:
        """

        Return toolbar actions to add to the browser.

        Override this to add custom toolbar buttons.

        Returns:
            list: List of QAction objects
        """

        return []
    def save_config(self, config: Dict[str, Any]):
        """Save plugin configuration"""

        self._config = config
    def load_config(self) -> Dict[str, Any]:
        """Load plugin configuration"""

        return self._config
    def set_enabled(self, enabled: bool):
        """Set plugin enabled state"""

        self._enabled = enabled
    def is_enabled(self) -> bool:
        """Check if plugin is enabled"""

        return self._enabled
    def get_version(self) -> str:
        """Get plugin version"""

        return self.get_metadata().version
    def check_compatibility(self, browser_version: str) -> bool:
        """

        Check if plugin is compatible with browser version.

        Args:
            browser_version: Browser version string
        Returns:
            bool: True if compatible, False otherwise
        """

        metadata = self.get_metadata()

        # Simple version check - you can make this more sophisticated

        try:
            from packaging import version

            return (version.parse(browser_version) >= version.parse(metadata.min_browser_version) and

                    version.parse(browser_version) <= version.parse(metadata.max_browser_version))
        except:
            # Fallback to simple string comparison

            return True
