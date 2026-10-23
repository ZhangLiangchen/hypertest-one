"""Model-readable, derived Cloud handoff contracts; no platform authority is exposed."""
from __future__ import annotations

import hashlib
from copy import deepcopy
from uuid import UUID

from hypertest.api.cloud_schemas import (
    PROFILE,
    CloudArtifactUpload,
    CloudDelegationSubmit,
    CloudFinish,
    CloudQuestionSubmit,
    CloudRunSubmit,
    CloudSubmitAssets,
)

HANDOFF_PROFILE = "hypertest-cloud-handoff/v1alpha1"
HANDOFF_DIRECTORY = ".hypertest-cloud/ready"
RECEIPT_DIRECTORY = ".hypertest-cloud/receipts"
REJECTION_DIRECTORY = ".hypertest-cloud/rejections"
WORKER_FIELDS = frozenset({"profile", "project_id", "task_id", "attempt_id", "operation",
    "operation_key", "expected_version", "budget_reservation", "budget_settlement"})


def ssh_client_instructions() -> list[str]:
    """Only action keys cross the namespace boundary; no remote shell payload."""
    return [
        "Fixed SSH diagnostics are available only through the host broker socket /run/hypertest-ssh.sock; the namespace has no SSH credentials or general network.",
        "Invoke one frozen no-argument action with python -m hypertest.cloud.ssh_client invoke --key KEY --action ACTION. Use a stable key once; never send a target, command, arguments, environment, private key or platform identity.",
        "For SENT, UNKNOWN, a lost response or NOT_FOUND, query the original operation UUID using python -m hypertest.cloud.ssh_client query --operation UUID. Never invoke again, change the key or recreate the diagnostic to repeat it.",
        "Only fixed environment diagnostics are admitted. SSH exit status, an action result or a successful query is not a test PASS, deployment identity proof or task completion.",
        "The host records remote operations and separately observes their terminal state and empty cgroup. Publishing COMPLETE_ATTEMPT does not assert remote shutdown; unknown operations keep the Task in recovery with its reservation held.",
    ]


def handoff_semantics() -> dict:
    """Expose cross-field validators and DB rules JSON Schema cannot compare."""
    return {
        "typed_validators": [
            {"source_validator": "Input.bounded", "rule": "Each host-materialized typed request must serialize to at most 12 MiB UTF-8 JSON; the ready manifest itself is limited to 1 MiB."},
            {"source_validator": "Asset.content", "rule": "CASE details must contain steps, expected and actual keys. Every non-CASE asset needs nonempty markdown or an accepted artifact_id; details alone do not deliver original text."},
            {"source_validator": "CloudSubmitAssets.unique_assets", "rule": "Within one batch, each (kind,key) pair is unique. A non-null checkpoint_report_key must exactly equal a REPORT key in this same assets batch; a previous receipt or CASE key does not qualify."},
            {"source_validator": "RunExecution.observed", "rule": "If finished_at or exit_code is absent/null, supply nonempty unobserved_reason. A provided finished_at must be >= started_at. CI source requires a nonempty ci_identity; use PROJECT_FRAMEWORK in this workspace-only profile."},
        ],
        "reference_and_state_rules": [
            "An Artifact UUID is not an AssetRevision UUID. UPLOAD_ARTIFACT creates accepted original bytes only, not an asset revision. Within SUBMIT_ASSETS, its receipt.artifact_id belongs only in asset.artifact_id, never referenced_asset_ids. An upload is not a CASE or REPORT revision.",
            "referenced_asset_ids must be [] when no asset dependency exists, or exact AssetRevision UUIDs from this Task's earlier ACCEPTED SUBMIT_ASSETS receipt.assets[].id. Never guess or predeclare IDs, use an upload UUID, or reference a newly submitted sibling in the same batch; wait for its accepted receipt before publishing a dependent handoff.",
            "Database validation remains authoritative: artifact_id resolves an accepted CloudArtifact, while referenced_asset_ids resolves CloudAssetRevision rows owned by this Task. UUID shape and local typed validation cannot prove either identity; a platform HTTP rejection does not become LOCAL_REJECTED or authorize a replacement POST.",
            "IMPLEMENTATION.details requires framework_sha equal to the frozen framework commit, plus cwd, dirty_files, untracked_files and test_tree_digest. Dirty or untracked changes require an accepted artifact_id containing the complete patch/new-file originals.",
            "SUBMIT_RUN execution.framework_sha and entrypoint must exactly match the frozen framework commit and allowed entrypoint. Use unique case_revision_id values from accepted CASE receipts; every referenced CASE/artifact must belong to this Task. A run_key is immutable and each actual rerun uses a new key.",
            "COMPLETE_ATTEMPT final_report_revision must be an accepted REPORT from this Attempt with the same reported_result. required_asset_ids must name this Attempt's accepted expected stage kinds and contain final_report_revision; use an empty pending_operation_keys list.",
            "Completion needs actual Run records, or an explicit no_tests_reason and a non-PASS result. PASS requires the latest actual Run to report PASS without contradictory case outcomes; SDK idle cannot supply that result.",
            "REQUEST_INPUT required_action must already be in the frozen permitted_actions. Answers cannot enlarge authorization; this profile cannot resume a prior SDK runtime automatically.",
            "Typed payload validation happens before a new platform request is frozen. LOCAL_REJECTED with platform_operation_submitted=false is local feedback, never an ACCEPTED receipt or uploaded asset. Correct the contribution under a new handoff key; never change or resend the rejected published file.",
            "A SENT/UNKNOWN/frozen request is not locally rejected. Reconcile only its original operation key; absence or NOT_FOUND never authorizes a new handoff, new POST or replacement task to repeat that operation.",
        ],
    }


