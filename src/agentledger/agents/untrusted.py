"""Text that came from another agent. It is data, never an instruction."""

from __future__ import annotations

import unicodedata


def clip_untrusted(text: str, limit: int = 120) -> str:
    """Drop control characters and keep the tool-facing blurb short."""
    cleaned = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")
    cleaned = " ".join(cleaned.split())
    return cleaned[:limit]
