from __future__ import annotations

import json
import re
from typing import Any, Optional

from apitally_serverless.common.config import ApitallyConfig
from apitally_serverless.common.output import OutputData


MASKED = "******"

EXCLUDE_PATH_PATTERNS = [
    re.compile(r"/_?healthz?$", re.IGNORECASE),
    re.compile(r"/_?health[_-]?checks?$", re.IGNORECASE),
    re.compile(r"/_?heart[_-]?beats?$", re.IGNORECASE),
    re.compile(r"/ping$", re.IGNORECASE),
    re.compile(r"/ready$", re.IGNORECASE),
    re.compile(r"/live$", re.IGNORECASE),
]

MASK_HEADER_PATTERNS = [
    re.compile(r"auth", re.IGNORECASE),
    re.compile(r"api-?key", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"cookie", re.IGNORECASE),
]

MASK_BODY_FIELD_PATTERNS = [
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"pwd", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"auth", re.IGNORECASE),
    re.compile(r"card[-_]?number", re.IGNORECASE),
    re.compile(r"ccv", re.IGNORECASE),
    re.compile(r"ssn", re.IGNORECASE),
]


def _match_patterns(value: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(pattern.search(value) for pattern in patterns)


class DataMasker:
    def __init__(self, config: ApitallyConfig) -> None:
        self.config = config

    def _should_exclude_path(self, url_path: str) -> bool:
        patterns = list(self.config.exclude_paths) + EXCLUDE_PATH_PATTERNS
        return _match_patterns(url_path, patterns)

    def _should_mask_header(self, name: str) -> bool:
        patterns = list(self.config.mask_headers) + MASK_HEADER_PATTERNS
        return _match_patterns(name, patterns)

    def _should_mask_body_field(self, name: str) -> bool:
        patterns = list(self.config.mask_body_fields) + MASK_BODY_FIELD_PATTERNS
        return _match_patterns(name, patterns)

    def _mask_headers(
        self, headers: list[tuple[str, str]]
    ) -> list[tuple[str, str]]:
        return [(k, MASKED if self._should_mask_header(k) else v) for k, v in headers]

    def _mask_body(self, data: Any) -> Any:
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                if isinstance(value, str) and self._should_mask_body_field(key):
                    result[key] = MASKED
                else:
                    result[key] = self._mask_body(value)
            return result
        if isinstance(data, list):
            return [self._mask_body(item) for item in data]
        return data

    def _get_content_type(self, headers: Optional[list[tuple[str, str]]]) -> Optional[str]:
        if not headers:
            return None
        for k, v in headers:
            if k.lower() == "content-type":
                return v
        return None

    def _mask_body_bytes(
        self, body: bytes, headers: Optional[list[tuple[str, str]]]
    ) -> bytes:
        content_type = self._get_content_type(headers)

        try:
            if content_type is None or "json" in content_type.lower():
                parsed = json.loads(body.decode("utf-8"))
                masked = self._mask_body(parsed)
                return json.dumps(masked, separators=(",", ":")).encode("utf-8")
            elif "ndjson" in content_type.lower():
                lines = body.decode("utf-8").split("\n")
                masked_lines = []
                for line in lines:
                    line = line.strip()
                    if line:
                        try:
                            parsed = json.loads(line)
                            masked = self._mask_body(parsed)
                            masked_lines.append(json.dumps(masked, separators=(",", ":")))
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            masked_lines.append(line)
                return "\n".join(masked_lines).encode("utf-8")
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

        return body

    def apply_masking(self, data: OutputData) -> None:
        # Check if path is excluded
        if self._should_exclude_path(data.request.path):
            data.request.headers = None
            data.request.body = None
            data.response.headers = None
            data.response.body = None
            data.exclude = True
            return

        # Drop request and response bodies if logging is disabled
        if not self.config.log_request_body and data.request.body:
            data.request.body = None
        if not self.config.log_response_body and data.response.body:
            data.response.body = None

        # Mask request and response body fields
        if data.request.body:
            data.request.body = self._mask_body_bytes(
                data.request.body, data.request.headers
            )
        if data.response.body:
            data.response.body = self._mask_body_bytes(
                data.response.body, data.response.headers
            )

        # Mask request and response headers
        if self.config.log_request_headers and data.request.headers:
            data.request.headers = self._mask_headers(data.request.headers)
        else:
            data.request.headers = None

        if self.config.log_response_headers and data.response.headers:
            data.response.headers = self._mask_headers(data.response.headers)
        else:
            data.response.headers = None

