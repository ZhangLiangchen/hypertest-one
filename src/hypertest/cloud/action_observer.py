"""Trusted, bounded OAuth reads for an existing controlled action.

The Agent cannot choose a URL, bearer token, original reference or response.
Network replies are passed only to the frozen, confined project adapter; raw
headers, bodies, OAuth tokens and authentication failures never enter output.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import ssl
import time
from urllib.parse import urlencode, urlsplit

import httpx

from .action_profile import validate_action_profile
from .action_resolver import resolve_action_public
from .errors import CloudBlocked
from .http_profile import canonical_path, public_address

_REFERENCE = re.compile(r"[A-Za-z0-9_.~-]{1,128}\Z")
_ORDER_ID = re.compile(r"[1-9][0-9]{0,39}\Z")
_INTEGER = re.compile(r"(?:0|[1-9][0-9]{0,39})\Z")
_TX_HASH = re.compile(r"(?:0x)?[A-Fa-f0-9]{64}\Z")
_MAX_RESPONSE = 100_000
_MAX_BEARER_TOKEN = 8192


def _blocked(code="CONTROLLED_ACTION_OBSERVATION_UNAVAILABLE"):
    return CloudBlocked(code, "Original action observation is unavailable or unconfirmed")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _json(raw):
    value = json.loads(raw, object_pairs_hook=_pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    if not isinstance(value, dict):
        raise ValueError
    return value


def _oauth_document(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 32768:
        raise _blocked()
    try:
        value = _json(raw)
        keys = {"username", "password", "client_id", "client_secret", "grant_type"}
        if (set(value) != keys or value["grant_type"] != "password"
                or any(not isinstance(item, str) or not item or len(item) > 8192
                       or any(ord(c) < 32 for c in item) for item in value.values())):
            raise ValueError
        return value
    except (ValueError, TypeError, UnicodeError):
        raise _blocked() from None


def _lookup(value, path):
    for key in path:
        if not isinstance(value, dict) or key not in value:
            raise ValueError
        value = value[key]
    return value


def _projection(value, *, profile, client_ref, order_id, terminal_transaction_type):
    """Bound the pinned adapter's output independently of provider raw data."""
    keys = {"profile", "client_order_id", "order_id", "business_status", "business_terminal", "details",
            "chain_receipt", "actual_trx_received"}
    statuses = {"Pending", "Processing", "Completed", "Failed", "Cancelled", "Timeout"}
    detail_statuses = {"Pending", "Broadcast", "Confirming", "Success", "Fail", "Timeout"}
    if (not isinstance(value, dict) or set(value) != keys or value["profile"] != profile
            or value["client_order_id"] != client_ref or value["order_id"] != order_id
            or value["business_status"] not in statuses or type(value["business_terminal"]) is not bool
            or value["chain_receipt"] != "UNOBSERVED" or value["actual_trx_received"] != "UNOBSERVED"
            or not isinstance(value["details"], list) or len(value["details"]) > 128):
        raise ValueError
    seen = set()
    for detail in value["details"]:
        fields = {"detail_id", "transaction_type", "status", "tx_hash", "block_number", "confirmations", "required_confirmations"}
        if not isinstance(detail, dict) or set(detail) != fields:
            raise ValueError
        detail_id, kind, status = detail["detail_id"], detail["transaction_type"], detail["status"]
        if (not isinstance(detail_id, str) or _INTEGER.fullmatch(detail_id) is None or detail_id in seen
                or not isinstance(kind, str) or re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,63}", kind) is None
                or status not in detail_statuses):
            raise ValueError
        seen.add(detail_id)
        tx_hash, block = detail["tx_hash"], detail["block_number"]
        if ((tx_hash is not None and (not isinstance(tx_hash, str) or _TX_HASH.fullmatch(tx_hash) is None))
                or (block is not None and (not isinstance(block, str) or _INTEGER.fullmatch(block) is None))):
            raise ValueError
        for field in ("confirmations", "required_confirmations"):
            number = detail[field]
            if number is not None and (type(number) is not int or not 0 <= number <= 10**9):
                raise ValueError
    if value["business_terminal"]:
        details = value["details"]
        if (not details or any(item["status"] not in {"Success", "Fail"} for item in details)
                or value["business_status"] not in {"Completed", "Failed", "Cancelled"}
                or value["business_status"] == "Completed" and (any(item["status"] != "Success" for item in details)
                    or not any(item["transaction_type"] == terminal_transaction_type and item["tx_hash"] is not None
                               and item["block_number"] is not None for item in details))
                or value["business_status"] in {"Failed", "Cancelled"} and not any(item["status"] == "Fail" for item in details)):
            raise ValueError
    return value


