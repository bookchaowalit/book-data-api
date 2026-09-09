from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from book_data_api.api import ApiService, create_server
from book_data_api.schema import DataContractError
from book_data_api.store import load_dataset


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


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
        manifest_path = REPOSITORY_ROOT / "data" / "manifests" / "resource_records.v1.manifest.json"
        original = manifest_path.read_text(encoding="utf-8")
        try:
            manifest_path.write_text(original.replace('"record_count": 2', '"record_count": 3'), encoding="utf-8")
            with self.assertRaisesRegex(DataContractError, "record_count"):
                load_dataset(REPOSITORY_ROOT)
        finally:
            manifest_path.write_text(original, encoding="utf-8")


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
        self.assertEqual(mutation.headers["Allow"], "GET")

    def test_rate_limit_returns_retry_hint(self) -> None:
        service = ApiService(load_dataset(REPOSITORY_ROOT), read_token=None, rate_limit=1)
        self.assertEqual(service.handle("GET", "/healthz", client_id="test-client").status, 200)
        response = service.handle("GET", "/healthz", client_id="test-client")
        self.assertEqual(response.status, 429)
        self.assertIn("Retry-After", response.headers)


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
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


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


if __name__ == "__main__":
    unittest.main()
