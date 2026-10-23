"""Only fake HTTP is used here; the controller never runs a Worker or framework."""
import base64
import hashlib
import importlib.util
import json
import re
import sys
from copy import deepcopy
from pathlib import Path
from urllib.parse import unquote

import httpx
import pytest

SPEC = importlib.util.spec_from_file_location("cloud_acceptance_controller", Path(__file__).parents[1] / "ops/deepseek/cloud_acceptance.py")
controller = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = controller
SPEC.loader.exec_module(controller)
PROJECT = "00000000-0000-4000-8000-000000000031"
TASK = "00000000-0000-4000-8000-000000000032"
ATTEMPT = "00000000-0000-4000-8000-000000000033"
CONFIG = "00000000-0000-4000-8000-000000000034"
NEXT_TASK = "00000000-0000-4000-8000-000000000035"
RESOLUTION = "00000000-0000-4000-8000-000000000036"


def strict_fixture():
    """Synthetic accepted records, never a real execution or provider session."""
    def identity(value):
        return "00000000-0000-4000-8000-" + f"{value:012d}"

    analysis_id, design_id, implementation_id, final_id, case_id = map(identity, range(100, 105))
    child_id, patch_id, report_id, log_id = map(identity, range(200, 204))
    run_id, native_ref, delegation_id, native_run = map(identity, range(300, 304))
    child = "Synthetic child analysis and design original\n"
    test_file = "import unittest\nclass Tests(unittest.TestCase):\n    def test_boundary(self):\n        self.assertEqual(1 + 1, 2)\n"
    path = "tests/test_boundaries.py"
    patch = (f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,4 @@\n"
        + "".join("+" + line for line in test_file.splitlines(keepends=True)))
    log = "test_boundary (test_boundaries.Tests.test_boundary) ... ok\n\nRan 1 test in 0.001s\n\nOK\n"
    execution = {"source": "PROJECT_FRAMEWORK", "entrypoint": controller.ENTRYPOINT, "cwd": "/workspace/framework",
        "framework_sha": "a" * 40, "actual_sut_build": "a" * 40, "test_tree_digest": "b" * 64,
        "started_at": "2026-10-23T01:00:00Z", "finished_at": "2026-10-23T01:00:01Z", "exit_code": 0}
    report = {key: execution[key] for key in ("entrypoint", "cwd", "framework_sha", "test_tree_digest", "started_at", "finished_at", "exit_code")}
    report.update(sut_sha="a" * 40, run_key="one", result="OK", tests_run=1,
        cases=[{"test": "test_boundary", "qualname": "test_boundaries.Tests.test_boundary", "result": "ok"}],
        log_sha256=hashlib.sha256(log.encode()).hexdigest(), log_bytes=len(log.encode()))
    values = [(child_id, "text/markdown", child), (patch_id, "text/x-diff", patch),
        (report_id, "application/json", json.dumps(report)), (log_id, "text/plain", log)]
    artifacts, originals = [], []
    for artifact_id, media_type, content in values:
        checksum = hashlib.sha256(content.encode()).hexdigest()
        artifacts.append({"id": artifact_id, "task_id": TASK, "project_id": PROJECT, "attempt_id": ATTEMPT,
            "media_type": media_type, "sha256": checksum, "byte_count": len(content.encode()), "verified_at": "2026-10-23T01:00:02Z"})
        originals.append({"id": artifact_id, "sha256": checksum, "content_utf8": content})
    assets = []
    for asset_id, kind, version in ((analysis_id, "ANALYSIS", 3), (design_id, "DESIGN", 4),
            (implementation_id, "IMPLEMENTATION", 5), (case_id, "CASE", 6), (final_id, "REPORT", 8)):
        assets.append({"id": asset_id, "task_id": TASK, "attempt_id": ATTEMPT, "kind": kind,
            "task_version": version, "reported_result": "PASS", "details": {},
            "artifact_id": child_id if kind in {"ANALYSIS", "DESIGN"} else None})
    assets[2].update(artifact_id=patch_id, details={"framework_sha": "a" * 40, "test_tree_digest": "b" * 64,
        "cwd": "/workspace/framework", "dirty_files": [], "untracked_files": [controller.CHILD_FILE, path],
        "retained_child_file": {"path": controller.CHILD_FILE, "artifact_id": child_id,
            "sha256": artifacts[0]["sha256"], "bytes": len(child.encode())},
        "new_files": [{"path": path, "artifact_id": patch_id, "sha256": hashlib.sha256(test_file.encode()).hexdigest()}]})
    assets[3]["details"] = {"test_method": "test_boundary", "steps": ["Synthetic fixture"], "expected": "2", "actual": "2"}
    inputs = {"framework_entrypoints": [controller.ENTRYPOINT]}
    document = {"task": {"id": TASK, "project_id": PROJECT, "version": 9, "latest_attempt_id": ATTEMPT,
        "status": "COMPLETED", "reported_result": "PASS", "inputs": inputs,
        "frozen_manifest": {"inputs": deepcopy(inputs), "resolution": {"repositories": {
            role: {"url": controller.REPOSITORY, "commit_sha": "a" * 40} for role in ("sut", "framework")}}}},
        "attempts": [{"id": ATTEMPT, "task_id": TASK, "status": "COMPLETED", "reported_result": "PASS", "checkpoint": {
            "final_report_revision": final_id, "completion_manifest": {"required_asset_ids": [row["id"] for row in assets],
                "pending_operation_keys": [], "all_local_processes_stopped": True, "external_operations_reconciled": True}}}],
        "assets": assets, "artifacts": artifacts,
        "asset_references": [{"task_id": TASK, "asset_id": design_id, "referenced_asset_id": analysis_id}],
        "delegations": [{"id": delegation_id, "task_id": TASK, "attempt_id": ATTEMPT, "task_version": 7,
            "provider": "codex", "native_ref": native_ref, "status": "COMPLETED", "terminal_observation": {
                "source": "official-plugin-runtime-reported", "source_commit": controller.HARNESS_COMMIT,
                "run_id": native_run, "stop_reason": "completed", "independent_execution_proof": False}}],
        "delegation_assets": [{"task_id": TASK, "delegation_id": delegation_id, "asset_id": value} for value in (analysis_id, design_id)],
        "runs": [{"id": run_id, "task_id": TASK, "attempt_id": ATTEMPT, "reported_result": "PASS", "run_key": "one", "execution": execution}],
        "run_cases": [{"task_id": TASK, "run_id": run_id, "case_revision_id": case_id, "reported_result": "PASS", "actual": "Executed; observed 2"}],
        "run_artifacts": [{"task_id": TASK, "run_id": run_id, "artifact_id": value, "role": role}
            for value, role in ((report_id, "REPORT"), (log_id, "LOG"))]}
    expected = controller.NativeAcceptanceExpectation(profile=controller.STRICT_PROFILE, project_id=PROJECT, task_id=TASK,
        attempt_id=ATTEMPT, accepted_version=9, native_ref=native_ref, child_artifact_id=child_id,
        child_sha256=artifacts[0]["sha256"], analysis_asset_id=analysis_id, design_asset_id=design_id,
        implementation_asset_id=implementation_id, run_id=run_id)
    return document, originals, expected


