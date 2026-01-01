from __future__ import annotations

import re
import sys
import time
from importlib.metadata import PackageNotFoundError, version
from typing import Any, List, Optional, Union
from uuid import uuid4

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.routing import BaseRoute, Match, Router
from starlette.schemas import EndpointInfo, SchemaGenerator
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from apitally_serverless import __version__
from apitally_serverless.common.config import ApitallyConfig
from apitally_serverless.common.consumers import ApitallyConsumer, consumer_from_string_or_object
from apitally_serverless.common.headers import convert_headers, is_supported_content_type, parse_content_length
from apitally_serverless.common.masking import DataMasker
from apitally_serverless.common.output import (
    OutputData,
    RequestData,
    ResponseData,
    StartupData,
    ValidationError,
    log_data,
)


__all__ = ["ApitallyMiddleware", "ApitallyConsumer", "ApitallyConfig", "set_consumer", "use_apitally"]

MAX_BODY_SIZE = 10_000
BODY_TOO_LARGE = b"<body too large>"

_instance_uuid: Optional[str] = None
_is_first_request = True


class ApitallyMiddleware:
    """
    Apitally middleware for Starlette applications in serverless environments.

    For more information, see:
    - Setup guide: https://docs.apitally.io/frameworks/starlette
    - Reference: https://docs.apitally.io/reference/python
    """

    def __init__(
        self,
        app: ASGIApp,
        config: Optional[ApitallyConfig] = None,
    ) -> None:
        self.app = app
        self.config = config or ApitallyConfig()
        self.masker = DataMasker(self.config)

        self.capture_request_body = self.config.enabled and self.config.log_request_body
        self.capture_response_body = self.config.enabled and self.config.log_response_body

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        global _instance_uuid, _is_first_request

        if not self.config.enabled or scope["type"] != "http" or scope["method"] == "OPTIONS":
            await self.app(scope, receive, send)
            return

        start_time = time.perf_counter()
        request = Request(scope, receive, send)
        request_size = parse_content_length(request.headers.get("Content-Length"))
        request_content_type = request.headers.get("Content-Type")
        request_body = b""
        request_body_too_large = request_size is not None and request_size > MAX_BODY_SIZE

        response_status = 0
        response_time: Optional[float] = None
        response_headers = Headers()
        response_body = b""
        response_body_too_large = False
        response_size: Optional[int] = None
        response_chunked = False
        response_content_type: Optional[str] = None

        async def receive_wrapper() -> Message:
            nonlocal request_body, request_body_too_large

            message = await receive()
            if message["type"] == "http.request":
                if (
                    self.capture_request_body
                    and not request_body_too_large
                    and is_supported_content_type(request_content_type)
                ):
                    request_body += message.get("body", b"")
                    if len(request_body) > MAX_BODY_SIZE:
                        request_body_too_large = True
                        request_body = b""
            return message

        async def send_wrapper(message: Message) -> None:
            nonlocal response_time, response_status, response_headers, response_body
            nonlocal response_body_too_large, response_chunked, response_content_type, response_size

            if message["type"] == "http.response.start":
                response_time = time.perf_counter() - start_time
                response_status = message["status"]
                response_headers = Headers(scope=message)
                response_chunked = (
                    response_headers.get("Transfer-Encoding") == "chunked"
                    or "Content-Length" not in response_headers
                )
                response_content_type = response_headers.get("Content-Type")
                response_size = (
                    parse_content_length(response_headers.get("Content-Length"))
                    if not response_chunked
                    else 0
                )
                response_body_too_large = response_size is not None and response_size > MAX_BODY_SIZE

            elif message["type"] == "http.response.body":
                if response_chunked and response_size is not None:
                    response_size += len(message.get("body", b""))

                should_capture = (
                    (self.capture_response_body or response_status == 422)
                    and is_supported_content_type(response_content_type)
                    and not response_body_too_large
                )
                if should_capture:
                    response_body += message.get("body", b"")
                    if len(response_body) > MAX_BODY_SIZE:
                        response_body_too_large = True
                        response_body = b""

            await send(message)

        try:
            await self.app(scope, receive_wrapper, send_wrapper)
        finally:
            if response_time is None:
                response_time = time.perf_counter() - start_time

            if request_body_too_large:
                request_body = BODY_TOO_LARGE
            if response_body_too_large:
                response_body = BODY_TOO_LARGE

            path = self._get_path(request)

            if path is not None:
                consumer = self._get_consumer(request)
                consumer_identifier = (
                    consumer.identifier
                    if isinstance(consumer, ApitallyConsumer)
                    else consumer
                )

                # Build startup data on first request
                startup_data: Optional[StartupData] = None
                if _is_first_request:
                    _is_first_request = False
                    _instance_uuid = str(uuid4())
                    startup_data = StartupData(
                        paths=_list_endpoints(self.app),
                        versions=_get_versions(),
                        client="python-serverless:starlette",
                    )

                # Extract validation errors from 422 responses
                validation_errors: Optional[list[ValidationError]] = None
                if response_status == 422 and response_body:
                    validation_errors = _extract_validation_errors(response_body)

                data = OutputData(
                    instance_uuid=_instance_uuid or str(uuid4()),
                    request_uuid=str(uuid4()),
                    consumer=consumer if isinstance(consumer, ApitallyConsumer) else None,
                    startup=startup_data,
                    request=RequestData(
                        path=path,
                        headers=convert_headers(request.headers.items()),
                        size=request_size,
                        consumer=consumer_identifier,
                        body=request_body or None,
                    ),
                    response=ResponseData(
                        response_time=response_time,
                        status_code=response_status,
                        headers=convert_headers(response_headers.items()),
                        size=response_size,
                        body=response_body or None,
                    ),
                    validation_errors=validation_errors,
                )

                self.masker.apply_masking(data)
                log_data(data)

    def _get_path(
        self, request: Request, routes: Optional[List[BaseRoute]] = None
    ) -> Optional[str]:
        if routes is None:
            routes = request.app.routes
        for route in routes:
            if hasattr(route, "routes"):
                path = self._get_path(request, routes=route.routes)
                if path is not None:
                    return path
            elif hasattr(route, "path"):
                match, _ = route.matches(request.scope)
                if match == Match.FULL:
                    return request.scope.get("root_path", "") + route.path
        return None

    def _get_consumer(
        self, request: Request
    ) -> Optional[Union[ApitallyConsumer, str]]:
        if hasattr(request.state, "apitally_consumer") and request.state.apitally_consumer:
            return consumer_from_string_or_object(request.state.apitally_consumer)
        return None


