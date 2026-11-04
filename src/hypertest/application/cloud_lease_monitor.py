"""Database-only lease expiry, independent of a surviving Worker poll loop."""
import asyncio
import logging
from contextlib import asynccontextmanager

from hypertest.config import get_settings


async def expire_loop():
    from hypertest.application.cloud_tasks import expire_leases
    from hypertest.db.session import AsyncSessionLocal
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await expire_leases(db)
        except Exception:
            # Never log DB URLs, driver messages or credentials.
            logging.getLogger(__name__).warning("CLOUD_LEASE_EXPIRY_UNAVAILABLE")
        await asyncio.sleep(15)


@asynccontextmanager
async def lifespan(_app):
    settings = get_settings()
    monitor = asyncio.create_task(expire_loop()) if settings.cloud_enabled and settings.cloud_worker_enabled else None
    try:
        yield
    finally:
        if monitor:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
