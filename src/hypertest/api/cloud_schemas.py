"""Strict, bounded Cloud contracts. These never change SessionTask wire semantics."""
import ipaddress
import re
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_serializer,
    model_validator,
)

PROFILE = "cloud-harness-task/v1alpha1"
KEY = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
Result = Literal["NOT_RUN", "PASS", "FAIL", "ERROR", "SKIPPED", "UNKNOWN", "BLOCKED"]
Status = Literal["PREPARING", "RUNNING", "WAITING_INPUT", "RECOVERY_REQUIRED", "COMPLETED", "FAILED", "CANCELLED"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def bounded(self):
        if len(self.model_dump_json().encode()) > 12 * 1024 * 1024:
            raise ValueError("Cloud request exceeds 12 MiB")
        return self


class Selector(Input):
    kind: Literal["BRANCH", "SHA", "MR"] = "BRANCH"
    value: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9_./:-]*$")
    feat: str | None = Field(default=None, max_length=255)
    checkout_strategy: Literal["HEAD", "MERGE"] = "HEAD"
    base_ref: str | None = Field(default=None, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9_./-]*$")

    @model_validator(mode="after")
    def valid_ref(self):
        if self.kind == "SHA" and not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", self.value):
            raise ValueError("SHA requires full lowercase commit identity")
        if ".." in self.value or "@{" in self.value:
            raise ValueError("Unsafe Git selector")
        if self.kind == "MR" and (not self.value.isdigit() or int(self.value) <= 0 or not self.base_ref):
            raise ValueError("MR requires a positive identifier and explicit base_ref")
        if self.base_ref and (".." in self.base_ref or self.base_ref.endswith(".lock")):
            raise ValueError("Unsafe MR base ref")
        return self


class Repository(Input):
    url: str = Field(min_length=1, max_length=2048)
    default_selector: Selector | None = None
    credential_version_id: UUID | None = None

    @model_serializer(mode="wrap")
    def preserve_optional_selector(self, handler):
        result = handler(self)
        if self.default_selector is None:
            result.pop("default_selector", None)
        return result

    @field_validator("url")
    @classmethod
    def safe_url(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "ssh"} or not parsed.hostname or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Repository requires credential-free HTTPS or SSH URL")
        if parsed.username and (parsed.scheme != "ssh" or parsed.username != "git"):
            raise ValueError("Repository URL cannot contain credentials")
        return value


class SshDiagnosticAction(Input):
    key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    script_path: str = Field(min_length=2, max_length=255, pattern=r"^/opt/hypertest-ssh/actions/[A-Za-z0-9_.-]+$")
    script_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    timeout_seconds: int = Field(strict=True, ge=1, le=30)
    stdout_limit_bytes: int = Field(strict=True, ge=1, le=65536)
    stderr_limit_bytes: int = Field(strict=True, ge=1, le=65536)

    @field_validator("script_path")
    @classmethod
    def canonical_script_path(cls, value):
        if any(part in {"", ".", ".."} for part in value[1:].split("/")):
            raise ValueError("SSH action requires one fixed absolute regular script path")
        return value


class SshDiagnosticAccess(Input):
    profile: Literal["SSH_FIXED_DIAGNOSTICS_V1"]
    helper_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    catalog_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    authority_public_key: str = Field(min_length=64, max_length=255, pattern=r"^ssh-ed25519 [A-Za-z0-9+/]+={0,2}$")
    actions: list[SshDiagnosticAction] = Field(min_length=1, max_length=8)
    max_operations: int = Field(strict=True, ge=1, le=8)

    @model_validator(mode="after")
    def unique_actions(self):
        if len({action.key for action in self.actions}) != len(self.actions):
            raise ValueError("SSH diagnostic action keys must be unique")
        return self


