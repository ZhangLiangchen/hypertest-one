"""Authenticated observations use only frozen target and original identity."""
from __future__ import annotations

import json
import ssl
from copy import deepcopy

import httpx
import pytest
from test_cloud_action_profile import profile

from hypertest.cloud.action_observer import ActionObserver
from hypertest.cloud.errors import CloudBlocked


def _policy():
    value = profile()
    value["actions"][0]["expected_body"].update(chainName="TRON_TEST", fromAddress="synthetic-address")
    item = value["actions"][0]["observer"]
    item.update(preflight_profile="preflight/v1", preflight_observed_profile="preflight-observation/v1",
                address_page_path="/addresses/page", address_page_query={"walletId": "42", "chain": "TRON_TEST",
                    "address": "synthetic-address", "pageNumber": 1, "pageSize": 10},
                address_balance_path="/addresses/balance/TRON_TEST/synthetic-address", terminal_transaction_type="Uniswap")
    item["expectations"] = {"wallet_id": "42", "chain": "TRON_TEST", "from_coin_code": "TRON_TESTUSDT",
        "to_coin_code": "TRON_TESTTRX", "amount_atomic": "2000000", "from_address": "synthetic-address"}
    return value


class Authority:
    def __init__(self):
        self.checks, self.deny = [], False

    async def admit_preflight(self, *, action_key):
        self.checks.append(("preflight", action_key))
        if self.deny:
            raise CloudBlocked("REVOKED", "revoked")

    async def admit_observation(self, *, identity_id):
        self.checks.append(("observation", identity_id))
        if self.deny:
            raise CloudBlocked("REVOKED", "revoked")

    async def materialize_preflight_credential(self, *, action_key):
        assert action_key == "swap-2"
        return self.credential()

    async def materialize_credential(self, *, identity_id, role):
        assert identity_id == "identity-original" and role == "observer_oauth"
        return self.credential()

    @staticmethod
    def credential():
        return json.dumps({"username": "SYNTHETIC-USER", "password": "SYNTHETIC-PASSWORD",
            "client_id": "SYNTHETIC-CLIENT", "client_secret": "SYNTHETIC-SECRET", "grant_type": "password"}).encode()

    async def get_by_key(self, key):
        return {"identity_id": "identity-original", "operation_key": key, "action_key": "swap-2",
                "client_ref": "original-client", "state": "SENT"}


class Signer:
    async def observe(self, action, client_ref, first, second):
        assert action["action_key"] == "swap-2" and client_ref == "original-client"
        assert first["data"]["id"] == second["data"]["id"] == "42"
        return {"profile": "observation/v1", "client_order_id": client_ref, "order_id": "42",
                "business_status": "Completed", "business_terminal": True,
                "details": [{"detail_id": "5", "transaction_type": "Uniswap", "status": "Success",
                    "tx_hash": "ab" * 32, "block_number": "20", "confirmations": 2, "required_confirmations": 1}],
                "chain_receipt": "UNOBSERVED", "actual_trx_received": "UNOBSERVED"}

    async def preflight(self, action, first, second):
        assert action["action_key"] == "swap-2" and first["data"] and second["data"]
        return {"profile": "preflight-observation/v1", "allowed": True, "available_atomic": "2000001",
                "address_membership": "OBSERVED", "aggregate_dex_withdraw_role": "OBSERVED",
                "coin_specific_role": "UNOBSERVED", "address_active": "UNOBSERVED", "lock_state": "UNOBSERVED",
                "concurrent_changes": "POSSIBLE"}


class JsonStream(httpx.AsyncByteStream):
    def __init__(self, value):
        self.value = json.dumps(value).encode()

    async def __aiter__(self):
        yield self.value


def _response(value):
    return httpx.Response(200, stream=JsonStream(value))


