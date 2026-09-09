"""Read-only lake-first fixture loading with manifest verification."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import DATASET_NAME, MANIFEST_PATH, SCHEMA_VERSION
from .schema import (
    DataContractError,
    validate_bronze_document,
    validate_manifest,
    validate_source_document,
)


@dataclass(frozen=True)
class Lineage:
    manifest_version: str
    source: str
    source_object: str
    bronze_object: str
    source_sha256: str
    bronze_sha256: str
    record_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "source": self.source,
            "source_object": self.source_object,
            "bronze_object": self.bronze_object,
            "source_sha256": self.source_sha256,
            "bronze_sha256": self.bronze_sha256,
            "record_count": self.record_count,
        }


@dataclass(frozen=True)
class Dataset:
    schema_version: str
    dataset: str
    records: tuple[dict[str, str], ...]
    lineage: Lineage

    def get(self, record_id: str) -> dict[str, str] | None:
        for record in self.records:
            if record["id"] == record_id:
                return dict(record)
        return None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DataContractError("STORE001", "required data object is missing", {"path": str(path)}) from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataContractError("STORE002", "required data object is unreadable", {"path": str(path)}) from exc


def _safe_path(root: Path, relative_name: str, *, field: str) -> tuple[Path, str]:
    candidate = (root / relative_name).resolve()
    try:
        relative = candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise DataContractError("LINEAGE017", f"{field} must stay inside the repository", {"field": field}) from exc
    if Path(relative_name).is_absolute() or str(relative) != relative_name:
        raise DataContractError("LINEAGE018", f"{field} must be a normalized relative path", {"field": field})
    return candidate, str(relative)


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise DataContractError("STORE003", "required data object cannot be hashed", {"path": str(path)}) from exc


def load_dataset(root: str | Path | None = None) -> Dataset:
    """Load and verify the fixture lake without mutating any data."""

    repository_root = Path(root or MANIFEST_PATH.parents[2]).resolve()
    manifest_path = repository_root / "data" / "manifests" / "resource_records.v1.manifest.json"
    manifest = validate_manifest(_read_json(manifest_path))
    source_path, source_object = _safe_path(repository_root, manifest["source_object"], field="source_object")
    bronze_path, bronze_object = _safe_path(repository_root, manifest["bronze_object"], field="bronze_object")

    source_sha256 = _sha256(source_path)
    bronze_sha256 = _sha256(bronze_path)
    if source_sha256 != manifest["source_sha256"]:
        raise DataContractError(
            "LINEAGE001",
            "source object digest does not match manifest",
            {"object": source_object, "expected": manifest["source_sha256"], "actual": source_sha256},
        )
    if bronze_sha256 != manifest["bronze_sha256"]:
        raise DataContractError(
            "LINEAGE002",
            "bronze object digest does not match manifest",
            {"object": bronze_object, "expected": manifest["bronze_sha256"], "actual": bronze_sha256},
        )

    source_records = validate_source_document(_read_json(source_path))
    schema_version, dataset, bronze_records = validate_bronze_document(_read_json(bronze_path))
    if schema_version != SCHEMA_VERSION or dataset != DATASET_NAME:
        raise DataContractError("STORE004", "loaded dataset does not match configured contract")
    if source_records != bronze_records:
        raise DataContractError(
            "LINEAGE003",
            "bronze records do not match the source snapshot",
            {"source_count": len(source_records), "bronze_count": len(bronze_records)},
        )
    if manifest["record_count"] != len(bronze_records):
        raise DataContractError(
            "LINEAGE004",
            "manifest record_count does not match the bronze object",
            {"expected": manifest["record_count"], "actual": len(bronze_records)},
        )

    lineage = Lineage(
        manifest_version=manifest["manifest_version"],
        source=manifest["source"],
        source_object=source_object,
        bronze_object=bronze_object,
        source_sha256=source_sha256,
        bronze_sha256=bronze_sha256,
        record_count=len(bronze_records),
    )
    return Dataset(schema_version, dataset, tuple(bronze_records), lineage)