class Environment(Input):
    name: str = Field(min_length=1, max_length=128)
    connection: Literal["NONE", "HTTPS", "SSH"] = "NONE"
    host: str | None = Field(default=None, max_length=255, pattern=r"^[A-Za-z0-9_.:-]+$")
    port: int | None = Field(default=None, ge=1, le=65535)
    user: str | None = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    host_key: str | None = Field(default=None, max_length=4096)
    network_requirements: str = Field(default="", max_length=4096)
    credential_version_id: UUID | None = None
    expected_deployment: str = Field(default="UNKNOWN", max_length=512)
    require_matching_deployment: bool = False
    ssh_access: SshDiagnosticAccess | None = None
    https_access: dict | None = None
    cloud_access_policy: Literal["LOCAL_ONLY", "WEB_ONLY"] | None = None

    @model_validator(mode="after")
    def ssh_identity(self):
        if self.https_access is not None:
            from hypertest.cloud.errors import CloudBlocked
            from hypertest.cloud.http_profile import validate_profile
            try:
                validate_profile(self.model_dump(mode="json"))
            except CloudBlocked:
                raise ValueError("HTTPS access requires the exact bounded public read profile") from None
        if self.connection == "SSH" and not (self.host and self.user and self.host_key):
            raise ValueError("SSH requires host, user and pinned host key")
        if self.ssh_access is not None:
            if self.connection != "SSH" or self.port is None or self.credential_version_id is None:
                raise ValueError("Executable SSH diagnostics require explicit SSH port and credential version")
            if self.user in {"root", "0"} or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", self.user or ""):
                raise ValueError("SSH diagnostics require an explicit non-root service user")
            try:
                address = ipaddress.ip_address(self.host)
            except ValueError:
                raise ValueError("SSH diagnostics require a canonical literal IP address") from None
            if str(address) != self.host:
                raise ValueError("SSH diagnostics require a canonical literal IP address")
            from hypertest.cloud.errors import CloudBlocked
            from hypertest.cloud.ssh_profile import validate_profile
            try:
                validate_profile(self.model_dump(mode="json"))
            except CloudBlocked:
                raise ValueError("SSH diagnostics require the exact pinned profile and catalog") from None
        return self

    @model_serializer(mode="wrap")
    def preserve_legacy_serialization(self, handler):
        result = handler(self)
        if self.ssh_access is None:
            # Existing frozen requests/configuration digests predate this opt-in
            # field. Absence must not silently add null to their full request.
            result.pop("ssh_access", None)
        if self.cloud_access_policy is None:
            result.pop("cloud_access_policy", None)
        if self.https_access is None:
            result.pop("https_access", None)
        return result


class Configuration(Input):
    sut: Repository
    framework: Repository
    environment: Environment


class Budgets(Input):
    accounting_unit: Literal["CONSERVATIVE_MICROUNITS", "REQUEST_CREDITS"] = "CONSERVATIVE_MICROUNITS"
    total_seconds: int = Field(ge=60, le=604800)
    total_cost_microunits: int = Field(ge=1, le=1_000_000_000_000)
    max_attempts: int = Field(default=3, ge=1, le=100)
    max_concurrency: int = Field(default=1, ge=1, le=16)


class Authorization(Input):
    targets: list[str] = Field(min_length=1, max_length=64)
    permitted_actions: list[Literal["git:read", "git:write", "environment:read", "environment:write", "framework:execute", "ci:execute", "issue:write"]] = Field(min_length=1, max_length=16)
    network_targets: list[str] = Field(default_factory=list, max_length=64)
    side_effect_limits: str = Field(min_length=1, max_length=16000)
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("Authorization expiration requires a timezone")
        return value


