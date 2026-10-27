# Explicit archive manifest

The CLI accepts a UTF-8 JSON file. `profile` below is the wire protocol, separate from the CLI connection's `--profile NAME`. Project and Task IDs are mandatory in both manifest and command. Omit `subtask_id` or set it to null for Task-root archival. When present, it must match the command's `--subtask-id`.

```json
{
  "profile": "local-artifact-archive/v1alpha1",
  "project_id": "00000000-0000-4000-8000-000000000001",
  "task_id": "00000000-0000-4000-8000-000000000002",
  "assets": [
    {
      "kind": "PLAN",
      "stable_key": "checkout-plan",
      "title": "Checkout test plan",
      "path": "./test-plan.md",
      "reported_result": "NOT_RUN",
      "origin": {"producer": "local-agent"}
    },
    {
      "kind": "CASE",
      "stable_key": "checkout-empty-cart",
      "title": "Reject checkout with an empty cart",
      "steps": ["Open an empty cart", "Attempt checkout"],
      "expected": "Checkout is blocked",
      "actual": "Checkout was blocked",
      "reported_result": "PASS",
      "origin": {"origin_provider": "codex"}
    },
    {
      "kind": "REPORT",
      "stable_key": "checkout-run-report",
      "title": "Original checkout test report",
      "path": "./test-results/report.txt",
      "reported_result": "FAIL",
      "origin": {"source_ref": "local-test-run-1"}
    }
  ]
}
```

Paths are explicit regular files, absolute or relative to the manifest directory. The CLI resolves no remote URLs, runs no commands, and expands no globs or directories. It reads approved files once and freezes their exact UTF-8 content before sending. Keep the manifest outside credential, conversation, and reasoning directories. Symlinks and writable-by-other-user files are rejected. Text formats: `.md`, `.markdown`, `.txt`, `.log`, `.json`, `.xml`, `.csv`. Binary files and null bytes are rejected.

PLAN/REPORT require `path`; their content is sent as original text. Optional `artifact_uri` is a reference only. CASE uses inline `steps`, `expected`, `actual`, and optional `implementation_ref`; it does not execute those steps. `reported_result` is one of NOT_RUN, PASS, FAIL, ERROR, SKIPPED, UNKNOWN, BLOCKED. Defaults are NOT_RUN for PLAN/CASE and UNKNOWN for REPORT; preserve a known result explicitly.

`origin` optionally carries `origin_provider`, `origin_session_ref`, `producer`, `source_ref`, `test_started_at`, `test_finished_at`, and `report_created_at`. Timestamp values must include a timezone. Do not attribute every asset to the current uploading session unless that is accurate. Omitted source details stay unknown.

Limits: stable key up to 128 ASCII letters/digits/`_.:-` (starts alphanumeric); title up to 512 characters; each plan/report up to 262144 characters; at most 16 plans, 200 cases, 16 reports per request; at most 100 case steps of 16000 characters each; expected/actual up to 16000 characters; final JSON body at most 2 MiB. Duplicate kind/key pairs are rejected. Do not split or truncate a rejected upload without a new explicit user decision.

Only a SUBTASK target accepts an optional update:

```json
"subtask_update": {"status": "COMPLETED", "reported_result": "FAIL"}
```

Status is DRAFT, IN_PROGRESS, BLOCKED, COMPLETED, or CANCELLED. Include only the fields the user intends to change; null is not a clearing instruction. Task-root uploads cannot update overall task status/result. Overall publication remains an explicit Web operation.

CLI exit codes: 0 success (including an explicitly labeled PREVIEW), 2 invalid local input, 3 explicit server rejection, 4 unresolved or incomplete readback, 5 missing configuration/capability. `status --request-id ID --json` is local; `status --remote` and `reconcile` may query the original server key, never resend it.