def _semantic_schema(definitions: dict) -> None:
    asset = definitions["Asset"]
    asset["properties"]["artifact_id"]["description"] = (
        "Original-content CloudArtifact UUID from this Task's earlier ACCEPTED UPLOAD_ARTIFACT receipt.artifact_id. "
        "It is not an AssetRevision UUID; within SUBMIT_ASSETS put this upload UUID only here, never in referenced_asset_ids.")
    asset["properties"]["referenced_asset_ids"]["description"] = (
        "AssetRevision dependencies only: use [] for no dependency, or exact UUIDs from this Task's earlier ACCEPTED "
        "SUBMIT_ASSETS receipt.assets[].id. Never use an UPLOAD_ARTIFACT UUID, guess/predeclare an ID, "
        "or reference a newly submitted asset in the same batch. Database ownership validation remains authoritative.")
    asset["properties"]["referenced_asset_ids"]["items"]["description"] = (
        "Previously accepted AssetRevision UUID, not a CloudArtifact UUID, stable asset key or operation key.")
    definitions["RunCase"]["properties"]["case_revision_id"]["description"] = (
        "Exact CASE AssetRevision UUID from ACCEPTED SUBMIT_ASSETS receipt.assets[].id, never an upload Artifact UUID.")
    asset["properties"]["details"]["description"] = (
        "CASE: include steps, expected, actual here, not only in markdown. "
        "IMPLEMENTATION: include frozen framework_sha, cwd, dirty_files, untracked_files, test_tree_digest.")
    asset["allOf"] = [
        {"if": {"properties": {"kind": {"const": "CASE"}}},
         "then": {"required": ["details"], "properties": {"details": {
             "type": "object", "required": ["steps", "expected", "actual"],
             "properties": {"steps": {}, "expected": {}, "actual": {}}}}},
         "else": {"anyOf": [
             {"required": ["markdown"], "properties": {"markdown": {"type": "string", "minLength": 1}}},
             {"required": ["artifact_id"], "properties": {"artifact_id": {"type": "string", "format": "uuid"}}},
         ]}},
        {"if": {"properties": {"kind": {"const": "IMPLEMENTATION"}}},
         "then": {"required": ["details"], "properties": {"details": {"type": "object",
             "required": ["framework_sha", "cwd", "dirty_files", "untracked_files", "test_tree_digest"]}}}},
    ]
    definitions["RunExecution"]["allOf"] = [
        {"if": {"anyOf": [
            {"not": {"required": ["finished_at"]}},
            {"required": ["finished_at"], "properties": {"finished_at": {"type": "null"}}},
            {"not": {"required": ["exit_code"]}},
            {"required": ["exit_code"], "properties": {"exit_code": {"type": "null"}}},
        ]}, "then": {"required": ["unobserved_reason"], "properties": {
            "unobserved_reason": {"type": "string", "minLength": 1}}}},
        {"if": {"properties": {"source": {"const": "CI"}}},
         "then": {"required": ["ci_identity"], "properties": {
             "ci_identity": {"type": "object", "minProperties": 1}}}},
    ]


