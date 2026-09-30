"""Read-only HTTP API for the local reference dataset."""

from __future__ import annotations

import hmac
import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from .config import API_VERSION, APP_NAME
from .schema import error_payload
from .store import Dataset, load_dataset


@dataclass(frozen=True)
class Response:
    status: int
    payload: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


class _RateLimiter:
    # Idle clients are swept once this many are tracked, so unique client ids
    # (for example many source addresses) cannot grow memory without bound.
    sweep_threshold = 1024

    def __init__(self, max_requests: int, window_seconds: float = 60) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be positive")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, client_id: str) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            if len(self._events) >= self.sweep_threshold and client_id not in self._events:
                self._sweep(now)
            events = [event for event in self._events.get(client_id, []) if now - event < self.window_seconds]
            if len(events) >= self.max_requests:
                retry_after = max(1, int(self.window_seconds - (now - events[0])))
                self._events[client_id] = events
                return False, retry_after
            events.append(now)
            self._events[client_id] = events
            return True, 0

    def _sweep(self, now: float) -> None:
        for key in list(self._events):
            recent = [event for event in self._events[key] if now - event < self.window_seconds]
            if recent:
                self._events[key] = recent
            else:
                del self._events[key]

    def tracked_clients(self) -> int:
        with self._lock:
            return len(self._events)


class ApiService:
    """Application service that can be exercised without opening a socket."""

    def __init__(self, dataset: Dataset | None = None, *, read_token: str | None = None, rate_limit: int = 60) -> None:
        self.dataset = dataset or load_dataset()
        self.read_token = read_token
        self._rate_limiter = _RateLimiter(rate_limit)

    def _response(self, status: int, payload: dict[str, Any], **headers: str) -> Response:
        return Response(status, payload, headers)

    def _authorized(self, headers: dict[str, str]) -> bool:
        if self.read_token is None:
            return True
        supplied = headers.get("Authorization", "")
        expected = f"Bearer {self.read_token}"
        return hmac.compare_digest(supplied, expected)

    def _metadata(self) -> dict[str, Any]:
        return {
            "api": APP_NAME,
            "api_version": API_VERSION,
            "access": "read-only",
            "schema_version": self.dataset.schema_version,
            "dataset": self.dataset.dataset,
            "records_count": len(self.dataset.records),
            "data_status": "valid",
            "storage": "local_bronze_fixture",
            "lineage": self.dataset.lineage.as_dict(),
        }

    def _parse_query(self, query: str) -> tuple[str | None, int, int] | Response:
        values = parse_qs(query, keep_blank_values=True)
        for key in ("category", "limit", "offset"):
            if len(values.get(key, [])) > 1:
                return self._response(400, error_payload("API001", f"{key} must be provided once", {"field": key}))
        category = values.get("category", [None])[0]
        try:
            limit = int(values.get("limit", ["50"])[0])
            offset = int(values.get("offset", ["0"])[0])
        except ValueError:
            return self._response(400, error_payload("API002", "limit and offset must be integers"))
        if limit < 1 or limit > 100:
            return self._response(400, error_payload("API003", "limit must be between 1 and 100"))
        if offset < 0:
            return self._response(400, error_payload("API004", "offset must be non-negative"))
        return category, limit, offset

    def handle(
        self,
        method: str,
        target: str,
        headers: dict[str, str] | None = None,
        *,
        client_id: str = "local",
    ) -> Response:
        request_headers = headers or {}
        allowed, retry_after = self._rate_limiter.allow(client_id)
        if not allowed:
            return self._response(
                429,
                error_payload(
                    "RATE001", "rate limit exceeded", {"window_seconds": self._rate_limiter.window_seconds}
                ),
                **{"Retry-After": str(retry_after)},
            )

        parsed = urlsplit(target)
        path = parsed.path or "/"
        method = method.upper()
        if path not in {"/healthz", "/v1/metadata", "/v1/records"} and not path.startswith("/v1/records/"):
            return self._response(404, error_payload("API404", "route not found"))
        # HEAD is the body-less form of GET; the HTTP layer omits the body.
        if method not in {"GET", "HEAD"}:
            return self._response(405, error_payload("API405", "this API is read-only"), Allow="GET, HEAD")
        if path == "/healthz":
            return self._response(
                200,
                {
                    "status": "ok",
                    "api": APP_NAME,
                    "data_status": "valid",
                    "storage": "local_bronze_fixture",
                    "schema_version": self.dataset.schema_version,
                },
            )
        if not self._authorized(request_headers):
            return self._response(
                401, error_payload("AUTH001", "Bearer authentication required"), **{"WWW-Authenticate": "Bearer"}
            )
        if path == "/v1/metadata":
            return self._response(200, self._metadata())
        if path == "/v1/records":
            parsed_query = self._parse_query(parsed.query)
            if isinstance(parsed_query, Response):
                return parsed_query
            category, limit, offset = parsed_query
            records = list(self.dataset.records)
            if category is not None:
                records = [record for record in records if record["category"] == category]
            total = len(records)
            selected = records[offset : offset + limit]
            return self._response(
                200,
                {
                    "schema_version": self.dataset.schema_version,
                    "dataset": self.dataset.dataset,
                    "data_status": "valid",
                    "records": selected,
                    "pagination": {
                        "limit": limit,
                        "offset": offset,
                        "total": total,
                        "returned": len(selected),
                        "has_more": offset + len(selected) < total,
                    },
                    "lineage": {
                        "manifest_version": self.dataset.lineage.manifest_version,
                        "bronze_object": self.dataset.lineage.bronze_object,
                        "bronze_sha256": self.dataset.lineage.bronze_sha256,
                    },
                },
            )

        record_id = unquote(path.removeprefix("/v1/records/"))
        if not record_id or "/" in record_id:
            return self._response(404, error_payload("API404", "record not found"))
        record = self.dataset.get(record_id)
        if record is None:
            return self._response(404, error_payload("API404", "record not found", {"id": record_id}))
        return self._response(
            200,
            {
                "schema_version": self.dataset.schema_version,
                "dataset": self.dataset.dataset,
                "data_status": "valid",
                "record": record,
                "lineage": {
                    "manifest_version": self.dataset.lineage.manifest_version,
                    "bronze_object": self.dataset.lineage.bronze_object,
                    "bronze_sha256": self.dataset.lineage.bronze_sha256,
                },
            },
        )


class DataApiServer(ThreadingHTTPServer):
    """HTTP server carrying the application service as explicit state."""

    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], service: ApiService) -> None:
        super().__init__(address, DataApiRequestHandler)
        self.service = service


class DataApiRequestHandler(BaseHTTPRequestHandler):
    server: DataApiServer
    server_version = "book-data-api/0.1"
    sys_version = ""

    def _dispatch(self) -> None:
        headers = {key: value for key, value in self.headers.items()}
        response = self.server.service.handle(
            self.command,
            self.path,
            headers,
            client_id=self.client_address[0],
        )
        body = json.dumps(response.payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        self.send_response(response.status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self) -> None:
        self._dispatch()

    def do_HEAD(self) -> None:
        self._dispatch()

    def do_POST(self) -> None:
        self._dispatch()

    def do_PUT(self) -> None:
        self._dispatch()

    def do_PATCH(self) -> None:
        self._dispatch()

    def do_DELETE(self) -> None:
        self._dispatch()

    def log_message(self, format: str, *args: Any) -> None:
        """Keep the local test server quiet; callers own structured logs."""


def create_server(service: ApiService, host: str = "127.0.0.1", port: int = 0) -> DataApiServer:
    return DataApiServer((host, port), service)

