"""Tests de la CSP de GenTab (A-006) y del JSON seguro dentro de <script> (A-011)."""

import json
import os
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gentab_engine import GENTAB_CSP, apply_gentab_csp, json_for_script  # noqa: E402

CSP_META = f'<meta http-equiv="Content-Security-Policy" content="{GENTAB_CSP}">'


def _csp_metas(html):
    return re.findall(r"<meta\b[^>]*content-security-policy[^>]*>", html, re.IGNORECASE)


def test_csp_restrictiva():
    assert "default-src 'none'" in GENTAB_CSP
    assert "connect-src 'none'" in GENTAB_CSP
    assert "https:" not in GENTAB_CSP


def test_head_presente_csp_primer_hijo():
    html = ("<!DOCTYPE html><html lang='es'><head><script>fetch('https://x')</script>"
            "<title>T</title></head><body>hola</body></html>")
    out = apply_gentab_csp(html)
    assert "<head>" + CSP_META + "<script>" in out
    assert out.index(CSP_META) < out.index("<script")


def test_head_ausente():
    html = "<!DOCTYPE html><html><body><script>alert(1)</script></body></html>"
    out = apply_gentab_csp(html)
    assert out.startswith("<!DOCTYPE html><html>" + CSP_META)
    assert out.index(CSP_META) < out.index("<script")


def test_sin_html_ni_head_y_texto_inicial():
    out = apply_gentab_csp("Texto<script>x()</script>")
    assert out.startswith(CSP_META)


def test_no_confunde_header_con_head():
    html = "<html><header>cab</header><script>x()</script></html>"
    out = apply_gentab_csp(html)
    assert out.startswith("<html>" + CSP_META + "<header>")


def test_quita_csp_base_y_refresh_del_modelo():
    html = ("<html><head>"
            "<meta http-equiv='Content-Security-Policy' content=\"default-src *\">"
            "<META HTTP-EQUIV=content-security-policy CONTENT=\"connect-src *\">"
            "<base href='https://evil.example/'>"
            "<meta http-equiv=\"refresh\" content=\"0;url=https://evil.example/\">"
            "</head><body></body></html>")
    out = apply_gentab_csp(html)
    assert _csp_metas(out) == [CSP_META]
    assert "<base" not in out.lower()
    assert "refresh" not in out.lower()
    assert "evil.example" not in out


def test_idempotente():
    html = "<html><head><title>x</title></head><body></body></html>"
    once = apply_gentab_csp(html)
    assert apply_gentab_csp(once) == once
    assert len(_csp_metas(once)) == 1


def test_json_con_cierre_de_script():
    data = [{"title": "</script><script>alert(1)</script>", "excerpt": "<!-- x -->"}]
    js = json_for_script(data)
    assert "</" not in js
    assert "<!--" not in js
    # Sigue siendo un literal JS válido con el mismo contenido (\/ y \! son escapes JS
    # inofensivos; json.loads no los admite, así que se deshace el escape para comparar)
    assert json.loads(js.replace("<\\/", "</").replace("<\\!--", "<!--")) == data
    page = f"<script>const DATA = {js};</script>"
    assert page.lower().count("</script") == 1
