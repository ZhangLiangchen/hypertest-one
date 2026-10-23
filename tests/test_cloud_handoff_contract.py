"""Derived Agent contracts validate real API payloads without exposing authority."""
import base64
import hashlib
import json
from copy import deepcopy

import jsonschema
import pytest
from pydantic import TypeAdapter, ValidationError

from hypertest.api.cloud_schemas import (
    Asset,
    CloudArtifactUpload,
    CloudDelegationSubmit,
    CloudFinish,
    CloudMutation,
    CloudQuestionSubmit,
    CloudRunSubmit,
    CloudSubmitAssets,
    RunExecution,
)
from hypertest.cloud.handoff_contract import handoff_contract, handoff_schema, handoff_semantics

TASK = "00000000-0000-4000-8000-000000000011"
ATTEMPT = "00000000-0000-4000-8000-000000000012"
ASSET = "00000000-0000-4000-8000-000000000013"
PROJECT = "00000000-0000-4000-8000-000000000014"
ARTIFACT = "00000000-0000-4000-8000-000000000015"
REPORT = "00000000-0000-4000-8000-000000000016"


def typed_operation(operation, payload):
    return TypeAdapter(CloudMutation).validate_python({**deepcopy(payload), "project_id": PROJECT,
        "task_id": TASK, "attempt_id": ATTEMPT, "operation_key": "worker-key",
        "expected_version": 1, "operation": operation})


def agent_handoff(operation, payload):
    return {"profile": "hypertest-cloud-handoff/v1alpha1", "task_id": TASK, "attempt_id": ATTEMPT,
        "key": "one", "operation": operation, "payload": payload}


def samples():
    return {
        "SUBMIT_ASSETS": {"assets": [{"kind": "CASE", "key": "case-one", "title": "One", "details": {"steps": ["Observe"], "expected": "match", "actual": "mismatch"}, "reported_result": "FAIL"}]},
        "UPLOAD_ARTIFACT": {"path": "framework/report.txt", "filename": "report.txt", "media_type": "text/plain", "byte_count": 4, "sha256": hashlib.sha256(b"FAIL").hexdigest()},
        "SUBMIT_RUN": {"run_key": "observed-failure", "execution": {"source": "PROJECT_FRAMEWORK", "actual_sut_build": "UNKNOWN", "framework_sha": "a" * 40, "test_tree_digest": "b" * 64,
            "environment_observation": {"kind": "contract-fixture"}, "entrypoint": "python -m pytest", "cwd": "/workspace/framework", "framework_version": "fixture", "started_at": "2026-10-22T10:00:00Z", "finished_at": "2026-10-22T10:00:01Z", "exit_code": 1},
            "reported_result": "FAIL", "report_artifact_ids": [ARTIFACT], "cases": [{"case_revision_id": ASSET, "actual": "Observed mismatch", "reported_result": "FAIL"}]},
        "REQUEST_INPUT": {"question_key": "missing-input", "question": "Supply the declared fixture version", "required_action": "framework:execute", "checkpoint": {"fixture": "stopped"}},
        "COMPLETE_ATTEMPT": {"final_report_revision": REPORT, "reported_result": "FAIL", "completion_manifest": {"required_asset_ids": [REPORT], "scope_and_gaps": "Contract fixture only; no real execution"}},
    }


@pytest.mark.parametrize("operation,payload", list(samples().items()))
def test_agent_schema_matches_host_materialized_typed_operation(operation, payload):
    schema = handoff_schema(task_id=TASK, attempt_id=ATTEMPT)
    jsonschema.Draft202012Validator.check_schema(schema)
    handoff = {"profile": "hypertest-cloud-handoff/v1alpha1", "task_id": TASK, "attempt_id": ATTEMPT,
        "key": "one", "operation": operation, "payload": payload}
    jsonschema.validate(handoff, schema)
    host = deepcopy(payload)
    if operation == "UPLOAD_ARTIFACT":
        del host["path"]
        host["content_base64"] = base64.b64encode(b"FAIL").decode()
    if operation == "REQUEST_INPUT":
        host.update(local_processes_stopped=True, external_operations_reconciled=True)
    if operation == "COMPLETE_ATTEMPT":
        host.update(usage_seconds=1, cost_microunits=0)
        host["completion_manifest"].update(all_local_processes_stopped=True, external_operations_reconciled=True)
    typed = TypeAdapter(CloudMutation).validate_python({**host, "project_id": PROJECT, "task_id": TASK,
        "attempt_id": ATTEMPT, "operation_key": "worker-key", "expected_version": 1, "operation": operation})
    assert typed.operation == operation


