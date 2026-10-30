"""Check a project's exact signed request against its frozen action.

This function never signs, sends, stores a body, or decides business outcome.
The caller must separately verify the signature and the original send receipt.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re

from .action_profile import validate_action_profile
from .errors import CloudBlocked

_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_MAX_BODY = 131072


def _blocked():
    return CloudBlocked("CONTROLLED_ACTION_BODY_INVALID", "Prepared action does not match its frozen request")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _invalid(_value):
    raise ValueError


def validate_prepared_body(profile, *, action_key, client_ref, unique_ref, body):
    profile = validate_action_profile(profile)
    if (not isinstance(action_key, str) or not isinstance(client_ref, str) or not isinstance(unique_ref, str)
            or _REFERENCE.fullmatch(client_ref) is None or _REFERENCE.fullmatch(unique_ref) is None
            or not isinstance(body, bytes) or not 0 < len(body) <= _MAX_BODY):
        raise _blocked()
    matches = [action for action in profile["actions"] if action["action_key"] == action_key]
    if len(matches) != 1:
        raise _blocked()
    action = matches[0]
    try:
        document = json.loads(body, object_pairs_hook=_unique, parse_float=_invalid, parse_constant=_invalid)
        fields, expected = action["identity_fields"], action["expected_body"]
        expected_keys = set(expected) | set(fields.values())
        if (not isinstance(document, dict) or set(document) != expected_keys
                or document[fields["client_ref"]] != client_ref or document[fields["unique_ref"]] != unique_ref):
            raise ValueError
        for key, value in expected.items():
            # Python treats True == 1; the exact JSON type is part of the contract.
            if type(document[key]) is not type(value) or document[key] != value:
                raise ValueError
        signature = document[fields["signature"]]
        if not isinstance(signature, str) or not 1 <= len(signature) <= 2048:
            raise ValueError
        raw_signature = base64.b64decode(signature, validate=True)
        if not 64 <= len(raw_signature) <= 1024:
            raise ValueError
    except (ValueError, TypeError, UnicodeDecodeError, KeyError, RecursionError):
        raise _blocked() from None
    return {"body_sha256": hashlib.sha256(body).hexdigest(), "byte_count": len(body)}