def test_strict_native_readback_accepts_exact_direct_original_and_full_record_chain_without_execution():
    document, originals, expected = strict_fixture()
    before = deepcopy((document, originals))
    result = controller.strict_native_acceptance(document, originals, expected)
    assert result["strict_result"] == "PASS" and result["failures"] == []
    assert result["case_count"] == 1 and len(result["new_file_sha256"]) == 1
    assert result["child_writer_provenance"] == "RUNTIME_REPORTED"
    assert result["canonical_state_modified"] is result["tests_executed_by_checker"] is result["sdk_idle_used"] is False
    assert result["legacy_gate_upgraded"] is result["independent_execution_proof"] is False
    assert (document, originals) == before


def test_r5_design_transitive_only_shape_is_non_pass_without_rewriting_reported_pass():
    document, originals, expected = strict_fixture()
    document["assets"][1]["artifact_id"] = None
    before = deepcopy(document)
    result = controller.strict_native_acceptance(document, originals, expected)
    assert result["strict_result"] == "NON_PASS"
    assert result["failures"] == ["DESIGN_DIRECT_ARTIFACT_MISMATCH"]
    assert document == before and document["task"]["reported_result"] == "PASS"


@pytest.mark.parametrize("corruption,code", [
    ("analysis_wrong_artifact", "ANALYSIS_DIRECT_ARTIFACT_MISMATCH"),
    ("cross_task_asset", "SELECTED_ASSET_IDENTITY_MISMATCH"),
    ("cross_attempt_artifact", "ORIGINAL_BYTES_INTEGRITY_MISMATCH"),
    ("changed_child_bytes", "ORIGINAL_BYTES_INTEGRITY_MISMATCH"),
    ("missing_child_bytes", "ORIGINAL_BYTES_MISSING"),
    ("wrong_native_ref", "NATIVE_DELEGATION_IDENTITY_MISMATCH"),
    ("missing_design_delegation_ref", "NATIVE_DELEGATION_ASSET_LINK_MISSING"),
    ("contradictory_case", "RUN_CASE_ACTUALS_MISMATCH"),
    ("wrong_run_sha", "ACTUAL_RUN_EXECUTION_MISMATCH"),
    ("missing_run", "ACTUAL_RUN_MISSING"),
    ("missing_patch", "ORIGINAL_BYTES_MISSING"),
    ("wrong_new_file_hash", "IMPLEMENTATION_NEW_FILE_BYTES_MISMATCH"),
    ("pending_operation", "COMPLETION_REFERENCES_INCOMPLETE"),
    ("duplicate_asset", "DUPLICATE_ACCEPTED_ID"),
])
def test_strict_native_acceptance_fails_closed_for_reference_byte_run_and_case_gaps(corruption, code):
    document, originals, expected = strict_fixture()
    if corruption == "analysis_wrong_artifact":
        document["assets"][0]["artifact_id"] = document["artifacts"][1]["id"]
    elif corruption == "cross_task_asset":
        document["assets"][1]["task_id"] = NEXT_TASK
    elif corruption == "cross_attempt_artifact":
        document["artifacts"][0]["attempt_id"] = NEXT_TASK
    elif corruption == "changed_child_bytes":
        originals[0]["content_utf8"] += "Changed bytes"
    elif corruption == "missing_child_bytes":
        originals.pop(0)
    elif corruption == "wrong_native_ref":
        document["delegations"][0]["native_ref"] = NEXT_TASK
    elif corruption == "missing_design_delegation_ref":
        document["delegation_assets"].pop()
    elif corruption == "contradictory_case":
        document["run_cases"][0]["reported_result"] = "FAIL"
    elif corruption == "wrong_run_sha":
        document["runs"][0]["execution"]["framework_sha"] = "f" * 40
    elif corruption == "missing_run":
        document["runs"] = []
    elif corruption == "missing_patch":
        originals.pop(1)
    elif corruption == "wrong_new_file_hash":
        document["assets"][2]["details"]["new_files"][0]["sha256"] = "f" * 64
    elif corruption == "pending_operation":
        document["attempts"][0]["checkpoint"]["completion_manifest"]["pending_operation_keys"] = ["original"]
    elif corruption == "duplicate_asset":
        document["assets"].append(deepcopy(document["assets"][0]))
    result = controller.strict_native_acceptance(document, originals, expected)
    assert result["strict_result"] == "NON_PASS" and code in result["failures"]
    assert document["task"]["reported_result"] == "PASS"


def test_strict_controller_only_gets_fixed_accepted_version_and_original_bytes_without_writes(tmp_path, monkeypatch):
    document, originals, expected = strict_fixture()
    expectation = tmp_path / "expectation.json"
    expectation.write_text(expected.model_dump_json())
    expectation.chmod(0o600)
    calls = []

    def transport(request):
        calls.append(request)
        assert request.method == "GET"
        if "/artifacts/" in request.url.path:
            artifact_id = request.url.path.rsplit("/", 1)[1]
            artifact = next(row for row in document["artifacts"] if row["id"] == artifact_id)
            original = next(row for row in originals if row["id"] == artifact_id)["content_utf8"].encode()
            return httpx.Response(200, json={**artifact, "offset": 0, "next_offset": len(original), "complete": True,
                "content_base64": base64.b64encode(original).decode()})
        assert request.url.params["version"] == "9"
        return httpx.Response(200, json=page(document))

    def forbidden(*args, **kwargs):
        raise AssertionError("Strict acceptance must not persist or submit anything")

    monkeypatch.setattr(controller, "save", forbidden)
    state = {"project_id": PROJECT, "task_id": TASK, "writes": {"create": {"state": "READBACK_COMPLETE"}}}
    with httpx.Client(base_url="https://isolated.invalid", transport=httpx.MockTransport(transport)) as client:
        run = controller.Controller(client, tmp_path / "state.json", state)
        monkeypatch.setattr(run, "mutate", forbidden)
        monkeypatch.setattr(run, "reconcile", forbidden)
        result = run.strict_readback(expectation)
    assert result["strict_result"] == "PASS" and len(calls) == 5
    assert result["expectation_sha256"] == hashlib.sha256(expectation.read_bytes()).hexdigest()
    assert re.fullmatch(r"[a-f0-9]{64}", result["readback_sha256"])


def test_strict_controller_pending_unknown_is_blocked_before_any_api_get(tmp_path):
    _, _, expected = strict_fixture()
    expectation = tmp_path / "expectation.json"
    expectation.write_text(expected.model_dump_json())
    expectation.chmod(0o600)
    state = {"project_id": PROJECT, "task_id": TASK, "writes": {"one": {"state": "UNKNOWN"}}}
    run = controller.Controller(None, tmp_path / "state.json", state)
    with pytest.raises(controller.Blocked, match="ORIGINAL_PENDING_KEYS_GET_ONLY"):
        run.strict_readback(expectation)


def replace_new_file_original(document, originals, content):
    implementation = document["assets"][2]
    item = implementation["details"]["new_files"][0]
    path = item["path"]
    lines = content.splitlines(keepends=True)
    patch = (f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n"
        + "".join("+" + line for line in lines))
    checksum = hashlib.sha256(patch.encode()).hexdigest()
    artifact = next(row for row in document["artifacts"] if row["id"] == item["artifact_id"])
    original = next(row for row in originals if row["id"] == item["artifact_id"])
    artifact.update(sha256=checksum, byte_count=len(patch.encode()))
    original.update(sha256=checksum, content_utf8=patch)
    item["sha256"] = hashlib.sha256(content.encode()).hexdigest()


