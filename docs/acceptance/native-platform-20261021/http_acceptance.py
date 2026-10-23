"""One-time local HTTP acceptance; never invokes a SUT or replays uncertain writes.

Run phase one and phase two as separate processes. Secrets live only in the
ignored private runtime directory. Reports remain local UNVERIFIED materials.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
RAW = HERE.parent / "native-framework-20261021"
PRIVATE = HERE / "private-runtime"


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value, *, private=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if private:
        path.parent.chmod(0o700)
    content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
    with os.fdopen(fd, "w") as out:
        out.write(content)
    tmp.replace(path)


def public(value):
    if isinstance(value, dict):
        return {k: public(v) for k, v in value.items() if k not in {"writer_token", "writer_token_hash", "operator_key"}}
    if isinstance(value, list):
        return [public(v) for v in value]
    return value


def material(name, kind, format_name):
    content = (RAW / name).read_bytes()
    return {"name": Path(name).name, "kind": kind, "format": format_name,
            "content_base64": base64.b64encode(content).decode(), "sha256": digest(content)}


def prepare(lane):
    inventory = json.loads((RAW / "inventory.json").read_text())
    results = json.loads((RAW / "NATIVE_RESULTS.json").read_text())
    if lane == "xblock":
        ids = inventory["selected_scenarios"]
        case_rows = [(name, name) for name in ids]
        inputs = {
            "sut": {"repository_url": "https://gitlab.charprotocol.com/xblock/xblock-service-asset.git",
                    "source_commit": None, "binary_sha256": inventory["xblock_binary"]["sha256"],
                    "source_association": "UNVERIFIED", "local_changes": "Binary only; no embedded build/source attestation"},
            "framework": {"repository_url": inventory["framework"]["origin"],
                          "commit_sha": inventory["framework"]["commit"], "local_changes": inventory["framework"]["dirty"]},
            "test_assets": [{"path": f["path"], "sha256": f["sha256"]} for f in inventory["asset_files"]],
            "environment": {"Java": "JBR 21.0.10", "Node": "v26.8.1", "execution": "existing loopback fake provider and in-memory chain",
                            "identity_gap": "JAR to source commit UNVERIFIED"},
        }
        report_materials = [material("xblock-scenarios.stdout.jsonl", "REPORT", "CONSUMER_PARITY_JSONL"),
                            material("xblock-scenarios.stderr.log", "STDERR", "TEXT"),
                            material("xblock-scenarios.process.json", "CONTEXT", "TEXT")]
        process_name, framework = "xblock-scenarios.process.json", "existing Java/Node consumer-parity"
    else:
        case_rows = [(f"BC-{i:03}", c["native_id"]) for i, c in enumerate(results["blockchain"]["cases"], 1)]
        source = json.loads((RAW / "blockchain-source.materialization.json").read_text())
        selected = [f for f in source["files"] if "/src/test/" in f["path"] or f["path"].endswith("pom.xml")]
        inputs = {
            "sut": {"repository_url": source["origin"], "source_commit": source["commit"],
                    "source_association": "DECLARED", "local_changes": "Clean checkout; local materialization checked bytewise; platform provenance UNVERIFIED"},
            "framework": {"repository_url": source["origin"], "commit_sha": source["commit"],
                          "local_changes": "No tracked changes; existing Maven/JUnit5 starter tests"},
            "test_assets": [{"path": f["path"], "sha256": f["sha256"]} for f in selected],
            "environment": {"Java": "JBR 21.0.10", "Maven": "3.9.16", "framework": "JUnit5 / MockWebServer / Surefire",
                            "dependency_mode": "offline isolated Maven repository", "network": "local MockWebServer only"},
        }
        report_materials = [material(r["path"], "REPORT", "JUNIT_XML") for r in results["blockchain"]["reports"]]
        report_materials += [material("blockchain-maven-01.stdout.log", "STDOUT", "TEXT"),
                             material("blockchain-maven-01.stderr.log", "STDERR", "TEXT"),
                             material("blockchain-maven-01.process.json", "CONTEXT", "TEXT")]
        process_name, framework = "blockchain-maven-01.process.json", "existing Maven/JUnit5/Surefire"
    process = json.loads((RAW / process_name).read_text())
    inputs.update(environment_variable_names=process["environment_variable_names"],
                  authorization_scope="Local retrospective report intake only; no source/JAR export, production deploy, chain write or issue write",
                  source_transfer="NONE")
    plan_ref = "docs/acceptance/native-framework-20261021/TEST_PLAN.md"
    cases = [{"key": key, "title": f"{lane}: {native_id}", "requirement_ref": plan_ref,
              "risk_ref": plan_ref, "expected_result": "Existing native test assertions pass; negative behavior is classified as the existing test expects",
              "implementation_ref": native_id} for key, native_id in case_rows]
    plan = {"objective": f"Retrospectively govern real {lane} native component results", "scope":
            "Existing component tests only; no live chain/current deployment/full business E2E. This plan is accepted after the observed execution.",
            "requirement_refs": [plan_ref], "risk_refs": [plan_ref], "inputs": inputs, "cases": cases}
    execution = {"command": process["argv"], "cwd": process["cwd"], "framework": framework,
                 "started_at": process["started_at"], "finished_at": process["ended_at"], "exit_code": process["exit_code"],
                 "results": [{"case_key": key, "result": "PASS"} for key, _ in case_rows], "materials": report_materials}
    return plan, execution


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["one", "two", "readback"])
    parser.add_argument("--api", required=True)
    parser.add_argument("--operator-key-file", type=Path, required=True)
    args = parser.parse_args()
    if not args.api.startswith("http://127.0.0.1:"):
        raise SystemExit("Acceptance is restricted to explicit loopback HTTP")
    key_path = args.operator_key_file
    if key_path.stat().st_mode & 0o077:
        raise SystemExit("Operator key requires private permissions")
    operator_key = key_path.read_text().strip()
    events = []

    def request(method, path, payload=None, writer=None, expect=200):
        headers = {"Content-Type": "application/json", "X-Hypertest-Operator-Key": operator_key}
        if writer:
            headers["X-Hypertest-Native-Writer-Key"] = writer
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        try:
            with urlopen(Request(args.api + path, data=data, headers=headers, method=method), timeout=30) as response:
                status, content = response.status, response.read()
        except HTTPError as error:
            status, content = error.code, error.read()
        try:
            result = json.loads(content)
        except ValueError:
            result = {"response_sha256": digest(content), "bytes": len(content)}
        events.append({"time": utc(), "method": method, "path": path, "status": status,
                       "input_sha256": digest(data) if data else None, "result": public(result)})
        save(HERE / f"http-{args.phase}.json", {"client_pid": os.getpid(), "api": args.api, "events": events})
        if status != expect:
            raise RuntimeError(f"{method} {path} returned {status}; expected {expect}; public evidence saved")
        return result

    state_path = PRIVATE / "client-state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    if args.phase == "one":
        if state or (HERE / "http-one.json").exists():
            raise SystemExit("Existing state: use readback, never replay phase one")
        for lane in ["xblock", "blockchain"]:
            project_key = f"NATIVE_{lane.upper()}_20261021"
            plan, execution = prepare(lane)
            # Project POST is attempted once; any failed process must be reconciled.
            project = request("POST", "/projects", {"key": project_key, "name": f"{lane} native QA", "repository_url": plan["inputs"]["sut"]["repository_url"]}, expect=201)
            create = {"profile": "native-framework-intake/v1alpha1", "project_id": project["id"],
                      "idempotency_key": f"{lane}-native-retrospective-20261021", "session_ref": "acceptance-client-A", "plan": plan}
            save(HERE / f"{lane}-accepted-proposal.json", create)
            save(PRIVATE / f"{lane}-create-intent.json", {"status": "SENT", "input_sha256": digest(json.dumps(create, ensure_ascii=False).encode()), "key": create["idempotency_key"]}, private=True)
            receipt = request("POST", "/native-runs", create, expect=201)
            state[lane] = {**receipt, "project_id": project["id"], "create_key": create["idempotency_key"]}
            save(state_path, state, private=True)
            write = {"contributor_id": receipt["contributor_id"], "generation": receipt["generation"]}
            payload = {**write, "idempotency_key": f"{lane}-observed-execution-20261021", **execution}
            save(PRIVATE / f"{lane}-execution-intent.json", {"status": "SENT", "input_sha256": digest(json.dumps(payload, ensure_ascii=False).encode()), "key": payload["idempotency_key"]}, private=True)
            result = request("POST", f"/native-runs/{receipt['run_id']}/executions", payload, receipt["writer_token"], expect=201)
            state[lane]["execution_receipt"] = result
            save(state_path, state, private=True)
            conclusion = request("POST", f"/native-runs/{receipt['run_id']}/evaluate", {**write, "idempotency_key": f"{lane}-gate-initial"}, receipt["writer_token"])
            if conclusion["decision"] != "UNKNOWN":
                raise RuntimeError("All-pass local material must remain UNKNOWN without provenance")
            view = request("GET", f"/native-runs/{receipt['run_id']}")
            save(HERE / f"{lane}-initial-state.json", public(view))
            if len(view["cases"]) != len(plan["cases"]) or len(view["executions"]) != 1:
                raise RuntimeError("Plan/case/execution association was not preserved")
            for mat in view["materials"]:
                body = request("GET", f"/native-runs/{receipt['run_id']}/materials/{mat['id']}")
                original = next((m for m in execution["materials"] if m["name"] == mat["name"]))
                content = base64.b64decode(body["content_base64"])
                if digest(content) != original["sha256"] or len(content) != mat["size_bytes"]:
                    raise RuntimeError("Raw material readback is incomplete or changed")
            # Strip bulk base64 from HTTP evidence; originals and their IDs remain.
            for event in events:
                if isinstance(event["result"], dict) and "content_base64" in event["result"]:
                    event["result"]["content_base64"] = "[original bytes verified; see local raw material]"
            save(HERE / "http-one.json", {"client_pid": os.getpid(), "api": args.api, "events": events})
    elif args.phase == "two":
        if not state:
            raise SystemExit("Phase one state is required")
        for lane, current in state.items():
            if "successor" in current:
                raise SystemExit("Existing successor: query original operation; never replay handoff")
            run_id, old_token = current["run_id"], current["writer_token"]
            view = request("GET", f"/native-runs/{run_id}")
            original_ids = {name: [r["id"] for r in view[name]] for name in ["cases", "executions", "materials", "verifications", "conclusions"]}
            payload = {"contributor_id": current["contributor_id"], "generation": current["generation"],
                       "idempotency_key": f"{lane}-handoff-A-to-B", "successor_session_ref": "acceptance-client-B",
                       "remaining_work": ["Independent provenance remains UNVERIFIED; native CI/PASS/Web/MCP are pending"],
                       "reason": "Explicit sequential contribution handoff between independent HTTP client processes; no claim of native Provider resume"}
            save(PRIVATE / f"{lane}-handoff-intent.json", {"status": "SENT", "key": payload["idempotency_key"]}, private=True)
            successor = request("POST", f"/native-runs/{run_id}/handoffs", payload, expect=201)
            current["successor"] = successor
            save(state_path, state, private=True)
            write = {"contributor_id": successor["contributor_id"], "generation": successor["generation"]}
            request("POST", f"/native-runs/{run_id}/evaluate", {**write, "idempotency_key": f"{lane}-old-capability-new-generation"}, old_token, expect=403)
            response = request("GET", f"/native-runs/{run_id}/operations/{payload['idempotency_key']}")
            if "writer_token" in json.dumps(response) or "writer_token_hash" in json.dumps(response):
                raise RuntimeError("Operation query leaked a capability")
            conclusion = request("POST", f"/native-runs/{run_id}/evaluate", {**write, "idempotency_key": f"{lane}-gate-successor"}, successor["writer_token"])
            if conclusion["decision"] != "UNKNOWN":
                raise RuntimeError("Contribution change must not improve provenance trust")
            after = request("GET", f"/native-runs/{run_id}")
            for name, ids in original_ids.items():
                if not set(ids).issubset({r["id"] for r in after[name]}):
                    raise RuntimeError(f"Handoff lost accepted {name}")
            save(HERE / f"{lane}-post-handoff-state.json", public(after))
        lane, current = "xblock", state["xblock"]
        successor, run_id = current["successor"], current["run_id"]
        write = {"contributor_id": successor["contributor_id"], "generation": successor["generation"]}
        unknown = request("POST", f"/native-runs/{run_id}/uncertainties", {**write, "idempotency_key": "control-only-unknown",
                          "external_operation_ref": "acceptance-control/no-external-request-sent",
                          "reason": "Governance control-path test only; no real external request is made by this acceptance script"}, successor["writer_token"], expect=201)
        request("POST", f"/native-runs/{run_id}/handoffs", {**write, "idempotency_key": "control-only-unknown-handoff",
                    "successor_session_ref": "acceptance-client-C", "remaining_work": ["Reconcile original UNKNOWN"],
                    "reason": "Expected rejection while original operation remains UNKNOWN"}, expect=409)
        blocked = request("POST", f"/native-runs/{run_id}/evaluate", {**write, "idempotency_key": "xblock-gate-unknown-operation"}, successor["writer_token"])
        if blocked["decision"] != "BLOCKED" or "UNRESOLVED_EXTERNAL_OPERATION" not in blocked["reasons"]:
            raise RuntimeError("Unresolved external operation did not block governance")
    else:
        for lane, current in state.items():
            receipt = request("GET", f"/native-runs/submissions/{current['project_id']}/{current['create_key']}")
            if "writer_token" in json.dumps(receipt):
                raise RuntimeError("Readback cannot reissue a secret")
            view = request("GET", f"/native-runs/{current['run_id']}")
            old_token, successor = current["writer_token"], current["successor"]
            write = {"contributor_id": successor["contributor_id"], "generation": successor["generation"]}
            request("POST", f"/native-runs/{current['run_id']}/evaluate",
                    {**write, "idempotency_key": f"{lane}-final-old-capability-probe"}, old_token, expect=403)
            handoff_receipt = request("GET", f"/native-runs/{current['run_id']}/operations/{lane}-handoff-A-to-B")
            if any(secret in json.dumps(handoff_receipt) for secret in ["writer_token", "writer_token_hash"]):
                raise RuntimeError("Original operation query returned secret metadata")
            for mat in view["materials"]:
                body = request("GET", f"/native-runs/{current['run_id']}/materials/{mat['id']}")
                raw = base64.b64decode(body.pop("content_base64"))
                if digest(raw) != mat["sha256"] or len(raw) != mat["size_bytes"]:
                    raise RuntimeError("Final runtime raw material readback failed")
                events[-1]["result"]["content_base64"] = "[original bytes verified; see local raw material]"
            snapshot = request("GET", f"/native-runs/{current['run_id']}/handoffs/{successor['handoff_id']}/state")
            serialized = json.dumps(snapshot["state"], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
            if digest(serialized) != snapshot["state_digest"]:
                raise RuntimeError("Accepted handoff snapshot digest does not match original state")
            save(HERE / f"{lane}-final-state.json", public(view))
        current = state["xblock"]
        successor, run_id = current["successor"], current["run_id"]
        write = {"contributor_id": successor["contributor_id"], "generation": successor["generation"]}
        missing = request("GET", f"/native-runs/{run_id}/operations/nonexistent-control-readback", expect=404)
        raw_lookup = json.dumps({"kind": "LOCAL_GOVERNANCE_CONTROL_ONLY", "query_result": missing,
                                  "explanation": "No external request was sent; this local 404 does not resolve the deliberately registered UNKNOWN.",
                                  "observed_at": utc()}, sort_keys=True).encode()
        proof = {"name": "control-local-404-readback.json", "kind": "CONTEXT", "format": "TEXT",
                 "content_base64": base64.b64encode(raw_lookup).decode(), "sha256": digest(raw_lookup)}
        old_summary_only = {**write, "idempotency_key": "control-summary-only-reconcile", "resolution": "NOT_FOUND",
                            "observed_operation_ref": "acceptance-control/no-external-request-sent", "material": proof,
                            "reason": "Expected rejection: old summary-only payload lacks Operator readback attestation"}
        request("POST", f"/native-runs/{run_id}/uncertainties/control-only-unknown/reconcile", old_summary_only, expect=422)
        payload = {**old_summary_only, "idempotency_key": "control-not-found-reconcile", "attestation": {
            "kind": "EXECUTION_CONTROL_READBACK", "source_ref": f"local-api-control:{run_id}/operations/nonexistent-control-readback",
            "operation_ref": "acceptance-control/no-external-request-sent", "observed_at": utc(), "result": "NOT_FOUND",
            "raw_material_sha256": digest(raw_lookup), "operator_attests_original_readback": True}}
        pending = request("POST", f"/native-runs/{run_id}/uncertainties/control-only-unknown/reconcile", payload)
        if pending["status"] != "UNKNOWN":
            raise RuntimeError("NOT_FOUND must preserve UNKNOWN even with an explicit Operator readback")
        request("POST", f"/native-runs/{run_id}/handoffs", {**write, "idempotency_key": "control-final-unknown-handoff",
                    "successor_session_ref": "acceptance-client-C", "remaining_work": ["Reconcile original UNKNOWN"],
                    "reason": "Expected rejection after NOT_FOUND readback preserves original UNKNOWN"}, expect=409)
        _, duplicate_observation = prepare("xblock")
        request("POST", f"/native-runs/{run_id}/executions", {**write, "idempotency_key": "control-final-unknown-execution",
                    **duplicate_observation}, successor["writer_token"], expect=409)
        operation = request("GET", f"/native-runs/{run_id}/operations/control-only-unknown")
        if operation["status"] != "UNKNOWN":
            raise RuntimeError("Original operation UNKNOWN was lost")
        final = request("GET", f"/native-runs/{run_id}")
        if len(final["executions"]) != 1 or len(final["handoffs"]) != 1 or final["run"]["generation"] != 2:
            raise RuntimeError("Blocked writes changed execution/handoff history")
        save(HERE / "xblock-final-state.json", public(final))
    save(HERE / f"http-{args.phase}.json", {"client_pid": os.getpid(), "api": args.api, "completed_at": utc(), "events": events})
    print(json.dumps({"phase": args.phase, "client_pid": os.getpid(), "http_checks": len(events), "result": "PASS", "formal_evidence": False}))


if __name__ == "__main__":
    main()
