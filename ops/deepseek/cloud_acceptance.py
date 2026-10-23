"""Private six-step Cloud acceptance controller; never executes a model or tests.

Run against an explicitly isolated API/database. A separate operator-run Worker
resolves inputs and executes the task. Sent writes are GET-only on every rerun.
"""
from __future__ import annotations

import argparse
import ast
import base64
import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlsplit
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from hypertest.api.cloud_schemas import PROFILE, CloudMutation
from hypertest.api.schemas import ProjectCreate

REPOSITORY = "https://github.com/pypa/sampleproject.git"
ENTRYPOINT = "PYTHONPATH=/workspace/sut/src python -m unittest discover -s tests -v"
STATE_PROFILE = "hypertest-cloud-acceptance/v1"
STRICT_PROFILE = "hypertest-cloud-public-native-acceptance/v1"
HARNESS_COMMIT = "687f282e8625c6b8d11ff58211a90524be2e4317"
CHILD_FILE = "artifacts/codex_analysis.md"


class NativeAcceptanceExpectation(BaseModel):
    """Operator-selected fixed identities, never execution or platform authority."""
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    profile: Literal["hypertest-cloud-public-native-acceptance/v1"]
    project_id: UUID
    task_id: UUID
    attempt_id: UUID
    accepted_version: int = Field(strict=True, ge=1)
    native_ref: UUID
    child_artifact_id: UUID
    child_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    analysis_asset_id: UUID
    design_asset_id: UUID
    implementation_asset_id: UUID
    run_id: UUID


class OperatorBaselineOriginal(BaseModel):
    """Private operator input, never taken from an Agent or accepted report.

    The caller must independently compare the frozen framework Git object and
    stopped workspace bytes. This finite profile supports only the public
    fixture's existing tests/test_simple.py, without fetching or executing it.
    """
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, frozen=True)
    repository_url: Literal["https://github.com/pypa/sampleproject.git"]
    framework_sha: str = Field(strict=True, pattern=r"^[a-f0-9]{40}([a-f0-9]{24})?$")
    path: Literal["tests/test_simple.py"]
    expected_sha256: str = Field(strict=True, pattern=r"^[a-f0-9]{64}$")
    byte_count: int = Field(strict=True, ge=1, le=65536)
    content_utf8: str = Field(strict=True, min_length=1, max_length=65536)
    source: Literal["OPERATOR_VERIFIED_FROZEN_FRAMEWORK"] = "OPERATOR_VERIFIED_FROZEN_FRAMEWORK"


def _new_file_originals(patch: str) -> dict[str, bytes]:
    """Decode complete new-file diffs only; never apply a patch or execute code.

    This finite public-fixture acceptance profile declines modified/deleted files
    and multi-hunk layouts instead of guessing missing baseline bytes.
    """
    result = {}
    blocks = re.split(r"(?m)^diff --git ", patch)
    if blocks[0]:
        raise ValueError("UNSUPPORTED_NEW_FILE_PATCH")
    for block in blocks[1:]:
        lines = block.splitlines(keepends=True)
        header = re.fullmatch(r"a/(tests/[A-Za-z0-9_./-]+\.py|artifacts/codex_analysis\.md) b/\1\n", lines[0])
        if not header or ".." in header[1].split("/") or header[1] in result:
            raise ValueError("UNSUPPORTED_NEW_FILE_PATCH")
        path = header[1]
        start = lines.index("--- /dev/null\n")
        if lines[start + 1] != "+++ b/" + path + "\n":
            raise ValueError("UNSUPPORTED_NEW_FILE_PATCH")
        hunk = re.fullmatch(r"@@ -0,0 \+1,([0-9]+) @@\n", lines[start + 2])
        if not hunk:
            raise ValueError("UNSUPPORTED_NEW_FILE_PATCH")
        additions = lines[start + 3:]
        no_newline = additions and additions[-1].rstrip("\n") == "\\ No newline at end of file"
        if no_newline:
            additions.pop()
        if len(additions) != int(hunk[1]) or any(not line.startswith("+") for line in additions):
            raise ValueError("INCOMPLETE_NEW_FILE_PATCH")
        original = "".join(line[1:] for line in additions)
        if no_newline:
            original = original.removesuffix("\n")
        result[path] = original.encode("utf-8")
    if not result:
        raise ValueError("NEW_FILE_PATCH_REQUIRED")
    return result