@pytest.mark.parametrize("content,code", [
    ("import unittest\ndef test_boundary():\n    assert 1 + 1 == 2\n", "CASE_IMPLEMENTATION_METHODS_MISMATCH"),
    ("import unittest\nclass Tests(object):\n    def test_boundary(self):\n        assert 1 + 1 == 2\n", "CASE_IMPLEMENTATION_METHODS_MISMATCH"),
    ("import unittest\nclass OtherTests(unittest.TestCase):\n    def test_boundary(self):\n        self.assertEqual(1 + 1, 2)\n", "CASE_IMPLEMENTATION_METHODS_MISMATCH"),
    ("import unittest\nclass Tests(unittest.TestCase):\n    def test_boundary(self):\n        self.assertEqual(1 + 1, 2)\nclass Second(unittest.TestCase):\n    def test_boundary(self):\n        self.assertEqual(1 + 1, 2)\n", "IMPLEMENTATION_TEST_METHOD_AMBIGUOUS"),
])
def test_strict_case_mapping_never_accepts_undiscovered_or_other_qualname_code(content, code):
    document, originals, expected = strict_fixture()
    replace_new_file_original(document, originals, content)
    result = controller.strict_native_acceptance(document, originals, expected)
    assert result["strict_result"] == "NON_PASS" and code in result["failures"]


@pytest.mark.parametrize("uncovered", ["tests/omitted.py", "tests/", "artifacts/unreturned.txt"])
def test_strict_inventory_requires_originals_for_every_declared_untracked_file(uncovered):
    document, originals, expected = strict_fixture()
    document["assets"][2]["details"]["untracked_files"].append(uncovered)
    result = controller.strict_native_acceptance(document, originals, expected)
    assert result["strict_result"] == "NON_PASS"
    assert "IMPLEMENTATION_INVENTORY_INCOMPLETE" in result["failures"]


def replace_accepted_artifact(document, originals, artifact_id, content):
    """Keep synthetic persisted hash/count valid while changing one original."""
    checksum = hashlib.sha256(content.encode()).hexdigest()
    artifact = next(row for row in document["artifacts"] if row["id"] == artifact_id)
    original = next(row for row in originals if row["id"] == artifact_id)
    artifact.update(sha256=checksum, byte_count=len(content.encode()))
    original.update(sha256=checksum, content_utf8=content)


def report_original(document, originals):
    artifact_id = next(row["artifact_id"] for row in document["run_artifacts"] if row["role"] == "REPORT")
    return artifact_id, json.loads(next(row["content_utf8"] for row in originals if row["id"] == artifact_id))


def dual_original_fixture():
    document, originals, expected = strict_fixture()
    source = "import unittest\nclass Tests(unittest.TestCase):\n    def test_boundary(self):\n        self.assertEqual(1 + 1, 2)\n"
    item = document["assets"][2]["details"]["new_files"][0]
    patch_id = item["artifact_id"]
    patch = next(row for row in document["artifacts"] if row["id"] == patch_id)
    raw_id = "00000000-0000-4000-8000-000000000205"
    raw_sha = hashlib.sha256(source.encode()).hexdigest()
    document["artifacts"].append({**patch, "id": raw_id, "media_type": "text/plain", "sha256": raw_sha, "byte_count": len(source.encode())})
    originals.append({"id": raw_id, "sha256": raw_sha, "content_utf8": source})
    item.update(artifact_id=raw_id, unified_diff_artifact_id=patch_id, bytes=len(source.encode()),
        unified_diff_sha256=patch["sha256"], unified_diff_bytes=patch["byte_count"])
    return document, originals, expected


@pytest.mark.parametrize("overall,case_result", [("OK", "ok"), ("PASS", "PASS"), ("OK", "PASS"), ("PASS", "ok")])
def test_explicit_raw_plus_diff_and_exact_repository_build_accept_only_equivalent_success(overall, case_result):
    document, originals, expected = dual_original_fixture()
    document["runs"][0]["execution"]["actual_sut_build"] = controller.REPOSITORY + "@" + "a" * 40
    report_id, report = report_original(document, originals)
    report["result"] = overall
    report["cases"][0]["result"] = case_result
    replace_accepted_artifact(document, originals, report_id, json.dumps(report))
    result = controller.strict_native_acceptance(document, originals, expected)
    assert result["strict_result"] == "PASS" and result["failures"] == []
    assert document["runs"][0]["execution"]["actual_sut_build"].startswith(controller.REPOSITORY)


@pytest.mark.parametrize("build", [
    "https://wrong.invalid/pypa/sampleproject.git@" + "a" * 40,
    controller.REPOSITORY + "@" + "f" * 40,
    controller.REPOSITORY + "@" + "a" * 40 + "-extra",
    controller.REPOSITORY + "@" + "a" * 12,
    "UNKNOWN",
])
def test_strict_build_identity_does_not_match_substrings_suffixes_wrong_repository_or_partial_sha(build):
    document, originals, expected = strict_fixture()
    document["runs"][0]["execution"]["actual_sut_build"] = build
    result = controller.strict_native_acceptance(document, originals, expected)
    assert result["strict_result"] == "NON_PASS" and "ACTUAL_RUN_EXECUTION_MISMATCH" in result["failures"]


def test_report_sut_sha_remains_the_bare_frozen_commit_even_when_run_uses_repository_identity():
    document, originals, expected = strict_fixture()
    report_id, report = report_original(document, originals)
    report["sut_sha"] = controller.REPOSITORY + "@" + "a" * 40
    replace_accepted_artifact(document, originals, report_id, json.dumps(report))
    result = controller.strict_native_acceptance(document, originals, expected)
    assert result["strict_result"] == "NON_PASS" and "RUN_REPORT_EXECUTION_MISMATCH" in result["failures"]


@pytest.mark.parametrize("corruption,code", [
    ("raw_diff_disagree", "IMPLEMENTATION_RAW_DIFF_BYTES_MISMATCH"),
    ("wrong_raw_pair", "IMPLEMENTATION_RAW_DIFF_BYTES_MISMATCH"),
    ("wrong_patch_pair", "IMPLEMENTATION_PATCH_MISSING"),
    ("wrong_patch_sha", "IMPLEMENTATION_PATCH_BYTES_MISMATCH"),
    ("wrong_patch_count", "IMPLEMENTATION_PATCH_BYTES_MISMATCH"),
    ("wrong_raw_count", "IMPLEMENTATION_NEW_FILE_BYTES_MISMATCH"),
    ("wrong_impl_diff_ref", "IMPLEMENTATION_PATCH_MISSING"),
    ("cross_attempt_patch", "ORIGINAL_BYTES_INTEGRITY_MISMATCH"),
])
def test_dual_originals_require_exact_pairing_bytes_counts_hashes_and_current_attempt(corruption, code):
    document, originals, expected = dual_original_fixture()
    implementation = document["assets"][2]
    item = implementation["details"]["new_files"][0]
    if corruption == "raw_diff_disagree":
        replace_accepted_artifact(document, originals, item["artifact_id"], "# Different but internally hash-valid original\n")
    elif corruption == "wrong_raw_pair":
        item["artifact_id"] = str(expected.child_artifact_id)
    elif corruption == "wrong_patch_pair":
        item["unified_diff_artifact_id"] = item["artifact_id"]
    elif corruption == "wrong_patch_sha":
        item["unified_diff_sha256"] = "f" * 64
    elif corruption == "wrong_patch_count":
        item["unified_diff_bytes"] += 1
    elif corruption == "wrong_raw_count":
        item["bytes"] += 1
    elif corruption == "wrong_impl_diff_ref":
        implementation["artifact_id"] = item["artifact_id"]
    elif corruption == "cross_attempt_patch":
        next(row for row in document["artifacts"] if row["id"] == item["unified_diff_artifact_id"])["attempt_id"] = NEXT_TASK
    result = controller.strict_native_acceptance(document, originals, expected)
    assert result["strict_result"] == "NON_PASS" and code in result["failures"]


