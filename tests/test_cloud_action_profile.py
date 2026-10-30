"""Controlled writes accept only the frozen exact body and original identities."""
import base64
import hashlib
import json
from copy import deepcopy
from uuid import uuid4

import pytest

from hypertest.cloud.action_body import validate_prepared_body
from hypertest.cloud.action_profile import PROFILE, validate_action_profile
from hypertest.cloud.errors import CloudBlocked


def profile():
    return {"profile": PROFILE, "target": "https://api.example.invalid:443", "allowed_addresses": ["8.8.8.8"],
        "max_operations": 1, "actions": [{"action_key": "swap-2", "method": "POST", "path": "/fixed/action",
        "parameters": {"amount": "2", "object_id": "synthetic"},
        "expected_body": {"amount": "2000000", "slippagePercent": 0, "flag": True},
        "identity_fields": {"client_ref": "clientOrderId", "unique_ref": "uniqueUserKey", "signature": "sign"},
        "credential_version_ids": {key: str(uuid4()) for key in ("api_key", "signing_key", "observer_oauth")},
        "framework_commit": "a" * 40, "adapter_path": "python/adapter.py", "adapter_import_root": "python",
        "adapter_protocol": {"prepare": "adapter-prepare/v1", "prepared": "adapter-prepared/v1",
            "verify": "adapter-verify/v1", "verified": "adapter-verified/v1", "client_ref_field": "client_order_id",
            "unique_ref_field": "unique_user_key", "secret_field": "signing_key"},
        "signature_policy": {"profile": "RSA_SHA256_SORTED_FIELDS_V1", "excluded_fields": ["class", "sign", "signature"]},
        "observer": {"adapter_path": "python/observer.py", "adapter_import_root": "python", "adapter_sha256": "c" * 64,
            "profile": "observer/v1", "observed_profile": "observation/v1", "oauth_path": "/oauth/token",
            "client_order_path_prefix": "/orders/client/", "order_detail_path_prefix": "/orders/",
            "order_detail_path_suffix": "/with-details", "order_id_path": ["data", "id"], "expectations": {"wallet_id": "fixture"},
            "preflight_profile": "preflight/v1", "preflight_observed_profile": "preflight-observed/v1",
            "address_page_path": "/addresses", "address_page_query": {"walletId": "fixture"},
            "address_balance_path": "/addresses/balance/fixture", "terminal_transaction_type": "Uniswap"},
        "adapter_sha256": "b" * 64}]}


def prepared():
    return {"amount": "2000000", "slippagePercent": 0, "flag": True, "clientOrderId": "order-original",
            "uniqueUserKey": "unique-original", "sign": base64.b64encode(b"S" * 256).decode()}


def test_exact_raw_bytes_are_hashed_and_frozen_values_cannot_change():
    raw = json.dumps(prepared(), indent=2).encode()
    result = validate_prepared_body(profile(), action_key="swap-2", client_ref="order-original",
                                    unique_ref="unique-original", body=raw)
    assert result == {"body_sha256": hashlib.sha256(raw).hexdigest(), "byte_count": len(raw)}


@pytest.mark.parametrize("change", ["amount", "boolean_integer", "extra", "client", "unique", "signature", "duplicate"])
def test_rejects_changed_business_values_original_ids_and_malformed_json(change):
    item = prepared()
    if change == "amount":
        item["amount"] = "7000000"
    elif change == "boolean_integer":
        item["flag"] = 1
    elif change == "extra":
        item["newField"] = "unapproved"
    elif change == "client":
        item["clientOrderId"] = "replacement"
    elif change == "unique":
        item["uniqueUserKey"] = "replacement"
    elif change == "signature":
        item["sign"] = "not-base64"
    raw = json.dumps(item).encode()
    if change == "duplicate":
        raw = raw[:-1] + b',"amount":"2000000"}'
    with pytest.raises(CloudBlocked):
        validate_prepared_body(profile(), action_key="swap-2", client_ref="order-original",
                               unique_ref="unique-original", body=raw)


@pytest.mark.parametrize("change", ["private_address", "arbitrary_method", "credential_alias", "body_alias", "adapter_git"])
def test_profile_rejects_unsafe_plan(change):
    policy = deepcopy(profile())
    action = policy["actions"][0]
    if change == "private_address":
        policy["allowed_addresses"] = ["127.0.0.1"]
    elif change == "arbitrary_method":
        action["method"] = "GET"
    elif change == "credential_alias":
        action["credential_version_ids"]["signing_key"] = action["credential_version_ids"]["api_key"]
    elif change == "body_alias":
        action["expected_body"]["sign"] = "attacker"
    else:
        action["adapter_path"] = ".git/config"
    with pytest.raises(CloudBlocked):
        validate_action_profile(policy)
