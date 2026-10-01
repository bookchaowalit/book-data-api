"""Command-line entry points for the local reference data API."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from urllib.parse import urlencode

from .api import ApiService, create_server
from .config import DEFAULT_HOST, DEFAULT_PORT, LOOPBACK_HOSTS, TOKEN_ENV
from .schema import DataContractError
from .store import load_dataset


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))


def _service(args: argparse.Namespace, *, read_token: str | None = None) -> ApiService:
    return ApiService(load_dataset(args.root), read_token=read_token)


def _root_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=None, help="repository root containing data/ (defaults to this app)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="book-data-api", description="Local lineage-aware read-only data API")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="verify the fixture, schema, and lineage manifest")
    _root_argument(validate)

    metadata = subparsers.add_parser("metadata", help="print dataset metadata")
    _root_argument(metadata)
    metadata.add_argument("--json", action="store_true", help="kept for an explicit machine-readable invocation")

    records = subparsers.add_parser("records", help="read versioned records")
    _root_argument(records)
    records.add_argument("--category")
    records.add_argument("--limit", type=int, default=50)
    records.add_argument("--offset", type=int, default=0)
    records.add_argument("--json", action="store_true", help="kept for an explicit machine-readable invocation")

    serve = subparsers.add_parser("serve", help="serve the read-only HTTP API")
    _root_argument(serve)
    serve.add_argument("--host", default=DEFAULT_HOST)
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument(
        "--allow-unauthenticated-local",
        action="store_true",
        help="allow local-only development without BOOK_DATA_API_TOKEN",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            dataset = load_dataset(args.root)
            _print(
                {
                    "status": "ok",
                    "schema_version": dataset.schema_version,
                    "dataset": dataset.dataset,
                    "records_count": len(dataset.records),
                    "lineage": dataset.lineage.as_dict(),
                }
            )
            return 0
        if args.command == "metadata":
            response = _service(args).handle("GET", "/v1/metadata")
            _print(response.payload)
            return 0 if response.status == 200 else 1
        if args.command == "records":
            query = {"limit": args.limit, "offset": args.offset}
            if args.category is not None:
                query["category"] = args.category
            target = "/v1/records?" + urlencode(query)
            response = _service(args).handle("GET", target)
            _print(response.payload)
            return 0 if response.status == 200 else 1
        if args.command == "serve":
            token = os.environ.get(TOKEN_ENV) or None
            if token is None and not args.allow_unauthenticated_local:
                _print(
                    {
                        "error": {
                            "code": "CONFIG001",
                            "message": f"set {TOKEN_ENV} or pass --allow-unauthenticated-local for local development",
                        }
                    }
                )
                return 2
            if token is None and args.host not in LOOPBACK_HOSTS:
                # Unauthenticated mode is for this machine only: never serve
                # the data openly on a LAN or public interface.
                _print(
                    {
                        "error": {
                            "code": "CONFIG002",
                            "message": f"--allow-unauthenticated-local requires a loopback --host; set {TOKEN_ENV} to bind {args.host}",
                        }
                    }
                )
                return 2
            service = _service(args, read_token=token)
            # One JSON access line per request on stderr (no headers, tokens or queries).
            logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
            server = create_server(service, args.host, args.port)
            print(f"{server.server_address[0]}:{server.server_address[1]}", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                return 0
            finally:
                server.server_close()
            return 0
    except DataContractError as exc:
        _print({"error": {"code": exc.code, "message": exc.message, "details": exc.details}})
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
