"""LLM providers. Local-first: Ollama is the default and nothing requires a paid API."""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx

from .settings import get_secret, load_config

Message = dict[str, str]


class LLMUnavailable(RuntimeError):
    pass


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


class CustomProvider(OpenAICompatibleProvider):
    """Any OpenAI-compatible server (LM Studio, vLLM, LocalAI, servidor interno)."""

    name = "custom"
    secret_name = "custom_api_key"


class GeminiProvider(LLMProvider):
    name = "gemini"
    secret_name = "gemini_api_key"
    base = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, api_key: str = "", **kw):
        super().__init__(**kw)
        self.api_key = api_key

    def list_models(self) -> list[str]:
        try:
            r = httpx.get(f"{self.base}/models", params={"key": self.api_key}, timeout=10)
            r.raise_for_status()
            return [m["name"].removeprefix("models/") for m in r.json().get("models", [])]
        except Exception:
            return []

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
        try:
            r = httpx.post(f"{self.base}/models/{self.model}:generateContent", params={"key": self.api_key},
                           json=body, timeout=300)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"Gemini indisponível: {exc}") from exc
        parts = r.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        if not self.embedding_model:
            return None
        model = f"models/{self.embedding_model}"
        try:
            r = httpx.post(f"{self.base}/{model}:batchEmbedContents", params={"key": self.api_key},
                           json={"requests": [{"model": model, "content": {"parts": [{"text": t}]}} for t in texts]},
                           timeout=300)
            r.raise_for_status()
            return [e["values"] for e in r.json()["embeddings"]]
        except Exception:
            return None


def get_provider(cfg: dict[str, Any] | None = None) -> LLMProvider:
    cfg = cfg or load_config()
    kw = {"model": cfg.get("llm_model", ""), "embedding_model": cfg.get("embedding_model", ""),
          "temperature": float(cfg.get("temperature", 0.2))}
    kind = cfg.get("llm_provider", "ollama")
    if kind == "openai_compatible":
        return OpenAICompatibleProvider(cfg.get("openai_base_url", ""), get_secret("openai_api_key"), **kw)
    if kind == "gemini":
        return GeminiProvider(get_secret("gemini_api_key"), **kw)
    if kind == "groq":
        return GroqProvider(get_secret("groq_api_key"), **kw)
    if kind == "custom":
        return CustomProvider(cfg.get("custom_base_url", ""), get_secret("custom_api_key"), **kw)
    return OllamaProvider(cfg.get("ollama_url", "http://127.0.0.1:11434"), **kw)
