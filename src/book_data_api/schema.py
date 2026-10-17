"""Versioned data and error contracts for the reference API."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .config import DATASET_NAME, SCHEMA_VERSION


class DataContractError(ValueError):
    """Raised when a fixture or lineage document violates the contract."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def error_payload(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the stable error envelope used by CLI and HTTP responses."""

    return {"error": {"code": code, "message": message, "details": details or {}}}


def _object(value: Any, *, code: str, message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DataContractError(code, message)
    return value


# Zero-width space/joiners, word joiner, BOM and soft hyphen: invisible and not
# removed by ``str.strip()``, so "\u200b" used to count as a non-empty value.
_INVISIBLE = re.compile("[\u00ad\u200b-\u200d\u2060\ufeff]")


def _non_empty_string(value: Any, *, field: str, code: str) -> str:
    if not isinstance(value, str) or not _INVISIBLE.sub("", value).strip():
        raise DataContractError(code, f"{field} must be a non-empty string", {"field": field})
    return value


def _observed_at(value: Any) -> str:
    result = _non_empty_string(value, field="observed_at", code="SCHEMA003")
    try:
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataContractError("SCHEMA003", "observed_at must be ISO-8601", {"field": "observed_at"}) from exc
    if parsed.tzinfo is None:
        raise DataContractError("SCHEMA003", "observed_at must include a timezone", {"field": "observed_at"})
    return result


def validate_record(value: Any, *, index: int) -> dict[str, str]:
    """Validate one resource record and return a normalized copy."""

    record = _object(value, code="SCHEMA001", message=f"record {index} must be an object")
    required = {"id", "name", "category", "observed_at", "source_url"}
    if set(record) != required:
        raise DataContractError(
            "SCHEMA002",
            f"record {index} fields do not match resource.v1",
            {"index": index, "expected_fields": sorted(required), "actual_fields": sorted(record)},
        )
    return {
        "id": _non_empty_string(record["id"], field="id", code="SCHEMA003"),
        "name": _non_empty_string(record["name"], field="name", code="SCHEMA003"),
        "category": _non_empty_string(record["category"], field="category", code="SCHEMA003"),
        "observed_at": _observed_at(record["observed_at"]),
        "source_url": _non_empty_string(record["source_url"], field="source_url", code="SCHEMA003"),
    }


def validate_records(value: Any, *, field: str = "records") -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise DataContractError("SCHEMA004", f"{field} must be an array", {"field": field})
    records = [validate_record(item, index=index) for index, item in enumerate(value)]
    ids = [record["id"] for record in records]
    if len(ids) != len(set(ids)):
        raise DataContractError("SCHEMA005", f"{field} contains duplicate ids", {"field": field})
    return records


def validate_source_document(value: Any) -> list[dict[str, str]]:
    return validate_records(value, field="source_records")


def validate_bronze_document(value: Any) -> tuple[str, str, list[dict[str, str]]]:
    document = _object(value, code="SCHEMA010", message="bronze document must be an object")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise DataContractError(
            "SCHEMA011",
            "bronze schema_version is unsupported",
            {"expected": SCHEMA_VERSION, "actual": document.get("schema_version")},
        )
    if document.get("dataset") != DATASET_NAME:
        raise DataContractError(
            "SCHEMA012",
            "bronze dataset is unsupported",
            {"expected": DATASET_NAME, "actual": document.get("dataset")},
        )
    return SCHEMA_VERSION, DATASET_NAME, validate_records(document.get("records"))


def validate_manifest(value: Any) -> dict[str, Any]:
    manifest = _object(value, code="LINEAGE010", message="manifest must be an object")
    required = {
        "manifest_version",
        "source",
        "dataset",
        "source_object",
        "bronze_object",
        "source_sha256",
        "bronze_sha256",
        "record_count",
    }
    if set(manifest) != required:
        raise DataContractError(
            "LINEAGE011",
            "manifest fields do not match the lineage contract",
            {"expected_fields": sorted(required), "actual_fields": sorted(manifest)},
        )
    for field in ("manifest_version", "source", "dataset", "source_object", "bronze_object"):
        _non_empty_string(manifest[field], field=field, code="LINEAGE012")
    for field in ("source_sha256", "bronze_sha256"):
        digest = _non_empty_string(manifest[field], field=field, code="LINEAGE013")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise DataContractError("LINEAGE014", f"{field} must be a lowercase SHA-256 digest", {"field": field})
    if not isinstance(manifest["record_count"], int) or manifest["record_count"] < 0:
        raise DataContractError("LINEAGE015", "record_count must be a non-negative integer")
    if manifest["dataset"] != DATASET_NAME:
        raise DataContractError("LINEAGE016", "manifest dataset is unsupported", {"expected": DATASET_NAME})
    return manifest