class TaskInputs(Input):
    sut_selector: Selector
    framework_selector: Selector
    prd_markdown: str = Field(min_length=1, max_length=262144)
    prd_version: str = Field(min_length=1, max_length=255)
    prd_source_ref: str | None = Field(default=None, max_length=2048)
    objective: str = Field(min_length=1, max_length=16000)
    basic_flow: str = Field(min_length=1, max_length=16000)
    test_scope: str = Field(min_length=1, max_length=16000)
    expected_outputs: list[Literal["ANALYSIS", "DESIGN", "CASE", "IMPLEMENTATION", "REPORT"]] = Field(default_factory=lambda: ["ANALYSIS", "DESIGN", "CASE", "IMPLEMENTATION", "REPORT"], min_length=1, max_length=5)
    framework_entrypoints: list[str] = Field(min_length=1, max_length=32)
    framework_runtime: dict | None = None
    authorization: Authorization
    budgets: Budgets

    @model_validator(mode="after")
    def frozen_framework(self):
        if self.framework_runtime is not None:
            from hypertest.cloud.errors import CloudBlocked
            from hypertest.cloud.framework_runtime import validate_runtime_spec
            try:
                self.framework_runtime = validate_runtime_spec(self.framework_runtime)
            except CloudBlocked:
                raise ValueError("Invalid frozen framework runtime specification") from None
            if (len(self.framework_entrypoints) != len(set(self.framework_entrypoints))
                    or {entry["key"] for entry in self.framework_runtime["entrypoints"]} != set(self.framework_entrypoints)):
                raise ValueError("Runtime entrypoint keys must exactly match the task entrypoints")
        return self

    @model_serializer(mode="wrap")
    def preserve_legacy_serialization(self, handler):
        result = handler(self)
        if self.framework_runtime is None:
            result.pop("framework_runtime", None)
        return result


class Mutation(Input):
    profile: Literal["cloud-harness-task/v1alpha1"] = PROFILE
    project_id: UUID
    operation_key: str = Field(pattern=KEY)
    expected_version: int = Field(ge=0)


class CloudConfigure(Mutation):
    operation: Literal["CONFIGURE"] = "CONFIGURE"
    configuration: Configuration


class CloudCredentialStore(Mutation):
    operation: Literal["STORE_CREDENTIAL"] = "STORE_CREDENTIAL"
    credential_id: UUID | None = None
    kind: Literal["GIT_TOKEN", "GIT_SSH_KEY", "SSH_KEY", "APPLICATION_PRIVATE_KEY"]
    label: str = Field(min_length=1, max_length=255)
    purpose: str = Field(min_length=1, max_length=255)
    allowed_targets: list[str] = Field(min_length=1, max_length=64)
    allowed_actions: list[str] = Field(min_length=1, max_length=16)
    expires_at: datetime | None = None
    secret: SecretStr = Field(min_length=1, max_length=65536)


class CloudCredentialRevoke(Mutation):
    operation: Literal["REVOKE_CREDENTIAL"] = "REVOKE_CREDENTIAL"
    credential_id: UUID
    reason: str = Field(min_length=1, max_length=4096)


class CloudTaskCreate(Mutation):
    operation: Literal["CREATE_TASK"] = "CREATE_TASK"
    title: str = Field(min_length=1, max_length=512)
    config_id: UUID
    inputs: TaskInputs
    related_task_id: UUID | None = None


class TaskMutation(Mutation):
    task_id: UUID


class CloudTaskUpdate(TaskMutation):
    operation: Literal["UPDATE_TASK"] = "UPDATE_TASK"
    title: str = Field(min_length=1, max_length=512)
    config_id: UUID
    inputs: TaskInputs


class CloudResolveRequest(TaskMutation):
    operation: Literal["RESOLVE_INPUTS"] = "RESOLVE_INPUTS"


class CloudDispatch(TaskMutation):
    operation: Literal["DISPATCH"] = "DISPATCH"
    resolution_id: UUID | None = None
    retry_of_attempt_id: UUID | None = None
    reason: str = Field(default="", max_length=4096)

    @model_validator(mode="after")
    def explicit_dispatch(self):
        if (self.resolution_id is None) == (self.retry_of_attempt_id is None):
            raise ValueError("Choose resolution or explicit retry")
        if self.retry_of_attempt_id and not self.reason.strip():
            raise ValueError("Retry requires reason")
        return self


