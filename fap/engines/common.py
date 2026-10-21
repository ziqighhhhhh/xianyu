"""Shared helpers for the reply / delivery / workflow engines."""

from __future__ import annotations

import re

_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}")


def render(template: str, context: dict) -> str:
    """Replace ``{{key}}`` placeholders with values from *context*.

    Unknown keys are replaced with an empty string so a missing variable never
    leaks a template expression to a buyer.
    """

    def repl(match: re.Match) -> str:
        key = match.group(1)
        value = context.get(key, "")
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    return _PLACEHOLDER.sub(repl, template or "")


def split_keywords(pattern: str) -> list[str]:
    parts = re.split(r"[,，、;；\n]+", pattern or "")
    return [p.strip() for p in parts if p.strip()]
