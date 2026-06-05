"""Narrative-first D&D-lite rules hinting."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass
class RuleHint:
    requires_roll: bool
    roll_type: str | None
    dc_hint: str | None
    reason: str
    confidence: float
    roll_value: int | None = None
    outcome_deferred: bool = False


_ATTACK_KEYWORDS = {"attack", "shoot", "slash", "stab", "hit", "smite"}
_STEALTH_KEYWORDS = {"sneak", "stealth", "hide", "silently"}
_SOCIAL_KEYWORDS = {
    "persuade",
    "deceive",
    "intimidate",
    "convince",
    "negotiate",
    "bluff",
    "lie",
    "con",
    "impersonate",
}
_LORE_KEYWORDS = {"investigate", "search", "inspect", "recall", "arcana", "history"}
_ATHLETIC_KEYWORDS = {"climb", "jump", "grapple", "lift", "shove"}
_THIEVES_TOOLS_KEYWORDS = {
    "thieves'",
    "thieves",
    "lockpick",
    "lockpicks",
    "disarm",
    "disable",
    "pick",
    "trap",
    "circuit",
    "ward",
    "sigil",
}
_MOBILITY_KEYWORDS = {
    "sprint",
    "run",
    "dash",
    "escape",
    "leap",
    "vault",
    "gutter",
    "rooftops",
    "roof",
    "chase",
}


DC_HINTS = {
    "attack": "10-18 (target armor dependent)",
    "stealth": "12-17",
    "social": "12-18",
    "lore": "10-18",
    "athletics": "10-16",
    "thieves_tools": "12-18",
    "mobility": "12-18",
    "check": "10-18",
}


def _extract_roll_value(text: str) -> int | None:
    normalized = (text or '').lower()
    if 'natural 20' in normalized or 'nat 20' in normalized:
        return 20
    if 'natural 1' in normalized or 'nat 1' in normalized:
        return 1

    patterns = [
        r'\broll(?:ed|ing)?\s*(?:a\s*)?(?:d20\s*)?(?:=|is|:)?\s*(\d{1,2})\b',
        r'\bd20\s*(?:=|is|:)\s*(\d{1,2})\b',
        r'\bcheck\s*(?:=|is|:)\s*(\d{1,2})\b',
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        value = int(match.group(1))
        if 1 <= value <= 20:
            return value
    return None


def _with_resolution(hint: RuleHint) -> RuleHint:
    deferred = bool(hint.requires_roll and hint.roll_value is None)
    hint.outcome_deferred = deferred
    return hint


def classify_player_action(message: str) -> RuleHint:
    text = (message or "").strip().lower()
    if not text:
        return RuleHint(False, None, None, "No actionable text provided", confidence=0.99)

    tokens = set(text.replace(".", " ").replace(",", " ").split())
    roll_value = _extract_roll_value(text)

    if tokens & _ATTACK_KEYWORDS:
        return _with_resolution(
            RuleHint(
                True,
                "attack",
                DC_HINTS["attack"],
                "Combat action detected",
                confidence=0.92,
                roll_value=roll_value,
            )
        )
    if tokens & _STEALTH_KEYWORDS:
        return _with_resolution(
            RuleHint(
                True,
                "stealth",
                DC_HINTS["stealth"],
                "Stealth action detected",
                confidence=0.9,
                roll_value=roll_value,
            )
        )
    if tokens & _SOCIAL_KEYWORDS:
        return _with_resolution(
            RuleHint(
                True,
                "social",
                DC_HINTS["social"],
                "Social influence action detected",
                confidence=0.88,
                roll_value=roll_value,
            )
        )
    if tokens & _LORE_KEYWORDS:
        return _with_resolution(
            RuleHint(
                True,
                "lore",
                DC_HINTS["lore"],
                "Investigation or knowledge action detected",
                confidence=0.87,
                roll_value=roll_value,
            )
        )
    if tokens & _ATHLETIC_KEYWORDS:
        return _with_resolution(
            RuleHint(
                True,
                "athletics",
                DC_HINTS["athletics"],
                "Physical challenge action detected",
                confidence=0.89,
                roll_value=roll_value,
            )
        )
    if tokens & _THIEVES_TOOLS_KEYWORDS:
        return _with_resolution(
            RuleHint(
                True,
                "thieves_tools",
                DC_HINTS["thieves_tools"],
                "Precision disable/disarm action detected",
                confidence=0.9,
                roll_value=roll_value,
            )
        )
    if tokens & _MOBILITY_KEYWORDS:
        return _with_resolution(
            RuleHint(
                True,
                "mobility",
                DC_HINTS["mobility"],
                "High-risk movement or escape detected",
                confidence=0.86,
                roll_value=roll_value,
            )
        )

    if roll_value is not None or 'roll' in text or 'check' in text:
        return _with_resolution(
            RuleHint(
                True,
                "check",
                DC_HINTS["check"],
                "Player indicated a generic roll/check",
                confidence=0.78,
                roll_value=roll_value,
            )
        )

    return RuleHint(False, None, None, "Narrative action; no explicit roll required", confidence=0.75)
