from __future__ import annotations


DIRECT_ORDER_TRIGGER = "es una orden"


def has_direct_order_override(message: str) -> bool:
    return DIRECT_ORDER_TRIGGER in message.lower()
