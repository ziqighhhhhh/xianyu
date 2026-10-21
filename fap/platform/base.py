"""Platform adapter contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class IncomingMessage:
    account_id: int
    buyer: str
    text: str
    goods_id: int | None = None


@dataclass
class PlatformItem:
    key: str
    title: str
    price: float
    url: str = ""


class PlatformAdapter:
    name = "base"

    def connect(self) -> dict:
        raise NotImplementedError

    def search_items(self, keyword: str, min_price: float | None, max_price: float | None) -> list[PlatformItem]:
        raise NotImplementedError

    def send_message(self, buyer: str, content: str) -> dict:
        raise NotImplementedError

    def fetch_orders(self, page: int = 1) -> list[dict]:
        raise NotImplementedError

    def fetch_order(self, order_id: str) -> dict:
        raise NotImplementedError

    def publish_item(self, material: dict) -> dict:
        raise NotImplementedError