def _handler(request):
    if request.url.path == "/oauth/token":
        assert request.method == "POST" and request.headers.get("authorization") is None
        return _response({"code": 200, "data": {"access_token": "SYNTHETIC-BEARER"}})
    assert request.method == "GET" and request.headers["authorization"] == "Bearer SYNTHETIC-BEARER"
    order = {"id": "42", "clientOrderId": "original-client", "status": "Completed", "walletId": 42,
             "fromChain": "TRON_TEST", "toChain": "TRON_TEST", "fromCoinCode": "TRON_TESTUSDT",
             "toCoinCode": "TRON_TESTTRX", "amount": 2000000, "fromAddress": "synthetic-address",
             "transactionType": "Uniswap"}
    if request.url.path == "/orders/client/original-client":
        return _response({"code": 200, "data": order})
    if request.url.path == "/orders/42/with-details":
        return _response({"code": 200, "data": {**order, "private": "SYNTHETIC-RAW", "details": [{"id": "5", "orderId": "42",
                "transactionType": "Uniswap", "status": "Success", "txHash": "ab" * 32, "blockNumber": "20",
                "confirmations": 2, "requiredConfirmations": 1, "signedTransaction": "SYNTHETIC-SIGNED"}]}})
    if request.url.path == "/addresses/page":
        return _response({"code": 200, "data": {"records": [{"walletId": 42, "chain": "TRON_TEST",
            "address": "synthetic-address", "allOutRuleTypes": ["DEXWithdraw"]}]}})
    if request.url.path == "/addresses/balance/TRON_TEST/synthetic-address":
        return _response({"code": 200, "data": [{"chain": "TRON_TEST", "address": "synthetic-address",
            "code": "TRON_TESTUSDT", "available": 2000001}]})
    raise AssertionError("unexpected unapproved URL")


async def _resolve(_host, _port):
    return ["8.8.8.8"]


@pytest.mark.asyncio
async def test_original_order_reads_are_fixed_pinned_and_token_stays_private():
    policy, authority, signer = _policy(), Authority(), Signer()
    observer = ActionObserver(profile=policy, resolver=_resolve, transport=httpx.MockTransport(_handler))
    async def validate_output(_value):
        return None
    result = await observer.observe(action=policy["actions"][0], authority=authority, signer=signer,
        identity_id="identity-original", operation_key="original-key", validate_output=validate_output)
    assert result["projection"]["business_terminal"] is True
    assert result["projection"]["chain_receipt"] == "UNOBSERVED"
    assert len(result["order_response_sha256"]) == len(result["details_response_sha256"]) == 64
    assert "SYNTHETIC" not in json.dumps(result)
    assert len(authority.checks) == 4


@pytest.mark.asyncio
async def test_preflight_uses_only_frozen_paths_and_authority_rechecks():
    policy, authority, signer = _policy(), Authority(), Signer()
    observer = ActionObserver(profile=policy, resolver=_resolve, transport=httpx.MockTransport(_handler))
    assert await observer.preflight(action=policy["actions"][0], authority=authority, signer=signer) is True
    assert len(authority.checks) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("size,accepted", [(5731, True), (8192, True), (8193, False)])
async def test_oauth_accepts_bounded_long_bearer_and_rejects_oversize(size, accepted):
    policy, authority = _policy(), Authority()
    def handler(request):
        assert request.url.path == "/oauth/token"
        return _response({"code": 200, "data": {"access_token": "x" * size}})
    observer = ActionObserver(profile=policy, resolver=_resolve, transport=httpx.MockTransport(handler))
    if accepted:
        assert len(await observer._token(policy["actions"][0], authority, None)) == size
    else:
        with pytest.raises(CloudBlocked):
            await observer._token(policy["actions"][0], authority, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage,code", [
    ("credential", "CONTROLLED_ACTION_PREFLIGHT_CREDENTIAL_UNAVAILABLE"),
    ("authority", "CONTROLLED_ACTION_PREFLIGHT_AUTHORITY_UNAVAILABLE"),
    ("oauth", "CONTROLLED_ACTION_PREFLIGHT_OAUTH_UNAVAILABLE"),
    ("address", "CONTROLLED_ACTION_PREFLIGHT_ADDRESS_UNAVAILABLE"),
    ("balance", "CONTROLLED_ACTION_PREFLIGHT_BALANCE_UNAVAILABLE"),
    ("adapter", "CONTROLLED_ACTION_PREFLIGHT_ADAPTER_UNAVAILABLE"),
    ("validation", "CONTROLLED_ACTION_PREFLIGHT_VALIDATION_UNAVAILABLE"),
])
async def test_preflight_errors_identify_only_fixed_stage_without_secrets(stage, code):
    policy, authority, signer = _policy(), Authority(), Signer()
    if stage == "credential":
        async def missing(**_kwargs):
            raise RuntimeError("SYNTHETIC-SECRET")
        authority.materialize_preflight_credential = missing
    if stage == "authority":
        authority.deny = True
    if stage == "adapter":
        async def fail(*_args):
            raise RuntimeError("SYNTHETIC-SECRET")
        signer.preflight = fail
    if stage == "validation":
        policy["actions"][0]["expected_body"]["amount"] = "3000000"
    def handler(request):
        paths = {"oauth": "/oauth/token", "address": "/addresses/page",
                 "balance": "/addresses/balance/TRON_TEST/synthetic-address"}
        if request.url.path == paths.get(stage):
            return httpx.Response(403)
        return _handler(request)
    observer = ActionObserver(profile=policy, resolver=_resolve, transport=httpx.MockTransport(handler))
    with pytest.raises(CloudBlocked) as error:
        await observer.preflight(action=policy["actions"][0], authority=authority, signer=signer)
    assert error.value.code == code
    assert "SYNTHETIC" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["wallet", "role", "balance", "coin", "frozen_amount", "untrusted_output"])
