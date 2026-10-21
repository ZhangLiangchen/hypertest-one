"""Operator CLI for ADR-017. It submits existing reports; it never runs tests."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx

from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.journal import Journal
from hypertest.interactive_client.journal import canonical as canonical_json
from hypertest.interactive_client.security import private_create, private_directory, private_read


def save_writer(path: Path, token: str):
    private_directory(path.parent)
    if path.exists():
        private_read(path, max_bytes=512)
    temporary = path.parent / (".native-key-" + secrets.token_hex(8))
    private_create(temporary, token.encode())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


class NativeClient:
    def __init__(self, api_url: str, operator_key_file: Path, journal_path: Path,
                 writer_key_file: Path | None = None, *, transport=None):
        parsed = urlsplit(api_url)
        if (parsed.username or parsed.password or parsed.query or parsed.fragment or
            parsed.scheme not in {"http", "https"} or not parsed.hostname or
            (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"})):
            raise ClientError("NATIVE_API_REQUIRES_HTTPS_OR_LOOPBACK")
        private_directory(journal_path.parent)
        if writer_key_file:
            private_directory(writer_key_file.parent)
        self.base = api_url.rstrip("/")
        self.writer_file = writer_key_file
        self.journal = Journal(journal_path)
        self.client = httpx.Client(headers={"X-Hypertest-Operator-Key": private_read(operator_key_file, max_bytes=512).decode().strip()},
                                   timeout=30, follow_redirects=False, transport=transport)

    def get(self, path: str):
        response = self.client.get(self.base + path)
        if response.status_code == 404:
            return {"status": "UNKNOWN", "reason": "NOT_FOUND_DOES_NOT_AUTHORIZE_REPLAY"}
        response.raise_for_status()
        return response.json()

    def submit(self, path: str, payload: dict, lookup: str, *, needs_writer=False, issues_writer=False):
        key = path + ":" + payload["idempotency_key"]
        identity = {"api_url": self.base, "path": path, "payload": payload, "lookup": lookup}
        # Raw reports remain in the SUT material files and server Artifact Store.
        # Keep only the immutable request identity and lookup pointer locally, so
        # repeated legal uploads cannot fill the private recovery ledger.
        pointer = {"api_url": self.base, "path": path, "idempotency_key": payload["idempotency_key"],
                   "lookup": lookup, "request_digest": hashlib.sha256(canonical_json(identity).encode()).hexdigest()}
        intent = self.journal.intent("native", key, pointer, identity=identity)
        if intent["state"] == "SUCCEEDED":
            return intent["result"]
        if intent["state"] in {"SENT", "UNKNOWN"}:
            # Only read back an existing operation after any response loss.
            result = self.get(lookup)
            return {"reconciliation_only": True, "original_result": result,
                    "instruction": "No POST was retried. Lost writer capability needs explicit Operator handoff."}
        if intent["state"] == "REJECTED":
            return intent["result"]
        if issues_writer and not self.writer_file:
            raise ClientError("WRITER_KEY_FILE_REQUIRED_BEFORE_SUBMISSION")
        headers = {}
        if needs_writer:
            if not self.writer_file:
                raise ClientError("NATIVE_WRITER_KEY_FILE_REQUIRED")
            headers["X-Hypertest-Native-Writer-Key"] = private_read(self.writer_file, max_bytes=512).decode().strip()
        self.journal.mark("native", key, "SENT")
        try:
            response = self.client.post(self.base + path, json=payload, headers=headers)
            if 400 <= response.status_code < 500:
                result = {"status": "REJECTED", "http_status": response.status_code, "detail": response.json().get("detail")}
                self.journal.mark("native", key, "REJECTED", result)
                return result
            response.raise_for_status()
            result = response.json()
            token = result.pop("writer_token", None)
            if token:
                save_writer(self.writer_file, token)
                result["writer_key_file"] = str(self.writer_file)
            self.journal.mark("native", key, "SUCCEEDED", result)
            return result
        except Exception:
            self.journal.mark("native", key, "UNKNOWN")
            raise ClientError("NATIVE_RESPONSE_UNKNOWN_QUERY_ORIGINAL_KEY") from None

    def close(self):
        self.client.close()
        self.journal.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--operator-key-file", required=True, type=Path)
    parser.add_argument("--journal", required=True, type=Path)
    parser.add_argument("--writer-key-file", type=Path)
    parser.add_argument("action", choices=["create", "get", "operation", "material", "submit", "evaluate", "handoff", "uncertain", "reconcile"])
    parser.add_argument("--input", type=Path, help="Reviewed JSON payload. Materials use explicit base64 bytes.")
    parser.add_argument("--run-id")
    parser.add_argument("--key")
    args = parser.parse_args()
    client = None
    try:
        client = NativeClient(args.api_url, args.operator_key_file, args.journal, args.writer_key_file)
        if args.action != "create" and not args.run_id:
            parser.error("--run-id is required")
        root = "/native-runs" + ("/" + quote(args.run_id, safe="") if args.run_id else "")
        if args.action in {"get", "operation", "material"}:
            if args.action != "get" and not args.key:
                parser.error("--key is required")
            suffix = "" if args.action == "get" else "/" + ("operations/" if args.action == "operation" else "materials/") + quote(args.key, safe="")
            result = client.get(root + suffix)
        else:
            if not args.input:
                parser.error("--input is required")
            payload = json.loads(args.input.read_text())
            if args.action == "create":
                path = "/native-runs"
                lookup = f"/native-runs/submissions/{quote(payload['project_id'], safe='')}/{quote(payload['idempotency_key'], safe='')}"
            else:
                suffixes = {"submit": "/executions", "evaluate": "/evaluate", "handoff": "/handoffs", "uncertain": "/uncertainties"}
                if args.action == "reconcile" and not args.key:
                    parser.error("reconcile requires the original UNKNOWN --key")
                suffix = "/uncertainties/" + quote(args.key, safe="") + "/reconcile" if args.action == "reconcile" else suffixes[args.action]
                path = root + suffix
                lookup = root + "/operations/" + quote(payload["idempotency_key"], safe="")
            result = client.submit(path, payload, lookup,
                needs_writer=args.action in {"submit", "evaluate", "uncertain"},
                issues_writer=args.action in {"create", "handoff"})
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ClientError, httpx.HTTPError, OSError, ValueError, KeyError):
        print(json.dumps({"error": "Native request failed; inspect private journal and query original key. No automatic retry."}))
        raise SystemExit(1) from None
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    main()
