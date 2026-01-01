from __future__ import annotations

import base64
import gzip
import json
from dataclasses import asdict, is_dataclass
from typing import Any, Optional

from apitally_serverless.common.consumers import ApitallyConsumer


class ValidationError:
    __slots__ = ("loc", "msg", "type")

    def __init__(self, loc: list[str], msg: str, type: str) -> None:
        self.loc = loc
        self.msg = msg
        self.type = type


class StartupData:
    __slots__ = ("paths", "versions", "client")

    def __init__(
        self,
        paths: list[dict[str, str]],
        versions: dict[str, str],
        client: str,
    ) -> None:
        self.paths = paths
        self.versions = versions
        self.client = client


class RequestData:
    __slots__ = ("path", "headers", "size", "consumer", "body")

    def __init__(
        self,
        path: str,
        headers: Optional[list[tuple[str, str]]] = None,
        size: Optional[int] = None,
        consumer: Optional[str] = None,
        body: Optional[bytes] = None,
    ) -> None:
        self.path = path
        self.headers = headers
        self.size = size
        self.consumer = consumer
        self.body = body


class ResponseData:
    __slots__ = ("response_time", "status_code", "headers", "size", "body")

    def __init__(
        self,
        response_time: float,
        status_code: int,
        headers: Optional[list[tuple[str, str]]] = None,
        size: Optional[int] = None,
        body: Optional[bytes] = None,
    ) -> None:
        self.response_time = response_time
        self.status_code = status_code
        self.headers = headers
        self.size = size
        self.body = body


class OutputData:
    __slots__ = (
        "instance_uuid",
        "request_uuid",
        "consumer",
        "startup",
        "request",
        "response",
        "validation_errors",
        "exclude",
    )

    def __init__(
        self,
        instance_uuid: str,
        request_uuid: str,
        request: RequestData,
        response: ResponseData,
        consumer: Optional[ApitallyConsumer] = None,
        startup: Optional[StartupData] = None,
        validation_errors: Optional[list[ValidationError]] = None,
        exclude: bool = False,
    ) -> None:
        self.instance_uuid = instance_uuid
        self.request_uuid = request_uuid
        self.consumer = consumer
        self.startup = startup
        self.request = request
        self.response = response
        self.validation_errors = validation_errors
        self.exclude = exclude


def _to_dict(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")
    if isinstance(obj, (list, tuple)):
        return [_to_dict(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_dict(v) for k, v in asdict(obj).items()}
    if hasattr(obj, "__slots__"):
        return {slot: _to_dict(getattr(obj, slot)) for slot in obj.__slots__}
    return obj


def _to_camel_case(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(word.capitalize() for word in parts[1:])


def _convert_keys_to_camel_case(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {_to_camel_case(k): _convert_keys_to_camel_case(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_convert_keys_to_camel_case(item) for item in obj]
    return obj


def _skip_empty_values(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: _skip_empty_values(v)
            for k, v in obj.items()
            if v is not None and v != [] and v != {} and v != "" and v is not False
        }
    if isinstance(obj, list):
        return [_skip_empty_values(item) for item in obj]
    return obj


def _create_log_message(data: OutputData) -> str:
    data_dict = _to_dict(data)
    data_dict = _convert_keys_to_camel_case(data_dict)
    data_dict = _skip_empty_values(data_dict)

    json_str = json.dumps(data_dict, separators=(",", ":"))
    compressed = gzip.compress(json_str.encode("utf-8"))
    encoded = base64.b64encode(compressed).decode("ascii")

    return f"apitally:{encoded}"


def log_data(data: OutputData) -> None:
    msg = _create_log_message(data)

    if len(msg) > 15_000:
        # Cloudflare Workers Logpush limits the total length of all exception and log messages to 16,384 characters,
        # so we need to keep the logged message well below that limit.
        data.request.body = None
        data.response.body = None
        msg = _create_log_message(data)

    print(msg)

