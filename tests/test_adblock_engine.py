"""Tests del motor de Katphi AdBlock (plugins/adblock/engine.py).

El motor es Python puro: se prueba sin Qt, con reglas de ejemplo y con las
listas que trae el plugin.
"""
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_DIR = os.path.join(ROOT, "plugins", "adblock")
if not os.path.isdir(PLUGIN_DIR):  # copia sin plugins (repositorio público)
    pytest.skip("plugin adblock no incluido", allow_module_level=True)
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

import engine as E  # noqa: E402


def _eng(*rules):
    return E.Engine.from_lines(list(rules))


def _decide(eng, url, page="www.ejemplo.es", rtype=E.T_SCRIPT):
    from urllib.parse import urlsplit
    return eng.match(url, urlsplit(url).hostname, page, rtype)[0]


# ── red ──

def test_host_anchor_blocks_subdomains_only_at_label_boundary():
    eng = _eng("||doubleclick.net^")
    assert _decide(eng, "https://securepubads.g.doubleclick.net/tag/js/gpt.js") == "block"
    assert _decide(eng, "https://doubleclick.net/x") == "block"
    assert _decide(eng, "https://notdoubleclick.net/x") is None


def test_exception_overrides_block_and_important_overrides_exception():
    eng = _eng("||ads.example.com^", "@@||ads.example.com/ok.js")
    assert _decide(eng, "https://ads.example.com/ok.js") == "allow"
    assert _decide(eng, "https://ads.example.com/ad.js") == "block"
    eng = _eng("||ads.example.com^$important", "@@||ads.example.com/ok.js")
    assert _decide(eng, "https://ads.example.com/ok.js") == "block"


def test_resource_types_and_negation():
    eng = _eng("||cdn.example.com/ads/$script", "||t.example.com^$~image")
    assert _decide(eng, "https://cdn.example.com/ads/a.js", rtype=E.T_SCRIPT) == "block"
    assert _decide(eng, "https://cdn.example.com/ads/a.png", rtype=E.T_IMAGE) is None
    assert _decide(eng, "https://t.example.com/p.gif", rtype=E.T_IMAGE) is None
    assert _decide(eng, "https://t.example.com/p.js", rtype=E.T_XHR) == "block"


def test_xhr_stylesheet_font_subdocument_types_match():
    # El bloqueador antiguo nunca aplicaba estos tipos (nombres de Qt erróneos)
    eng = _eng("/beacon/*$xmlhttprequest", "/adframe.$subdocument",
               "/adstyle.css$stylesheet", "/adfont.$font")
    assert _decide(eng, "https://x.com/beacon/1", rtype=E.T_XHR) == "block"
    assert _decide(eng, "https://x.com/adframe.html", rtype=E.T_SUBDOCUMENT) == "block"
    assert _decide(eng, "https://x.com/adstyle.css", rtype=E.T_STYLESHEET) == "block"
    assert _decide(eng, "https://x.com/adfont.woff", rtype=E.T_FONT) == "block"


def test_domain_option_uses_page_not_request_host():
    eng = _eng("||cdn.example.com/banner$domain=periodico.es")
    assert _decide(eng, "https://cdn.example.com/banner.js", page="www.periodico.es") == "block"
    assert _decide(eng, "https://cdn.example.com/banner.js", page="otro.es") is None


def test_third_party():
    eng = _eng("||tracker.com^$third-party")
    assert _decide(eng, "https://tracker.com/t.js", page="www.ejemplo.es") == "block"
    assert _decide(eng, "https://tracker.com/t.js", page="www.tracker.com") is None


def test_regex_and_separator():
    eng = _eng(r"/\/ad[sv]?\d+\.js/", "&adformat^")
    assert _decide(eng, "https://x.com/ads12.js") == "block"
    assert _decide(eng, "https://x.com/v?a=1&adformat=2&b") == "block"
    assert _decide(eng, "https://x.com/loads.js") is None
    assert _decide(eng, "https://x.com/v?a=1&adformats=2") is None


def test_unknown_or_unsupported_options_drop_the_filter():
    eng = _eng("||x.com^$csp=script-src 'none'", "||y.com^$removeparam=utm", "||z.com^$nonsense")
    assert eng.stats["network"] == 0


def test_badfilter_disables_filter():
    eng = _eng("||x.com^$script", "||x.com^$script,badfilter")
    assert _decide(eng, "https://x.com/a.js") is None


def test_main_frame_and_popup_filters_are_not_applied():
    eng = _eng("||malo.com^$document", "||pop.com^$popup")
    assert eng.stats["network"] == 0 or _decide(eng, "https://malo.com/") is None


def test_page_exception_document_flag():
    eng = _eng("@@||permitido.es^$document")
    assert eng.page_flags("https://www.permitido.es/x", "www.permitido.es") & E.PF_DOCUMENT


# ── cosmético y scriptlets ──

