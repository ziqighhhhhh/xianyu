"""Select a platform adapter for an account."""

from __future__ import annotations

from .base import PlatformAdapter
from .goofish import GoofishAdapter
from .mock import MockAdapter


def adapter_for(account: dict | None) -> PlatformAdapter:
    if not account:
        return MockAdapter()
    if (account.get("cookie") or "").startswith("demo"):
        return MockAdapter(account)
    return GoofishAdapter(account)
