"""Channel-independent contracts. Telegram, the website and tests all speak these types."""
from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Style = Literal["ta", "en", "ta-Latn"]  # Tamil script, English, Tanglish


class Media(BaseModel):
    kind: Literal["image", "voice"]
    path: str  # local path (object-storage key in production)
    mime: str = ""


class InboundMessage(BaseModel):
    channel: str = "telegram"
    user_ref: str  # channel user id, e.g. Telegram chat id
    text: str | None = None
    media: list[Media] = Field(default_factory=list)
    button: str | None = None  # payload of a pressed button, e.g. "crop:chilli"
    idempotency_key: str | None = None
    user_name: str | None = None


class Button(BaseModel):
    label: str
    payload: str


class Source(BaseModel):
    title: str
    ref: str  # URL or "file.pdf p.3"


class Probability(BaseModel):
    label: str
    display: str
    p: float

    @field_validator("p")
    @classmethod
    def finite(cls, v: float) -> float:
        if not math.isfinite(v) or v < 0 or v > 1:
            raise ValueError("probability must be finite and in [0, 1]")
        return v


class Reply(BaseModel):
    text: str
    style: Style
    buttons: list[Button] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    case_id: str | None = None
    action: str = "answer"  # answer | ask | escalate | error
    escalate: bool = False
    escalation_summary: str | None = None
    escalation_images: list[str] = Field(default_factory=list)
    audio_path: str | None = None
    debug: dict = Field(default_factory=dict)
