"""Metadata-only inspection: importing this module does not import the SDK."""

from importlib import metadata

from .models import RUNTIME_DISTRIBUTION, SDK_DISTRIBUTION, SDK_VERSION, SdkCompatibility


def inspect_compatibility() -> SdkCompatibility:
    versions: list[str | None] = []
    issues: list[str] = []
    for name, label in ((SDK_DISTRIBUTION, "SDK"), (RUNTIME_DISTRIBUTION, "RUNTIME")):
        try:
            version = metadata.version(name)
        except metadata.PackageNotFoundError:
            version = None
        versions.append(version)
        if version is None:
            issues.append(f"{label}_NOT_INSTALLED")
        elif version != SDK_VERSION:
            issues.append(f"{label}_VERSION_UNSUPPORTED")
    if versions[0] is not None and versions[1] is not None and versions[0] != versions[1]:
        issues.append("SDK_RUNTIME_VERSION_MISMATCH")
    return SdkCompatibility(versions[0], versions[1], not issues, tuple(issues))
