"""LLM providers. Embedded llama.cpp is the default: no install, no paid API, nothing leaves the computer."""
from __future__ import annotations

import hashlib
import json
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import httpx

from . import embedded
from .settings import get_secret, load_config

Message = dict[str, str]


class LLMUnavailable(RuntimeError):
    """Its text reaches the UI and the logs, so it never carries keys (e.g. an API key in a failed URL)."""

    def __init__(self, message: str = ""):
        from .security import mask_secrets

        super().__init__(mask_secrets(str(message)))


class LLMProvider(ABC):
    name = "base"

    def __init__(self, model: str = "", embedding_model: str = "", temperature: float = 0.2):
        self.model = model
        self.embedding_model = embedding_model
        self.temperature = temperature

    @abstractmethod
    def status(self) -> dict[str, Any]: ...

    @abstractmethod
    def list_models(self) -> list[str]: ...

    @abstractmethod
    def chat(self, messages: list[Message], json_mode: bool = False) -> str: ...

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        return None

    def chat_json(self, messages: list[Message]) -> dict[str, Any]:
        raw = self.chat(messages, json_mode=True)
        return parse_json_loose(raw)


def parse_json_loose(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {"items": data}
    except ValueError:
        match = re.search(r"\{.*\}", raw, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except ValueError:
                pass
    return {}


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, base_url: str = "http://127.0.0.1:11434", **kw):
        super().__init__(**kw)
        self.base_url = base_url.rstrip("/")

    def list_models(self) -> list[str]:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=3)
            r.raise_for_status()
            return [m.get("name", "") for m in r.json().get("models", [])]
        except Exception:
            return []

    def status(self) -> dict[str, Any]:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=3)
            r.raise_for_status()
            models = [m.get("name", "") for m in r.json().get("models", [])]
            return {"online": True, "provider": self.name, "models": models, "model": self.resolved_model(models),
                    "embedding_model": self.embedding_model if self._has(models, self.embedding_model) else ""}
        except Exception as exc:
            return {"online": False, "provider": self.name, "models": [], "model": self.model, "error": str(exc)}

    @staticmethod
    def _has(models: list[str], name: str) -> bool:
        return bool(name) and any(m == name or m.split(":")[0] == name.split(":")[0] for m in models)

    def resolved_model(self, models: list[str] | None = None) -> str:
        models = self.list_models() if models is None else models
        if self.model and self._has(models, self.model):
            return self.model
        chat_models = [m for m in models if "embed" not in m]
        return chat_models[0] if chat_models else self.model

    def chat(self, messages: list[Message], json_mode: bool = False) -> str:
        model = self.resolved_model()
        if not model:
            raise LLMUnavailable("Nenhum modelo Ollama instalado. Execute: ollama pull qwen2.5:7b")
        payload: dict[str, Any] = {"model": model, "stream": False, "messages": messages,
                                   "options": {"temperature": self.temperature}}
        if json_mode:
            payload["format"] = "json"
        try:
            r = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=300)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"Ollama indisponível: {exc}") from exc
        return r.json()["message"]["content"]

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        if not self.embedding_model:
            return None
        try:
            r = httpx.post(f"{self.base_url}/api/embed", json={"model": self.embedding_model, "input": texts}, timeout=300)
            r.raise_for_status()
            return r.json().get("embeddings")
        except Exception:
            return None


