"""Run a pinned project signer under Worker-only Landlock/seccomp confinement."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import signal
import sys
from pathlib import Path

from .action_profile import validate_action_profile
from .errors import CloudBlocked
from .source_export import MAX_BYTES, _open_root, _read, validate_export

_MAX_INPUT = 1024 * 1024  # Two independently bounded provider responses plus metadata.
_MAX_OUTPUT = 350000


def _blocked(code="CONTROLLED_ACTION_SIGNER_UNAVAILABLE"):
    return CloudBlocked(code, "Trusted project signer could not be verified or confined")


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


class ActionCredentials:
    def __init__(self, authority):
        self.authority = authority

    async def api_key(self, _action, *, identity_id):
        return await self.authority.materialize_credential(identity_id=identity_id, role="api_key")


class ActionSigner:
    def __init__(self, *, source_root: Path, export_policy: dict, action_profile: dict, authority, timeout=10):
        self.source_root = Path(source_root)
        self.export_policy = validate_export(export_policy)
        self.profile = validate_action_profile(action_profile)
        self.authority = authority
        self._public_keys = {}
        if type(timeout) is not int or not 1 <= timeout <= 15:
            raise _blocked()
        self.timeout = timeout

    def _source(self, action, *, observer=False):
        if action not in self.profile["actions"]:
            raise _blocked()
        selected = action["observer"] if observer else action
        expected = {item["path"]: item["sha256"] for item in self.export_policy["framework"]}
        if expected.get(selected["adapter_path"]) != selected["adapter_sha256"]:
            raise _blocked("CONTROLLED_ACTION_ADAPTER_MISMATCH")
        root = None
        try:
            root = _open_root(self.source_root)
            seen, total = set(), 0
            for directory, subdirs, files in os.walk(self.source_root, followlinks=False):
                for name in subdirs:
                    if (Path(directory) / name).is_symlink():
                        raise ValueError
                for name in files:
                    path = (Path(directory) / name).relative_to(self.source_root).as_posix()
                    if path not in expected or path in seen:
                        raise ValueError
                    raw, _ = _read(root, path, expected[path], MAX_BYTES - total)
                    total += len(raw)
                    seen.add(path)
            if seen != set(expected):
                raise ValueError
            import_root = self.source_root / selected["adapter_import_root"]
            adapter = self.source_root / selected["adapter_path"]
            if (not import_root.is_dir() or import_root.resolve(strict=True) != import_root
                    or adapter.resolve(strict=True) != adapter):
                raise ValueError
            return import_root, adapter
        except (OSError, ValueError, TypeError):
            raise _blocked("CONTROLLED_ACTION_ADAPTER_MISMATCH") from None
        finally:
            if root is not None:
                os.close(root)

    async def _run(self, action, document, *, observer=False):
        import_root, adapter = self._source(action, observer=observer)
        try:
            raw = json.dumps(document, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
            if not 0 < len(raw) <= _MAX_INPUT:
                raise ValueError
            process = await asyncio.create_subprocess_exec(sys.executable, "-I", "-m", "hypertest.cloud.signer_guard",
                str(self.source_root), str(import_root), str(adapter), stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=_MAX_OUTPUT + 1,
                env={"PATH": os.defpath, "LANG": "C.UTF-8", "HOME": "/nonexistent",
                     "PYTHONDONTWRITEBYTECODE": "1"}, start_new_session=True)
            try:
                async with asyncio.timeout(self.timeout):
                    process.stdin.write(raw)
                    await process.stdin.drain()
                    process.stdin.close()
                    output = await process.stdout.readline()
                    if not output.endswith(b"\n") or len(output) > _MAX_OUTPUT:
                        raise ValueError
                    if await process.stdout.read(1) or await process.wait() != 0:
                        raise ValueError
            except BaseException:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()
                raise
            value = json.loads(output, object_pairs_hook=_unique)
            if not isinstance(value, dict):
                raise ValueError
            return value
        except (OSError, ValueError, TypeError, UnicodeError, TimeoutError, asyncio.LimitOverrunError):
            raise _blocked() from None

    async def prepare(self, action, client_ref, unique_ref, *, identity_id):
        from cryptography.hazmat.primitives import serialization

        protocol = action["adapter_protocol"]
        key = await self.authority.materialize_credential(identity_id=identity_id, role="signing_key")
        if not isinstance(key, bytes) or not 0 < len(key) <= 65536:
            raise _blocked()
        try:
            if key.strip().startswith(b"-----"):
                private = serialization.load_pem_private_key(key, password=None)
            else:
                private = serialization.load_der_private_key(base64.b64decode(b"".join(key.split()), validate=True), password=None)
            public = private.public_key().public_bytes(serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")
            document = {"profile": protocol["prepare"], **action["parameters"],
                protocol["client_ref_field"]: client_ref, protocol["unique_ref_field"]: unique_ref,
                protocol["secret_field"]: key.decode("utf-8")}
            output = await self._run(action, document)
            if (set(output) != {"profile", "path", "body_base64", "body_sha256"}
                    or output["profile"] != protocol["prepared"] or output["path"] != action["path"]):
                raise ValueError
            body = base64.b64decode(output["body_base64"], validate=True)
            if len(body) > 131072 or hashlib.sha256(body).hexdigest() != output["body_sha256"]:
                raise ValueError
            self._public_keys[identity_id] = public
            return body
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise _blocked() from None
        finally:
            del key

    async def verify(self, action, body, *, identity_id):
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa

        protocol = action["adapter_protocol"]
        public = self._public_keys.get(identity_id)
        if not isinstance(public, str):
            raise _blocked()
        try:
            # Independently verify the actual frozen body, not just the
            # project adapter's self-reported verification result. PKCS#1 v1.5
            # is deterministic and prevents an adapter using sign as an
            # unverified covert channel for the private key.
            document = json.loads(body, object_pairs_hook=_unique)
            if not isinstance(document, dict) or action not in self.profile["actions"]:
                raise ValueError
            public_key = serialization.load_pem_public_key(public.encode("ascii"))
            if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size < 2048:
                raise ValueError
            signature = base64.b64decode(document[action["identity_fields"]["signature"]], validate=True)
            parts = []
            excluded = action["signature_policy"]["excluded_fields"]
            for key in sorted(document):
                if key in excluded:
                    continue
                item = document[key]
                if item is None:
                    value = ""
                elif type(item) is bool:
                    value = "true" if item else "false"
                elif type(item) is int or isinstance(item, str):
                    value = str(item)
                else:
                    raise ValueError
                if value:
                    parts.append(key + "=" + value)
            public_key.verify(signature, "&".join(parts).encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
        except (InvalidSignature, ValueError, KeyError, TypeError, UnicodeError):
            return False
        output = await self._run(action, {"profile": protocol["verify"],
            "body_base64": base64.b64encode(body).decode("ascii"), "public_key": public})
        return set(output) == {"profile", "valid"} and output["profile"] == protocol["verified"] and output["valid"] is True

    async def observe(self, action, client_ref, order_response, details_response):
        observer = action["observer"]
        return await self._run(action, {"profile": observer["profile"],
            "expected": {**observer["expectations"], "client_order_id": client_ref},
            "order_response": order_response, "details_response": details_response}, observer=True)

    async def preflight(self, action, address_response, balance_response):
        observer = action["observer"]
        return await self._run(action, {"profile": observer["preflight_profile"],
            "expected": observer["expectations"], "address_response": address_response,
            "balance_response": balance_response}, observer=True)