@pytest.mark.parametrize("failure", ["FAIL", "ERROR", "BLOCKED", "UNKNOWN", "SKIPPED", "pass"])
@pytest.mark.parametrize("field", ["overall", "case"])
def test_report_success_aliases_never_erase_failure_unknown_or_unrecognized_results(failure, field):
    document, originals, expected = dual_original_fixture()
    report_id, report = report_original(document, originals)
    if field == "overall":
        report["result"] = failure
    else:
        report["cases"][0]["result"] = failure
    replace_accepted_artifact(document, originals, report_id, json.dumps(report))
    result = controller.strict_native_acceptance(document, originals, expected)
    assert result["strict_result"] == "NON_PASS"
    code = "RUN_REPORT_EXECUTION_MISMATCH" if field == "overall" else "RUN_REPORT_CASE_RESULTS_MISMATCH"
    assert code in result["failures"]


def new_file_patch(path, source):
    lines = source.splitlines(keepends=True)
    return (f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n"
        + f"@@ -0,0 +1,{len(lines)} @@\n" + "".join("+" + line for line in lines))


def combined_child_fixture():
    document, originals, expected = strict_fixture()
    patch_id = document["assets"][2]["details"]["new_files"][0]["artifact_id"]
    patch = next(row["content_utf8"] for row in originals if row["id"] == patch_id)
    child = next(row["content_utf8"] for row in originals if row["id"] == str(expected.child_artifact_id))
    replace_accepted_artifact(document, originals, patch_id, patch + new_file_patch(controller.CHILD_FILE, child))
    return document, originals, expected


def test_complete_combined_new_test_and_exact_retained_child_patch_is_not_a_missing_original():
    document, originals, expected = combined_child_fixture()
    before = deepcopy((document, originals, expected.model_dump()))
    result = controller.strict_native_acceptance(document, originals, expected)
    assert result["strict_result"] == "PASS" and result["failures"] == []
    assert set(result["new_file_sha256"]) == {"tests/test_boundaries.py"}
    assert result["child_sha256"] == expected.child_sha256
    assert before == (document, originals, expected.model_dump())


@pytest.mark.parametrize("corruption,code", [
    ("changed_child_bytes", "IMPLEMENTATION_CHILD_PATCH_BYTES_MISMATCH"),
    ("duplicate_child", "READBACK_STRUCTURE_OR_SUPPORTED_ORIGINAL_FORMAT_INVALID"),
    ("undeclared_test", "IMPLEMENTATION_PATCH_INVENTORY_MISMATCH"),
    ("third_non_test_path", "READBACK_STRUCTURE_OR_SUPPORTED_ORIGINAL_FORMAT_INVALID"),
    ("traversal", "READBACK_STRUCTURE_OR_SUPPORTED_ORIGINAL_FORMAT_INVALID"),
    ("modified_child", "READBACK_STRUCTURE_OR_SUPPORTED_ORIGINAL_FORMAT_INVALID"),
])
def test_combined_patch_requires_exact_child_bytes_and_rejects_other_or_repeated_paths(corruption, code):
    document, originals, expected = combined_child_fixture()
    patch_id = document["assets"][2]["details"]["new_files"][0]["artifact_id"]
    patch = next(row["content_utf8"] for row in originals if row["id"] == patch_id)
    child = next(row["content_utf8"] for row in originals if row["id"] == str(expected.child_artifact_id))
    if corruption == "changed_child_bytes":
        patch = patch.replace("+" + child, "+A different internally hash-valid child original\n")
    elif corruption == "duplicate_child":
        patch += new_file_patch(controller.CHILD_FILE, child)
    elif corruption == "undeclared_test":
        patch += new_file_patch("tests/test_omitted.py", "# Complete but undeclared test original\n")
    elif corruption == "third_non_test_path":
        patch += new_file_patch("artifacts/other.md", "Undeclared third path\n")
    elif corruption == "traversal":
        patch += new_file_patch("tests/../test_escape.py", "# Escapes approved new test path\n")
    else:
        patch = patch.replace("--- /dev/null\n+++ b/" + controller.CHILD_FILE,
            "--- a/" + controller.CHILD_FILE + "\n+++ b/" + controller.CHILD_FILE)
    replace_accepted_artifact(document, originals, patch_id, patch)
    result = controller.strict_native_acceptance(document, originals, expected)
    assert result["strict_result"] == "NON_PASS" and code in result["failures"]


def described_build_fixture():
    document, originals, expected = strict_fixture()
    execution = document["runs"][0]["execution"]
    execution["actual_sut_build"] = "pypa/sampleproject " + "a" * 40 + " via PYTHONPATH=/workspace/sut/src"
    execution["environment_observation"] = {"sut_sha": "a" * 40, "pythonpath": "/workspace/sut/src"}
    return document, originals, expected


def test_exact_descriptive_build_binds_full_sha_import_path_and_report_without_rewriting_raw_value():
    document, originals, expected = described_build_fixture()
    before = deepcopy(document)
    result = controller.strict_native_acceptance(document, originals, expected)
    assert result["strict_result"] == "PASS" and result["failures"] == []
    assert document == before


@pytest.mark.parametrize("corruption,code", [
    ("wrong_slug", "ACTUAL_RUN_EXECUTION_MISMATCH"),
    ("wrong_sha", "ACTUAL_RUN_EXECUTION_MISMATCH"),
    ("short_sha", "ACTUAL_RUN_EXECUTION_MISMATCH"),
    ("extra_suffix", "ACTUAL_RUN_EXECUTION_MISMATCH"),
    ("wrong_import_path", "ACTUAL_RUN_EXECUTION_MISMATCH"),
    ("missing_observed_sha", "ACTUAL_RUN_EXECUTION_MISMATCH"),
    ("wrong_observed_sha", "ACTUAL_RUN_EXECUTION_MISMATCH"),
    ("wrong_repository", "PUBLIC_FIXED_REPOSITORIES_REQUIRED"),
    ("wrong_report_sha", "RUN_REPORT_EXECUTION_MISMATCH"),
])
def test_descriptive_build_is_a_closed_format_not_a_substring_sha_fallback(corruption, code):
    document, originals, expected = described_build_fixture()
    execution = document["runs"][0]["execution"]
    if corruption == "wrong_slug":
        execution["actual_sut_build"] = execution["actual_sut_build"].replace("pypa/sampleproject", "other/sampleproject")
    elif corruption == "wrong_sha":
        execution["actual_sut_build"] = execution["actual_sut_build"].replace("a" * 40, "f" * 40)
    elif corruption == "short_sha":
        execution["actual_sut_build"] = execution["actual_sut_build"].replace("a" * 40, "a" * 12)
    elif corruption == "extra_suffix":
        execution["actual_sut_build"] += " plus another target"
    elif corruption == "wrong_import_path":
        execution["environment_observation"]["pythonpath"] = "/workspace/framework/src"
    elif corruption == "missing_observed_sha":
        del execution["environment_observation"]["sut_sha"]
    elif corruption == "wrong_observed_sha":
        execution["environment_observation"]["sut_sha"] = "f" * 40
    elif corruption == "wrong_repository":
        document["task"]["frozen_manifest"]["resolution"]["repositories"]["sut"]["url"] = "https://wrong.invalid/project.git"
    else:
        report_id, report = report_original(document, originals)
        report["sut_sha"] = "f" * 40
        replace_accepted_artifact(document, originals, report_id, json.dumps(report))
    result = controller.strict_native_acceptance(document, originals, expected)
    assert result["strict_result"] == "NON_PASS" and code in result["failures"]