async def test_preflight_rejects_forged_adapter_or_unmatched_frozen_conditions(change):
    policy, authority, signer = _policy(), Authority(), Signer()
    if change == "frozen_amount":
        policy["actions"][0]["expected_body"]["amount"] = "3000000"
    if change == "untrusted_output":
        async def forged(_action, _first, _second):
            return {"profile": "preflight-observation/v1", "allowed": True}
        signer.preflight = forged
    def handler(request):
        if request.url.path == "/addresses/page" and change in {"wallet", "role"}:
            return _response({"code": 200, "data": {"records": [{"walletId": 43 if change == "wallet" else 42,
                "chain": "TRON_TEST", "address": "synthetic-address",
                "allOutRuleTypes": ["Withdraw" if change == "role" else "DEXWithdraw"]}]}})
        if request.url.path == "/addresses/balance/TRON_TEST/synthetic-address" and change in {"balance", "coin"}:
            return _response({"code": 200, "data": [{"chain": "TRON_TEST", "address": "synthetic-address",
                "code": "TRON_TESTTRX" if change == "coin" else "TRON_TESTUSDT",
                "available": 1 if change == "balance" else 2000001}]})
        return _handler(request)
    observer = ActionObserver(profile=policy, resolver=_resolve, transport=httpx.MockTransport(handler))
    with pytest.raises(CloudBlocked):
        await observer.preflight(action=policy["actions"][0], authority=authority, signer=signer)


@pytest.mark.asyncio
async def test_substituted_action_or_original_identity_fails_before_network():
    policy, authority, signer = _policy(), Authority(), Signer()
    observer = ActionObserver(profile=policy, resolver=_resolve, transport=httpx.MockTransport(_handler))
    changed = deepcopy(policy["actions"][0])
    changed["observer"]["oauth_path"] = "/other"
    with pytest.raises(CloudBlocked):
        await observer.preflight(action=changed, authority=authority, signer=signer)
    with pytest.raises(CloudBlocked):
        await observer.observe(action=policy["actions"][0], authority=authority, signer=signer,
            identity_id="different", operation_key="original-key", validate_output=lambda _: None)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["tx_hash", "extra"])
async def test_projector_cannot_forge_terminal_details_or_export_extra_fields(change):
    class DishonestSigner(Signer):
        async def observe(self, action, client_ref, first, second):
            output = await super().observe(action, client_ref, first, second)
            if change == "tx_hash":
                output["details"][0]["tx_hash"] = "cd" * 32
            else:
                output["leaked_raw"] = "SYNTHETIC-SIGNED"
            return output
    policy = _policy()
    observer = ActionObserver(profile=policy, resolver=_resolve, transport=httpx.MockTransport(_handler))
    with pytest.raises(CloudBlocked):
        await observer.observe(action=policy["actions"][0], authority=Authority(), signer=DishonestSigner(),
            identity_id="identity-original", operation_key="original-key", validate_output=lambda _: None)


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("walletId", 43), ("fromChain", "TRON"),
    ("toCoinCode", "other"), ("amount", 1), ("fromAddress", "different"), ("transactionType", "Withdraw")])
