"""Vendor-neutral LLM client. Every caller must cope with `None` (no LLM, timeout, bad JSON):
the bot then falls back to deterministic rules and templates instead of failing."""
from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path
from typing import Protocol

import httpx

from .config import get_settings

log = logging.getLogger(__name__)


class LLM(Protocol):
    def generate(self, system: str, user: str, images: list[str] | None = None, json_mode: bool = False) -> str | None: ...


def _mime(path: str) -> str:
    p = path.lower()
    return "image/png" if p.endswith(".png") else "image/webp" if p.endswith(".webp") else "image/jpeg"


class GeminiLLM:
    def __init__(self, key: str, model: str, timeout: float):
        self.key, self.model, self.timeout = key, model, timeout

    def generate(self, system, user, images=None, json_mode=False):
        parts: list[dict] = [{"text": user}]
        for img in images or []:
            parts.append({"inline_data": {"mime_type": _mime(img), "data": base64.b64encode(Path(img).read_bytes()).decode()}})
        body: dict = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0.2},
        }
        if json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        try:
            r = httpx.post(url, params={"key": self.key}, json=body, timeout=self.timeout)
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:  # network, quota, safety block
            log.warning("Gemini call failed: %s", e)
            return None


class AnthropicLLM:
    def __init__(self, key: str, model: str, timeout: float):
        self.key, self.model, self.timeout = key, model, timeout

    def generate(self, system, user, images=None, json_mode=False):
        content: list[dict] = []
        for img in images or []:
            content.append({"type": "image", "source": {"type": "base64", "media_type": _mime(img),
                                                         "data": base64.b64encode(Path(img).read_bytes()).decode()}})
        content.append({"type": "text", "text": user + ("\n\nRespond with JSON only." if json_mode else "")})
        try:
            r = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": self.key, "anthropic-version": "2023-06-01"},
                json={"model": self.model, "max_tokens": 1500, "system": system, "temperature": 0.2,
                      "messages": [{"role": "user", "content": content}]},
                timeout=self.timeout,
            )
            r.raise_for_status()
            return "".join(b.get("text", "") for b in r.json()["content"])
        except Exception as e:
            log.warning("Anthropic call failed: %s", e)
            return None


class NoLLM:
    def generate(self, system, user, images=None, json_mode=False):
        return None


_llm: LLM | None = None


def get_llm() -> LLM:
    global _llm
    if _llm is None:
        s = get_settings()
        if s.llm_provider == "gemini" and s.gemini_api_key:
            _llm = GeminiLLM(s.gemini_api_key, s.gemini_model, s.llm_timeout_s)
        elif s.llm_provider == "anthropic" and s.anthropic_api_key:
            _llm = AnthropicLLM(s.anthropic_api_key, s.anthropic_model, s.llm_timeout_s)
        else:
            _llm = NoLLM()
    return _llm


def set_llm(llm: LLM | None) -> None:
    """Tests inject a fake; None resets to configuration."""
    global _llm
    _llm = llm


def parse_json(text: str | None) -> dict | None:
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        out = json.loads(m.group(0))
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        return None


def has_llm() -> bool:
    return not isinstance(get_llm(), NoLLM)