def operator_baseline_fixture():
    """External operator bytes plus synthetic baseline CASE/log, not Agent authority."""
    document, originals, expected = strict_fixture()
    baseline = "import unittest\nclass TestSimple(unittest.TestCase):\n    def test_add_one(self):\n        self.assertEqual(5 + 1, 6)\n"
    baseline_input = [{"repository_url": controller.REPOSITORY, "framework_sha": "a" * 40,
        "path": "tests/test_simple.py", "expected_sha256": hashlib.sha256(baseline.encode()).hexdigest(),
        "byte_count": len(baseline.encode()), "content_utf8": baseline, "source": "OPERATOR_VERIFIED_FROZEN_FRAMEWORK"}]
    case = deepcopy(document["assets"][3])
    case.update(id="00000000-0000-4000-8000-000000000105", details={"test_method": "test_add_one",
        "test_id": "test_simple.TestSimple.test_add_one", "module": "test_simple.TestSimple",
        "steps": ["Existing frozen baseline"], "expected": "6", "actual": "6"})
    document["assets"].append(case)
    document["attempts"][0]["checkpoint"]["completion_manifest"]["required_asset_ids"].append(case["id"])
    document["run_cases"].append({**document["run_cases"][0], "case_revision_id": case["id"], "actual": "Observed baseline 6"})
    report_id, report = report_original(document, originals)
    report["tests_run"] = 2
    report["cases"].append({"test": "test_add_one", "qualname": "test_simple.TestSimple.test_add_one", "result": "PASS"})
    log = ("test_boundary (test_boundaries.Tests.test_boundary) ... ok\n"
        "test_add_one (test_simple.TestSimple.test_add_one) ... ok\n\nRan 2 tests in 0.001s\n\nOK\n")
    log_id = next(row["artifact_id"] for row in document["run_artifacts"] if row["role"] == "LOG")
    replace_accepted_artifact(document, originals, log_id, log)
    report.update(log_sha256=hashlib.sha256(log.encode()).hexdigest(), log_bytes=len(log.encode()))
    replace_accepted_artifact(document, originals, report_id, json.dumps(report))
    return document, originals, expected, baseline_input


def test_operator_frozen_baseline_adds_only_the_exact_existing_case_without_changing_task_or_expectation():
    document, originals, expected, baseline_input = operator_baseline_fixture()
    before = deepcopy((document, originals, expected.model_dump(), baseline_input))
    result = controller.strict_native_acceptance(document, originals, expected, baseline_files=baseline_input)
    assert result["strict_result"] == "PASS" and result["failures"] == [] and result["case_count"] == 2
    assert result["operator_baseline_sha256"] == {"tests/test_simple.py": baseline_input[0]["expected_sha256"]}
    assert result["baseline_source"] == "OPERATOR_SUPPLIED_FROZEN_FRAMEWORK_ORIGINAL"
    assert result["independent_execution_proof"] is False
    assert before == (document, originals, expected.model_dump(), baseline_input)


@pytest.mark.parametrize("untrusted_location", ["missing", "asset_details", "report_original"])
def test_baseline_case_requires_separate_operator_bytes_and_never_infers_them_from_agent_material(untrusted_location):
    document, originals, expected, baseline_input = operator_baseline_fixture()
    if untrusted_location == "asset_details":
        document["assets"][2]["details"]["baseline_files"] = baseline_input
    elif untrusted_location == "report_original":
        report_id, report = report_original(document, originals)
        report["baseline_files"] = baseline_input
        replace_accepted_artifact(document, originals, report_id, json.dumps(report))
    result = controller.strict_native_acceptance(document, originals, expected)
    assert result["strict_result"] == "NON_PASS" and "BASELINE_ORIGINAL_REQUIRED" in result["failures"]


@pytest.mark.parametrize("corruption", ["missing_pin", "wrong_hash", "wrong_count", "changed_body_same_qualname",
    "wrong_repo", "wrong_framework", "wrong_path", "agent_source", "not_testcase", "extra_method", "wrong_class"])
def test_operator_baseline_requires_real_pinned_bytes_scope_and_only_the_supported_unittest_method(corruption):
    document, originals, expected, baseline_input = operator_baseline_fixture()
    item = baseline_input[0]
    if corruption == "missing_pin":
        del item["expected_sha256"]
    elif corruption == "wrong_hash":
        item["expected_sha256"] = "f" * 64
    elif corruption == "wrong_count":
        item["byte_count"] += 1
    elif corruption == "changed_body_same_qualname":
        item["content_utf8"] = item["content_utf8"].replace("5 + 1, 6", "5 + 1, 999")
    elif corruption == "wrong_repo":
        item["repository_url"] = "https://wrong.invalid/pypa/sampleproject.git"
    elif corruption == "wrong_framework":
        item["framework_sha"] = "f" * 40
    elif corruption == "wrong_path":
        item["path"] = "tests/test_other.py"
    elif corruption == "agent_source":
        item["source"] = "AGENT_REPORTED"
    else:
        if corruption == "not_testcase":
            item["content_utf8"] = item["content_utf8"].replace("unittest.TestCase", "object")
        elif corruption == "extra_method":
            item["content_utf8"] += "    def test_extra(self):\n        pass\n"
        else:
            item["content_utf8"] = item["content_utf8"].replace("class TestSimple", "class Other")
        item.update(expected_sha256=hashlib.sha256(item["content_utf8"].encode()).hexdigest(),
            byte_count=len(item["content_utf8"].encode()))
    result = controller.strict_native_acceptance(document, originals, expected, baseline_files=baseline_input)
    assert result["strict_result"] == "NON_PASS" and "BASELINE_ORIGINAL_REQUIRED" in result["failures"]


def test_baseline_case_cannot_use_another_module_with_the_same_short_test_name():
    document, originals, expected, baseline_input = operator_baseline_fixture()
    document["assets"][-1]["details"]["module"] = "other.TestSimple"
    result = controller.strict_native_acceptance(document, originals, expected, baseline_files=baseline_input)
    assert result["strict_result"] == "NON_PASS" and "CASE_IMPLEMENTATION_METHODS_MISMATCH" in result["failures"]


def test_baseline_case_must_appear_under_exact_full_identity_in_both_report_and_log():
    document, originals, expected, baseline_input = operator_baseline_fixture()
    report_id, report = report_original(document, originals)
    report["cases"][-1]["qualname"] = "other.TestSimple.test_add_one"
    log_id = next(row["artifact_id"] for row in document["run_artifacts"] if row["role"] == "LOG")
    log = next(row["content_utf8"] for row in originals if row["id"] == log_id).replace(
        "test_simple.TestSimple.test_add_one", "other.TestSimple.test_add_one")
    replace_accepted_artifact(document, originals, log_id, log)
    report.update(log_sha256=hashlib.sha256(log.encode()).hexdigest(), log_bytes=len(log.encode()))
    replace_accepted_artifact(document, originals, report_id, json.dumps(report))
    result = controller.strict_native_acceptance(document, originals, expected, baseline_files=baseline_input)
    assert result["strict_result"] == "NON_PASS" and "CASE_IMPLEMENTATION_METHODS_MISMATCH" in result["failures"]


