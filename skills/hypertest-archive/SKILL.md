---
name: hypertest-archive
description: Explicitly upload and archive selected completed local test artifacts to HyperTest One through the hypertest CLI. Use when the user invokes this skill or explicitly requests HyperTest archival; a completed test or tool event alone does not invoke it.
---

# HyperTest artifact archive

Use this skill only for an explicit user request to archive. Testing remains independent: do not install Hooks/MCP, observe session lifecycle events, run tests, or continuously synchronize. A phrase such as “当前需求测试完成，请将测试产物上传至 HyperTest” expresses upload intent; it is not an authentication credential.

Obtain the explicit **Project ID**, **Task ID**, and approved artifact files. **Subtask ID is optional**: omission archives directly to the Task, without creating a hidden child. If the required target or file scope is missing, ask only for that information. Do not infer targets from the current directory, a session ID, or the only visible task. Do not create platform tasks on the user's behalf as part of this skill.

Use the globally installed `hypertest` command. `hypertest profile show --json` reveals safe profile metadata. With multiple profiles, require the user-selected server/profile; do not switch identities to make an upload succeed. If authorization is absent, direct the user to the platform's CLI authorization page and its one-command binding instructions. Do not read credential files, ask for tokens, place tokens in commands, or use an Operator key.

Read [the manifest format](references/manifest.md) when preparing an upload. Enumerate only the approved finite set of formal plans, structured test cases, and original UTF-8 reports. Preserve original report text and reported FAIL/ERROR/NOT_RUN. Attribute each asset's source separately when known; provider/session strings are declarations, not verified identity. Do not invent test evidence, extract transcripts/reasoning/tool payloads, or inspect authentication directories. Unsupported binary screenshots/videos/archives must be identified as unsupported, without silently converting or dropping them.

Write a manifest containing the explicit targets and selected files. Use stable asset keys across revisions. This operation upserts the selected complete assets; it does not delete omitted assets. Optional subtask status updates must be explicit and supported by the artifacts; successful transport never implies PASS or overall task completion. Then invoke:

```sh
hypertest archive --project-id PROJECT_UUID --task-id TASK_UUID \
  --manifest /absolute/path/archive-manifest.json --json
```

Add `--profile NAME` for an explicitly selected connection and `--subtask-id SUBTASK_UUID` only when provided. The manifest must carry matching IDs. An explicitly authorized, sufficiently specified upload needs no additional confirmation. Use `--dry-run` only when the user requests a preview; report it as a preview.

Interpret the CLI's non-secret JSON. Report success only for `ARCHIVED` or `UNCHANGED` with `readback_complete: true`; include the task link and submission ID. Preserve the `request_id` in your result for recovery. For `UNKNOWN` or incomplete readback, explain that acceptance is unconfirmed and run only the original request's read-only recovery when requested or needed to finish the same authorized upload:

```sh
hypertest reconcile --request-id ORIGINAL_REQUEST_UUID --json
```

Never retry an uncertain upload with a new request ID, edit its frozen request, change targets, or repeatedly poll after an unresolved read. A successful archive preserves reported test results; it does not certify independently verified evidence or release readiness.
