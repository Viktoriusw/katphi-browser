#!/usr/bin/env python3
"""
LLM Client - Abstracción unificada para proveedores LLM en Katphi Browser.

Proveedores soportados:
  - LM Studio    : servidor local OpenAI-compatible  (sin API key)
  - Ollama       : servidor local, API nativa         (sin API key)
  - llmapi.ai    : gateway cloud gratuito/premium     (requiere API key)
  - Anthropic    : API nativa Claude                  (requiere API key)
  - HuggingFace  : Inference API / serverless         (requiere API key)
  - OpenAI       : API oficial (GPT)                  (requiere API key)
  - DeepSeek     : API oficial, OpenAI-compatible     (requiere API key)

API idéntica: LLMClient(config).chat(messages, max_tokens, temperature)
"""

import json
import logging
import requests
from dataclasses import dataclass, field
from typing import Iterator, List, Dict, Optional

from PySide6.QtCore import QSettings

logger = logging.getLogger(__name__)

# ─── Constantes ────────────────────────────────────────────────────────────────

PROVIDER_LOCAL = "local"              # LM Studio / cualquier servidor OpenAI-compatible
PROVIDER_OLLAMA = "ollama"            # Ollama (API nativa /api/*)
PROVIDER_OPENAI = "openai"            # API oficial de OpenAI
PROVIDER_DEEPSEEK = "deepseek"        # API oficial de DeepSeek
PROVIDER_GEMINI = "gemini"            # Google Gemini (endpoint OpenAI-compatible)
PROVIDER_OPENROUTER = "openrouter"    # OpenRouter (cientos de modelos con una key)
PROVIDER_GROQ = "groq"                # Groq (inferencia muy rápida)
PROVIDER_MISTRAL = "mistral"          # Mistral AI
PROVIDER_XAI = "xai"                  # xAI (Grok)
PROVIDER_QWEN = "qwen"                # Qwen (Alibaba Cloud Model Studio)
PROVIDER_LLMAPI = "llmapi"            # llmapi.ai
PROVIDER_ANTHROPIC = "anthropic"      # API nativa de Anthropic
PROVIDER_HUGGINGFACE = "huggingface"  # HuggingFace Inference API

LLMAPI_BASE_URL = "https://api.llmapi.ai"
ANTHROPIC_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_API_VERSION = "2023-06-01"
HUGGINGFACE_BASE_URL = "https://api-inference.huggingface.co"
# Endpoint OpenAI-compatible (Serverless Inference — modelos de texto)
HUGGINGFACE_ROUTER_URL = "https://router.huggingface.co/v1/chat/completions"
OLLAMA_DEFAULT_URL = "http://localhost:11434"
# Ollama usa por defecto un contexto pequeño (2k-4k) y recorta el prompt en silencio.
# Se fija num_ctx explícitamente: el del modelo, limitado para no disparar la RAM/VRAM.
OLLAMA_MAX_NUM_CTX = 8192
OLLAMA_FALLBACK_NUM_CTX = 4096

# Modelos de Anthropic sugeridos (IDs exactos de la API; el botón "Actualizar"
# consulta /v1/models para ver los disponibles en la cuenta del usuario)
ANTHROPIC_MODELS = [
    # Claude 5
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-fable-5-1",
    # Claude 4
    "claude-opus-4-8",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
]

ANTHROPIC_DEFAULT_MODEL = "claude-opus-5"

# IDs que versiones anteriores del navegador guardaban pero la API no reconoce
_ANTHROPIC_INVALID_LEGACY_MODELS = {
    "claude-sonnet-3-7", "claude-sonnet-3-5", "claude-haiku-3-5",
    "claude-opus-3", "claude-sonnet-3", "claude-haiku-3",
}

# Modelos que rechazan temperature/top_p/top_k con HTTP 400
_ANTHROPIC_NO_SAMPLING_PREFIXES = (
    "claude-fable-", "claude-mythos-", "claude-opus-5", "claude-sonnet-5",
    "claude-opus-4-7", "claude-opus-4-8",
)

# Modelos disponibles en HuggingFace Inference API (serverless)
HUGGINGFACE_MODELS = [
    # Meta Llama
    "meta-llama/Llama-3.3-70B-Instruct",
    "meta-llama/Llama-3.1-8B-Instruct",
    "meta-llama/Llama-3.2-3B-Instruct",
    # Mistral / Mixtral
    "mistralai/Mistral-7B-Instruct-v0.3",
    "mistralai/Mixtral-8x7B-Instruct-v0.1",
    "mistralai/Mistral-Small-3.1-24B-Instruct-2503",
    # Qwen
    "Qwen/Qwen2.5-72B-Instruct",
    "Qwen/Qwen2.5-Coder-32B-Instruct",
    # DeepSeek
    "deepseek-ai/DeepSeek-R1",
    "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
    # Google
    "google/gemma-2-27b-it",
    "google/gemma-2-9b-it",
    # Microsoft
    "microsoft/Phi-4-mini-instruct",
]

HUGGINGFACE_DEFAULT_MODEL = "meta-llama/Llama-3.3-70B-Instruct"

