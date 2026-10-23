"""Optional official DeepSeek Harness SDK metadata and no-prompt probe.

No import here starts a runtime, reads credentials, or changes Local sync.
"""

from .compatibility import inspect_compatibility
from .errors import AdapterError, CapabilityError, DependencyError, RecoveryRequired
from .models import (
    SDK_VERSION,
    ProtocolProbeReport,
    SdkCompatibility,
    StopObservation,
)
from .probe import probe_protocol

__all__ = [
    "SDK_VERSION", "AdapterError", "CapabilityError",
    "DependencyError", "ProtocolProbeReport", "RecoveryRequired",
    "SdkCompatibility", "StopObservation", "inspect_compatibility", "probe_protocol",
]
