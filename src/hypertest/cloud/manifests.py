"""Explicit Agent handoff schema; raw SDK text and arbitrary files are not input."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .artifacts import read_workspace_file
from .errors import CloudBlocked
from .handoff_contract import handoff_contract, ssh_client_instructions
from .ssh_profile import SSH_ACCESS_PROFILE, SshProfile

MANIFEST_PROFILE = "hypertest-cloud-handoff/v1alpha1"


class Handoff(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    profile: str
    task_id: str
    attempt_id: str
    key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
    operation: str
    payload: dict


def load_handoff(workspace: Path, relative: str, *, task_id: str, attempt_id: str) -> tuple[Handoff, str]:
    if not re.fullmatch(r"\.hypertest-cloud/ready/[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\.json", relative):
        raise CloudBlocked("HANDOFF_PATH_INVALID", "Only the declared ready manifest directory is collected")
    raw = read_workspace_file(workspace, relative, max_bytes=1024 * 1024)
    try:
        handoff = Handoff.model_validate_json(raw)
    except Exception as exc:
        raise CloudBlocked("HANDOFF_SCHEMA_INVALID", "Formal handoff does not match the strict schema") from exc
    if (handoff.profile != MANIFEST_PROFILE or handoff.task_id != task_id or handoff.attempt_id != attempt_id):
        raise CloudBlocked("HANDOFF_OWNER_MISMATCH", "Formal handoff belongs to a different profile/task/attempt")
    if handoff.operation not in {"SUBMIT_ASSETS", "UPLOAD_ARTIFACT", "SUBMIT_RUN", "SUBMIT_DELEGATION", "COMPLETE_ATTEMPT", "REQUEST_INPUT"}:
        raise CloudBlocked("HANDOFF_OPERATION_UNSUPPORTED", "Agent handoff cannot perform control-plane operations")
    forbidden = {"profile", "project_id", "task_id", "attempt_id", "operation", "operation_key", "expected_version",
                 "budget_reservation", "budget_settlement"}
    if forbidden & handoff.payload.keys():
        raise CloudBlocked("HANDOFF_AUTHORITY_OVERRIDE", "Worker owns platform identity and mutation metadata")
    return handoff, hashlib.sha256(raw).hexdigest()


def task_prompt(task: dict, attempt: dict, *, allow_delegation: bool = False,
                ssh_profile: SshProfile | None = None) -> str:
    """Only non-secret frozen testing inputs; Agent gets no management token."""
    envelope = {"task_id": task["id"], "attempt_id": attempt["id"],
                "frozen_manifest": task["frozen_manifest"],
                "handoff_profile": MANIFEST_PROFILE,
                "handoff_directory": ".hypertest-cloud/ready",
                "handoff_contract": handoff_contract(task_id=task["id"], attempt_id=attempt["id"],
                                                     allow_delegation=allow_delegation),
                "capabilities": {"workspace_local_tests": True, "remote_network": False,
                                 "external_codex_or_claude": allow_delegation,
                                 "codex": allow_delegation, "claude_code": "PLACEHOLDER"},
                "instructions": [
                    "Use the existing framework in /workspace/framework and SUT source in /workspace/sut.",
                    "Publish deliberate versioned test artifacts/checkpoints with exact original text; never publish chat, reasoning, prompts or credentials.",
                    "Publish each immutable handoff atomically as KEY.json in .hypertest-cloud/ready. Set profile, task_id, attempt_id, key, operation, payload.",
                    "Operations use Cloud typed payload fields only; the Worker supplies auth, IDs, operation key and expected version.",
                    "SUBMIT_ASSETS uses assets and optional checkpoint_report_key. Include REPORT milestones while running.",
                    "UPLOAD_ARTIFACT uses path, filename, media_type, sha256, byte_count; paths are relative regular files under the workspace.",
                    "SUBMIT_RUN records actual framework observations and already accepted original report/log artifact IDs; never invent a run from SDK events.",
                    "The Worker writes per-key accepted receipts to .hypertest-cloud/receipts; wait for these exact IDs before referencing assets/artifacts.",
                    "Finish only by an explicit COMPLETE_ATTEMPT payload naming final_report_revision and completion_manifest; idle/answer/upload success is not completion or PASS.",
                    "General remote shell, CI and Git writes are unavailable. Use only explicitly admitted fixed SSH diagnostics, if declared below; report all other remote scope as a gap.",
                    "Preserve each failure and correction as a new revision/run, and include unobserved scope in the final report."]}
    if ssh_profile is not None:
        envelope["capabilities"]["ssh"] = {"profile": SSH_ACCESS_PROFILE,
            "actions": [action.key for action in ssh_profile.actions],
            "max_operations": ssh_profile.max_operations, "general_remote_shell": False,
            "closes_before_task_deadline_seconds": 30}
        envelope["instructions"].append("The SSH scope closes 30 seconds before the original total task deadline for bounded cleanup. If it returns REFUSED, finish the remaining workspace work and report the gap; do not retry the action or treat scope closure as task completion.")
        envelope["instructions"].extend(ssh_client_instructions())
    else:
        envelope["capabilities"]["ssh"] = False
        envelope["instructions"].append("SSH diagnostics are unavailable in this profile.")
    if allow_delegation:
        envelope["instructions"].extend([
            "Delegate only through the official subagent_codex tool. Each call is a fresh one-shot native Codex task in this workspace; there is no resume or follow-up.",
            "Call subagent_codex with description, a complete self-contained prompt, and explicit cwd=/workspace/framework. Give the child absolute /workspace/sut paths for read-only source and request a short original contribution file inside /workspace/framework; the child must not publish ready handoffs or call platform APIs.",
            "Each child contributes artifacts to this parent mission and receives no platform token. You alone publish formal handoffs after collecting and checking its original files.",
            "Read and check the child's original contribution before integrating it. Publish small handoff batches: the first asset batch has at most two assets including a REPORT; wait for its accepted receipt before the next batch. Keep the frozen PRD objectives and required outputs; include contributed files in the implementation originals and dirty/untracked inventory.",
            "After the official terminal completion notice, publish SUBMIT_DELEGATION with native_ref equal to the tool's returned child UUID, provider codex, responsibility and accepted asset_ids; the Worker supplies terminal observations/status.",
            "Wait for every native child to finish and for each delegation receipt before terminal/input handoff. A child answer is not a test result.",
            "After publishing COMPLETE_ATTEMPT or REQUEST_INPUT, finish your turn immediately without waiting for that terminal receipt; the Worker waits for the official native metadata channel to close, stops the namespace and then accepts it.",
            "Claude Code remains unavailable. Cloud Codex OAuth is provided only through the model relay; never read or create real login files.",
        ])
    else:
        envelope["instructions"].append("External CLI delegation is unavailable in this profile.")
    return json.dumps(envelope, ensure_ascii=False)