def _number(value):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or _INTEGER.fullmatch(value) is None:
        raise ValueError
    return int(value)


def _preflight_projection(action, address, balance, result):
    """Recheck the authorised source and atomic amount independently of the project adapter."""
    config = action["observer"]
    expected, query, body = config["expectations"], config["address_page_query"], action["expected_body"]
    wallet, chain, source = expected["wallet_id"], expected["chain"], expected["from_address"]
    amount, coin = _number(expected["amount_atomic"]), expected["from_coin_code"]
    if (amount <= 0 or _number(query["walletId"]) != _number(wallet)
            or query["chain"] != chain or query["address"] != source
            or body.get("chainName") != chain or body.get("fromAddress") != source
            or _number(body.get("amount")) != amount
            or not config["address_balance_path"].endswith("/" + chain + "/" + source)):
        raise ValueError
    if any(not isinstance(item, dict) or type(item.get("code")) is not int
           or item["code"] not in (0, 200) for item in (address, balance)):
        raise ValueError
    rows = address.get("data")
    if isinstance(rows, dict):
        rows = rows.get("records")
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError
    matches = [row for row in rows if isinstance(row, dict) and row.get("address") == source
               and row.get("chain") == chain and _number(row.get("walletId")) == _number(wallet)]
    if len(matches) != 1 or not isinstance(matches[0].get("allOutRuleTypes"), list):
        raise ValueError
    roles = matches[0]["allOutRuleTypes"]
    if any(not isinstance(item, str) for item in roles) or "DEXWithdraw" not in roles:
        raise ValueError
    rows = balance.get("data")
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError
    selected = [row for row in rows if isinstance(row, dict) and row.get("address") == source
                and row.get("chain") == chain and (row.get("code") or row.get("coinCode")) == coin]
    if len(selected) != 1:
        raise ValueError
    available = _number(selected[0].get("available"))
    if available < amount:
        raise _blocked("CONTROLLED_ACTION_PREFLIGHT_INSUFFICIENT_BALANCE")
    required = {"profile", "allowed", "available_atomic", "address_membership", "aggregate_dex_withdraw_role",
                "coin_specific_role", "address_active", "lock_state", "concurrent_changes"}
    if (not isinstance(result, dict) or set(result) != required
            or result["profile"] != config["preflight_observed_profile"] or result["allowed"] is not True
            or result["available_atomic"] != str(available) or result["address_membership"] != "OBSERVED"
            or result["aggregate_dex_withdraw_role"] != "OBSERVED"
            or any(result[key] != "UNOBSERVED" for key in ("coin_specific_role", "address_active", "lock_state"))
            or result["concurrent_changes"] != "POSSIBLE"):
        raise ValueError
    return True


def _bound_order(action, order, client_ref):
    expected, body = action["observer"]["expectations"], action["expected_body"]
    amount = _number(expected["amount_atomic"])
    if (not isinstance(order, dict) or order.get(action["identity_fields"]["client_ref"]) != client_ref
            or _number(order.get("walletId")) != _number(expected["wallet_id"])
            or order.get("fromChain") != expected["chain"] or order.get("toChain") != expected["chain"]
            or order.get("fromCoinCode") != expected["from_coin_code"]
            or order.get("toCoinCode") != expected["to_coin_code"]
            or _number(order.get("amount")) != amount or _number(body.get("amount")) != amount
            or order.get("fromAddress") != expected["from_address"]
            or order.get("transactionType") != action["observer"]["terminal_transaction_type"]
            or body.get("fromAddress") != expected["from_address"] or body.get("chainName") != expected["chain"]):
        raise ValueError


