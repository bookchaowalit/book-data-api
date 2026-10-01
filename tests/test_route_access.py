"""Route access matrix for the read-only data API.

ROUTE_ACCESS is the table `_route` dispatches on. These tests pin it, forbid
state-changing methods, and call every route with every method as an
anonymous caller, with a wrong token and with the read token.
"""

from __future__ import annotations

import io
import json
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from book_data_api import cli
from book_data_api.api import PUBLIC, READ_METHODS, READER, ROUTE_ACCESS, ApiService, route_pattern
from book_data_api.store import load_dataset

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TOKEN = "matrix-read-token"
EXPECTED = {
    "/healthz": PUBLIC,
    "/v1/metadata": READER,
    "/v1/records": READER,
    "/v1/records/{id}": READER,
}
ALL_METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")


class RouteAccessMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dataset = load_dataset(REPOSITORY_ROOT)
        self.service = ApiService(self.dataset, read_token=TOKEN, rate_limit=10_000)
        self.sample = {
            "/healthz": "/healthz",
            "/v1/metadata": "/v1/metadata",
            "/v1/records": "/v1/records?limit=1",
            "/v1/records/{id}": "/v1/records/" + self.dataset.records[0]["id"],
        }

    def test_table_is_pinned_and_read_only(self) -> None:
        self.assertEqual(ROUTE_ACCESS, EXPECTED)
        self.assertEqual(READ_METHODS, frozenset({"GET", "HEAD"}))

    def test_every_route_resolves_to_its_own_pattern(self) -> None:
        for pattern, target in self.sample.items():
            self.assertEqual(route_pattern(target.split("?")[0]), pattern)
        for path in ("/", "/v1", "/v1/", "/v1/records/", "/healthz/x", "/admin", "/v2/records"):
            with self.subTest(path=path):
                self.assertNotEqual(self.service.handle("GET", path, {"Authorization": f"Bearer {TOKEN}"}).status, 200)

    def test_every_route_method_and_caller(self) -> None:
        callers = {
            "anonymous": {},
            "wrong-token": {"Authorization": "Bearer wrong"},
            "reader": {"Authorization": f"Bearer {TOKEN}"},
        }
        for pattern, level in ROUTE_ACCESS.items():
            target = self.sample[pattern]
            for method in ALL_METHODS:
                for caller, headers in callers.items():
                    with self.subTest(route=pattern, method=method, caller=caller):
                        status = self.service.handle(method, target, headers).status
                        if method not in READ_METHODS:
                            self.assertEqual(status, 405)
                        elif level == PUBLIC or caller == "reader":
                            self.assertEqual(status, 200)
                        else:
                            self.assertEqual(status, 401)


class UnauthenticatedBindTests(unittest.TestCase):
    def _serve(self, *args: str) -> tuple[int, dict]:
        with patch.dict(os.environ, {"BOOK_DATA_API_TOKEN": ""}), redirect_stdout(io.StringIO()) as out:
            code = cli.main(["serve", "--port", "0", "--allow-unauthenticated-local", *args])
        return code, json.loads(out.getvalue())

    def test_unauthenticated_mode_refuses_non_loopback_hosts(self) -> None:
        for host in ("0.0.0.0", "::", "192.168.1.10"):
            with self.subTest(host=host):
                code, payload = self._serve("--host", host)
                self.assertEqual(code, 2)
                self.assertEqual(payload["error"]["code"], "CONFIG002")


if __name__ == "__main__":
    unittest.main()
