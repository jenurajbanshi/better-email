"""Concrete real LLM providers. SDKs are imported lazily so they remain
optional dependencies -- the app runs fully on the mock provider with none of
these installed.
"""
from __future__ import annotations

import httpx

from .json_provider import JSONChatProvider


class OpenAIProvider(JSONChatProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for the openai provider.")
        self.model = model
        self._api_key = api_key

    def _complete(self, system: str, user: str) -> str:
        try:
            from openai import OpenAI  # lazy import
        except ImportError as e:  # pragma: no cover - optional dep
            raise RuntimeError("Install the 'openai' package to use the openai provider.") from e
        client = OpenAI(api_key=self._api_key)
        resp = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0,
        )
        return resp.choices[0].message.content or ""


class AnthropicProvider(JSONChatProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for the anthropic provider.")
        self.model = model
        self._api_key = api_key

    def _complete(self, system: str, user: str) -> str:
        try:
            import anthropic  # lazy import
        except ImportError as e:  # pragma: no cover - optional dep
            raise RuntimeError("Install the 'anthropic' package to use the anthropic provider.") from e
        client = anthropic.Anthropic(api_key=self._api_key)
        resp = client.messages.create(
            model=self.model,
            max_tokens=1024,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")


class OllamaProvider(JSONChatProvider):
    """Local models via Ollama -- the privacy-preserving default for sensitive
    deployments (data never leaves the host)."""

    name = "ollama"

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def _complete(self, system: str, user: str) -> str:
        resp = httpx.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "stream": False,
                "options": {"temperature": 0},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")
