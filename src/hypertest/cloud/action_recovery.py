"""Worker-private, operator-authorized observation of one original SENT action.

This entry point never invokes an Agent, creates identities, or sends a DEX
request. The original attempt's pinned source is required and revalidated.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from hypertest.application.cloud_action_recovery import ActionRecoveryAuthority
from hypertest.cloud.action_observer import ActionObserver
from hypertest.cloud.action_signer import ActionSigner
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal


async def observe(task_id, attempt_id, authorization_key):
    authority = ActionRecoveryAuthority(AsyncSessionLocal, task_id=task_id,
        attempt_id=attempt_id, authorization_key=authorization_key)
    async with AsyncSessionLocal() as db:
        task, attempt, _, _, _, profile, _, _, _ = await authority._checked(db)
        export = task.inputs["agent_source_export"]
        source = Path(get_settings().cloud_runtime_root) / ("attempt-" + str(attempt.id)) / "private-signer-source"
    observer = ActionObserver(profile=profile)
    signer = ActionSigner(source_root=source, export_policy=export, action_profile=profile, authority=authority)
    result = await authority.observe_original(observer=observer, signer=signer)
    return {"status": "BUSINESS_TERMINAL" if result["business_terminal"] else "UNKNOWN",
            "recorded": result["recorded"], "observation": result["projection"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--authorization-key", required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(observe(args.task_id, args.attempt_id, args.authorization_key))
    except Exception as error:
        from hypertest.cloud.errors import CloudBlocked
        allowed = {"CONTROLLED_ACTION_OBSERVE_" + stage + "_UNAVAILABLE" for stage in
                   ("ORIGINAL", "OAUTH", "ORDER_GET", "DETAIL_GET", "ADAPTER", "VALIDATION", "AUTHORITY")}
        code = (error.code if isinstance(error, CloudBlocked) and error.code in allowed
                else "CONTROLLED_ACTION_OBSERVE_AUTHORITY_UNAVAILABLE")
        result = {"status": "UNKNOWN", "code": code}
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result["status"] == "BUSINESS_TERMINAL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