class OpenAICompatibleProvider(LLMProvider):
    name = "openai_compatible"
    secret_name = "openai_api_key"

    def __init__(self, base_url: str, api_key: str = "", **kw):
        super().__init__(**kw)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def list_models(self) -> list[str]:
        try:
            r = httpx.get(f"{self.base_url}/models", headers=self._headers(), timeout=10)
            r.raise_for_status()
            return sorted(m["id"] for m in r.json().get("data", []))
        except Exception:
            return []

    def status(self) -> dict[str, Any]:
        models = self.list_models()
        return {"online": bool(models) or bool(self.api_key and self.model), "provider": self.name,
                "models": models, "model": self.model, "embedding_model": self.embedding_model}

    def chat(self, messages: list[Message], json_mode: bool = False) -> str:
        if not self.model:
            raise LLMUnavailable("Modelo não configurado.")
        payload: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": self.temperature}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            r = httpx.post(f"{self.base_url}/chat/completions", json=payload, headers=self._headers(), timeout=300)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"Provedor indisponível: {exc}") from exc
        return r.json()["choices"][0]["message"]["content"]

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        if not self.embedding_model:
            return None
        try:
            r = httpx.post(f"{self.base_url}/embeddings", json={"model": self.embedding_model, "input": texts},
                           headers=self._headers(), timeout=300)
            r.raise_for_status()
            return [d["embedding"] for d in r.json()["data"]]
        except Exception:
            return None


class GroqProvider(OpenAICompatibleProvider):
    name = "groq"
    secret_name = "groq_api_key"

    def __init__(self, api_key: str = "", **kw):
        super().__init__("https://api.groq.com/openai/v1", api_key, **kw)
        self.embedding_model = ""  # Groq has no embeddings endpoint

    def chat(self, messages: list[Message], json_mode: bool = False) -> str:
        if not self.model:  # Groq retires models often: default to its largest current chat model
            chat = [m for m in self.list_models() if not re.search(r"whisper|guard|tts|embed|orpheus", m)]
            self.model = next((m for m in chat if "70b" in m), chat[0] if chat else "")
        return super().chat(messages, json_mode)


class CustomProvider(OpenAICompatibleProvider):
    """Any OpenAI-compatible server (LM Studio, vLLM, LocalAI, servidor interno)."""

    name = "custom"
    secret_name = "custom_api_key"


def gemini_candidates(names: list[str]) -> list[str]:
    """Stable Flash models, newest first; then other Flash variants; then Google's moving alias."""
    def version(n: str) -> list[int]:
        return [int(x) for x in re.findall(r"\d+", n)]

    stable = sorted((n for n in names if re.fullmatch(r"gemini-[\d.]+-flash", n)), key=version, reverse=True)
    other = [n for n in names if "flash" in n and n not in stable and not re.search(r"lite|image|tts|live|audio", n)]
    return (stable + other)[:3] + ["gemini-flash-latest"]


def pick_gemini_model(names: list[str]) -> str:
    return gemini_candidates(names)[0]


class GeminiProvider(LLMProvider):
    name = "gemini"
    secret_name = "gemini_api_key"
    base = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, api_key: str = "", **kw):
        super().__init__(**kw)
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.api_key}  # header, not ?key=: URLs end up in error messages

    _models: tuple[float, str, list[str]] = (0.0, "", [])  # (time, key hash, names): one lookup per 10 min, not per question

    def list_models(self) -> list[str]:
        key = hashlib.sha256(self.api_key.encode()).hexdigest()
        at, cached_key, names = GeminiProvider._models
        if names and cached_key == key and time.time() - at < 600:
            return names
        try:
            r = httpx.get(f"{self.base}/models", headers=self._headers(), params={"pageSize": 1000}, timeout=10)
            r.raise_for_status()
            names = [m["name"].removeprefix("models/") for m in r.json().get("models", [])]
        except Exception:
            return []
        GeminiProvider._models = (time.time(), key, names)
        return names

    def status(self) -> dict[str, Any]:
        models = self.list_models()
        return {"online": bool(models), "provider": self.name, "models": models, "model": self.model,
                "embedding_model": self.embedding_model}

    def chat(self, messages: list[Message], json_mode: bool = False) -> str:
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                    for m in messages if m["role"] != "system"]
        body: dict[str, Any] = {"contents": contents, "generationConfig": {"temperature": self.temperature}}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"
        # Google renames models often and the free tier is often overloaded (503/429):
        # without a configured model, try the stable Flash models newest first.
        models = [self.model] if self.model else gemini_candidates(self.list_models())
        status = 0
        for model in models:
            try:
                r = httpx.post(f"{self.base}/models/{model}:generateContent", headers=self._headers(),
                               json=body, timeout=300)
            except httpx.HTTPError as exc:
                raise LLMUnavailable(f"Gemini indisponível ({type(exc).__name__}).") from exc
            status = r.status_code
            if status == 200:
                self.model = model
                cand = (r.json().get("candidates") or [{}])[0]
                text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []) if not p.get("thought"))
                if not text:  # blocked by a safety filter or cut by the token limit
                    raise LLMUnavailable(f"Gemini não gerou resposta ({cand.get('finishReason') or 'sem conteúdo'}).")
                return text
            if status not in (404, 429, 500, 503):
                break
        hint = {400: "chave ou pedido inválido", 403: "chave sem permissão", 429: "limite gratuito atingido, tente mais tarde",
                503: "serviço sobrecarregado, tente de novo em instantes"}.get(status, "erro do serviço")
        raise LLMUnavailable(f"Gemini indisponível (HTTP {status}: {hint}).")

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        if not self.embedding_model:
            return None
        model = f"models/{self.embedding_model}"
        try:
            r = httpx.post(f"{self.base}/{model}:batchEmbedContents", headers=self._headers(),
                           json={"requests": [{"model": model, "content": {"parts": [{"text": t}]}} for t in texts]},
                           timeout=300)
            r.raise_for_status()
            return [e["values"] for e in r.json()["embeddings"]]
        except Exception:
            return None


