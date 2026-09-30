from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from book_data_api import cli
from book_data_api.api import ApiService, _RateLimiter, create_server
from book_data_api.schema import DataContractError
from book_data_api.store import load_dataset

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path("data") / "manifests" / "resource_records.v1.manifest.json"


@contextmanager
def fixture_copy():
    """Yield a temporary repository root holding a copy of data/ so tests never edit fixtures."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        shutil.copytree(REPOSITORY_ROOT / "data", root / "data")
        yield root


class StoreContractTests(unittest.TestCase):
    def test_fixture_is_versioned_and_lineage_verified(self) -> None:
        dataset = load_dataset(REPOSITORY_ROOT)
        self.assertEqual(dataset.schema_version, "resource.v1")
        self.assertEqual(dataset.dataset, "reference_resources")
        self.assertEqual(len(dataset.records), 2)
        self.assertEqual(dataset.lineage.record_count, 2)
        self.assertEqual(dataset.lineage.source, "local-sanitized-fixture")
        self.assertEqual(dataset.get("resource-001")["name"], "Ledger Lens")

    def test_tampered_manifest_fails_closed(self) -> None:
        with fixture_copy() as root:
            manifest_path = root / MANIFEST
            original = manifest_path.read_text(encoding="utf-8")
            manifest_path.write_text(original.replace('"record_count": 2', '"record_count": 3'), encoding="utf-8")
            with self.assertRaisesRegex(DataContractError, "record_count"):
                load_dataset(root)

    def test_tampered_bronze_digest_fails_closed(self) -> None:
        with fixture_copy() as root:
            bronze = root / "data" / "bronze" / "resource_records.v1.json"
            bronze.write_text(bronze.read_text(encoding="utf-8").replace("Ledger Lens", "Ledger Lies"), encoding="utf-8")
            with self.assertRaises(DataContractError) as caught:
                load_dataset(root)
            self.assertEqual(caught.exception.code, "LINEAGE002")

    def test_manifest_paths_must_stay_inside_repository(self) -> None:
        cases = {
            "../outside.json": "LINEAGE017",
            "data/./landing/source_records.json": "LINEAGE018",
        }
        for source_object, code in cases.items():
            with self.subTest(source_object=source_object), fixture_copy() as root:
                manifest_path = root / MANIFEST
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["source_object"] = source_object
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaises(DataContractError) as caught:
                    load_dataset(root)
                self.assertEqual(caught.exception.code, code)

    def test_source_and_bronze_must_match_even_with_valid_digests(self) -> None:
        with fixture_copy() as root:
            source_path = root / "data" / "landing" / "source_records.json"
            records = json.loads(source_path.read_text(encoding="utf-8"))
            records[0]["name"] = "Changed upstream"
            source_path.write_text(json.dumps(records), encoding="utf-8")
            manifest_path = root / MANIFEST
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["source_sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(DataContractError) as caught:
                load_dataset(root)
            self.assertEqual(caught.exception.code, "LINEAGE003")

    def test_missing_manifest_is_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as empty, self.assertRaises(DataContractError) as caught:
            load_dataset(empty)
        self.assertEqual(caught.exception.code, "STORE001")

    def test_repository_fixture_is_not_modified_by_tests(self) -> None:
        manifest = json.loads((REPOSITORY_ROOT / MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual(manifest["record_count"], 2)


class ApiServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.token = "test-token-generated-in-memory"
        self.service = ApiService(load_dataset(REPOSITORY_ROOT), read_token=self.token, rate_limit=20)
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_health_is_public_but_data_requires_authentication(self) -> None:
        health = self.service.handle("GET", "/healthz")
        metadata = self.service.handle("GET", "/v1/metadata")
        self.assertEqual(health.status, 200)
        self.assertEqual(health.payload["status"], "ok")
        self.assertEqual(metadata.status, 401)
        self.assertEqual(metadata.payload["error"]["code"], "AUTH001")

    def test_records_are_filterable_and_paginated(self) -> None:
        response = self.service.handle("GET", "/v1/records?category=developer-tools&limit=1", self.headers)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.payload["pagination"], {"limit": 1, "offset": 0, "total": 1, "returned": 1, "has_more": False})
        self.assertEqual(response.payload["records"][0]["id"], "resource-001")
        self.assertEqual(response.payload["schema_version"], "resource.v1")

    def test_invalid_query_missing_record_and_mutation_are_bounded(self) -> None:
        invalid = self.service.handle("GET", "/v1/records?limit=0", self.headers)
        missing = self.service.handle("GET", "/v1/records/unknown", self.headers)
        mutation = self.service.handle("POST", "/v1/records", self.headers)
        self.assertEqual(invalid.status, 400)
        self.assertEqual(missing.status, 404)
        self.assertEqual(mutation.status, 405)
        self.assertEqual(mutation.headers["Allow"], "GET, HEAD")

    def test_wrong_token_and_query_validation(self) -> None:
        wrong = self.service.handle("GET", "/v1/records", {"Authorization": "Bearer nope"})
        self.assertEqual(wrong.status, 401)
        self.assertEqual(wrong.headers["WWW-Authenticate"], "Bearer")
        for query, code in (
            ("limit=101", "API003"),
            ("limit=x", "API002"),
            ("offset=-1", "API004"),
            ("limit=1&limit=2", "API001"),
        ):
            with self.subTest(query=query):
                response = self.service.handle("GET", "/v1/records?" + query, self.headers)
                self.assertEqual(response.status, 400)
                self.assertEqual(response.payload["error"]["code"], code)

    def test_offset_pagination_reports_has_more(self) -> None:
        first = self.service.handle("GET", "/v1/records?limit=1", self.headers).payload
        second = self.service.handle("GET", "/v1/records?limit=1&offset=1", self.headers).payload
        self.assertTrue(first["pagination"]["has_more"])
        self.assertFalse(second["pagination"]["has_more"])
        self.assertNotEqual(first["records"][0]["id"], second["records"][0]["id"])
        beyond = self.service.handle("GET", "/v1/records?offset=10", self.headers).payload
        self.assertEqual(beyond["records"], [])
        self.assertEqual(beyond["pagination"]["returned"], 0)

    def test_unknown_routes_and_nested_ids_are_404(self) -> None:
        for target in ("/", "/v1", "/v1/records/", "/v1/records/resource-001/extra", "/v2/records"):
            with self.subTest(target=target):
                self.assertEqual(self.service.handle("GET", target, self.headers).status, 404)

    def test_head_is_allowed_like_get(self) -> None:
        self.assertEqual(self.service.handle("HEAD", "/healthz").status, 200)
        self.assertEqual(self.service.handle("HEAD", "/v1/metadata").status, 401)
        self.assertEqual(self.service.handle("HEAD", "/v1/metadata", self.headers).status, 200)

    def test_records_are_copies_not_shared_state(self) -> None:
        record = self.service.handle("GET", "/v1/records/resource-001", self.headers).payload["record"]
        record["name"] = "mutated by a caller"
        again = self.service.handle("GET", "/v1/records/resource-001", self.headers).payload["record"]
        self.assertEqual(again["name"], "Ledger Lens")

    def test_rate_limit_returns_retry_hint(self) -> None:
        service = ApiService(load_dataset(REPOSITORY_ROOT), read_token=None, rate_limit=1)
        self.assertEqual(service.handle("GET", "/healthz", client_id="test-client").status, 200)
        response = service.handle("GET", "/healthz", client_id="test-client")
        self.assertEqual(response.status, 429)
        self.assertIn("Retry-After", response.headers)
        self.assertEqual(response.payload["error"]["details"]["window_seconds"], 60)

    def test_rate_limiter_sweeps_idle_clients(self) -> None:
        limiter = _RateLimiter(1, window_seconds=0.01)
        limiter.sweep_threshold = 8
        for index in range(8):
            limiter.allow(f"client-{index}")
        time.sleep(0.02)
        limiter.allow("new-client")
        self.assertEqual(limiter.tracked_clients(), 1)


class HttpServerTests(unittest.TestCase):
    def test_http_server_exposes_record_contract(self) -> None:
        token = "http-test-token-generated-in-memory"
        server = create_server(ApiService(load_dataset(REPOSITORY_ROOT), read_token=token), port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/v1/records/resource-002"
            request = Request(url, headers={"Authorization": f"Bearer {token}"})
            with urlopen(request, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertEqual(payload["record"]["name"], "Field Atlas")
            self.assertEqual(payload["data_status"], "valid")

            head = Request(url, method="HEAD", headers={"Authorization": f"Bearer {token}"})
            with urlopen(head, timeout=3) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.read(), b"")
                self.assertGreater(int(response.headers["Content-Length"]), 0)

            post = Request(url, method="POST", data=b"{}", headers={"Authorization": f"Bearer {token}"})
            with self.assertRaises(HTTPError) as caught:
                urlopen(post, timeout=3)
            self.assertEqual(caught.exception.code, 405)
            self.assertEqual(caught.exception.headers["Allow"], "GET, HEAD")
            caught.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


class AccessLogTests(unittest.TestCase):
    def test_access_log_is_structured_and_never_carries_secrets(self) -> None:
        token = "access-log-token-generated-in-memory"
        server = create_server(ApiService(load_dataset(REPOSITORY_ROOT), read_token=token), port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with self.assertLogs("book_data_api.access", level="INFO") as captured:
                ok = Request(base + "/v1/records?category=developer-tools&limit=2",
                             headers={"Authorization": f"Bearer {token}"})
                with urlopen(ok, timeout=3) as response:
                    body = response.read()
                with self.assertRaises(HTTPError) as caught:
                    urlopen(Request(base + "/v1/metadata", headers={"Authorization": "Bearer wrong-secret"}), timeout=3)
                caught.exception.close()
                head = Request(base + "/healthz", method="HEAD")
                with urlopen(head, timeout=3):
                    pass
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

        records = [json.loads(line.split(":", 2)[2]) for line in captured.output]
        self.assertEqual([(r["method"], r["path"], r["status"]) for r in records], [
            ("GET", "/v1/records", 200),
            ("GET", "/v1/metadata", 401),
            ("HEAD", "/healthz", 200),
        ])
        for record in records:
            self.assertEqual(set(record), {"event", "method", "path", "status", "latency_ms", "bytes"})
            self.assertGreaterEqual(record["latency_ms"], 0)
        self.assertEqual(records[0]["bytes"], len(body))
        self.assertEqual(records[2]["bytes"], 0)
        joined = "\n".join(captured.output)
        for secret in (token, "wrong-secret", "Bearer", "category=", "developer-tools"):
            self.assertNotIn(secret, joined)

    def test_long_paths_are_truncated_in_the_access_log(self) -> None:
        from book_data_api.api import access_log_record

        record = access_log_record("get", "/v1/records/" + "x" * 1000 + "?token=abc", 404, 1.23456, 10)
        self.assertEqual(record["method"], "GET")
        self.assertLessEqual(len(record["path"]), 256 + 3)
        self.assertNotIn("token", json.dumps(record))
        self.assertEqual(record["latency_ms"], 1.235)


class CliTests(unittest.TestCase):
    def test_validate_command_is_machine_readable(self) -> None:
        env = dict(os.environ, PYTHONPATH=str(REPOSITORY_ROOT / "src"))
        result = subprocess.run(
            [sys.executable, "-m", "book_data_api.cli", "validate"],
            cwd=REPOSITORY_ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["records_count"], 2)

    def test_serve_refuses_to_start_without_token(self) -> None:
        with patch.dict(os.environ, {"BOOK_DATA_API_TOKEN": ""}), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(["serve", "--port", "0"]), 2)
        self.assertEqual(json.loads(out.getvalue())["error"]["code"], "CONFIG001")

    def test_records_command_reports_bad_query_and_broken_fixture(self) -> None:
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(["records", "--limit", "0"]), 1)
        self.assertEqual(json.loads(out.getvalue())["error"]["code"], "API003")
        with tempfile.TemporaryDirectory() as empty, redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(["validate", "--root", empty]), 1)
        self.assertEqual(json.loads(out.getvalue())["error"]["code"], "STORE001")


if __name__ == "__main__":
    unittest.main()
