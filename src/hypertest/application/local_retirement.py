"""New Local writes retire after original-key lookup; history stays readable."""
from fastapi import HTTPException

from hypertest.config import get_settings


def require_legacy_local_write():
    if not get_settings().local_session_writes_enabled:
        raise HTTPException(410, "LOCAL_SYNC_RETIRED_USE_EXPLICIT_ARCHIVE")