class CloudTaskCancel(TaskMutation):
    operation: Literal["CANCEL_TASK"] = "CANCEL_TASK"
    reason: str = Field(min_length=1, max_length=4096)


class AttemptMutation(TaskMutation):
    attempt_id: UUID


class CloudCancel(AttemptMutation):
    operation: Literal["CANCEL_ATTEMPT"] = "CANCEL_ATTEMPT"
    reason: str = Field(min_length=1, max_length=4096)


class CloudResume(AttemptMutation):
    operation: Literal["RESUME_ATTEMPT"] = "RESUME_ATTEMPT"
    reason: str = Field(min_length=1, max_length=4096)
    reconciliation: dict = Field(min_length=1)


class CloudReconcile(AttemptMutation):
    operation: Literal["RECONCILE_ATTEMPT"] = "RECONCILE_ATTEMPT"
    status: Literal["CANCELLED", "FAILED"]
    reason: str = Field(min_length=1, max_length=4096)
    reconciliation: dict = Field(min_length=1)


BudgetScope = Literal["ROOT", "CODEX", "CLAUDE_CODE"]


class BudgetRequestLimit(Input):
    scope: BudgetScope
    max_requests: int = Field(strict=True, ge=1, le=10000)
    cost_per_request_microunits: int = Field(strict=True, ge=1, le=1_000_000_000_000)


class CloudBudgetReservation(Input):
    accounting_unit: Literal["CONSERVATIVE_MICROUNITS", "REQUEST_CREDITS"] = "CONSERVATIVE_MICROUNITS"
    reserved_seconds: int = Field(strict=True, ge=1, le=604800)
    request_limits: list[BudgetRequestLimit] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def unique_scopes(self):
        scopes = [item.scope for item in self.request_limits]
        if len(set(scopes)) != len(scopes) or "ROOT" not in scopes:
            raise ValueError("Reservation requires unique model scopes including ROOT")
        return self


class BudgetRequestObservation(Input):
    scope: BudgetScope
    requests: int = Field(strict=True, ge=0, le=10000)


class CloudBudgetSettlement(Input):
    accounting_unit: Literal["CONSERVATIVE_MICROUNITS", "REQUEST_CREDITS"] = "CONSERVATIVE_MICROUNITS"
    observed_seconds: int = Field(strict=True, ge=0, le=1_209_600)
    namespace_stopped: Literal[True]
    brokers_drained: Literal[True]
    requests: list[BudgetRequestObservation] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def unique_scopes(self):
        scopes = [item.scope for item in self.requests]
        if len(set(scopes)) != len(scopes):
            raise ValueError("Settlement requires unique observed model scopes")
        return self


class CloudContainerCreateIntent(AttemptMutation):
    """Private Worker registration only; does not itself authorize Docker I/O."""
    operation: Literal["PREPARE_CONTAINER_CREATE"] = "PREPARE_CONTAINER_CREATE"
    container_name: str = Field(pattern=r"^hypertest-attempt-[a-f0-9]{32}-[a-f0-9]{32}$")
    image_id: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    spec_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    key_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    clock_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    recovery_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    hard_deadline: int = Field(strict=True, gt=0, le=253402300799)
    spec: dict


class CloudContainerObservation(AttemptMutation):
    operation: Literal["CONFIRM_CONTAINER_ID", "OBSERVE_CONTAINER_STOP", "OBSERVE_CONTAINER_NEVER_STARTED"]
    create_operation_key: str = Field(pattern=KEY)
    container_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    spec_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    engine_status: Literal["created", "exited"]
    exit_code: int = Field(strict=True, ge=0, le=255)


