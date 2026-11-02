"""Observe model authentication independently of task scheduling.

Only a fixed, redacted observation is published. Failure to observe or persist
must never interrupt a Cloud attempt or reveal a provider response.
"""
from __future__ import annotations

import asyncio

from hypertest.application.cloud_agent_auth import record_worker_auth_status
from hypertest.cloud.auth_probe import probe_deepseek_auth

POLL_SECONDS = 60


async def monitor_agent_auth(sessions, settings, worker_id: str) -> None:
    while True:
        try:
            status = await asyncio.to_thread(probe_deepseek_auth, settings.cloud_model_key_file)
            await record_worker_auth_status(sessions, worker_id, status)
        except Exception:
            # Do not serialize exception text: transports and DB errors may
            # contain private data. Existing observations expire server-side.
            pass
        await asyncio.sleep(POLL_SECONDS)
