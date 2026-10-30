"""Frozen, exact per-action inputs for the proposed authenticated broker.

Validation does not grant network access, materialize credentials, run a
project signer, or enable the broker. An Agent cannot amend this profile.
"""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit
from uuid import UUID

from .errors import CloudBlocked
from .http_profile import canonical_path, canonical_target, public_address
from .source_export import _path

PROFILE = "CONTROLLED_ACTIONS_V1"
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_HEX = re.compile(r"[a-f0-9]{64}\Z")
_COMMIT = re.compile(r"(?:[a-f0-9]{40}|[a-f0-9]{64})\Z")
_BODY_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_PROTOCOL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,127}\Z")
_ACTION = {"action_key", "method", "path", "parameters", "expected_body", "identity_fields",
           "credential_version_ids", "framework_commit", "adapter_path", "adapter_import_root", "adapter_sha256", "adapter_protocol", "signature_policy", "observer"}


def _blocked() -> CloudBlocked:
    return CloudBlocked("CONTROLLED_ACTION_PROFILE_INVALID", "Controlled action inputs are outside the frozen contract")


def _scalars(value: object) -> dict:
    if not isinstance(value, dict) or not value or len(value) > 64:
        raise _blocked()
    for key, item in value.items():
        if not isinstance(key, str) or _BODY_KEY.fullmatch(key) is None:
            raise _blocked()
        if item is None or type(item) in (bool, int):
            if type(item) is int and not -(10**30) < item < 10**30:
                raise _blocked()
        elif not isinstance(item, str) or len(item) > 2048 or any(ord(char) < 32 for char in item):
            raise _blocked()
    return value.copy()


