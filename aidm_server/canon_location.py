"""Location inference helpers for emergent canon projection."""

from __future__ import annotations

import re


LOCATION_PATTERNS = [
    re.compile(
        r'\b(?:enter|entered|arrive(?:d)? at|reach(?:ed)?|head(?:ing)? to|go(?:ing)? to|travel(?:ing)? to|'
        r'move(?:d)? to|sprint(?:ing)? for|run(?:ning)? for|escape(?:d)? (?:to|through)|'
        r'slip(?:ped)? into|leap(?:ing)? into|jump(?:ing)? into|vault(?:ing)? onto)\s+'
        r'(?:the\s+)?([^.,;!?]+)',
        re.IGNORECASE,
    ),
    re.compile(
        r'\b(?:you reach|you arrive at|you enter|you slip into|you burst into|you move into)\s+'
        r'(?:the\s+)?([^.,;!?]+)',
        re.IGNORECASE,
    ),
    re.compile(
        r'\b(?:lead(?:s|ing)?|guide(?:s|d)?|usher(?:s|ed)?|pull(?:s|ed)?)\s+you\s+'
        r'(?:into|to|toward)\s+(?:the\s+)?([^.,;!?]+)',
        re.IGNORECASE,
    ),
]


def normalize_location_candidate(raw_text: str | None) -> str | None:
    text = (raw_text or '').strip(" \t\r\n'\"`")
    if not text:
        return None

    lower = text.lower()
    split_tokens = [
        ' and ',
        ' while ',
        ' before ',
        ' after ',
        ' as ',
        ' with ',
        ' but ',
        ' where ',
        ' to ',
        ' through ',
        ' across ',
        ' above ',
        ' unhindered',
    ]
    cut = len(text)
    for token in split_tokens:
        idx = lower.find(token)
        if idx != -1 and idx < cut:
            cut = idx

    cleaned = text[:cut].strip(' -')
    words = cleaned.split()
    trailing_noise = {
        'quietly',
        'carefully',
        'quickly',
        'silently',
        'safely',
        'unseen',
        'unhindered',
        'immediately',
    }
    while words and words[-1].lower().strip('.,;:!?') in trailing_noise:
        words.pop()
    if not words:
        return None
    return ' '.join(words[:8])


def infer_location_update(player_input: str, dm_output: str | None) -> str | None:
    sources = [player_input or '', dm_output or '']
    for source in sources:
        for pattern in LOCATION_PATTERNS:
            match = pattern.search(source)
            if not match:
                continue
            candidate = normalize_location_candidate(match.group(1))
            if candidate:
                return candidate
    return None
