"""python -m hypertest.cloud [--once]; requires both Cloud opt-in settings."""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
from uuid import uuid4

from hypertest.config import get_settings


async def run(*, once: bool) -> int:
    settings = get_settings()
    if not settings.cloud_enabled or not settings.cloud_worker_enabled:
        print(json.dumps({"code": "CLOUD_WORKER_DISABLED", "model_started": False}))
        return 78
    service_release = getattr(settings, "cloud_service_release_sha256", "")
    if service_release:
        from .worker_admission import admit_credentials, blocked_observation, inspect_admission

        try:
            inspect_admission(settings, release_sha256=service_release)
        except Exception as error:
            print(json.dumps(blocked_observation(error, scope="SERVICE_STARTUP_ONLY")), flush=True)
            return 1
    # Import persistence only in the explicitly enabled dedicated worker.
    from hypertest.db.session import AsyncSessionLocal, engine

    from .worker import CloudWorker
    from .worker_diagnostics import exception_metadata, failure_code, failure_metadata

    worker = CloudWorker(AsyncSessionLocal, settings, "cloud-worker-" + uuid4().hex)
    active = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, active.cancel)
    last_failure = None
    cancelled = False
    exit_code = 0
    try:
        while True:
            if service_release:
                try:
                    admit_credentials(settings)
                except Exception as error:
                    last_failure = error
                    print(json.dumps(blocked_observation(error, scope="BEFORE_NEXT_CLAIM")), flush=True)
                    exit_code = 1
                    break
            try:
                worked = await worker.run_once()
            except Exception as error:
                # No raw DB, model, Git, tool or credential exception text.
                last_failure = error
                print(json.dumps({"code": failure_code(error),
                    "worker_diagnostics": failure_metadata(error)}), flush=True)
                # A namespace failure is cached for this process. Stop instead
                # of repeatedly logging the same blocked admission every poll.
                if once or getattr(worker, "_namespace_failure", None) is not None:
                    exit_code = 1
                    break
                worked = False
            if once:
                print(json.dumps({"work_claimed": worked}), flush=True)
                break
            if not worked:
                await asyncio.sleep(settings.cloud_worker_poll_seconds)
    except asyncio.CancelledError:
        cancelled = True
        exit_code = 130
    finally:
        try:
            await engine.dispose()
        except Exception as error:
            metadata = failure_metadata(last_failure) if last_failure is not None else failure_metadata(error)
            metadata["secondary"] = (metadata["secondary"] + [
                {"stage": "ENGINE_DISPOSE", "error": exception_metadata(error)}])[:8]
            print(json.dumps({"code": failure_code(last_failure) if last_failure is not None else "CLOUD_WORKER_CLEANUP_FAILED",
                "worker_diagnostics": metadata}), flush=True)
            if not cancelled:
                exit_code = 1
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dedicated opt-in HyperTest Cloud worker")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    return asyncio.run(run(once=args.once))


if __name__ == "__main__":
    raise SystemExit(main())