def test_operator_baseline_never_substitutes_for_missing_new_test_method_case_coverage():
    document, originals, expected, baseline_input = operator_baseline_fixture()
    document["attempts"][0]["checkpoint"]["completion_manifest"]["required_asset_ids"].remove(document["assets"][3]["id"])
    document["run_cases"] = document["run_cases"][1:]
    result = controller.strict_native_acceptance(document, originals, expected, baseline_files=baseline_input)
    assert result["strict_result"] == "NON_PASS" and "CASE_IMPLEMENTATION_METHODS_MISMATCH" in result["failures"]


def test_new_and_baseline_cases_cannot_share_an_ambiguous_short_method_name():
    document, originals, expected, baseline_input = operator_baseline_fixture()
    content = ("import unittest\nclass Tests(unittest.TestCase):\n    def test_add_one(self):\n"
        "        self.assertEqual(1 + 1, 2)\n")
    replace_new_file_original(document, originals, content)
    document["assets"][3]["details"]["test_method"] = "test_add_one"
    report_id, report = report_original(document, originals)
    report["cases"][0].update(test="test_add_one", qualname="test_boundaries.Tests.test_add_one")
    log_id = next(row["artifact_id"] for row in document["run_artifacts"] if row["role"] == "LOG")
    log = next(row["content_utf8"] for row in originals if row["id"] == log_id).replace("test_boundary", "test_add_one")
    replace_accepted_artifact(document, originals, log_id, log)
    report.update(log_sha256=hashlib.sha256(log.encode()).hexdigest(), log_bytes=len(log.encode()))
    replace_accepted_artifact(document, originals, report_id, json.dumps(report))
    result = controller.strict_native_acceptance(document, originals, expected, baseline_files=baseline_input)
    assert result["strict_result"] == "NON_PASS" and "CASE_IMPLEMENTATION_METHOD_AMBIGUOUS" in result["failures"]


def test_existing_tracked_baseline_cannot_be_reintroduced_as_a_new_file_diff():
    document, originals, expected = strict_fixture()
    implementation = document["assets"][2]
    item = implementation["details"]["new_files"][0]
    item["path"] = "tests/test_simple.py"
    implementation["details"]["untracked_files"] = [controller.CHILD_FILE, item["path"]]
    content = ("import unittest\nclass Tests(unittest.TestCase):\n    def test_boundary(self):\n"
        "        self.assertEqual(1 + 1, 2)\n")
    replace_new_file_original(document, originals, content)
    result = controller.strict_native_acceptance(document, originals, expected)
    assert result["strict_result"] == "NON_PASS" and "IMPLEMENTATION_BASELINE_FILE_CHANGED" in result["failures"]


def source_document(status="RECOVERY_REQUIRED", version=6):
    configuration = {"sut": {"url": controller.REPOSITORY}, "framework": {"url": controller.REPOSITORY},
        "environment": {"connection": "NONE"}}
    return {"task": {"id": TASK, "project_id": PROJECT, "version": version, "status": status,
        "latest_attempt_id": ATTEMPT, "config_id": CONFIG, "input_digest": "a" * 64,
        "frozen_manifest": {"config_id": CONFIG, "configuration": configuration,
            "resolution": {"repositories": {role: {"url": controller.REPOSITORY, "commit_sha": digit * 40}
                for role, digit in (("sut", "1"), ("framework", "2"))}}}},
        "attempts": [{"id": ATTEMPT, "task_id": TASK, "project_id": PROJECT, "status": status,
            "checkpoint": {}, "runtime_metadata": {
                "budget_reservation": {"state": "HELD", "reserved_seconds": 900, "reserved_cost_microunits": 32},
                "preparation_budget_reservation": {"state": "HELD", "reserved_seconds": 900}}}],
        "assets": [], "artifacts": [], "runs": [], "delegations": []}


def derived_state(purpose):
    return {"project_id": PROJECT, "source_task_id": TASK, "task_id": TASK,
        "purpose": purpose, "target": "root", "writes": {},
        "source_writes": {"dispatch": {"state": "READBACK_COMPLETE", "request": {
            "operation": "DISPATCH", "project_id": PROJECT, "task_id": TASK,
            "operation_key": "accept:original-dispatch", "expected_version": 3}}}}


def page(document):
    original = json.dumps(document, ensure_ascii=False)
    return {"profile": controller.PROFILE, "project_id": PROJECT, "task_id": document["task"]["id"],
        "version": document["task"]["version"], "offset": 0, "next_offset": len(original),
        "complete": True, "content": original, "total_characters": len(original),
        "sha256": hashlib.sha256(original.encode()).hexdigest()}


def proof_file(tmp_path, **changes):
    proof = {"profile": "hypertest-cloud-host-reconciliation/v1", "project_id": PROJECT,
        "task_id": TASK, "attempt_id": ATTEMPT, "expected_version": 6,
        "observed_at": "2026-10-22T12:00:00Z", "old_owner_fenced": True,
        "local_processes_stopped": True, "external_operations_reconciled": True,
        "pending_operation_keys": [], "model_budget_disposition": "KEEP_HELD",
        "model_drain_observed": False, "observations": "Synthetic host stop proof; no model drain claim", **changes}
    path = tmp_path / "operator-proof.json"
    path.write_text(json.dumps(proof))
    path.chmod(0o600)
    return path


def source_response(request, document):
    if "/operations/" in request.url.path:
        return httpx.Response(200, json={"status": "ACCEPTED", "profile": controller.PROFILE,
            "project_id": PROJECT, "task_id": TASK, "operation": "DISPATCH",
            "operation_key": "accept:original-dispatch", "version": 4, "attempt_id": ATTEMPT})
    if request.url.path.endswith("/summary"):
        return httpx.Response(200, json={**document["task"], "current_attempt": document["attempts"][0]})
    if request.url.path.endswith("/configuration"):
        return httpx.Response(200, json={"items": [{"id": CONFIG,
            "configuration": document["task"]["frozen_manifest"]["configuration"]}]})
    snapshot = deepcopy(document)
    snapshot["task"]["version"] = int(request.url.params.get("version", document["task"]["version"]))
    return httpx.Response(200, json=page(snapshot))


