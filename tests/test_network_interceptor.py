"""Tests de la lista blanca por host y de los User-Agent del interceptor de red."""

import os
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import network_interceptor  # noqa: E402
from network_interceptor import NetworkInterceptor  # noqa: E402


class _Interceptor:
    """Lo mínimo de NetworkInterceptor para probar _should_block_url sin SQLite."""

    def __init__(self, patterns):
        self.blocked_patterns = [
            {"pattern": p, "type": "wildcard",
             "compiled": NetworkInterceptor._compile_pattern(None, p, "wildcard")}
            for p in patterns
        ]

    _should_block_url = NetworkInterceptor._should_block_url


def test_whitelist_no_se_salta_con_la_query():
    it = _Interceptor(["*evil.com*"])
    assert it._should_block_url("https://evil.com/?x=google.com")
    assert it._should_block_url("https://evil.com/google.com/x.js")


def test_whitelist_por_host_y_subdominio():
    it = _Interceptor(["*google*"])
    assert not it._should_block_url("https://google.com/search?q=1")
    assert not it._should_block_url("https://www.google.com/")
    assert it._should_block_url("https://notgoogle.com.evil.net/")


def test_sin_patrones_no_bloquea():
    assert not _Interceptor([])._should_block_url("https://evil.com/")


def test_user_agent_chromium_coherente():
    agents = network_interceptor._build_user_agents()
    major = network_interceptor._chromium_major()
    chrome = agents["Chrome"]
    assert f"Chrome/{major}.0.0.0" in chrome
    assert "QtWebEngine" not in chrome
    assert network_interceptor._platform_token() in chrome
    assert agents["Edge"].startswith(chrome) and f"Edg/{major}" in agents["Edge"]
    assert re.search(r"Chrome/\d+\.0\.0\.0 Mobile", agents["Android"])


def test_plataforma_real():
    token = network_interceptor._platform_token()
    if sys.platform.startswith("linux"):
        assert token == "X11; Linux x86_64"
    elif sys.platform.startswith("win"):
        assert token.startswith("Windows NT")