class CloudContainerStartIntent(AttemptMutation):
    operation: Literal["PREPARE_CONTAINER_START"] = "PREPARE_CONTAINER_START"
    create_operation_key: str = Field(pattern=KEY)
    container_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    spec_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class CloudTransition(AttemptMutation):
    operation: Literal["TRANSITION"] = "TRANSITION"
    status: Literal["RUNNING", "FAILED", "RECOVERY_REQUIRED"]
    reason: str = Field(default="", max_length=4096)
    runtime_metadata: dict = Field(default_factory=dict)
    checkpoint: dict | None = None
    budget_reservation: CloudBudgetReservation | None = None
    budget_settlement: CloudBudgetSettlement | None = None

    @model_validator(mode="after")
    def worker_budget_metadata(self):
        if {"budget_reservation", "preparation_budget_reservation"} & self.runtime_metadata.keys():
            raise ValueError("Budget reservation requires the typed Worker field")
        if self.budget_reservation is not None and self.status != "RUNNING":
            raise ValueError("Only RUNNING admission reserves an execution budget")
        if self.budget_settlement is not None and self.status == "RUNNING":
            raise ValueError("An active runtime cannot settle its reservation")
        return self
    usage_seconds: int = Field(default=0, ge=0)
    cost_microunits: int = Field(default=0, ge=0)


class Asset(Input):
    kind: Literal["ANALYSIS", "DESIGN", "CASE", "IMPLEMENTATION", "REPORT"]
    key: str = Field(pattern=KEY)
    title: str = Field(min_length=1, max_length=512)
    markdown: str = Field(default="", max_length=524288)
    details: dict = Field(default_factory=dict)
    artifact_id: UUID | None = None
    reported_result: Result = "NOT_RUN"
    source: dict = Field(default_factory=dict)
    referenced_asset_ids: list[UUID] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def content(self):
        if not self.markdown and not self.artifact_id and self.kind != "CASE":
            raise ValueError("Asset requires original text or accepted artifact")
        if self.kind == "CASE" and not all(key in self.details for key in ("steps", "expected", "actual")):
            raise ValueError("CASE requires steps, expected and actual")
        return self


class CloudSubmitAssets(AttemptMutation):
    operation: Literal["SUBMIT_ASSETS"] = "SUBMIT_ASSETS"
    assets: list[Asset] = Field(min_length=1, max_length=200)
    checkpoint_report_key: str | None = Field(default=None, pattern=KEY)

    @model_validator(mode="after")
    def unique_assets(self):
        if len({(x.kind, x.key) for x in self.assets}) != len(self.assets):
            raise ValueError("Duplicate asset kind/key")
        if self.checkpoint_report_key and not any(x.kind == "REPORT" and x.key == self.checkpoint_report_key for x in self.assets):
            raise ValueError("checkpoint_report_key must select a submitted REPORT")
        return self


class CloudArtifactUpload(AttemptMutation):
    operation: Literal["UPLOAD_ARTIFACT"] = "UPLOAD_ARTIFACT"
    filename: str = Field(min_length=1, max_length=255, pattern=r"^[^/\\\x00]+$")
    media_type: Literal["text/plain", "text/markdown", "application/json", "application/xml", "text/x-diff"]
    content_base64: str = Field(max_length=11_184_816)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    byte_count: int = Field(ge=0, le=8 * 1024 * 1024)


class RunCase(Input):
    case_revision_id: UUID
    actual: str = Field(max_length=65536)
    reported_result: Result