def test_lost_submission_is_persisted_and_rerun_only_queries_original_key(tmp_path):
    calls = []

    def transport(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            raise httpx.ReadTimeout("Synthetic lost response", request=request)
        return httpx.Response(404, json={"detail": "Not yet observed"})

    state = {"project_id": PROJECT, "writes": {}}
    with httpx.Client(base_url="https://isolated.invalid", transport=httpx.MockTransport(transport),
            headers={"X-Hypertest-Operator-Key": "synthetic-private-key"}) as client:
        run = controller.Controller(client, tmp_path / "state.json", state)
        with pytest.raises(controller.Blocked, match="RECONCILIATION"):
            run.mutate("cancel", "CANCEL_TASK", task_id=TASK, reason="Fixture cancellation")
        original = json.loads((tmp_path / "state.json").read_text())
        assert original["writes"]["cancel"]["state"] == "UNKNOWN"
        assert "synthetic-private-key" not in json.dumps(original)
        with pytest.raises(controller.Blocked, match="NOT_OBSERVED"):
            run.mutate("cancel", "CANCEL_TASK", task_id=TASK, reason="Must not replace the frozen request")
    assert [method for method, _ in calls] == ["POST", "GET"]
    assert unquote(calls[1][1]).endswith(original["writes"]["cancel"]["request"]["operation_key"])


def test_fixed_readback_uses_original_version_and_full_unicode_digest(tmp_path):
    document = {"task": {"id": TASK, "project_id": PROJECT, "version": 4, "title": "原文 🧪"}, "assets": []}
    original = json.dumps(document, ensure_ascii=False)
    checksum = hashlib.sha256(original.encode()).hexdigest()
    versions = []

    def transport(request):
        offset = int(request.url.params["offset"])
        versions.append(request.url.params.get("version"))
        end = 20 if offset == 0 else len(original)
        return httpx.Response(200, json={"profile": controller.PROFILE, "project_id": PROJECT, "task_id": TASK,
            "version": 4, "offset": offset, "next_offset": end, "complete": end == len(original),
            "content": original[offset:end], "sha256": checksum, "total_characters": len(original)})

    with httpx.Client(base_url="https://isolated.invalid", transport=httpx.MockTransport(transport)) as client:
        run = controller.Controller(client, tmp_path / "state.json", {"project_id": PROJECT})
        assert run.read_document(TASK) == document
    assert versions == [None, "4"]


def test_uncertain_project_creation_is_read_by_frozen_unique_key_not_reposted(tmp_path):
    methods = []

    def transport(request):
        methods.append(request.method)
        if request.method == "POST":
            raise httpx.ReadTimeout("Lost create", request=request)
        return httpx.Response(200, json=[])

    state = {"project": {"state": "NEW", "request": {"key": "CLOUDSDK_FIXTURE", "name": "Isolated fixture"}}}
    with httpx.Client(base_url="https://isolated.invalid", transport=httpx.MockTransport(transport)) as client:
        run = controller.Controller(client, tmp_path / "state.json", state)
        for _ in range(2):
            with pytest.raises(controller.Blocked, match="PROJECT_CREATE_UNCERTAIN"):
                run.project()
    assert methods == ["POST", "GET"]


def test_only_explicit_loopback_http_and_finite_public_fixture_inputs_are_admitted():
    with pytest.raises(controller.Blocked):
        controller.api_origin("http://127.0.0.1:8000", False)
    with pytest.raises(controller.Blocked):
        controller.api_origin("http://public.invalid", True)
    assert controller.api_origin("http://127.0.0.1:8000", True) == "http://127.0.0.1:8000"
    inputs = controller.task_inputs("codex", seconds=300, credits=12)
    assert inputs["budgets"] == {"accounting_unit": "REQUEST_CREDITS", "total_seconds": 300,
        "total_cost_microunits": 12, "max_attempts": 1, "max_concurrency": 1}
    assert inputs["authorization"]["network_targets"] == []
    assert "Codex child" in inputs["prd_markdown"] and "manufacture a failure" in inputs["prd_markdown"]


def test_operator_reconciliation_freezes_one_request_and_preserves_original_held_budget(tmp_path):
    state = derived_state("HOST_RECONCILIATION")
    original_source = deepcopy(state["source_writes"])
    document = source_document()
    calls = []
    receipt = None

    def transport(request):
        nonlocal receipt
        calls.append(request.method)
        if request.method == "POST":
            body = json.loads(request.content)
            persisted = json.loads((tmp_path / "reconcile.json").read_text())
            assert persisted["writes"]["reconcile"]["request"] == body
            assert persisted["writes"]["reconcile"]["state"] == "SENT"
            assert body["operation"] == "RECONCILE_ATTEMPT" and body["status"] == "FAILED"
            assert body["task_id"] == TASK and body["attempt_id"] == ATTEMPT and body["expected_version"] == 6
            assert body["reconciliation"]["model_budget_disposition"] == "KEEP_HELD"
            assert body["reconciliation"]["model_drain_observed"] is False
            assert "budget_settlement" not in body and "usage_seconds" not in body
            document["task"].update(version=7, status="FAILED")
            document["attempts"][0]["status"] = "FAILED"
            receipt = {"status": "ACCEPTED", "profile": controller.PROFILE, "project_id": PROJECT,
                "task_id": TASK, "attempt_id": ATTEMPT, "version": 7,
                "operation": body["operation"], "operation_key": body["operation_key"]}
            return httpx.Response(200, json=receipt)
        if receipt and "/operations/" in request.url.path and not request.url.path.endswith("original-dispatch"):
            return httpx.Response(200, json=receipt)
        return source_response(request, document)

    with httpx.Client(base_url="https://isolated.invalid", transport=httpx.MockTransport(transport)) as client:
        run = controller.Controller(client, tmp_path / "reconcile.json", state)
        result = run.reconcile_attempt(proof_file(tmp_path))
        assert result["model_budget_disposition"] == "KEEP_HELD" and result["version"] == 7
        assert run.reconcile_attempt(None) == result  # Accepted original receipt, never another POST.
    assert calls.count("POST") == 1
    assert state["source_writes"] == original_source
    assert document["attempts"][0]["runtime_metadata"]["budget_reservation"]["state"] == "HELD"


@pytest.mark.parametrize("change", [{"task_id": NEXT_TASK}, {"attempt_id": NEXT_TASK}, {"expected_version": 5}])
def test_host_proof_target_and_version_must_match_before_any_post(tmp_path, change):
    methods = []

    def transport(request):
        methods.append(request.method)
        return source_response(request, source_document())

    with httpx.Client(base_url="https://isolated.invalid", transport=httpx.MockTransport(transport)) as client:
        run = controller.Controller(client, tmp_path / "reconcile.json", derived_state("HOST_RECONCILIATION"))
        with pytest.raises(controller.Blocked, match="TARGET_OR_VERSION"):
            run.reconcile_attempt(proof_file(tmp_path, **change))
    assert "POST" not in methods


@pytest.mark.parametrize("change", [
    {"pending_operation_keys": ["still-pending"]}, {"model_drain_observed": True},
    {"old_owner_fenced": 1}, {"model_budget_disposition": "RELEASE"},
    {"observed_at": "2026-10-22T12:00:00"}, {"extra_observation": "unreviewed"},
])
def test_host_proof_is_closed_and_does_not_infer_drain_or_release(tmp_path, change):
    with pytest.raises(ValueError):
        controller.HostReconciliationProof.model_validate_json(proof_file(tmp_path, **change).read_bytes())


def test_unknown_reconciliation_uses_original_key_without_a_new_proof_or_post(tmp_path):
    state = derived_state("HOST_RECONCILIATION")
    methods = []
    original_key = None

    def transport(request):
        nonlocal original_key
        methods.append(request.method)
        if request.method == "POST":
            original_key = json.loads(request.content)["operation_key"]
            raise httpx.ReadTimeout("Synthetic unknown reconcile", request=request)
        if original_key and unquote(request.url.path).endswith(original_key):
            return httpx.Response(404, json={"detail": "Original request not observed"})
        return source_response(request, source_document())

    with httpx.Client(base_url="https://isolated.invalid", transport=httpx.MockTransport(transport)) as client:
        run = controller.Controller(client, tmp_path / "reconcile.json", state)
        with pytest.raises(controller.Blocked, match="RECONCILIATION"):
            run.reconcile_attempt(proof_file(tmp_path))
        frozen = deepcopy(state["writes"]["reconcile"]["request"])
        with pytest.raises(controller.Blocked, match="NOT_OBSERVED"):
            run.reconcile_attempt(None)
    assert methods.count("POST") == 1 and state["writes"]["reconcile"]["request"] == frozen


def test_followup_uses_same_project_config_and_frozen_dual_sha_with_explicit_related_task(tmp_path):
    state = derived_state("FOLLOWUP")
    document = source_document("FAILED", 7)
    posts = []

    def transport(request):
        if request.url.path.endswith("/capabilities"):
            return httpx.Response(200, json={"profile": controller.PROFILE, "enabled": True})
        if request.method == "POST":
            body = json.loads(request.content)
            posts.append(body)
            persisted = json.loads((tmp_path / "followup.json").read_text())
            name = "create" if body["operation"] == "CREATE_TASK" else "resolve"
            assert persisted["writes"][name]["request"] == body
            assert request.url.path == "/api/v1/cloud/operations"  # Never /projects or CONFIGURE.
            return httpx.Response(200, json={"status": "ACCEPTED", "profile": controller.PROFILE,
                "project_id": PROJECT, "task_id": NEXT_TASK, "operation": body["operation"],
                "operation_key": body["operation_key"], "version": 1 if name == "create" else 2,
                "resolution_id": RESOLUTION})
        if request.url.path.endswith(NEXT_TASK):
            return httpx.Response(200, json=page({"task": {"id": NEXT_TASK, "project_id": PROJECT,
                "version": int(request.url.params["version"])}}))
        return source_response(request, document)

    with httpx.Client(base_url="https://isolated.invalid", transport=httpx.MockTransport(transport)) as client:
        result = controller.Controller(client, tmp_path / "followup.json", state).start_followup(seconds=600, credits=24)
    assert [row["operation"] for row in posts] == ["CREATE_TASK", "RESOLVE_INPUTS"]
    created = posts[0]
    assert created["project_id"] == PROJECT and created["config_id"] == CONFIG and created["related_task_id"] == TASK
    assert created["inputs"]["sut_selector"]["kind"] == "SHA" and created["inputs"]["sut_selector"]["value"] == "1" * 40
    assert created["inputs"]["framework_selector"]["value"] == "2" * 40
    assert created["inputs"]["budgets"]["total_cost_microunits"] == 24
    assert result["task_id"] == NEXT_TASK and result["execution_started"] is False


@pytest.mark.parametrize("pending", [False, True])
def test_followup_never_bypasses_recovery_or_original_pending_write(tmp_path, pending):
    state = derived_state("FOLLOWUP")
    if pending:
        state["source_writes"]["dispatch"]["state"] = "UNKNOWN"
    calls = []

    def transport(request):
        calls.append(request.method)
        if request.url.path.endswith("/capabilities"):
            return httpx.Response(200, json={"profile": controller.PROFILE, "enabled": True})
        return source_response(request, source_document("FAILED" if pending else "RECOVERY_REQUIRED"))

    with httpx.Client(base_url="https://isolated.invalid", transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(controller.Blocked, match="SOURCE_LEDGER_READBACK_REQUIRED" if pending else "SOURCE_MUST_BE_TERMINAL"):
            controller.Controller(client, tmp_path / "followup.json", state).start_followup(seconds=600, credits=24)
    assert "POST" not in calls and state["writes"] == {}


def cli_source(tmp_path, **changes):
    tmp_path.chmod(0o700)
    operator = tmp_path / "operator-key"
    operator.write_text("synthetic-private-operator")
    operator.chmod(0o600)
    source_path = tmp_path / "root-reconcile.json"
    source = {"profile": controller.STATE_PROFILE, "api_origin": "https://isolated.invalid", "target": "root",
        "operator_fingerprint": hashlib.sha256(operator.read_bytes()).hexdigest(),
        "project_id": PROJECT, "task_id": TASK,
        "writes": derived_state("FOLLOWUP")["source_writes"], **changes}
    controller.save(source_path, source)
    args = ["start-followup", "--api-origin", "https://isolated.invalid",
        "--state-file", str(tmp_path / "codex.json"), "--source-state-file", str(source_path),
        "--operator-key-file", str(operator), "--target", "codex", "--seconds", "600", "--credits", "24"]
    return source_path, args


@pytest.mark.parametrize("lost_response", [False, True])
def test_new_codex_followup_from_root_keeps_source_and_existing_target_frozen(tmp_path, monkeypatch, capsys, lost_response):
    source_path, args = cli_source(tmp_path)
    original_source = source_path.read_bytes()
    document, requests = source_document("FAILED", 7), []
    real_client = httpx.Client
    original_key = None

    def transport(request):
        nonlocal original_key
        requests.append((request.method, request.url.path))
        if request.url.path.endswith("/capabilities"):
            return httpx.Response(200, json={"profile": controller.PROFILE, "enabled": True})
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["project_id"] == PROJECT
            if body["operation"] == "CREATE_TASK":
                assert body["related_task_id"] == TASK and body["config_id"] == CONFIG
                assert "Codex child" in body["inputs"]["prd_markdown"]
                original_key = body["operation_key"]
                if lost_response:
                    raise httpx.ReadTimeout("Synthetic lost create", request=request)
            return httpx.Response(200, json={"status": "ACCEPTED", "profile": controller.PROFILE,
                "project_id": PROJECT, "task_id": NEXT_TASK, "operation": body["operation"],
                "operation_key": body["operation_key"], "version": 1 if body["operation"] == "CREATE_TASK" else 2,
                "resolution_id": RESOLUTION})
        if original_key and unquote(request.url.path).endswith(original_key):
            return httpx.Response(404, json={"detail": "Original key unobserved"})
        if request.url.path.endswith(NEXT_TASK):
            return httpx.Response(200, json=page({"task": {"id": NEXT_TASK, "project_id": PROJECT,
                "version": int(request.url.params["version"])}}))
        return source_response(request, document)

    monkeypatch.setattr(controller.httpx, "Client", lambda **kwargs:
        real_client(**kwargs, transport=httpx.MockTransport(transport)))
    assert controller.main(args) == int(lost_response)
    output = json.loads(capsys.readouterr().out)
    if lost_response:
        assert output["code"] == "ORIGINAL_KEY_RECONCILIATION_REQUIRED"
    else:
        assert output["task_id"] == NEXT_TASK
    path = tmp_path / "codex.json"
    frozen = path.read_bytes()
    state = json.loads(frozen)
    assert state["target"] == "codex" and state["source_target"] == "root"
    assert state["source_task_id"] == TASK and source_path.read_bytes() == original_source
    # Replace only the explicit --target value, never the source state or key.
    changed_target = list(args)
    changed_target[changed_target.index("--target") + 1] = "root"
    before = len(requests)
    assert controller.main(changed_target) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "ORIGINAL_TARGET_OR_IDENTITY_MISMATCH"
    assert len(requests) == before and path.read_bytes() == frozen
    if lost_response:
        assert controller.main(args) == 1
        assert json.loads(capsys.readouterr().out)["code"] == "ORIGINAL_KEY_NOT_OBSERVED"
        assert all(method == "GET" for method, _ in requests[before:])
        assert path.read_bytes() == frozen and sum(method == "POST" for method, _ in requests) == 1
    assert source_path.read_bytes() == original_source


@pytest.mark.parametrize("mode,changes", [
    ("reconcile", {}), ("start-followup", {"api_origin": "https://other.invalid"}),
    ("start-followup", {"operator_fingerprint": "f" * 64}),
    ("start-followup", {"project_id": ""}), ("start-followup", {"target": "unknown"}),
])
def test_new_followup_role_does_not_relax_identity_or_retarget_reconciliation(tmp_path, monkeypatch, capsys, mode, changes):
    source_path, args = cli_source(tmp_path, **changes)
    original_source = source_path.read_bytes()
    args[0] = mode

    def forbidden_client(**kwargs):
        pytest.fail("Invalid source identity must be rejected before any HTTP client")

    monkeypatch.setattr(controller.httpx, "Client", forbidden_client)
    assert controller.main(args) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "ORIGINAL_TARGET_OR_IDENTITY_MISMATCH"
    assert source_path.read_bytes() == original_source and not (tmp_path / "codex.json").exists()