def handoff_schema(*, task_id: str, attempt_id: str, allow_delegation: bool = False,
                   delegation_providers: tuple[str, ...] = ("codex",)) -> dict:
    """Return a fresh complete JSON Schema, derived from current typed API models.

    Files contain testing contributions only. Upload bytes and terminal/usage
    observations are materialized by the Worker, never supplied by the Agent.
    """
    task_id, attempt_id = str(UUID(task_id)), str(UUID(attempt_id))
    models = [CloudSubmitAssets, CloudArtifactUpload, CloudRunSubmit, CloudQuestionSubmit, CloudFinish]
    if allow_delegation:
        if not delegation_providers or set(delegation_providers) - {"codex", "claude-code"}:
            raise ValueError("Declare only admitted external delegation providers")
        models.append(CloudDelegationSubmit)
    definitions, variants = {}, []
    for model in models:
        source = deepcopy(model.model_json_schema(mode="validation"))
        definitions.update(source.pop("$defs", {}))
        properties = {key: value for key, value in source["properties"].items() if key not in WORKER_FIELDS}
        required = [key for key in source.get("required", []) if key not in WORKER_FIELDS]
        operation = source["properties"]["operation"]["const"]
        if model is CloudSubmitAssets:
            properties["assets"]["description"] = "Unique by (kind,key); CASE fields belong in details. See x-hypertest-semantics."
            properties["checkpoint_report_key"]["description"] = "Exact REPORT key from this same assets batch, or omit/null."
        removed = set()
        if model is CloudArtifactUpload:
            removed.add("content_base64")
            properties["path"] = {"type": "string", "minLength": 1, "maxLength": 2048,
                "pattern": r"^(?!/)(?!.*(?:^|/)\.\.?(?:/|$))[^\x00\\]+$",
                "description": "Workspace-relative regular UTF-8 file; compute exact byte_count and SHA-256 before atomic publication."}
            required.append("path")
        if model is CloudQuestionSubmit:
            removed.update({"local_processes_stopped", "external_operations_reconciled"})
        if model is CloudFinish:
            removed.update({"usage_seconds", "cost_microunits"})
            properties["final_report_revision"]["description"] = (
                "Accepted REPORT AssetRevision UUID from this Attempt's SUBMIT_ASSETS receipt.assets[].id, "
                "never an UPLOAD_ARTIFACT UUID.")
        if model is CloudDelegationSubmit:
            properties["provider"] = {"type": "string", "enum": sorted(set(delegation_providers))}
            properties["native_ref"] = {"type": "string", "format": "uuid",
                "description": "Exact child identifier from the admitted host delegation tool; never invent an identity."}
            required.append("native_ref")
            removed.update({"status", "terminal_observation"})
        properties = {key: value for key, value in properties.items() if key not in removed}
        required = [key for key in required if key not in removed]
        variants.append({"type": "object", "additionalProperties": False,
            "required": ["profile", "task_id", "attempt_id", "key", "operation", "payload"],
            "properties": {"profile": {"const": HANDOFF_PROFILE}, "task_id": {"const": task_id},
                "attempt_id": {"const": attempt_id},
                "key": {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$",
                    "description": "Use this same filename-safe stable key for KEY.json; do not include colons or path separators."},
                "operation": {"const": operation},
                "payload": {"type": "object", "additionalProperties": False,
                    "properties": properties, "required": required}}})
    _semantic_schema(definitions)
    completion = definitions["CompletionManifest"]
    host_observations = {"all_local_processes_stopped", "external_operations_reconciled"}
    completion["properties"] = {key: value for key, value in completion["properties"].items() if key not in host_observations}
    completion["required"] = [key for key in completion["required"] if key not in host_observations]
    completion["properties"]["pending_operation_keys"]["maxItems"] = 0
    completion["properties"]["required_asset_ids"]["description"] = (
        "Accepted AssetRevision UUIDs for this Attempt's required stage kinds, including the final REPORT revision; "
        "never upload Artifact UUIDs or unaccepted same-batch IDs.")
    root = {"$schema": "https://json-schema.org/draft/2020-12/schema", "oneOf": variants,
        "$comment": "Structural schema plus explicit cross-field/state rules; JSON Schema alone cannot compare receipt references or timestamps.",
        "x-hypertest-semantics": handoff_semantics()}
    # Remove unused API definitions, including Worker budget/authentication types.
    needed: set[str] = set()

    def references(value):
        if isinstance(value, dict):
            ref = value.get("$ref", "")
            if ref.startswith("#/$defs/") and ref[8:] not in needed:
                name = ref[8:]
                needed.add(name)
                references(definitions[name])
            for nested in value.values():
                references(nested)
        elif isinstance(value, list):
            for nested in value:
                references(nested)

    references(root)
    root["$defs"] = {key: definitions[key] for key in sorted(needed)}
    return root