# Proveedores cloud con API OpenAI-compatible + API key.
# Para añadir otro servicio de este tipo basta con una entrada nueva aquí;
# los paneles de IA generan su sección de configuración a partir de esta tabla.
#   base_url      : raíz de la API (se le añade /chat/completions y /models)
#   models        : sugerencias iniciales (el botón "Actualizar" consulta /models)
#   context       : ventana de contexto que se asume para recortar el prompt
#   max_output    : límite de tokens de salida del servicio (None = sin límite propio)
#   model_prefixes: filtro de /models para mostrar solo modelos de chat (None = todos)
#   extra_headers : cabeceras adicionales que pide el servicio (opcional)
OPENAI_COMPAT_PROVIDERS: Dict[str, Dict] = {
    PROVIDER_OPENAI: {
        "label": "OpenAI (GPT)",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "models": ["gpt-5", "gpt-5-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini", "o4-mini"],
        "context": 128000,
        "max_output": None,
        "model_prefixes": ("gpt-", "o1", "o3", "o4", "chatgpt-"),
        "key_placeholder": "sk-...",
        "key_url": "https://platform.openai.com/api-keys",
    },
    PROVIDER_DEEPSEEK: {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "context": 64000,
        "max_output": 8192,
        "model_prefixes": ("deepseek-",),
        "key_placeholder": "sk-...",
        "key_url": "https://platform.deepseek.com/api_keys",
    },
    PROVIDER_GEMINI: {
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-2.5-flash",
        "models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"],
        "context": 200000,
        "max_output": None,
        "model_prefixes": ("gemini-",),
        "key_placeholder": "AIza...",
        "key_url": "https://aistudio.google.com/apikey",
    },
    PROVIDER_OPENROUTER: {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "openrouter/auto",
        "models": [
            "openrouter/auto",
            "anthropic/claude-sonnet-4.5",
            "openai/gpt-4o-mini",
            "google/gemini-2.5-flash",
            "deepseek/deepseek-chat",
            "meta-llama/llama-3.3-70b-instruct",
        ],
        "context": 128000,
        "max_output": None,
        "model_prefixes": None,
        "key_placeholder": "sk-or-...",
        "key_url": "https://openrouter.ai/settings/keys",
        # Identificación opcional de la app en las estadísticas de OpenRouter
        "extra_headers": {"HTTP-Referer": "https://katphi.com", "X-Title": "Katphi Browser"},
    },
    PROVIDER_GROQ: {
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "openai/gpt-oss-120b", "qwen/qwen3-32b"],
        "context": 128000,
        "max_output": 32768,
        "model_prefixes": None,
        "key_placeholder": "gsk_...",
        "key_url": "https://console.groq.com/keys",
    },
    PROVIDER_MISTRAL: {
        "label": "Mistral AI",
        "base_url": "https://api.mistral.ai/v1",
        "default_model": "mistral-small-latest",
        "models": ["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest",
                   "codestral-latest", "ministral-8b-latest"],
        "context": 128000,
        "max_output": None,
        "model_prefixes": None,
        "key_placeholder": "API key de Mistral",
        "key_url": "https://console.mistral.ai/api-keys",
    },
    PROVIDER_XAI: {
        "label": "xAI (Grok)",
        "base_url": "https://api.x.ai/v1",
        "default_model": "grok-3-mini",
        "models": ["grok-4", "grok-3", "grok-3-mini"],
        "context": 128000,
        "max_output": None,
        "model_prefixes": ("grok",),
        "key_placeholder": "xai-...",
        "key_url": "https://console.x.ai",
    },
    PROVIDER_QWEN: {
        "label": "Qwen (Alibaba Cloud)",
        # Endpoint internacional; las keys de la región China usan dashscope.aliyuncs.com
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "models": ["qwen-max", "qwen-plus", "qwen-turbo", "qwen3-coder-plus"],
        "context": 128000,
        "max_output": 8192,
        "model_prefixes": ("qwen",),
        "key_placeholder": "sk-...",
        "key_url": "https://modelstudio.console.alibabacloud.com/?tab=playground#/api-key",
    },
}

# Modelos de razonamiento de OpenAI: no aceptan temperature distinta de 1
_OPENAI_REASONING_PREFIXES = ("o1", "o3", "o4", "gpt-5")
# Modelos que /models devuelve pero no sirven para chat
_NON_CHAT_MODEL_MARKERS = (
    "audio", "realtime", "tts", "transcribe", "image", "embed", "search", "moderation",
    "whisper", "guard", "ocr", "asr",
)

# Modelos gratuitos disponibles en llmapi.ai (para mostrar en la UI)
LLMAPI_FREE_MODELS = [
    "zai/glm-4.5-flash",
    "gpt-4o-mini",
    "gemini-1.5-flash",
    "gemini-2.0-flash",
    "claude-haiku-4-5",
    "llama-3.3-70b-instruct",
    "mistral-small-latest",
    "deepseek-chat",
]


# ─── Configuración ──────────────────────────────────────────────────────────────

