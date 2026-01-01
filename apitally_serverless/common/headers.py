from __future__ import annotations

from typing import Iterable, Optional, Tuple, Union


SUPPORTED_CONTENT_TYPES = [
    "application/json",
    "application/ld+json",
    "application/problem+json",
    "application/vnd.api+json",
    "application/x-ndjson",
    "text/plain",
    "text/html",
]


def convert_headers(
    headers: Optional[Iterable[Tuple[str, str]]],
) -> list[tuple[str, str]]:
    if headers is None:
        return []
    return [(k.lower(), v) for k, v in headers]


def parse_content_length(
    content_length: Optional[Union[str, bytes, int]],
) -> Optional[int]:
    if content_length is None:
        return None
    if isinstance(content_length, int):
        return content_length
    if isinstance(content_length, bytes):
        content_length = content_length.decode()
    try:
        return int(content_length)
    except ValueError:
        return None


def is_supported_content_type(content_type: Optional[str]) -> bool:
    if not content_type:
        return False
    return any(content_type.startswith(t) for t in SUPPORTED_CONTENT_TYPES)

