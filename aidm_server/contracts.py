"""Internal typed contracts used by AI-DM runtime modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class SegmentTriggerSpec:
    trigger_type: str
    raw: dict


@dataclass
class ProviderRequest:
    prompt: str
    system_message: Optional[str] = None


@dataclass
class ProviderResponse:
    text: str
    provider: str
    model: str