@dataclass
class LLMConfig:
    """Configuración de un proveedor LLM. Se serializa/deserializa con QSettings."""
    provider: str = PROVIDER_LOCAL
    local_url: str = "http://localhost:1234"
    llmapi_key: str = ""
    llmapi_model: str = "gpt-4o-mini"
    anthropic_key: str = ""
    anthropic_model: str = ANTHROPIC_DEFAULT_MODEL
    huggingface_key: str = ""
    huggingface_model: str = HUGGINGFACE_DEFAULT_MODEL
    ollama_url: str = OLLAMA_DEFAULT_URL
    ollama_model: str = ""   # vacío = primer modelo instalado
    # API key y modelo de cada proveedor de OPENAI_COMPAT_PROVIDERS, por id
    compat_keys: Dict[str, str] = field(default_factory=dict)
    compat_models: Dict[str, str] = field(default_factory=dict)
    temperature: float = 0.7
    max_tokens: int = 4000

    def compat_key(self, provider: str) -> str:
        return self.compat_keys.get(provider, "")
    def compat_model(self, provider: str) -> str:
        return (self.compat_models.get(provider)
                or OPENAI_COMPAT_PROVIDERS[provider]["default_model"])
    # ── Persistencia ─────────────────────────────────────────────────────────

    def save(self, namespace: str = "LLMClient"):
        s = QSettings("Katphi", namespace)
        s.setValue("provider", self.provider)
        s.setValue("local_url", self.local_url)
        s.setValue("llmapi_key", self.llmapi_key)
        s.setValue("llmapi_model", self.llmapi_model)
        s.setValue("anthropic_key", self.anthropic_key)
        s.setValue("anthropic_model", self.anthropic_model)
        s.setValue("huggingface_key", self.huggingface_key)
        s.setValue("huggingface_model", self.huggingface_model)
        s.setValue("ollama_url", self.ollama_url)
        s.setValue("ollama_model", self.ollama_model)
        for pid in OPENAI_COMPAT_PROVIDERS:
            s.setValue(f"{pid}_key", self.compat_keys.get(pid, ""))
            s.setValue(f"{pid}_model", self.compat_models.get(pid, ""))
        s.setValue("temperature", self.temperature)
        s.setValue("max_tokens", self.max_tokens)
    @classmethod
    def load(cls, namespace: str = "LLMClient") -> "LLMConfig":
        s = QSettings("Katphi", namespace)
        cfg = cls()
        cfg.provider = str(s.value("provider", PROVIDER_LOCAL))
        cfg.local_url = str(s.value("local_url", "http://localhost:1234"))
        cfg.llmapi_key = str(s.value("llmapi_key", ""))
        cfg.llmapi_model = str(s.value("llmapi_model", "gpt-4o-mini"))
        cfg.anthropic_key = str(s.value("anthropic_key", ""))
        cfg.anthropic_model = str(s.value("anthropic_model", ANTHROPIC_DEFAULT_MODEL))
        if cfg.anthropic_model in _ANTHROPIC_INVALID_LEGACY_MODELS or not cfg.anthropic_model:
            cfg.anthropic_model = ANTHROPIC_DEFAULT_MODEL
        cfg.huggingface_key = str(s.value("huggingface_key", ""))
        cfg.huggingface_model = str(s.value("huggingface_model", HUGGINGFACE_DEFAULT_MODEL))
        cfg.ollama_url = str(s.value("ollama_url", OLLAMA_DEFAULT_URL))
        cfg.ollama_model = str(s.value("ollama_model", ""))
        for pid in OPENAI_COMPAT_PROVIDERS:
            cfg.compat_keys[pid] = str(s.value(f"{pid}_key", "") or "")
            cfg.compat_models[pid] = str(s.value(f"{pid}_model", "") or "")
        try:
            cfg.temperature = float(s.value("temperature", 0.7))
        except (TypeError, ValueError):
            cfg.temperature = 0.7
        try:
            cfg.max_tokens = int(s.value("max_tokens", 4000))
        except (TypeError, ValueError):
            cfg.max_tokens = 4000
        return cfg


# ─── Cliente ────────────────────────────────────────────────────────────────────

