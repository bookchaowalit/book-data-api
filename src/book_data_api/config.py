"""Configuration constants for the local data API."""

from pathlib import Path

APP_NAME = "book-data-api"
API_VERSION = "v1"
SCHEMA_VERSION = "resource.v1"
DATASET_NAME = "reference_resources"
DEFAULT_HOST = "127.0.0.1"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
DEFAULT_PORT = 8080
TOKEN_ENV = "BOOK_DATA_API_TOKEN"

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parent
MANIFEST_PATH = REPOSITORY_ROOT / "data" / "manifests" / "resource_records.v1.manifest.json"