class ActionObserver:
    """Observe one already SENT original, with current authority on every read."""

    def __init__(self, *, profile, resolver=None, transport=None, tls_context=None):
        self.profile = validate_action_profile(profile)
        self.resolver = resolver or resolve_action_public
        self.transport = transport
        self.tls = tls_context or ssl.create_default_context()
        if self.tls.verify_mode != ssl.CERT_REQUIRED or not self.tls.check_hostname:
            raise _blocked("CONTROLLED_ACTION_OBSERVER_TLS_REQUIRED")

    def _action(self, action_key):
        matches = [item for item in self.profile["actions"] if item["action_key"] == action_key]
        if len(matches) != 1:
            raise _blocked()
        return matches[0]

    async def _request(self, *, authority, action, identity_id, method, path, token=None, body=None, query=None, limit=_MAX_RESPONSE):
        canonical_path(path)
        if method not in {"GET", "POST"} or type(limit) is not int or not 1 <= limit <= _MAX_RESPONSE:
            raise _blocked()
        target = urlsplit(self.profile["target"])
        try:
            addresses = await self.resolver(target.hostname, target.port)
            if (not isinstance(addresses, (tuple, list)) or not 1 <= len(addresses) <= 8
                    or any(public_address(a) not in self.profile["allowed_addresses"] for a in addresses)):
                raise _blocked("CONTROLLED_ACTION_OBSERVER_DNS_REFUSED")
            try:
                if identity_id is None:
                    await authority.admit_preflight(action_key=action["action_key"])
                else:
                    await authority.admit_observation(identity_id=identity_id)
            except Exception:
                if identity_id is None:
                    raise _blocked("CONTROLLED_ACTION_PREFLIGHT_AUTHORITY_UNAVAILABLE") from None
                raise _blocked() from None
            address = sorted(set(addresses))[0]
            host = f"[{address}]" if ":" in address else address
            authority = f"[{target.hostname}]" if ":" in target.hostname else target.hostname
            headers = {"Host": f"{authority}:{target.port}", "Accept": "application/json", "Accept-Encoding": "identity"}
            if token is not None:
                headers["Authorization"] = "Bearer " + token
            if body is not None:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            request = httpx.Request(method, f"https://{host}:{target.port}{path}", headers=headers,
                params=query, content=body, extensions={"sni_hostname": target.hostname,
                    "timeout": {key: 10 for key in ("connect", "read", "write", "pool")}})
            transport = self.transport or httpx.AsyncHTTPTransport(verify=self.tls, retries=0, trust_env=False,
                http1=True, http2=False, limits=httpx.Limits(max_connections=1, max_keepalive_connections=0))
            async with httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False,
                                         timeout=10) as client:
                response = await client.send(request, stream=True, follow_redirects=False)
                try:
                    if (response.status_code != 200 or sum(len(k) + len(v) for k, v in response.headers.raw) > 16384
                            or response.headers.get("content-encoding", "identity").lower() != "identity"):
                        raise _blocked()
                    length = response.headers.get("content-length")
                    if length is not None and (not length.isdecimal() or int(length) > limit):
                        raise _blocked()
                    chunks, total = [], 0
                    async for chunk in response.aiter_raw():
                        total += len(chunk)
                        if total > limit:
                            raise _blocked()
                        chunks.append(chunk)
                    return b"".join(chunks)
                finally:
                    await response.aclose()
        except (OSError, ValueError, httpx.HTTPError):
            raise _blocked() from None

    async def _token(self, action, authority, identity_id):
        try:
            raw = (await authority.materialize_preflight_credential(action_key=action["action_key"]) if identity_id is None
                   else await authority.materialize_credential(identity_id=identity_id, role="observer_oauth"))
            credential = _oauth_document(raw)
        except Exception:
            if identity_id is None:
                raise _blocked("CONTROLLED_ACTION_PREFLIGHT_CREDENTIAL_UNAVAILABLE") from None
            raise _blocked() from None
        try:
            encoded = urlencode(credential).encode("ascii")
            response = _json(await self._request(authority=authority, action=action, identity_id=identity_id, method="POST",
                path=action["observer"]["oauth_path"], body=encoded, limit=32768))
            if "code" in response and (type(response["code"]) is not int or response["code"] not in (0, 200)):
                raise ValueError
            token_data = response.get("data", response)
            if not isinstance(token_data, dict):
                raise ValueError
            token = token_data.get("access_token")
            if (not isinstance(token, str) or not 1 <= len(token) <= _MAX_BEARER_TOKEN
                    or any(ord(c) < 33 or ord(c) > 126 for c in token)):
                raise ValueError
            return token
        except (ValueError, TypeError, UnicodeError):
            raise _blocked() from None
        finally:
            del raw, credential

    async def preflight(self, *, action, authority, signer, timeout=25):
        if action not in self.profile["actions"] or type(timeout) not in (int, float) or not 0 < timeout <= 25:
            raise _blocked()
        stage = "OAUTH"
        try:
            async with asyncio.timeout(timeout):
                token = await self._token(action, authority, None)
                try:
                    config = action["observer"]
                    stage = "ADDRESS"
                    address = await self._request(authority=authority, action=action, identity_id=None, method="GET",
                        path=config["address_page_path"], query=config["address_page_query"], token=token)
                    stage = "BALANCE"
                    balance = await self._request(authority=authority, action=action, identity_id=None, method="GET",
                        path=config["address_balance_path"], token=token)
                    stage = "ADAPTER"
                    address_json, balance_json = _json(address), _json(balance)
                    result = await signer.preflight(action, address_json, balance_json)
                    stage = "VALIDATION"
                    _preflight_projection(action, address_json, balance_json, result)
                    stage = "AUTHORITY"
                    await authority.admit_preflight(action_key=action["action_key"])
                    return True
                finally:
                    del token
        except Exception as error:
            safe_codes = {"CONTROLLED_ACTION_PREFLIGHT_CREDENTIAL_UNAVAILABLE", "CONTROLLED_ACTION_OBSERVER_DNS_REFUSED",
                          "CONTROLLED_ACTION_PREFLIGHT_INSUFFICIENT_BALANCE", "CONTROLLED_ACTION_PREFLIGHT_AUTHORITY_UNAVAILABLE"}
            if isinstance(error, CloudBlocked) and error.code in safe_codes:
                raise _blocked(error.code) from None
            raise _blocked("CONTROLLED_ACTION_PREFLIGHT_" + stage + "_UNAVAILABLE") from None

    async def observe(self, *, action, authority, signer, identity_id, operation_key, validate_output, timeout=25):
        if action not in self.profile["actions"]:
            raise _blocked()
        action_key = action["action_key"]
        if type(timeout) not in (int, float) or not 0 < timeout <= 25:
            raise _blocked()
        try:
            async with asyncio.timeout(timeout):
                record = await authority.get_by_key(operation_key)
                client_ref = record.get("client_ref")
                if (record.get("identity_id") != identity_id or record.get("operation_key") != operation_key
                        or record.get("action_key") != action_key or record.get("state") != "SENT"
                        or not isinstance(client_ref, str) or _REFERENCE.fullmatch(client_ref) is None):
                    raise ValueError
                token = await self._token(action, authority, identity_id)
                try:
                    config = action["observer"]
                    first = await self._request(authority=authority, action=action, identity_id=identity_id, method="GET",
                        path=config["client_order_path_prefix"] + client_ref, token=token)
                    first_json = _json(first)
                    order_id = _lookup(first_json, config["order_id_path"])
                    if type(order_id) is int:
                        order_id = str(order_id)
                    if not isinstance(order_id, str) or _ORDER_ID.fullmatch(order_id) is None:
                        raise ValueError
                    first_order = _lookup(first_json, config["order_id_path"][:-1])
                    _bound_order(action, first_order, client_ref)
                    second = await self._request(authority=authority, action=action, identity_id=identity_id, method="GET",
                        path=config["order_detail_path_prefix"] + order_id + config["order_detail_path_suffix"], token=token)
                    second_json = _json(second)
                    second_id = _lookup(second_json, config["order_id_path"])
                    second_order = _lookup(second_json, config["order_id_path"][:-1])
                    if str(second_id) != order_id:
                        raise ValueError
                    _bound_order(action, second_order, client_ref)
                    projection = _projection(await signer.observe(action, client_ref, first_json, second_json),
                        profile=config["observed_profile"], client_ref=client_ref, order_id=order_id,
                        terminal_transaction_type=config["terminal_transaction_type"])
                    if first_order.get("status") != projection["business_status"] or second_order.get("status") != projection["business_status"]:
                        raise ValueError
                    raw_details = second_order.get("details")
                    if not isinstance(raw_details, list) or len(raw_details) != len(projection["details"]):
                        raise ValueError
                    projected = {item["detail_id"]: item for item in projection["details"]}
                    if len(projected) != len(raw_details):
                        raise ValueError
                    for raw_detail in raw_details:
                        if not isinstance(raw_detail, dict):
                            raise ValueError
                        item = projected.get(str(raw_detail.get("id")))
                        raw_block = raw_detail.get("blockNumber")
                        if (item is None or str(raw_detail.get("orderId")) != order_id
                                or item["status"] != raw_detail.get("status")
                                or item["transaction_type"] != raw_detail.get("transactionType")
                                or item["tx_hash"] != raw_detail.get("txHash")
                                or item["block_number"] != (str(raw_block) if raw_block is not None else None)
                                or item["confirmations"] != raw_detail.get("confirmations")
                                or item["required_confirmations"] != raw_detail.get("requiredConfirmations")):
                            raise ValueError
                    await validate_output({"controlled_action_observation": projection})
                    await authority.admit_observation(identity_id=identity_id)
                    return {"projection": projection, "order_response_sha256": hashlib.sha256(first).hexdigest(),
                            "details_response_sha256": hashlib.sha256(second).hexdigest(), "observed_at": int(time.time())}
                finally:
                    del token
        except (OSError, ValueError, TypeError, KeyError, UnicodeError, TimeoutError):
            raise _blocked() from None