class RunExecution(Input):
    source: Literal["PROJECT_FRAMEWORK", "CI"]
    actual_sut_build: str = Field(min_length=1, max_length=512)
    framework_sha: str = Field(pattern=r"^[a-f0-9]{40}([a-f0-9]{24})?$")
    test_tree_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    environment_observation: dict = Field(min_length=1)
    entrypoint: str = Field(min_length=1, max_length=8192)
    cwd: str = Field(min_length=1, max_length=2048)
    framework_version: str = Field(min_length=1, max_length=255)
    started_at: datetime
    finished_at: datetime | None = None
    exit_code: int | None = None
    unobserved_reason: str | None = Field(default=None, max_length=4096)
    ci_identity: dict | None = None

    @model_validator(mode="after")
    def observed(self):
        if (self.finished_at is None or self.exit_code is None) and not self.unobserved_reason:
            raise ValueError("Missing observations require explicit reason")
        if self.finished_at and self.finished_at < self.started_at:
            raise ValueError("Execution end precedes start")
        if self.source == "CI" and not self.ci_identity:
            raise ValueError("CI execution requires project/job identity")
        return self


class CloudRunSubmit(AttemptMutation):
    operation: Literal["SUBMIT_RUN"] = "SUBMIT_RUN"
    run_key: str = Field(pattern=KEY)
    execution: RunExecution
    reported_result: Result
    report_artifact_ids: list[UUID] = Field(min_length=1, max_length=32)
    log_artifact_ids: list[UUID] = Field(default_factory=list, max_length=32)
    cases: list[RunCase] = Field(default_factory=list, max_length=1000)


class CloudDelegationSubmit(AttemptMutation):
    operation: Literal["SUBMIT_DELEGATION"] = "SUBMIT_DELEGATION"
    delegation_key: str = Field(pattern=KEY)
    provider: Literal["deepseek", "codex", "claude-code"]
    responsibility: str = Field(min_length=1, max_length=16000)
    native_ref: str | None = Field(default=None, max_length=512)
    status: Literal["RUNNING", "COMPLETED", "FAILED", "CANCELLED", "UNKNOWN"]
    terminal_observation: dict | None = None
    asset_ids: list[UUID] = Field(default_factory=list, max_length=200)


class CloudQuestionSubmit(AttemptMutation):
    operation: Literal["REQUEST_INPUT"] = "REQUEST_INPUT"
    question_key: str = Field(pattern=KEY)
    question: str = Field(min_length=1, max_length=16000)
    options: list[str] = Field(default_factory=list, max_length=16)
    required_action: str = Field(min_length=1, max_length=255)
    checkpoint: dict = Field(min_length=1)
    local_processes_stopped: bool
    external_operations_reconciled: bool


class CloudAnswer(AttemptMutation):
    operation: Literal["ANSWER_INPUT"] = "ANSWER_INPUT"
    question_id: UUID
    answer: str = Field(min_length=1, max_length=16000)


class CompletionManifest(Input):
    required_asset_ids: list[UUID] = Field(min_length=1, max_length=1000)
    no_tests_reason: str | None = Field(default=None, max_length=16000)
    all_local_processes_stopped: bool
    external_operations_reconciled: bool
    pending_operation_keys: list[str] = Field(default_factory=list, max_length=200)
    scope_and_gaps: str = Field(min_length=1, max_length=16000)


class CloudFinish(AttemptMutation):
    operation: Literal["COMPLETE_ATTEMPT"] = "COMPLETE_ATTEMPT"
    final_report_revision: UUID
    reported_result: Result
    completion_manifest: CompletionManifest
    usage_seconds: int = Field(ge=0)
    cost_microunits: int = Field(ge=0)
    budget_settlement: CloudBudgetSettlement | None = None


CloudMutation = Annotated[CloudConfigure | CloudCredentialStore | CloudCredentialRevoke | CloudTaskCreate | CloudTaskUpdate | CloudResolveRequest | CloudDispatch | CloudTaskCancel | CloudCancel | CloudResume | CloudReconcile | CloudTransition | CloudContainerCreateIntent | CloudContainerObservation | CloudContainerStartIntent | CloudSubmitAssets | CloudArtifactUpload | CloudRunSubmit | CloudDelegationSubmit | CloudQuestionSubmit | CloudAnswer | CloudFinish, Field(discriminator="operation")]
