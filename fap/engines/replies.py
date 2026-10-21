"""Auto-reply rule matching."""

from __future__ import annotations

import re

from .common import render, split_keywords


def _match(rule: dict, text: str) -> bool:
    kind = rule.get("match_type") or "keyword"
    pattern = rule.get("pattern") or ""
    if kind == "exact":
        return text.strip().casefold() == pattern.strip().casefold()
    if kind == "keyword":
        lowered = text.casefold()
        return any(k.casefold() in lowered for k in split_keywords(pattern))
    if kind == "regex":
        try:
            return re.search(pattern, text, re.IGNORECASE) is not None
        except re.error:
            return False
    return False


def find_matching_rule(conn, text: str, account_id: int | None, goods_id: int | None) -> dict | None:
    rows = conn.execute(
        "SELECT * FROM autoreply_rules WHERE enabled=1 "
        "AND (account_id IS NULL OR account_id=?) "
        "AND (scope='all' OR goods_id=?) "
        "ORDER BY priority DESC, id ASC",
        (account_id, goods_id),
    ).fetchall()
    for row in rows:
        rule = dict(row)
        if rule["reply_type"] == "ai":
            # AI rules are a fallback: they match everything but only when no
            # concrete rule matched and AI is enabled on the account.
            continue
        if _match(rule, text):
            return rule
    return None


def build_reply(rule: dict, context: dict) -> dict:
    reply_type = rule.get("reply_type") or "text"
    if reply_type == "image":
        return {
            "type": "image",
            "image_url": render(rule.get("image_url", ""), context),
            "content": render(rule.get("content", ""), context),
            "rule_id": rule["id"],
            "rule_name": rule["name"],
        }
    return {
        "type": "text",
        "content": render(rule.get("content", ""), context),
        "rule_id": rule["id"],
        "rule_name": rule["name"],
    }