@pytest.mark.parametrize("field", ["project_id", "operation_key", "expected_version", "budget_reservation", "budget_settlement"])
def test_agent_schema_rejects_worker_authority_fields(field):
    handoff = {"profile": "hypertest-cloud-handoff/v1alpha1", "task_id": TASK, "attempt_id": ATTEMPT,
        "key": "one", "operation": "SUBMIT_ASSETS", "payload": {**samples()["SUBMIT_ASSETS"], field: "forbidden"}}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(handoff, handoff_schema(task_id=TASK, attempt_id=ATTEMPT))


def test_schema_binds_owner_and_omits_unadmitted_delegation_and_budget_definitions():
    schema = handoff_schema(task_id=TASK, attempt_id=ATTEMPT)
    operations = {item["properties"]["operation"]["const"] for item in schema["oneOf"]}
    assert operations == set(samples())
    assert not any("Budget" in name or "Credential" in name for name in schema["$defs"])
    schema["oneOf"][0]["properties"]["task_id"]["const"] = "changed"
    assert handoff_schema(task_id=TASK, attempt_id=ATTEMPT)["oneOf"][0]["properties"]["task_id"]["const"] == TASK
    enabled = handoff_schema(task_id=TASK, attempt_id=ATTEMPT, allow_delegation=True)
    delegation = next(row for row in enabled["oneOf"] if row["properties"]["operation"]["const"] == "SUBMIT_DELEGATION")
    assert delegation["properties"]["payload"]["properties"]["provider"]["enum"] == ["codex"]


def test_bundle_explains_immutable_receipts_original_bytes_and_exact_case_revision():
    bundle = handoff_contract(task_id=TASK, attempt_id=ATTEMPT)
    text = json.dumps(bundle)
    assert len(text.encode()) < 96 * 1024
    assert "case_revision_id" in text and "artifact_id" in text and "byte_count" in text
    assert "atomically rename" in text and "lexically" in text and "placeholders" in text
    assert "tokens" in text  # Explicit prohibition, never an actual capability.
    assert bundle["receipt_example"]["task_id"] == TASK


@pytest.mark.parametrize("details", [{}, {"steps": ["Call"], "expected": "1"},
    {"steps": ["Call"], "actual": "Not executed"}, {"expected": "1", "actual": "Not executed"}])