def handoff_instructions() -> list[str]:
    return [
        "The supplied JSON Schema defines the complete payload; do not guess additional fields. IDs come only from this task and its accepted receipts.",
        "Write a new UTF-8 manifest to a temporary sibling, fsync and atomically rename it to .hypertest-cloud/ready/KEY.json. Never alter a published key or file.",
        "Publish dependent contributions sequentially: wait for .hypertest-cloud/receipts/KEY.json before publishing a contribution that references its returned IDs. Filenames are processed lexically, not as dependency declarations.",
        "A receipt is written only after ACCEPTED and complete fixed-version readback. Its operation_key/version are Worker-owned; never submit platform API requests, tokens or replacement operation keys.",
        "SUBMIT_ASSETS receipt.assets entries contain exact id/kind/key/revision. Run cases use that CASE revision's id, never the stable case key or a later revision.",
        "A DESIGN may normally reference accepted ANALYSIS revisions. When this task requires both ANALYSIS and DESIGN to deliver the same child original directly, set artifact_id to that accepted child Artifact UUID on BOTH assets; also retain DESIGN.referenced_asset_ids=[accepted ANALYSIS revision id]. A transitive analysis reference does not satisfy an explicit direct-original requirement.",
        "Artifact UUIDs and AssetRevision UUIDs are different identities. After UPLOAD_ARTIFACT, first submit ANALYSIS with artifact_id=receipt.artifact_id and referenced_asset_ids=[]. Only after that SUBMIT_ASSETS is accepted may a later DESIGN use its receipt.assets[].id in referenced_asset_ids. Do not put upload IDs in CASE/report revision fields or guess same-batch asset IDs.",
        "For every CASE put steps, expected and actual inside details, even when markdown describes them. Include actual='Not executed' before a run instead of omitting actual. Each batch is unique by (kind,key); checkpoint_report_key must select a REPORT in that same batch.",
        "UPLOAD_ARTIFACT reads payload.path and replaces it with base64 internally. Its receipt.artifact_id/sha256/byte_count identify accepted original bytes; do not reference an upload before its receipt.",
        "SUBMIT_RUN requires exact frozen framework_sha, actual executed entrypoint from the frozen list, test_tree_digest, cwd, timestamps, exit_code, original report_artifact_ids and actual case observations. Do not claim an execution from SDK events.",
        "If any genuine failure occurs, preserve its run and original report, explain a correction in a new CASE/IMPLEMENTATION revision, rerun with a new run_key, and retain both runs. Do not manufacture a failure or weaken a valid assertion to manufacture PASS.",
        "IMPLEMENTATION requires framework_sha/cwd/dirty_files/untracked_files/test_tree_digest and complete accepted patch/new-file artifacts whenever files changed; hashes alone do not deliver code.",
        "Publish COMPLETE_ATTEMPT only after all required artifacts/runs have receipts. final_report_revision and required_asset_ids use accepted IDs from the current Attempt; pending_operation_keys must be empty or completion stays blocked.",
        "Completion or REQUEST_INPUT stops the namespace. Do not publish more work afterwards. Process stopping, external-action reconciliation, usage and budget settlement are host observations, never Agent-supplied fields.",
        "If delegation is admitted, SUBMIT_DELEGATION references the exact native_ref child UUID returned by the host tool. Status and terminal_observation are supplied only from host observations, never from Agent claims or in-process subagent.finished.",
        "Never publish authentication, secrets, full prompts, transcript, hidden reasoning or raw model-tool payloads. UNKNOWN/recovery requires the original receipt; do not replay work or mutate frozen handoffs.",
        "Check .hypertest-cloud/rejections/SHA256(KEY).json as well as the receipt path. LOCAL_REJECTED with platform_operation_submitted=false is pre-freeze local validation feedback, not platform ACK. Match key_sha256 and handoff_sha256; correct under a NEW key and leave the rejected file unchanged. Feedback gives only fixed error types/static schema locations, never an echoed input.",
        "No rejection file does not prove acceptance or non-submission. Pending/frozen/SENT/UNKNOWN, secret/security failures and platform HTTP rejection never use this correction path; preserve their original key and reconcile rather than publishing a replacement.",
    ]