def test_cosmetic_generic_specific_and_exceptions():
    eng = _eng("##.ad-banner", "periodico.es##.patrocinado", "periodico.es#@#.ad-banner",
               "~otro.es##.solo-fuera")
    assert ".ad-banner" in eng.cosmetic.generic
    cfg = eng.cosmetic_for("www.periodico.es")
    assert ".patrocinado" in cfg["hide"]
    assert ".ad-banner" in cfg["unhide"]
    assert ".solo-fuera" in eng.cosmetic_for("www.otro.es")["unhide"]


def test_entity_domains_and_procedural():
    eng = _eng("google.*##.ads-top", "x.com##div.card:has-text(Patrocinado):upward(2)")
    assert ".ads-top" in eng.cosmetic_for("www.google.co.uk")["hide"]
    proc = eng.cosmetic_for("x.com")["proc"]
    assert proc == [["div.card", [["has-text", "Patrocinado"], ["upward", "2"]]]]


def test_scriptlets_parsed_with_aliases_and_exclusions():
    eng = _eng("a.com,~b.a.com##+js(aopr, adBlockDetected)",
               "a.com##+js(set, ads.enabled, false)",
               "a.com##+js(trusted-replace-fetch-response, x, y)")
    js = eng.cosmetic_for("a.com")["js"]
    assert ["abort-on-property-read", "adBlockDetected"] in js
    assert ["set-constant", "ads.enabled", "false"] in js
    assert all(c[0] != "trusted-replace-fetch-response" for c in js)
    assert ["abort-on-property-read", "adBlockDetected"] not in eng.cosmetic_for("b.a.com")["js"]
    eng = _eng("a.com##+js(aopr, adBlockDetected)", "a.com#@#+js(abort-on-property-read, adBlockDetected)")
    assert eng.cosmetic_for("a.com")["js"] == []


def test_bucket_hash_matches_javascript():
    node = shutil.which("node") or shutil.which("nodejs")
    if not node:
        pytest.skip("sin node")
    import scripts as JS
    js = JS._HOST_HELPERS + "\nconsole.log(['www.marca.com','google.*','a.b.c'].map(kabFnv).join(','));"
    out = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=30).stdout.strip()
    assert out == ",".join(str(E.fnv1a(k)) for k in ("www.marca.com", "google.*", "a.b.c"))


# ── listas reales del plugin ──

@pytest.fixture(scope="module")
def real_engine():
    lines = []
    lists_dir = os.path.join(PLUGIN_DIR, "lists")
    for f in sorted(os.listdir(lists_dir)):
        if f.endswith(".txt") and f != "LICENCIAS.txt":
            with open(os.path.join(lists_dir, f), encoding="utf-8") as fh:
                lines.extend(fh.read().splitlines())
    return E.Engine.from_lines(lines)


@pytest.mark.parametrize("url,page,rtype", [
    ("https://securepubads.g.doubleclick.net/tag/js/gpt.js", "www.elmundo.es", E.T_SCRIPT),
    ("https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js", "as.com", E.T_SCRIPT),
    ("https://c.amazon-adsystem.com/aax2/apstag.js", "www.marca.com", E.T_SCRIPT),
    ("https://cdn.taboola.com/libtrc/x/loader.js", "as.com", E.T_SCRIPT),
    ("https://www.google-analytics.com/analytics.js", "as.com", E.T_SCRIPT),
    ("https://imasdk.googleapis.com/js/sdkloader/ima3.js", "www.marca.com", E.T_SCRIPT),
    ("https://www.youtube.com/api/stats/ads?ver=2", "www.youtube.com", E.T_XHR),
    ("https://www.youtube.com/pagead/viewthroughconversion/1", "www.youtube.com", E.T_XHR),
])
def test_real_lists_block_ads(real_engine, url, page, rtype):
    assert _decide(real_engine, url, page, rtype) == "block"


@pytest.mark.parametrize("url,page,rtype", [
    ("https://www.youtube.com/s/player/abc/player_ias.vflset/es_ES/base.js", "www.youtube.com", E.T_SCRIPT),
    ("https://rr3---sn-x.googlevideo.com/videoplayback?expire=1", "www.youtube.com", E.T_XHR),
    ("https://fonts.googleapis.com/css2?family=Roboto", "www.marca.com", E.T_STYLESHEET),
    ("https://ajax.googleapis.com/ajax/libs/jquery/3.6.0/jquery.min.js", "as.com", E.T_SCRIPT),
    ("https://www.gstatic.com/recaptcha/releases/x/recaptcha__es.js", "as.com", E.T_SCRIPT),
    ("https://www.elmundo.es/assets/main.js", "www.elmundo.es", E.T_SCRIPT),
])
def test_real_lists_do_not_block_content(real_engine, url, page, rtype):
    assert _decide(real_engine, url, page, rtype) != "block"


def test_youtube_has_cosmetic_and_scriptlets(real_engine):
    cfg = real_engine.cosmetic_for("www.youtube.com")
    assert "ytd-ad-slot-renderer" in cfg["hide"]
    assert any(c[0] == "json-prune" for c in cfg["js"])
