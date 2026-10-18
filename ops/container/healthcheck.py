"""Container liveness with real database/own-worker heartbeat checks."""
import asyncio
import socket
import sys
import urllib.request


async def database(*, worker: bool) -> None:
    from sqlalchemy import text

    from hypertest.db.session import AsyncSessionLocal, engine

    try:
        async with AsyncSessionLocal() as session:
            if worker:
                # A healthy sibling cannot hide this container's dead Worker.
                found = await session.scalar(text(
                    "SELECT EXISTS (SELECT 1 FROM worker_heartbeats "
                    "WHERE split_part(worker_id, ':', 1) = :hostname "
                    "AND last_seen_at > clock_timestamp() - interval '30 seconds')"
                ), {"hostname": socket.gethostname()})
                if not found:
                    raise RuntimeError("this Worker's heartbeat is missing or stale")
            else:
                await session.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "api":
        with urllib.request.urlopen("http://127.0.0.1:8000/api/v1/health", timeout=4) as response:
            if response.status != 200:
                raise RuntimeError("API health request failed")
    asyncio.run(database(worker=mode == "worker"))
