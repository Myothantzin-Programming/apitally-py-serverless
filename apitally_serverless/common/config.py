from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ApitallyConfig:
    enabled: bool = False
    log_request_headers: bool = False
    log_request_body: bool = False
    log_response_headers: bool = True
    log_response_body: bool = False
    mask_headers: list[re.Pattern[str]] = field(default_factory=list)
    mask_body_fields: list[re.Pattern[str]] = field(default_factory=list)
    exclude_paths: list[re.Pattern[str]] = field(default_factory=list)


DEFAULT_CONFIG = ApitallyConfig()

