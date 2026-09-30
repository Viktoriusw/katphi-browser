# Katphi Browser — Plugin Development Guide

**Version:** 1.0 · **Browser version:** ≥ 3.4 · **Runtime:** Python 3.10+ / PySide6

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Quick Start — Minimal Plugin in 5 Minutes](#3-quick-start)
4. [Plugin File Structure](#4-plugin-file-structure)
5. [PluginBase API Reference](#5-pluginbase-api-reference)
6. [PluginMetadata Reference](#6-pluginmetadata-reference)
7. [plugin_info.json Reference](#7-plugin_infojson-reference)
8. [Browser API — What Your Plugin Can Access](#8-browser-api)
9. [UI Integration](#9-ui-integration)
10. [Theme System Integration](#10-theme-system-integration)
11. [Icon System](#11-icon-system)
12. [Events and Hooks](#12-events-and-hooks)
13. [Free vs. Premium Plugins](#13-free-vs-premium-plugins)
14. [Premium Decorators](#14-premium-decorators)
15. [Permissions](#15-permissions)
16. [Settings Persistence](#16-settings-persistence)
17. [Plugin Lifecycle](#17-plugin-lifecycle)
18. [Real-World Examples](#18-real-world-examples)
19. [Packaging and Distribution](#19-packaging-and-distribution)
20. [Testing Your Plugin](#20-testing-your-plugin)
21. [Checklist Before Publishing](#21-checklist-before-publishing)

---

## 1. Overview

Katphi Browser is an open-source, Python-based desktop browser built with **PySide6 + Qt WebEngine**. Its plugin system allows third-party developers to extend the browser with new panels, toolbar actions, sidebar buttons, and page-level behaviors.

### Key Facts

| Property | Value |
|---|---|
| Language | Python 3.10+ |
| UI Framework | PySide6 (PyQt6 compatible) |
| Plugin loader | Dynamic import via `importlib` |
| Distribution | ZIP package or local directory |
| Access model | Free or premium (JWT license) |
| Config format | `plugin_info.json` inside the plugin directory |

---

## 2. Architecture

```
Browser starts
    └─► UnifiedPluginManager.load_all_installed_plugins()
            └─► For each plugins/<plugin_id>/
                    ├─ Reads plugin_info.json  (premium flag, metadata)
                    ├─ Imports plugin.py       (dynamic importlib)
                    ├─ Calls initialize_plugin()
                    └─ Emits plugin_loaded signal → UI hooks execute
```

The plugin manager (`unified_plugin_manager.py`) is the central authority. It:

- Discovers plugins by scanning the `plugins/` directory
- Validates access (free / trial / licensed)
- Dynamically imports `plugin.py` and calls `initialize_plugin()`
- Emits Qt signals so `ui.py` can attach sidebar buttons, dock panels, etc.

---

## 3. Quick Start

### Step 1 — Create the directory

```
plugins/
└── hello_world/
    ├── __init__.py
    ├── plugin.py
    └── plugin_info.json
```

### Step 2 — `__init__.py`

```python
# Leave empty or add package-level imports
```

### Step 3 — `plugin_info.json`

```json
{
  "id": "hello_world",
  "name": "Hello World",
  "version": "1.0.0",
  "author": "Your Name",
  "description": "A minimal example plugin for Katphi Browser.",
  "premium": false,
  "category": "utilities",
  "tags": ["example", "demo"],
  "permissions": [],
  "min_browser_version": "3.0.0"
}
```

### Step 4 — `plugin.py`

```python
#!/usr/bin/env python3
"""Hello World plugin — minimal example."""

from plugins.plugin_base import PluginBase, PluginMetadata

# ─── Plugin class ──────────────────────────────────────────────────────────────

class HelloWorldPlugin(PluginBase):

    def get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            id="hello_world",
            name="Hello World",
            version="1.0.0",
            author="Your Name",
            description="A minimal example plugin.",
            permissions=[],
        )

    def initialize(self, browser_instance) -> bool:
        self.browser = browser_instance
        print("[HelloWorld] Initialized!")
        return True

    def shutdown(self) -> bool:
        print("[HelloWorld] Shutdown.")
        return True


# ─── Module interface (required by UnifiedPluginManager) ───────────────────────

_plugin_instance = None


def initialize_plugin() -> bool:
    """Called by UnifiedPluginManager when loading the plugin."""
    global _plugin_instance
    try:
        _plugin_instance = HelloWorldPlugin()
        return True
    except Exception as e:
        print(f"[HelloWorld] init error: {e}")
        return False


def get_plugin_instance() -> HelloWorldPlugin:
    return _plugin_instance


def get_plugin_info() -> dict:
    return {
        "id": "hello_world",
        "name": "Hello World",
        "version": "1.0.0",
        "premium": False,
        "available": _plugin_instance is not None,
    }
```

### Step 5 — Run the browser

```bash
python3 main.py
```

You will see `[HelloWorld] Initialized!` in the console. The plugin is running.

---

## 4. Plugin File Structure

```
plugins/
└── my_plugin/               ← plugin_id must match directory name
    ├── __init__.py          ← required (can be empty)
    ├── plugin.py            ← required entry point
    ├── plugin_info.json     ← required metadata file
    ├── panel.py             ← optional: sidebar panel widget
    ├── settings_widget.py   ← optional: settings panel
    ├── core/                ← optional: business logic subpackage
    │   ├── __init__.py
    │   └── engine.py
    └── assets/              ← optional: icons, images
        └── icon.svg
```

### Required files

| File | Purpose |
|---|---|
| `__init__.py` | Makes the directory a Python package |
| `plugin.py` | Entry point — must expose `initialize_plugin()` |
| `plugin_info.json` | Metadata read by the plugin manager |

### Required functions in `plugin.py`

| Function | Signature | Description |
|---|---|---|
| `initialize_plugin` | `() -> bool` | Called once when the plugin loads. Return `True` on success. |
| `get_plugin_info` | `() -> dict` | Returns a dictionary with plugin metadata. |
| `get_plugin_instance` | `() -> PluginBase \| None` | Returns the singleton plugin instance. |

---

## 5. PluginBase API Reference

All plugin classes **must** inherit from `PluginBase` (`plugins/plugin_base.py`).

### Abstract methods (must implement)

#### `get_metadata() -> PluginMetadata`

Return the plugin's metadata object.

```python
def get_metadata(self) -> PluginMetadata:
    return PluginMetadata(
        id="my_plugin",
        name="My Plugin",
        version="1.0.0",
        author="Dev Name",
        description="What my plugin does.",
    )
```

#### `initialize(browser_instance) -> bool`

Called when the plugin loads. `browser_instance` is the `MainWindow` object.

```python
def initialize(self, browser_instance) -> bool:
    self.browser = browser_instance
    # Set up your plugin here
    return True
```

#### `shutdown() -> bool`

Called when the browser closes or the plugin is disabled.

```python
def shutdown(self) -> bool:
    # Clean up resources
    return True
```

### Optional override methods

#### `get_settings_widget() -> QWidget | None`

Return a PySide6 widget to display in the Plugin Store settings panel.

```python
def get_settings_widget(self):
    from PySide6.QtWidgets import QLabel
    return QLabel("No configurable settings.")
```

#### `on_page_loaded(url: str, page: QWebEnginePage)`

Triggered every time a page finishes loading in any tab.

```python
def on_page_loaded(self, url: str, page):
    if "example.com" in url:
        print(f"Loaded example.com page: {url}")
```

#### `on_tab_changed(tab_index: int)`

Triggered when the user switches to a different tab.

#### `on_browser_startup()`

Triggered immediately after the browser window is fully initialized.

#### `on_browser_shutdown()`

Triggered before the browser begins its shutdown sequence.

#### `get_menu_items() -> list`

Return items to inject into the browser's main menu.

```python
def get_menu_items(self) -> list:
    return [
        ("Tools", "Run My Tool", self._run_tool),
    ]
```

Returns a list of `(menu_name, action_label, callback)` tuples.

#### `get_toolbar_actions() -> list`

Return `QAction` objects to inject into the navigation toolbar.

```python
from PySide6.QtGui import QAction, QIcon

def get_toolbar_actions(self) -> list:
    action = QAction(QIcon("plugins/my_plugin/assets/icon.svg"), "My Tool", None)
    action.triggered.connect(self._run_tool)
    return [action]
```

### Utility methods (inherited, do not override)

| Method | Description |
|---|---|
| `is_enabled() -> bool` | Returns whether the plugin is enabled |
| `set_enabled(bool)` | Enable / disable the plugin |
| `get_version() -> str` | Returns `metadata.version` |
| `check_compatibility(browser_version) -> bool` | Checks min/max version range |
| `save_config(dict)` | Saves a config dictionary in memory |
| `load_config() -> dict` | Loads the saved config |

---

## 6. PluginMetadata Reference

`PluginMetadata` is a `dataclass` in `plugins/plugin_base.py`.

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | `str` | Yes | Unique identifier. Must match the directory name. |
| `name` | `str` | Yes | Human-readable name shown in the Plugin Store. |
| `version` | `str` | Yes | SemVer string, e.g. `"1.2.0"`. |
| `author` | `str` | Yes | Author or organization name. |
| `description` | `str` | Yes | Short description (1–2 sentences). |
| `min_browser_version` | `str` | No | Minimum compatible browser version. Default: `"1.0.0"`. |
| `max_browser_version` | `str` | No | Maximum compatible browser version. Default: `"999.0.0"`. |
| `dependencies` | `list[str]` | No | Python package requirements, e.g. `["requests>=2.28", "beautifulsoup4"]`. |
| `permissions` | `list[str]` | No | Permission strings the plugin needs. See [Permissions](#15-permissions). |
| `icon` | `str \| None` | No | Path to icon file relative to plugin directory, or emoji. |
| `homepage` | `str \| None` | No | Plugin homepage URL. |
| `repository` | `str \| None` | No | Source code repository URL. |
| `tags` | `list[str]` | No | Search/filter tags for the Plugin Store. |

---

## 7. plugin_info.json Reference

This file is read **before** importing `plugin.py`. It determines whether the plugin is free or premium, and provides metadata for the Plugin Store UI.

```json
{
  "id": "my_plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "author": "Your Name",
  "description": "One or two sentences describing what the plugin does.",
  "premium": false,
  "price": 0.0,
  "currency": "USD",
  "billing_cycle": "monthly",
  "category": "utilities",
  "tags": ["tag1", "tag2"],
  "features": [
    "Feature description 1",
    "Feature description 2"
  ],
  "free_features": ["basic_feature"],
  "premium_features": ["advanced_feature"],
  "trial_days": 7,
  "requirements": {
    "min_browser_version": "3.0.0",
    "dependencies": ["requests"]
  },
  "permissions": ["web_access"],
  "icon": "assets/icon.svg",
  "homepage": "https://yoursite.com/plugin",
  "repository": "https://github.com/you/my-plugin"
}
```

### Field notes

| Field | Notes |
|---|---|
| `premium` | Set to `false` for open-source / free plugins. The plugin loads without any license check. |
| `free_features` | Feature IDs accessible without a license. |
| `premium_features` | Feature IDs that require a valid license or active trial. |
| `trial_days` | Days of full access before requiring a license. Use `0` to disable trials. |
| `category` | Used to group plugins in the store. Common values: `"utilities"`, `"data_extraction"`, `"network"`, `"customization"`, `"seo"`, `"security"`. |

---

## 8. Browser API

Inside `initialize(browser_instance)`, the `browser_instance` is the `MainWindow` object (`ui.py`). The following attributes are guaranteed to exist.

### Navigation

```python
# Load a URL in the current tab
browser.load_url("https://example.com")

# Open a URL in a new tab
browser.tab_manager.add_new_tab("https://example.com")

# Get the URL bar widget
browser.url_bar  # QLineEdit / ConversationalNavBar

# Get the current QWebEngineView
tab_widget = browser.tab_manager.tabs.currentWidget()
# tab_widget is a QWebEngineView
```

### Tab Manager

```python
tm = browser.tab_manager

# Current tab index
index = tm.tabs.currentIndex()

# Get tab count
count = tm.tabs.count()

# Get a specific tab's web view
web_view = tm.tabs.widget(index)  # QWebEngineView

# Add a new tab
tm.add_new_tab()                     # blank tab
tm.add_new_tab("https://example.com")  # with URL

# Close current tab
tm.close_current_tab()
```

### History

```python
browser.history_manager.add_entry(url, title)
```

### Content Splitter (UI Layout)

```python
# The main horizontal splitter: [sidebar | advanced_panel | tabs | ...]
splitter = browser.content_splitter  # QSplitter

# Insert your widget at position 3 (after tabs)
splitter.insertWidget(3, my_widget)
```

### Side Strip (Sidebar Buttons)

```python
from PySide6.QtGui import QAction, QIcon

action = QAction(QIcon("plugins/my_plugin/assets/icon.svg"), "My Panel", browser)
action.triggered.connect(my_callback)
browser.side_strip.addAction(action)
```

### Advanced Panel Stack

The left sidebar panel area uses a `QStackedWidget`.

```python
# Add your panel to the sidebar stack
browser.advanced_panel_stack.addWidget(my_panel_widget)

# Show it
browser.show_advanced_panel(my_panel_widget)

# Hide it
browser.hide_advanced_panel()
```

### Auth Manager

```python
am = browser.auth_manager

# Is the user logged in?
am.auth_state.is_authenticated  # bool

# Does the user have a license for a plugin?
am.is_plugin_licensed("my_plugin")  # bool

# Get license details
license = am.get_plugin_license("my_plugin")
```

### Plugin Manager

```python
pm = browser.plugin_manager  # UnifiedPluginManager

# Check feature access
pm.can_access_feature("my_plugin", "my_feature")  # bool

# Get full access info
info = pm.get_plugin_access("my_plugin")
# info.access_level: PluginAccessLevel.FREE | PREMIUM | TRIAL
# info.is_licensed: bool
# info.trial_remaining: int (days)
# info.features_available: list[str]
```

---

## 9. UI Integration

### Adding a Sidebar Panel

The recommended pattern for plugins that add a panel to the left sidebar:

```python
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtGui import QAction, QIcon


class MyPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Hello from My Plugin!"))


class MyPlugin(PluginBase):

    def initialize(self, browser_instance) -> bool:
        self.browser = browser_instance

        # Create the panel (parent=None to avoid rendering issues)
        self.panel = MyPanel(parent=None)

        # Add to the advanced panel stack
        self.browser.advanced_panel_stack.addWidget(self.panel)

        # Add a button to the side strip
        action = QAction(
            QIcon("plugins/my_plugin/assets/icon.svg"),
            "My Plugin",
            self.browser,
        )
        action.triggered.connect(self._toggle_panel)
        self.browser.side_strip.addAction(action)
        self._sidebar_action = action

        return True

    def _toggle_panel(self):
        stack = self.browser.advanced_panel_stack
        if stack.currentWidget() is self.panel and stack.isVisible():
            self.browser.hide_advanced_panel()
        else:
            self.browser.show_advanced_panel(self.panel)

    def shutdown(self) -> bool:
        if self._sidebar_action:
            self.browser.side_strip.removeAction(self._sidebar_action)
        return True
```

### Adding a Dock Widget

For panels that should float or dock to the right:

```python
from PySide6.QtWidgets import QDockWidget
from PySide6.QtCore import Qt


def initialize(self, browser_instance) -> bool:
    self.browser = browser_instance
    self.panel = MyPanel()

    self.dock = QDockWidget("My Plugin", browser_instance)
    self.dock.setWidget(self.panel)
    self.dock.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)
    browser_instance.addDockWidget(Qt.RightDockWidgetArea, self.dock)
    self.dock.hide()

    return True
```

### Using KatphiPanelBase

For a consistent look with the rest of the browser's panels, inherit from `KatphiPanelBase`:

```python
from base_panel import KatphiPanelBase
from PySide6.QtWidgets import QVBoxLayout, QLabel


class MyPanel(KatphiPanelBase):

    def __init__(self, parent=None):
        super().__init__(title="My Plugin", parent=parent)
        self._build_content()

    def _build_content(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(QLabel("Content goes here"))
        self.content_widget.setLayout(layout)
```

`KatphiPanelBase` provides:
- Standard 40px header with title and close button
- `get_theme_colors()` method for theme-aware styling
- Auto-subscription to `theme_changed` signal

---

## 10. Theme System Integration

Katphi uses a centralized `ThemeEngine`. Always read colors from it instead of hardcoding hex values.

### Reading colors

```python
try:
    from ui.core.theme_engine import get_color, get_theme_engine
    bg = get_color("surface_0")
    text = get_color("text_primary")
    accent = get_color("accent")
except ImportError:
    bg, text, accent = "#1A1A1A", "#F0F0F0", "#4B9EFF"
```

### Using BasePanel.get_theme_colors()

If your panel inherits from `BasePanel` or `KatphiPanelBase`, call `self.get_theme_colors()`:

```python
def _apply_my_style(self):
    c = self.get_theme_colors()
    self.setStyleSheet(f"""
        QWidget {{
            background: {c['surface_0']};
            color: {c['text_primary']};
        }}
        QPushButton {{
            background: {c['surface_1']};
            border: 1px solid {c['border']};
            border-radius: 4px;
            padding: 4px 10px;
        }}
        QPushButton:hover {{
            background: {c['surface_hover']};
        }}
    """)
```

### Reacting to theme changes

```python
def initialize(self, browser_instance) -> bool:
    ...
    try:
        from ui.core.theme_engine import get_theme_engine
        engine = get_theme_engine()
        if engine:
            engine.theme_changed.connect(self._on_theme_changed)
    except ImportError:
        pass
    return True

def _on_theme_changed(self, theme_name: str):
    self._apply_my_style()
```

### Standard color tokens

| Token | Dark value | Description |
|---|---|---|
| `surface_0` | `#1A1A1A` | Primary background |
| `surface_1` | `#222222` | Secondary background (cards, panels) |
| `surface_2` | `#2A2A2A` | Tertiary background |
| `surface_hover` | `#303030` | Hover state |
| `text_primary` | `#F0F0F0` | Main text |
| `text_secondary` | `#A0A0A0` | Secondary / muted text |
| `text_muted` | `#606060` | Disabled / very muted text |
| `accent` | `#4B9EFF` | Action color (buttons, links) |
| `border` | `rgba(255,255,255,0.08)` | Subtle border |
| `success` | `#3FB950` | Success state |
| `warning` | `#D29922` | Warning state |
| `error` | `#F85149` | Error state |

---

## 11. Icon System

Use `build_nav_icon` to create theme-aware icons from SVG files.

```python
from ui.core.strip_icons import build_nav_icon
from PySide6.QtCore import QSize

# Create a 16×16 icon tinted with the current theme color
icon = build_nav_icon("my_icon_name", color_hex="#A0A0A0", size=QSize(16, 16))
```

The function looks for `icons/<name>.svg` in the project's `icons/` directory, or you can pass an absolute path. It replaces all `fill` and `stroke` attributes in the SVG with `color_hex`.

For plugin-specific icons stored inside your plugin directory, use the lower-level function:

```python
from ui.core.strip_icons import build_strip_icon
import os

icon_path = os.path.join(os.path.dirname(__file__), "assets", "my_icon.svg")
icon = build_strip_icon(os.path.abspath(icon_path), color_hex="#A0A0A0", size=QSize(16, 16))
```

---

## 12. Events and Hooks

You can react to browser events by overriding methods on your `PluginBase` subclass **or** by connecting to Qt signals directly after `initialize()` is called.

### PluginBase hooks

| Method | When called |
|---|---|
| `on_page_loaded(url, page)` | After any tab finishes loading a page |
| `on_tab_changed(tab_index)` | When the active tab changes |
| `on_browser_startup()` | After the browser window opens |
| `on_browser_shutdown()` | Before the browser closes |

### Connecting to Qt signals directly

```python
def initialize(self, browser_instance) -> bool:
    self.browser = browser_instance

    # React when any tab finishes loading
    tabs = browser_instance.tab_manager.tabs
    tabs.currentChanged.connect(self._on_tab_changed)

    # React when the URL bar text changes
    browser_instance.url_bar.textChanged.connect(self._on_url_text_changed)

    return True
```

### Injecting JavaScript into the current page

```python
def run_js_on_current_page(self):
    tab = self.browser.tab_manager.tabs.currentWidget()
    if tab:
        tab.page().runJavaScript(
            "document.title",
            lambda result: print(f"Page title: {result}")
        )
```

---

## 13. Free vs. Premium Plugins

### Free plugins

Set `"premium": false` in `plugin_info.json`. The plugin loads immediately without any authentication check. No license validation is performed.

### Premium plugins

Set `"premium": true`. The plugin requires the user to:
1. Be logged in to their Katphi account
2. Have an active license for the plugin

The plugin can define `free_features` (accessible without a license) and `premium_features` (require license or active trial).

### Hybrid plugins (recommended pattern)

Most commercial plugins follow this pattern:

```python
def initialize(self, browser_instance) -> bool:
    self.browser = browser_instance
    self.plugin_manager = getattr(browser_instance, "plugin_manager", None)

    # Always create the UI — disable premium parts if not licensed
    self.panel = MyPanel(plugin_manager=self.plugin_manager)
    ...
    return True
```

Inside the panel:

```python
def _run_advanced_feature(self):
    if not self.plugin_manager:
        return
    if self.plugin_manager.can_access_feature("my_plugin", "advanced_feature"):
        self._do_advanced_feature()
    else:
        self.plugin_manager.request_feature_access("my_plugin", "advanced_feature", self)
        # ^ This shows a trial/upgrade dialog automatically
```

---

## 14. Premium Decorators

`premium_decorators.py` provides ready-made decorators to protect methods.

### `@requires_premium`

Blocks the method entirely if the user does not have premium access. Shows an upgrade dialog.

```python
from premium_decorators import requires_premium

class MyPanel(QWidget, PremiumMixin):

    @requires_premium(plugin_id="my_plugin", feature="advanced_export")
    def export_advanced(self):
        # Only runs if user has access to "advanced_export"
        self._do_export()
```

### `@premium_feature`

Same as `@requires_premium` but supports a fallback function for free-tier users.

```python
from premium_decorators import premium_feature

class MyPanel(QWidget, PremiumMixin):

    @premium_feature(
        plugin_id="my_plugin",
        feature="csv_export",
        fallback_func=lambda self: self._export_basic()
    )
    def export_csv(self):
        self._export_full_csv()
```

### `@trial_feature`

Allows access during trial period.

```python
from premium_decorators import trial_feature

class MyPanel(QWidget, PremiumMixin):

    @trial_feature(plugin_id="my_plugin", feature="bulk_analysis", max_uses=10)
    def analyze_bulk(self):
        self._run_bulk()
```

### `PremiumMixin`

Mix into your widget class to get helper methods:

```python
from premium_decorators import PremiumMixin
from PySide6.QtWidgets import QWidget

class MyPanel(QWidget, PremiumMixin):

    def __init__(self, plugin_manager=None):
        super().__init__()
        if plugin_manager:
            self.set_plugin_validator(plugin_manager)
        self._setup_ui()

    def _setup_ui(self):
        # After creating widgets, call this to enable/disable
        # premium elements based on current access level
        self.update_premium_ui("my_plugin")
```

---

## 15. Permissions

Declare permissions your plugin needs in both `plugin_info.json` and `PluginMetadata`. Permissions are informational today (used in the Plugin Store UI) but will be enforced in future versions.

| Permission | Description |
|---|---|
| `web_access` | Makes HTTP/HTTPS requests to external URLs |
| `file_system` | Reads or writes files on the local filesystem |
| `data_export` | Exports data to files |
| `network_access` | Low-level network access (proxies, sockets) |
| `proxy_configuration` | Configures system-level proxy settings |
| `ui_modification` | Modifies the browser's UI (adds buttons, panels, etc.) |
| `toolbar` | Adds buttons to the navigation toolbar |
| `clipboard` | Reads from or writes to the system clipboard |
| `notifications` | Shows system notifications |
| `tab_management` | Opens, closes, or rearranges tabs |

---

## 16. Settings Persistence

Use `QSettings` for persistent plugin configuration.

```python
from PySide6.QtCore import QSettings

class MyPlugin(PluginBase):

    def _get_settings(self) -> QSettings:
        return QSettings("Katphi", "MyPlugin")

    def save_user_preference(self, key: str, value):
        s = self._get_settings()
        s.setValue(key, value)

    def load_user_preference(self, key: str, default=None):
        s = self._get_settings()
        return s.value(key, default)
```

Always namespace your settings under `"Katphi"` + your plugin name to avoid collisions with other plugins.

---

## 17. Plugin Lifecycle

```
Browser opens
    │
    ▼
UnifiedPluginManager.__init__()
    │  Scans plugins/ directory
    │  Reads plugin_info.json for each subdirectory
    │
    ▼
load_all_installed_plugins()
    │  For each plugin:
    │    1. get_plugin_access(plugin_id)   ← checks free/premium/trial
    │    2. load_plugin(plugin_id)
    │         importlib loads plugin.py
    │         calls initialize_plugin()    ← YOUR CODE RUNS HERE
    │         emits plugin_loaded signal
    │
    ▼
Browser runs normally
    │  on_page_loaded() called on tab load
    │  on_tab_changed() called on tab switch
    │
    ▼
Browser closes
    │
    ▼
unload_plugin(plugin_id)
    │  calls plugin.shutdown()            ← YOUR CLEANUP RUNS HERE
    │  removes from sys.modules
    │  emits plugin_unloaded signal
```

---

## 18. Real-World Examples

### Example A — Page Inspector (reads page DOM)

```python
class PageInspectorPlugin(PluginBase):

    def initialize(self, browser_instance) -> bool:
        self.browser = browser_instance
        return True

    def on_page_loaded(self, url: str, page):
        page.runJavaScript(
            "document.querySelectorAll('h1').length",
            lambda count: print(f"[PageInspector] {url} has {count} H1 tags")
        )

    def shutdown(self) -> bool:
        return True
```

### Example B — URL Watcher (reacts to navigation)

```python
class UrlWatcherPlugin(PluginBase):

    WATCHED_DOMAINS = ["github.com", "stackoverflow.com"]

    def initialize(self, browser_instance) -> bool:
        self.browser = browser_instance
        tabs = browser_instance.tab_manager.tabs
        tabs.currentChanged.connect(self._on_tab_changed)
        return True

    def _on_tab_changed(self, index: int):
        web_view = self.browser.tab_manager.tabs.widget(index)
        if web_view:
            url = web_view.url().toString()
            for domain in self.WATCHED_DOMAINS:
                if domain in url:
                    print(f"[UrlWatcher] Developer site detected: {url}")

    def shutdown(self) -> bool:
        return True
```

### Example C — Sidebar Panel with theme support

```python
from base_panel import KatphiPanelBase
from PySide6.QtWidgets import QVBoxLayout, QPushButton, QLabel


class MyPanel(KatphiPanelBase):

    def __init__(self, parent=None):
        super().__init__(title="My Tool", parent=parent)
        self._build_content()

    def _build_content(self):
        c = self.get_theme_colors()

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(8)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(f"color: {c['text_secondary']};")
        layout.addWidget(self.status_label)

        run_btn = QPushButton("Run Analysis")
        run_btn.setStyleSheet(f"""
            QPushButton {{
                background: {c['accent']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: 600;
            }}
        """)
        run_btn.clicked.connect(self._run)
        layout.addWidget(run_btn)

        layout.addStretch()
        self.content_widget.setLayout(layout)

    def _run(self):
        self.status_label.setText("Running...")
```

---

## 19. Packaging and Distribution

### Directory ZIP package

```bash
cd plugins/
zip -r my_plugin_v1.0.0.zip my_plugin/
```

The ZIP must contain the plugin directory at its root:

```
my_plugin_v1.0.0.zip
└── my_plugin/
    ├── __init__.py
    ├── plugin.py
    └── plugin_info.json
```

### Manual installation

Copy the plugin directory into the `plugins/` folder inside the browser's root directory, then restart the browser.

```
katphi-browser/
└── plugins/
    └── my_plugin/    ← drop it here
```

### Publishing to the Katphi Plugin Store

To list your plugin in the official Plugin Store (served by the Katphi backend):

1. Submit your plugin at [katphi.com/developers/submit](https://katphi.com/developers/submit) (coming soon)
2. Provide a valid `plugin_info.json` with `homepage` and `repository` fields
3. If it's a premium plugin, integrate with the Katphi licensing API (documentation available upon request)

---

## 20. Testing Your Plugin

### Run in development mode

```bash
# From the browser root directory
python3 main.py
```

Watch the terminal for your plugin's log output. All `print()` calls from `plugin.py` are visible.

### Verify your plugin loads

```python
# From the Python REPL inside the browser root
import importlib.util, sys
spec = importlib.util.spec_from_file_location("plugin", "plugins/my_plugin/plugin.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(mod.initialize_plugin())   # Should print True
print(mod.get_plugin_info())
```

### Syntax check

```bash
python3 -c "import ast; ast.parse(open('plugins/my_plugin/plugin.py').read()); print('Syntax OK')"
```

### Common errors

| Error | Cause | Fix |
|---|---|---|
| `Plugin missing plugin.py` | `plugin.py` not found in directory | Add the file |
| `initialize_plugin()` returns `False` | Exception inside `initialize()` | Add try/except and log the error |
| Plugin loads but panel doesn't appear | Panel not added to `advanced_panel_stack` | Call `browser.advanced_panel_stack.addWidget(panel)` |
| Icons are black or invisible | SVG uses `fill="none"` on root element | Use `fill="currentColor"` in SVG paths |
| `ImportError: No module named 'X'` | Missing Python dependency | Install it: `pip install X` |

---

## 21. Checklist Before Publishing

- [ ] `plugin_info.json` is valid JSON and has all required fields
- [ ] `id` field matches the directory name exactly
- [ ] `initialize_plugin()` returns `True` on success, `False` on failure
- [ ] `shutdown()` releases all resources (timers, threads, file handles)
- [ ] No API keys, tokens, or passwords hardcoded in source
- [ ] All sensitive config loaded from `QSettings` or environment variables
- [ ] Colors read from `ThemeEngine`, not hardcoded hex values
- [ ] Premium features are properly gated (use `can_access_feature()` or decorators)
- [ ] Plugin works when the user is **not** logged in (free tier / no auth)
- [ ] Python dependencies listed in `plugin_info.json` under `requirements.dependencies`
- [ ] `permissions` list is accurate and minimal
- [ ] `on_browser_shutdown()` / `shutdown()` disconnect all Qt signals
- [ ] Tested with the browser's dark and light themes
- [ ] `repository` field points to public source code (for open-source plugins)

---

## Appendix A — Minimal plugin_info.json (free plugin)

```json
{
  "id": "my_plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "author": "Your Name",
  "description": "Short description.",
  "premium": false,
  "category": "utilities",
  "tags": [],
  "permissions": [],
  "requirements": {
    "min_browser_version": "3.0.0",
    "dependencies": []
  }
}
```

## Appendix B — Full plugin_info.json (premium plugin)

```json
{
  "id": "my_premium_plugin",
  "name": "My Premium Plugin",
  "version": "1.0.0",
  "author": "Your Name",
  "description": "A professional-grade tool for Katphi Browser.",
  "premium": true,
  "price": 9.99,
  "currency": "USD",
  "billing_cycle": "monthly",
  "category": "data_extraction",
  "tags": ["data", "automation"],
  "features": ["Export to CSV", "Scheduled runs", "Pattern detection"],
  "free_features": ["basic_export"],
  "premium_features": ["csv_export", "scheduled_runs", "pattern_detection"],
  "trial_days": 7,
  "requirements": {
    "min_browser_version": "3.0.0",
    "dependencies": ["beautifulsoup4>=4.11", "pandas"]
  },
  "permissions": ["web_access", "file_system", "data_export"],
  "icon": "assets/icon.svg",
  "homepage": "https://yoursite.com/plugin",
  "repository": "https://github.com/you/my-premium-plugin"
}
```

## Appendix C — Complete minimal plugin.py template

```python
#!/usr/bin/env python3
"""
my_plugin — brief one-line description.
Author: Your Name
Version: 1.0.0
"""

import logging
from plugins.plugin_base import PluginBase, PluginMetadata

logger = logging.getLogger(__name__)

PLUGIN_ID = "my_plugin"
PLUGIN_VERSION = "1.0.0"


class MyPlugin(PluginBase):

    def __init__(self):
        super().__init__()
        self.browser = None

    def get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            id=PLUGIN_ID,
            name="My Plugin",
            version=PLUGIN_VERSION,
            author="Your Name",
            description="Brief description.",
            min_browser_version="3.0.0",
            dependencies=[],
            permissions=[],
        )

    def initialize(self, browser_instance) -> bool:
        try:
            self.browser = browser_instance
            logger.info("[MyPlugin] Initialized successfully")
            return True
        except Exception as e:
            logger.error("[MyPlugin] Initialization error: %s", e)
            return False

    def shutdown(self) -> bool:
        try:
            self.browser = None
            logger.info("[MyPlugin] Shutdown complete")
            return True
        except Exception as e:
            logger.error("[MyPlugin] Shutdown error: %s", e)
            return False

    def on_page_loaded(self, url: str, page):
        pass  # Override if you need to react to page loads

    def on_browser_shutdown(self):
        pass  # Override for cleanup on browser exit


# ─── Module interface ────────────────────────────────────────────────────────

_plugin_instance: MyPlugin | None = None


def initialize_plugin() -> bool:
    global _plugin_instance
    try:
        _plugin_instance = MyPlugin()
        return True
    except Exception as e:
        logger.error("[my_plugin] initialize_plugin error: %s", e)
        return False


def get_plugin_instance() -> MyPlugin | None:
    return _plugin_instance


def get_plugin_info() -> dict:
    return {
        "id": PLUGIN_ID,
        "name": "My Plugin",
        "version": PLUGIN_VERSION,
        "premium": False,
        "available": _plugin_instance is not None,
    }


def shutdown_plugin() -> bool:
    global _plugin_instance
    if _plugin_instance:
        result = _plugin_instance.shutdown()
        _plugin_instance = None
        return result
    return True
```

---

*Katphi Browser is open-source software. Contributions and third-party plugins are welcome.*
*For questions, open an issue on the repository or visit [katphi.com](https://katphi.com).*
