# Remote candidate validation and subsequent upgrade boundary

Date: 2026-10-21, Asia/Singapore. This preserves the initial preparation plan and its then-pending boundaries. Subsequent observed candidate results are recorded in [REMOTE_REPORT.md](REMOTE_REPORT.md); the current concise production decision plan is [FORMAL_UPGRADE_PLAN.md](FORMAL_UPGRADE_PLAN.md). No production release is implied.

## Observed remote baseline

The authorized SSH alias was used with `BatchMode=yes`, `PreferredAuthentications=publickey`, and host-key verification. Production currently runs schema `0020_interactive_tool_inbox`; its interactive capabilities expose the original nine tools and OpenAPI has no new task/native routes. The existing application/operations/Bridge current links remain unchanged. Raw inventory: [remote-inventory.json](remote-inventory.json). A separate preservation baseline records 61 production tables, five containers, current targets and protected configuration metadata: [remote-production-before.json](remote-production-before.json). These hashes establish preservation boundaries, not test execution.

An independent candidate is being prepared at `/opt/hypertest/candidates/session-sync-20261021`; private state is `/var/lib/hypertest-session-sync-candidate-20261021` (0700), with a separate 0600 environment file. Its PostgreSQL database is `hypertest_session_sync_candidate_20261021` with a dedicated non-superuser role. The production database, application authorization and container configuration are not copied or changed. No candidate migration or end-to-end result is claimed by this preparation record.

The existing host CPython 3.12.15 runtime supports a separate candidate virtual environment. Core dependencies were installed using the exact versions observed in the production API image; test/MCP dependencies are confined to the new virtual environment. Host Node 22.23.3 already exists at `/opt/hypertest/node/bin`, although it is absent from the root shell's default PATH. No additional test container or execution engine is needed.

## Candidate validation sequence

1. Wait for the authorization-race and bounded-read/client-correlation fixes to finish. Freeze a new source archive and per-file manifest covering all intended tracked and new files, excluding credentials, `.env`, caches, virtual environments, generated builds and SUT source. The existing preliminary snapshot remains an explicitly identified intermediate artifact.
2. Install the final candidate source in the independent virtual environment. Migrate only the new database first to `0020_interactive_tool_inbox`, capture its state, then advance through the actual final `0021_native_intake` and `0022_session_task_sync` files. Do not `stamp` or use manually replaced functions as migration proof.
3. Run the relevant task API, authorization, client and pagination tests against that remote candidate database. Verify a scoped management-only token cannot use the managed execution path. Preserve raw test output, including failures and subsequent repair runs.
4. Start the candidate API only on `127.0.0.1:18101`, using the independent database/role/operator identity and private artifact/workspace directories. Do not start a candidate Worker, Bridge, Provider or Runner. The real existing Codex task/cases/reports can be synchronized through the new management API/MCP without re-running SUT tests.
5. In the final candidate `web` directory, use the existing host Node runtime for `npm ci`, typecheck, tests and build. Set `HYPERTEST_API_ORIGIN=http://127.0.0.1:18101` during build and startup so the new UI cannot accidentally read the production API. Start it only on `127.0.0.1:13101`.
6. Read back the accepted remote task, its original receipt and raw report content from that candidate. Recheck the formal platform against its independent baseline. Report dynamic heartbeat/node observation differences explicitly; do not normalize unrelated historical or authorization fields.

The existing SSH policy disables forwarding, and production loopback nginx is health-only. The candidate UI is therefore not automatically reachable from the Mac browser. This plan does not open a port, add a proxy route, change TLS/ACL/UFW, or restore an old SSH tunnel. A successful remote build/HTTP check is not a browser interaction result.

## Why existing full-stack scripts are not run directly for the candidate

- `ops/container/build-images.sh` pulls base images including PostgreSQL/nginx and builds API/Worker/Web. Candidate preparation reuses the installed host runtimes and existing PostgreSQL rather than invoking that full-stack build.
- `ops/container/readiness.py` verifies the existing managed platform's Worker/Bridge/Docker capabilities; it is suitable for baseline platform health, not proof that a management-only candidate needs a Runner.
- `ops/container/start.py` manages all original stack roles. It is not used to start or stop the independent candidate.
- `scheduled_backup.py` stops all `start.ROLES`, including PostgreSQL, before its backup sequence. It must not be invoked blindly when the formal change requires PostgreSQL identity/start/restart continuity. The established ADR-016 formal deployment instead kept PostgreSQL running and used a single maintenance lock around its controlled cold application/Bridge window.

## Formal upgrade: separate later action

This candidate does not authorize switching production `current` links, updating images/configuration or migrating the production database. A later formal upgrade needs the concrete candidate results and an explicitly approved maintenance action.

The required production side effects would be: a controlled API admission pause; drain and reconciliation of active/waiting/unknown work; an application/Bridge pause only after safety is established; a new paired backup; isolated restore/migration verification; the production `0020→0021→0022` migration; compatible application/UI activation; and internal readiness/history checks before reopening admission. Retain the original PostgreSQL container/volume, Bridge runtime, OAuth/native sessions, TLS/SSH/VPN rules, existing two managed modes, and every previous result.

`0021` adds eleven native-history tables and guards without importing old execution history. `0022` adds four management tables/guards and widens only the allowed integration-scope constraint to include `task:sync`; it does not grant that scope to existing tokens. The scope-constraint replacement requires a table lock, so this is not the earlier Web-only exception.

Use the existing fixed operations release and the same maintenance flock. A paired backup includes the database, artifacts, workspaces and Bridge state, plus manifest/COMPLETE. Do not copy OAuth secrets; original provider runtime remains on the host. `backup.restore_verify` only restores into a newly named `hypertest_verify_...` database and a new directory, and explicitly does not certify application integrity. Independently compare restored historical rows/relationships/files, then migrate that clone and read representative old reports/verdicts. The complete historical preservation verifier referenced by the old deployment record is not included as a runnable generic script in this repository; it must be located and checked or re-established before formal use.

Software rollback can be considered only with a verified compatible version and known inactive work; the additive schema remains forward. After new management records/grants are accepted, an old binary lacks the new management API and cannot be described as a complete functional rollback. Preserve the new records and use a compatible release or repair forward. Never downgrade, restore an old dump over production, delete volumes/history, or replay unknown writes. Candidate rollback is narrower: stop only its own API/UI processes while retaining its database, source, logs and accepted records.

## Repository evidence

- [SERVER_OPERATIONS.md](../../SERVER_OPERATIONS.md): current SSH/access rules and independently versioned app/ops/Bridge releases.
- [ADR016_PRODUCTION_DEPLOYMENT.md](../../ADR016_PRODUCTION_DEPLOYMENT.md): production preservation, paired backup/clone migration and rollback boundaries.
- [CONTAINERIZED_DEPLOYMENT.md](../../CONTAINERIZED_DEPLOYMENT.md): maintenance locking, backup/restore and rollback procedures.
- [backup.py](../../../ops/container/backup.py), [scheduled_backup.py](../../../ops/container/scheduled_backup.py), [start.py](../../../ops/container/start.py): actual operational behavior and limitations.

Pending facts are the final source identity, actual remote migration/test/build/SDK results, candidate runtime readback and production-after comparison. They must be recorded as observed outcomes rather than inferred from this plan.
