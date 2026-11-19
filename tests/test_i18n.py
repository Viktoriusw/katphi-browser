"""Sistema de idioma (i18n.py) y catálogos locales/en.py y locales/es.py."""
import collections
import importlib
import re

import i18n

PH = re.compile(r"\{[^{}]*\}")
PC = re.compile(r"%[-#0 +]*\d*(?:\.\d+)?[sdrfixXc%]")


def _real_catalog(lang):
    mod = importlib.import_module("locales.en" if lang == "en" else "locales.es")
    return mod.EN if lang == "en" else mod.ES


def test_catalogs_keep_placeholders():
    for lang in ("en", "es"):
        for src, dst in _real_catalog(lang).items():
            assert collections.Counter(PH.findall(src)) == collections.Counter(PH.findall(dst)), src
            if "{" not in src:
                assert collections.Counter(PC.findall(src)) == collections.Counter(PC.findall(dst)), src


def test_catalogs_not_empty():
    assert len(_real_catalog("en")) > 1000
    assert len(_real_catalog("es")) > 100


def test_tr_translates_and_formats(monkeypatch):
    monkeypatch.setattr(i18n, "_catalogs", {"en": dict(_real_catalog("en")), "es": {}})
    monkeypatch.setattr(i18n, "_lang", "en")
    assert i18n.tr("Guardar") == "Save"
    assert i18n.tr("Pestaña {value} de {count}.", value=2, count=5) == "Tab 2 of 5."
    # Sin traducción: se devuelve el texto tal cual
    assert i18n.tr("texto que no existe {x}", x=1) == "texto que no existe 1"


def test_tr_spanish_catalog_for_english_sources(monkeypatch):
    monkeypatch.setattr(i18n, "_catalogs", {"en": {}, "es": dict(_real_catalog("es"))})
    monkeypatch.setattr(i18n, "_lang", "es")
    assert i18n.tr("Last hour") == "La última hora"
    assert i18n.tr("Guardar") == "Guardar"


def test_bad_format_does_not_crash(monkeypatch):
    monkeypatch.setattr(i18n, "_catalogs", {"en": {"Hola {a}": "Hello {b}"}, "es": {}})
    monkeypatch.setattr(i18n, "_lang", "en")
    assert i18n.tr("Hola {a}", a=1) == "Hello {b}"


def test_register_catalog(monkeypatch):
    monkeypatch.setattr(i18n, "_catalogs", {"en": {}, "es": {}})
    monkeypatch.setattr(i18n, "_lang", "en")
    i18n.register_catalog({"Hola plugin": "Hello plugin"})
    assert i18n.tr("Hola plugin") == "Hello plugin"


def test_env_overrides_language(monkeypatch):
    monkeypatch.setattr(i18n, "_lang", None)
    monkeypatch.setenv("KATPHI_LANG", "en_GB")
    assert i18n.get_language() == "en"
    monkeypatch.setattr(i18n, "_lang", None)
    monkeypatch.setenv("KATPHI_LANG", "es")
    assert i18n.get_language() == "es"