async def test_raw_order_must_match_frozen_authorization(field, value):
    async def handler(request):
        if request.url.path == "/orders/client/original-client":
            order = {"id": "42", "clientOrderId": "original-client", "status": "Completed", "walletId": 42,
                "fromChain": "TRON_TEST", "toChain": "TRON_TEST", "fromCoinCode": "TRON_TESTUSDT",
                "toCoinCode": "TRON_TESTTRX", "amount": 2000000, "fromAddress": "synthetic-address",
                "transactionType": "Uniswap"}
            order[field] = value
            return _response({"code": 200, "data": order})
        return _handler(request)
    policy = _policy()
    observer = ActionObserver(profile=policy, resolver=_resolve, transport=httpx.MockTransport(handler))
    with pytest.raises(CloudBlocked):
        await observer.observe(action=policy["actions"][0], authority=Authority(), signer=Signer(),
            identity_id="identity-original", operation_key="original-key", validate_output=lambda _: None)


@pytest.mark.asyncio
async def test_dangerous_dynamic_order_id_never_becomes_get_path():
    paths = []
    def handler(request):
        paths.append(request.url.path)
        if request.url.path == "/orders/client/original-client":
            return _response({"code": 200, "data": {"id": "../another", "clientOrderId": "original-client"}})
        return _handler(request)
    policy = _policy()
    observer = ActionObserver(profile=policy, resolver=_resolve, transport=httpx.MockTransport(handler))
    with pytest.raises(CloudBlocked):
        await observer.observe(action=policy["actions"][0], authority=Authority(), signer=Signer(),
            identity_id="identity-original", operation_key="original-key", validate_output=lambda _: None)
    assert paths == ["/oauth/token", "/orders/client/original-client"]


@pytest.mark.asyncio
async def test_redirect_dns_change_and_explicit_tls_downgrade_are_rejected():
    policy = _policy()
    async def bad_dns(_host, _port):
        return ["1.1.1.1"]
    observer = ActionObserver(profile=policy, resolver=bad_dns, transport=httpx.MockTransport(_handler))
    with pytest.raises(CloudBlocked):
        await observer.preflight(action=policy["actions"][0], authority=Authority(), signer=Signer())
    observer = ActionObserver(profile=policy, resolver=_resolve,
                              transport=httpx.MockTransport(lambda _: httpx.Response(302, headers={"location": "https://other.invalid"})))
    with pytest.raises(CloudBlocked):
        await observer.preflight(action=policy["actions"][0], authority=Authority(), signer=Signer())
    tls = ssl.create_default_context()
    tls.check_hostname = False
    tls.verify_mode = ssl.CERT_NONE
    with pytest.raises(CloudBlocked):
        ActionObserver(profile=policy, tls_context=tls)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage,expected", [
    ("original", "ORIGINAL"), ("oauth", "OAUTH"), ("order", "ORDER_GET"),
    ("detail", "DETAIL_GET"), ("adapter", "ADAPTER"), ("validation", "VALIDATION"),
    ("authority", "AUTHORITY"),
])
async def test_observe_errors_only_disclose_fixed_stage(stage, expected):
    policy, authority, signer = _policy(), Authority(), Signer()
    if stage == "original":
        async def missing(_key):
            raise RuntimeError("SYNTHETIC-SECRET")
        authority.get_by_key = missing
    if stage == "adapter":
        async def bad_adapter(*_args):
            raise RuntimeError("SYNTHETIC-SECRET")
        signer.observe = bad_adapter
    if stage == "authority":
        original = authority.admit_observation
        async def after_reads(**kwargs):
            if len(authority.checks) == 3:
                raise RuntimeError("SYNTHETIC-SECRET")
            await original(**kwargs)
        authority.admit_observation = after_reads
    def handler(request):
        paths = {"oauth": "/oauth/token", "order": "/orders/client/original-client", "detail": "/orders/42/with-details"}
        if request.url.path == paths.get(stage):
            return httpx.Response(403)
        if stage == "validation" and request.url.path == "/orders/client/original-client":
            return _response({"code": 200, "data": {"id": "42"}})
        return _handler(request)
    observer = ActionObserver(profile=policy, resolver=_resolve, transport=httpx.MockTransport(handler))
    async def validate_output(_value):
        pass
    with pytest.raises(CloudBlocked) as error:
        await observer.observe(action=policy["actions"][0], authority=authority, signer=signer,
            identity_id="identity-original", operation_key="original-key", validate_output=validate_output)
    assert error.value.code == "CONTROLLED_ACTION_OBSERVE_" + expected + "_UNAVAILABLE"
    assert "SYNTHETIC-SECRET" not in str(error.value)
