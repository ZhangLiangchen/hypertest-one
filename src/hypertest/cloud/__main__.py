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
    docker_enabled = getattr(settings, "cloud_docker_enabled", False)
    if docker_enabled:
        # Do not claim or contact a database while the implementation gate is closed.
        if not getattr(settings, "cloud_container_intents_enabled", False):
            print(json.dumps({"code": "CLOUD_DOCKER_NOT_READY", "work_claimed": False, "model_started": False}), flush=True)
            return 1
    service_release = getattr(settings, "cloud_service_release_sha256", "")
    if docker_enabled and not service_release:
        print(json.dumps({"code": "WORKER_RELEASE_INVALID", "work_claimed": False, "model_started": False}), flush=True)
        return 1
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

    docker_runtime = None
    if docker_enabled:
        from .docker_attempt import DockerEngine
        from .docker_attempt_spec import ResourceLimit
        from .docker_runtime import DockerRuntime
        from .docker_service_admission import load_docker_service_profile

        try:
            profile = load_docker_service_profile()
            docker_runtime = DockerRuntime(settings=settings, profile=profile, sessions=AsyncSessionLocal,
                engine=DockerEngine(profile.docker_socket_target),
                attempt_limit=ResourceLimit(memory=2 * 1024**3, memory_swap=2 * 1024**3, pids=128))
        except Exception as error:
            print(json.dumps(blocked_observation(error, scope="SERVICE_STARTUP_ONLY")), flush=True)
            await engine.dispose()
            return 1
    worker_options = {"docker_runtime": docker_runtime} if docker_enabled else {}
    if docker_enabled:
        # The controlled-action implementation remains separately gated; a
        # Cloud worker or a frozen plan alone cannot enable external writes.
        if getattr(settings, "cloud_controlled_actions_enabled", False):
            from .action_observer import ActionObserver
            from .action_runtime import ActionRuntime

            worker_options["action_runtime"] = ActionRuntime(sessions=AsyncSessionLocal, observer_factory=ActionObserver)
    worker = CloudWorker(AsyncSessionLocal, settings, "cloud-worker-" + uuid4().hex, **worker_options)
    active = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, active.cancel)
    last_failure = None
    last_attempt_admission_code = None
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
                code = failure_code(error)
                attempt_admission = getattr(worker, "_attempt_admission_failure", None)
                if not attempt_admission or code != last_attempt_admission_code:
                    print(json.dumps({"code": code,
                        "worker_diagnostics": failure_metadata(error)}), flush=True)
                last_attempt_admission_code = code if attempt_admission else None
                # A namespace failure is cached for this process. Stop instead
                # of repeatedly logging the same blocked admission every poll.
                if once or getattr(worker, "_namespace_failure", None) is not None:
                    exit_code = 1
                    break
                worked = False
            else:
                last_attempt_admission_code = None
            if once:
                print(json.dumps({"work_claimed": worked}), flush=True)
                break
            if not worked:
                await asyncio.sleep(settings.cloud_worker_poll_seconds)
    except asyncio.CancelledError:
        cancelled = True
        exit_code = 130
    finally:
        if docker_runtime is not None:
            docker_runtime.close()
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