class LLMClient:
    """
    Cliente unificado. Expone:
      chat(messages, max_tokens?, temperature?) -> str   (contenido del mensaje)
      test() -> (ok: bool, info: str)
      list_models() -> [str]
    """

    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()
        # Session reutilizable para connection pooling (reduce latencia TCP)
        self._session = requests.Session()
        # Caché del modelo local detectado (evita llamadas GET repetidas)
        self._cached_model_id: Optional[str] = None
        # Caché de num_ctx de Ollama (evita /api/show en cada petición)
        self._ollama_num_ctx: Optional[int] = None
    # ── API pública ───────────────────────────────────────────────────────────

    def chat(
        self,
        messages: List[Dict],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """
        Envía mensajes al LLM y devuelve el texto de la respuesta.
        Si max_tokens es None el servidor decide el límite (sin restricción desde el cliente).
        Lanza LLMError si algo falla.
        """
        temp = temperature if temperature is not None else self.config.temperature

        if self.config.provider == PROVIDER_ANTHROPIC:
            return self._chat_anthropic(messages, max_tokens, temp)
        if self.config.provider == PROVIDER_LLMAPI:
            return self._chat_llmapi(messages, max_tokens, temp)
        if self.config.provider == PROVIDER_HUGGINGFACE:
            return self._chat_huggingface(messages, max_tokens, temp)
        if self.config.provider == PROVIDER_OLLAMA:
            return self._chat_ollama(messages, max_tokens, temp)
        if self.config.provider in OPENAI_COMPAT_PROVIDERS:
            return self._chat_compat(messages, max_tokens, temp)
        return self._chat_local(messages, max_tokens, temp)
    def chat_stream(
        self,
        messages: List[Dict],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Iterator[str]:
        """
        Genera la respuesta del LLM como un iterador de fragmentos de texto (SSE).
        Compatible con el formato OpenAI Server-Sent Events.
        """
        temp = temperature if temperature is not None else self.config.temperature

        if self.config.provider == PROVIDER_ANTHROPIC:
            yield from self._stream_anthropic(messages, max_tokens, temp)
            return
        if self.config.provider == PROVIDER_HUGGINGFACE:
            yield from self._stream_huggingface(messages, max_tokens, temp)
            return
        if self.config.provider == PROVIDER_OLLAMA:
            yield from self._stream_ollama(messages, max_tokens, temp)
            return
        if self.config.provider in OPENAI_COMPAT_PROVIDERS:
            yield from self._stream_compat(messages, max_tokens, temp)
            return
        payload: Dict = {
            "messages": messages,
            "temperature": temp,
            "stream": True,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if self.config.provider == PROVIDER_LLMAPI:
            if not self.config.llmapi_key:
                raise LLMError("API key de llmapi.ai no configurada")
            url = f"{LLMAPI_BASE_URL}/v1/chat/completions"
            payload["model"] = self.config.llmapi_model
            headers = self.get_headers()
        else:
            url = f"{self.config.local_url.rstrip('/')}/v1/chat/completions"
            model_id = self._detect_local_model()
            if model_id:
                payload["model"] = model_id
            headers = self.get_headers()
        resp = self._session.post(url, json=payload, headers=headers,
                                  stream=True, timeout=180)
        if resp.status_code != 200:
            raise LLMError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        for raw_line in resp.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            if not line.startswith("data: "):
                continue
            data = line[6:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
                delta = obj["choices"][0]["delta"].get("content", "")
                if delta:
                    yield delta
            except (json.JSONDecodeError, KeyError, IndexError):
                continue
    def test(self) -> tuple:
        """Prueba la conexión. Devuelve (ok: bool, mensaje: str)."""
        try:
            if self.config.provider == PROVIDER_ANTHROPIC:
                return self._test_anthropic()
            if self.config.provider == PROVIDER_LLMAPI:
                return self._test_llmapi()
            if self.config.provider == PROVIDER_HUGGINGFACE:
                return self._test_huggingface()
            if self.config.provider == PROVIDER_OLLAMA:
                return self._test_ollama()
            if self.config.provider in OPENAI_COMPAT_PROVIDERS:
                return self._test_compat()
            return self._test_local()
        except Exception as e:
            return False, str(e)
    def list_models(self) -> List[str]:
        """Lista modelos disponibles (solo para el proveedor activo)."""
        try:
            if self.config.provider == PROVIDER_ANTHROPIC:
                return self._list_models_anthropic()
            if self.config.provider == PROVIDER_LLMAPI:
                return LLMAPI_FREE_MODELS
            if self.config.provider == PROVIDER_HUGGINGFACE:
                return HUGGINGFACE_MODELS
            if self.config.provider == PROVIDER_OLLAMA:
                return self._list_models_ollama()
            if self.config.provider in OPENAI_COMPAT_PROVIDERS:
                return self._list_models_compat()
            return self._list_models_local()
        except Exception:
            return []
    def get_base_url(self) -> str:
        if self.config.provider == PROVIDER_ANTHROPIC:
            return ANTHROPIC_BASE_URL
        if self.config.provider == PROVIDER_LLMAPI:
            return LLMAPI_BASE_URL
        if self.config.provider == PROVIDER_HUGGINGFACE:
            return HUGGINGFACE_ROUTER_URL
        if self.config.provider == PROVIDER_OLLAMA:
            return self._ollama_base()
        if self.config.provider in OPENAI_COMPAT_PROVIDERS:
            return OPENAI_COMPAT_PROVIDERS[self.config.provider]["base_url"]
        return self.config.local_url.rstrip("/")
    def get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.provider == PROVIDER_ANTHROPIC and self.config.anthropic_key:
            headers["x-api-key"] = self.config.anthropic_key
            headers["anthropic-version"] = ANTHROPIC_API_VERSION
        elif self.config.provider == PROVIDER_LLMAPI and self.config.llmapi_key:
            headers["Authorization"] = f"Bearer {self.config.llmapi_key}"
        elif self.config.provider == PROVIDER_HUGGINGFACE and self.config.huggingface_key:
            headers["Authorization"] = f"Bearer {self.config.huggingface_key}"
        elif self.config.provider in OPENAI_COMPAT_PROVIDERS and self.config.compat_key(self.config.provider):
            headers["Authorization"] = f"Bearer {self.config.compat_key(self.config.provider)}"
            headers.update(OPENAI_COMPAT_PROVIDERS[self.config.provider].get("extra_headers", {}))
        return headers
    # ── Implementaciones locales ──────────────────────────────────────────────

    def _chat_local(self, messages, max_tokens, temperature) -> str:
        url = f"{self.config.local_url.rstrip('/')}/v1/chat/completions"
        model_id = self._detect_local_model()
        payload: Dict = {
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if model_id:
            payload["model"] = model_id
        resp = self._session.post(url, json=payload, headers=self.get_headers(), timeout=120)
        return self._parse_response(resp)
    def _test_local(self) -> tuple:
        url = f"{self.config.local_url.rstrip('/')}/v1/models"
        resp = self._session.get(url, timeout=8)
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}"
        models = resp.json().get("data", [])
        if not models:
            return False, "Servidor responde pero sin modelos cargados"
        return True, f"Conectado — modelo: {models[0].get('id', '?')}"
    def _list_models_local(self) -> List[str]:
        url = f"{self.config.local_url.rstrip('/')}/v1/models"
        resp = self._session.get(url, timeout=8)
        if resp.status_code != 200:
            return []
        return [m.get("id", "") for m in resp.json().get("data", []) if m.get("id")]
    def _detect_local_model(self) -> str:
        """Devuelve el primer modelo disponible, usando caché para evitar GETs repetidos."""
        if self._cached_model_id is not None:
            return self._cached_model_id
        try:
            url = f"{self.config.local_url.rstrip('/')}/v1/models"
            resp = self._session.get(url, timeout=6)
            if resp.status_code == 200:
                models = resp.json().get("data", [])
                if models:
                    self._cached_model_id = models[0].get("id", "")
                    return self._cached_model_id
        except Exception:
            pass
        self._cached_model_id = ""
        return ""
    def detect_context_window(self) -> int:
        """Detecta ventana de contexto del modelo local; fallback seguro 4096."""
        if self.config.provider == PROVIDER_ANTHROPIC:
            return 200000  # Todos los modelos Claude tienen 200k ctx
        if self.config.provider == PROVIDER_LLMAPI:
            return 32000  # los modelos cloud tienen contexto amplio
        if self.config.provider == PROVIDER_HUGGINGFACE:
            return 32000  # ventana conservadora para modelos HuggingFace
        if self.config.provider == PROVIDER_OLLAMA:
            return self._ollama_context_window()
        if self.config.provider in OPENAI_COMPAT_PROVIDERS:
            return OPENAI_COMPAT_PROVIDERS[self.config.provider]["context"]
        try:
            url = f"{self.config.local_url.rstrip('/')}/v1/models"
            resp = self._session.get(url, timeout=6)
            if resp.status_code != 200:
                return 4096
            models = resp.json().get("data", [])
            if not models:
                return 4096
            first = models[0] if isinstance(models[0], dict) else {}
            # Guardar el modelo en caché de paso
            if not self._cached_model_id and first.get("id"):
                self._cached_model_id = first["id"]
            for key in ("context_length", "n_ctx", "max_context_length", "num_ctx"):
                val = first.get(key)
                if isinstance(val, int) and val >= 1024:
                    return val
                if isinstance(val, str) and val.isdigit() and int(val) >= 1024:
                    return int(val)
        except Exception:
            pass
        return 4096
    # ── Implementaciones llmapi.ai ────────────────────────────────────────────

    def _chat_llmapi(self, messages, max_tokens, temperature) -> str:
        if not self.config.llmapi_key:
            raise LLMError("API key de llmapi.ai no configurada")
        url = f"{LLMAPI_BASE_URL}/v1/chat/completions"
        payload = {
            "model": self.config.llmapi_model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        resp = self._session.post(url, json=payload, headers=self.get_headers(), timeout=120)
        return self._parse_response(resp)
    def _test_llmapi(self) -> tuple:
        if not self.config.llmapi_key:
            return False, "API key vacía — introduce tu clave de llmapi.ai"
        resp = self._session.post(
            f"{LLMAPI_BASE_URL}/v1/chat/completions",
            json={
                "model": self.config.llmapi_model,
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 10,
                "stream": False,
            },
            headers=self.get_headers(),
            timeout=20,
        )
        if resp.status_code == 200:
            return True, f"Conectado a llmapi.ai — modelo: {self.config.llmapi_model}"
        try:
            err = resp.json().get("error", {}).get("message", resp.text[:200])
        except Exception:
            err = resp.text[:200]
        return False, f"HTTP {resp.status_code}: {err}"
    # ── Implementaciones Anthropic ────────────────────────────────────────────

    def _build_anthropic_payload(
        self,
        messages: List[Dict],
        max_tokens: Optional[int],
        temperature: float,
        stream: bool = False,
    ) -> Dict:
        """
        Convierte el formato OpenAI de mensajes al formato nativo de Anthropic.
        - El mensaje system se extrae y va en el campo 'system' de top-level.
        - Los mensajes user/assistant van en 'messages'.
        """
        system_prompt = ""
        anthropic_messages = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                system_prompt = content
            elif role in ("user", "assistant"):
                anthropic_messages.append({"role": role, "content": content})
        payload: Dict = {
            "model": self.config.anthropic_model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens if max_tokens is not None else self.config.max_tokens,
            "stream": stream,
        }
        if not self.config.anthropic_model.startswith(_ANTHROPIC_NO_SAMPLING_PREFIXES):
            payload["temperature"] = temperature
        if system_prompt:
            payload["system"] = system_prompt
        return payload
    def _chat_anthropic(self, messages: List[Dict], max_tokens: Optional[int], temperature: float) -> str:
        """Llamada síncrona a la API de Anthropic."""
        if not self.config.anthropic_key:
            raise LLMError("API key de Anthropic no configurada")
        url = f"{ANTHROPIC_BASE_URL}/v1/messages"
        payload = self._build_anthropic_payload(messages, max_tokens, temperature, stream=False)

        resp = self._session.post(url, json=payload, headers=self.get_headers(), timeout=120)

        if resp.status_code != 200:
            detail = ""
            try:
                err = resp.json()
                detail = err.get("error", {}).get("message", resp.text[:400])
            except Exception:
                detail = resp.text[:400]
            raise LLMError(f"Anthropic API error {resp.status_code}: {detail}")
        data = resp.json()
        if data.get("stop_reason") == "refusal":
            raise LLMError(self._anthropic_refusal_message(data.get("stop_details")))
        content_blocks = data.get("content", [])
        if not content_blocks:
            raise LLMError("Respuesta vacía de Anthropic")
        return "".join(block.get("text", "") for block in content_blocks if block.get("type") == "text")
    def _stream_anthropic(
        self,
        messages: List[Dict],
        max_tokens: Optional[int],
        temperature: float,
    ) -> Iterator[str]:
        """
        Streaming nativo SSE de Anthropic.
        Eventos relevantes:
          - content_block_delta → delta.type == "text_delta" → delta.text
          - message_stop        → fin de stream
        """
        if not self.config.anthropic_key:
            raise LLMError("API key de Anthropic no configurada")
        url = f"{ANTHROPIC_BASE_URL}/v1/messages"
        payload = self._build_anthropic_payload(messages, max_tokens, temperature, stream=True)

        resp = self._session.post(
            url, json=payload, headers=self.get_headers(),
            stream=True, timeout=180,
        )

        if resp.status_code != 200:
            detail = ""
            try:
                detail = resp.json().get("error", {}).get("message", resp.text[:200])
            except Exception:
                detail = resp.text[:200]
            raise LLMError(f"Anthropic stream error {resp.status_code}: {detail}")
        current_event = None
        for raw_line in resp.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line

            if line.startswith("event: "):
                current_event = line[7:].strip()
                continue
            if line.startswith("data: "):
                data_str = line[6:].strip()
                if data_str == "[DONE]" or current_event == "message_stop":
                    break
                if current_event == "message_delta":
                    try:
                        delta = json.loads(data_str).get("delta", {})
                    except json.JSONDecodeError:
                        continue
                    if delta.get("stop_reason") == "refusal":
                        raise LLMError(self._anthropic_refusal_message(delta.get("stop_details")))
                    continue
                if current_event == "error":
                    try:
                        err = json.loads(data_str).get("error", {}).get("message", data_str)
                    except json.JSONDecodeError:
                        err = data_str
                    raise LLMError(f"Anthropic stream error: {err}")
                if current_event != "content_block_delta":
                    continue
                try:
                    obj = json.loads(data_str)
                    delta = obj.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            yield text
                except (json.JSONDecodeError, KeyError):
                    continue
    @staticmethod
    def _anthropic_refusal_message(stop_details) -> str:
        explanation = (stop_details or {}).get("explanation") if isinstance(stop_details, dict) else None
        return "Claude ha rechazado responder a esta petición" + (f": {explanation}" if explanation else ".")
    def _list_models_anthropic(self) -> List[str]:
        """Modelos disponibles para la API key (GET /v1/models); sin key, la lista sugerida."""
        if not self.config.anthropic_key:
            return ANTHROPIC_MODELS
        resp = self._session.get(
            f"{ANTHROPIC_BASE_URL}/v1/models", params={"limit": 1000},
            headers=self.get_headers(), timeout=15,
        )
        if resp.status_code != 200:
            raise LLMError(f"Anthropic HTTP {resp.status_code}: {resp.text[:200]}")
        return [m["id"] for m in resp.json().get("data", []) if m.get("id")]
    def _test_anthropic(self) -> tuple:
        """Valida API key y modelo con GET /v1/models/{id} (no consume tokens)."""
        if not self.config.anthropic_key:
            return False, "API key de Anthropic vacía — introduce tu clave sk-ant-..."
        try:
            url = f"{ANTHROPIC_BASE_URL}/v1/models/{self.config.anthropic_model}"
            resp = self._session.get(url, headers=self.get_headers(), timeout=20)
            if resp.status_code == 200:
                return True, f"Conectado a Anthropic — modelo: {self.config.anthropic_model}"
            if resp.status_code == 401:
                return False, "Anthropic: API key no válida (HTTP 401)"
            if resp.status_code == 404:
                return False, (f"API key válida, pero el modelo '{self.config.anthropic_model}' "
                               "no existe o no está disponible para tu cuenta")
            err = ""
            try:
                err = resp.json().get("error", {}).get("message", resp.text[:200])
            except Exception:
                err = resp.text[:200]
            return False, f"HTTP {resp.status_code}: {err}"
        except requests.exceptions.ConnectionError:
            return False, "Sin conexión a api.anthropic.com — verifica tu red"
        except requests.exceptions.Timeout:
            return False, "Timeout — la API de Anthropic no respondió en 20s"
        except Exception as e:
            return False, str(e)
    # ── Implementaciones HuggingFace ──────────────────────────────────────────

    def _chat_huggingface(self, messages: List[Dict], max_tokens: Optional[int], temperature: float) -> str:
        """
        Llamada síncrona al endpoint OpenAI-compatible de HuggingFace Inference API.
        Usa el router serverless de HuggingFace que admite el formato messages estándar.
        """
        if not self.config.huggingface_key:
            raise LLMError("API key de HuggingFace no configurada")
        payload: Dict = {
            "model": self.config.huggingface_model,
            "messages": messages,
            "temperature": max(0.01, temperature),  # HF no acepta temperature=0
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        resp = self._session.post(
            HUGGINGFACE_ROUTER_URL,
            json=payload,
            headers=self.get_headers(),
            timeout=120,
        )
        return self._parse_response(resp)
    def _stream_huggingface(
        self,
        messages: List[Dict],
        max_tokens: Optional[int],
        temperature: float,
    ) -> Iterator[str]:
        """
        Streaming SSE desde HuggingFace Inference Router (formato OpenAI-compatible).
        """
        if not self.config.huggingface_key:
            raise LLMError("API key de HuggingFace no configurada")
        payload: Dict = {
            "model": self.config.huggingface_model,
            "messages": messages,
            "temperature": max(0.01, temperature),
            "stream": True,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        resp = self._session.post(
            HUGGINGFACE_ROUTER_URL,
            json=payload,
            headers=self.get_headers(),
            stream=True,
            timeout=180,
        )
        if resp.status_code != 200:
            raise LLMError(f"HuggingFace HTTP {resp.status_code}: {resp.text[:200]}")
        for raw_line in resp.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            if not line.startswith("data: "):
                continue
            data = line[6:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
                delta = obj["choices"][0]["delta"].get("content", "")
                if delta:
                    yield delta
            except (json.JSONDecodeError, KeyError, IndexError):
                continue
    def _test_huggingface(self) -> tuple:
        """Prueba la conexión con HuggingFace enviando un mensaje mínimo."""
        if not self.config.huggingface_key:
            return False, "API key vacía — introduce tu token HuggingFace (hf_...)"
        try:
            resp = self._session.post(
                HUGGINGFACE_ROUTER_URL,
                json={
                    "model": self.config.huggingface_model,
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 10,
                    "stream": False,
                },
                headers=self.get_headers(),
                timeout=25,
            )
            if resp.status_code == 200:
                return True, f"Conectado a HuggingFace — modelo: {self.config.huggingface_model}"
            try:
                err_body = resp.json()
                err = err_body.get("error", resp.text[:200])
                if isinstance(err, dict):
                    err = err.get("message", str(err))
            except Exception:
                err = resp.text[:200]
            return False, f"HTTP {resp.status_code}: {err}"
        except requests.exceptions.ConnectionError:
            return False, "Sin conexión a router.huggingface.co — verifica tu red"
        except requests.exceptions.Timeout:
            return False, "Timeout — HuggingFace no respondió en 25s (modelo frío)"
        except Exception as e:
            return False, str(e)
    # ── Implementaciones cloud OpenAI-compatible (OpenAI, DeepSeek...) ────────

    def _compat_spec(self) -> Dict:
        return OPENAI_COMPAT_PROVIDERS[self.config.provider]
    def _compat_require_key(self) -> str:
        key = self.config.compat_key(self.config.provider)
        if not key:
            raise LLMError(f"API key de {self._compat_spec()['label']} no configurada")
        return key
    def _build_compat_payload(self, messages, max_tokens, temperature, stream: bool) -> Dict:
        spec = self._compat_spec()
        model = self.config.compat_model(self.config.provider)
        payload: Dict = {"model": model, "messages": messages, "stream": stream}
        is_openai = self.config.provider == PROVIDER_OPENAI
        if not (is_openai and model.startswith(_OPENAI_REASONING_PREFIXES)):
            payload["temperature"] = temperature
        if max_tokens is not None:
            if spec["max_output"]:
                max_tokens = min(max_tokens, spec["max_output"])
            # OpenAI ha sustituido max_tokens por max_completion_tokens (obligatorio en o*/gpt-5)
            payload["max_completion_tokens" if is_openai else "max_tokens"] = max_tokens
        return payload
    def _compat_error(self, resp: requests.Response) -> str:
        label = self._compat_spec()["label"]
        if resp.status_code == 401:
            return f"{label}: API key no válida (HTTP 401)"
        if resp.status_code == 402:
            return f"{label}: saldo insuficiente en la cuenta (HTTP 402)"
        if resp.status_code == 429:
            return f"{label}: límite de uso o de cuota alcanzado (HTTP 429)"
        try:
            err = resp.json().get("error", {})
            detail = err.get("message", "") if isinstance(err, dict) else str(err)
        except ValueError:
            detail = ""
        return f"{label} HTTP {resp.status_code}: {detail or resp.text[:300]}"
    def _chat_compat(self, messages, max_tokens, temperature) -> str:
        self._compat_require_key()
        payload = self._build_compat_payload(messages, max_tokens, temperature, stream=False)
        resp = self._session.post(
            f"{self._compat_spec()['base_url']}/chat/completions",
            json=payload, headers=self.get_headers(), timeout=180,
        )
        if resp.status_code != 200:
            raise LLMError(self._compat_error(resp))
        return self._parse_response(resp)
    def _stream_compat(self, messages, max_tokens, temperature) -> Iterator[str]:
        self._compat_require_key()
        payload = self._build_compat_payload(messages, max_tokens, temperature, stream=True)
        resp = self._session.post(
            f"{self._compat_spec()['base_url']}/chat/completions",
            json=payload, headers=self.get_headers(), stream=True, timeout=180,
        )
        if resp.status_code != 200:
            raise LLMError(self._compat_error(resp))
        for raw_line in resp.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            if not line.startswith("data: "):
                continue
            data = line[6:].strip()
            if data == "[DONE]":
                break
            try:
                choices = json.loads(data).get("choices") or []
                # DeepSeek-reasoner envía también reasoning_content: solo se muestra content
                delta = choices[0].get("delta", {}).get("content") if choices else None
                if delta:
                    yield delta
            except (json.JSONDecodeError, AttributeError, IndexError):
                continue
    def _list_models_compat(self) -> List[str]:
        spec = self._compat_spec()
        self._compat_require_key()
        resp = self._session.get(f"{spec['base_url']}/models", headers=self.get_headers(), timeout=15)
        if resp.status_code != 200:
            raise LLMError(self._compat_error(resp))
        # Gemini devuelve los ids como "models/gemini-..." pero los acepta sin prefijo
        ids = [m.get("id", "").removeprefix("models/") for m in resp.json().get("data", [])]
        prefixes = spec["model_prefixes"]
        return sorted(
            i for i in ids
            if i and (prefixes is None or i.startswith(prefixes))
            and not any(mark in i.lower() for mark in _NON_CHAT_MODEL_MARKERS)
        )
    def _test_compat(self) -> tuple:
        """Valida la API key consultando /models (no consume tokens)."""
        spec = self._compat_spec()
        if not self.config.compat_key(self.config.provider):
            return False, f"API key vacía — introduce tu clave de {spec['label']}"
        try:
            try:
                models = self._list_models_compat()
            except LLMError as e:
                # Algunos servicios no exponen /models: se valida con un mensaje mínimo
                if "HTTP 404" not in str(e) and "HTTP 405" not in str(e):
                    raise
                self._chat_compat([{"role": "user", "content": "Hi"}], 5, 0.0)
                models = []
        except requests.exceptions.ConnectionError:
            return False, f"Sin conexión a {spec['base_url']} — verifica tu red"
        except requests.exceptions.Timeout:
            return False, f"Timeout — {spec['label']} no respondió"
        except LLMError as e:
            return False, str(e)
        model = self.config.compat_model(self.config.provider)
        if models and model not in models:
            return False, f"API key válida, pero el modelo '{model}' no está disponible para tu cuenta"
        return True, f"Conectado a {spec['label']} — modelo: {model}"
    # ── Implementaciones Ollama ───────────────────────────────────────────────

    def _ollama_base(self) -> str:
        return (self.config.ollama_url or OLLAMA_DEFAULT_URL).rstrip("/")
    def _list_models_ollama(self) -> List[str]:
        resp = self._session.get(f"{self._ollama_base()}/api/tags", timeout=8)
        if resp.status_code != 200:
            return []
        return [m.get("name", "") for m in resp.json().get("models", []) if m.get("name")]
    def _ollama_model(self) -> str:
        """Modelo configurado o, si está vacío, el primero instalado."""
        if self.config.ollama_model:
            return self.config.ollama_model
        if self._cached_model_id is None:
            try:
                models = self._list_models_ollama()
            except requests.exceptions.RequestException:
                models = []
            self._cached_model_id = models[0] if models else ""
        if not self._cached_model_id:
            raise LLMError(
                "Ollama no tiene modelos instalados — descarga uno con: ollama pull llama3.2"
            )
        return self._cached_model_id
    def _ollama_context_window(self) -> int:
        """num_ctx a usar: context_length del modelo (vía /api/show), limitado a OLLAMA_MAX_NUM_CTX."""
        if self._ollama_num_ctx is not None:
            return self._ollama_num_ctx
        num_ctx = OLLAMA_FALLBACK_NUM_CTX
        try:
            resp = self._session.post(
                f"{self._ollama_base()}/api/show",
                json={"model": self._ollama_model()},
                timeout=8,
            )
            if resp.status_code == 200:
                info = resp.json().get("model_info", {}) or {}
                for key, val in info.items():
                    if key.endswith(".context_length") and isinstance(val, int) and val >= 1024:
                        num_ctx = min(val, OLLAMA_MAX_NUM_CTX)
                        break
        except (requests.exceptions.RequestException, ValueError, LLMError):
            pass
        self._ollama_num_ctx = num_ctx
        return num_ctx
    def _build_ollama_payload(self, messages, max_tokens, temperature, stream: bool) -> Dict:
        options: Dict = {
            "temperature": temperature,
            "num_ctx": self._ollama_context_window(),
        }
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        return {
            "model": self._ollama_model(),
            "messages": [
                {"role": m.get("role", "user"), "content": m.get("content", "")}
                for m in messages
            ],
            "stream": stream,
            "options": options,
        }
    @staticmethod
    def _ollama_error(resp: requests.Response) -> str:
        try:
            detail = resp.json().get("error", "") or resp.text[:300]
        except ValueError:
            detail = resp.text[:300]
        return f"Ollama HTTP {resp.status_code}: {detail}"
    def _chat_ollama(self, messages, max_tokens, temperature) -> str:
        payload = self._build_ollama_payload(messages, max_tokens, temperature, stream=False)
        # Timeout amplio: la primera petición carga el modelo en memoria
        resp = self._session.post(f"{self._ollama_base()}/api/chat", json=payload, timeout=300)
        if resp.status_code != 200:
            raise LLMError(self._ollama_error(resp))
        content = resp.json().get("message", {}).get("content", "")
        if not content:
            raise LLMError("Respuesta vacía de Ollama")
        return content
    def _stream_ollama(self, messages, max_tokens, temperature) -> Iterator[str]:
        """Streaming NDJSON de Ollama: una línea JSON por fragmento, la última con done=true."""
        payload = self._build_ollama_payload(messages, max_tokens, temperature, stream=True)
        resp = self._session.post(
            f"{self._ollama_base()}/api/chat", json=payload, stream=True, timeout=300,
        )
        if resp.status_code != 200:
            raise LLMError(self._ollama_error(resp))
        for raw_line in resp.iter_lines():
            if not raw_line:
                continue
            try:
                obj = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if obj.get("error"):
                raise LLMError(f"Ollama: {obj['error']}")
            text = obj.get("message", {}).get("content", "")
            if text:
                yield text
            if obj.get("done"):
                break
    def _test_ollama(self) -> tuple:
        base = self._ollama_base()
        try:
            models = self._list_models_ollama()
        except requests.exceptions.ConnectionError:
            return False, f"Sin conexión a {base} — ¿está Ollama ejecutándose? (ollama serve)"
        except requests.exceptions.Timeout:
            return False, f"Timeout — Ollama no respondió en {base}"
        if not models:
            return False, "Ollama responde pero no hay modelos instalados (ollama pull llama3.2)"
        model = self.config.ollama_model
        if model and model not in models and f"{model}:latest" not in models:
            return False, f"El modelo '{model}' no está instalado en Ollama. Disponibles: {', '.join(models[:5])}"
        return True, f"Conectado a Ollama — modelo: {model or models[0]}"
    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_response(resp: requests.Response) -> str:
        if resp.status_code != 200:
            detail = ""
            try:
                detail = resp.json().get("error", {}).get("message", "")
            except Exception:
                detail = resp.text[:400]
            raise LLMError(f"Error del servidor: {resp.status_code}" + (f" — {detail}" if detail else ""))
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise LLMError("Respuesta vacía del servidor")
        return choices[0]["message"]["content"]


class LLMError(Exception):
    """Error en la comunicación con el LLM."""