def _artifact_to_asset_example(task_id: str, attempt_id: str) -> dict:
    """Illustrative sequential handoffs; no example ID is actual task evidence."""
    artifact_id = "00000000-0000-4000-8000-000000000003"
    analysis_revision_id = "00000000-0000-4000-8000-000000000005"
    path = "framework/analysis-example.md"
    original = "Example analysis original; no actual task evidence.\n"
    raw = original.encode("utf-8")
    upload = {"path": path, "filename": "analysis-example.md", "media_type": "text/markdown",
        "byte_count": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    def handoff(key, operation, payload):
        return {"profile": HANDOFF_PROFILE, "task_id": task_id, "attempt_id": attempt_id,
            "key": key, "operation": operation, "payload": payload}

    return {"example_file": {"path": path, "utf8": original}, "sequence": [
        {"handoff": handoff("01-example-upload-analysis", "UPLOAD_ARTIFACT", upload),
         "wait_for_accepted_receipt": {"status": "ACCEPTED", "operation": "UPLOAD_ARTIFACT",
             "artifact_id": artifact_id, "sha256": upload["sha256"], "byte_count": upload["byte_count"]}},
        {"handoff": handoff("02-example-analysis", "SUBMIT_ASSETS", {"assets": [
            {"kind": "ANALYSIS", "key": "example-analysis", "title": "Example analysis original",
             "artifact_id": artifact_id, "referenced_asset_ids": [], "reported_result": "NOT_RUN"}]}),
         "wait_for_accepted_receipt": {"status": "ACCEPTED", "operation": "SUBMIT_ASSETS", "assets": [
             {"id": analysis_revision_id, "kind": "ANALYSIS", "key": "example-analysis", "revision": 1}]}},
        {"handoff": handoff("03-example-design", "SUBMIT_ASSETS", {"assets": [
            {"kind": "DESIGN", "key": "example-design", "title": "Example dependency on accepted analysis",
             "markdown": "Design based on the preceding accepted analysis; no execution observed.",
             "artifact_id": artifact_id,
             "referenced_asset_ids": [analysis_revision_id], "reported_result": "NOT_RUN"}]})},
    ]}


def handoff_contract(*, task_id: str, attempt_id: str, allow_delegation: bool = False,
                     delegation_providers: tuple[str, ...] = ("codex",)) -> dict:
    """One bounded non-secret bundle suitable for a pinned task instruction file."""
    return {"profile": HANDOFF_PROFILE, "ready_directory": HANDOFF_DIRECTORY,
        "receipt_directory": RECEIPT_DIRECTORY, "local_rejection_directory": REJECTION_DIRECTORY,
        "schema": handoff_schema(task_id=task_id, attempt_id=attempt_id,
            allow_delegation=allow_delegation, delegation_providers=delegation_providers),
        "instructions": handoff_instructions(),
        "artifact_to_asset_example": _artifact_to_asset_example(str(UUID(task_id)), str(UUID(attempt_id))),
        "receipt_example": {"status": "ACCEPTED", "profile": PROFILE, "project_id": "00000000-0000-4000-8000-000000000001",
            "task_id": str(UUID(task_id)), "attempt_id": str(UUID(attempt_id)), "operation_key": "c:" + "0" * 64,
            "operation": "SUBMIT_ASSETS", "version": 7, "checkpoint": {},
            "assets": [{"id": "00000000-0000-4000-8000-000000000002", "kind": "CASE", "key": "case-add", "revision": 1}]},
        "receipt_reference_examples": {
            "upload": {"artifact_id": "00000000-0000-4000-8000-000000000003", "sha256": "0" * 64, "byte_count": 123},
            "run_case": {"case_revision_id": "00000000-0000-4000-8000-000000000002", "actual": "Observed assertion mismatch", "reported_result": "FAIL"},
            "completion": {"final_report_revision": "00000000-0000-4000-8000-000000000004",
                "reported_result": "FAIL", "completion_manifest": {"required_asset_ids": ["00000000-0000-4000-8000-000000000004"],
                    "pending_operation_keys": [], "scope_and_gaps": "Replace with complete current-attempt accepted asset IDs and actual observed scope."}},
        },
        "asset_batch_example": {"assets": [
            {"kind": "CASE", "key": "example-case", "title": "Example only: add_one zero boundary",
             "details": {"steps": ["Call add_one(0) using the frozen SUT"], "expected": "Result equals 1", "actual": "Not executed"},
             "reported_result": "NOT_RUN"},
            {"kind": "REPORT", "key": "example-progress", "title": "Example only: planned case", "markdown": "One case planned; no execution observed.", "reported_result": "NOT_RUN"},
        ], "checkpoint_report_key": "example-progress"},
        "example_notice": "Illustrative receipt IDs, hashes, counts and example assets are placeholders, never actual task evidence; replace them only using original bytes and this task's receipts."}