def test_case_details_semantics_are_visible_and_enforced_by_schema_and_typed_validator(details):
    payload = {"assets": [{"kind": "CASE", "key": "case-one", "title": "One",
        "markdown": "Markdown alone does not supply typed CASE details", "details": details}]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(agent_handoff("SUBMIT_ASSETS", payload), handoff_schema(task_id=TASK, attempt_id=ATTEMPT))
    with pytest.raises(ValidationError):
        typed_operation("SUBMIT_ASSETS", payload)


def test_complete_case_and_progress_batch_example_matches_both_contracts_without_claiming_execution():
    bundle = handoff_contract(task_id=TASK, attempt_id=ATTEMPT)
    payload = bundle["asset_batch_example"]
    jsonschema.validate(agent_handoff("SUBMIT_ASSETS", payload), bundle["schema"])
    typed = typed_operation("SUBMIT_ASSETS", payload)
    assert typed.checkpoint_report_key == typed.assets[1].key
    assert typed.assets[0].reported_result == "NOT_RUN"
    assert typed.assets[0].details["actual"] == "Not executed"
    # The actual validator checks key presence, not stronger invented value types.
    payload["assets"][0]["details"] = {"steps": None, "expected": 1, "actual": {}}
    jsonschema.validate(agent_handoff("SUBMIT_ASSETS", payload), bundle["schema"])
    typed_operation("SUBMIT_ASSETS", payload)


@pytest.mark.parametrize("kind", ["ANALYSIS", "DESIGN", "IMPLEMENTATION", "REPORT"])
def test_non_case_details_alone_never_satisfy_original_content(kind):
    payload = {"assets": [{"kind": kind, "key": "original", "title": "Original", "details": {"note": "No original"}}]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(agent_handoff("SUBMIT_ASSETS", payload), handoff_schema(task_id=TASK, attempt_id=ATTEMPT))
    with pytest.raises(ValidationError):
        typed_operation("SUBMIT_ASSETS", payload)


@pytest.mark.parametrize("change", ["duplicate_kind_key", "checkpoint_not_report"])
def test_non_json_schema_cross_field_rules_are_explicit_and_typed_validation_stays_strict(change):
    payload = deepcopy(handoff_contract(task_id=TASK, attempt_id=ATTEMPT)["asset_batch_example"])
    if change == "duplicate_kind_key":
        payload["assets"].append({**payload["assets"][0], "title": "Same kind/key, different original"})
    else:
        payload["checkpoint_report_key"] = payload["assets"][0]["key"]
    # Standard JSON Schema cannot compare a projected composite key or $data.
    jsonschema.validate(agent_handoff("SUBMIT_ASSETS", payload), handoff_schema(task_id=TASK, attempt_id=ATTEMPT))
    with pytest.raises(ValidationError):
        typed_operation("SUBMIT_ASSETS", payload)
    rules = handoff_semantics()["typed_validators"]
    assert any(row["source_validator"] == "CloudSubmitAssets.unique_assets"
        and "(kind,key)" in row["rule"] and "same assets batch" in row["rule"] for row in rules)


@pytest.mark.parametrize("missing", ["finished_at", "exit_code"])
def test_run_missing_observation_requires_reason_in_schema_and_typed_contract(missing):
    payload = deepcopy(samples()["SUBMIT_RUN"])
    payload["execution"].pop(missing)
    schema = handoff_schema(task_id=TASK, attempt_id=ATTEMPT)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(agent_handoff("SUBMIT_RUN", payload), schema)
    with pytest.raises(ValidationError):
        typed_operation("SUBMIT_RUN", payload)
    payload["execution"]["unobserved_reason"] = "Actual end observation unavailable in this contract fixture"
    jsonschema.validate(agent_handoff("SUBMIT_RUN", payload), schema)
    typed_operation("SUBMIT_RUN", payload)


def test_ci_identity_is_structural_and_timestamp_order_is_explicit_semantics():
    payload = deepcopy(samples()["SUBMIT_RUN"])
    payload["execution"].update(source="CI", ci_identity={})
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(agent_handoff("SUBMIT_RUN", payload), handoff_schema(task_id=TASK, attempt_id=ATTEMPT))
    with pytest.raises(ValidationError):
        typed_operation("SUBMIT_RUN", payload)
    payload["execution"].update(source="PROJECT_FRAMEWORK", finished_at="2026-10-22T09:59:59Z")
    with pytest.raises(ValidationError):
        typed_operation("SUBMIT_RUN", payload)
    assert any("finished_at must be >= started_at" in row["rule"]
        for row in handoff_semantics()["typed_validators"])


def test_handoff_semantics_cover_every_current_exposed_typed_model_validator():
    models = [Asset, RunExecution, CloudSubmitAssets, CloudArtifactUpload, CloudRunSubmit,
        CloudQuestionSubmit, CloudFinish, CloudDelegationSubmit]
    actual = {validator.func.__qualname__ for model in models
        for validator in model.__pydantic_decorators__.model_validators.values()}
    declared = {row["source_validator"] for row in handoff_semantics()["typed_validators"]}
    assert actual == declared  # A new invisible validator must update the model-readable contract.


def test_local_rejection_feedback_is_distinct_from_receipts_and_never_replaces_unknown():
    bundle = handoff_contract(task_id=TASK, attempt_id=ATTEMPT)
    text = json.dumps(bundle)
    assert bundle["local_rejection_directory"] == ".hypertest-cloud/rejections"
    for phrase in ("SHA256(KEY)", "key_sha256", "handoff_sha256", "LOCAL_REJECTED",
                   "platform_operation_submitted=false", "NEW key", "SENT/UNKNOWN", "not platform ACK"):
        assert phrase in text


def test_asset_reference_descriptions_distinguish_original_artifacts_from_revisions():
    schema = handoff_schema(task_id=TASK, attempt_id=ATTEMPT)
    fields = schema["$defs"]["Asset"]["properties"]
    original = fields["artifact_id"]["description"]
    references = fields["referenced_asset_ids"]["description"]
    assert "CloudArtifact UUID" in original and "UPLOAD_ARTIFACT receipt.artifact_id" in original
    assert "only here, never in referenced_asset_ids" in original
    for phrase in ("AssetRevision", "[]", "earlier ACCEPTED", "SUBMIT_ASSETS receipt.assets[].id",
                   "Never use an UPLOAD_ARTIFACT UUID", "same batch", "Database"):
        assert phrase in references
    assert "not a CloudArtifact UUID" in fields["referenced_asset_ids"]["items"]["description"]
    # Descriptions clarify identity; UUID format and the existing nullable upload
    # field stay structural. Only the DB can establish ownership and row kind.
    assert fields["artifact_id"]["anyOf"] == Asset.model_json_schema()["properties"]["artifact_id"]["anyOf"]
    assert fields["referenced_asset_ids"]["items"]["format"] == "uuid"
    assert "never an upload Artifact UUID" in schema["$defs"]["RunCase"]["properties"]["case_revision_id"]["description"]


def test_upload_analysis_design_examples_use_only_prior_receipts_and_disjoint_identities():
    bundle = handoff_contract(task_id=TASK, attempt_id=ATTEMPT)
    example = bundle["artifact_to_asset_example"]
    sequence = example["sequence"]
    assert [row["handoff"]["operation"] for row in sequence] == ["UPLOAD_ARTIFACT", "SUBMIT_ASSETS", "SUBMIT_ASSETS"]
    original = example["example_file"]["utf8"].encode("utf-8")
    upload = sequence[0]["handoff"]["payload"]
    assert upload["path"] == example["example_file"]["path"]
    assert upload["byte_count"] == len(original) and upload["sha256"] == hashlib.sha256(original).hexdigest()
    accepted_artifacts, accepted_assets = set(), set()
    for row in sequence:
        handoff = row["handoff"]
        jsonschema.validate(handoff, bundle["schema"])
        payload = deepcopy(handoff["payload"])
        if handoff["operation"] == "UPLOAD_ARTIFACT":
            payload.pop("path")
            payload["content_base64"] = base64.b64encode(original).decode()
        else:
            for asset in payload["assets"]:
                if asset.get("artifact_id"):
                    assert asset["artifact_id"] in accepted_artifacts
                    assert asset["artifact_id"] not in accepted_assets
                # The receipt ledger advances after validating each handoff;
                # guessed/same-batch IDs or artifact IDs fail this example check.
                assert set(asset["referenced_asset_ids"]) <= accepted_assets
                assert not set(asset["referenced_asset_ids"]) & accepted_artifacts
        typed_operation(handoff["operation"], payload)
        receipt = row.get("wait_for_accepted_receipt")
        if receipt:
            assert receipt["status"] == "ACCEPTED" and receipt["operation"] == handoff["operation"]
            if receipt["operation"] == "UPLOAD_ARTIFACT":
                assert "assets" not in receipt
                accepted_artifacts.add(receipt["artifact_id"])
            else:
                accepted_assets.update(item["id"] for item in receipt["assets"])
            assert accepted_artifacts.isdisjoint(accepted_assets)
    analysis = sequence[1]["handoff"]["payload"]["assets"][0]
    design = sequence[2]["handoff"]["payload"]["assets"][0]
    assert analysis["referenced_asset_ids"] == []
    assert analysis["artifact_id"] == sequence[0]["wait_for_accepted_receipt"]["artifact_id"]
    assert design["artifact_id"] == analysis["artifact_id"]
    assert design["referenced_asset_ids"] == [sequence[1]["wait_for_accepted_receipt"]["assets"][0]["id"]]


def test_direct_child_original_is_explicit_task_semantics_not_a_global_design_validator():
    bundle = handoff_contract(task_id=TASK, attempt_id=ATTEMPT)
    payload = {"assets": [{"kind": "DESIGN", "key": "markdown-design", "title": "Standalone design",
        "markdown": "Generic design with its own original text", "referenced_asset_ids": []}]}
    jsonschema.validate(agent_handoff("SUBMIT_ASSETS", payload), bundle["schema"])
    assert typed_operation("SUBMIT_ASSETS", payload).assets[0].artifact_id is None
    assert any("on BOTH assets" in rule and "transitive" in rule for rule in bundle["instructions"])
    assert {ARTIFACT}.isdisjoint({ASSET, REPORT})


def test_uuid_shape_never_substitutes_database_reference_validation_or_rejection_recovery():
    schema = handoff_schema(task_id=TASK, attempt_id=ATTEMPT)
    ambiguous = {"assets": [{"kind": "ANALYSIS", "key": "bad-identity-example", "title": "Shape only",
        "artifact_id": ARTIFACT, "referenced_asset_ids": [ARTIFACT]}]}
    # These are both syntactically UUIDs. The database must reject the wrong
    # identity; this change does not add a local validator or retry permission.
    jsonschema.validate(agent_handoff("SUBMIT_ASSETS", ambiguous), schema)
    typed_operation("SUBMIT_ASSETS", ambiguous)
    rules = " ".join(handoff_semantics()["reference_and_state_rules"])
    for phrase in ("Artifact UUID is not an AssetRevision UUID", "not an asset revision", "only in asset.artifact_id",
                   "earlier ACCEPTED SUBMIT_ASSETS receipt.assets[].id", "Never guess or predeclare IDs",
                   "same batch", "Database validation remains authoritative", "does not become LOCAL_REJECTED",
                   "replacement POST", "not a CASE or REPORT revision"):
        assert phrase in rules
