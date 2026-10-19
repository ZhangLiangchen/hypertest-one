"""Connector envelopes are independent from the existing UDS Bridge contract."""
import hashlib
import re
from typing import Any

from hypertest.harness_bridge.protocol import PROFILE, PROTOCOL, canonical

TRANSPORT = "hypertest.harness-connector/v1alpha1"
MAX_MESSAGE = 4_000_000
MAX_QUEUE = 256
MAX_TTL_SECONDS = 120
BRIDGE_EXECUTION = frozenset({'create_session','execute','resume','get_call','renew','respond_tool'})
BRIDGE_MANAGEMENT = frozenset({'capabilities','get_call','restore_session','interrupt','close','recover'})
INTEGRATION = frozenset({'prepare_source','install_workspace','issue_create','issue_query','source_prepare'})
OPERATIONS = BRIDGE_EXECUTION | BRIDGE_MANAGEMENT | INTEGRATION
ERROR_CODE = re.compile(r'^[A-Z][A-Z0-9_]{0,63}$')


def digest(payload: Any) -> str:
    return hashlib.sha256(canonical(payload)).hexdigest()


def claim_identity(node_id: str, claim_token: str) -> str:
    # The device can fence a stable opaque identity, but never receives Job's secret.
    return hashlib.sha256(f'{TRANSPORT}:{node_id}:{claim_token}'.encode()).hexdigest()


def hello(node_id: str, capabilities: dict[str, Any]) -> dict[str, Any]:
    return {'type':'hello','transport':TRANSPORT,'protocol':PROTOCOL,'profile':PROFILE,
            'node_id':node_id,'capabilities':capabilities,'max_message':MAX_MESSAGE}