class EmbeddedProvider(OpenAICompatibleProvider):
    """The engine bundled with the app (see embedded.py); started on first use."""

    name = "embedded"

    def __init__(self, model_key: str = "", model_file: str = "", **kw):
        super().__init__("", **kw)
        self.model_key = model_key if model_key in embedded.MODELS else embedded.DEFAULT_MODEL
        self.path = Path(model_file) if model_file else embedded.model_path(self.model_key)
        self.model = self.path.name
        self.embedding_model = ""  # lexical + metadata search; no second model to download

    def _problem(self) -> str:
        if not embedded.server_binary():
            return "Motor de IA embutido não encontrado nesta instalação. Reinstale o GV Support AI."
        if not embedded.is_gguf(self.path):
            return "Modelo de IA ainda não baixado. Em Configurações > IA, clique em Baixar modelo."
        return ""

    def list_models(self) -> list[str]:
        return [self.model] if not self._problem() else []

    def status(self) -> dict[str, Any]:
        problem = self._problem()
        return {"online": not problem, "provider": self.name, "models": self.list_models(), "model": self.model,
                "embedding_model": "", "model_key": self.model_key, "model_ready": embedded.is_gguf(self.path),
                **({"error": problem} if problem else {})}

    def chat(self, messages: list[Message], json_mode: bool = False) -> str:
        if problem := self._problem():
            raise LLMUnavailable(problem)
        try:
            self.base_url, self.api_key = embedded.ensure(self.path)
        except RuntimeError as exc:
            raise LLMUnavailable(str(exc)) from exc
        return super().chat(messages, json_mode)


def get_provider(cfg: dict[str, Any] | None = None) -> LLMProvider:
    cfg = cfg or load_config()
    kw = {"model": cfg.get("llm_model", ""), "embedding_model": cfg.get("embedding_model", ""),
          "temperature": float(cfg.get("temperature", 0.2))}
    kind = cfg.get("llm_provider", "embedded")
    if kind == "embedded":
        return EmbeddedProvider(cfg.get("embedded_model", ""), cfg.get("embedded_model_path", ""), **kw)
    if kind == "openai_compatible":
        return OpenAICompatibleProvider(cfg.get("openai_base_url", ""), get_secret("openai_api_key"), **kw)
    if kind == "gemini":
        return GeminiProvider(get_secret("gemini_api_key"), **kw)
    if kind == "groq":
        return GroqProvider(get_secret("groq_api_key"), **kw)
    if kind == "custom":
        return CustomProvider(cfg.get("custom_base_url", ""), get_secret("custom_api_key"), **kw)
    return OllamaProvider(cfg.get("ollama_url", "http://127.0.0.1:11434"), **kw)
