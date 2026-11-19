"""
Idioma de la interfaz de Katphi Browser (español / inglés).

Los textos del código se escriben en español y se pasan por ``tr()``:

    from i18n import tr
    QLabel(tr("Guardar"))
    tr("Descargado {name}", name=fname)

Si el idioma activo es el inglés, ``tr()`` busca el texto en el catálogo
(``locales/en.py``, diccionario español -> inglés). Algunos textos antiguos
están escritos en inglés; para ellos ``locales/es.py`` (inglés -> español) se
usa cuando el idioma es el español. Si un texto no está en el catálogo se
devuelve tal cual, así que un texto sin traducir nunca rompe nada.

El idioma se elige en Ajustes > General y se guarda en
QSettings("Katphi", "Settings") con la clave ``ui/language`` ("es" / "en").
Sin valor guardado se usa el idioma del sistema (español si empieza por "es",
inglés en cualquier otro caso). La variable de entorno KATPHI_LANG manda sobre
todo. El cambio se aplica al reiniciar el navegador.

Los plugins registran su propio catálogo con ``register_catalog(dict)`` y
deben importar ``tr`` con un respaldo para navegadores antiguos:

    try:
        from i18n import tr, register_catalog
    except ImportError:
        def tr(text, **kw):
            return text.format(**kw) if kw else text
        def register_catalog(_catalog):
            pass
"""

import os

SUPPORTED = ("es", "en")
SETTINGS_KEY = "ui/language"

_lang = None
_catalogs = {}


def _system_language() -> str:
    try:
        from PySide6.QtCore import QLocale
        name = QLocale.system().name() or ""
    except Exception:
        name = ""
    if not name:
        import locale
        try:
            name = locale.getlocale()[0] or ""
        except Exception:
            name = ""
        name = name or os.environ.get("LANG", "")
    return "es" if name.lower().startswith("es") else "en"


def _stored_language() -> str:
    try:
        from PySide6.QtCore import QSettings
        value = QSettings("Katphi", "Settings").value(SETTINGS_KEY, "")
        return str(value or "")
    except Exception:
        return ""


def get_language() -> str:
    """Idioma activo ("es" o "en"). Se decide una vez por sesión."""
    global _lang
    if _lang is None:
        lang = os.environ.get("KATPHI_LANG", "").strip().lower()[:2]
        if lang not in SUPPORTED:
            lang = _stored_language()
        if lang not in SUPPORTED:
            lang = _system_language()
        _lang = lang
    return _lang


def get_saved_language() -> str:
    """Idioma guardado en Ajustes ("es", "en" o "" = el del sistema)."""
    lang = _stored_language()
    return lang if lang in SUPPORTED else ""


def save_language(lang: str) -> None:
    """Guarda el idioma elegido ("" = el del sistema). Se aplica al reiniciar."""
    from PySide6.QtCore import QSettings
    s = QSettings("Katphi", "Settings")
    if lang in SUPPORTED:
        s.setValue(SETTINGS_KEY, lang)
    else:
        s.remove(SETTINGS_KEY)
    s.sync()


def set_language(lang: str) -> None:
    """Fija el idioma de esta sesión (tests y arranque)."""
    global _lang
    _lang = lang if lang in SUPPORTED else "es"


def _load_catalog(lang: str) -> dict:
    cat = _catalogs.get(lang)
    if cat is None:
        cat = _catalogs[lang] = {}
        try:
            if lang == "en":
                from locales.en import EN as data
            else:
                from locales.es import ES as data
            cat.update(data)
        except Exception:
            pass
    return cat


def register_catalog(catalog: dict, lang: str = "en") -> None:
    """Añade traducciones de un plugin.

    lang="en": español -> inglés (lo normal); lang="es": inglés -> español,
    para textos que el plugin tenga escritos en inglés.
    """
    if catalog:
        _load_catalog(lang).update(catalog)


def N_(text):
    """Marca un texto para traducir sin traducirlo aún (se traduce con tr(var))."""
    return text


def tr(text, **kwargs):
    """Traduce ``text`` al idioma activo y, si hay kwargs, aplica format()."""
    if not isinstance(text, str):
        return text
    text = _load_catalog(get_language()).get(text, text)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text