def strict_native_acceptance(document: dict, originals: list[dict], expected: NativeAcceptanceExpectation,
                             *, baseline_files: list[dict] | None = None) -> dict:
    """Mechanical PRD acceptance of accepted records and original bytes only.

    It does not run unittest, establish independent child-writer provenance,
    inspect SDK history, change Canonical State or upgrade a legacy Gate.
    baseline_files is a separate trusted operator input, not an artifact, field
    of the frozen Task/expectation, or authority inferred from report text.
    """
    failures = []

    def require(condition, code):
        if not condition and code not in failures:
            failures.append(code)

    result = {"assessment_profile": STRICT_PROFILE, "strict_result": "NON_PASS",
        "task_id": str(expected.task_id), "attempt_id": str(expected.attempt_id),
        "accepted_version": expected.accepted_version, "failures": failures,
        "canonical_state_modified": False, "tests_executed_by_checker": False,
        "independent_execution_proof": False, "child_writer_provenance": "RUNTIME_REPORTED",
        "sdk_idle_used": False, "legacy_gate_upgraded": False}
    try:
        task = document["task"]
        task_id, attempt_id = str(expected.task_id), str(expected.attempt_id)
        require(task["id"] == task_id and task["project_id"] == str(expected.project_id)
            and type(task["version"]) is int and task["version"] == expected.accepted_version,
            "FIXED_TASK_IDENTITY_MISMATCH")
        result["platform_reported_result"] = task["reported_result"] if task["reported_result"] in {
            "NOT_RUN", "PASS", "FAIL", "ERROR", "SKIPPED", "UNKNOWN", "BLOCKED"} else "UNKNOWN"
        attempts = [row for row in document["attempts"] if row["id"] == attempt_id]
        require(len(attempts) == 1, "ATTEMPT_IDENTITY_MISMATCH")
        attempt = attempts[0]
        require(attempt["task_id"] == task_id and task["latest_attempt_id"] == attempt_id,
            "ATTEMPT_IDENTITY_MISMATCH")
        require(task["status"] == attempt["status"] == "COMPLETED"
            and task["reported_result"] == attempt["reported_result"] == "PASS", "TASK_NOT_COMPLETED_PASS")
        manifest = task["frozen_manifest"]
        require(manifest["inputs"] == task["inputs"], "FROZEN_INPUTS_MISMATCH")
        repositories = manifest["resolution"]["repositories"]
        require(all(repositories[role]["url"] == REPOSITORY
            and re.fullmatch(r"[a-f0-9]{40}([a-f0-9]{24})?", repositories[role]["commit_sha"])
            for role in ("sut", "framework")), "PUBLIC_FIXED_REPOSITORIES_REQUIRED")

        def indexed(rows):
            values = {row["id"]: row for row in rows}
            require(len(values) == len(rows), "DUPLICATE_ACCEPTED_ID")
            return values

        assets, artifacts = indexed(document["assets"]), indexed(document["artifacts"])
        original_index = indexed(originals)
        verified = {}
        for artifact_id, artifact in artifacts.items():
            original = original_index.get(artifact_id)
            require(original is not None, "ORIGINAL_BYTES_MISSING")
            if original is None:
                continue
            raw = original["content_utf8"].encode("utf-8")
            valid = (artifact["task_id"] == task_id and artifact["attempt_id"] == attempt_id
                and artifact["project_id"] == str(expected.project_id) and bool(artifact["verified_at"])
                and type(artifact["byte_count"]) is int and len(raw) == artifact["byte_count"]
                and hashlib.sha256(raw).hexdigest() == artifact["sha256"] == original["sha256"])
            require(valid, "ORIGINAL_BYTES_INTEGRITY_MISMATCH")
            if valid:
                verified[artifact_id] = raw
        require(set(original_index) == set(artifacts), "ORIGINAL_ID_SET_MISMATCH")
        child_id = str(expected.child_artifact_id)
        child = verified.get(child_id, b"")
        require(0 < len(child) <= 8192 and hashlib.sha256(child).hexdigest() == expected.child_sha256,
            "CHILD_ORIGINAL_MISMATCH")
        selected = {}
        for kind, asset_id in (("ANALYSIS", expected.analysis_asset_id), ("DESIGN", expected.design_asset_id),
                               ("IMPLEMENTATION", expected.implementation_asset_id)):
            asset = assets.get(str(asset_id), {})
            selected[kind] = asset
            require(asset.get("kind") == kind and asset.get("task_id") == task_id
                and asset.get("attempt_id") == attempt_id and type(asset.get("task_version")) is int
                and asset["task_version"] <= expected.accepted_version, "SELECTED_ASSET_IDENTITY_MISMATCH")
            if kind in {"ANALYSIS", "DESIGN"}:
                require(asset.get("artifact_id") == child_id, kind + "_DIRECT_ARTIFACT_MISMATCH")
        analysis, design, implementation = selected["ANALYSIS"], selected["DESIGN"], selected["IMPLEMENTATION"]
        links = {(row["asset_id"], row["referenced_asset_id"]) for row in document["asset_references"]
            if row["task_id"] == task_id}
        require((str(expected.design_asset_id), str(expected.analysis_asset_id)) in links
            and analysis["task_version"] < design["task_version"], "DESIGN_ANALYSIS_RECEIPT_LINK_MISSING")

        delegations = [row for row in document["delegations"] if row["native_ref"] == str(expected.native_ref)]
        require(len(delegations) == 1, "NATIVE_DELEGATION_IDENTITY_MISMATCH")
        delegation = delegations[0]
        terminal = delegation["terminal_observation"]
        UUID(terminal["run_id"])
        require(delegation["task_id"] == task_id and delegation["attempt_id"] == attempt_id
            and delegation["provider"] == "codex" and delegation["status"] == "COMPLETED"
            and terminal["source"] == "official-plugin-runtime-reported" and terminal["source_commit"] == HARNESS_COMMIT
            and terminal["stop_reason"] == "completed" and terminal["independent_execution_proof"] is False,
            "NATIVE_DELEGATION_TERMINAL_MISMATCH")
        contributions = {row["asset_id"] for row in document["delegation_assets"]
            if row["task_id"] == task_id and row["delegation_id"] == delegation["id"]}
        require({str(expected.analysis_asset_id), str(expected.design_asset_id)} <= contributions
            and max(analysis["task_version"], design["task_version"]) < delegation["task_version"],
            "NATIVE_DELEGATION_ASSET_LINK_MISSING")

        runs = [row for row in document["runs"] if row["id"] == str(expected.run_id)]
        require(len(runs) == 1, "ACTUAL_RUN_MISSING")
        run = runs[0]
        execution = run["execution"]
        started = datetime.fromisoformat(execution["started_at"].replace("Z", "+00:00"))
        finished = datetime.fromisoformat(execution["finished_at"].replace("Z", "+00:00"))
        sut_sha = repositories["sut"]["commit_sha"]
        observation = execution.get("environment_observation", {})
        described_build = (execution["actual_sut_build"] == "pypa/sampleproject " + sut_sha
            + " via PYTHONPATH=/workspace/sut/src"
            and isinstance(observation, dict) and observation.get("sut_sha") == sut_sha
            and observation.get("pythonpath") == "/workspace/sut/src")
        require(run["task_id"] == task_id and run["attempt_id"] == attempt_id and run["reported_result"] == "PASS"
            and execution["source"] == "PROJECT_FRAMEWORK" and execution["entrypoint"] == ENTRYPOINT
            and ENTRYPOINT in task["inputs"]["framework_entrypoints"] and execution["cwd"] == "/workspace/framework"
            and type(execution["exit_code"]) is int and execution["exit_code"] == 0
            and started.tzinfo is not None and finished.tzinfo is not None and started <= finished
            and execution["framework_sha"] == repositories["framework"]["commit_sha"]
            and (execution["actual_sut_build"] in {sut_sha, REPOSITORY + "@" + sut_sha} or described_build)
            and re.fullmatch(r"[a-f0-9]{64}", execution["test_tree_digest"]), "ACTUAL_RUN_EXECUTION_MISMATCH")
        completion = attempt["checkpoint"]["completion_manifest"]
        required_ids = set(completion["required_asset_ids"])
        require({str(expected.analysis_asset_id), str(expected.design_asset_id), str(expected.implementation_asset_id)} <= required_ids
            and required_ids <= assets.keys() and completion["pending_operation_keys"] == []
            and completion["all_local_processes_stopped"] is True and completion["external_operations_reconciled"] is True,
            "COMPLETION_REFERENCES_INCOMPLETE")
        final = assets.get(attempt["checkpoint"]["final_report_revision"], {})
        require(final.get("id") in required_ids and final.get("kind") == "REPORT"
            and final.get("attempt_id") == attempt_id and final.get("reported_result") == "PASS", "FINAL_REPORT_MISMATCH")
        case_assets = {asset_id: assets[asset_id] for asset_id in required_ids & assets.keys()
            if assets[asset_id]["kind"] == "CASE"}
        cases = [row for row in document["run_cases"] if row["run_id"] == run["id"]]
        require(bool(case_assets) and len(cases) == len(case_assets)
            and {row["case_revision_id"] for row in cases} == set(case_assets)
            and all(row["task_id"] == task_id and row["reported_result"] == "PASS" and bool(row["actual"].strip()) for row in cases)
            and all(row["attempt_id"] == attempt_id and row["reported_result"] not in {"FAIL", "ERROR", "BLOCKED"}
                for row in case_assets.values()), "RUN_CASE_ACTUALS_MISMATCH")

        details = implementation["details"]
        retained = details["retained_child_file"]
        require(details["framework_sha"] == execution["framework_sha"] and details["test_tree_digest"] == execution["test_tree_digest"]
            and details["cwd"] == execution["cwd"] and details["dirty_files"] == []
            and retained["path"] == CHILD_FILE and retained["artifact_id"] == child_id
            and retained["sha256"] == expected.child_sha256 and retained["bytes"] == len(child)
            and CHILD_FILE in details["untracked_files"], "IMPLEMENTATION_INVENTORY_MISMATCH")
        new_files, methods, decoded_patches = {}, {}, {}
        child_patch_id = None
        declared_paths = {}
        for item in details["new_files"]:
            patch_id = item.get("unified_diff_artifact_id", item["artifact_id"])
            declared_paths.setdefault(patch_id, set()).add(item["path"])
        for item in details["new_files"]:
            # Two explicit representations only: the historical artifact_id is
            # itself a complete new-file diff, or artifact_id holds raw UTF-8
            # source and unified_diff_artifact_id names the separate diff. Never
            # infer the pairing from filenames, suffixes or untrusted text.
            patch_id = item.get("unified_diff_artifact_id", item["artifact_id"])
            require(item["path"] != "tests/test_simple.py", "IMPLEMENTATION_BASELINE_FILE_CHANGED")
            patch_valid = patch_id in verified and artifacts[patch_id]["media_type"] == "text/x-diff"
            require(patch_valid, "IMPLEMENTATION_PATCH_MISSING")
            if not patch_valid:
                continue
            patch_bytes = verified[patch_id]
            require(type(item.get("unified_diff_bytes", len(patch_bytes))) is int
                and item.get("unified_diff_bytes", len(patch_bytes)) == len(patch_bytes)
                and item.get("unified_diff_sha256", artifacts[patch_id]["sha256"]) == hashlib.sha256(patch_bytes).hexdigest(),
                "IMPLEMENTATION_PATCH_BYTES_MISMATCH")
            if patch_id not in decoded_patches:
                decoded = _new_file_originals(patch_bytes.decode("utf-8"))
                # A combined new-file patch may also retain the exact child
                # original required by this fixture. It is never parsed as
                # Python tests or allowed to introduce an undeclared path.
                child_paths = {CHILD_FILE} if CHILD_FILE in decoded else set()
                require(set(decoded) == declared_paths[patch_id] | child_paths,
                    "IMPLEMENTATION_PATCH_INVENTORY_MISMATCH")
                if child_paths:
                    require(child_patch_id is None, "IMPLEMENTATION_CHILD_PATCH_DUPLICATE")
                    child_patch_id = patch_id
                    require(decoded[CHILD_FILE] == child, "IMPLEMENTATION_CHILD_PATCH_BYTES_MISMATCH")
                decoded_patches[patch_id] = decoded
            decoded = decoded_patches[patch_id]
            raw = decoded[item["path"]]
            require(hashlib.sha256(raw).hexdigest() == item["sha256"] and item["path"] in details["untracked_files"]
                and type(item.get("bytes", len(raw))) is int and item.get("bytes", len(raw)) == len(raw),
                "IMPLEMENTATION_NEW_FILE_BYTES_MISMATCH")
            if "unified_diff_artifact_id" in item:
                raw_id = item["artifact_id"]
                require(raw_id != patch_id and raw_id in verified and artifacts[raw_id]["media_type"] == "text/plain",
                    "IMPLEMENTATION_RAW_ORIGINAL_LAYOUT_INVALID")
                require(verified.get(raw_id) == raw, "IMPLEMENTATION_RAW_DIFF_BYTES_MISMATCH")
            require(item["path"] not in new_files, "IMPLEMENTATION_DUPLICATE_NEW_FILE")
            new_files[item["path"]] = hashlib.sha256(raw).hexdigest()
            tree = ast.parse(raw.decode("utf-8"))
            # Public fixture only: unittest discover -s tests imports root-level
            # test_*.py modules. Free functions and other classes are not tests.
            require(re.fullmatch(r"tests/test_[A-Za-z_0-9]+\.py", item["path"])
                and any(isinstance(node, ast.Import) and any(alias.name == "unittest" and alias.asname is None
                    for alias in node.names) for node in tree.body), "IMPLEMENTATION_UNITTEST_LAYOUT_UNSUPPORTED")
            module = item["path"].removeprefix("tests/").removesuffix(".py")
            for node in tree.body:
                if not isinstance(node, ast.ClassDef) or not any(isinstance(base, ast.Attribute)
                        and isinstance(base.value, ast.Name) and base.value.id == "unittest" and base.attr == "TestCase"
                        for base in node.bases):
                    continue
                for method in node.body:
                    if isinstance(method, ast.FunctionDef) and method.name.startswith("test_"):
                        require(method.name not in methods, "IMPLEMENTATION_TEST_METHOD_AMBIGUOUS")
                        methods[method.name] = module + "." + node.name + "." + method.name
        require(bool(new_files) and implementation["artifact_id"] in declared_paths,
            "IMPLEMENTATION_PATCH_MISSING")
        require(len(details["untracked_files"]) == len(set(details["untracked_files"]))
            and set(details["untracked_files"]) == {CHILD_FILE} | new_files.keys(),
            "IMPLEMENTATION_INVENTORY_INCOMPLETE")

        baseline_methods, baseline_hashes = {}, {}
        if baseline_files is not None:
            try:
                if not isinstance(baseline_files, list) or len(baseline_files) != 1:
                    raise ValueError
                baseline = OperatorBaselineOriginal.model_validate(baseline_files[0])
                raw = baseline.content_utf8.encode("utf-8")
                if (baseline.repository_url != repositories["framework"]["url"]
                        or baseline.framework_sha != repositories["framework"]["commit_sha"]
                        or len(raw) != baseline.byte_count or hashlib.sha256(raw).hexdigest() != baseline.expected_sha256):
                    raise ValueError
                tree = ast.parse(baseline.content_utf8)
                if not any(isinstance(node, ast.Import) and any(alias.name == "unittest" and alias.asname is None
                        for alias in node.names) for node in tree.body):
                    raise ValueError
                for node in tree.body:
                    if not isinstance(node, ast.ClassDef) or not any(isinstance(base, ast.Attribute)
                            and isinstance(base.value, ast.Name) and base.value.id == "unittest" and base.attr == "TestCase"
                            for base in node.bases):
                        continue
                    for method in node.body:
                        if isinstance(method, ast.FunctionDef) and method.name.startswith("test_"):
                            if method.name in baseline_methods:
                                raise ValueError
                            baseline_methods[method.name] = "test_simple." + node.name + "." + method.name
                if baseline_methods != {"test_add_one": "test_simple.TestSimple.test_add_one"}:
                    raise ValueError
                baseline_hashes[baseline.path] = baseline.expected_sha256
            except (TypeError, ValueError, SyntaxError):
                require(False, "BASELINE_ORIGINAL_REQUIRED")
                baseline_methods = {}

        run_artifacts = [row for row in document["run_artifacts"] if row["run_id"] == run["id"] and row["task_id"] == task_id]
        reports = [json.loads(verified[row["artifact_id"]]) for row in run_artifacts
            if row["role"] == "REPORT" and artifacts[row["artifact_id"]]["media_type"] == "application/json"]
        require(len(reports) == 1, "ACTUAL_REPORT_ORIGINAL_MISSING")
        report = reports[0]
        require(all(report[key] == value for key, value in {"run_key": run["run_key"], "entrypoint": ENTRYPOINT,
            "cwd": execution["cwd"], "framework_sha": execution["framework_sha"], "sut_sha": repositories["sut"]["commit_sha"],
            "started_at": execution["started_at"], "finished_at": execution["finished_at"], "exit_code": 0,
            "test_tree_digest": execution["test_tree_digest"]}.items())
            and report["result"] in {"OK", "PASS"}, "RUN_REPORT_EXECUTION_MISMATCH")
        reported_tests = report["cases"]
        require(type(report["tests_run"]) is int and report["tests_run"] == len(reported_tests)
            and len({row["qualname"] for row in reported_tests}) == len(reported_tests)
            and all(row["result"] in {"ok", "PASS"} and row["qualname"].split(".")[-1] == row["test"] for row in reported_tests),
            "RUN_REPORT_CASE_RESULTS_MISMATCH")
        test_names = {row["test"] for row in reported_tests}
        case_methods = {row["details"]["test_method"] for row in case_assets.values()}
        if case_methods - methods.keys() and not baseline_methods:
            require(False, "BASELINE_ORIGINAL_REQUIRED")
        require(not (methods.keys() & baseline_methods.keys()), "CASE_IMPLEMENTATION_METHOD_AMBIGUOUS")
        allowed_methods = {**baseline_methods, **methods}
        require(bool(methods) and methods.keys() <= case_methods <= allowed_methods.keys()
            and case_methods <= test_names and {allowed_methods[name] for name in case_methods if name in allowed_methods}
                <= {row["qualname"] for row in reported_tests}, "CASE_IMPLEMENTATION_METHODS_MISMATCH")
        for case in case_assets.values():
            name = case["details"]["test_method"]
            if name in baseline_methods:
                qualname = baseline_methods[name]
                require(case["details"].get("test_id", qualname) == qualname
                    and case["details"].get("module", "test_simple.TestSimple") == "test_simple.TestSimple",
                    "CASE_IMPLEMENTATION_METHODS_MISMATCH")
        if baseline_files is not None:
            require({row["qualname"] for row in reported_tests} <= set(allowed_methods.values()),
                "CASE_IMPLEMENTATION_METHODS_MISMATCH")
        logs = [verified[row["artifact_id"]] for row in run_artifacts if row["role"] == "LOG"]
        matching_logs = [raw for raw in logs if hashlib.sha256(raw).hexdigest() == report["log_sha256"] and len(raw) == report["log_bytes"]]
        require(len(matching_logs) == 1, "ACTUAL_LOG_ORIGINAL_MISSING")
        logged = re.findall(r"^([A-Za-z_][A-Za-z_0-9]*) \(([^\n]+)\) \.\.\. ok$", matching_logs[0].decode("utf-8"), re.MULTILINE)
        require(set(logged) == {(row["test"], row["qualname"]) for row in reported_tests}
            and len(logged) == len(reported_tests)
            and re.search(r"^Ran " + str(len(reported_tests)) + r" tests? in [0-9.]+s$", matching_logs[0].decode("utf-8"), re.MULTILINE)
            and matching_logs[0].decode("utf-8").rstrip().endswith("\nOK"), "RUN_LOG_CASE_RESULTS_MISMATCH")
        result.update(native_ref=str(expected.native_ref), child_artifact_id=child_id, child_sha256=expected.child_sha256,
            run_id=run["id"], case_count=len(cases), new_file_sha256=new_files)
        if baseline_hashes:
            result.update(operator_baseline_sha256=baseline_hashes,
                baseline_source="OPERATOR_SUPPLIED_FROZEN_FRAMEWORK_ORIGINAL")
    except (KeyError, IndexError, TypeError, ValueError, SyntaxError, AttributeError):
        require(False, "READBACK_STRUCTURE_OR_SUPPORTED_ORIGINAL_FORMAT_INVALID")
    if not failures:
        result["strict_result"] = "PASS"
    return result


