"""The signed body is independently verified against the frozen action."""
import base64
import json
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from test_cloud_action_profile import prepared, profile

from hypertest.cloud.action_signer import ActionSigner
from hypertest.cloud.source_export import PROFILE


@pytest.mark.asyncio
async def test_independent_rsa_verification_rejects_untrusted_adapter_lies(tmp_path):
    policy = profile()
    signer = ActionSigner(source_root=tmp_path, export_policy={"profile": PROFILE,
        "sut": [{"path": "main.py", "sha256": "a" * 64}],
        "framework": [{"path": "python/adapter.py", "sha256": "b" * 64}]}, action_profile=policy, authority=None)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    identity_id = str(uuid4())
    signer._public_keys[identity_id] = key.public_key().public_bytes(serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")
    item = prepared()
    content = "&".join(f"{name}={str(value).lower() if type(value) is bool else value}"
                       for name, value in sorted(item.items()) if name not in {"class", "sign", "signature"})
    item["sign"] = base64.b64encode(key.sign(content.encode(), padding.PKCS1v15(), hashes.SHA256())).decode()
    calls = []
    async def claimed_verified(_action, _document):
        calls.append(1)
        return {"profile": "adapter-verified/v1", "valid": True}
    signer._run = claimed_verified
    body = json.dumps(item).encode()
    assert await signer.verify(policy["actions"][0], body, identity_id=identity_id) is True
    item["amount"] = "7000000"
    assert await signer.verify(policy["actions"][0], json.dumps(item).encode(), identity_id=identity_id) is False
    assert calls == [1]  # The adapter's self-reported True was not enough.