def set_consumer(
    request: Request,
    identifier: str,
    name: Optional[str] = None,
    group: Optional[str] = None,
) -> None:
    """Set the consumer for the current request."""
    request.state.apitally_consumer = ApitallyConsumer(identifier, name=name, group=group)


def use_apitally(app: ASGIApp, config: Optional[ApitallyConfig] = None) -> None:
    """
    Add Apitally middleware to a Starlette/FastAPI application.

    This function modifies the app in-place by wrapping it with the middleware.
    """
    if isinstance(app, Router):
        original_app = app.app
        app.app = ApitallyMiddleware(original_app, config=config)
    else:
        raise TypeError("app must be a Starlette or FastAPI application")


def _list_endpoints(app: ASGIApp) -> list[dict[str, str]]:
    routes = _get_routes(app)
    schemas = SchemaGenerator({})
    endpoints = schemas.get_endpoints(routes)
    return [{"method": e.http_method, "path": e.path} for e in endpoints]


def _get_routes(app: Union[ASGIApp, Router]) -> List[BaseRoute]:
    if isinstance(app, Router):
        return app.routes
    elif hasattr(app, "app"):
        return _get_routes(app.app)
    return []


def _get_versions() -> dict[str, str]:
    versions: dict[str, str] = {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    }

    for package in ["apitally-serverless", "fastapi", "starlette"]:
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            pass

    versions["apitally-serverless"] = __version__

    return versions


def _extract_validation_errors(response_body: bytes) -> Optional[list[ValidationError]]:
    """Extract Pydantic validation errors from a 422 response body."""
    import json

    try:
        body = json.loads(response_body.decode("utf-8"))
        if isinstance(body, dict) and "detail" in body and isinstance(body["detail"], list):
            errors = []
            for detail in body["detail"]:
                if isinstance(detail, dict):
                    loc = detail.get("loc", [])
                    msg = detail.get("msg", "")
                    error_type = detail.get("type", "")
                    errors.append(ValidationError(
                        loc=[str(l) for l in loc],
                        msg=str(msg),
                        type=str(error_type),
                    ))
            return errors if errors else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass

    return None