class HostReconciliationProof(BaseModel):
    """Explicit operator observations; never inferred from Agent submissions."""
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    profile: Literal["hypertest-cloud-host-reconciliation/v1"]
    project_id: UUID
    task_id: UUID
    attempt_id: UUID
    expected_version: int = Field(strict=True, ge=1)
    observed_at: datetime
    old_owner_fenced: Literal[True]
    local_processes_stopped: Literal[True]
    external_operations_reconciled: Literal[True]
    pending_operation_keys: list[str] = Field(max_length=0)
    model_budget_disposition: Literal["KEEP_HELD"]
    model_drain_observed: Literal[False]
    observations: str = Field(min_length=1, max_length=16000)

    @field_validator("observed_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("Host observation requires a timezone")
        return value

    @field_validator("old_owner_fenced", "local_processes_stopped",
        "external_operations_reconciled", "model_drain_observed", mode="before")
    @classmethod
    def explicit_boolean(cls, value):
        if type(value) is not bool:
            raise ValueError("Host observations require explicit booleans")
        return value


class Blocked(Exception):
    pass


def private_read(path: Path, *, max_bytes=40 * 1024 * 1024, owner_uid=None) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077
                or (owner_uid is not None and info.st_uid != owner_uid)):
            raise Blocked("PRIVATE_FILE_REQUIRED")
        content = stream.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise Blocked("PRIVATE_FILE_LIMIT")
        return content


