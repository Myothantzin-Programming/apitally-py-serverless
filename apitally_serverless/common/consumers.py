from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union


@dataclass
class ApitallyConsumer:
    identifier: str
    name: Optional[str] = None
    group: Optional[str] = None

    def __post_init__(self) -> None:
        self.identifier = str(self.identifier).strip()[:128]
        self.name = str(self.name).strip()[:64] if self.name else None
        self.group = str(self.group).strip()[:64] if self.group else None


_seen_consumer_hashes: set[int] = set()


def _djb2_hash(s: str) -> int:
    h = 5381
    for char in s:
        h = ((h << 5) + h) ^ ord(char)
    return h & 0xFFFFFFFF


def consumer_from_string_or_object(
    consumer: Optional[Union[str, ApitallyConsumer]],
) -> Optional[Union[str, ApitallyConsumer]]:
    if not consumer:
        return None

    if isinstance(consumer, str):
        trimmed = consumer.strip()[:128]
        return trimmed or None

    if isinstance(consumer, ApitallyConsumer):
        identifier = consumer.identifier
        if not identifier:
            return None

        name = consumer.name
        group = consumer.group

        if not name and not group:
            return identifier

        hash_key = f"{identifier}||{name or ''}||{group or ''}"
        h = _djb2_hash(hash_key)

        if h in _seen_consumer_hashes:
            return identifier

        _seen_consumer_hashes.add(h)
        return consumer

    return None

