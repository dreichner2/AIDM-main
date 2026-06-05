from __future__ import annotations

import re


_REASONING_TAG_NAMES = r'(?:thought|think)'
_REASONING_BLOCK_RE = re.compile(
    rf'<\s*{_REASONING_TAG_NAMES}\b[^>]*>[\s\S]*?(?:<\s*/\s*{_REASONING_TAG_NAMES}\s*>|$)',
    re.IGNORECASE,
)
_REASONING_CLOSE_RE = re.compile(rf'<\s*/\s*{_REASONING_TAG_NAMES}\s*>', re.IGNORECASE)
_REASONING_OPEN_RE = re.compile(rf'<\s*{_REASONING_TAG_NAMES}\b[^>]*>', re.IGNORECASE)
_PARTIAL_REASONING_OPEN_RE = re.compile(r'<\s*(?:t|th|thi|thin|think|tho|thou|thoug|though|thought)?$', re.IGNORECASE)
_PARTIAL_REASONING_CLOSE_RE = re.compile(r'<\s*/\s*(?:t|th|thi|thin|think|tho|thou|thoug|though|thought)?$', re.IGNORECASE)
_MARKDOWN_IMAGE_RE = re.compile(r'!\[[^\]]*]\([^)]+\)')
_MARKDOWN_LINK_RE = re.compile(r'\[([^\]]+)]\([^)]+\)')
_MARKDOWN_CODE_FENCE_RE = re.compile(r'```[\s\S]*?```')
_MARKDOWN_INLINE_CODE_RE = re.compile(r'`([^`]+)`')
_MARKDOWN_LINE_PREFIX_RE = re.compile(r'^\s{0,3}(?:#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)', re.MULTILINE)
_MARKDOWN_EMPHASIS_RE = re.compile(r'[*_~]{1,3}')
_WHITESPACE_RE = re.compile(r'\s+')


def strip_reasoning_blocks(value: str | None) -> str:
    if not value:
        return ''
    return _REASONING_BLOCK_RE.sub('', str(value))


def normalize_tts_text(value: str | None) -> str:
    """Return text safe to send to TTS providers.

    The React client does its own display cleanup, but the backend should also
    remove provider reasoning tags and common markdown syntax before speech so
    any caller of `/api/tts/speak` gets consistent narration text.
    """
    text = strip_reasoning_blocks(value)
    if not text:
        return ''

    text = _MARKDOWN_CODE_FENCE_RE.sub(' ', text)
    text = _MARKDOWN_IMAGE_RE.sub(' ', text)
    text = _MARKDOWN_LINK_RE.sub(r'\1', text)
    text = _MARKDOWN_INLINE_CODE_RE.sub(r'\1', text)
    text = _MARKDOWN_LINE_PREFIX_RE.sub('', text)
    text = _MARKDOWN_EMPHASIS_RE.sub('', text)
    return _WHITESPACE_RE.sub(' ', text).strip()


class ReasoningBlockFilter:
    """Streaming filter for provider reasoning tags that may span chunks."""

    def __init__(self):
        self._buffer = ''
        self._inside_reasoning = False

    def filter(self, chunk: str | None) -> str:
        if not chunk:
            return ''

        text = self._buffer + str(chunk)
        self._buffer = ''
        output: list[str] = []
        index = 0

        while index < len(text):
            if self._inside_reasoning:
                close_match = _REASONING_CLOSE_RE.search(text, index)
                if close_match is None:
                    self._buffer = self._reasoning_suffix(text[index:])
                    return ''.join(output)
                index = close_match.end()
                self._inside_reasoning = False
                continue

            open_match = _REASONING_OPEN_RE.search(text, index)
            if open_match is None:
                safe_text, pending_suffix = self._split_safe_suffix(text[index:])
                output.append(safe_text)
                self._buffer = pending_suffix
                break

            output.append(text[index:open_match.start()])
            index = open_match.end()
            self._inside_reasoning = True

        return ''.join(output)

    def finish(self) -> str:
        if self._inside_reasoning:
            self._buffer = ''
            self._inside_reasoning = False
            return ''
        pending = self._buffer
        self._buffer = ''
        return pending

    @staticmethod
    def _reasoning_suffix(value: str) -> str:
        suffix = value[-24:]
        partial_start = suffix.rfind('<')
        if partial_start == -1:
            return ''
        candidate = suffix[partial_start:]
        return candidate if _PARTIAL_REASONING_CLOSE_RE.match(candidate) else ''

    @staticmethod
    def _split_safe_suffix(value: str) -> tuple[str, str]:
        partial_start = value.rfind('<')
        if partial_start == -1:
            return value, ''
        candidate = value[partial_start:]
        if _PARTIAL_REASONING_OPEN_RE.match(candidate):
            return value[:partial_start], candidate
        return value, ''