def save(path: Path, value: dict) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".cloud-acceptance-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2).encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def api_origin(value: str, allow_loopback_http: bool) -> str:
    parsed = urlsplit(value)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"} or any(c.isspace() for c in value)):
        raise Blocked("API_ORIGIN_INVALID")
    if parsed.scheme != "https" and not (allow_loopback_http and parsed.scheme == "http"
            and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
        raise Blocked("HTTPS_OR_EXPLICIT_LOOPBACK_REQUIRED")
    return value.rstrip("/")


class Controller:
    def __init__(self, client, state_file: Path, state: dict):
        self.client, self.path, self.state = client, state_file, state

    def persist(self):
        save(self.path, self.state)

    def get(self, path: str, **params):
        try:
            response = self.client.get("/api/v1" + path, params=params)
        except httpx.HTTPError:
            raise Blocked("API_READ_UNAVAILABLE") from None
        if response.status_code != 200:
            raise Blocked("ORIGINAL_KEY_NOT_OBSERVED" if response.status_code == 404 else "API_READ_REJECTED")
        return response.json()

    def read_document(self, task_id: str, version=None):
        offset, parts, expected_hash, total = 0, [], None, None
        for _ in range(2000):
            params = {"project_id": self.state["project_id"], "offset": offset, "limit": 24000}
            if version is not None:
                params["version"] = version
            page = self.get("/cloud/tasks/" + task_id, **params)
            version = version if version is not None else page["version"]
            expected_hash = expected_hash or page["sha256"]
            total = page["total_characters"] if total is None else total
            if (page["profile"] != PROFILE or page["project_id"] != self.state["project_id"]
                    or page["task_id"] != task_id or page["version"] != version or page["offset"] != offset
                    or type(page["version"]) is not int or type(total) is not int or total < 0
                    or page["sha256"] != expected_hash or page["total_characters"] != total or total > 32 * 1024 * 1024):
                raise Blocked("FIXED_READBACK_IDENTITY_MISMATCH")
            parts.append(page["content"])
            offset += len(page["content"])
            if page["complete"]:
                original = "".join(parts)
                if offset != total or hashlib.sha256(original.encode()).hexdigest() != expected_hash:
                    raise Blocked("FIXED_READBACK_INCOMPLETE")
                document = json.loads(original)
                if document["task"]["id"] != task_id or document["task"]["project_id"] != self.state["project_id"] or document["task"]["version"] != version:
                    raise Blocked("FIXED_DOCUMENT_TARGET_MISMATCH")
                return document
            if not page["content"] or page["next_offset"] != offset:
                raise Blocked("FIXED_READBACK_GAP")
        raise Blocked("FIXED_READBACK_LIMIT")

    def verify(self, write, receipt):
        body = write["request"]
        if (receipt.get("status") != "ACCEPTED" or receipt.get("profile") != PROFILE
                or receipt.get("project_id") != self.state["project_id"]
                or receipt.get("operation") != body["operation"] or receipt.get("operation_key") != body["operation_key"]
                or type(receipt.get("version")) is not int or receipt.get("version") != body["expected_version"] + 1
                or (body.get("task_id") and receipt.get("task_id") != body["task_id"])
                or (body.get("attempt_id") and receipt.get("attempt_id") != body["attempt_id"])):
            raise Blocked("RECEIPT_MISMATCH")
        if receipt.get("task_id"):
            document = self.read_document(receipt["task_id"], receipt["version"])
            if body["operation"] == "RECONCILE_ATTEMPT" and self.state.get("purpose") == "HOST_RECONCILIATION":
                accepted = next((row for row in document["attempts"] if row["id"] == body["attempt_id"]), None)
                metadata = accepted.get("runtime_metadata", {}) if accepted else {}
                if (not accepted or accepted["status"] != "FAILED"
                        or metadata.get("budget_reservation") != self.state.get("source_budget_reservation")
                        or metadata.get("preparation_budget_reservation") != self.state.get("source_preparation_reservation")):
                    raise Blocked("ORIGINAL_HELD_BUDGET_READBACK_MISMATCH")
        elif body["operation"] == "CONFIGURE":
            rows = self.get(f"/cloud/projects/{self.state['project_id']}/configuration")["items"]
            if not any(row["id"] == receipt["config_id"] and row["revision"] == receipt["version"] for row in rows):
                raise Blocked("CONFIGURATION_READBACK_PENDING")
        write.update(state="READBACK_COMPLETE", receipt=receipt)
        self.persist()
        return receipt

    def reconcile(self, write):
        key = quote(write["request"]["operation_key"], safe="")
        receipt = self.get(f"/cloud/projects/{self.state['project_id']}/operations/{key}")
        return self.verify(write, receipt)

    def mutate(self, name: str, operation: str, expected_version=0, **fields):
        existing = self.state["writes"].get(name)
        if existing:
            if existing["state"] == "REJECTED":
                raise Blocked("ORIGINAL_REQUEST_REJECTED_REVIEW_REQUIRED")
            if existing["state"] == "READBACK_COMPLETE":
                return existing["receipt"]
            return self.reconcile(existing)  # NOT_FOUND never permits another POST.
        if any(row["state"] not in {"READBACK_COMPLETE"} for row in self.state["writes"].values()):
            raise Blocked("ORIGINAL_PENDING_WRITE_BLOCKS_NEW_INTENTION")
        body = TypeAdapter(CloudMutation).validate_python({"project_id": self.state["project_id"],
            "operation": operation, "operation_key": "accept:" + str(uuid4()),
            "expected_version": expected_version, **fields}).model_dump(mode="json")
        write = {"request": body, "state": "SENT"}
        self.state["writes"][name] = write
        self.persist()  # Complete non-secret fixed request precedes its one POST.
        try:
            response = self.client.post("/api/v1/cloud/operations", json=body)
            if response.status_code != 200:
                write["state"] = "REJECTED" if 400 <= response.status_code < 500 else "UNKNOWN"
                self.persist()
                raise Blocked("API_MUTATION_REJECTED" if write["state"] == "REJECTED" else "ORIGINAL_KEY_RECONCILIATION_REQUIRED")
            return self.verify(write, response.json())
        except httpx.HTTPError:
            write["state"] = "UNKNOWN"
            self.persist()
            raise Blocked("ORIGINAL_KEY_RECONCILIATION_REQUIRED") from None

    def project(self):
        project = self.state["project"]
        if project["state"] == "NEW":
            project["state"] = "SENT"
            self.persist()
            try:
                response = self.client.post("/api/v1/projects", json=project["request"])
                if response.status_code != 201:
                    raise Blocked("PROJECT_CREATE_UNCERTAIN")
                candidate = response.json()
            except httpx.HTTPError:
                raise Blocked("PROJECT_CREATE_UNCERTAIN") from None
        else:
            # Project creation has no Cloud receipt: its frozen unique key is the
            # read-only reconciliation target. Absence still does not allow POST.
            matches = [row for row in self.get("/projects") if row["key"] == project["request"]["key"]]
            if len(matches) != 1:
                raise Blocked("PROJECT_CREATE_UNCERTAIN")
            candidate = matches[0]
        if any(candidate.get(key) != value for key, value in project["request"].items()):
            raise Blocked("PROJECT_IDENTITY_MISMATCH")
        verified = self.get("/projects/" + candidate["id"])
        if verified["key"] != project["request"]["key"]:
            raise Blocked("PROJECT_READBACK_MISMATCH")
        project["state"], self.state["project_id"] = "READBACK_COMPLETE", candidate["id"]
        self.persist()

    def prepare(self):
        capabilities = self.get("/cloud/capabilities")
        if capabilities.get("profile") != PROFILE or capabilities.get("enabled") is not True:
            raise Blocked("ISOLATED_CLOUD_ADMISSION_REQUIRED")
        self.project()
        config = self.mutate("configure", "CONFIGURE", configuration={
            "sut": {"url": REPOSITORY, "default_selector": {"kind": "BRANCH", "value": "refs/heads/main"}},
            "framework": {"url": REPOSITORY, "default_selector": {"kind": "BRANCH", "value": "refs/heads/main"}},
            "environment": {"name": "Public sampleproject workspace only", "connection": "NONE"}})
        task = self.mutate("create", "CREATE_TASK", title="Cloud real " + self.state["target"] + " acceptance",
            config_id=config["config_id"], inputs=self.state["task_inputs"])
        self.state["task_id"] = task["task_id"]
        self.persist()
        resolution = self.mutate("resolve", "RESOLVE_INPUTS", task["version"], task_id=task["task_id"])
        return {"stage": "INPUT_RESOLUTION_REQUESTED", "project_id": self.state["project_id"],
            "task_id": task["task_id"], "resolution_id": resolution["resolution_id"], "execution_started": False}

    def dispatch(self):
        capabilities = self.get("/cloud/capabilities")
        if capabilities.get("profile") != PROFILE or capabilities.get("enabled") is not True:
            raise Blocked("ISOLATED_CLOUD_ADMISSION_REQUIRED")
        if "resolve" not in self.state["writes"]:
            raise Blocked("PREPARE_REQUIRED")
        self.reconcile(self.state["writes"]["resolve"])
        document = self.read_document(self.state["task_id"])
        task = document["task"]
        if "dispatch" in self.state["writes"]:
            receipt = self.mutate("dispatch", "DISPATCH")
        else:
            resolution_id = self.state["writes"]["resolve"]["receipt"]["resolution_id"]
            resolution = next((row for row in document["resolutions"] if row["id"] == resolution_id), None)
            if task["status"] != "DRAFT" or not resolution or resolution["status"] != "ACCEPTED" or resolution["accepted_task_version"] != task["version"]:
                raise Blocked("WAITING_FOR_FIXED_INPUT_RESOLUTION")
            expected = self.state["writes"]["create"]["request"]["inputs"]
            if task["inputs"] != expected:
                raise Blocked("TASK_INPUTS_CHANGED")
            self.state["resolved_repositories"] = resolution["result"]["repositories"]
            self.persist()
            receipt = self.mutate("dispatch", "DISPATCH", task["version"], task_id=task["id"], resolution_id=resolution_id)
        return {"stage": "DISPATCH_ACCEPTED", "task_id": receipt["task_id"], "attempt_id": receipt["attempt_id"],
            "version": receipt["version"], "repositories": self.state.get("resolved_repositories"), "model_execution": "NOT_ASSESSED_BY_CONTROLLER"}

    def read_originals(self, document):
        """GET and verify original bytes selected by one fixed accepted document."""
        originals = []
        for artifact in document["artifacts"]:
            if (artifact.get("task_id") != document["task"]["id"]
                    or type(artifact.get("byte_count")) is not int or not 0 <= artifact["byte_count"] <= 8 * 1024 * 1024):
                raise Blocked("ARTIFACT_IDENTITY_MISMATCH")
            offset, pieces = 0, []
            while True:
                page = self.get(f"/cloud/tasks/{self.state['task_id']}/artifacts/{artifact['id']}",
                    project_id=self.state["project_id"], offset=offset, length=65536)
                if page["id"] != artifact["id"] or page["task_id"] != self.state["task_id"] or page["offset"] != offset or page["sha256"] != artifact["sha256"] or page["byte_count"] != artifact["byte_count"]:
                    raise Blocked("ARTIFACT_IDENTITY_MISMATCH")
                raw = base64.b64decode(page["content_base64"], validate=True)
                pieces.append(raw)
                offset += len(raw)
                if page["next_offset"] != offset:
                    raise Blocked("ARTIFACT_READBACK_GAP")
                if page["complete"]:
                    break
                if not raw or offset > 8 * 1024 * 1024:
                    raise Blocked("ARTIFACT_READBACK_LIMIT")
            content = b"".join(pieces)
            if len(content) != artifact["byte_count"] or hashlib.sha256(content).hexdigest() != artifact["sha256"]:
                raise Blocked("ARTIFACT_INTEGRITY_MISMATCH")
            originals.append({"id": artifact["id"], "sha256": artifact["sha256"], "content_utf8": content.decode("utf-8")})
        return originals

    def strict_readback(self, expectation_file: Path):
        raw = private_read(expectation_file, max_bytes=16384)
        expected = NativeAcceptanceExpectation.model_validate_json(raw)
        if (str(expected.task_id) != self.state["task_id"] or str(expected.project_id) != self.state["project_id"]):
            raise Blocked("STRICT_EXPECTATION_TARGET_MISMATCH")
        if any(row["state"] != "READBACK_COMPLETE" for row in self.state["writes"].values()):
            raise Blocked("ORIGINAL_PENDING_KEYS_GET_ONLY")
        # Never ask for latest and then silently replace the accepted version.
        # No mutate/reconcile/POST, SDK, shell or model path is reachable here.
        document = self.read_document(str(expected.task_id), expected.accepted_version)
        originals = self.read_originals(document)
        result = strict_native_acceptance(document, originals, expected)
        readback = {"document": document, "verified_originals": originals}
        result["readback_sha256"] = hashlib.sha256(json.dumps(readback, sort_keys=True,
            ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
        result["expectation_sha256"] = hashlib.sha256(raw).hexdigest()
        result["readback_source"] = "FIXED_VERSION_API_GET_AND_ORIGINAL_BYTES"
        return result

    def readback(self):
        for write in self.state["writes"].values():
            if write["state"] in {"SENT", "UNKNOWN"}:
                self.reconcile(write)
        document = self.read_document(self.state["task_id"])
        originals = self.read_originals(document)
        save(self.path.with_suffix(".readback.json"), {"document": document, "verified_originals": originals})
        task = document["task"]
        summary = self.get(f"/cloud/tasks/{task['id']}/summary", project_id=self.state["project_id"])
        if summary["id"] != task["id"] or summary["project_id"] != task["project_id"] or summary["version"] != task["version"]:
            raise Blocked("LIVE_VERSION_ADVANCED_REREAD_REQUIRED")
        return {"stage": "FIXED_READBACK_OBSERVED", "task_id": task["id"], "version": task["version"],
            "status": summary["status"], "reported_result": task["reported_result"],
            "asset_count": len(document["assets"]), "run_count": len(document["runs"]),
            "delegation_count": len(document["delegations"]), "originals_verified": len(originals),
            "model_execution": "NOT_ASSESSED_BY_CONTROLLER", "test_pass_inferred": False}

    def source_readback(self):
        """Verify original receipts, without changing the source ledger file."""
        writes = self.state.get("source_writes", {})
        if not writes:
            raise Blocked("SOURCE_STATE_REQUIRED")
        for write in writes.values():
            was_complete = write.get("state") == "READBACK_COMPLETE"
            self.reconcile(deepcopy(write))  # GET-only, even for an uncertain source key.
            if not was_complete:
                raise Blocked("SOURCE_LEDGER_READBACK_REQUIRED")
        document = self.read_document(self.state["source_task_id"])
        task = document["task"]
        summary = self.get(f"/cloud/tasks/{task['id']}/summary", project_id=self.state["project_id"])
        if (summary["id"] != task["id"] or summary["project_id"] != task["project_id"]
                or summary["version"] != task["version"]):
            raise Blocked("SOURCE_LIVE_VERSION_MISMATCH")
        attempt = summary.get("current_attempt")
        if (not attempt or attempt.get("id") != task.get("latest_attempt_id")
                or attempt.get("task_id") != task["id"] or attempt.get("project_id") != task["project_id"]
                or attempt.get("checkpoint", {}).get("pending_operation_keys")):
            raise Blocked("SOURCE_ATTEMPT_OR_PENDING_OPERATIONS_UNCONFIRMED")
        self.state["source_readback_complete"] = True
        self.persist()
        return document, summary, attempt

    def reconcile_attempt(self, proof_file: Path | None):
        if self.state.get("purpose") != "HOST_RECONCILIATION":
            raise Blocked("SEPARATE_RECONCILIATION_STATE_REQUIRED")
        if "reconcile" in self.state["writes"]:
            receipt = self.mutate("reconcile", "RECONCILE_ATTEMPT")
        else:
            if proof_file is None:
                raise Blocked("OPERATOR_HOST_PROOF_REQUIRED")
            document, summary, attempt = self.source_readback()
            if summary["status"] != "RECOVERY_REQUIRED" or attempt["status"] != "RECOVERY_REQUIRED":
                raise Blocked("SOURCE_RECOVERY_REQUIRED")
            metadata = attempt.get("runtime_metadata", {})
            if metadata.get("budget_reservation", {}).get("state") != "HELD":
                raise Blocked("ORIGINAL_HELD_BUDGET_REQUIRED")
            raw = private_read(proof_file, max_bytes=65536, owner_uid=os.geteuid())
            proof = HostReconciliationProof.model_validate_json(raw)
            if (str(proof.project_id) != self.state["project_id"]
                    or str(proof.task_id) != self.state["source_task_id"]
                    or str(proof.attempt_id) != attempt["id"]
                    or proof.expected_version != document["task"]["version"]
                    or not proof.observations.strip()):
                raise Blocked("HOST_PROOF_TARGET_OR_VERSION_MISMATCH")
            self.state["host_proof_sha256"] = hashlib.sha256(raw).hexdigest()
            self.state["source_budget_reservation"] = deepcopy(metadata["budget_reservation"])
            self.state["source_preparation_reservation"] = deepcopy(metadata.get("preparation_budget_reservation"))
            self.persist()
            reconciliation = proof.model_dump(mode="json", exclude={
                "profile", "project_id", "task_id", "attempt_id", "expected_version"})
            receipt = self.mutate("reconcile", "RECONCILE_ATTEMPT", proof.expected_version,
                task_id=str(proof.task_id), attempt_id=str(proof.attempt_id), status="FAILED",
                reason="OPERATOR_VERIFIED_STOPPED_FOLLOWUP", reconciliation=reconciliation)
        return {"stage": "OPERATOR_RECONCILIATION_ACCEPTED", "task_id": receipt["task_id"],
            "attempt_id": receipt["attempt_id"], "version": receipt["version"],
            "model_budget_disposition": "KEEP_HELD", "automatic_execution": False}

    def start_followup(self, *, seconds: int, credits: int):
        if self.state.get("purpose") != "FOLLOWUP":
            raise Blocked("SEPARATE_FOLLOWUP_STATE_REQUIRED")
        capabilities = self.get("/cloud/capabilities")
        if capabilities.get("profile") != PROFILE or capabilities.get("enabled") is not True:
            raise Blocked("ISOLATED_CLOUD_ADMISSION_REQUIRED")
        if "create" in self.state["writes"]:
            created = self.mutate("create", "CREATE_TASK")
        else:
            document, summary, attempt = self.source_readback()
            if summary["status"] not in {"COMPLETED", "FAILED", "CANCELLED"} or attempt["status"] not in {"COMPLETED", "FAILED", "CANCELLED"}:
                raise Blocked("SOURCE_MUST_BE_TERMINAL_WITH_ORIGINAL_WRITES_COMPLETE")
            task = document["task"]
            manifest = task.get("frozen_manifest")
            if not manifest or manifest["config_id"] != task["config_id"]:
                raise Blocked("SOURCE_FROZEN_CONFIGURATION_REQUIRED")
            configurations = self.get(f"/cloud/projects/{self.state['project_id']}/configuration")["items"]
            selected = next((row for row in configurations if row["id"] == task["config_id"]), None)
            if not selected or selected["configuration"] != manifest["configuration"]:
                raise Blocked("SOURCE_CONFIGURATION_READBACK_MISMATCH")
            # Only this reviewed public fixture is admitted by this controller.
            repositories = manifest["resolution"]["repositories"]
            if any(repositories[role]["url"] != REPOSITORY for role in ("sut", "framework")):
                raise Blocked("FOLLOWUP_PUBLIC_FIXTURE_REQUIRED")
            if "task_inputs" not in self.state:
                inputs = task_inputs(self.state["target"], seconds=seconds, credits=credits)
                for role in ("sut", "framework"):
                    inputs[role + "_selector"] = {"kind": "SHA", "value": repositories[role]["commit_sha"]}
                self.state["task_inputs"] = inputs
                self.state["source_input_digest"] = task["input_digest"]
                self.state["source_config_id"] = task["config_id"]
                self.persist()
            created = self.mutate("create", "CREATE_TASK", title="Cloud explicit " + self.state["target"] + " follow-up",
                config_id=self.state["source_config_id"], related_task_id=self.state["source_task_id"],
                inputs=self.state["task_inputs"])
        self.state["task_id"] = created["task_id"]
        self.persist()
        resolution = self.mutate("resolve", "RESOLVE_INPUTS", created["version"], task_id=created["task_id"])
        return {"stage": "RELATED_INPUT_RESOLUTION_REQUESTED", "project_id": self.state["project_id"],
            "task_id": created["task_id"], "related_task_id": self.state["source_task_id"],
            "resolution_id": resolution["resolution_id"], "execution_started": False}


def task_inputs(target: str, *, seconds: int, credits: int) -> dict:
    delegation = ("Use the admitted real Codex child tool specifically for test analysis; preserve its exact child identity and host-observed terminal record. Root integrates the analysis and remains responsible for cases, code and execution. "
        if target == "codex" else "DeepSeek root performs the work without external delegation. ")
    prd = ("# Public sampleproject Cloud acceptance\n" + delegation
        + "Read the frozen SUT src/sample/simple.py and the existing unittest tests/test_simple.py. Analyse add_one risks and design meaningful boundary cases; implement new tests in the writable framework checkout, while importing the read-only SUT via PYTHONPATH=/workspace/sut/src. Do not alter SUT source or publish Git changes. "
        + "Execute the actual existing unittest framework; record exact times, exit code, raw report/log bytes, tested tree and case actuals. If a genuine failure occurs, retain its report and explain the correction as a new revision and run; never manufacture a failure or weaken a correct assertion to manufacture PASS. "
        + "Deliver ANALYSIS, DESIGN, CASE, IMPLEMENTATION and REPORT through the supplied exact handoff contract, with complete patch/new-file originals for changed tests. Publish real checkpoints and wait for original receipts before referencing IDs. Complete explicitly with scope/gaps; do not treat SDK idle as completion. Claude, SSH, CI, private SUT and remote writes are excluded.")
    return {"sut_selector": {"kind": "BRANCH", "value": "refs/heads/main"},
        "framework_selector": {"kind": "BRANCH", "value": "refs/heads/main"},
        "prd_markdown": prd, "prd_version": "cloud-public-acceptance/v1", "objective": "Observe a real finite Cloud six-step task on public source",
        "basic_flow": "Resolve exact dual-role source, analyse, design, implement tests, execute unittest and read back original results",
        "test_scope": "Public sampleproject only; no private source, deployment or production writes",
        "framework_entrypoints": [ENTRYPOINT], "expected_outputs": ["ANALYSIS", "DESIGN", "CASE", "IMPLEMENTATION", "REPORT"],
        "authorization": {"targets": [REPOSITORY], "permitted_actions": ["git:read", "framework:execute"],
            "network_targets": [], "side_effect_limits": "Only writable framework tests/artifacts; SUT readonly; no general network or Git writes",
            "expires_at": (datetime.now(UTC) + timedelta(seconds=seconds + 1800)).isoformat()},
        "budgets": {"accounting_unit": "REQUEST_CREDITS", "total_seconds": seconds,
            "total_cost_microunits": credits, "max_attempts": 1, "max_concurrency": 1}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "dispatch", "readback", "strict-readback", "reconcile", "start-followup"))
    parser.add_argument("--acceptance-expectation-file", type=Path)
    parser.add_argument("--api-origin", required=True)
    parser.add_argument("--allow-loopback-http", action="store_true")
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--source-state-file", type=Path)
    parser.add_argument("--host-proof-file", type=Path)
    parser.add_argument("--operator-key-file", type=Path, required=True)
    parser.add_argument("--target", choices=("root", "codex"), default="root")
    parser.add_argument("--seconds", type=int, choices=range(60, 1801), default=900, metavar="60..1800")
    parser.add_argument("--credits", type=int, choices=range(1, 1001), default=48, metavar="1..1000")
    args = parser.parse_args(argv)
    try:
        origin = api_origin(args.api_origin, args.allow_loopback_http)
        path = args.state_file.absolute()
        if path.parent.is_symlink() or path.parent.resolve() != path.parent or path.parent.stat().st_mode & 0o077:
            raise Blocked("PRIVATE_STATE_DIRECTORY_REQUIRED")
        key = private_read(args.operator_key_file).decode().strip()
        if not key or len(key) > 65536 or "\n" in key or "\r" in key:
            raise Blocked("OPERATOR_IDENTITY_UNAVAILABLE")
        if args.source_state_file and args.mode not in {"reconcile", "start-followup"}:
            raise Blocked("SOURCE_STATE_MODE_INVALID")
        if args.host_proof_file and args.mode != "reconcile":
            raise Blocked("HOST_PROOF_MODE_INVALID")
        if args.acceptance_expectation_file and args.mode != "strict-readback":
            raise Blocked("STRICT_EXPECTATION_MODE_INVALID")
        # Strict acceptance opens the existing ledger/lock read-only. It cannot
        # create a ledger, change bookkeeping or emit a local assessment file.
        lock_flags = os.O_RDONLY | os.O_NOFOLLOW if args.mode == "strict-readback" else os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW
        lock = os.open(str(path) + ".lock", lock_flags, 0o600)
        source_lock = None
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if path.exists():
                state = json.loads(private_read(path))
                if state["api_origin"] != origin or state["target"] != args.target or state["operator_fingerprint"] != hashlib.sha256(key.encode()).hexdigest():
                    raise Blocked("ORIGINAL_TARGET_OR_IDENTITY_MISMATCH")
            else:
                if args.mode == "prepare":
                    state = {"profile": STATE_PROFILE, "api_origin": origin, "target": args.target,
                        "operator_fingerprint": hashlib.sha256(key.encode()).hexdigest(), "writes": {},
                        "project": {"state": "NEW", "request": ProjectCreate(key="CLOUDSDK_" + uuid4().hex.upper(), name="Isolated Cloud " + args.target + " acceptance").model_dump(mode="json")},
                        "task_inputs": task_inputs(args.target, seconds=args.seconds, credits=args.credits)}
                elif args.mode in {"reconcile", "start-followup"}:
                    if args.source_state_file is None:
                        raise Blocked("SOURCE_STATE_REQUIRED")
                    source_path = args.source_state_file.absolute()
                    if source_path == path:
                        raise Blocked("SEPARATE_STATE_REQUIRED")
                    source_lock = os.open(str(source_path) + ".lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
                    fcntl.flock(source_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    raw_source = private_read(source_path)
                    source = json.loads(raw_source)
                    if (source.get("profile") != STATE_PROFILE or source.get("api_origin") != origin
                            or source.get("target") not in {"root", "codex"}
                            or (args.mode == "reconcile" and source["target"] != args.target)
                            or source.get("operator_fingerprint") != hashlib.sha256(key.encode()).hexdigest()
                            or not source.get("task_id") or not source.get("project_id")):
                        raise Blocked("ORIGINAL_TARGET_OR_IDENTITY_MISMATCH")
                    state = {"profile": STATE_PROFILE, "api_origin": origin, "target": args.target,
                        "operator_fingerprint": source["operator_fingerprint"], "writes": {},
                        "project_id": source["project_id"], "source_task_id": source["task_id"],
                        "source_target": source["target"],
                        "source_state_sha256": hashlib.sha256(raw_source).hexdigest(),
                        "source_writes": deepcopy(source["writes"]),
                        "purpose": "HOST_RECONCILIATION" if args.mode == "reconcile" else "FOLLOWUP"}
                    if args.mode == "reconcile":
                        state["task_id"] = source["task_id"]
                else:
                    raise Blocked("PREPARE_REQUIRED")
                save(path, state)
            with httpx.Client(base_url=origin, headers={"X-Hypertest-Operator-Key": key}, timeout=30,
                              follow_redirects=False, trust_env=False) as client:
                run = Controller(client, path, state)
                if args.mode == "strict-readback":
                    if args.acceptance_expectation_file is None:
                        raise Blocked("STRICT_EXPECTATION_FILE_REQUIRED")
                    result = run.strict_readback(args.acceptance_expectation_file)
                elif args.mode == "reconcile":
                    result = run.reconcile_attempt(args.host_proof_file)
                elif args.mode == "start-followup":
                    result = run.start_followup(seconds=args.seconds, credits=args.credits)
                else:
                    result = getattr(run, args.mode)()
            print(json.dumps(result, ensure_ascii=False))
            return 1 if result.get("strict_result") == "NON_PASS" else 0
        finally:
            if source_lock is not None:
                os.close(source_lock)
            os.close(lock)
    except Exception as error:
        # No raw HTTP bodies, headers, key material or underlying exceptions.
        print(json.dumps({"status": "BLOCKED", "code": str(error) if isinstance(error, Blocked) else "ACCEPTANCE_CHECK_FAILED"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
