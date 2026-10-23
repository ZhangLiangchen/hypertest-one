"""Probe observations; none are canonical CloudTask state or test results."""

from dataclasses import dataclass

SDK_VERSION = "0.2.1rc2"
SDK_DISTRIBUTION = "deepseek-harness-sdk"
RUNTIME_DISTRIBUTION = "deepseek-harness-runtime-bin"
SERVER_NAME = "deepseek-harness-sdk-runtime"
SERVER_VERSION = "0.0.1"
PROFILE = "sdk"


@dataclass(frozen=True, slots=True)
class SdkCompatibility:
    sdk_version: str | None
    runtime_version: str | None
    compatible: bool
    issues: tuple[str, ...]

    def as_public_dict(self) -> dict[str, object]:
        return {
            "sdk_installed": self.sdk_version is not None,
            "runtime_installed": self.runtime_version is not None,
            "sdk_version": self.sdk_version,
            "runtime_version": self.runtime_version,
            "versions_match": self.sdk_version is not None and self.sdk_version == self.runtime_version,
            "pinned_version": SDK_VERSION,
            "compatible": self.compatible,
            "issues": list(self.issues),
        }


@dataclass(frozen=True, slots=True)
class StopObservation:
    root_reaped: bool
    process_group_absent: bool
    scope: str = "POSIX_PROCESS_GROUP"
    external_operations_reconciled: bool = False


@dataclass(frozen=True, slots=True)
class ProtocolProbeReport:
    runtime_started: bool
    initialized: bool
    session_created: bool
    runtime_closed: bool
    server_name: str
    server_version: str

    def as_public_dict(self) -> dict[str, object]:
        return {
            "runtime_started": self.runtime_started,
            "initialized": self.initialized,
            "session_created": self.session_created,
            "runtime_closed": self.runtime_closed,
            "server_name": self.server_name,
            "server_version": self.server_version,
            "model_prompt_sent": False,
            "test_result": "NOT_RUN",
        }