def validate_action_profile(value: object) -> dict:
    try:
        if (not isinstance(value, dict) or set(value) != {"profile", "target", "allowed_addresses", "max_operations", "actions"}
                or value["profile"] != PROFILE):
            raise _blocked()
        target = value["target"]
        parsed = urlsplit(target)
        if (parsed.scheme != "https" or parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment or parsed.port is None
                or canonical_target(parsed.hostname, parsed.port) != target):
            raise _blocked()
        addresses = value["allowed_addresses"]
        if (not isinstance(addresses, list) or not 1 <= len(addresses) <= 8
                or len(set(addresses)) != len(addresses)):
            raise _blocked()
        for address in addresses:
            public_address(address)
        try:
            literal = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            literal = None
        if literal is not None and addresses != [str(literal)]:
            raise _blocked()
        actions, limit = value["actions"], value["max_operations"]
        if (not isinstance(actions, list) or not 1 <= len(actions) <= 32
                or type(limit) is not int or not len(actions) <= limit <= 32):
            raise _blocked()
        result = {"profile": PROFILE, "target": target, "allowed_addresses": list(addresses),
                  "max_operations": limit, "actions": []}
        seen = set()
        for action in actions:
            if not isinstance(action, dict) or set(action) != _ACTION:
                raise _blocked()
            key, method = action["action_key"], action["method"]
            if not isinstance(key, str) or _KEY.fullmatch(key) is None or key in seen or method != "POST":
                raise _blocked()
            seen.add(key)
            canonical_path(action["path"])
            parameters, expected = _scalars(action["parameters"]), _scalars(action["expected_body"])
            protocol = action["adapter_protocol"]
            protocol_keys = {"prepare", "prepared", "verify", "verified", "client_ref_field", "unique_ref_field", "secret_field"}
            if (not isinstance(protocol, dict) or set(protocol) != protocol_keys
                    or any(not isinstance(protocol[key], str) or _PROTOCOL.fullmatch(protocol[key]) is None
                           for key in ("prepare", "prepared", "verify", "verified"))
                    or any(not isinstance(protocol[key], str) or _BODY_KEY.fullmatch(protocol[key]) is None
                           for key in ("client_ref_field", "unique_ref_field", "secret_field"))
                    or len({protocol["client_ref_field"], protocol["unique_ref_field"], protocol["secret_field"]}) != 3
                    or {"profile", protocol["client_ref_field"], protocol["unique_ref_field"], protocol["secret_field"]} & set(parameters)):
                raise _blocked()
            identity = action["identity_fields"]
            if (not isinstance(identity, dict) or set(identity) != {"client_ref", "unique_ref", "signature"}
                    or any(not isinstance(v, str) or _BODY_KEY.fullmatch(v) is None for v in identity.values())
                    or len(set(identity.values())) != 3 or set(identity.values()) & set(expected)):
                raise _blocked()
            signature_policy = action["signature_policy"]
            if (signature_policy != {"profile": "RSA_SHA256_SORTED_FIELDS_V1", "excluded_fields": ["class", "sign", "signature"]}
                    or identity["signature"] not in signature_policy["excluded_fields"]):
                raise _blocked()
            credentials = action["credential_version_ids"]
            if (not isinstance(credentials, dict) or set(credentials) != {"api_key", "signing_key", "observer_oauth"}
                    or any(not isinstance(v, str) or str(UUID(v)) != v for v in credentials.values())
                    or len(set(credentials.values())) != len(credentials)):
                raise _blocked()
            commit, adapter_hash = action["framework_commit"], action["adapter_sha256"]
            if (not isinstance(commit, str) or _COMMIT.fullmatch(commit) is None
                    or not isinstance(adapter_hash, str) or _HEX.fullmatch(adapter_hash) is None):
                raise _blocked()
            adapter_path = _path(action["adapter_path"])
            adapter_root = _path(action["adapter_import_root"])
            if not adapter_path.startswith(adapter_root + "/") or not adapter_path.endswith(".py"):
                raise _blocked()
            observer = action["observer"]
            observer_keys = {"adapter_path", "adapter_import_root", "adapter_sha256", "profile", "observed_profile", "oauth_path",
                             "client_order_path_prefix", "order_detail_path_prefix", "order_detail_path_suffix", "order_id_path", "expectations",
                             "preflight_profile", "preflight_observed_profile", "address_page_path", "address_page_query", "address_balance_path",
                             "terminal_transaction_type"}
            if (not isinstance(observer, dict) or set(observer) != observer_keys
                    or any(not isinstance(observer[key], str) or _PROTOCOL.fullmatch(observer[key]) is None
                           for key in ("profile", "observed_profile", "preflight_profile", "preflight_observed_profile"))
                    or not isinstance(observer["adapter_sha256"], str) or _HEX.fullmatch(observer["adapter_sha256"]) is None):
                raise _blocked()
            observer_path = _path(observer["adapter_path"])
            observer_root = _path(observer["adapter_import_root"])
            if not observer_path.startswith(observer_root + "/") or not observer_path.endswith(".py"):
                raise _blocked()
            for path_key in ("oauth_path", "client_order_path_prefix", "order_detail_path_prefix", "order_detail_path_suffix",
                             "address_page_path", "address_balance_path"):
                canonical_path(observer[path_key])
            if (not observer["client_order_path_prefix"].endswith("/")
                    or not observer["order_detail_path_prefix"].endswith("/")
                    or not observer["order_detail_path_suffix"].startswith("/")):
                raise _blocked()
            order_id_path = observer["order_id_path"]
            if (not isinstance(order_id_path, list) or not 1 <= len(order_id_path) <= 4
                    or any(not isinstance(key, str) or _BODY_KEY.fullmatch(key) is None for key in order_id_path)):
                raise _blocked()
            expectations = _scalars(observer["expectations"])
            address_page_query = _scalars(observer["address_page_query"])
            if (not isinstance(observer["terminal_transaction_type"], str)
                    or re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,63}", observer["terminal_transaction_type"]) is None):
                raise _blocked()
            if "client_order_id" in expectations:
                raise _blocked()
            result["actions"].append({**action, "parameters": parameters, "expected_body": expected,
                "identity_fields": identity.copy(), "credential_version_ids": credentials.copy(),
                "adapter_path": adapter_path, "adapter_import_root": adapter_root, "adapter_protocol": protocol.copy(),
                "signature_policy": {"profile": signature_policy["profile"], "excluded_fields": list(signature_policy["excluded_fields"])},
                "observer": {**observer, "expectations": expectations, "address_page_query": address_page_query,
                             "order_id_path": list(order_id_path)}})
        return result
    except (TypeError, ValueError, AttributeError, KeyError):
        raise _blocked() from None
